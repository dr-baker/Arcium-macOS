"""Copy-on-write scratch source for patch authoring.

A scratch is a build dir without build output, holding only what Quilt
touches: every file the patch series owns, Quilt's `.pc` backups, and its own
copy of the patch catalog, all as APFS clones. That is a few thousand files
instead of Chromium's million, so it takes seconds and holds the shared build
dir's lock only that long. Workers pop, edit, and save patches there while the
shared build dir keeps building.

A file no patch owns yet is not in the scratch. `he scratch-pull PATH...`
clones it from the shared build dir before `quilt add`; `he save-patch`
refuses a patch that would create a file the shared tree already has.
"""

from __future__ import annotations

import ctypes
import json
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
        _clone(paths.src / ".pc", root / "src" / ".pc")
        for relative in [*quilt.owned_files(paths.src, series), "chrome/VERSION"]:
            source = paths.src / relative
            if source.is_file() and not source.is_symlink():
                (root / "src" / relative).parent.mkdir(parents=True, exist_ok=True)
                _clone(source, root / "src" / relative)
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


def parent_src(build_dir: Path) -> Path:
    marker = json.loads((build_dir / ".arcium" / MARKER).read_text(encoding="utf-8"))
    return Path(marker["parent"]) / "src"


def pull(paths: Paths, relatives: list[str]) -> list[str]:
    """Clone files no patch owns yet from the shared build dir into this scratch."""
    if not is_scratch(paths.build_dir):
        raise HeError("he scratch-pull runs inside a scratch build dir")
    source_root = parent_src(paths.build_dir)
    pulled = []  # files that do not exist in the shared tree are new; nothing to pull
    for relative in relatives:
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts or not parts:
            raise HeError(f"paths are relative to src without '..': {relative}")
        source, target = source_root / relative, paths.src / relative
        if target.exists():
            continue
        if not source.exists():
            continue  # a new file: quilt add creates it
        if not source.is_file() or source.is_symlink():
            raise HeError(f"{relative} is not a regular file in {source_root}")
        target.parent.mkdir(parents=True, exist_ok=True)
        _clone(source, target)
        pulled.append(relative)
    return pulled


def created_files_in_parent(paths: Paths, patch: Path) -> list[str]:
    """Files a scratch patch would create that the shared tree already has."""
    if not is_scratch(paths.build_dir):
        return []
    source_root = parent_src(paths.build_dir)
    lines = patch.read_text(errors="replace").splitlines()
    created = []
    for previous, line in zip(lines, lines[1:]):
        if previous.startswith("--- /dev/null") and line.startswith("+++ "):
            name = line[4:].split("\t")[0].strip()
            for prefix in ("b/", "src/"):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            if (source_root / name).exists():
                created.append(name)
    return created


def remove(paths: Paths, name: str) -> Path:
    root = scratch_root(paths, name)
    if not is_scratch(root):
        raise HeError(f"no scratch named {name} in {paths.build_dir}")
    shutil.rmtree(root)
    return root
