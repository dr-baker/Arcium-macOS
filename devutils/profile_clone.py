#!/usr/bin/env python3
"""Safely clone one stopped Chromium user-data directory exactly once."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable

from helium_dev_bundle import _copy_source


class ProfileCloneError(RuntimeError):
    """A browser profile cannot be cloned without risking source data."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_TRANSIENT_ENTRIES = (
    "RunningChromeVersion",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)


def _profile_snapshot(root: Path) -> tuple[tuple[str, int, int, str | None], ...]:
    records: list[tuple[str, int, int, str | None]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        link_target = os.readlink(path) if path.is_symlink() else None
        records.append((relative, metadata.st_size, metadata.st_mtime_ns, link_target))
    return tuple(records)


def clone_profile_once(
    source: Path,
    destination: Path,
    *,
    copy_runner: CommandRunner | None = None,
) -> str:
    """Clone `source` into a missing destination and never overwrite it."""

    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ProfileCloneError(
                f"profile destination is not a safe directory: {destination}"
            )
        return "existing"
    if source.is_symlink() or not source.is_dir():
        raise ProfileCloneError(f"profile seed is missing: {source}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.seed-{uuid.uuid4().hex}"
    try:
        before = _profile_snapshot(source)
        method = _copy_source(source, staging, copy_runner)
        for name in _TRANSIENT_ENTRIES:
            path = staging / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        unsafe_links = tuple(path for path in staging.rglob("*") if path.is_symlink())
        if unsafe_links:
            raise ProfileCloneError(
                "profile seed contains symlinks that cannot be cloned safely"
            )
        if _profile_snapshot(source) != before:
            raise ProfileCloneError(
                "profile seed changed during cloning; quit the source browser and retry"
            )
        os.replace(staging, destination)
        os.chmod(destination, 0o700)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return method
