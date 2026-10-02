"""Bounded per-command build evidence, independent of runnable-build proof.

Call while holding the lane lock. This module invokes no build tools and never
changes Siso state. Changed Siso files are snapshots and may contain cumulative
or earlier records; their contents are not treated as per-invocation metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import fnmatch
import json
import os
import shlex
from pathlib import Path
import stat
import time
from typing import Sequence
import uuid


CAPTURE_BYTES = 64 * 1024
MAX_FILES = 16
_PATTERNS = ("siso_explain*", "siso_metrics*", "siso_metadata*")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
_JSON_ERRORS = (ValueError, UnicodeError, TypeError, RecursionError)


def _absolute(path: Path) -> Path:
    # Keep the caller's spelling so symlink aliases cannot disappear in resolve().
    if ".." in path.parts:
        raise OSError(errno.EINVAL, "build evidence directory contains parent traversal", str(path))
    return path if path.is_absolute() else Path.cwd() / path


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


class _Directories:
    """Own a common anchor and every opened lane-relative directory descriptor."""

    def __init__(self, anchor: Path) -> None:
        self.anchor = anchor
        self.descriptors: list[int] = []
        try:
            self.root = os.open(anchor, _DIRECTORY_FLAGS)
            self.descriptors.append(self.root)
            self.identity = _identity(os.fstat(self.root))
            self.verify(())
        except BaseException:
            self.close()
            raise

    def open(
        self, parts: Sequence[str], *, create: bool = False, parent: int | None = None,
    ) -> tuple[int, list[tuple[int, str, tuple[int, int]]]]:
        parent = self.root if parent is None else parent
        links = []
        for name in parts:
            if create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
            self.descriptors.append(child)
            links.append((parent, name, _identity(os.fstat(child))))
            parent = child
        self.verify(links)
        return parent, links

    def verify(self, links: Sequence[tuple[int, str, tuple[int, int]]]) -> None:
        value = self.anchor.lstat()
        if not stat.S_ISDIR(value.st_mode) or _identity(value) != self.identity:
            raise OSError(errno.ESTALE, "build evidence anchor was replaced", str(self.anchor))
        for parent, name, expected in links:
            value = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or _identity(value) != expected:
                raise OSError(errno.ESTALE, "build evidence directory was replaced", name)

    def close(self) -> None:
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()


def _signature(value: os.stat_result) -> tuple[int, ...] | None:
    if not stat.S_ISREG(value.st_mode):
        return None
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _file_signature(directory: int, name: str) -> tuple[int, ...] | None:
    try:
        return _signature(os.stat(name, dir_fd=directory, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _files(directory: int) -> list[str]:
    return sorted(name for name in os.listdir(directory)
                  if any(fnmatch.fnmatchcase(name, pattern) for pattern in _PATTERNS))


def _write_new(directory: int, name: str, data: bytes) -> None:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        os.fchmod(handle.fileno(), 0o400)


class BuildEvidence:
    """One unique archive; ``finish`` may publish its manifest only once."""

    def __init__(self, archive_root: Path, out_dir: Path, argv: Sequence[str]) -> None:
        self.out_dir = out_dir
        self.argv = list(argv)
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished = False
        self._directories: _Directories | None = None
        self._archive: int | None = None
        self._captured: dict[str, bytes] = {}
        archive = _absolute(archive_root)
        output = _absolute(out_dir)
        # The common directory is the caller-selected lane anchor. System path
        # prefixes, such as macOS's /var alias for temporary fixtures, precede
        # it; every state component below it is opened without following links.
        anchor = Path(os.path.commonpath((archive.parent, output.parent)))
        try:
            self._directories = _Directories(anchor)
            self._out, self._out_links = self._directories.open(output.relative_to(anchor).parts)
            archive_directory, links = self._directories.open(archive.relative_to(anchor).parts, create=True)
            self.path = archive_root / uuid.uuid4().hex
            os.mkdir(self.path.name, mode=0o700, dir_fd=archive_directory)
            self._archive, invocation_links = self._directories.open(
                (self.path.name,), parent=archive_directory,
            )
            self._archive_links = links + invocation_links
            self._directories.verify(self._archive_links)
            self._directories.verify(self._out_links)
            self.before = {name: _file_signature(self._out, name) for name in _files(self._out)}
            self.args = self._snapshot("args.gn")
            self.started = time.monotonic()
        except BaseException:
            self._close()
            raise

    def _close(self) -> None:
        if self._archive is not None:
            try:
                os.fchmod(self._archive, 0o500)
            except OSError:
                pass
            self._archive = None
        if self._directories is not None:
            self._directories.close()
        self._captured.clear()

    def __del__(self) -> None:
        self._close()

    def _write(self, name: str, content: bytes) -> None:
        self._directories.verify(self._archive_links)
        _write_new(self._archive, name, content)

    def _snapshot(self, name: str) -> dict[str, object]:
        try:
            self._directories.verify(self._out_links)
        except OSError:
            return {"status": "output-directory-changed-or-unavailable"}
        before = _file_signature(self._out, name)
        if before is None:
            return {"status": "missing-or-not-regular"}
        # Pin the containing directory as well as refusing a symlinked file.
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._out)
        except OSError as error:
            return {"status": "unreadable", "error_type": type(error).__name__}
        with os.fdopen(descriptor, "rb") as handle:
            opened = _signature(os.fstat(handle.fileno()))
            if opened is None:
                return {"status": "not-regular"}
            if opened != before:
                return {"status": "changed-while-reading"}
            split_metrics = name.startswith("siso_metrics") and before[2] > CAPTURE_BYTES
            content = handle.read(CAPTURE_BYTES // 2 if split_metrics else CAPTURE_BYTES)
            tail = None
            if split_metrics:
                handle.seek(-CAPTURE_BYTES // 2, os.SEEK_END)
                # Drop the first possibly partial JSONL record. The bounded
                # tail still includes the final complete cumulative record.
                tail = handle.read(CAPTURE_BYTES // 2).partition(b"\n")[2]
            after = _signature(os.fstat(handle.fileno()))
        try:
            self._directories.verify(self._out_links)
        except OSError:
            return {"status": "output-directory-changed-or-unavailable"}
        if before != after or before != _file_signature(self._out, name):
            return {"status": "changed-while-reading"}
        self._write(name, content)
        self._captured[name] = content
        result = {"status": "captured", "file": name, "size_bytes": before[2],
                  "truncated": before[2] > CAPTURE_BYTES}
        if tail is not None:
            tail_name = "metrics-tail-" + name
            self._write(tail_name, tail)
            self._captured[tail_name] = tail
            result["tail_file"] = tail_name
            result["capture"] = "head-and-complete-tail-lines-middle-omitted"
        return result

    def finish(
        self, *, returncode: int | None, stdout: str = "", stderr: str = "",
        timed_out: bool = False, stdout_truncated: bool = False,
        stderr_truncated: bool = False, error_type: str | None = None,
    ) -> Path:
        if self.finished:
            raise RuntimeError("build evidence was already finalized")
        self.finished = True
        try:
            return self._finish(
                returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out,
                stdout_truncated=stdout_truncated, stderr_truncated=stderr_truncated,
                error_type=error_type,
            )
        finally:
            self._close()

    def _finish(
        self, *, returncode: int | None, stdout: str, stderr: str,
        timed_out: bool, stdout_truncated: bool, stderr_truncated: bool,
        error_type: str | None,
    ) -> Path:
        elapsed = max(0.0, time.monotonic() - self.started)
        snapshots: dict[str, object] = {}
        try:
            self._directories.verify(self._out_links)
            names = sorted(set(self.before) | set(_files(self._out)))
            output_directory_status = "verified"
        except OSError:
            names = sorted(self.before)
            output_directory_status = "changed-or-unavailable"
        for name in names[:MAX_FILES]:
            if output_directory_status != "verified":
                snapshots[name] = {"status": "output-directory-changed-or-unavailable"}
                continue
            after = _file_signature(self._out, name)
            if after is None:
                snapshots[name] = {"status": "missing-or-not-regular"}
            elif after == self.before.get(name):
                snapshots[name] = {"status": "unchanged-not-current"}
            else:
                snapshots[name] = {**self._snapshot(name),
                                   "scope": "changed-file-snapshot-may-include-earlier-records"}
        try:
            self._directories.verify(self._out_links)
        except OSError:
            output_directory_status = "changed-or-unavailable"
        # Metadata must itself have changed during this invocation. A stale
        # metadata file cannot attribute a new metrics file to this command.
        metadata_ids: set[str] = set()
        for name, snapshot in snapshots.items():
            if (not name.startswith("siso_metadata") or snapshot.get("status") != "captured"
                    or snapshot.get("truncated")):
                continue
            try:
                value = json.loads(self._captured[name].decode("utf-8"))
                build_id = value.get("build_id") if isinstance(value, dict) else None
                if isinstance(build_id, str) and build_id:
                    metadata_ids.add(build_id)
            except _JSON_ERRORS:
                snapshot["metadata_parse"] = "malformed-or-unsupported-json"
        for name, snapshot in snapshots.items():
            if not name.startswith("siso_metrics"):
                continue
            snapshot["attribution"] = "unknown"
            if snapshot.get("status") != "captured":
                continue
            try:
                metrics_file = str(snapshot.get("tail_file", name))
                records = [json.loads(line) for line in self._captured[metrics_file].decode("utf-8").splitlines() if line.strip()]
                # Siso JSONL repeats cumulative duration in summary records.
                # Keep the final cumulative value; never sum durations or
                # infer totals from the retained sample of step records.
                summaries = [record for record in records if isinstance(record, dict)
                             and "build_id" in record and "duration_nanos" in record]
                final = summaries[-1] if summaries else None
                if final is not None and final["build_id"] in metadata_ids:
                    duration = final["duration_nanos"]
                    if (isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0
                            or isinstance(duration, str) and duration.isascii() and duration.isdigit()):
                        duration = int(duration)
                        snapshot["attribution"] = "matches-changed-metadata-build-id"
                        snapshot["final_cumulative_duration_nanos"] = duration
            except _JSON_ERRORS:
                snapshot["metrics_parse"] = "malformed-or-unsupported-jsonl"
        output = {}
        for name, value, truncated in (("stdout", stdout, stdout_truncated),
                                        ("stderr", stderr, stderr_truncated)):
            data = value.encode("utf-8", errors="replace")
            self._write(f"{name}.txt", data[:CAPTURE_BYTES])
            output[name] = {"file": f"{name}.txt", "truncated": truncated or len(data) > CAPTURE_BYTES}
        outcome = "exception" if error_type else "success" if returncode == 0 else "failed"
        manifest = {
            "schema": 1, "invocation_id": self.path.name,
            "started_at": self.started_at, "command_wall_seconds": elapsed,
            "argv": self.argv, "output_directory": str(self.out_dir),
            "output_directory_status": output_directory_status,
            "mode": "dry-run" if "-n" in self.argv else "build",
            "outcome": outcome, "returncode": returncode, "timed_out": timed_out,
            "error_type": error_type, "args_at_start": self.args,
            "siso_snapshots": snapshots, "omitted_file_count": max(0, len(names) - MAX_FILES),
            "output": output,
            "cache_delta": {"status": "unknown", "reason": "no scoped cache counters available"},
        }
        self._write("manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
        siso_timings = [f"{name}: {snapshot['final_cumulative_duration_nanos']} ns"
                        for name, snapshot in snapshots.items()
                        if "final_cumulative_duration_nanos" in snapshot]
        timing_summary = "; ".join(siso_timings) if siso_timings else "unknown"
        self._write("summary.txt", (
            f"{manifest['mode']}: {outcome}; wall {elapsed:.3f}s; cache delta unknown.\n"
            f"Siso final cumulative duration: {timing_summary}.\n"
            f"argv: {shlex.join(self.argv)[:512]}\n"
            "Full argv and snapshot status: manifest.json.\n"
            "Siso files are bounded snapshots; changed files may include earlier records.\n"
        ).encode())
        os.fchmod(self._archive, 0o500)
        self._directories.verify(self._archive_links)
        return self.path
