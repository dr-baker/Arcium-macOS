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
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Sequence

from build_execution import ExecutionError, require_current_execution
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


def _replace_directory(candidate: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = destination.parent / f".{destination.name}.previous-{uuid.uuid4().hex}"
    moved_previous = False
    try:
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                raise ArciumError(f"refusing to replace non-directory: {destination}")
            os.replace(destination, previous)
            moved_previous = True
        os.replace(candidate, destination)
    except Exception:
        if moved_previous and not destination.exists() and previous.exists():
            os.replace(previous, destination)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def copy_component_libraries(out_dir: Path, app_path: Path) -> int:
    """Make a component-build application self-contained before signing it."""

    args_path = out_dir / "args.gn"
    if not args_path.is_file():
        raise ArciumError("Chromium build arguments are missing")
    args = args_path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^\s*is_component_build\s*=\s*true\s*$", args):
        return 0

    frameworks = app_path / "Contents" / "Frameworks"
    if not frameworks.is_dir():
        raise ArciumError("copied Arcium bundle has no Frameworks directory")
    libraries = sorted(out_dir.glob("*.dylib"))
    if not libraries:
        raise ArciumError("component build has no runtime libraries")
    for source in libraries:
        if not source.is_file() or source.is_symlink():
            raise ArciumError(f"unsafe component runtime library: {source}")
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
        with acquire_lane_lock(
            paths.source_dir.parent / ".arcium" / "lane.lock", owner
        ):
            return _package_arcium_locked(
                paths,
                identity=identity,
                signer=signer,
                copy_runner=copy_runner,
            )
    except LaneError as error:
        raise ArciumError(str(error)) from error


def process_conflicts(
    ps_text: str,
    *,
    source_profile: Path,
    target_profile: Path,
    install_path: Path,
) -> tuple[str, ...]:
    conflicts: list[str] = []
    for line in ps_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        is_release = "/Helium.app/Contents/MacOS/Helium" in stripped
        is_arcium = str(install_path / "Contents" / "MacOS" / "Helium") in stripped
        source_selected = f"--user-data-dir={source_profile}" in stripped
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
    source_profile: Path,
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
    if conflicts:
        raise ArciumError(
            "quit installed Helium and Arcium before updating (matching PIDs: "
            + ", ".join(conflicts)
            + ")"
        )


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


def install_arcium(candidate: Path, destination: Path) -> str:
    if candidate.is_symlink() or not candidate.is_dir():
        raise ArciumError(f"Arcium candidate is missing: {candidate}")
    staging = destination.parent / f".{destination.name}.install-{uuid.uuid4().hex}"
    try:
        method = _copy_source(candidate, staging, None)
        _replace_directory(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return method


def verify_installed_arcium(destination: Path) -> None:
    info = _read_plist(destination / "Contents" / "Info.plist")
    if info.get("CFBundleIdentifier") != ARCIUM_BUNDLE_ID:
        raise ArciumError("installed Arcium has the wrong bundle identifier")
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
    info = _read_plist(install_path / "Contents" / "Info.plist")
    if info.get("CFBundleIdentifier") != ARCIUM_BUNDLE_ID:
        raise ArciumError("installed Arcium has the wrong bundle identifier")
    executable_name = _safe_executable_name(info.get("CFBundleExecutable"))
    executable = install_path / "Contents" / "MacOS" / executable_name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ArciumError("installed Arcium executable is missing")
    process = subprocess.Popen(
        [
            str(executable),
            f"--user-data-dir={profile}",
            f"--profile-directory={DEFAULT_PROFILE_DIRECTORY}",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--enable-features=" + ",".join(DEFAULT_FEATURES),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def _update_action_locked(
    paths: BundlePaths,
    *,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    launch: bool = True,
) -> dict[str, object]:
    try:
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
        require_closed(
            source_profile=source_profile,
            target_profile=target_profile,
            install_path=install_path,
            ps_text=ps_text,
        )
        identity = resolve_signing_identity()
        migration = initialize_profile(source_profile, target_profile)
        package = _package_arcium_locked(paths, identity=identity)
        install_method = install_arcium(Path(str(package["app_path"])), install_path)
        verify_installed_arcium(install_path)
        require_closed(
            source_profile=source_profile,
            target_profile=target_profile,
            install_path=install_path,
            ps_text=ps_text,
        )
        pid = launch_arcium(install_path, target_profile) if launch else None
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
    }


def update_action(
    root: str | os.PathLike[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    launch: bool = True,
) -> dict[str, object]:
    """Update stable Arcium while owning the complete generated-lane transaction."""

    paths = resolve_bundle_paths(root, build_root)
    owner = {
        "action": "arcium",
        "lane": os.environ.get("HELIUM_DEV_LANE", "worktree"),
        "worktree": str(paths.worktree),
    }
    try:
        with acquire_lane_lock(
            paths.source_dir.parent / ".arcium" / "lane.lock", owner
        ):
            return _update_action_locked(
                paths,
                home=home,
                install_path=install_path,
                ps_text=ps_text,
                launch=launch,
            )
    except LaneError as error:
        raise ArciumError(str(error)) from error


def preflight_action(
    *,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
) -> dict[str, object]:
    source_profile = source_profile_path(home)
    target_profile = arcium_profile_path(home)
    require_closed(
        source_profile=source_profile,
        target_profile=target_profile,
        install_path=install_path,
        ps_text=ps_text,
    )
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


def _emit(document: dict[str, object], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(document, sort_keys=True))
    elif document.get("action") == "arcium-preflight":
        print("arcium: preflight passed")
    else:
        print(f"arcium: installed and launched {document.get('app_path')}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--build-root")
    parser.add_argument("action", choices=("preflight", "update"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            document = preflight_action()
        else:
            document = update_action(args.root, build_root=args.build_root)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
