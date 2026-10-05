#!/usr/bin/env python3
"""Check Quilt-owned source changes without requiring a Git checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

try:
    from .quilt_state import QuiltStateError, read_patch_list
except ImportError:  # Executed as a standalone devutils script.
    from quilt_state import QuiltStateError, read_patch_list


class SourceCheckError(RuntimeError):
    """The source could not be checked or contains a checked-in error."""


def first_patch_reject(source_dir: Path) -> Path | None:
    """Find a source reject without scanning top-level output or metadata.

    Nested directories with these names remain source and must be checked.
    Match any entry named *.rej without descending through directory symlinks.
    Unreadable source fails the check.
    """
    root = os.fspath(source_dir)

    def fail(error: OSError) -> None:
        raise error

    for directory, directories, files in os.walk(root, topdown=True, onerror=fail,
                                                 followlinks=False):
        if directory == root:
            directories[:] = [name for name in directories if name not in {"out", ".git", ".pc"}]
        for names in (directories, files):
            for name in names:
                if name.endswith(".rej"):
                    return Path(directory) / name
    return None


def _run_git_diff_check(source_dir: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(source_dir), "diff", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise SourceCheckError(
            detail or f"git diff --check failed with status {result.returncode}"
        )


def _is_source_git_root(source_dir: Path) -> bool:
    """Return whether source_dir, rather than an enclosing repo, is the root."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if result.returncode:
        return False
    try:
        return Path(result.stdout.strip()).resolve() == source_dir
    except (OSError, RuntimeError):
        return False


def _safe_patch_path(patch: str) -> Path:
    path = Path(patch)
    if path.is_absolute() or ".." in path.parts or patch in {"", ".", ".."}:
        raise SourceCheckError(f"unsafe applied patch name: {patch}")
    return path


def _first_patch_preimages(source_dir: Path, applied: tuple[str, ...]) -> dict[Path, Path]:
    """Map every Quilt-owned path to its first applied patch preimage."""
    preimages: dict[Path, Path] = {}
    for patch in applied:
        patch_path = _safe_patch_path(patch)
        patch_dir = source_dir / ".pc" / patch_path
        if not patch_dir.is_dir():
            raise SourceCheckError(f"Quilt preimage directory is missing: {patch}")
        try:
            entries = sorted(patch_dir.rglob("*"))
        except OSError as error:
            raise SourceCheckError(
                f"could not enumerate Quilt preimages for {patch}"
            ) from error
        for entry in entries:
            relative = entry.relative_to(patch_dir)
            if relative == Path(".timestamp") or entry.is_dir():
                continue
            try:
                metadata = entry.lstat()
            except OSError as error:
                raise SourceCheckError(
                    f"could not inspect Quilt preimage: {patch}/{relative}"
                ) from error
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)):
                raise SourceCheckError(
                    f"unsupported Quilt preimage type: {patch}/{relative}"
                )
            preimages.setdefault(relative, entry)
    return preimages


def _materialize_link(source: Path, destination: Path) -> None:
    """Link a preimage or source file into a temporary comparison tree."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = source.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        destination.symlink_to(os.readlink(source))
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise SourceCheckError(f"unsupported source path type: {source}")
    try:
        os.link(source, destination)
    except OSError:
        # A source and temporary directory can live on different volumes.
        try:
            shutil.copy2(source, destination)
        except OSError as error:
            raise SourceCheckError(f"could not stage source path: {source}") from error


def _check_quilt_source(source_dir: Path) -> None:
    applied_path = source_dir / ".pc" / "applied-patches"
    if not applied_path.exists() and not applied_path.is_symlink():
        # A missing ledger is Quilt's fully-popped representation. The caller's
        # complete-state check rejects it when the declared series is non-empty.
        return
    try:
        applied = read_patch_list(applied_path)
    except QuiltStateError as error:
        raise SourceCheckError(str(error)) from error
    preimages = _first_patch_preimages(source_dir, applied)
    if not preimages:
        return

    try:
        temporary = tempfile.TemporaryDirectory(
            prefix=".arcium-source-check-", dir=source_dir.parent
        )
    except OSError as error:
        raise SourceCheckError("could not create source-check workspace") from error
    with temporary:
        root = Path(temporary.name)
        before = root / "before"
        after = root / "after"
        for relative, preimage in preimages.items():
            _materialize_link(preimage, before / relative)
            current = source_dir / relative
            if current.exists() or current.is_symlink():
                _materialize_link(current, after / relative)

        result = subprocess.run(
            ["git", "diff", "--no-index", "--check", str(before), str(after)],
            check=False,
            capture_output=True,
            text=True,
        )
    # git diff --no-index returns 1 for ordinary content differences. Its
    # dedicated check status (3) and all command failures remain errors.
    if result.returncode not in (0, 1):
        detail = (result.stdout + result.stderr).strip()
        raise SourceCheckError(
            detail
            or f"source whitespace/conflict check failed with status {result.returncode}"
        )


def check_source(source_dir: Path) -> None:
    """Validate source changes using the native Git or Quilt representation."""
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise SourceCheckError(f"source directory is missing: {source_dir}")
    rejected = first_patch_reject(source_dir)
    if rejected is not None:
        raise SourceCheckError(f"patch rejects remain in the development source: {rejected}")
    if _is_source_git_root(source_dir):
        _run_git_diff_check(source_dir)
    else:
        _check_quilt_source(source_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        check_source(arguments.source)
    except (OSError, SourceCheckError) as error:
        print(f"check: source validation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
