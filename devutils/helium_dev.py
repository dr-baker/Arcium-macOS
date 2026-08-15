#!/usr/bin/env python3
"""Safe, worktree-aware control plane for a Helium Dev build.

The module is intentionally small enough to use from ``dev.sh`` and directly
from another worktree.  It only selects ``Helium Dev.app`` in the supplied
worktree; it never guesses at an installed or release Helium application.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from helium_dev_build import (
    DEFAULT_EDGE_BUDGET,
    ArtifactStatus,
    BuildPaths,
    HeliumDevBuilder,
)
from helium_dev_runtime import (
    MANIFEST_FIELDS,
    LockBusyError,
    ProfileSpec,
    RuntimeInputError,
    acquire_profile_lock,
    build_manifest,
    build_stop_plan,
    component_metadata,
    classify_artifact_state,
    discover_chromium_processes,
    launch_arguments,
    manifest_path_for,
    parse_runtime_arguments,
    prepare_profile,
    read_manifest,
    resolve_profile,
    structured_result,
    write_manifest_atomic,
)


class HarnessError(RuntimeError):
    """A missing or ambiguous development artifact must not be guessed."""


class HarnessArgumentParser(argparse.ArgumentParser):
    """Turn parser failures into the same JSON-safe error path as other input."""

    def error(self, message: str) -> None:
        raise RuntimeInputError(message)


@dataclass(frozen=True)
class WorktreePaths:
    worktree: Path
    source_dir: Path
    out_dir: Path
    app_path: Path
    executable_path: Path
    bundle_identifier: str
    component_path: Path
    siso_path: Path
    autoninja_path: Path


def resolve_worktree_paths(root: str | os.PathLike[str]) -> WorktreePaths:
    """Resolve only the active worktree's branded development artifact."""

    worktree = Path(root).expanduser().resolve()
    source_dir = worktree / "build" / "src"
    out_dir = source_dir / "out" / "Default"
    app_path = out_dir / "Helium Dev.app"
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise HarnessError(f"Helium Dev.app is missing from {out_dir}")
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise HarnessError(f"could not read Helium Dev.app metadata: {error}") from error
    executable_name = info.get("CFBundleExecutable")
    bundle_identifier = info.get("CFBundleIdentifier")
    if not isinstance(executable_name, str) or not executable_name or "/" in executable_name:
        raise HarnessError("Helium Dev.app has no safe CFBundleExecutable")
    if not isinstance(bundle_identifier, str) or not bundle_identifier:
        raise HarnessError("Helium Dev.app has no CFBundleIdentifier")
    executable_path = app_path / "Contents" / "MacOS" / executable_name
    if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
        raise HarnessError(f"Helium Dev executable is missing or not executable: {executable_path}")
    return WorktreePaths(
        worktree=worktree,
        source_dir=source_dir,
        out_dir=out_dir,
        app_path=app_path,
        executable_path=executable_path,
        bundle_identifier=bundle_identifier,
        component_path=out_dir / "libchrome_dll.dylib",
        siso_path=source_dir / "third_party" / "siso" / "cipd" / "siso",
        autoninja_path=source_dir / "third_party" / "depot_tools" / "autoninja.py",
    )


