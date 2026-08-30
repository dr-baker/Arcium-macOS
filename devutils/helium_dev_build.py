"""Guarded, generated-graph build primitives for Helium Dev.

This module deliberately does not decide which sources need compiling.  The
caller supplies explicit Ninja/Siso targets, this module asks the generated
graph whether they exist, and only then invokes Chromium's existing
``autoninja.py`` entrypoint.  Keeping the command construction here makes the
shell facade small while avoiding a second, hand-maintained Chromium link
command.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from threading import Lock, Thread
from typing import Callable, Mapping, Protocol, Sequence


DEFAULT_EDGE_BUDGET = 500
COMPONENT_RELINK_TARGET = "libchrome_dll.dylib"
RESOURCE_RELINK_TARGET = "chrome_app"
FULL_BUILD_TARGETS = ("chrome",)

# Output targets and GN labels use this conservative character set.  The
# generated graph remains the authority on whether a syntactically valid
# target actually exists.
_SAFE_TARGET = re.compile(r"[A-Za-z0-9_./:+=@%,-]+\Z")
_EXPLICITLY_BROAD_TARGETS = frozenset(
    {
        "all",
        "chrome",
        "chromedriver",
        "chrome_app",
        "chrome_framework+link",
        "chrome_dll",
        "libchrome_dll.dylib",
        "default",
    }
)
_EDGE_SUMMARY_PATTERN = re.compile(r"\b([0-9][0-9,]*)\s+(?:edges|actions|commands|steps)\b", re.I)
_EDGE_PROGRESS_PATTERN = re.compile(r"\[\s*[0-9][0-9,]*\s*/\s*([0-9][0-9,]*)\s*\]")
_ACTION_PROGRESS_PATTERN = re.compile(
    r"\[\s*([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)\s*\]"
)
_EDGE_PATTERNS = (_EDGE_SUMMARY_PATTERN, _EDGE_PROGRESS_PATTERN)
_NO_WORK_PATTERN = re.compile(r"(?:ninja|siso):?\s*(?:no work to do|no build steps)\.?", re.I)
_EDGE_PARSER_TAIL = 512


class BuildError(RuntimeError):
    """Base class for a guarded build operation failure."""


class BuildInputError(BuildError):
    """The requested operation is not safe to pass to the build tools."""


class BuildGraphError(BuildError):
    """The active generated graph could not validate an operation."""


class BuildBudgetError(BuildError):
    """A dry run exceeded (or could not establish) its edge budget."""


@dataclass(frozen=True)
class CommandResult:
    """Bounded command output suitable for diagnostics and tests."""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    streamed_edge_count: int | None = None
    streamed_edge_count_ambiguous: bool = False

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


@dataclass(frozen=True)
class _EdgeCountObservation:
    count: int | None
    ambiguous: bool = False


class _EdgeCountParser:
    """Bounded incremental parser for Siso/Ninja dry-run progress output.

    The dry-run can emit many thousands of progress lines.  Keeping only the
    largest complete total from each evidence format lets callers make the
    same conservative budget decision without retaining the full transcript.
    A short tail handles a pattern split across pipe reads; malformed or
    conflicting evidence remains fail-closed.
    """

    def __init__(self) -> None:
        self._tail = ""
        self._last_nonempty_line = ""
        self._summary_max: int | None = None
        self._progress_max: int | None = None
        self._invalid = False

    def feed(self, text: str) -> None:
        if not text:
            return
        combined = self._tail + text
        for pattern, kind in (
            (_EDGE_SUMMARY_PATTERN, "summary"),
            (_EDGE_PROGRESS_PATTERN, "progress"),
        ):
            for match in pattern.finditer(combined):
                try:
                    count = int(match.group(1).replace(",", ""))
                except ValueError:
                    self._invalid = True
                    continue
                if kind == "summary":
                    self._summary_max = max(self._summary_max or 0, count)
                else:
                    self._progress_max = max(self._progress_max or 0, count)

        for line in combined.splitlines():
            stripped = line.strip()
            self._last_nonempty_line = stripped if stripped and len(stripped) <= _EDGE_PARSER_TAIL else ""
        self._tail = combined[-_EDGE_PARSER_TAIL:]

    def observe(self) -> _EdgeCountObservation:
        candidates = tuple(
            count for count in (self._summary_max, self._progress_max) if count is not None
        )
        if candidates:
            count = max(candidates)
        elif _NO_WORK_PATTERN.fullmatch(self._last_nonempty_line):
            count = 0
        else:
            count = None
        # A progress denominator and an explicit summary should agree.  If
        # they do not, choosing one would turn ambiguous diagnostics into a
        # build decision, so retain the maximum only as evidence and mark it
        # unsafe for the caller.
        ambiguous = self._invalid or (
            self._summary_max is not None
            and self._progress_max is not None
            and self._summary_max != self._progress_max
        )
        return _EdgeCountObservation(count=count, ambiguous=ambiguous)


class CommandRunner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        progress_total: int | None = None,
    ) -> CommandResult:
        """Run one argv command without a shell."""


@dataclass(frozen=True)
class BuildPaths:
    """The existing generated build environment owned by one worktree."""

    source_dir: Path
    out_dir: Path
    siso_path: Path
    autoninja_path: Path
    python_path: str = sys.executable

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_dir", Path(self.source_dir).resolve())
        object.__setattr__(self, "out_dir", Path(self.out_dir).resolve())
        object.__setattr__(self, "siso_path", Path(self.siso_path).resolve())
        object.__setattr__(self, "autoninja_path", Path(self.autoninja_path).resolve())

    def validate(self) -> None:
        missing = [
            name
            for name, path in (
                ("source directory", self.source_dir),
                ("output directory", self.out_dir),
                ("Siso executable", self.siso_path),
                ("autoninja.py", self.autoninja_path),
            )
            if not path.exists()
        ]
        if missing:
            raise BuildInputError("missing active generated build input: " + ", ".join(missing))
        if not self.source_dir.is_dir() or not self.out_dir.is_dir():
            raise BuildInputError("source and output inputs must be directories")
        try:
            self.out_dir.relative_to(self.source_dir)
        except ValueError as error:
            raise BuildInputError("output directory must be inside the source directory") from error


@dataclass(frozen=True)
class ArtifactStatus:
    """A hook result supplied by the launcher/runtime layer after a relink."""

    artifact_state: str = "unverified"
    running_process_stale: bool | None = None
    warnings: tuple[str, ...] = ()


ArtifactStatusProbe = Callable[[], ArtifactStatus]


@dataclass(frozen=True)
class BuildResult:
    """Structured, privacy-safe outcome for a facade to render or serialize."""

    ok: bool
    action: str
    targets: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    edge_count: int | None = None
    proof_gates: tuple[str, ...] = ()
    artifact_state: str = "unverified"
    running_process_stale: bool | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "action": self.action,
            "targets": list(self.targets),
            "commands": [list(command) for command in self.commands],
            "edge_count": self.edge_count,
            "proof_gates": list(self.proof_gates),
            "artifact_state": self.artifact_state,
            "running_process_stale": self.running_process_stale,
            "warnings": list(self.warnings),
            "error": self.error,
        }


def normalize_targets(targets: Sequence[str]) -> tuple[str, ...]:
    """Validate and de-duplicate explicit graph targets without inferring any."""

    if not targets:
        raise BuildInputError("at least one explicit generated-graph target is required")

    normalized: list[str] = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, str):
            raise BuildInputError("build targets must be strings")
        is_gn_label = target.startswith("//")
        if (
            not target
            or target.startswith("-")
            or (target.startswith("/") and not is_gn_label)
            or ".." in target
            or not _SAFE_TARGET.fullmatch(target)
        ):
            raise BuildInputError(f"unsafe generated-graph target: {target!r}")
        if target not in seen:
            normalized.append(target)
            seen.add(target)
    return tuple(normalized)


def _is_broad_compile_target(target: str) -> bool:
    """Reject aliases that can schedule a component or full-browser build.

    ``compile`` accepts explicit generated object targets.  GN labels and
    component aliases have too much fan-out to be a safe shorthand here;
    callers can inspect them with ``build-plan`` and use ``relink`` instead.
    """

    lower = target.lower()
    return (
        lower in _EXPLICITLY_BROAD_TARGETS
        or lower.startswith("//")
        or ":" in lower
        or lower.rsplit("/", 1)[-1] in {"chrome_dll", "libchrome_dll.dylib"}
    )


def parse_dry_run_edge_count(output: str) -> int | None:
    """Return Siso/Ninja's planned edge total, or ``None`` when unprovable."""

    parser = _EdgeCountParser()
    parser.feed(output)
    observation = parser.observe()
    return None if observation.ambiguous else observation.count


