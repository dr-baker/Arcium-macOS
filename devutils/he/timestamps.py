"""Keep timestamps of byte-identical files across pop and push.

Quilt's pop touches every file it restores, on purpose, so make-style tools
rebuild them. When the same patches are pushed back unchanged, those files
come back byte-identical but newer, and Ninja and Siso recompile everything
that includes them. This module gives such files their original timestamps.

Safety invariant: restore only if nothing has built since the snapshot. A
build in between may have compiled an intermediate version; giving the source
an older time afterwards would hide that change from the build tool.

Three layers enforce it:
1. `he` holds the build-dir lock from snapshot to restore, and `he build`
   discards a pending snapshot before building.
2. Before restoring, every src/out/*/ directory (following a symlinked out
   dir to its target) is scanned for any entry whose inode change time is newer than the snapshot.
   Any hit skips restoration. The snapshot's own mtime is the cutoff, so it
   must still equal the recorded capture time, and the wall clock must not
   have moved backwards since capture.
3. The docs state the one case left: a build outside `he` running at the
   same moment as the restore.

Every failure path skips restoration, which only costs rebuild time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import time

from . import quilt
from .common import HeError, Paths, sha256_file, write_json

JOURNAL = "timestamps.json"
VERSION = 1
_EXCLUDED_ROOTS = {"out", ".pc", ".git", ".arcium"}


def journal_path(paths: Paths) -> Path:
    return paths.state / JOURNAL


def enabled() -> bool:
    return os.environ.get("HELIUM_KEEP_TIMESTAMPS", "1") != "0"


def pending(paths: Paths) -> bool:
    return journal_path(paths).exists()


def _out_dirs(paths: Paths) -> list[str]:
    """Each src/out entry that is a directory, by name and resolved target.

    Symlinked out dirs count: outputs written through a symlink change the
    target's entries, not the link's.
    """
    root = paths.src / "out"
    if not root.is_dir():
        return []
    return sorted(f"{entry.name}={Path(entry.path).resolve()}" for entry in os.scandir(root) if entry.is_dir())


def _clock() -> dict:
    """Wall and monotonic time plus boot identity, to detect clock changes."""
    boot = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, check=False).stdout.strip()
    return {"wall_ns": time.time_ns(), "monotonic_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC), "boot": boot}


def _clock_problem(captured: dict) -> str | None:
    now = _clock()
    if not captured or captured.get("boot") != now["boot"]:
        return "the machine restarted since the snapshot"
    wall = now["wall_ns"] - captured["wall_ns"]
    monotonic = now["monotonic_ns"] - captured["monotonic_ns"]
    # Allow one second of drift; a backward jump means ctimes cannot be trusted.
    if wall < monotonic - 1_000_000_000:
        return "the wall clock moved backwards since the snapshot"
    return None


def _safe(relative: str) -> bool:
    parts = Path(relative).parts
    return bool(parts) and not Path(relative).is_absolute() and ".." not in parts and parts[0] not in _EXCLUDED_ROOTS


def _record(path: Path) -> list | None:
    """[sha256, mode, atime_ns, mtime_ns] for a plain single-link file."""
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None
        digest = sha256_file(path)
        after = os.lstat(path)
    except OSError:
        return None
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        return None
    return [digest, before.st_mode, before.st_atime_ns, before.st_mtime_ns]


def capture(paths: Paths) -> str:
    """Snapshot files owned by the applied patches, before Quilt pops them.

    Only a fully applied stack is captured. An existing snapshot is kept, so a
    run of pops, edits, and failed pushes keeps the original times.
    """
    if not enabled():
        return "timestamp keeper is off (HELIUM_KEEP_TIMESTAMPS=0)"
    journal = journal_path(paths)
    if journal.exists():
        return "keeping the existing timestamp snapshot"
    series = quilt.read_list(paths.catalog / "series.merged")
    applied = quilt.applied(paths.src)
    if not applied or applied != series:
        return "stack is not fully applied; no timestamp snapshot taken"
    clock = _clock()
    captured_at = clock["wall_ns"]
    files = {}
    for relative in quilt.owned_files(paths.src, applied):
        if _safe(relative) and (record := _record(paths.src / relative)) is not None:
            files[relative] = record
    write_json(journal, {
        "version": VERSION,
        "captured_at_ns": captured_at,
        "clock": clock,
        "source_dir": str(paths.src),
        "out_dirs": _out_dirs(paths),
        "files": files,
    })
    # The scan compares change times against the journal's mtime.
    os.utime(journal, ns=(captured_at, captured_at))
    return f"timestamp snapshot: {len(files)} files"


def discard(paths: Paths, reason: str) -> str | None:
    journal = journal_path(paths)
    if not journal.exists():
        return None
    journal.unlink()
    return f"timestamp snapshot discarded ({reason}); the next build recompiles popped files normally"


def _built_since(paths: Paths, journal: Path, out_dirs: list[str]) -> str | None:
    for entry in out_dirs:
        directory = paths.src / "out" / entry.split("=", 1)[0]
        # -H follows a symlinked out dir itself. Links inside out/ point at
        # Xcode SDKs and log files, not build outputs, so they are not followed.
        # Errors count as a hit.
        # Dev app bundles that `he run` copies next to Helium.app are not build
        # outputs; skip them, and the out dir's own entry, which they touch.
        result = subprocess.run(
            ["find", "-H", str(directory), "-mindepth", "1",
             "(", "-name", "Helium Dev*.app", "-o", "-name", ".Helium Dev*", ")", "-prune",
             "-o", "-newercm", str(journal), "-print", "-quit"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode or result.stdout.strip():
            return result.stdout.strip() or f"could not scan {directory}"
    return None


def restore(paths: Paths) -> str | None:
    """After a push that reaches the top of the series, restore what is safe."""
    journal = journal_path(paths)
    if not journal.exists():
        return None
    if not enabled():
        return discard(paths, "HELIUM_KEEP_TIMESTAMPS=0")
    if quilt.applied(paths.src) != quilt.read_list(paths.catalog / "series.merged"):
        return "stack is not fully applied; timestamp snapshot kept for the next push"
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        if data.get("version") != VERSION or not isinstance(data.get("files"), dict):
            raise ValueError("unsupported snapshot")
    except (OSError, ValueError) as error:
        journal.unlink(missing_ok=True)
        return f"timestamp snapshot was unreadable ({error}); discarded"
    reason = None
    if journal.stat().st_mtime_ns != data.get("captured_at_ns"):
        reason = "the snapshot file was modified after capture"
    elif (problem := _clock_problem(data.get("clock"))) is not None:
        reason = problem
    elif data.get("source_dir") != str(paths.src):
        reason = "snapshot belongs to another source tree"
    elif data.get("out_dirs") != _out_dirs(paths):
        reason = "out directories changed since the snapshot"
    elif (hit := _built_since(paths, journal, data["out_dirs"])) is not None:
        reason = f"something wrote build output since the snapshot ({hit})"
    if reason is not None:
        journal.unlink()
        return f"timestamps not restored: {reason}"
    # Delete first: a crash part-way leaves newer times, which is only slower.
    journal.unlink()
    restored = 0
    for relative, (digest, mode, atime_ns, mtime_ns) in data["files"].items():
        if not _safe(relative):
            continue
        path = paths.src / relative
        current = _record(path)
        if current is not None and current[0] == digest and current[1] == mode:
            os.utime(path, ns=(atime_ns, mtime_ns), follow_symlinks=False)
            restored += 1
    return f"restored timestamps on {restored} unchanged files"


def status(paths: Paths) -> str | None:
    journal = journal_path(paths)
    if not journal.exists():
        return None
    try:
        count = len(json.loads(journal.read_text(encoding="utf-8")).get("files", {}))
    except (OSError, ValueError):
        raise HeError(f"unreadable timestamp snapshot: {journal}")
    return f"timestamp snapshot pending for {count} files; it is restored when the stack is fully pushed"
