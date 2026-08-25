"""Create a private, independently identifiable Helium Dev application.

The Chromium build emits ``Helium.app``.  The runtime harness deliberately
selects ``Helium Dev.app`` so a worktree can be exercised without colliding
with a release build or with another worktree.  This module owns that small
packaging boundary: it validates the build first, clones the application into
an owned staging directory, rewrites only copied metadata, and signs the copy
before publishing it atomically.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class BundleError(RuntimeError):
    """The current build cannot be packaged safely as a Dev bundle."""


@dataclass(frozen=True)
class BundlePaths:
    worktree: Path
    source_dir: Path
    out_dir: Path
    source_app: Path
    dev_app: Path


CopyRunner = Callable[..., object]
Signer = Callable[[Path], None]


def resolve_bundle_paths(root: str | os.PathLike[str]) -> BundlePaths:
    worktree = Path(root).expanduser().resolve()
    source_dir = worktree / "build" / "src"
    out_dir = source_dir / "out" / "Default"
    return BundlePaths(
        worktree=worktree,
        source_dir=source_dir,
        out_dir=out_dir,
        source_app=out_dir / "Helium.app",
        dev_app=out_dir / "Helium Dev.app",
    )


def _read_plist(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise BundleError(f"could not read bundle metadata: {path.name}") from error
    if not isinstance(value, dict):
        raise BundleError(f"bundle metadata is not a dictionary: {path.name}")
    return value


def _safe_executable_name(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise BundleError("Helium.app has no safe CFBundleExecutable")
    if "/" in value or "\\" in value or "\x00" in value:
        raise BundleError("Helium.app has no safe CFBundleExecutable")
    return value


def _require_fresh_source(
    paths: BundlePaths, *, require_dev_destination_absent: bool = True
) -> dict[str, object]:
    if require_dev_destination_absent and (
        paths.dev_app.exists() or paths.dev_app.is_symlink()
    ):
        raise BundleError(f"refusing to overwrite existing Dev bundle: {paths.dev_app}")
    if paths.source_app.is_symlink() or not paths.source_app.is_dir():
        raise BundleError(f"Helium.app is missing from {paths.out_dir}")

    root_plist_path = paths.source_app / "Contents" / "Info.plist"
    executable_info = _read_plist(root_plist_path)
    executable_name = _safe_executable_name(executable_info.get("CFBundleExecutable"))
    executable_path = paths.source_app / "Contents" / "MacOS" / executable_name
    component_path = paths.out_dir / "libchrome_dll.dylib"
    build_graph = paths.out_dir / "build.ninja"
    args_path = paths.out_dir / "args.gn"
    for path, description in (
        (root_plist_path, "Helium.app metadata"),
        (executable_path, "Helium executable"),
        (component_path, "component library"),
        (build_graph, "generated build graph"),
        (args_path, "generated build arguments"),
    ):
        if not path.is_file():
            raise BundleError(f"{description} is missing: {path}")
    if not os.access(executable_path, os.X_OK):
        raise BundleError(f"Helium executable is not executable: {executable_path}")

    graph_mtime = build_graph.stat().st_mtime_ns
    stale_inputs = [
        path
        for path in (executable_path, component_path)
        if path.stat().st_mtime_ns < graph_mtime
    ]
    if stale_inputs:
        names = ", ".join(path.name for path in stale_inputs)
        raise BundleError(f"build artifacts are older than build.ninja: {names}")
    return {
        "root_info": executable_info,
        "executable_name": executable_name,
        "executable_path": executable_path,
        "component_path": component_path,
        "build_graph": build_graph,
    }


def _copy_source(source: Path, destination: Path, runner: CopyRunner | None) -> str:
    """Use APFS clonefile-aware copy first, with a safe owned fallback."""

    command_runner = subprocess.run if runner is None else runner
    try:
        command_runner(
            ["/bin/cp", "-cR", str(source), str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        return "apfs-clone"
    except (OSError, subprocess.CalledProcessError):
        # ``destination`` lives below a newly-created staging directory.  It
        # is therefore safe to remove a partial clone before falling back.
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
    try:
        shutil.copytree(source, destination, symlinks=True)
    except OSError as error:
        raise BundleError("could not clone or copy Helium.app") from error
    return "fallback-copy"


def _dev_suffix(value: str, suffix: str) -> str:
    return value if value.endswith(suffix) else value + suffix


def _dev_name(value: str) -> str:
    return value if value.endswith(" Dev") else value + " Dev"


def _write_plist(path: Path, info: dict[str, object], original: bytes) -> None:
    fmt = plistlib.FMT_BINARY if original.startswith(b"bplist00") else plistlib.FMT_XML
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            plistlib.dump(info, handle, fmt=fmt, sort_keys=False)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def rewrite_dev_metadata(app_path: Path) -> int:
    """Give every copied local bundle a distinct Dev identity.

    Executable names remain byte-for-byte unchanged because Chromium's helper
    launch and framework lookup code expects those names.
    """

    plist_paths = sorted(app_path.rglob("Info.plist"))
    if not plist_paths:
        raise BundleError("copied Dev bundle has no Info.plist files")
    root_plist = app_path / "Contents" / "Info.plist"
    if root_plist not in plist_paths:
        raise BundleError("copied Dev bundle has no root Info.plist")
    changed = 0
    for path in plist_paths:
        try:
            original = path.read_bytes()
        except OSError as error:
            raise BundleError(f"could not read copied metadata: {path}") from error
        info = _read_plist(path)
        executable = info.get("CFBundleExecutable")
        if executable is not None:
            _safe_executable_name(executable)
        bundle_id = info.get("CFBundleIdentifier")
        if isinstance(bundle_id, str) and bundle_id:
            info["CFBundleIdentifier"] = _dev_suffix(bundle_id, ".dev")
        for key in ("CFBundleDisplayName", "CFBundleName"):
            value = info.get(key)
            if isinstance(value, str) and value:
                info[key] = _dev_name(value)
        if path == root_plist:
            info["CFBundleIdentifier"] = _dev_suffix(
                str(info.get("CFBundleIdentifier") or "net.imput.helium"), ".dev"
            )
            info["CFBundleDisplayName"] = "Helium Dev"
            info["CFBundleName"] = "Helium Dev"
        _write_plist(path, info, original)
        changed += 1
    return changed


def _codesign_path() -> str:
    for candidate in ("/usr/bin/codesign", "/bin/codesign"):
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    path = shutil.which("codesign")
    if path:
        return path
    raise BundleError("codesign is unavailable; refusing to publish Helium Dev.app")


def sign_and_verify_ad_hoc(app_path: Path) -> None:
    codesign = _codesign_path()
    try:
        subprocess.run(
            [codesign, "--force", "--deep", "--sign", "-", str(app_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [codesign, "--verify", "--deep", "--strict", str(app_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise BundleError("ad-hoc signing or verification failed") from error


def package_dev_bundle(
    root: str | os.PathLike[str],
    *,
    copy_runner: CopyRunner | None = None,
    signer: Signer | None = None,
) -> dict[str, object]:
    """Package and atomically publish ``Helium Dev.app`` for one worktree."""

    paths = resolve_bundle_paths(root)
    source = _require_fresh_source(paths)
    staging_root = Path(tempfile.mkdtemp(prefix=".helium-dev-bundle-", dir=paths.out_dir))
    staging_app = staging_root / paths.dev_app.name
    try:
        copy_method = _copy_source(paths.source_app, staging_app, copy_runner)
        plist_count = rewrite_dev_metadata(staging_app)
        if signer is None:
            sign_and_verify_ad_hoc(staging_app)
        else:
            signer(staging_app)
        if paths.dev_app.exists() or paths.dev_app.is_symlink():
            raise BundleError(f"refusing to overwrite existing Dev bundle: {paths.dev_app}")
        os.replace(staging_app, paths.dev_app)
        staging_root.rmdir()
    except BundleError:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    except (OSError, TypeError, ValueError) as error:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise BundleError("could not publish Helium Dev.app") from error

    root_info = _read_plist(paths.dev_app / "Contents" / "Info.plist")
    return {
        "ok": True,
        "action": "dev-bundle",
        "source_app": str(paths.source_app),
        "app_path": str(paths.dev_app),
        "bundle_identifier": root_info.get("CFBundleIdentifier"),
        "display_name": root_info.get("CFBundleDisplayName"),
        "executable": str(paths.dev_app / "Contents" / "MacOS" / source["executable_name"]),
        "source_freshness": {
            "build_graph": str(source["build_graph"]),
            "build_graph_mtime": source["build_graph"].stat().st_mtime_ns,
            "executable": str(source["executable_path"]),
            "executable_mtime": source["executable_path"].stat().st_mtime_ns,
            "component": str(source["component_path"]),
            "component_mtime": source["component_path"].stat().st_mtime_ns,
            "fresh": True,
        },
        "copy_method": copy_method,
        "plist_count": plist_count,
        "signature": "ad-hoc",
        "proof_gates": (
            "source-present",
            "source-fresh",
            "dev-identities-rewritten",
            "ad-hoc-signature-verified",
            "atomic-publish",
        ),
    }
