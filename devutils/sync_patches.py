#!/usr/bin/env python3
"""Synchronize generated outer patch copies from the authoritative core tree."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import tempfile

from quilt_state import QuiltStateError, inspect_quilt_state, read_patch_list


class SyncError(RuntimeError):
    """The generated patch catalog cannot be safely synchronized."""


def _read_quilt_metadata(path: Path, description: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SyncError(f"could not read {description}: {path}") from error
    if not value or "\n" in value or "\x00" in value:
        raise SyncError(f"invalid {description}: {path}")
    return value


def _require_missing_applied_is_clean(source_dir: Path, outer_patches: Path) -> None:
    """Validate Quilt provenance when pop removed ``applied-patches``."""
    pc_dir = source_dir / ".pc"
    pointer = Path(_read_quilt_metadata(pc_dir / ".quilt_patches", "Quilt patch pointer"))
    if not pointer.is_absolute():
        pointer = source_dir / pointer
    if pointer.resolve() != outer_patches.resolve():
        raise SyncError(
            "Quilt patch provenance does not point to the selected outer patches"
        )
    if _read_quilt_metadata(pc_dir / ".quilt_series", "Quilt series pointer") != "series.merged":
        raise SyncError("Quilt series pointer does not select series.merged")
    try:
        declared = read_patch_list(outer_patches / "series.merged")
    except QuiltStateError as error:
        raise SyncError(f"could not validate the merged Quilt catalog: {error}") from error
    if len(set(declared)) != len(declared):
        raise SyncError("merged Quilt catalog contains duplicate patches")


def _regular_bytes(path: Path, description: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SyncError(f"missing {description}: {path}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise SyncError(f"{description} must be a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise SyncError(f"could not read {description}: {path}") from error


def _stage_file(source: Path, destination: Path, staging: Path) -> Path:
    relative = destination.relative_to(staging.parent)
    staged = staging / relative
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, staged)
    return staged


def _install_staged(
    staged_files: list[tuple[Path, Path]], staging: Path
) -> None:
    backup = staging / ".backup"
    moved: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for destination, _staged in staged_files:
            if destination.is_symlink() or destination.exists():
                metadata = destination.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise SyncError(f"generated destination is not a regular file: {destination}")
                backup_path = backup / destination.relative_to(staging.parent)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup_path)
                moved.append((destination, backup_path))
        for destination, staged in staged_files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
            installed.append(destination)
    except (OSError, SyncError) as error:
        for destination in reversed(installed):
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            for destination, backup_path in reversed(moved):
                os.replace(backup_path, destination)
        except OSError as rollback_error:
            raise SyncError(
                "patch synchronization failed and could not fully restore generated files"
            ) from rollback_error
        if isinstance(error, SyncError):
            raise
        raise SyncError("patch synchronization failed; generated files were restored") from error


def sync_generated_patches(worktree: Path, source_dir: Path) -> None:
    """Refresh only generated core copies while preserving outer patches.

    This operation intentionally runs in merged-catalog mode.  The source
    must be fully popped first so no generated source is left referring to the
    old patch bytes.  The outer ``series.orig`` and its platform patch files
    are read-only inputs; only generated core copies, ``series.prepend``, and
    ``series.merged`` are replaced.
    """
    worktree = worktree.resolve()
    source_dir = source_dir.resolve()
    core_patches = worktree / "helium-chromium" / "patches"
    outer_patches = worktree / "patches"
    core_series = core_patches / "series"
    platform_series = outer_patches / "series.orig"
    merged_series = outer_patches / "series.merged"
    if not core_series.is_file():
        raise SyncError("authoritative helium-chromium/patches/series is missing")
    if not platform_series.is_file() or not merged_series.is_file():
        raise SyncError(
            "generated patch state is not merged; run he merge with Quilt fully popped"
        )

    applied_path = source_dir / ".pc" / "applied-patches"
    if applied_path.is_symlink() or applied_path.exists():
        try:
            report = inspect_quilt_state(source_dir, outer_patches)
            report.comparison.require_valid_prefix()
        except QuiltStateError as error:
            raise SyncError(f"cannot inspect Quilt state: {error}") from error
        if report.comparison.applied:
            raise SyncError(
                "sync-patches requires Quilt to be fully popped; run he pop, then retry"
            )
    else:
        _require_missing_applied_is_clean(source_dir, outer_patches)

    try:
        authored = read_patch_list(core_series)
        platform = read_patch_list(platform_series)
    except QuiltStateError as error:
        raise SyncError(f"could not read authoritative patch catalogs: {error}") from error
    overlap = sorted(set(authored).intersection(platform))
    if overlap:
        raise SyncError(
            "core and outer patch catalogs overlap: "
            + ", ".join(overlap)
        )
    for name in authored:
        _regular_bytes(core_patches / name, f"authoritative core patch {name}")

    platform_bytes = _regular_bytes(platform_series, "outer platform catalog")
    merged_bytes = b"".join(f"{name}\n".encode("utf-8") for name in authored)
    merged_bytes += platform_bytes
    if merged_bytes and not merged_bytes.endswith(b"\n"):
        merged_bytes += b"\n"

    try:
        staging = Path(tempfile.mkdtemp(prefix=".sync-patches-", dir=outer_patches))
    except OSError as error:
        raise SyncError("could not create generated patch staging area") from error
    staged_files: list[tuple[Path, Path]] = []
    try:
        for name in authored:
            destination = outer_patches / name
            staged_files.append(
                (destination, _stage_file(core_patches / name, destination, staging))
            )
        prepend = outer_patches / "series.prepend"
        prepend_stage = staging / "series.prepend"
        prepend_stage.write_bytes(core_series.read_bytes())
        staged_files.append((prepend, prepend_stage))
        merged_stage = staging / "series.merged"
        merged_stage.write_bytes(merged_bytes)
        staged_files.append((merged_series, merged_stage))
        _install_staged(staged_files, staging)
    except OSError as error:
        raise SyncError("could not stage generated patch copies; no core files were changed") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        sync_generated_patches(arguments.worktree, arguments.source)
    except (OSError, SyncError) as error:
        print(str(error))
        return 2
    print("generated core patches synchronized; run he replay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
