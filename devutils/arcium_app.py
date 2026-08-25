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

from helium_dev_bundle import (
    BundleError,
    _copy_source,
    _read_plist,
    _require_fresh_source,
    _safe_executable_name,
    _write_plist,
    resolve_bundle_paths,
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
        _write_plist(path, info, original)
        changed += 1
    return changed


def available_signing_identities(
    runner: CommandRunner = subprocess.run,
) -> tuple[str, ...]:
    try:
        result = runner(
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


def resolve_signing_identity(
    environ: dict[str, str] | os._Environ[str] | None = None,
    runner: CommandRunner = subprocess.run,
) -> str:
    values = os.environ if environ is None else environ
    requested = values.get(SIGNING_IDENTITY_ENV, "").strip()
    identities = available_signing_identities(runner)
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


def sign_and_verify(app_path: Path, identity: str) -> None:
    try:
        subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--deep",
                "--timestamp",
                "--options",
                "runtime",
                "--sign",
                identity,
                str(app_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
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


def package_arcium(
    root: str | os.PathLike[str],
    *,
    identity: str,
    signer: Signer = sign_and_verify,
    copy_runner: CommandRunner | None = None,
) -> dict[str, object]:
    paths = resolve_bundle_paths(root)
    source = _require_fresh_source(paths, require_dev_destination_absent=False)
    staging_root = Path(tempfile.mkdtemp(prefix=".arcium-bundle-", dir=paths.out_dir))
    staging_app = staging_root / "Arcium.app"
    output_app = paths.out_dir / "Arcium.app"
    try:
        copy_method = _copy_source(paths.source_app, staging_app, copy_runner)
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
        "display_name": ARCIUM_NAME,
        "executable_name": source["executable_name"],
        "plist_count": plist_count,
        "signing_identity": identity,
    }


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
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ArciumError(f"Arcium profile is not a safe directory: {destination}")
        return "existing"
    if source.is_symlink() or not source.is_dir():
        raise ArciumError(f"Helium profile is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.migration-{uuid.uuid4().hex}"
    try:
        before = _profile_snapshot(source)
        method = _copy_source(source, staging, copy_runner)
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
            path = staging / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        unsafe_links = tuple(path for path in staging.rglob("*") if path.is_symlink())
        if unsafe_links:
            raise ArciumError(
                "Helium profile contains symlinks that cannot be migrated safely"
            )
        if _profile_snapshot(source) != before:
            raise ArciumError("Helium profile changed during migration; quit Helium and retry")
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return method


def _profile_snapshot(root: Path) -> tuple[tuple[str, int, int, str | None], ...]:
    records: list[tuple[str, int, int, str | None]] = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        metadata = path.lstat()
        link_target = os.readlink(path) if path.is_symlink() else None
        records.append((relative, metadata.st_size, metadata.st_mtime_ns, link_target))
    return tuple(records)


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
    *,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> int:
    info = _read_plist(install_path / "Contents" / "Info.plist")
    if info.get("CFBundleIdentifier") != ARCIUM_BUNDLE_ID:
        raise ArciumError("installed Arcium has the wrong bundle identifier")
    executable_name = _safe_executable_name(info.get("CFBundleExecutable"))
    executable = install_path / "Contents" / "MacOS" / executable_name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ArciumError("installed Arcium executable is missing")
    process = popen(
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


def update_action(
    root: str | os.PathLike[str],
    *,
    home: str | os.PathLike[str] | None = None,
    install_path: Path = DEFAULT_INSTALL_PATH,
    ps_text: str | None = None,
    launch: bool = True,
) -> dict[str, object]:
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
        package = package_arcium(root, identity=identity)
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
    parser.add_argument("action", choices=("preflight", "update"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            document = preflight_action()
        else:
            document = update_action(args.root)
    except (ArciumError, BundleError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "action": f"arcium-{args.action}", "error": str(error)}))
        return 2
    _emit(document, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
