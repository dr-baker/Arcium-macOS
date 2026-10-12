"""Clone a stopped Chromium user-data directory once, without risking the source."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import uuid

from .apps import copy_app, lock_state
from .common import HeError

_TRANSIENT = ("RunningChromeVersion", "SingletonCookie", "SingletonLock", "SingletonSocket")


def _snapshot(root: Path) -> tuple:
    """Sizes, mtimes, and link targets; any change means a browser is writing."""
    records = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        records.append((path.relative_to(root).as_posix(), metadata.st_size, metadata.st_mtime_ns,
                        os.readlink(path) if path.is_symlink() else None))
    return tuple(records)


def clone_once(source: Path, destination: Path, *, still_running=None) -> str:
    """Copy `source` to a missing `destination`; never overwrite an existing one.

    SQLite journal and WAL files are copied with their databases. Runtime
    singleton links are dropped; any other symlink refuses the clone.
    """
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise HeError(f"profile destination is not a safe directory: {destination}")
        return "existing"
    if source.is_symlink() or not source.is_dir():
        raise HeError(f"profile seed is missing: {source}")
    state, pid = lock_state(source)
    if state == "live":
        raise HeError(f"profile seed {source} is in use by pid {pid}; quit that browser first")
    if state == "foreign":
        raise HeError(f"profile seed {source} is locked by another host or an unreadable lock; "
                      "quit any browser using it, then remove its SingletonLock")
    if still_running is not None and (pids := still_running()):
        raise HeError(f"a browser that may use {source} is running (pids {pids}); quit it first")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.seed-{uuid.uuid4().hex}"
    try:
        before = _snapshot(source)
        method = copy_app(source, staging)
        for name in _TRANSIENT:
            path = staging / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        if any(path.is_symlink() for path in staging.rglob("*")):
            raise HeError("profile seed contains symlinks that cannot be cloned safely")
        if _snapshot(source) != before:
            raise HeError("profile seed changed while copying; quit the browser using it and retry")
        os.replace(staging, destination)
        os.chmod(destination, 0o700)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return method
