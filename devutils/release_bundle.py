#!/usr/bin/env python3
"""Stage a release copy of the Chromium-built app under Arcium's identity."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from arcium.bundle import ARCIUM_BUNDLE_ID, ARCIUM_NAME, PROFILE_DIR_NAME, ArciumError, rewrite_metadata
from he.apps import copy_app, read_plist
from he.common import HeError


class ReleaseBundleError(RuntimeError):
    """A release copy could not be staged safely."""


def stage_release_bundle(
    source: Path,
    destination: Path,
) -> dict[str, object]:
    """Copy Helium.app, rewrite only the copy, then verify its root identity."""

    source_input = Path(source).expanduser()
    destination_input = Path(destination).expanduser()
    if source_input.is_symlink() or not source_input.is_dir():
        raise ReleaseBundleError(f"built app is missing or unsafe: {source_input}")
    if destination_input.exists() or destination_input.is_symlink():
        raise ReleaseBundleError(
            f"refusing to overwrite staged release app: {destination_input}"
        )

    source_path = source_input.resolve()
    # Resolve the parent independently so a symlinked ancestor cannot make an
    # apparently external destination point back into the source app.
    destination_parent = destination_input.parent.resolve()
    destination_path = destination_parent / destination_input.name
    if destination_path == source_path or source_path in destination_path.parents:
        raise ReleaseBundleError("release app destination must be outside the source app")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        copy_method = copy_app(source_path, destination_path)
        plist_count = rewrite_metadata(destination_path)
        root_info = read_plist(destination_path / "Contents" / "Info.plist")
        expected = {
            "CFBundleIdentifier": ARCIUM_BUNDLE_ID,
            "CFBundleDisplayName": ARCIUM_NAME,
            "CFBundleName": ARCIUM_NAME,
            "CrProductDirName": PROFILE_DIR_NAME,
        }
        for key, value in expected.items():
            if root_info.get(key) != value:
                raise ReleaseBundleError(f"staged app has incorrect {key}")
    except Exception:
        if destination_path.is_dir() and not destination_path.is_symlink():
            shutil.rmtree(destination_path, ignore_errors=True)
        elif destination_path.exists() or destination_path.is_symlink():
            destination_path.unlink(missing_ok=True)
        raise

    return {
        "app_path": str(destination_path),
        "bundle_identifier": ARCIUM_BUNDLE_ID,
        "copy_method": copy_method,
        "display_name": ARCIUM_NAME,
        "executable_name": root_info.get("CFBundleExecutable"),
        "plist_count": plist_count,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        staged = stage_release_bundle(args.source, args.destination)
    except (
        HeError,
        OSError,
        ReleaseBundleError,
        subprocess.SubprocessError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        f"staged {staged['display_name']} at {staged['app_path']} "
        f"({staged['copy_method']}, {staged['plist_count']} property lists)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
