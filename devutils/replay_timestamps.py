"""Preserve unchanged patch-owned source mtimes within one locked replay.

Snapshots are ephemeral. Callers must hold the lane lock through collection,
Quilt replay, restoration, and proof publication.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Iterable, Iterator


@dataclass(frozen=True)
class FileTimestamp:
    digest: bytes
    mode: int
    atime_ns: int
    mtime_ns: int


def _parts(relative: str) -> tuple[str, ...]:
    path = Path(relative)
    if (not relative or path.is_absolute() or '..' in path.parts
            or not path.parts or '\x00' in relative):
        return ()
    # Quilt metadata and generated output must never receive source timestamps.
    if path.parts[0] in {'.pc', '.git', '.arcium', 'out', 'gen', 'obj'}:
        return ()
    return path.parts


@contextmanager
def _regular_file(root: Path, relative: str) -> Iterator[int | None]:
    """Walk with directory descriptors, refusing symlinks and hard-linked files."""
    parts = _parts(relative)
    descriptors: list[int] = []
    descriptor = None
    try:
        if parts:
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(parent)
            for part in parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=parent)
                descriptors.append(parent)
            candidate = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=parent)
            descriptors.append(candidate)
            metadata = os.fstat(candidate)
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                descriptor = candidate
    except OSError:
        # An optimization must not follow or repair an unsafe/unreadable path.
        pass
    try:
        yield descriptor
    finally:
        for opened in reversed(descriptors):
            os.close(opened)


def _stable_record(descriptor: int) -> FileTimestamp | None:
    before = os.fstat(descriptor)
    digest = hashlib.sha256()
    while block := os.read(descriptor, 1024 * 1024):
        digest.update(block)
    after = os.fstat(descriptor)
    # atime can change from our read; ctime/mtime, size and mode must not.
    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or after.st_nlink != 1:
        return None
    return FileTimestamp(digest.digest(), stat.S_IMODE(before.st_mode),
                         before.st_atime_ns, before.st_mtime_ns)


def snapshot_timestamps(root: Path, paths: Iterable[str]) -> dict[str, FileTimestamp]:
    records = {}
    for relative in sorted(set(paths)):
        with _regular_file(root, relative) as descriptor:
            if descriptor is None:
                continue
            try:
                record = _stable_record(descriptor)
            except OSError:
                continue
            if record is not None:
                records[relative] = record
    return records


def restore_timestamps(root: Path, records: dict[str, FileTimestamp]) -> int:
    restored = 0
    for relative, previous in records.items():
        with _regular_file(root, relative) as descriptor:
            if descriptor is None:
                continue
            try:
                current = _stable_record(descriptor)
                if current is None or (current.digest, current.mode) != (
                        previous.digest, previous.mode):
                    continue
                # Mutate the verified descriptor, never reopen a pathname.
                os.utime(descriptor, ns=(previous.atime_ns, previous.mtime_ns))
            except OSError:
                continue
            restored += 1
    return restored
