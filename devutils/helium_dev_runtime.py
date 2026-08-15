"""Small, stdlib-only primitives behind the worktree-aware ``he`` harness.

This module deliberately does not launch Chromium or invoke a build.  Keeping
the state and process safety rules here lets the shell facade be thin and makes
the dangerous parts straightforward to test without a browser installation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import tempfile
import time
import uuid
import fcntl
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_PROFILE_DIRECTORY = "Default"
DEFAULT_DEV_FLAGS = (
    "--enable-ui-devtools",
    "--use-mock-keychain",
    "--no-first-run",
    "--disable-session-crashed-bubble",
    "--disable-features=DialMediaRouteProvider",
)
MANIFEST_FIELDS = (
    "schema_version",
    "ok",
    "run_id",
    "action",
    "main_pid",
    "process_count",
    "started_at",
    "worktree",
    "source_dir",
    "app_path",
    "executable_path",
    "profile_mode",
    "user_data_dir",
    "profile_directory",
    "mock_keychain",
    "quilt_top",
    "component_path",
    "component_sha256",
    "component_mtime",
    "artifact_state",
    "manifest_path",
    "warnings",
)
_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class RuntimeInputError(ValueError):
    """The command would create an ambiguous or unsafe runtime scope."""


class LockBusyError(RuntimeError):
    """The requested profile is already reserved by a live harness action."""


@dataclass(frozen=True)
class ProfileSpec:
    mode: str
    name: str | None
    user_data_dir: Path
    profile_directory: str = DEFAULT_PROFILE_DIRECTORY

    @property
    def key(self) -> str:
        return self.mode if self.name is None else "%s--%s" % (self.mode, self.name)


@dataclass(frozen=True)
class RuntimeArguments:
    profile_mode: str
    profile_name: str | None
    profile_directory: str
    passthrough: tuple[str, ...]


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    command: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ProcessCohort:
    records: tuple[ProcessRecord, ...]
    main_pid: int | None
    reason: str | None = None

    @property
    def process_count(self) -> int:
        return len(self.records)

    @property
    def pids(self) -> tuple[int, ...]:
        return tuple(record.pid for record in self.records)


@dataclass(frozen=True)
class StopPlan:
    main_pid: int
    pids: tuple[int, ...]


def default_registry_root(home: str | os.PathLike[str] | None = None) -> Path:
    """Return the one machine-wide, privacy-safe runtime registry root."""

    home_path = Path.home() if home is None else Path(home)
    return home_path / "Library" / "Application Support" / "Helium Development"


def _application_support(home: str | os.PathLike[str] | None) -> Path:
    home_path = Path.home() if home is None else Path(home)
    return home_path / "Library" / "Application Support"


def normalize_profile_name(name: str) -> str:
    """Accept one portable path segment and reject traversal or aliases."""

    if not isinstance(name, str):
        raise RuntimeInputError("profile name must be a string")
    value = name.strip()
    if value != name or not _PROFILE_NAME.fullmatch(value) or value in {".", ".."}:
        raise RuntimeInputError(
            "profile name must be 1-64 ASCII letters, digits, '.', '_' or '-', "
            "and must not contain whitespace or path separators"
        )
    return value


def normalize_profile_directory(name: str) -> str:
    """Validate Chromium's profile-directory value as one harmless segment."""

    return normalize_profile_name(name)


def resolve_profile(
    mode: str = "normal",
    name: str | None = None,
    *,
    home: str | os.PathLike[str] | None = None,
    profile_directory: str = DEFAULT_PROFILE_DIRECTORY,
) -> ProfileSpec:
    """Resolve a profile without creating it.

    ``normal`` is intentionally the historic persistent Dev profile.  Named
    isolated and fresh profiles live below the harness registry parent, never
    below the release profile.  ``fresh`` creation is enforced by
    :func:`prepare_profile`.
    """

    if mode not in {"normal", "isolated", "fresh"}:
        raise RuntimeInputError("unknown profile mode: %s" % mode)
    profile_directory = normalize_profile_directory(profile_directory)
    support = _application_support(home)
    if mode == "normal":
        if name is not None:
            raise RuntimeInputError("normal mode does not accept a profile name")
        user_data_dir = support / "net.imput.helium.dev"
    else:
        if name is None:
            raise RuntimeInputError("--%s requires a profile name" % mode)
        safe_name = normalize_profile_name(name)
        user_data_dir = support / "Helium Development" / "profiles" / mode / safe_name
        name = safe_name
    return ProfileSpec(mode, name, user_data_dir, profile_directory)


