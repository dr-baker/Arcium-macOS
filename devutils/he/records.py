"""Facts the build graph cannot see.

Ninja and Siso track everything inside the graph. These records cover what
happens outside it:

- applied.json: the exact bytes of each patch when Quilt applied it;
- stamps.json: the inputs of producers that copy or stamp files into src/
  (resources, version, GN defaults);
- acquisition.json: the architecture and source mode the build dir holds.
"""

from __future__ import annotations

import os
from pathlib import Path
import platform

from . import quilt
from .common import HeError, Paths, read_json, sha256_bytes, sha256_file, write_json

APPLIED = "applied.json"
STAMPS = "stamps.json"
ACQUISITION = "acquisition.json"
BEFORE_PUSH = "applied-before-push.json"

# Inputs per out-of-graph producer, relative to the source worktree.
STAMP_INPUTS = {
    "resources": (
        "helium-chromium/resources",
        "resources",
    ),
    "version": (
        "helium-chromium/version.txt",
        "helium-chromium/chromium_version.txt",
        "helium-chromium/revision.txt",
        "revision.txt",
    ),
    "gn-defaults": (
        "helium-chromium/flags.gn",
        "flags.macos.gn",
    ),
}
STAMP_FIX = {"resources": "he resources", "version": "he version", "gn-defaults": "he configure --refresh-defaults"}
_SKIP_NAMES = {".DS_Store", "__pycache__", "generated"}


# Applied-patch record ------------------------------------------------------

def _applied_record(paths: Paths) -> dict[str, str]:
    value = read_json(paths.state / APPLIED)
    patches = value.get("patches") if isinstance(value, dict) else None
    return dict(patches) if isinstance(patches, dict) else {}


def clear_applied(paths: Paths) -> None:
    (paths.state / APPLIED).unlink(missing_ok=True)
    (paths.state / BEFORE_PUSH).unlink(missing_ok=True)


def mark_before_push(paths: Paths) -> None:
    """Remember which patches were applied before `he push` runs Quilt."""
    write_json(paths.state / BEFORE_PUSH, list(quilt.applied(paths.src)))


def sync_applied(paths: Paths, rebaseline: tuple[str, ...] = ()) -> None:
    """Call after every push, pop, or refresh made through `he`.

    A patch keeps the hash recorded when it was applied. Only patches this
    push applied (absent from the list `mark_before_push` saved), and patches
    named in `rebaseline` (just refreshed), take the lane copy's current hash.
    A patch that was already applied without a record stays unrecorded, so
    `he check` keeps reporting it.
    """
    previous = _applied_record(paths)
    before_path = paths.state / BEFORE_PUSH
    before = read_json(before_path)
    before_push = set(before) if isinstance(before, list) else None
    current = {}
    for name in quilt.applied(paths.src):
        copy = paths.catalog / name
        if name in previous and name not in rebaseline:
            current[name] = previous[name]
        elif (name in rebaseline or (before_push is not None and name not in before_push)) and copy.is_file():
            current[name] = sha256_file(copy)
    write_json(paths.state / APPLIED, {"version": 1, "patches": current})
    before_path.unlink(missing_ok=True)


def applied_drift(paths: Paths) -> list[str]:
    record = _applied_record(paths)
    problems, unrecorded = [], []
    for name in quilt.applied(paths.src):
        copy = paths.catalog / name
        if name not in record:
            unrecorded.append(name)
        elif not copy.is_file() or sha256_file(copy) != record[name]:
            problems.append(f"{name} changed in the lane catalog after it was applied; "
                            "run he save-patch if you refreshed it, otherwise he replay")
    if len(unrecorded) > 3:
        problems.append(f"{len(unrecorded)} patches were applied outside he (first: {unrecorded[0]}); run he replay to be sure")
    else:
        problems += [f"{name} was applied outside he; run he replay to be sure" for name in unrecorded]
    return problems


# Out-of-graph stamps --------------------------------------------------------

def _hash_inputs(worktree: Path, inputs: tuple[str, ...]) -> str:
    entries = []
    for relative in inputs:
        root = worktree / relative
        if root.is_file():
            entries.append(f"{relative}\0{sha256_file(root)}")
        elif root.is_dir():
            for directory, names, files in os.walk(root):
                names[:] = sorted(n for n in names if n not in _SKIP_NAMES)
                for name in sorted(files):
                    if name in _SKIP_NAMES:
                        continue
                    path = Path(directory) / name
                    entries.append(f"{path.relative_to(worktree).as_posix()}\0{sha256_file(path)}")
        else:
            entries.append(f"{relative}\0missing")
    return sha256_bytes("\n".join(entries).encode())


def record_stamp(paths: Paths, name: str) -> None:
    stamps = read_json(paths.state / STAMPS) or {}
    stamps[name] = _hash_inputs(paths.worktree, STAMP_INPUTS[name])
    write_json(paths.state / STAMPS, stamps)


def stamp_drift(paths: Paths) -> list[str]:
    stamps = read_json(paths.state / STAMPS) or {}
    problems = []
    for name, inputs in STAMP_INPUTS.items():
        recorded = stamps.get(name)
        if recorded is None:
            problems.append(f"{name}: not recorded for this build dir; run {STAMP_FIX[name]} once to record it")
        elif recorded != _hash_inputs(paths.worktree, inputs):
            problems.append(f"{name} inputs changed since they were applied; run {STAMP_FIX[name]}")
    return problems


# Acquisition ----------------------------------------------------------------

def _chromium_version(path: Path) -> str | None:
    """MAJOR.MINOR.BUILD.PATCH from chrome/VERSION, or a one-line version file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    if {"MAJOR", "MINOR", "BUILD", "PATCH"} <= fields.keys():
        return ".".join(fields[k].strip() for k in ("MAJOR", "MINOR", "BUILD", "PATCH"))
    return text.strip() or None


def record_acquisition(paths: Paths, source_mode: str) -> None:
    write_json(paths.state / ACQUISITION, {
        "version": 1,
        "arch": platform.machine(),
        "source_mode": source_mode,
        "chromium_version": _chromium_version(paths.src / "chrome" / "VERSION"),
    })


def acquisition_problems(paths: Paths) -> list[str]:
    """Reasons this build dir cannot serve the selected worktree."""
    have = _chromium_version(paths.src / "chrome" / "VERSION")
    want = _chromium_version(paths.worktree / "helium-chromium" / "chromium_version.txt")
    problems = []
    if have and want and have != want:
        problems.append(f"build dir holds Chromium {have}, but {paths.worktree} pins {want}; "
                        "use a build dir for that version")
    record = read_json(paths.state / ACQUISITION)
    if isinstance(record, dict) and record.get("arch") not in (None, platform.machine()):
        problems.append(f"build dir was prepared for {record['arch']}, this machine is {platform.machine()}")
    return problems


def require_compatible(paths: Paths) -> None:
    problems = acquisition_problems(paths)
    if problems:
        raise HeError(problems[0])


def source_mode(paths: Paths) -> str | None:
    record = read_json(paths.state / ACQUISITION)
    if isinstance(record, dict) and record.get("source_mode"):
        return record["source_mode"]
    legacy = paths.state / "source-mode"
    return legacy.read_text(encoding="utf-8").strip() if legacy.is_file() else None
