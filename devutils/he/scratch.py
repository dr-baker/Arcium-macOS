"""Copy-on-write scratch source for patch authoring.

A scratch is a build dir without build output: an APFS clone of the warm
`src/` (minus `out/`) with its own copy of the patch catalog. Workers pop,
edit, and save patches there while the shared build dir keeps building.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import shutil

from . import quilt, timestamps
from .common import HeError, Paths, write_atomic, write_json

MARKER = "scratch.json"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_libc = ctypes.CDLL(None, use_errno=True)
_libc.clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
_CLONE_NOFOLLOW = 0x0001


def _clone(source: Path, destination: Path) -> None:
    """clonefile(2): copy-on-write, recursive for directories, APFS only."""
    if _libc.clonefile(os.fsencode(source), os.fsencode(destination), _CLONE_NOFOLLOW) != 0:
        error = ctypes.get_errno()
        raise HeError(f"could not clone {source} ({os.strerror(error)}); scratch needs APFS on one volume")


def scratch_root(paths: Paths, name: str) -> Path:
    if not _NAME.fullmatch(name):
        raise HeError(f"invalid scratch name: {name}")
    return paths.state / "scratch" / name


def is_scratch(build_dir: Path) -> bool:
    return (build_dir / ".arcium" / MARKER).is_file()


def create(paths: Paths, name: str) -> Path:
    """Clone a fully applied build dir into a scratch build dir."""
    if is_scratch(paths.build_dir):
        raise HeError("this build dir is already a scratch; create scratches from the shared build dir")
    series = quilt.read_list(paths.catalog / "series.merged")
    if not series or quilt.applied(paths.src) != series:
        raise HeError("he scratch needs a fully applied stack in the shared build dir; run he push first")
    if timestamps.pending(paths):
        raise HeError("a timestamp snapshot is pending; finish with he push first")
    root = scratch_root(paths, name)
    if root.exists():
        raise HeError(f"scratch {name} already exists: {root}")
    (root / "src").mkdir(parents=True)
    try:
        for entry in os.scandir(paths.src):
            if entry.name == "out":
                continue
            _clone(Path(entry.path), root / "src" / entry.name)
        (root / ".arcium").mkdir()
        _clone(paths.catalog, root / ".arcium" / "patches")
        for record in ("applied.json", "acquisition.json", "stamps.json"):
            if (paths.state / record).is_file():
                shutil.copy2(paths.state / record, root / ".arcium" / record)
        for gclient in (".gclient", ".gclient_entries"):
            if (paths.build_dir / gclient).is_file():
                shutil.copy2(paths.build_dir / gclient, root / gclient)
        # Quilt would otherwise keep using the parent's catalog.
        write_atomic(root / "src" / ".pc" / ".quilt_patches", f"{root / '.arcium' / 'patches'}\n".encode())
        write_json(root / ".arcium" / MARKER, {"version": 1, "parent": str(paths.build_dir)})
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root


def remove(paths: Paths, name: str) -> Path:
    root = scratch_root(paths, name)
    if not is_scratch(root):
        raise HeError(f"no scratch named {name} in {paths.build_dir}")
    shutil.rmtree(root)
    return root