def prepare_profile(spec: ProfileSpec, *, allow_existing_fresh: bool = False) -> ProfileSpec:
    """Create a profile without ever following a selected profile symlink."""

    path = spec.user_data_dir
    if path.is_symlink():
        raise RuntimeInputError("profile path must not be a symlink: %s" % path)
    if path.exists() and not path.is_dir():
        raise RuntimeInputError("profile path is not a directory: %s" % path)
    if spec.mode == "fresh":
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            if not allow_existing_fresh or path.is_symlink() or not path.is_dir():
                raise RuntimeInputError("fresh profile already exists: %s" % path) from exc
    else:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return spec


def _option_value(argv: Sequence[str], index: int, option: str) -> tuple[str, int] | None:
    argument = argv[index]
    if argument == option:
        if index + 1 >= len(argv):
            raise RuntimeInputError("%s needs a value" % option)
        return argv[index + 1], index + 1
    prefix = option + "="
    if argument.startswith(prefix):
        return argument[len(prefix) :], index
    return None


def parse_runtime_arguments(argv: Sequence[str]) -> RuntimeArguments:
    """Separate profile controls from Chromium arguments and reject ambiguity.

    The facade owns both Chromium profile switches so callers cannot
    accidentally split one registry key across several profile directories or
    point a Dev executable at the release profile.
    """

    modes: list[tuple[str, str]] = []
    user_data_dirs = 0
    profile_directories = 0
    passthrough: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        matched = False
        for option, mode in (("--isolated", "isolated"), ("--fresh", "fresh")):
            value = _option_value(argv, index, option)
            if value is not None:
                modes.append((mode, normalize_profile_name(value[0])))
                index = value[1]
                matched = True
                break
        if matched:
            index += 1
            continue
        value = _option_value(argv, index, "--user-data-dir")
        if value is not None:
            user_data_dirs += 1
            index = value[1] + 1
            continue
        value = _option_value(argv, index, "--profile-directory")
        if value is not None:
            profile_directories += 1
            index = value[1] + 1
            continue
        passthrough.append(argument)
        index += 1
    if user_data_dirs:
        raise RuntimeInputError(
            "--user-data-dir is owned by he; use --isolated NAME or --fresh NAME"
        )
    if len(modes) > 1:
        raise RuntimeInputError("choose exactly one profile mode")
    if profile_directories:
        raise RuntimeInputError("--profile-directory is owned by he and fixed to Default")
    mode, name = modes[0] if modes else ("normal", None)
    profile_directory = DEFAULT_PROFILE_DIRECTORY
    return RuntimeArguments(mode, name, profile_directory, tuple(passthrough))


def launch_arguments(spec: ProfileSpec, passthrough: Iterable[str] = ()) -> tuple[str, ...]:
    """Build the fixed Dev flags plus a selected profile scope."""

    return (
        "--user-data-dir=%s" % spec.user_data_dir,
        "--profile-directory=%s" % spec.profile_directory,
        *DEFAULT_DEV_FLAGS,
        *tuple(passthrough),
    )


def registry_paths(
    root: str | os.PathLike[str] | None = None,
    *,
    home: str | os.PathLike[str] | None = None,
) -> dict[str, Path]:
    registry = default_registry_root(home) if root is None else Path(root)
    runs = registry / "runs"
    locks = registry / "locks"
    for directory in (registry, runs, locks):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    return {"root": registry, "runs": runs, "locks": locks}


def manifest_path_for(spec: ProfileSpec, root: str | os.PathLike[str] | None = None) -> Path:
    return registry_paths(root)["runs"] / (spec.key + ".json")


def lock_path_for(spec: ProfileSpec, root: str | os.PathLike[str] | None = None) -> Path:
    return registry_paths(root)["locks"] / (spec.key + ".lock")


def _read_json(path: Path) -> Mapping[str, object] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


@dataclass
class ProfileLock:
    path: Path
    run_id: str
    pid: int
    descriptor: int

    def release(self) -> bool:
        """Release the advisory lock without racing a new owner into deletion."""

        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
        except OSError:
            return False
        return True


