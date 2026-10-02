#!/usr/bin/env python3
"""Package, install, migrate, and launch Daniel's stable Arcium browser."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Mapping, Sequence

from build_execution import (
    ExecutionError,
    capture_material_inputs,
    component_runtime_libraries,
    material_guard,
    require_current_execution,
    verify_material_inputs,
)
from build_lane import LaneError, acquire_lane_lock
from helium_dev_bundle import (
    BundleError,
    BundlePaths,
    _copy_source,
    _read_plist,
    _require_fresh_source,
    _safe_executable_name,
    _write_plist,
    resolve_bundle_paths,
)
from profile_clone import ProfileCloneError, clone_profile_once
from helium_dev_runtime import (
    ProcessCohort, ProcessRecord, ProfileSpec, discover_chromium_processes,
    live_singleton_owner,
)


ARCIUM_BUNDLE_ID = "net.imput.arcium"
ARCIUM_NAME = "Arcium"
DEFAULT_SOURCE_PROFILE_NAME = "net.imput.helium"
DEFAULT_PROFILE_NAME = "Arcium"
DEFAULT_INSTALL_PATH = Path("/Applications/Arcium.app")
DEFAULT_PROFILE_DIRECTORY = "Default"
DEFAULT_FEATURES = ("HeliumFavoritesAndPins",)
SIGNING_IDENTITY_ENV = "ARCIUM_CODESIGN_IDENTITY"


class ArciumError(RuntimeError):
    """The stable Arcium application cannot be updated safely."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Signer = Callable[[Path, str], None]


def _application_support(home: str | os.PathLike[str] | None = None) -> Path:
    home_path = Path.home() if home is None else Path(home)
    return home_path / "Library" / "Application Support"


@contextmanager
def update_lock(home: str | os.PathLike[str] | None = None):
    lock_root = _application_support(home) / "Arcium Development"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / "update.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ArciumError("another Arcium update is already running") from error
        yield


def source_profile_path(home: str | os.PathLike[str] | None = None) -> Path:
    return _application_support(home) / DEFAULT_SOURCE_PROFILE_NAME


def arcium_profile_path(home: str | os.PathLike[str] | None = None) -> Path:
    return _application_support(home) / DEFAULT_PROFILE_NAME


def _rewrite_identifier(value: str) -> str:
    prefix = "net.imput.helium"
    if value == prefix:
        return ARCIUM_BUNDLE_ID
    if value.startswith(prefix + "."):
        return ARCIUM_BUNDLE_ID + value[len(prefix) :]
    return value


def rewrite_arcium_metadata(app_path: Path) -> int:
    """Give the copied app a stable identity without renaming executables."""

    plist_paths = sorted(app_path.rglob("Info.plist"))
    root_plist = app_path / "Contents" / "Info.plist"
    if root_plist not in plist_paths:
        raise ArciumError("copied Arcium bundle has no root Info.plist")
    changed = 0
    for path in plist_paths:
        original = path.read_bytes()
        info = _read_plist(path)
        executable = info.get("CFBundleExecutable")
        if executable is not None:
            _safe_executable_name(executable)
        bundle_id = info.get("CFBundleIdentifier")
        if isinstance(bundle_id, str) and bundle_id:
            info["CFBundleIdentifier"] = _rewrite_identifier(bundle_id)
        if path == root_plist:
            info["CFBundleIdentifier"] = ARCIUM_BUNDLE_ID
            info["CFBundleDisplayName"] = ARCIUM_NAME
            info["CFBundleName"] = ARCIUM_NAME
            # Chromium uses this for Dock and LaunchServices profile selection.
            info["CrProductDirName"] = DEFAULT_PROFILE_NAME
        _write_plist(path, info, original)
        changed += 1
    return changed


def available_signing_identities() -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ArciumError("could not inspect macOS code-signing identities") from error
    return tuple(
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.search(r'^\s*\d+\)\s+[0-9A-F]+\s+"(.+)"\s*$', line))
    )