def parse_siso_query_commands(output: str) -> tuple[str, ...]:
    """Extract non-empty generated command records without executing them.

    Siso has emitted both raw command lines and ``command =`` records across
    versions.  We retain either form only as graph evidence; actual execution
    remains through autoninja with explicit target argv.
    """

    commands: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        lower_line = line.lower()
        if not line or lower_line.startswith(("target:", "rule:", "ninja: entering", "siso:")):
            continue
        if "no commands" in lower_line or "unknown target" in lower_line:
            continue
        if line.startswith("command ="):
            line = line.partition("=")[2].strip()
        elif line.lower().startswith("command:"):
            line = line.partition(":")[2].strip()
        if line:
            commands.append(line)
    return tuple(commands)


def subprocess_runner(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float | None = None,
    max_output_bytes: int = 64 * 1024,
    progress_total: int | None = None,
) -> CommandResult:
    """Run safely while draining pipes and retaining only bounded diagnostics."""

    argv = tuple(str(arg) for arg in args)
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    retained: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    parsers = {"stdout": _EdgeCountParser(), "stderr": _EdgeCountParser()}
    progress_lock = Lock()
    progress_completed = 0
    progress_bucket = -1

    def report_progress(text: str) -> None:
        nonlocal progress_completed, progress_bucket
        if progress_total is None or progress_total <= 0:
            return
        matches = tuple(_ACTION_PROGRESS_PATTERN.finditer(text))
        if not matches:
            return
        with progress_lock:
            for match in matches:
                completed = int(match.group(1).replace(",", ""))
                reported_total = int(match.group(2).replace(",", ""))
                if reported_total != progress_total or completed <= progress_completed:
                    continue
                progress_completed = completed
                percent = min(100.0, 100.0 * progress_completed / progress_total)
                bucket = int(percent)
                if bucket <= progress_bucket:
                    continue
                progress_bucket = bucket
                print(
                    f"build progress: {percent:.1f}% "
                    f"({progress_completed:,}/{progress_total:,} actions)",
                    file=sys.stderr,
                    flush=True,
                )

    def drain(name: str, pipe: object) -> None:
        assert hasattr(pipe, "read")
        progress_tail = ""
        while True:
            chunk = pipe.read(8192)  # type: ignore[union-attr]
            if not chunk:
                return
            decoded = chunk.decode("utf-8", errors="replace")
            parsers[name].feed(decoded)
            progress_text = progress_tail + decoded
            report_progress(progress_text)
            progress_tail = progress_text[-_EDGE_PARSER_TAIL:]
            remaining = max_output_bytes - len(retained[name])
            if remaining > 0:
                retained[name].extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated[name] = True

    stdout_thread = Thread(target=drain, args=("stdout", proc.stdout), daemon=True)
    stderr_thread = Thread(target=drain, args=("stderr", proc.stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    try:
        returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            returncode = proc.wait()
    stdout_thread.join()
    stderr_thread.join()
    # Thread readers reached EOF; close the Python wrappers promptly so test
    # suites and long-lived facades do not retain descriptor warnings.
    assert proc.stdout is not None
    assert proc.stderr is not None
    proc.stdout.close()
    proc.stderr.close()
    observations = tuple(parsers[name].observe() for name in ("stdout", "stderr"))
    observed_counts = tuple(observation.count for observation in observations if observation.count is not None)
    streamed_edge_count = max(observed_counts) if observed_counts else None
    streamed_edge_count_ambiguous = any(observation.ambiguous for observation in observations)
    if len(set(observed_counts)) > 1:
        streamed_edge_count_ambiguous = True
    return CommandResult(
        args=argv,
        returncode=124 if timed_out else returncode,
        stdout=retained["stdout"].decode("utf-8", errors="replace"),
        stderr=retained["stderr"].decode("utf-8", errors="replace"),
        timed_out=timed_out,
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
        streamed_edge_count=streamed_edge_count,
        streamed_edge_count_ambiguous=streamed_edge_count_ambiguous,
    )


@dataclass
class HeliumDevBuilder:
    """Generated-graph build coordinator with an injectable command runner."""

    paths: BuildPaths
    runner: CommandRunner = subprocess_runner
    edge_budget: int = DEFAULT_EDGE_BUDGET
    _commands: list[tuple[str, ...]] = field(default_factory=list, init=False)

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["SISO_PATH"] = str(self.paths.siso_path)
        environment.setdefault("LC_ALL", "C")
        return environment

    def _reset_commands(self) -> None:
        self._commands.clear()

    def _run(
        self,
        args: Sequence[str],
        *,
        progress_total: int | None = None,
    ) -> CommandResult:
        argv = tuple(str(arg) for arg in args)
        self._commands.append(argv)
        return self.runner(
            argv,
            cwd=self.paths.source_dir,
            env=self._environment(),
            progress_total=progress_total,
        )

    def _result(
        self,
        *,
        ok: bool,
        action: str,
        targets: tuple[str, ...],
        edge_count: int | None = None,
        proof_gates: Sequence[str] = (),
        artifact_status: ArtifactStatus = ArtifactStatus(),
        warnings: Sequence[str] = (),
        error: str | None = None,
    ) -> BuildResult:
        return BuildResult(
            ok=ok,
            action=action,
            targets=targets,
            commands=tuple(self._commands),
            edge_count=edge_count,
            proof_gates=tuple(proof_gates),
            artifact_state=artifact_status.artifact_state,
            running_process_stale=artifact_status.running_process_stale,
            warnings=tuple(warnings) + artifact_status.warnings,
            error=error,
        )

    def _prepare(self, targets: Sequence[str]) -> tuple[str, ...]:
        self.paths.validate()
        if self.edge_budget < 0:
            raise BuildInputError("edge budget must be zero or greater")
        return normalize_targets(targets)

    def _siso_query(self, kind: str, target: str) -> CommandResult:
        result = self._run((self.paths.siso_path, "query", kind, "-C", self.paths.out_dir, target))
        if result.returncode != 0:
            raise BuildGraphError(f"generated graph rejected target {target!r} while querying {kind}")
        return result

    def validate_graph_targets(self, targets: Sequence[str]) -> tuple[str, ...]:
        """Prove each explicit target exists in the active generated graph."""

        normalized = self._prepare(targets)
        for target in normalized:
            result = self._siso_query("rule", target)
            if not result.output.strip():
                raise BuildGraphError(f"generated graph returned no rule for target {target!r}")
        return normalized

    def query_commands(self, target: str) -> tuple[str, ...]:
        """Inspect a generated command record, never execute its shell text."""

        normalized = self._prepare((target,))
        result = self._siso_query("commands", normalized[0])
        commands = parse_siso_query_commands(result.output)
        if not commands:
            raise BuildGraphError(f"generated graph returned no command for target {target!r}")
        return commands

    def query_inputs(self, target: str) -> tuple[str, ...]:
        """Require generated graph inputs before a component/link operation."""

        normalized = self._prepare((target,))
        result = self._siso_query("inputs", normalized[0])
        inputs = tuple(line.strip() for line in result.output.splitlines() if line.strip())
        if not inputs:
            raise BuildGraphError(f"generated graph returned no inputs for target {target!r}")
        return inputs

    def _autoninja_command(self, targets: Sequence[str], *, dry_run: bool) -> tuple[str, ...]:
        args: list[str] = [
            self.paths.python_path,
            str(self.paths.autoninja_path),
            "-k",
            "0",
            "-C",
            str(self.paths.out_dir),
        ]
        if dry_run:
            args.append("-n")
        args.extend(targets)
        return tuple(args)

    def _dry_run(self, targets: tuple[str, ...]) -> int:
        explain_before = {
            path: path.stat().st_mtime_ns for path in self.paths.out_dir.glob("siso_explain*") if path.is_file()
        }
        result = self._run(self._autoninja_command(targets, dry_run=True))
        if result.returncode != 0:
            raise BuildGraphError("autoninja dry-run failed; refusing to build")
        if result.streamed_edge_count_ambiguous:
            raise BuildBudgetError("dry-run reported conflicting edge totals; refusing to build")
        if (
            (result.stdout_truncated or result.stderr_truncated)
            and result.streamed_edge_count is None
        ):
            raise BuildBudgetError(
                "dry-run diagnostics were truncated before a recognizable edge count was observed; refusing to build"
            )
        fresh_explains = [
            path for path in self.paths.out_dir.glob("siso_explain*")
            if path.is_file() and path.stat().st_mtime_ns != explain_before.get(path)
        ]
        if not fresh_explains:
            raise BuildBudgetError("dry-run did not produce a fresh Siso explain record; refusing to build")
        explain = max(fresh_explains, key=lambda path: path.stat().st_mtime_ns)
        explain_text = explain.read_bytes()[:64 * 1024].decode("utf-8", errors="replace")
        if re.search(r"(?:build\.ninja(?:\.stamp)?|args\.gn|toolchain(?:\.ninja)?)\b.*\b(?:older than|stale)", explain_text, re.I):
            raise BuildBudgetError("dry-run used a stale generated graph; regenerate it before building")
        edge_count = result.streamed_edge_count
        if edge_count is None:
            edge_count = parse_dry_run_edge_count(result.output)
        if edge_count is None:
            raise BuildBudgetError("dry-run did not report a recognizable edge count; refusing to build")
        if edge_count > self.edge_budget:
            raise BuildBudgetError(
                f"dry-run planned {edge_count} edges, above configured budget {self.edge_budget}; refusing to build"
            )
        return edge_count

    def build_plan(self, targets: Sequence[str]) -> BuildResult:
        """Validate explicit graph targets then produce an authoritative dry-run plan."""

        self._reset_commands()
        normalized: tuple[str, ...] = ()
        try:
            normalized = self.validate_graph_targets(targets)
            edge_count = self._dry_run(normalized)
        except BuildError as error:
            return self._result(ok=False, action="build-plan", targets=normalized, error=str(error))
        return self._result(
            ok=True,
            action="build-plan",
            targets=normalized,
            edge_count=edge_count,
            proof_gates=("generated-graph-validated", "autoninja-dry-run", "edge-budget-checked"),
        )

    def _execute_planned(self, action: str, plan: BuildResult, *, proof_gates: Sequence[str]) -> BuildResult:
        if plan.edge_count == 0:
            return self._result(
                ok=True,
                action=action,
                targets=plan.targets,
                edge_count=0,
                proof_gates=tuple(plan.proof_gates) + ("no-work-plan",),
                warnings=("dry-run reported no work; build was not executed",),
            )
        result = self._run(
            self._autoninja_command(plan.targets, dry_run=False),
            progress_total=plan.edge_count,
        )
        if result.returncode != 0:
            detail = "autoninja build failed"
            if result.timed_out:
                detail = "autoninja build timed out"
            return self._result(
                ok=False,
                action=action,
                targets=plan.targets,
                edge_count=plan.edge_count,
                proof_gates=plan.proof_gates,
                error=detail,
            )
        warnings: list[str] = []
        if result.stdout_truncated or result.stderr_truncated:
            warnings.append("build diagnostics were truncated")
        return self._result(
            ok=True,
            action=action,
            targets=plan.targets,
            edge_count=plan.edge_count,
            proof_gates=tuple(plan.proof_gates) + tuple(proof_gates),
            warnings=warnings,
        )

    def compile(self, targets: Sequence[str]) -> BuildResult:
        """Compile caller-selected narrow targets after a guarded dry run."""

        try:
            normalized = normalize_targets(targets)
        except BuildError as error:
            return BuildResult(ok=False, action="compile", error=str(error))
        broad = sorted(target for target in normalized if _is_broad_compile_target(target))
        if broad:
            return BuildResult(
                ok=False,
                action="compile",
                targets=normalized,
                error="compile only accepts focused targets; use relink or build-full for " + ", ".join(broad),
            )
        plan = self.build_plan(normalized)
        if not plan.ok:
            return replace(plan, action="compile", warnings=("compile was not started",))
        return self._execute_planned("compile", plan, proof_gates=("focused-compile",))

    def relink(
        self,
        *,
        resources: bool = False,
        artifact_status_probe: ArtifactStatusProbe | None = None,
    ) -> BuildResult:
        """Relink an existing component bundle from current generated targets."""

        target = RESOURCE_RELINK_TARGET if resources else COMPONENT_RELINK_TARGET
        self._reset_commands()
        try:
            self.validate_graph_targets((target,))
            self.query_inputs(target)
            self.query_commands(target)
            edge_count = self._dry_run((target,))
        except BuildError as error:
            return self._result(ok=False, action="relink", targets=(target,), error=str(error))

        plan = self._result(
            ok=True,
            action="relink",
            targets=(target,),
            edge_count=edge_count,
            proof_gates=(
                "generated-graph-validated",
                "generated-link-inputs-inspected",
                "generated-link-command-inspected",
                "autoninja-dry-run",
                "edge-budget-checked",
            ),
        )
        result = self._execute_planned(
            "relink",
            plan,
            proof_gates=(("bundle-resources-relinked",) if resources else ("component-relinked",)),
        )
        if not result.ok or artifact_status_probe is None:
            return result
        try:
            status = artifact_status_probe()
        except Exception as error:  # The build succeeded; runtime proof is separately unverified.
            return replace(
                result,
                warnings=result.warnings + (f"artifact freshness probe failed: {error}",),
            )
        return replace(
            result,
            artifact_state=status.artifact_state,
            running_process_stale=status.running_process_stale,
            warnings=result.warnings + status.warnings,
        )

    def build_full(self, *, approved: bool) -> BuildResult:
        """Run an intentionally broad full build only after an explicit approval bit."""

        if approved is not True:
            return BuildResult(
                ok=False,
                action="build-full",
                targets=FULL_BUILD_TARGETS,
                error="build-full requires explicit approved=True",
            )
        plan = self.build_plan(FULL_BUILD_TARGETS)
        if not plan.ok:
            return replace(plan, action="build-full", warnings=("full build was not started",))
        return self._execute_planned("build-full", plan, proof_gates=("full-build",))