def acquire_profile_lock(
    spec: ProfileSpec,
    *,
    root: str | os.PathLike[str] | None = None,
    run_id: str | None = None,
    pid: int | None = None,
    started_at: float | None = None,
) -> ProfileLock:
    """Atomically reserve one profile, replacing stale owner metadata safely."""

    path = lock_path_for(spec, root)
    actual_pid = os.getpid() if pid is None else pid
    actual_run_id = uuid.uuid4().hex if run_id is None else run_id
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile": spec.key,
        "pid": actual_pid,
        "run_id": actual_run_id,
        "started_at": time.time() if started_at is None else started_at,
    }
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockBusyError("profile is already locked: %s" % spec.key) from error
        # A lock file can outlive its holder; the advisory lock says whether it
        # is live.  Once held, atomically replace the former owner metadata.
        os.fchmod(descriptor, 0o600)
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.ftruncate(descriptor, 0)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
        return ProfileLock(path, actual_run_id, actual_pid, descriptor)
    except BaseException:
        os.close(descriptor)
        raise


def build_manifest(
    *,
    ok: bool,
    run_id: str,
    action: str,
    main_pid: int | None,
    process_count: int,
    started_at: str | None,
    worktree: str | os.PathLike[str] | None,
    source_dir: str | os.PathLike[str] | None,
    app_path: str | os.PathLike[str] | None,
    executable_path: str | os.PathLike[str] | None,
    profile: ProfileSpec,
    quilt_top: str | os.PathLike[str] | None = None,
    component_path: str | os.PathLike[str] | None = None,
    component_sha256: str | None = None,
    component_mtime: float | None = None,
    artifact_state: str = "unverified",
    manifest_path: str | os.PathLike[str] | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, object]:
    """Build the fixed privacy-safe manifest schema without process details."""

    if started_at is not None and not isinstance(started_at, str):
        raise RuntimeInputError("started_at must be an ISO-8601 string or null")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(ok),
        "run_id": run_id,
        "action": action,
        "main_pid": main_pid,
        "process_count": int(process_count),
        "started_at": started_at,
        "worktree": None if worktree is None else str(worktree),
        "source_dir": None if source_dir is None else str(source_dir),
        "app_path": None if app_path is None else str(app_path),
        "executable_path": None if executable_path is None else str(executable_path),
        "profile_mode": profile.mode,
        "user_data_dir": str(profile.user_data_dir),
        "profile_directory": profile.profile_directory,
        "mock_keychain": True,
        "quilt_top": None if quilt_top is None else str(quilt_top),
        "component_path": None if component_path is None else str(component_path),
        "component_sha256": component_sha256,
        "component_mtime": component_mtime,
        "artifact_state": artifact_state,
        "manifest_path": None if manifest_path is None else str(manifest_path),
        "warnings": [str(item) for item in warnings],
    }
    if tuple(manifest) != MANIFEST_FIELDS:
        raise AssertionError("manifest schema changed without updating MANIFEST_FIELDS")
    return manifest


def write_manifest_atomic(path: str | os.PathLike[str], manifest: Mapping[str, object]) -> Path:
    """Publish a complete 0600 manifest with a single atomic replacement."""

    destination = Path(path)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    missing = set(MANIFEST_FIELDS).difference(manifest)
    extra = set(manifest).difference(MANIFEST_FIELDS)
    if missing or extra:
        raise RuntimeInputError("manifest schema mismatch")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % destination.name, suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def read_manifest(path: str | os.PathLike[str]) -> dict[str, object] | None:
    loaded = _read_json(Path(path))
    if loaded is None or set(loaded) != set(MANIFEST_FIELDS):
        return None
    return dict(loaded)


def _split_ps_line(line: str) -> tuple[int, str] | None:
    match = re.match(r"^\s*(\d+)\s+(.*\S)\s*$", line)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


def _raw_command_has_only_exact_user_data_dir(command: str, expected: str) -> bool:
    """Validate BSD ``ps`` text, which does not quote arguments with spaces."""

    pattern = re.compile(r"(?:^|\s)--user-data-dir(?:=|\s+)")
    matches = list(pattern.finditer(command))
    if not matches:
        return False
    for match in matches:
        value_start = match.end()
        if not command.startswith(expected, value_start):
            return False
        value_end = value_start + len(expected)
        if value_end < len(command) and not command[value_end].isspace():
            return False
    return True


def _raw_command_has_process_type(command: str) -> bool:
    return bool(re.search(r"(?:^|\s)--type(?:=|\s|$)", command))


