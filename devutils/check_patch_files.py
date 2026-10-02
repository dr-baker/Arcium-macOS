#!/usr/bin/env python3
"""Validate the active Arcium-macOS patch catalog."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.util
import sys
import tempfile
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parent.parent
_CORE_DEVUTILS = _PLATFORM_ROOT / "helium-chromium" / "devutils"
_CORE_CHECKER_PATH = _CORE_DEVUTILS / "check_patch_files.py"
_CORE_CHECKER_SPEC = importlib.util.spec_from_file_location(
    "_arcium_core_check_patch_files", _CORE_CHECKER_PATH)
if _CORE_CHECKER_SPEC is None or _CORE_CHECKER_SPEC.loader is None:
    raise ImportError(f"Unable to load {_CORE_CHECKER_PATH}")
_CORE_CHECKER = importlib.util.module_from_spec(_CORE_CHECKER_SPEC)
sys.modules[_CORE_CHECKER_SPEC.name] = _CORE_CHECKER
sys.path.insert(0, str(_CORE_DEVUTILS))
try:
    _CORE_CHECKER_SPEC.loader.exec_module(_CORE_CHECKER)
finally:
    sys.path.pop(0)

check_patch_readability = _CORE_CHECKER.check_patch_readability
check_series_duplicates = _CORE_CHECKER.check_series_duplicates
check_unused_patches = _CORE_CHECKER.check_unused_patches

_SERIES_NAMES = ("series", "series.merged")
_MERGE_METADATA = {"series", "series.merged", "series.orig", "series.prepend"}


def active_series(patches_dir: Path) -> Path:
    """Return the sole active series file in patches_dir."""
    candidates = [patches_dir / name for name in _SERIES_NAMES
                  if (patches_dir / name).is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(f"No active series file found in {patches_dir}")
    names = ", ".join(path.name for path in candidates)
    raise ValueError(f"Ambiguous patch catalog in {patches_dir}: {names}")


@contextmanager
def _staged_patch_view(patches_dir: Path, series_path: Path):
    """Yield a checker view with the selected series exposed as `series`."""
    with tempfile.TemporaryDirectory(prefix="arcium-patch-check-") as temp_dir:
        view = Path(temp_dir)
        for path in patches_dir.rglob("*"):
            relative_path = path.relative_to(patches_dir)
            if (relative_path.parent == Path(".") and
                    relative_path.name in _MERGE_METADATA):
                continue
            if path.is_dir():
                continue
            destination = view / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(path)

        (view / "series").symlink_to(series_path)
        yield view


def validate_patches_dir(patches_dir: Path) -> bool:
    """Return whether the active patch catalog produced any warnings."""
    patches_dir = patches_dir.expanduser().resolve()
    selected_series = active_series(patches_dir)
    with _staged_patch_view(patches_dir, selected_series) as view:
        series_path = Path("series")
        warnings = False
        warnings |= check_patch_readability(view, series_path)
        warnings |= check_series_duplicates(view, series_path)
        warnings |= check_unused_patches(view, series_path)
        return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-p",
        "--patches",
        type=Path,
        default=_PLATFORM_ROOT / "patches",
        help="Path to the patch directory (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        warnings = validate_patches_dir(args.patches)
    except ValueError as error:
        parser.error(str(error))
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