def resolve_signing_identity() -> str:
    requested = os.environ.get(SIGNING_IDENTITY_ENV, "").strip()
    identities = available_signing_identities()
    if requested:
        if requested not in identities:
            raise ArciumError(
                f"{SIGNING_IDENTITY_ENV} does not name an available signing identity"
            )
        return requested
    developer_ids = tuple(
        value for value in identities if value.startswith("Developer ID Application:")
    )
    if len(developer_ids) == 1:
        return developer_ids[0]
    if not developer_ids:
        raise ArciumError(
            "Arcium needs a stable Developer ID signing identity for real Keychain access"
        )
    raise ArciumError(
        f"multiple Developer ID identities are available; set {SIGNING_IDENTITY_ENV}"
    )


def _signing_targets(app_path: Path) -> list[Path]:
    """Visit real code inside versioned frameworks, without following aliases."""

    targets = [app_path]
    macho_headers = {
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
    }
    for directory, subdirs, filenames in os.walk(app_path, followlinks=False):
        parent = Path(directory)
        subdirs[:] = [name for name in subdirs if not (parent / name).is_symlink()]
        targets.extend(
            parent / name
            for name in subdirs
            if Path(name).suffix in {".app", ".framework", ".xpc", ".appex"}
        )
        for name in filenames:
            path = parent / name
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as handle:
                if handle.read(4) in macho_headers:
                    targets.append(path)
    return sorted(targets, key=lambda path: (-len(path.parts), str(path)))


def _signing_entitlements(target: Path, app_path: Path) -> Path | None:
    # Match the existing release signing policy. JIT belongs only to the
    # renderer and GPU helpers, never to every binary in the application.
    name = None
    if target == app_path:
        name = "app-entitlements.plist"
    elif target.name.endswith(" Helper (Renderer).app"):
        name = "helper-renderer-entitlements.plist"
    elif target.name.endswith(" Helper (GPU).app"):
        name = "helper-gpu-entitlements.plist"
    elif target.name.endswith(" Helper.app") or target.name == "Helium Framework.framework":
        name = "helper-entitlements.plist"
    return Path(__file__).resolve().parents[1] / "entitlements" / name if name else None


def sign_and_verify(app_path: Path, identity: str) -> None:
    try:
        for target in _signing_targets(app_path):
            command = [
                "/usr/bin/codesign",
                "--force",
                "--timestamp",
                "--options",
                "runtime",
                "--sign",
                identity,
            ]
            entitlements = _signing_entitlements(target, app_path)
            if entitlements is not None:
                command.extend(["--entitlements", str(entitlements)])
            command.append(str(target))
            subprocess.run(command, check=True, capture_output=True, text=True)
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ArciumError("Arcium signing or verification failed") from error


