#!/usr/bin/env python3
"""Give an extracted Chromium build lane the identity depot_tools expects."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


class GClientIdentityError(RuntimeError):
    """The generated lane cannot be identified safely by depot_tools."""


_GCLIENT = b'''# Arcium generated-build discovery marker. Do not run gclient sync here.\nsolutions = [\n    {\n        "name": "src",\n        "url": "https://chromium.googlesource.com/chromium/src.git",\n        "managed": False,\n        "custom_deps": {},\n        "custom_vars": {},\n        "safesync_url": "",\n    },\n]\n'''
_GCLIENT_ENTRIES = b'''# Arcium generated-build discovery marker.\nentries = {\n    "src": "https://chromium.googlesource.com/chromium/src.git",\n}\n'''


def _primary_solution(source: Path, from_dir: Path) -> Path | None:
    depot_tools = source / "third_party" / "depot_tools"
    module = depot_tools / "gclient_paths.py"
    if not module.is_file():
        raise GClientIdentityError(f"depot_tools gclient_paths.py is missing: {module}")
    script = (
        "import sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "import gclient_paths; "
        "value = gclient_paths.GetPrimarySolutionPath(sys.argv[2]); "
        "print(value or '')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(depot_tools), str(from_dir)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise GClientIdentityError(detail or "depot_tools root discovery failed")
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def _publish_new_marker(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        try:
            metadata = path.lstat()
            existing = path.read_bytes()
        except OSError as error:
            raise GClientIdentityError(f"could not inspect lane marker: {path}") from error
        if not stat.S_ISREG(metadata.st_mode) or existing != content:
            raise GClientIdentityError(
                f"refusing to replace existing gclient metadata: {path}"
            )
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.arcium-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise GClientIdentityError(f"could not publish lane marker: {path}") from error


def _is_real_git_checkout(source: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode or not result.stdout.strip():
        return False
    return Path(result.stdout.strip()).resolve() == source


def ensure_gclient_identity(build_root: Path) -> Path:
    """Ensure depot_tools resolves this generated lane to its Chromium source."""
    root = build_root.expanduser().resolve()
    source = root / "src"
    out = source / "out" / "Default"
    sisoenv = source / "build" / "config" / "siso" / ".sisoenv"
    if not source.is_dir() or not out.is_dir() or not sisoenv.is_file():
        raise GClientIdentityError(
            "generated lane is missing Chromium source, out/Default, or .sisoenv"
        )

    marker = root / ".gclient"
    entries = root / ".gclient_entries"
    marker_state = (marker.exists() or marker.is_symlink(), entries.exists() or entries.is_symlink())
    generated_markers = False
    if any(marker_state):
        if not all(marker_state):
            raise GClientIdentityError("generated lane has incomplete gclient metadata")
        generated_markers = (
            marker.is_file()
            and not marker.is_symlink()
            and marker.read_bytes() == _GCLIENT
            and entries.is_file()
            and not entries.is_symlink()
            and entries.read_bytes() == _GCLIENT_ENTRIES
        )

    discovered = _primary_solution(source, out)
    if discovered == source:
        if generated_markers or _is_real_git_checkout(source):
            return source
        if any(marker_state):
            raise GClientIdentityError(
                "refusing foreign gclient metadata in a generated build lane"
            )
        # An ancestor marker can resolve coincidentally to this source. Publish
        # exact lane-local markers so future discovery is independent of it.
    elif discovered is not None:
        raise GClientIdentityError(
            f"depot_tools resolved the lane to an unexpected source: {discovered}"
        )

    _publish_new_marker(marker, _GCLIENT)
    _publish_new_marker(entries, _GCLIENT_ENTRIES)
    discovered = _primary_solution(source, out)
    if discovered != source:
        raise GClientIdentityError(
            "depot_tools still cannot identify the generated Chromium source"
        )
    return source


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if len(values) != 1:
        print("usage: gclient_identity.py BUILD_ROOT", file=sys.stderr)
        return 2
    try:
        source = ensure_gclient_identity(Path(values[0]))
    except GClientIdentityError as error:
        print(f"gclient identity error: {error}", file=sys.stderr)
        return 1
    print(f"depot_tools source identity: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
