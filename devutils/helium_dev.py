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
from dataclasses import dataclass, replace
from contextlib import ExitStack, nullcontext
from pathlib import Path
from typing import Callable, Iterable, Sequence

from build_preparation import prepared_build_digest, require_stage
from build_diagnostics import publish_result
from build_backend import BackendError
from build_lane import LaneError, LaneSpec, acquire_lane_lock, heavy_lane_temp, heavy_temp_environment
from build_execution import ExecutionError, invalidate_execution, material_guard, record_execution, verify_material_inputs
from build_receipt import ReceiptError, material_inputs_at_entry
from build_receipt_cli import (
    _publish_packaged_build,
    require_current_packaged_build,
)
from helium_dev_build import (
    DEFAULT_EDGE_BUDGET,
    ArtifactStatus,
    BuildPaths,
    HeliumDevBuilder,
)
from helium_dev_bundle import (
    BundleError,
    DevBundleIdentity,
    _package_dev_bundle_locked,
    resolve_bundle_paths,
    resolve_dev_identity,
)
from gclient_identity import GClientIdentityError, ensure_gclient_identity
from replay_contract import ReplayError, replay as replay_quilt, require_current_replay_proof
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
    effective_feature_selection,
    launch_arguments,
    live_singleton_owner,
    manifest_path_for,
    parse_runtime_arguments,
    prepare_profile,
    profile_seed_source,
    read_manifest,
    resolve_profile,
    structured_result,
    write_manifest_atomic,
)
from profile_clone import ProfileCloneError, clone_profile_once


class HarnessError(RuntimeError):
    """A missing or ambiguous development artifact must not be guessed."""


class HarnessArgumentParser(argparse.ArgumentParser):
    """Turn parser failures into the same JSON-safe error path as other input."""

    def error(self, message: str) -> None:
        raise RuntimeInputError(message)


def _positive_job_count(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    return int(value)


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


def resolve_worktree_paths(
    root: str | os.PathLike[str],
    build_root: str | os.PathLike[str] | None = None,
    *,
    identity: DevBundleIdentity | None = None,
) -> WorktreePaths:
    """Resolve only the active worktree's branded development artifact."""

    selected_identity = resolve_dev_identity() if identity is None else identity
    worktree = Path(root).expanduser().resolve()
    build_dir = (
        worktree / "build"
        if build_root is None
        else Path(build_root).expanduser().resolve()
    )
    source_dir = build_dir / "src"
    out_dir = source_dir / "out" / "Default"
    app_path = out_dir / selected_identity.app_name
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise HarnessError(f"{selected_identity.app_name} is missing from {out_dir}")
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise HarnessError(f"could not read Helium Dev.app metadata: {error}") from error
    executable_name = info.get("CFBundleExecutable")
    bundle_identifier = info.get("CFBundleIdentifier")
    if not isinstance(executable_name, str) or not executable_name or "/" in executable_name:
        raise HarnessError(f"{selected_identity.app_name} has no safe CFBundleExecutable")
    if not isinstance(bundle_identifier, str) or not bundle_identifier:
        raise HarnessError(f"{selected_identity.app_name} has no CFBundleIdentifier")
    if bundle_identifier != selected_identity.bundle_identifier:
        raise HarnessError(
            f"{selected_identity.app_name} has the wrong bundle identifier"
        )
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
    passthrough: Sequence[str] | None = None,
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
    inherited_effective: tuple[str, ...] | None = None
    inherited_disabled: tuple[str, ...] | None = None
    if passthrough is None:
        prior = read_manifest(manifest_path)
        prior_effective = prior.get("effective_features") if prior else None
        prior_disabled = prior.get("disabled_features") if prior else None
        if isinstance(prior_effective, list) and all(
            isinstance(feature, str) for feature in prior_effective
        ):
            inherited_effective = tuple(prior_effective)
        if isinstance(prior_disabled, list) and all(
            isinstance(feature, str) for feature in prior_disabled
        ):
            inherited_disabled = tuple(prior_disabled)
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
        passthrough=() if passthrough is None else passthrough,
        effective_features=inherited_effective,
        disabled_features=inherited_disabled,
    )


def _runtime_profile(
    arguments: Sequence[str], *, home: str | os.PathLike[str] | None = None
) -> tuple[ProfileSpec, tuple[str, ...], str | None]:
    parsed = parse_runtime_arguments(arguments)
    profile = resolve_profile(
        parsed.profile_mode,
        parsed.profile_name,
        home=home,
        profile_directory=parsed.profile_directory,
    )
    return profile, parsed.passthrough, parsed.seed_from


