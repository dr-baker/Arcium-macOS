"""Install the current build as /Applications/Arcium.app and launch it.

`he arcium` installs while Arcium is closed. `he arcium iterate` prepares the
replacement first, asks the running Arcium to quit normally, then swaps and
relaunches. Neither forces a quit, and neither touches profile data: the
persistent profile is created once from the Helium profile and then left
alone. Before the new bundle is published, a failure restores the previous
one. After publication there is no automatic rollback, because the new
version may already have opened and migrated the profile; both bundles are
kept and reported.

Usage: python3 -m arcium.install --build-dir DIR {install,iterate,status} [--json]
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

from he import apps
from he.common import HeError
from he.profiles import clone_once

from .bundle import (ARCIUM_BUNDLE_ID, ArciumError, copy_component_libraries, rewrite_metadata, sign,
                     signing_identity, verify_identity)

FEATURES = ("HeliumFavoritesAndPins",)
LOG_RETENTION = 8
QUIT_TIMEOUT = 15.0


def install_path() -> Path:
    return Path(os.environ.get("HELIUM_ARCIUM_INSTALL_PATH", "/Applications/Arcium.app"))


def _support() -> Path:
    return Path.home() / "Library" / "Application Support"


def arcium_profile() -> Path:
    return _support() / "Arcium"


def helium_profile() -> Path:
    return _support() / "net.imput.helium"


@contextmanager
def install_lock():
    """One update at a time, from any build dir (same file as the previous tooling)."""
    path = _support() / "Arcium Development" / "update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ArciumError("another Arcium update is running") from None
        yield


def running(app: Path, profile: Path) -> dict | None:
    """Who owns the Arcium profile, and whether it is this installed app."""
    pid = apps.profile_owner(profile)
    if pid is None:
        return None
    path = apps.process_path(pid)
    installed = app.is_dir() and path == str(apps.executable(app).resolve())
    command = apps.command_lines().get(pid, "")
    return {"pid": pid, "executable": path, "installed": installed, "mock_keychain": "--use-mock-keychain" in command}


def _quit(pid: int, app: Path) -> None:
    """Ask for a normal quit through NSRunningApplication, never forcing it."""
    if os.environ.get("HELIUM_ARCIUM_QUIT") == "term":  # test seam for stub browsers
        os.kill(pid, signal.SIGTERM)
        return
    script = """ObjC.import('AppKit');
