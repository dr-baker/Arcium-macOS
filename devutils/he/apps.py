"""macOS app bundle and browser-process helpers shared by Dev and Arcium apps."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from typing import Callable

from .common import HeError

_libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
_libproc.proc_pidpath.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
_PROC_PIDPATHINFO_MAXSIZE = 4096


# Bundles ------------------------------------------------------------------------

def read_plist(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise HeError(f"could not read bundle metadata: {path}") from error
    if not isinstance(value, dict):
        raise HeError(f"bundle metadata is not a dictionary: {path}")
    return value


def write_plist(path: Path, info: dict, original: bytes) -> None:
    """Rewrite a property list in its original binary or XML format."""
    fmt = plistlib.FMT_BINARY if original.startswith(b"bplist00") else plistlib.FMT_XML
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(info, handle, fmt=fmt, sort_keys=False)
        os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def executable(app: Path) -> Path:
    """The bundle's main executable, refusing unsafe names."""
    name = read_plist(app / "Contents" / "Info.plist").get("CFBundleExecutable")
    if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise HeError(f"{app} has no safe CFBundleExecutable")
    return app / "Contents" / "MacOS" / name


def copy_app(source: Path, destination: Path) -> str:
    """Copy a bundle, as an APFS clone when the volume allows it."""
    if source.is_symlink() or not source.is_dir():
        raise HeError(f"app bundle is missing: {source}")
    if destination.exists() or destination.is_symlink():
        raise HeError(f"refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["/bin/cp", "-cR", str(source), str(destination)], capture_output=True, check=False)
    if result.returncode == 0:
        return "apfs-clone"
    shutil.rmtree(destination, ignore_errors=True)
    try:
        shutil.copytree(source, destination, symlinks=True)
    except OSError as error:
        shutil.rmtree(destination, ignore_errors=True)
        raise HeError(f"could not copy {source}") from error
    return "copy"


def rewrite_identity(app: Path, rewrite_id: Callable[[str], str], rewrite_name: Callable[[str], str] | None,
                     root: dict) -> int:
    """Rewrite bundle identifiers in every nested Info.plist, then the root's keys.

    Executable names stay unchanged; Chromium locates its helpers by name.
    """
    root_plist = app / "Contents" / "Info.plist"
    paths = sorted(app.rglob("Info.plist"))
    if root_plist not in paths:
        raise HeError(f"{app} has no root Info.plist")
    for path in paths:
        original = path.read_bytes()
        info = read_plist(path)
        name = info.get("CFBundleExecutable")
        if name is not None and (not isinstance(name, str) or not name or "/" in name or name in {".", ".."}):
            raise HeError(f"{path} names an unsafe CFBundleExecutable")
        if isinstance(info.get("CFBundleIdentifier"), str) and info["CFBundleIdentifier"]:
            info["CFBundleIdentifier"] = rewrite_id(info["CFBundleIdentifier"])
        if rewrite_name is not None:
            for key in ("CFBundleDisplayName", "CFBundleName"):
                if isinstance(info.get(key), str) and info[key]:
                    info[key] = rewrite_name(info[key])
        if path == root_plist:
            info.update(root)
        write_plist(path, info, original)
    return len(paths)


def codesign(arguments: list[str], what: str) -> None:
    result = subprocess.run(["/usr/bin/codesign", *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise HeError(f"{what} failed: {(result.stderr or result.stdout).strip()}")


def sign_ad_hoc(app: Path) -> None:
    codesign(["--force", "--deep", "--sign", "-", str(app)], f"ad hoc signing {app.name}")
    verify_signature(app)


def verify_signature(app: Path) -> None:
    codesign(["--verify", "--deep", "--strict", str(app)], f"signature check of {app}")


def build_fingerprint(out_dir: Path) -> str:
    """Sizes and mtimes of Helium.app and the component dylibs: changes on every relink."""
    import hashlib
    digest = hashlib.sha256()
    app = out_dir / "Helium.app"
    for path in [*sorted(app.rglob("*")), *sorted(out_dir.glob("*.dylib"))]:
        metadata = path.lstat()
        digest.update(f"{path.relative_to(out_dir)}\0{metadata.st_size}\0{metadata.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def component_libraries(out_dir: Path) -> list[Path]:
    """Loose dylibs a component build's app loads from the out dir."""
    args = (out_dir / "args.gn").read_text(encoding="utf-8") if (out_dir / "args.gn").is_file() else ""
    values = re.findall(r"^\s*is_component_build\s*=\s*(\w+)", args, re.MULTILINE)
    if not values or values[-1] != "true":
        return []
    libraries = sorted(path for path in out_dir.glob("*.dylib") if path.is_file() and not path.is_symlink())
    if not libraries:
        raise HeError(f"component build in {out_dir} has no runtime libraries")
    return libraries


# Processes ----------------------------------------------------------------------

def process_path(pid: int) -> str | None:
    """The executable path of a running process, or None."""
    buffer = ctypes.create_string_buffer(_PROC_PIDPATHINFO_MAXSIZE)
    length = _libproc.proc_pidpath(pid, buffer, _PROC_PIDPATHINFO_MAXSIZE)
    return os.fsdecode(buffer.raw[:length]) if length > 0 else None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_state(user_data_dir: Path) -> tuple[str, int | None]:
    """("none" | "live" | "stale" | "foreign", pid) for a profile's SingletonLock.

    A lock naming another host cannot be checked from here, so callers treat
    it as possibly in use.
    """
    try:
        target = os.readlink(user_data_dir / "SingletonLock")
    except FileNotFoundError:
        return "none", None
    except OSError:
        return "foreign", None
    host, _, pid = target.rpartition("-")
    if not pid.isdigit():
        return "foreign", None
    if host != socket.gethostname():
        return "foreign", int(pid)
    return ("live" if alive(int(pid)) else "stale"), int(pid)


def profile_owner(user_data_dir: Path) -> int | None:
    """The live local process holding a Chromium profile's SingletonLock.

    The lock is a symlink to "<hostname>-<pid>". A lock naming another host or
    a dead process does not count.
    """
    try:
        target = os.readlink(user_data_dir / "SingletonLock")
    except OSError:
        return None
    host, _, pid = target.rpartition("-")
    if not pid.isdigit() or host != socket.gethostname():
        return None
    return int(pid) if alive(int(pid)) else None


def command_lines() -> dict[int, str]:
    result = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=True)
    lines = {}
    for line in result.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit():
            lines[int(pid)] = command
    return lines


def processes_in(bundle: Path) -> list[int]:
    """PIDs whose executable lives inside `bundle`."""
    prefix = str(bundle.resolve()) + "/"
    return [pid for pid in command_lines() if (path := process_path(pid)) and path.startswith(prefix)]


def main_processes_in(bundle: Path) -> list[int]:
    """Browser main processes (not helpers) running from `bundle`."""
    lines = command_lines()
    return [pid for pid in processes_in(bundle) if not re.search(r"(?:^|\s)--type=", lines.get(pid, ""))]


def uses_profile(pid: int, user_data_dir: Path) -> bool:
    """True if the process was started with exactly this --user-data-dir."""
    # ps joins arguments with spaces, and profile paths contain spaces, so match
    # the whole argument followed by the next separator.
    return f" --user-data-dir={user_data_dir} " in f" {command_lines().get(pid, '')} "


def require_plain_profile(path: Path, protected: list[Path]) -> None:
    """Refuse a profile path that is a symlink or resolves to a protected profile."""
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise HeError(f"profile {path} is a symlink or not a directory; refusing to use it")
    resolved = path.resolve()
    for other in protected:
        if other.exists() and resolved == other.resolve() and path.absolute() != other.absolute():
            raise HeError(f"profile {path} resolves to {other}; refusing to use it")


def wait_for_exit(pids: list[int], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while any(alive(pid) for pid in pids):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
    return True


def wait_for_owner(user_data_dir: Path, pid: int, executable_path: Path, timeout: float = 10.0,
                   steady: float = 1.0) -> bool:
    """True once `pid` runs `executable_path` and owns the profile for `steady` seconds."""
    deadline = time.monotonic() + timeout
    since = None
    expected = str(executable_path.resolve())
    while time.monotonic() < deadline:
        if profile_owner(user_data_dir) == pid and process_path(pid) == expected:
            since = since or time.monotonic()
            if time.monotonic() - since >= steady:
                return True
        else:
            since = None
        if not alive(pid):
            return False
        time.sleep(0.2)
    return False