def _read_prior_started_at(path: Path) -> str | None:
    prior = read_manifest(path)
    value = prior.get("started_at") if prior else None
    return value if isinstance(value, str) else None


def _profile_seed_conflicts(
    ps_text: str, source: Path, seed_from: str
) -> tuple[str, ...]:
    conflicts: list[str] = []
    source_switch = f"--user-data-dir={source}"
    for line in ps_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid, separator, command = stripped.partition(" ")
        if (
            not separator
            or not pid.isdigit()
            or " --type=" in command
            or " --type " in command
        ):
            continue
        installed_main = (
            seed_from == "installed"
            and "/Applications/Helium.app/Contents/MacOS/Helium" in command
        )
        if installed_main or source_switch in command:
            conflicts.append(pid)
    return tuple(dict.fromkeys(conflicts))


def _validate_profile_seed(
    profile: ProfileSpec,
    seed_from: str | None,
    *,
    home: str | os.PathLike[str] | None,
) -> Path | None:
    destination = profile.user_data_dir
    if destination.exists() or destination.is_symlink() or seed_from in {None, "empty"}:
        return None
    source = profile_seed_source(seed_from, home=home)
    if source is None:
        return None
    if source.is_symlink() or not source.is_dir():
        raise HarnessError(f"profile seed is missing: {source}")
    conflicts = _profile_seed_conflicts(_ps_snapshot(), source, seed_from)
    if conflicts:
        raise HarnessError(
            "quit the source Helium profile before seeding "
            f"{profile.key} (matching PIDs: {', '.join(conflicts)})"
        )
    return source


def _prepare_selected_profile(
    profile: ProfileSpec,
    seed_from: str | None,
    *,
    action: str,
    home: str | os.PathLike[str] | None,
) -> None:
    if profile.user_data_dir.exists() or profile.user_data_dir.is_symlink():
        prepare_profile(profile, allow_existing_fresh=(action == "restart"))
        return
    source = _validate_profile_seed(profile, seed_from, home=home)
    if source is None:
        prepare_profile(profile, allow_existing_fresh=(action == "restart"))
        return
    try:
        clone_profile_once(source, profile.user_data_dir)
    except ProfileCloneError as error:
        raise HarnessError(str(error)) from error


def _stop_owned_child(process: subprocess.Popen[bytes]) -> None:
    """Stop and reap the child created by this launch, without process discovery."""

    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


def _remove_owned_manifest(path: Path, run_id: str) -> None:
    current = read_manifest(path)
    if current is not None and current.get("run_id") == run_id:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _run_locked(
    paths: WorktreePaths,
    profile: ProfileSpec,
    passthrough: Sequence[str],
    *,
    action: str,
    seed_from: str | None = None,
    home: str | os.PathLike[str] | None = None,
    registry_root: Path | None = None,
    material_at_entry: str,
    cleanup: ExitStack,
) -> tuple[dict[str, object], Callable[[], None]]:
    """Keep the launched child owned until the caller's final material check."""

    manifest_path = manifest_path_for(profile, registry_root)
    existing = discover_chromium_processes(
        _ps_snapshot(), executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
    )
    if existing.records:
        raise HarnessError("an exact Helium Dev process is already running for this profile")
    singleton_owner = live_singleton_owner(profile)
    if singleton_owner is not None:
        raise HarnessError(
            f"profile is already owned by browser process {singleton_owner}; quit it first"
        )
    _prepare_selected_profile(
        profile, seed_from, action=action, home=home
    )
    verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
    command = (str(paths.executable_path), *launch_arguments(profile, passthrough))
    process = subprocess.Popen(command, cwd=paths.source_dir, start_new_session=True)
    cleanup.callback(_stop_owned_child, process)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        cohort_text = _ps_snapshot()
        cohort = discover_chromium_processes(
            cohort_text, executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
        )
        if (cohort.main_pid == process.pid
                and live_singleton_owner(profile) == process.pid
                and process.poll() is None):
            started = _process_started_at(cohort.main_pid)
            manifest = _manifest_for(
                paths=paths,
                profile=profile,
                action=action,
                cohort_text=cohort_text,
                run_id=uuid.uuid4().hex,
                manifest_path=manifest_path,
                process_started_at=started,
                passthrough=passthrough,
            )
            cleanup.callback(_remove_owned_manifest, manifest_path, str(manifest["run_id"]))
            write_manifest_atomic(manifest_path, manifest)

            def finish_launch() -> None:
                current = discover_chromium_processes(
                    _ps_snapshot(),
                    executable_path=paths.executable_path,
                    user_data_dir=profile.user_data_dir,
                )
                if (current.main_pid != process.pid
                        or live_singleton_owner(profile) != process.pid
                        or process.poll() is not None):
                    raise HarnessError("Dev launch lost its verified browser process")
                verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
                # The browser deliberately outlives this CLI only after the
                # final guard. Suppress Popen's warning for that handoff.
                process._child_created = False  # type: ignore[attr-defined]
                cleanup.pop_all()

            return manifest, finish_launch
        if process.poll() is not None:
            break
        time.sleep(0.1)
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


