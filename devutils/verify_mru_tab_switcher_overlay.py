#!/usr/bin/env python3
"""Strict sparse verification for the private MRU tab-switcher overlay patch.

Only files touched by the feature patch are materialized. Earlier patches that
touch those files are applied in series order before the overlay patch is
checked with zero fuzz. Without --source-dir, sources are fetched from the exact
Chromium Gitiles revision in chromium_version.txt.
"""

from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

CHROMIUM_REPOSITORY = Path(__file__).resolve().parent.parent / "helium-chromium"

sys.path.insert(0, str(CHROMIUM_REPOSITORY / "devutils" / "third_party"))
from unidiff import PatchSet # pylint: disable=wrong-import-position

sys.path.insert(0, str(CHROMIUM_REPOSITORY / "utils"))
from _common import parse_series # pylint: disable=wrong-import-position


def _patch_paths(patch_path: Path) -> tuple[set[Path], set[Path]]:
    paths = set()
    added_paths = set()
    for patched_file in PatchSet.from_filename(str(patch_path)):
        paths.add(Path(patched_file.path))
        if patched_file.is_added_file:
            added_paths.add(Path(patched_file.path))
    return paths, added_paths


def _write_filtered_patch(patch_path: Path, target_paths: set[Path], output: Path) -> int:
    selected = []
    for patched_file in PatchSet.from_filename(str(patch_path)):
        if Path(patched_file.path) in target_paths:
            selected.append(str(patched_file).rstrip("\n"))
    if not selected:
        return 0
    output.write_text("\n".join(selected) + "\n", encoding="utf-8")
    return len(selected)


def _run_patch(patch_path: Path, fixture: Path, dry_run: bool) -> None:
    command = [
        "patch",
        "-p1",
        "--batch",
        "--forward",
        "--fuzz=0",
        "--no-backup-if-mismatch",
    ]
    if dry_run:
        command.append("--dry-run")
    command.extend(["-i", str(patch_path), "-d", str(fixture)])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        mode = "dry-run" if dry_run else "apply"
        raise RuntimeError(f"patch failed ({mode}): {patch_path}\n{detail}")


def _fetch_gitiles(version: str, path: Path, destination: Path) -> None:
    url = ("https://chromium.googlesource.com/chromium/src/+/"
           f"{version}/{path}?format=TEXT")
    try:
        with urlopen(url, timeout=30) as response: # nosec B310: fixed host
            encoded = response.read()
    except Exception as exc: # pylint: disable=broad-except
        raise RuntimeError(f"could not fetch {path} from {url}: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64decode(encoded, validate=True))


def _materialize_sources(
    target_paths: set[Path],
    added_paths: set[Path],
    source_dir: Path | None,
    version: str,
    fixture: Path,
) -> None:
    for path in sorted(target_paths):
        destination = fixture / path
        if source_dir is not None and (source_dir / path).is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_dir / path, destination)
            print(f"source {path}: local snapshot")
        elif source_dir is not None:
            if path not in added_paths:
                raise RuntimeError(f"source snapshot is missing modified file: {source_dir / path}")
            print(f"source {path}: new patch file")
        elif path in added_paths:
            print(f"source {path}: new patch file")
        else:
            _fetch_gitiles(version, path, destination)
            print(f"source {path}: fetched Chromium {version}")


def verify(
    source_dir: Path | None,
    fixture: Path | None,
    version: str,
    patch_path: Path,
    series_path: Path,
) -> Path:
    """Materialize the sparse source state and strictly apply the feature."""
    target_paths, added_paths = _patch_paths(patch_path)
    if not target_paths:
        raise RuntimeError(f"feature patch has no files: {patch_path}")

    created_fixture = fixture is None
    fixture_path = fixture or Path(tempfile.mkdtemp(prefix="helium-mru-overlay-"))
    fixture_path.mkdir(parents=True, exist_ok=True)
    print(f"fixture: {fixture_path}")
    print(f"target files: {len(target_paths)}")

    _materialize_sources(target_paths, added_paths, source_dir, version, fixture_path)

    temporary_patch = fixture_path / ".existing-series.patch"
    applied_existing = 0
    for entry in parse_series(series_path):
        candidate = series_path.parent / entry
        if candidate.resolve() == patch_path.resolve():
            break
        selected = _write_filtered_patch(candidate, target_paths, temporary_patch)
        if not selected:
            continue
        print(f"existing {entry}: {selected} touched file section(s)")
        _run_patch(temporary_patch, fixture_path, dry_run=True)
        _run_patch(temporary_patch, fixture_path, dry_run=False)
        applied_existing += 1

    print(f"existing patches applied: {applied_existing}")
    _run_patch(patch_path, fixture_path, dry_run=True)
    print("feature patch: strict dry-run passed")
    _run_patch(patch_path, fixture_path, dry_run=False)
    print("feature patch: strict apply passed")
    for path in sorted(target_paths):
        print(f"verified: {path}")

    if created_fixture:
        shutil.rmtree(fixture_path)
        print("fixture removed")
    return fixture_path


def main() -> int:
    """Run the command-line verifier."""
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="offline Chromium source snapshot root",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="keep or use this sparse fixture directory",
    )
    parser.add_argument(
        "--version",
        default=(CHROMIUM_REPOSITORY / "chromium_version.txt").read_text(
            encoding="utf-8"
        ).strip(),
    )
    parser.add_argument(
        "--patch",
        type=Path,
        default=root / "patches/personal/mru-tab-switcher-overlay.patch",
    )
    parser.add_argument(
        "--series",
        type=Path,
        default=root / "patches/series.merged",
    )
    args = parser.parse_args()

    try:
        verify(
            args.source_dir.resolve() if args.source_dir else None,
            args.fixture.resolve() if args.fixture else None,
            args.version,
            args.patch.resolve(),
            args.series.resolve(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