def discover_chromium_processes(
    ps_text: str,
    *,
    executable_path: str | os.PathLike[str],
    user_data_dir: str | os.PathLike[str],
) -> ProcessCohort:
    """Find only processes with exact executable and user-data-dir arguments."""

    executable = str(executable_path)
    profile = str(user_data_dir)
    records: list[ProcessRecord] = []
    main_candidates: list[ProcessRecord] = []
    for line in ps_text.splitlines():
        parsed = _split_ps_line(line)
        if parsed is None:
            continue
        pid, command = parsed
        if command != executable and not command.startswith(executable + " "):
            continue
        if not _raw_command_has_only_exact_user_data_dir(command, profile):
            continue
        record = ProcessRecord(pid, command, (executable,))
        records.append(record)
        if not _raw_command_has_process_type(command):
            main_candidates.append(record)
    records.sort(key=lambda item: item.pid)
    if len(main_candidates) == 1:
        return ProcessCohort(tuple(records), main_candidates[0].pid)
    if not records:
        return ProcessCohort((), None, "no exact process cohort found")
    if not main_candidates:
        return ProcessCohort(tuple(records), None, "no main browser process found")
    return ProcessCohort(tuple(records), None, "multiple main browser processes found")


def classify_artifact_state(
    *,
    component_path: str | os.PathLike[str] | None,
    expected_component_path: str | os.PathLike[str] | None,
    component_mtime: float | None = None,
    process_started_at: float | None = None,
) -> str:
    """Classify whether a scoped process predates the known component artifact."""

    if component_path is None or expected_component_path is None:
        return "wrong-component-path"
    if os.path.abspath(os.fspath(component_path)) != os.path.abspath(
        os.fspath(expected_component_path)
    ):
        return "wrong-component-path"
    if component_mtime is None:
        try:
            component_mtime = os.stat(component_path).st_mtime
        except OSError:
            return "unverified"
    if process_started_at is None:
        return "unverified"
    if process_started_at < component_mtime:
        return "process-predates-artifact"
    return "current"


def component_metadata(
    component_path: str | os.PathLike[str] | None,
    *,
    expected_component_path: str | os.PathLike[str] | None,
) -> tuple[str | None, float | None, str]:
    """Return digest/mtime and a non-claiming state when the file is absent."""

    state = classify_artifact_state(
        component_path=component_path,
        expected_component_path=expected_component_path,
    )
    if state == "wrong-component-path" or component_path is None:
        return None, None, state
    try:
        hasher = hashlib.sha256()
        with open(component_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(block)
        return hasher.hexdigest(), os.stat(component_path).st_mtime, "unverified"
    except OSError:
        return None, None, "unverified"


def build_stop_plan(
    ps_text: str,
    *,
    executable_path: str | os.PathLike[str],
    user_data_dir: str | os.PathLike[str],
    expected_main_pid: int | None = None,
) -> StopPlan:
    """Revalidate the precise cohort immediately before signalling it."""

    cohort = discover_chromium_processes(
        ps_text, executable_path=executable_path, user_data_dir=user_data_dir
    )
    if cohort.main_pid is None:
        raise RuntimeInputError(cohort.reason or "main browser process is unverifiable")
    if expected_main_pid is not None and cohort.main_pid != expected_main_pid:
        raise RuntimeInputError("manifest main PID no longer matches the scoped browser")
    return StopPlan(cohort.main_pid, cohort.pids)


def stop_scoped_processes(
    ps_provider: Callable[[], str],
    killer: Callable[[int, int], object],
    *,
    executable_path: str | os.PathLike[str],
    user_data_dir: str | os.PathLike[str],
    expected_main_pid: int | None = None,
) -> dict[str, object]:
    """Signal an exact, freshly rediscovered cohort; never trust a saved PID list."""

    plan = build_stop_plan(
        ps_provider(),
        executable_path=executable_path,
        user_data_dir=user_data_dir,
        expected_main_pid=expected_main_pid,
    )
    signalled: list[int] = []
    failures: list[str] = []
    for pid in plan.pids:
        try:
            killer(pid, signal.SIGTERM)
        except OSError as exc:
            failures.append("%s: %s" % (pid, exc))
        else:
            signalled.append(pid)
    return {
        "ok": not failures,
        "action": "stop",
        "main_pid": plan.main_pid,
        "process_count": len(plan.pids),
        "signalled": signalled,
        "warnings": failures,
    }


def structured_result(
    *,
    ok: bool,
    action: str,
    manifest: Mapping[str, object] | None = None,
    error: str | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, object]:
    """Return JSON-ready data; the facade alone decides stdout and stderr."""

    result: dict[str, object] = {
        "ok": bool(ok),
        "action": action,
        "warnings": [str(item) for item in warnings],
    }
    if manifest is not None:
        result["manifest"] = dict(manifest)
    if error is not None:
        result["error"] = str(error)
    return result
