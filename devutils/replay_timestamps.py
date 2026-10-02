"""Preserve unchanged patch-owned source mtimes within one locked replay.

Recovery snapshots survive failed attempts. Callers must hold the lane lock
through collection, Quilt replay, proof publication, and restoration.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import secrets
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
    try:
        os.fsencode(relative)
    except UnicodeError:
        return ()
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


class TimestampRecoveryError(RuntimeError):
    """Recovery state cannot safely be used or replaced."""


_RECOVERY_NAME = "replay-timestamps.json"


def has_pending_recovery(root: Path) -> bool:
    """Refuse proof while a snapshot exists, even if it cannot be read safely."""
    directory = root.parent / ".arcium"
    try:
        if not stat.S_ISDIR(directory.lstat().st_mode):
            return True
        (directory / _RECOVERY_NAME).lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


@contextmanager
def _recovery_directory(root: Path) -> Iterator[int]:
    """Keep recovery I/O anchored to the selected lane, without symlink traversal."""
    parent = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = None
    try:
        try:
            os.mkdir(".arcium", mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        directory = os.open(".arcium", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
        yield directory
    finally:
        if directory is not None:
            os.close(directory)
        os.close(parent)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def recovery_timestamps(
    root: Path, *, worktree: Path, patch_root: Path, source_receipt_id: str,
    source_identity: dict[str, str], paths: Iterable[str],
) -> dict[str, FileTimestamp]:
    """Reuse the first snapshot for this exact replay context, or persist it.

    Mismatched or corrupt state blocks replay and must be deliberately removed
    before starting a fresh transaction. Never capture an intermediate tree as
    a substitute for a recovery snapshot. The checksum detects corruption; the
    lane directory remains trusted local state, not an authentication boundary.
    The original receipt is provenance only: a repaired patch/core commit may
    differ. Callers bind the upstream source version separately, and final file
    bytes and mode decide which timestamps can be restored.
    """
    try:
        metadata = root.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("source root is not a real directory")
        context = {
            "source": str(root.absolute()), "device": metadata.st_dev,
            "inode": metadata.st_ino, "worktree": str(worktree.resolve()),
            "patch_root": str(patch_root.resolve()), "source_identity": source_identity,
        }
        with _recovery_directory(root) as directory:
            try:
                fd = os.open(_RECOVERY_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
            except FileNotFoundError:
                fd = None
            if fd is not None:
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError("recovery snapshot is not a private regular file")
                    raw = stream.read(64 * 1024 * 1024 + 1)
                if len(raw) > 64 * 1024 * 1024:
                    raise ValueError("recovery snapshot is too large")
                document = json.loads(raw)
                checksum = document.pop("sha256")
                if checksum != hashlib.sha256(_json_bytes(document)).hexdigest():
                    raise ValueError("recovery checksum differs")
                if document.get("schema") != 1 or document.get("context") != context:
                    raise ValueError("recovery context differs")
                records = {}
                for relative, entry in document["files"].items():
                    if not _parts(relative) or str(Path(relative)) != relative:
                        raise ValueError("unsafe recovery path")
                    if not isinstance(entry, list) or len(entry) != 4:
                        raise ValueError("invalid recovery record")
                    digest, mode, atime, mtime = entry
                    if (not isinstance(digest, str) or len(digest) != 64
                            or any(c not in "0123456789abcdef" for c in digest)
                            or any(type(v) is not int for v in (mode, atime, mtime))
                            or not 0 <= mode <= 0o7777
                            or any(not 0 <= v < 2**63 for v in (atime, mtime))):
                        raise ValueError("invalid recovery metadata")
                    records[relative] = FileTimestamp(bytes.fromhex(digest), mode, atime, mtime)
                return records
            records = snapshot_timestamps(root, paths)
            document = {"schema": 1, "context": context,
                        "original_source_receipt_id": source_receipt_id, "files": {
                name: [r.digest.hex(), r.mode, r.atime_ns, r.mtime_ns]
                for name, r in records.items()
            }}
            document["sha256"] = hashlib.sha256(_json_bytes(document)).hexdigest()
            temporary = ".replay-timestamps-" + secrets.token_hex(12)
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(_json_bytes(document))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, _RECOVERY_NAME, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
            return records
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise TimestampRecoveryError(
            "cannot use replay timestamp recovery snapshot; inspect lane .arcium/replay-timestamps.json "
            "before deliberately discarding it"
        ) from error


def consume_recovery_timestamps(root: Path) -> None:
    """Durably retire the snapshot before restoring any timestamps.

    A snapshot left after success could outlive a later build and hide changes
    on a future replay. Failure here must invalidate proof and skip restoration.
    A crash after consumption merely loses this optimization.
    """
    try:
        with _recovery_directory(root) as directory:
            os.unlink(_RECOVERY_NAME, dir_fd=directory)
            os.fsync(directory)
    except OSError as error:
        raise TimestampRecoveryError("could not retire replay timestamp recovery snapshot") from error