def _replace_directory(
    candidate: Path,
    destination: Path,
    *,
    verifier: Callable[[Path], None] | None = None,
    retain_previous: bool = False,
    preserve_published: bool = False,
) -> Path | None:
    """Restore pre-publication failures; installed apps retain published state."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = destination.parent / f".{destination.name}.previous-{uuid.uuid4().hex}"
    candidate_identity = candidate.lstat()
    published = False
    try:
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                raise ArciumError(f"refusing to replace non-directory: {destination}")
            os.replace(destination, previous)
        os.replace(candidate, destination)
        published = True
        if verifier is not None:
            verifier(destination)
    except BaseException as error:
        if not published:
            try:
                destination_identity = destination.lstat()
                published = (destination_identity.st_dev, destination_identity.st_ino) == (
                    candidate_identity.st_dev, candidate_identity.st_ino,
                )
            except FileNotFoundError:
                pass
        if published and preserve_published:
            recovery = f" Previous bundle retained at {previous}." if previous.exists() else ""
            raise ArciumError(
                f"Arcium replacement failed after publication at {destination}.{recovery} "
                f"Profile was not rolled back: {error}"
            ) from error
        if published and destination.exists():
            shutil.rmtree(destination)
        if not destination.exists() and previous.exists():
            os.replace(previous, destination)
        raise
    if retain_previous and previous.exists():
        return previous
    if previous.exists():
        shutil.rmtree(previous)
    return None


def copy_component_libraries(out_dir: Path, app_path: Path) -> int:
    """Make a component-build application self-contained before signing it."""

    try:
        libraries = component_runtime_libraries(out_dir)
    except ExecutionError as error:
        raise ArciumError(str(error)) from error
    if not libraries:
        return 0

    frameworks = app_path / "Contents" / "Frameworks"
    if not frameworks.is_dir():
        raise ArciumError("copied Arcium bundle has no Frameworks directory")
    for source in libraries:
        shutil.copy2(source, frameworks / source.name)
    return len(libraries)


def _package_arcium_locked(
    paths: BundlePaths,
    *,
    identity: str,
    signer: Signer = sign_and_verify,
    copy_runner: CommandRunner | None = None,
) -> dict[str, object]:
    try:
        material_at_entry = capture_material_inputs(paths.worktree)
        require_current_execution(
            paths.worktree,
            paths.source_dir.parent,
            lane=os.environ.get("HELIUM_DEV_LANE", "worktree"),
        )
    except ExecutionError as error:
        raise ArciumError(str(error)) from error
    source = _require_fresh_source(paths, require_dev_destination_absent=False)
    staging_root = Path(tempfile.mkdtemp(prefix=".arcium-bundle-", dir=paths.out_dir))
    staging_app = staging_root / "Arcium.app"
    output_app = paths.out_dir / "Arcium.app"
    try:
        copy_method = _copy_source(paths.source_app, staging_app, copy_runner)
        component_library_count = copy_component_libraries(paths.out_dir, staging_app)
        plist_count = rewrite_arcium_metadata(staging_app)
        signer(staging_app, identity)
        try:
            verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
        except ExecutionError as error:
            raise ArciumError(str(error)) from error
        _replace_directory(staging_app, output_app)
        staging_root.rmdir()
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    return {
        "app_path": str(output_app),
        "bundle_identifier": ARCIUM_BUNDLE_ID,
        "copy_method": copy_method,
        "component_library_count": component_library_count,
        "display_name": ARCIUM_NAME,
        "executable_name": source["executable_name"],
        "plist_count": plist_count,
        "signing_identity": identity,
    }


def package_arcium(
    root: str | os.PathLike[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    identity: str,
    signer: Signer = sign_and_verify,
    copy_runner: CommandRunner | None = None,
) -> dict[str, object]:
    """Package stable Arcium while owning the selected generated lane."""

    paths = resolve_bundle_paths(root, build_root)
    owner = {
        "action": "arcium-package",
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(paths.worktree),
    }
    try:
        material_at_entry = capture_material_inputs(paths.worktree)
        with acquire_lane_lock(
            paths.source_dir.parent / ".arcium" / "lane.lock", owner
        ), material_guard(
            paths.worktree, paths.source_dir.parent, expected=material_at_entry
        ):
            return _package_arcium_locked(
                paths,
                identity=identity,
                signer=signer,
                copy_runner=copy_runner,
            )
    except (LaneError, ExecutionError) as error:
        raise ArciumError(str(error)) from error


def process_conflicts(
    ps_text: str,
    *,
    source_profile: Path | None,
    target_profile: Path,
    install_path: Path,
) -> tuple[str, ...]:
    conflicts: list[str] = []
    for line in ps_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split(maxsplit=1)
        command = fields[1] if len(fields) == 2 else ""
        is_release = source_profile is not None and "/Helium.app/Contents/MacOS/Helium" in stripped
        is_arcium = command.startswith(str(install_path / "Contents" / "MacOS") + "/") or (
            command.startswith(str(install_path / "Contents") + "/")
            and re.search(r"\.app/Contents/MacOS/", command) is not None
        )
        source_selected = source_profile is not None and f"--user-data-dir={source_profile}" in stripped
        target_selected = f"--user-data-dir={target_profile}" in stripped
        is_dev = "/Helium Dev.app/Contents/MacOS/Helium" in stripped
        safe_dev = (
            is_dev
            and "--use-mock-keychain" in stripped
            and "--user-data-dir=" in stripped
            and not source_selected
            and not target_selected
        )
        if is_release or is_arcium or source_selected or target_selected or (is_dev and not safe_dev):
            conflicts.append(stripped.split(maxsplit=1)[0])
    return tuple(dict.fromkeys(conflicts))


def _ps_snapshot(runner: CommandRunner = subprocess.run) -> str:
    result = runner(
        ["/bin/ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def require_closed(
    *,
    source_profile: Path | None,
    target_profile: Path,
    install_path: Path,
    ps_text: str | None = None,
) -> None:
    snapshot = _ps_snapshot() if ps_text is None else ps_text
    conflicts = process_conflicts(
        snapshot,
        source_profile=source_profile,
        target_profile=target_profile,
        install_path=install_path,
    )
    owners = tuple(str(pid) for profile in (source_profile, target_profile)
                   if profile is not None and (pid := _profile_owner(profile)) is not None)
    conflicts = tuple(dict.fromkeys((*conflicts, *owners)))
    if conflicts:
        raise ArciumError(
            "quit browsers using the required profiles before updating (matching PIDs: "
            + ", ".join(conflicts)
            + ")"
        )


def _profile_owner(profile: Path) -> int | None:
    return live_singleton_owner(ProfileSpec("normal", None, profile))


def installed_executable(install_path: Path) -> Path:
    info = _read_plist(install_path / "Contents" / "Info.plist")
    return install_path / "Contents" / "MacOS" / _safe_executable_name(info.get("CFBundleExecutable"))


def _ps_parent_snapshot() -> dict[int, int]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid="], check=True, capture_output=True, text=True,
    )
    parents = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*(\d+)\s+(\d+)\s*", line)
        if match is None or int(match[1]) in parents:
            raise ArciumError("process ancestry is malformed or ambiguous")
        parents[int(match[1])] = int(match[2])
    return parents


def _installed_helper_executables(install_path: Path) -> tuple[Path, ...]:
    bundle = install_path.resolve()
    helpers = []
    for app in (install_path / "Contents/Frameworks").rglob("*.app"):
        try:
            info = _read_plist(app / "Contents/Info.plist")
            identifier = info.get("CFBundleIdentifier")
            if not isinstance(identifier, str) or not identifier.startswith(ARCIUM_BUNDLE_ID + "."):
                continue
            executable = app / "Contents/MacOS" / _safe_executable_name(info.get("CFBundleExecutable"))
            executable.resolve().relative_to(bundle)
            if executable.is_file() and os.access(executable, os.X_OK):
                helpers.append(executable)
        except (ArciumError, BundleError, OSError, ValueError):
            continue
    return tuple(helpers)


def installed_processes(
    snapshot: str, install_path: Path, profile: Path, *,
    parent_pids: Mapping[int, int] | None = None,
) -> ProcessCohort:
    """Recognize explicit launches and verified Dock/Finder launches alike."""
    if not install_path.exists():
        return ProcessCohort((), None)
    verify_profile_identity(install_path)
    executable = installed_executable(install_path)
    explicit = discover_chromium_processes(
        snapshot, executable_path=executable, user_data_dir=profile,
    )
    records = list(explicit.records)
    # A missing switch is meaningful only when the bundle's product directory
    # resolves to this root. The singleton lock independently proves ownership.
    if profile == arcium_profile_path():
        try:
            verify_profile_identity(install_path)
        except (ArciumError, BundleError, OSError):
            pass
        else:
            owner = _profile_owner(profile)
            for line in snapshot.splitlines():
                match = re.fullmatch(r"\s*(\d+)\s+(.+?)\s*", line)
                if match is None or int(match[1]) != owner:
                    continue
                command = match[2]
                if command != str(executable) and not command.startswith(str(executable) + " "):
                    continue
                if re.search(r"(?:^|\s)--(?:user-data-dir|type)(?:=|\s|$)", command):
                    continue
                records.append(ProcessRecord(owner, command, (str(executable),)))
    mains = [record for record in records
             if not re.search(r"(?:^|\s)--type(?:=|\s|$)", record.command)]
    if len(mains) != 1:
        return ProcessCohort(tuple(mains), None)
    main = mains[0]
    records = [main]
    if _profile_owner(profile) != main.pid:
        return ProcessCohort(tuple(records), main.pid)
    default_main = profile == arcium_profile_path() and not re.search(
        r"(?:^|\s)--user-data-dir(?:=|\s|$)", main.command,
    )
    candidates = []
    for helper in _installed_helper_executables(install_path):
        explicit_helpers = discover_chromium_processes(
            snapshot, executable_path=helper, user_data_dir=profile,
        )
        candidates.extend(record for record in explicit_helpers.records
                          if re.search(r"(?:^|\s)--type(?:=|\s|$)", record.command))
        if default_main:
            for line in snapshot.splitlines():
                match = re.fullmatch(r"\s*(\d+)\s+(.+?)\s*", line)
                if match is None:
                    continue
                command = match[2]
                if not command.startswith(str(helper) + " "):
                    continue
                if re.search(r"(?:^|\s)--user-data-dir(?:=|\s|$)", command):
                    continue
                if re.search(r"(?:^|\s)--type(?:=|\s|$)", command):
                    candidates.append(ProcessRecord(int(match[1]), command, (str(helper),)))
    if candidates:
        parents = _ps_parent_snapshot() if parent_pids is None else parent_pids
        unique = {record.pid: record for record in candidates
                  if sum(other.pid == record.pid for other in candidates) == 1}

        def owned_helper(pid: int) -> bool:
            seen = set()
            while pid != main.pid:
                if pid in seen or pid not in unique:
                    return False
                seen.add(pid)
                parent = parents.get(pid)
                if type(parent) is not int or parent <= 0:
                    return False
                pid = parent
            return True

        records.extend(record for pid, record in unique.items() if owned_helper(pid))
    return ProcessCohort(tuple(sorted(records, key=lambda record: record.pid)), main.pid)


def restart_candidate(
    snapshot: str, *, source_profile: Path | None, target_profile: Path, install_path: Path,
    parent_pids: Mapping[int, int] | None = None,
) -> int | None:
    """Permit only one exact installed browser; other profile owners still block."""
    cohort = installed_processes(snapshot, install_path, target_profile, parent_pids=parent_pids)
    if any(re.search(r"(?:^|\s)--use-mock-keychain(?:=|\s|$)", record.command)
           for record in cohort.records):
        raise ArciumError("persistent Arcium is running with a mock Keychain; quit it before updating")
    conflicts = set(process_conflicts(
        snapshot, source_profile=source_profile,
        target_profile=target_profile, install_path=install_path,
    ))
    for profile in (source_profile, target_profile):
        owner = _profile_owner(profile) if profile is not None else None
        if owner is not None:
            if profile == source_profile or owner != cohort.main_pid:
                raise ArciumError("another live browser owns a profile required by Arcium")
            conflicts.add(str(owner))
    if not conflicts:
        return None
    if cohort.main_pid is None or conflicts - {str(pid) for pid in cohort.pids}:
        raise ArciumError(
            "restart requires one exact installed Arcium using its persistent profile; "
            "quit other Helium/Arcium profile owners first"
        )
    if _profile_owner(target_profile) != cohort.main_pid:
        raise ArciumError("restart requires the installed Arcium to own its persistent profile")
    return cohort.main_pid


def request_graceful_quit(pid: int, install_path: Path) -> None:
    # NSRunningApplication addresses the freshly identified PID, checks its
    # executable again, and asks for a normal quit. Never forceTerminate/kill.
    script = '''ObjC.import('AppKit');
function run(argv) {
    const app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(Number(argv[0]));
    if (app.isNil() || app.terminated) return;
    if (ObjC.unwrap(app.executableURL.path) !== argv[1] ||
        ObjC.unwrap(app.bundleIdentifier) !== argv[2]) throw Error('Arcium process changed');
    if (!app.terminate) throw Error('Arcium refused to quit');
}'''
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", script, str(pid),
             str(installed_executable(install_path)), ARCIUM_BUNDLE_ID],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ArciumError("could not request a normal Arcium quit; installed app was not replaced") from error


def quit_for_restart(
    *, source_profile: Path | None, target_profile: Path, install_path: Path, timeout: float = 15.0
) -> None:
    arguments = dict(source_profile=source_profile, target_profile=target_profile,
                     install_path=install_path)
    pid = restart_candidate(_ps_snapshot(), **arguments)
    if pid is None:
        return
    # Refresh the profile/executable match immediately before requesting quit.
    if restart_candidate(_ps_snapshot(), **arguments) != pid:
        raise ArciumError("Arcium process changed before restart; retry the command")
    request_graceful_quit(pid, install_path)
    deadline = time.monotonic() + timeout
    while True:
        snapshot = _ps_snapshot()
        if not process_conflicts(snapshot, **arguments):
            require_closed(**arguments, ps_text=snapshot)
            return
        if time.monotonic() >= deadline:
            raise ArciumError(
                "Arcium did not finish quitting; resolve any open dialog and retry. "
                "Installed app was not replaced"
            )
        time.sleep(0.2)


def initialize_profile(
    source: Path,
    destination: Path,
    *,
    copy_runner: CommandRunner | None = None,
) -> str:
    try:
        return clone_profile_once(source, destination, copy_runner=copy_runner)
    except ProfileCloneError as error:
        raise ArciumError(str(error)) from error


@contextmanager
def prepared_install(candidate: Path, destination: Path):
    """Copy and verify on the destination volume before interrupting a browser."""
    if candidate.is_symlink() or not candidate.is_dir():
        raise ArciumError(f"Arcium candidate is missing: {candidate}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.install-{uuid.uuid4().hex}"
    try:
        method = _copy_source(candidate, staging, None)
        verify_installed_arcium(staging)
        yield staging, method
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def install_arcium(candidate: Path, destination: Path) -> str:
    with prepared_install(candidate, destination) as (staging, method):
        _replace_directory(
            staging, destination, verifier=verify_installed_arcium, preserve_published=True,
        )
    return method


def verify_profile_identity(destination: Path) -> dict[str, object]:
    info = _read_plist(destination / "Contents" / "Info.plist")
    if info.get("CFBundleIdentifier") != ARCIUM_BUNDLE_ID:
        raise ArciumError("installed Arcium has the wrong bundle identifier")
    if info.get("CrProductDirName") != DEFAULT_PROFILE_NAME:
        raise ArciumError("Arcium bundle has the wrong default profile directory; repackage it before launching")
    return info


def verify_installed_arcium(destination: Path) -> None:
    verify_profile_identity(destination)
    try:
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ArciumError("installed Arcium signature verification failed") from error


def launch_arcium(
    install_path: Path,
    profile: Path,
) -> int:
    info = verify_profile_identity(install_path)
    executable_name = _safe_executable_name(info.get("CFBundleExecutable"))
    executable = install_path / "Contents" / "MacOS" / executable_name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ArciumError("installed Arcium executable is missing")
    process = subprocess.Popen(
        [
            str(executable),
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--enable-features=" + ",".join(DEFAULT_FEATURES),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def verify_arcium_launch(install_path: Path, profile: Path, pid: int) -> None:
    deadline = time.monotonic() + 10.0
    profile_spec = ProfileSpec("normal", None, profile, DEFAULT_PROFILE_DIRECTORY)
    observed_since: float | None = None
    while time.monotonic() < deadline:
        cohort = installed_processes(_ps_snapshot(), install_path, profile)
        if cohort.main_pid == pid and live_singleton_owner(profile_spec) == pid:
            if observed_since is None:
                observed_since = time.monotonic()
            elif time.monotonic() - observed_since >= 1.0:
                return
        else:
            observed_since = None
        time.sleep(0.2)
    raise ArciumError("Arcium launch did not produce the expected process and profile")


def _update_action_locked(
    paths: BundlePaths,
    *,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    launch: bool = True,
    restart: bool = False,
) -> dict[str, object]:
    try:
        material_at_entry = capture_material_inputs(paths.worktree)
        require_current_execution(
            paths.worktree,
            paths.source_dir.parent,
            lane=os.environ.get("HELIUM_DEV_LANE", "worktree"),
        )
    except ExecutionError as error:
        raise ArciumError(str(error)) from error
    source_profile = source_profile_path(home)
    target_profile = arcium_profile_path(home)
    with update_lock(home):
        profile_arguments = dict(source_profile=source_profile if not target_profile.is_dir() else None,
                                 target_profile=target_profile, install_path=install_path)
        if restart:
            restart_candidate(_ps_snapshot(), **profile_arguments)
        else:
            require_closed(**profile_arguments, ps_text=ps_text)
        identity = resolve_signing_identity()
        # Validate an existing destination, or seed only while both browsers
        # are closed. Profile preparation must fail before requesting a quit.
        if not target_profile.exists() and not target_profile.is_symlink():
            require_closed(**profile_arguments)
        migration = initialize_profile(source_profile, target_profile)
        started = time.monotonic()
        package = _package_arcium_locked(paths, identity=identity)
        with prepared_install(Path(str(package["app_path"])), install_path) as (staging, install_method):
            preparation_seconds = time.monotonic() - started
            print(f"arcium: replacement prepared in {preparation_seconds:.1f}s", file=sys.stderr)
            handoff_started = time.monotonic()
            verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
            if restart:
                quit_for_restart(**profile_arguments)
            require_closed(**profile_arguments)
            verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
            previous = _replace_directory(
                staging, install_path, verifier=verify_installed_arcium, retain_previous=True,
                preserve_published=True,
            )
            try:
                require_closed(**profile_arguments)
                verify_material_inputs(paths.worktree, paths.source_dir.parent, material_at_entry)
                pid = launch_arcium(install_path, target_profile) if launch else None
                if pid is not None:
                    verify_arcium_launch(install_path, target_profile, pid)
            except BaseException as error:
                recovery = f" Previous bundle retained at {previous}." if previous else ""
                raise ArciumError(f"Arcium handoff failed.{recovery} Profile was not rolled back: {error}") from error
            if previous is not None:
                try:
                    shutil.rmtree(previous)
                except OSError:
                    print(f"arcium: launch verified; could not remove previous bundle at {previous}", file=sys.stderr)
            handoff_seconds = time.monotonic() - handoff_started
    return {
        "ok": True,
        "action": "arcium",
        "app_path": str(install_path),
        "bundle_identifier": ARCIUM_BUNDLE_ID,
        "profile": str(target_profile),
        "profile_initialization": migration,
        "install_method": install_method,
        "signing_identity": identity,
        "mock_keychain": False,
        "pid": pid,
        "source_profile_unchanged": True,
        "restart": restart,
        "preparation_seconds": round(preparation_seconds, 3),
        "handoff_seconds": round(handoff_seconds, 3),
    }


def update_action(
    root: str | os.PathLike[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    launch: bool = True,
    restart: bool = False,
) -> dict[str, object]:
    """Update stable Arcium while owning the complete generated-lane transaction."""

    paths = resolve_bundle_paths(root, build_root)
    owner = {
        "action": "arcium",
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(paths.worktree),
    }
    try:
        material_at_entry = capture_material_inputs(paths.worktree)
        with acquire_lane_lock(
            paths.source_dir.parent / ".arcium" / "lane.lock", owner
        ), material_guard(
            paths.worktree, paths.source_dir.parent, expected=material_at_entry
        ):
            return _update_action_locked(
                paths,
                home=home,
                install_path=install_path,
                ps_text=ps_text,
                launch=launch,
                restart=restart,
            )
    except (LaneError, ExecutionError) as error:
        raise ArciumError(str(error)) from error


def preflight_action(
    *,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    restart: bool = False,
) -> dict[str, object]:
    source_profile = source_profile_path(home)
    target_profile = arcium_profile_path(home)
    arguments = dict(source_profile=source_profile if not target_profile.is_dir() else None,
                     target_profile=target_profile, install_path=install_path)
    if restart:
        restart_candidate(_ps_snapshot() if ps_text is None else ps_text, **arguments)
    else:
        require_closed(**arguments, ps_text=ps_text)
    identity = resolve_signing_identity()
    if not target_profile.exists() and not source_profile.is_dir():
        raise ArciumError(f"Helium profile is missing: {source_profile}")
    return {
        "ok": True,
        "action": "arcium-preflight",
        "profile": str(target_profile),
        "profile_initialization": "existing" if target_profile.is_dir() else "required",
        "signing_identity": identity,
    }


def status_action(*, install_path: Path = DEFAULT_INSTALL_PATH) -> dict[str, object]:
    """Read bundle identity and live ownership without opening or changing a profile."""
    profile = arcium_profile_path()
    verify_installed_arcium(install_path)
    snapshot = _ps_snapshot()
    cohort = installed_processes(snapshot, install_path, profile)
    executable = re.escape(str(installed_executable(install_path)))
    mains = []
    for line in snapshot.splitlines():
        match = re.match(rf"^\s*(\d+)\s+({executable}(?:\s.*)?$)", line)
        if match is not None and not re.search(r"(?:^|\s)--type(?:=|\s|$)", match[2]):
            mains.append(ProcessRecord(int(match[1]), match[2], ()))
    owner = _profile_owner(profile)
    mock_keychain_pids = sorted({record.pid for record in mains
                               if re.search(r"(?:^|\s)--use-mock-keychain(?:=|\s|$)", record.command)})
    main_pids = sorted({record.pid for record in mains})
    expected_pid = cohort.main_pid if owner == cohort.main_pid else None
    unexpected_pids = [pid for pid in main_pids if pid != expected_pid]
    running = expected_pid is not None and main_pids == [expected_pid]
    stopped = not main_pids and owner is None
    mock_keychain = bool(mock_keychain_pids)
    return {
        "ok": (running and not mock_keychain) or stopped,
        "action": "arcium-status",
        "app_path": str(install_path),
        "bundle_identifier": ARCIUM_BUNDLE_ID,
        "product_directory_name": DEFAULT_PROFILE_NAME,
        "profile": str(profile),
        "pid": cohort.main_pid,
        "main_pids": main_pids,
        "unexpected_pids": unexpected_pids,
        "mock_keychain_pids": mock_keychain_pids,
        "profile_owner_pid": owner,
        "state": "running" if running else ("stopped" if stopped else "profile-mismatch"),
        "mock_keychain": mock_keychain,
    }


def _emit(document: dict[str, object], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(document, sort_keys=True))
    elif document.get("action") == "arcium-status":
        print(f"arcium: {document['state']}, PID {document['pid']}, profile owner {document['profile_owner_pid']}")
        if document["unexpected_pids"]:
            print(f"arcium: unexpected installed main PIDs {document['unexpected_pids']}")
        if document["mock_keychain_pids"]:
            print(f"arcium: mock Keychain PIDs {document['mock_keychain_pids']}")
        print(f"arcium: bundle {document['app_path']}")
        print(f"arcium: profile root {document['profile']}")
        print(f"arcium: mock Keychain {document['mock_keychain']}")
    elif document.get("action") == "arcium-preflight":
        print("arcium: preflight passed")
    else:
        action = "installed and launched" if document.get("pid") is not None else "installed"
        print(f"arcium: {action} {document.get('app_path')}")
        print(f"arcium: handoff took {document.get('handoff_seconds')}s")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--build-root")
    parser.add_argument("action", choices=("preflight", "update", "status"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--restart", action="store_true", help="prepare before requesting a normal quit of the exact installed Arcium")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            document = status_action()
        elif args.action == "preflight":
            document = preflight_action(restart=args.restart)
        else:
            document = update_action(args.root, build_root=args.build_root, restart=args.restart)
    except (
        ArciumError,
        BundleError,
        ExecutionError,
        LaneError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(str(error), file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "action": f"arcium-{args.action}", "error": str(error)}))
        return 2
    _emit(document, args.json)
    return 0 if document.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