function run(argv) {
    const app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(Number(argv[0]));
    if (app.isNil() || app.terminated) return;
    if (ObjC.unwrap(app.executableURL.path) !== argv[1] || ObjC.unwrap(app.bundleIdentifier) !== argv[2])
        throw Error('Arcium process changed');
    if (!app.terminate) throw Error('Arcium refused to quit');
}"""
    result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script, str(pid),
                             str(apps.executable(app).resolve()), ARCIUM_BUNDLE_ID],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise ArciumError(f"could not ask Arcium to quit: {result.stderr.strip()}; nothing was replaced")


def package(out_dir: Path, staging: Path, identity: str) -> dict:
    """Stage Arcium.app from the build output on the install volume."""
    source = out_dir / "Helium.app"
    if not apps.executable(source).is_file():
        raise ArciumError(f"no built Helium.app in {out_dir}; run he build first")
    method = apps.copy_app(source, staging)
    libraries = copy_component_libraries(out_dir, staging)
    rewrite_metadata(staging)
    sign(staging, identity)
    verify_identity(staging)
    return {"copy": method, "component_libraries": libraries}


def _publish(staging: Path, app: Path) -> Path | None:
    """Swap the staged bundle in, keeping the previous one aside.

    Returns the previous bundle's path. A failure before the swap completes
    puts the previous bundle back.
    """
    previous = app.parent / f".{app.name}.previous-{uuid.uuid4().hex}"
    moved = False
    try:
        if app.exists() or app.is_symlink():
            if app.is_symlink() or not app.is_dir():
                raise ArciumError(f"refusing to replace non-directory {app}")
            os.replace(app, previous)
            moved = True
        os.replace(staging, app)
    except BaseException:
        if moved and not app.exists():
            os.replace(previous, app)
        raise
    return previous if moved else None


def _launch(app: Path, profile: Path) -> tuple[int, Path]:
    logs = Path.home() / "Library" / "Logs" / "Arcium"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old in sorted(logs.glob("launch-*.log"))[:-(LOG_RETENTION - 1)]:
        old.unlink(missing_ok=True)
    log = logs / f"launch-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.log"
    with log.open("wb") as handle:
        process = subprocess.Popen(
            [str(apps.executable(app)), f"--user-data-dir={profile}", "--no-first-run",
             f"--enable-features={','.join(FEATURES)}"],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, start_new_session=True,
        )
    return process.pid, log


def update(out_dir: Path, *, restart: bool, launch: bool = True) -> dict:
    app = install_path()
    profile = arcium_profile()
    with install_lock():
        owner = running(app, profile)
        if owner is not None:
            if not restart:
                raise ArciumError(f"Arcium is running (pid {owner['pid']}); quit it or use he arcium iterate")
            if not owner["installed"]:
                raise ArciumError(f"the Arcium profile is owned by {owner['executable']}, not {app}; quit it first")
            if owner["mock_keychain"]:
                raise ArciumError("Arcium is running with a mock Keychain; quit it before updating")
        identity = signing_identity()
        migrated = clone_once(helium_profile(), profile) if not profile.exists() else "existing"
        started = time.monotonic()
        staging = app.parent / f".{app.name}.install-{uuid.uuid4().hex}"
        try:
            packaged = package(out_dir, staging, identity)
            prepared = time.monotonic() - started
            if owner is not None:
                current = running(app, profile)
                if current is None or current["pid"] != owner["pid"] or not current["installed"]:
                    raise ArciumError("Arcium changed while the update was prepared; retry")
                _quit(owner["pid"], app)
                if not apps.wait_for_exit([owner["pid"]], QUIT_TIMEOUT):
                    raise ArciumError("Arcium did not finish quitting; close any open dialog and retry. "
                                      "Nothing was replaced")
            if (late := running(app, profile)) is not None:
                raise ArciumError(f"the Arcium profile is in use again (pid {late['pid']}); nothing was replaced")
            previous = _publish(staging, app)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        try:
            verify_identity(app)
            apps.verify_signature(app)
            pid, log = _launch(app, profile) if launch else (None, None)
            if pid is not None and not apps.wait_for_owner(profile, pid, apps.executable(app), timeout=20):
                raise ArciumError(f"the new Arcium did not take its profile; see {log}")
        except BaseException as error:
            kept = f" Previous bundle kept at {previous}." if previous else ""
            raise ArciumError(f"Arcium was replaced at {app} but did not start cleanly: {error}.{kept} "
                              "The profile was not rolled back.") from error
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
    return {"app": str(app), "profile": str(profile), "profile_setup": migrated, "pid": pid,
            "log": str(log) if log else None, "signing_identity": identity,
            "prepared_seconds": round(prepared, 1), "restarted": owner is not None, **packaged}


def status() -> dict:
    app = install_path()
    result = {"app": str(app), "installed": app.is_dir(), "profile": str(arcium_profile())}
    if not app.is_dir():
        return result
    try:
        info = verify_identity(app)
        result.update(identity_ok=True, version=info.get("CFBundleShortVersionString"))
    except HeError as error:
        result.update(identity_ok=False, problem=str(error))
    try:
        apps.verify_signature(app)
        result["signature_ok"] = True
    except HeError as error:
        result.update(signature_ok=False, problem=str(error))
    details = subprocess.run(["/usr/bin/codesign", "-dv", str(app)], capture_output=True, text=True, check=False).stderr
    result["signed_by"] = next((line.split("=", 1)[1] for line in details.splitlines() if line.startswith("Authority=")),
                               "ad hoc" if "adhoc" in details else None)
    result["running"] = running(app, arcium_profile())
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="he arcium")
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("action", choices=("install", "iterate", "status"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = status()
        else:
            result = update(args.build_dir.resolve() / "src" / "out" / "Default",
                            restart=args.action == "iterate", launch=not args.no_launch)
    except HeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