def _runtime_action_locked(
    action: str,
    root: str,
    arguments: Sequence[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
    registry_root: str | os.PathLike[str] | None = None,
    material_at_entry: str | None = None,
    cleanup: ExitStack | None = None,
) -> dict[str, object] | tuple[dict[str, object], Callable[[], None]]:
    """Perform one runtime action after any required lane lock is held."""

    preflight = sum(argument == "--preflight" for argument in arguments)
    if preflight > 1:
        raise RuntimeInputError("--preflight may be supplied only once")
    if preflight and action != "run":
        raise RuntimeInputError("--preflight is only valid with run")
    runtime_arguments = tuple(argument for argument in arguments if argument != "--preflight")
    profile, passthrough, seed_from = _runtime_profile(
        runtime_arguments, home=home
    )
    identity = resolve_dev_identity(profile.mode, profile.name)
    if action in {"run", "restart"}:
        if material_at_entry is None or cleanup is None:
            raise HarnessError("runtime launch requires a material input guard and cleanup")
        selected_build_root = (
            Path(build_root).expanduser().resolve()
            if build_root is not None
            else Path(root).expanduser().resolve() / "build"
        )
        require_current_packaged_build(
            Path(root).expanduser().resolve(),
            selected_build_root,
            os.environ.get("HELIUM_DEV_LANE", "worktree"),
            identity,
        )
    paths = resolve_worktree_paths(root, build_root, identity=identity)
    if preflight:
        if not paths.component_path.is_file():
            raise HarnessError(f"Helium Dev component is missing: {paths.component_path}")
        cohort = discover_chromium_processes(
            _ps_snapshot(), executable_path=paths.executable_path, user_data_dir=profile.user_data_dir
        )
        if cohort.records:
            raise HarnessError("an exact Helium Dev process is already running for this profile")
        singleton_owner = live_singleton_owner(profile)
        if singleton_owner is not None:
            raise HarnessError(
                f"profile is already owned by browser process {singleton_owner}; quit it first"
            )
        _validate_profile_seed(profile, seed_from, home=home)
        feature_selection = effective_feature_selection(passthrough)
        return {
            "ok": True,
            "action": "run-preflight",
            "app_path": str(paths.app_path),
            "executable_path": str(paths.executable_path),
            "bundle_identifier": paths.bundle_identifier,
            "profile_mode": profile.mode,
            "user_data_dir": str(profile.user_data_dir),
            "profile_directory": profile.profile_directory,
            "launch_arguments": list(launch_arguments(profile, passthrough)),
            "feature_bundle": feature_selection.bundle,
            "effective_features": list(feature_selection.enabled),
            "disabled_features": list(feature_selection.disabled),
            "process_state": "not-running",
            "proof_gates": (
                "dev-bundle-resolved",
                "executable-ready",
                "component-ready",
                "profile-scope-validated",
                "launch-not-started",
            ),
        }
    registry = None if registry_root is None else Path(registry_root)
    manifest_path = manifest_path_for(profile, registry)
    lock = acquire_profile_lock(profile, root=registry)
    if cleanup is not None:
        cleanup.callback(lock.release)
        launch_cleanup = cleanup.enter_context(ExitStack())
    try:
        if action == "run":
            return _run_locked(
                paths,
                profile,
                passthrough,
                action="run",
                seed_from=seed_from,
                home=home,
                registry_root=registry,
                material_at_entry=material_at_entry,
                cleanup=launch_cleanup,
            )
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
            return _run_locked(
                paths,
                profile,
                (),
                action="restart",
                seed_from=seed_from,
                home=home,
                registry_root=registry,
                material_at_entry=material_at_entry,
                cleanup=launch_cleanup,
            )
        raise HarnessError(f"unknown runtime action: {action}")
    finally:
        if cleanup is None:
            lock.release()


def runtime_action(
    action: str,
    root: str,
    arguments: Sequence[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
    registry_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Perform one scoped runtime action and persist its privacy-safe result."""

    if action not in {"run", "restart"}:
        return _runtime_action_locked(
            action,
            root,
            arguments,
            build_root=build_root,
            home=home,
            registry_root=registry_root,
        )
    worktree = Path(root).expanduser().resolve()
    selected_build_root = (
        Path(build_root).expanduser().resolve()
        if build_root is not None
        else worktree / "build"
    )
    owner = {
        "action": action,
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(worktree),
    }
    material_at_entry = material_inputs_at_entry(worktree)
    with acquire_lane_lock(
        selected_build_root / ".arcium" / "lane.lock", owner
    ), ExitStack() as cleanup:
        with material_guard(worktree, selected_build_root, expected=material_at_entry):
            result = _runtime_action_locked(
                action,
                root,
                arguments,
                build_root=build_root,
                home=home,
                registry_root=registry_root,
                material_at_entry=material_at_entry,
                cleanup=cleanup,
            )
        if isinstance(result, tuple):
            manifest, finish_launch = result
            finish_launch()
            return manifest
        return result


def build_action(
    action: str,
    root: str,
    arguments: Sequence[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Run a guarded build operation using the active worktree's graph only."""

    parser = HarnessArgumentParser(prog=f"he {action}", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--edge-budget", type=int, default=_edge_budget_from_environment())
    parser.add_argument("--jobs", type=_positive_job_count)
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--resources", action="store_true")
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument("--isolated")
    profile_group.add_argument("--fresh")
    parser.add_argument("targets", nargs="*")
    namespace = parser.parse_intermixed_args(list(arguments))
    profile_mode = "normal"
    profile_name = None
    if namespace.isolated is not None:
        profile_mode, profile_name = "isolated", namespace.isolated
    elif namespace.fresh is not None:
        profile_mode, profile_name = "fresh", namespace.fresh
    if action != "relink" and profile_name is not None:
        raise RuntimeInputError(f"--{profile_mode} is only valid with relink")
    artifact_identity = resolve_dev_identity(profile_mode, profile_name)
    worktree = Path(root).expanduser().resolve()
    build_dir = (
        worktree / "build"
        if build_root is None
        else Path(build_root).expanduser().absolute()
    )
    source_dir = build_dir / "src"
    out_dir = source_dir / "out" / "Default"
    builder = HeliumDevBuilder(
        BuildPaths(
            source_dir,
            out_dir,
            source_dir / "third_party" / "siso" / "cipd" / "siso",
            source_dir / "third_party" / "depot_tools" / "autoninja.py",
        ),
        edge_budget=namespace.edge_budget,
        jobs=namespace.jobs,
    )
    lock_path = build_dir / ".arcium" / "lane.lock"
    owner = {
        "action": action,
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(worktree),
    }
    needs_heavy_temp = owner["lane"] == "heavy" and (action != "build-full" or namespace.approved)
    temp_spec = LaneSpec("heavy", build_dir, 0, expected_volume_uuid=os.environ.get("HELIUM_DEV_HEAVY_VOLUME_UUID"))
    if needs_heavy_temp:
        heavy_lane_temp(temp_spec)
    material_at_entry = (
        material_inputs_at_entry(worktree)
        if needs_heavy_temp or action in {"compile", "relink"} or (action == "build-full" and namespace.approved)
        else None
    )
    execution_receipt = None
    with acquire_lane_lock(lock_path, owner), (
        material_guard(worktree, build_dir, expected=material_at_entry)
        if material_at_entry is not None else nullcontext()
    ), (heavy_temp_environment(temp_spec) if needs_heavy_temp else nullcontext()):
        if action == "build-plan":
            ensure_gclient_identity(build_dir)
            result = builder.build_plan(namespace.targets)
        elif action == "compile":
            require_stage(worktree, build_dir, "backend")
            ensure_gclient_identity(build_dir)
            result = builder.compile(namespace.targets)
        elif action == "relink":
            if namespace.targets:
                raise RuntimeInputError("relink takes no graph targets")
            if namespace.resources:
                require_current_replay_proof(worktree, source_dir)
                preparation_at_entry = prepared_build_digest(worktree, build_dir)
                invalidate_execution(build_dir)
            require_stage(worktree, build_dir, "backend")
            ensure_gclient_identity(build_dir)
            result = builder.relink(
                resources=namespace.resources,
                artifact_status_probe=lambda: _artifact_status_for_root(
                    worktree, build_root, identity=artifact_identity
                ),
            )
            if result.ok and namespace.resources:
                try:
                    execution_receipt = record_execution(
                        worktree,
                        build_dir,
                        lane=str(owner["lane"]),
                        action="relink-resources",
                        targets=result.targets,
                        material_inputs_at_entry=material_at_entry,
                        prepared_inputs_at_entry=preparation_at_entry,
                    )
                except ExecutionError as error:
                    result = replace(result, ok=False, outcome="failed", error=str(error),
                                     warnings=result.warnings + ("build finished; runnable build proof was not established",))
        elif action == "build-full":
            if namespace.targets:
                raise RuntimeInputError("build-full takes no graph targets")
            # Approval is checked first so an accidental broad build remains
            # a cheap, deterministic refusal.  An approved build additionally
            # requires a fresh full Quilt replay.
            if namespace.approved:
                require_current_replay_proof(worktree, source_dir)
                preparation_at_entry = prepared_build_digest(worktree, build_dir)
                invalidate_execution(build_dir)
                ensure_gclient_identity(build_dir)
            result = builder.build_full(approved=namespace.approved)
            if result.ok and namespace.approved:
                try:
                    execution_receipt = record_execution(
                        worktree,
                        build_dir,
                        lane=str(owner["lane"]),
                        action="build-full",
                        targets=result.targets,
                        material_inputs_at_entry=material_at_entry,
                        prepared_inputs_at_entry=preparation_at_entry,
                    )
                except ExecutionError as error:
                    result = replace(result, ok=False, outcome="failed", error=str(error),
                                     warnings=result.warnings + ("build finished; runnable build proof was not established",))
        else:
            raise HarnessError(f"unknown build action: {action}")
        document = result.as_dict()
        document.update(source_worktree=str(worktree), build_root=str(build_dir), lane=str(owner["lane"]))
        if execution_receipt is not None:
            document.update(execution_receipt_id=execution_receipt.receipt_id,
                            replay_receipt_id=execution_receipt.replay_receipt_id,
                            source_receipt_id=execution_receipt.source_receipt_id)
        try:
            document["result_path"] = str(publish_result(build_dir / ".arcium" / "build-evidence", document))
        except OSError as error:
            document["warnings"].append(f"build result report unavailable: {type(error).__name__}")
    return document


def dev_bundle_action(
    root: str,
    arguments: Sequence[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Create the active worktree's independently identifiable Dev bundle."""

    parsed = parse_runtime_arguments(arguments)
    profile = resolve_profile(parsed.profile_mode, parsed.profile_name)
    identity = resolve_dev_identity(profile.mode, profile.name)
    worktree = Path(root).expanduser().resolve()
    build_dir = (
        worktree / "build"
        if build_root is None
        else Path(build_root).expanduser().resolve()
    )
    lane = os.environ.get("HELIUM_DEV_LANE", "worktree")
    lock_path = build_dir / ".arcium" / "lane.lock"
    owner = {"action": "dev-bundle", "lane": lane, "worktree": str(worktree)}
    material_at_entry = material_inputs_at_entry(worktree)
    with acquire_lane_lock(lock_path, owner), material_guard(
        worktree, build_dir, expected=material_at_entry
    ):
        document = _package_dev_bundle_locked(
            resolve_bundle_paths(root, build_root, identity=identity),
            identity=identity,
        )
        receipt = _publish_packaged_build(
            worktree,
            build_dir,
            lane,
            expected_package_sha256=str(document["package_tree_sha256"]),
            identity=identity,
        )
        document["build_receipt"] = receipt.receipt_id
        return document


def replay_action(
    root: str,
    *,
    build_root: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Pop and strictly replay the complete stack under the lane lock."""
    worktree = Path(root).expanduser().resolve()
    build_dir = (
        worktree / "build"
        if build_root is None
        else Path(build_root).expanduser().resolve()
    )
    source_dir = build_dir / "src"
    lock_path = build_dir / ".arcium" / "lane.lock"
    owner = {
        "action": "replay",
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(worktree),
    }
    with acquire_lane_lock(lock_path, owner):
        receipt = replay_quilt(worktree, source_dir)
    return {
        "ok": True,
        "action": "replay",
        "receipt_id": receipt.receipt_id,
        "proof_gates": ("popped", "replayed", "series-verified", "receipt-published"),
    }


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


def _artifact_status_for_root(
    root: Path,
    build_root: str | os.PathLike[str] | None = None,
    *,
    identity: DevBundleIdentity | None = None,
) -> ArtifactStatus:
    try:
        return _artifact_status(
            resolve_worktree_paths(root, build_root, identity=identity)
        )
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
        state = document.get("outcome") or ("ok" if document.get("ok") else "refused")
        for name, seconds in document.get("stage_seconds", {}).items():
            print(f"{name}: {seconds:.3f}s measured wall time")
        if document.get("error"):
            print("error: " + str(document["error"])[:1200])
        for warning in document.get("warnings", ()):
            print("warning: " + str(warning)[:1200])
        if document.get("result_path"):
            print(f"result: {document['result_path']}")
        for path in document.get("evidence_paths", ()):
            print(f"evidence: {path}")
        gates = ", ".join(str(gate) for gate in document.get("proof_gates", ())) or "none"
        if document.get("action") == "dev-bundle":
            print(
                f"dev-bundle: {state} · {document.get('display_name', '-') } · "
                f"{document.get('copy_method', '-')} · proof {gates}"
            )
            return
        if document.get("action") == "run-preflight":
            print(f"run preflight: {state} · proof {gates}")
            return
        if document.get("action") == "replay":
            print(f"replay: {state} · proof {gates}")
            return
        edges = document.get("edge_count")
        artifact = document.get("artifact_state")
        runtime = f" · runtime artifact {artifact}" if document.get("action") == "relink" else ""
        print(f"{document['action']}: {state} · {edges if edges is not None else '-'} edges{runtime} · proof {gates}")
        return
    state = "ok" if document.get("ok") else "refused"
    detail = document.get("error") or document.get("action")
    print(f"{state}: {detail}")


def _usage() -> str:
    return (
        "usage: helium_dev.py --root WORKTREE [--build-root PATH] "
        "<run|status|activate|stop|restart|"
        "build-plan|compile|relink|build-full|dev-bundle|replay> [options]\n"
        "runtime profiles: --isolated NAME | --fresh NAME; "
        "--seed-from installed|dev|empty; run --preflight; --json\n"
        "build: --edge-budget N; --jobs N (positive local job limit); "
        "relink --resources; build-full --approved; "
        "dev-bundle: clone and sign the selected labeled Dev app"
    )


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    parser = HarnessArgumentParser(add_help=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--build-root")
    namespace, remaining = parser.parse_known_args(values)
    if not remaining:
        print(_usage(), file=sys.stderr)
        return 2
    action, *action_arguments = remaining
    try:
        json_mode, normalized_arguments = _split_json(action_arguments)
        if action in {"run", "status", "activate", "stop", "restart"}:
            document = runtime_action(
                action,
                namespace.root,
                normalized_arguments,
                build_root=namespace.build_root,
            )
        elif action in {"build-plan", "compile", "relink", "build-full"}:
            document = build_action(
                action,
                namespace.root,
                normalized_arguments,
                build_root=namespace.build_root,
            )
        elif action == "dev-bundle":
            document = dev_bundle_action(
                namespace.root,
                normalized_arguments,
                build_root=namespace.build_root,
            )
        elif action == "replay":
            if normalized_arguments:
                raise RuntimeInputError("replay takes no arguments")
            document = replay_action(
                namespace.root,
                build_root=namespace.build_root,
            )
        else:
            raise RuntimeInputError(f"unknown he command: {action}")
    except (
        BackendError,
        BundleError,
        ExecutionError,
        GClientIdentityError,
        HarnessError,
        LaneError,
        LockBusyError,
        ReplayError,
        ReceiptError,
        RuntimeInputError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        document = structured_result(ok=False, action=action, error=str(error))
        print(str(error), file=sys.stderr)
        _emit(document, json_mode="--json" in action_arguments)
        return 2
    _emit(document, json_mode=json_mode)
    return 0 if bool(document.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