def _ps_snapshot() -> str:
    result = subprocess.run(
        ["/bin/ps", "-axww", "-o", "pid=", "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise HarnessError("could not inspect running processes")
    return result.stdout


def _process_started_at(pid: int) -> float | None:
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    value = result.stdout.strip()
    if result.returncode or not value:
        return None
    try:
        return dt.datetime.strptime(value, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return None


def _started_at_value(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat()


def _quilt_top(source_dir: Path) -> tuple[str | None, list[str]]:
    try:
        result = subprocess.run(
            ["quilt", "top"], cwd=source_dir, check=False, capture_output=True, text=True
        )
    except OSError as error:
        return None, [f"could not inspect Quilt state: {error}"]
    if result.returncode:
        return None, ["Quilt top is unavailable"]
    value = result.stdout.strip()
    return (value or None), ([] if value else ["Quilt has no applied top patch"])


def _manifest_for(
    *,
    paths: WorktreePaths,
    profile: ProfileSpec,
    action: str,
    cohort_text: str,
    run_id: str,
    manifest_path: Path,
    ok: bool = True,
    warnings: Iterable[str] = (),
    started_at: str | None = None,
    process_started_at: float | None = None,
) -> dict[str, object]:
    cohort = discover_chromium_processes(
        cohort_text,
        executable_path=paths.executable_path,
        user_data_dir=profile.user_data_dir,
    )
    local_warnings = list(warnings)
    if cohort.reason:
        local_warnings.append(cohort.reason)
    if cohort.main_pid is not None and process_started_at is None:
        process_started_at = _process_started_at(cohort.main_pid)
    digest, mtime, component_state = component_metadata(
        paths.component_path, expected_component_path=paths.component_path
    )
    if not paths.component_path.is_file():
        artifact_state = "wrong-component-path"
    elif component_state == "wrong-component-path":
        artifact_state = component_state
    elif cohort.main_pid is None:
        artifact_state = "unverified"
    else:
        artifact_state = classify_artifact_state(
            component_path=paths.component_path,
            expected_component_path=paths.component_path,
            component_mtime=mtime,
            process_started_at=process_started_at,
        )
    quilt_top, quilt_warnings = _quilt_top(paths.source_dir)
    local_warnings.extend(quilt_warnings)
    # A stopped profile is a verifiable status.  A non-empty cohort with no
    # unique main is not: callers must get a nonzero result rather than a
    # warning that can be mistaken for success.
    manifest_ok = ok and not (cohort.records and cohort.main_pid is None)
    return build_manifest(
        ok=manifest_ok,
        run_id=run_id,
        action=action,
        main_pid=cohort.main_pid,
        process_count=cohort.process_count,
        started_at=started_at if started_at is not None else _started_at_value(process_started_at),
        worktree=paths.worktree,
        source_dir=paths.source_dir,
        app_path=paths.app_path,
        executable_path=paths.executable_path,
        profile=profile,
        quilt_top=quilt_top,
        component_path=paths.component_path,
        component_sha256=digest,
        component_mtime=mtime,
        artifact_state=artifact_state,
        manifest_path=manifest_path,
        warnings=local_warnings,
    )


def _runtime_profile(
    arguments: Sequence[str], *, home: str | os.PathLike[str] | None = None
) -> tuple[ProfileSpec, tuple[str, ...]]:
    parsed = parse_runtime_arguments(arguments)
    profile = resolve_profile(
        parsed.profile_mode,
        parsed.profile_name,
        home=home,
        profile_directory=parsed.profile_directory,
    )
    return profile, parsed.passthrough


def _read_prior_started_at(path: Path) -> str | None:
    prior = read_manifest(path)
    value = prior.get("started_at") if prior else None
    return value if isinstance(value, str) else None


def _run_locked(
    paths: WorktreePaths,
    profile: ProfileSpec,
    passthrough: Sequence[str],
    *,
    action: str,
    registry_root: Path | None = None,
) -> dict[str, object]:
    manifest_path = manifest_path_for(profile, registry_root)
    existing = discover_chromium_processes(
        _ps_snapshot(), executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
    )
    if existing.records:
        raise HarnessError("an exact Helium Dev process is already running for this profile")
    prepare_profile(profile, allow_existing_fresh=(action == "restart"))
    command = (str(paths.executable_path), *launch_arguments(profile, passthrough))
    process = subprocess.Popen(command, cwd=paths.source_dir, start_new_session=True)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        cohort_text = _ps_snapshot()
        cohort = discover_chromium_processes(
            cohort_text, executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
        )
        if cohort.main_pid is not None:
            started = _process_started_at(cohort.main_pid)
            manifest = _manifest_for(
                paths=paths,
                profile=profile,
                action=action,
                cohort_text=cohort_text,
                run_id=uuid.uuid4().hex,
                manifest_path=manifest_path,
                process_started_at=started,
            )
            write_manifest_atomic(manifest_path, manifest)
            # A verified browser deliberately outlives this short-lived CLI.
            # Popen otherwise warns on destruction even though handing the
            # session to launchd is the intended successful outcome.
            process._child_created = False  # type: ignore[attr-defined]
            return manifest
        if process.poll() is not None:
            break
        time.sleep(0.1)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    raise HarnessError("Dev launch did not produce a uniquely verifiable main browser process")


def _stop_locked(
    paths: WorktreePaths,
    profile: ProfileSpec,
    *,
    action: str,
    registry_root: Path | None = None,
) -> dict[str, object]:
    manifest_path = manifest_path_for(profile, registry_root)
    cohort_text = _ps_snapshot()
    existing = discover_chromium_processes(
        cohort_text, executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
    )
    if not existing.records:
        manifest = _manifest_for(
            paths=paths,
            profile=profile,
            action=action,
            cohort_text=cohort_text,
            run_id=uuid.uuid4().hex,
            manifest_path=manifest_path,
            started_at=_read_prior_started_at(manifest_path),
            warnings=("no exact Helium Dev process is running",),
        )
        write_manifest_atomic(manifest_path, manifest)
        return manifest
    # This is the final process-table snapshot before SIGTERM.  It never trusts
    # the historical child PIDs (which are deliberately absent from manifests).
    plan = build_stop_plan(
        _ps_snapshot(),
        executable_path=paths.executable_path,
        user_data_dir=profile.user_data_dir,
        expected_main_pid=None,
    )
    for pid in tuple(pid for pid in plan.pids if pid != plan.main_pid) + (plan.main_pid,):
        # Revalidate each candidate immediately before delivery.  A process
        # that exited and had its PID reused cannot be signalled from an old
        # snapshot.
        current = discover_chromium_processes(
            _ps_snapshot(),
            executable_path=paths.executable_path,
            user_data_dir=profile.user_data_dir,
        )
        if pid not in current.pids:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        remaining_text = _ps_snapshot()
        remaining = discover_chromium_processes(
            remaining_text,
            executable_path=paths.executable_path,
            user_data_dir=profile.user_data_dir,
        )
        if not remaining.records:
            manifest = _manifest_for(
                paths=paths,
                profile=profile,
                action=action,
                cohort_text=remaining_text,
                run_id=uuid.uuid4().hex,
                manifest_path=manifest_path,
                started_at=_read_prior_started_at(manifest_path),
            )
            write_manifest_atomic(manifest_path, manifest)
            return manifest
        time.sleep(0.1)
    remaining_text = _ps_snapshot()
    manifest = _manifest_for(
        paths=paths,
        profile=profile,
        action=action,
        cohort_text=remaining_text,
        run_id=uuid.uuid4().hex,
        manifest_path=manifest_path,
        ok=False,
        started_at=_read_prior_started_at(manifest_path),
        warnings=("exact Helium Dev process cohort remained after SIGTERM",),
    )
    write_manifest_atomic(manifest_path, manifest)
    return manifest


def runtime_action(
    action: str,
    root: str,
    arguments: Sequence[str],
    *,
    home: str | os.PathLike[str] | None = None,
    registry_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Perform one scoped runtime action and persist its privacy-safe result."""

    profile, passthrough = _runtime_profile(arguments, home=home)
    paths = resolve_worktree_paths(root)
    registry = None if registry_root is None else Path(registry_root)
    manifest_path = manifest_path_for(profile, registry)
    lock = acquire_profile_lock(profile, root=registry)
    try:
        if action == "run":
            return _run_locked(paths, profile, passthrough, action="run", registry_root=registry)
        if action == "status":
            if passthrough:
                raise RuntimeInputError("status does not accept Chromium launch arguments")
            manifest = _manifest_for(
                paths=paths,
                profile=profile,
                action="status",
                cohort_text=_ps_snapshot(),
                run_id=uuid.uuid4().hex,
                manifest_path=manifest_path,
                started_at=_read_prior_started_at(manifest_path),
            )
            write_manifest_atomic(manifest_path, manifest)
            return manifest
        if action == "activate":
            if passthrough:
                raise RuntimeInputError("activate does not accept Chromium launch arguments")
            cohort = discover_chromium_processes(
                _ps_snapshot(), executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
            )
            if cohort.main_pid is None:
                raise HarnessError(cohort.reason or "main browser process is unverifiable")
            result = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    (
                        'tell application "System Events" to set frontmost of '
                        f'(first process whose unix id is {cohort.main_pid}) to true'
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise HarnessError("could not activate the verified Helium Dev application")
            manifest = _manifest_for(
                paths=paths,
                profile=profile,
                action="activate",
                cohort_text=_ps_snapshot(),
                run_id=uuid.uuid4().hex,
                manifest_path=manifest_path,
            )
            write_manifest_atomic(manifest_path, manifest)
            return manifest
        if action == "stop":
            if passthrough:
                raise RuntimeInputError("stop does not accept Chromium launch arguments")
            return _stop_locked(paths, profile, action="stop", registry_root=registry)
        if action == "restart":
            if passthrough:
                raise RuntimeInputError("restart does not accept Chromium launch arguments")
            stopped = _stop_locked(paths, profile, action="restart", registry_root=registry)
            if not stopped["ok"]:
                return stopped
            return _run_locked(paths, profile, (), action="restart", registry_root=registry)
        raise HarnessError(f"unknown runtime action: {action}")
    finally:
        lock.release()


def build_action(action: str, root: str, arguments: Sequence[str]) -> dict[str, object]:
    """Run a guarded build operation using the active worktree's graph only."""

    parser = HarnessArgumentParser(prog=f"he {action}", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--edge-budget", type=int, default=_edge_budget_from_environment())
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--resources", action="store_true")
    parser.add_argument("targets", nargs="*")
    namespace = parser.parse_args(list(arguments))
    worktree = Path(root).expanduser().resolve()
    source_dir = worktree / "build" / "src"
    out_dir = source_dir / "out" / "Default"
    builder = HeliumDevBuilder(
        BuildPaths(
            source_dir,
            out_dir,
            source_dir / "third_party" / "siso" / "cipd" / "siso",
            source_dir / "third_party" / "depot_tools" / "autoninja.py",
        ),
        edge_budget=namespace.edge_budget,
    )
    if action == "build-plan":
        result = builder.build_plan(namespace.targets)
    elif action == "compile":
        result = builder.compile(namespace.targets)
    elif action == "relink":
        if namespace.targets:
            raise RuntimeInputError("relink takes no graph targets")
        result = builder.relink(
            resources=namespace.resources,
            artifact_status_probe=lambda: _artifact_status_for_root(worktree),
        )
    elif action == "build-full":
        if namespace.targets:
            raise RuntimeInputError("build-full takes no graph targets")
        result = builder.build_full(approved=namespace.approved)
    else:
        raise HarnessError(f"unknown build action: {action}")
    return result.as_dict()


def _edge_budget_from_environment() -> int:
    value = os.environ.get("HELIUM_DEV_EDGE_BUDGET", str(DEFAULT_EDGE_BUDGET))
    try:
        budget = int(value)
    except ValueError as error:
        raise RuntimeInputError("HELIUM_DEV_EDGE_BUDGET must be an integer") from error
    if budget < 0:
        raise RuntimeInputError("HELIUM_DEV_EDGE_BUDGET must be zero or greater")
    return budget


def _artifact_status(paths: WorktreePaths) -> ArtifactStatus:
    """Report whether a currently running exact Dev main predates this component."""

    digest, mtime, state = component_metadata(
        paths.component_path, expected_component_path=paths.component_path
    )
    del digest
    if not paths.component_path.is_file() or state == "wrong-component-path":
        return ArtifactStatus("wrong-component-path", None, ("component artifact is missing",))
    mains: list[int] = []
    for line in _ps_snapshot().splitlines():
        match = line.strip().split(maxsplit=1)
        if len(match) != 2 or not match[0].isdigit():
            continue
        pid, command = int(match[0]), match[1]
        if command != str(paths.executable_path) and not command.startswith(str(paths.executable_path) + " "):
            continue
        if " --type=" in command or " --type " in command:
            continue
        mains.append(pid)
    if len(mains) != 1:
        warning = "no exact Dev main is running" if not mains else "multiple exact Dev mains are running"
        return ArtifactStatus("unverified", None, (warning,))
    state = classify_artifact_state(
        component_path=paths.component_path,
        expected_component_path=paths.component_path,
        component_mtime=mtime,
        process_started_at=_process_started_at(mains[0]),
    )
    return ArtifactStatus(state, state == "process-predates-artifact", ())


def _artifact_status_for_root(root: Path) -> ArtifactStatus:
    try:
        return _artifact_status(resolve_worktree_paths(root))
    except HarnessError as error:
        return ArtifactStatus("unverified", None, (f"artifact freshness is unavailable: {error}",))


def _split_json(arguments: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    json_count = sum(argument == "--json" for argument in arguments)
    if json_count > 1:
        raise RuntimeInputError("--json may be supplied only once")
    return bool(json_count), tuple(argument for argument in arguments if argument != "--json")


def _emit(document: dict[str, object], *, json_mode: bool) -> None:
    if json_mode:
        json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
        return
    if set(document) == set(MANIFEST_FIELDS):
        state = document["artifact_state"]
        pid = document["main_pid"]
        print(f"{document['action']}: pid {pid if pid is not None else '-'} · {document['profile_mode']} · {state}")
        return
    if "proof_gates" in document:
        state = "ok" if document.get("ok") else "refused"
        gates = ", ".join(str(gate) for gate in document.get("proof_gates", ())) or "none"
        edges = document.get("edge_count")
        artifact = document.get("artifact_state")
        print(f"{document['action']}: {state} · {edges if edges is not None else '-'} edges · {artifact} · proof {gates}")
        return
    state = "ok" if document.get("ok") else "refused"
    detail = document.get("error") or document.get("action")
    print(f"{state}: {detail}")


def _usage() -> str:
    return (
        "usage: helium_dev.py --root WORKTREE <run|status|activate|stop|restart|"
        "build-plan|compile|relink|build-full> [options]\n"
        "runtime profiles: --isolated NAME | --fresh NAME; --json\n"
        "build: --edge-budget N; relink --resources; build-full --approved"
    )


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    parser = HarnessArgumentParser(add_help=False)
    parser.add_argument("--root", required=True)
    namespace, remaining = parser.parse_known_args(values)
    if not remaining:
        print(_usage(), file=sys.stderr)
        return 2
    action, *action_arguments = remaining
    try:
        json_mode, normalized_arguments = _split_json(action_arguments)
        if action in {"run", "status", "activate", "stop", "restart"}:
            document = runtime_action(action, namespace.root, normalized_arguments)
        elif action in {"build-plan", "compile", "relink", "build-full"}:
            document = build_action(action, namespace.root, normalized_arguments)
        else:
            raise RuntimeInputError(f"unknown he command: {action}")
    except (HarnessError, LockBusyError, RuntimeInputError, OSError, subprocess.SubprocessError) as error:
        document = structured_result(ok=False, action=action, error=str(error))
        print(str(error), file=sys.stderr)
        _emit(document, json_mode="--json" in action_arguments)
        return 2
    _emit(document, json_mode=json_mode)
    return 0 if bool(document.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
