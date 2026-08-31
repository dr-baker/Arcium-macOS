#!/usr/bin/env python3
"""Manage one lane-local generated Quilt patch catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
import fcntl

from quilt_state import QuiltStateError, inspect_quilt_state, read_patch_list


class PatchWorkspaceError(RuntimeError):
    """A generated patch workspace is missing, stale, or unsafe to change."""


@contextmanager
def _authoritative_lock(worktree: Path):
    """Serialize authoritative patch mutations across all build lanes."""
    common = _git_common_directory(worktree)
    common.mkdir(parents=True, exist_ok=True)
    with (common / "arcium-authoritative.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _git_common_directory(worktree: Path) -> Path:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise PatchWorkspaceError("could not locate the repository-wide patch lock")
    value = result.stdout.strip()
    if not value:
        raise PatchWorkspaceError("repository-wide patch lock path is empty")
    return Path(value).expanduser().resolve()


def _replace_bytes(path: Path, content: bytes, label: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.{label}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def generated_root(build_root: Path) -> Path:
    return build_root.expanduser().resolve() / ".arcium" / "patches"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_bytes(path: Path, description: str) -> bytes:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise PatchWorkspaceError(f"{description} must be a regular file: {path}")
        return path.read_bytes()
    except PatchWorkspaceError:
        raise
    except OSError as error:
        raise PatchWorkspaceError(f"could not read {description}: {path}") from error


def _series(path: Path, description: str) -> tuple[tuple[str, ...], bytes]:
    raw = _regular_bytes(path, description)
    try:
        names = read_patch_list(path)
    except QuiltStateError as error:
        raise PatchWorkspaceError(str(error)) from error
    if not names:
        raise PatchWorkspaceError(f"{description} is empty: {path}")
    return names, raw


def _with_final_newline(value: bytes) -> bytes:
    return value if not value or value.endswith(b"\n") else value + b"\n"


def _authoritative_state(worktree: Path) -> dict[str, object]:
    core_root = worktree / "helium-chromium" / "patches"
    outer_root = worktree / "patches"
    core_names, core_series = _series(core_root / "series", "core patch catalog")
    outer_names, outer_series = _series(outer_root / "series", "outer patch catalog")
    overlap = sorted(set(core_names).intersection(outer_names))
    if overlap:
        raise PatchWorkspaceError(
            "core and outer patch catalogs overlap: " + ", ".join(overlap)
        )

    hashes: dict[str, str] = {}
    owners: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for owner, root, names in (
        ("core", core_root, core_names),
        ("outer", outer_root, outer_names),
    ):
        for name in names:
            content = _regular_bytes(root / name, f"authoritative {owner} patch {name}")
            hashes[name] = _sha256_bytes(content)
            owners[name] = owner
            contents[name] = content
    return {
        "core_names": core_names,
        "outer_names": outer_names,
        "core_series": core_series,
        "outer_series": outer_series,
        "hashes": hashes,
        "owners": owners,
        "contents": contents,
    }


def _manifest(authoritative: dict[str, object]) -> dict[str, object]:
    core_series = authoritative["core_series"]
    outer_series = authoritative["outer_series"]
    assert isinstance(core_series, bytes)
    assert isinstance(outer_series, bytes)
    return {
        "schema_version": 1,
        "core": list(authoritative["core_names"]),
        "outer": list(authoritative["outer_names"]),
        "owners": authoritative["owners"],
        "hashes": authoritative["hashes"],
        "core_series_sha256": _sha256_bytes(core_series),
        "outer_series_sha256": _sha256_bytes(outer_series),
    }


def _write_workspace(staging: Path, authoritative: dict[str, object]) -> None:
    contents = authoritative["contents"]
    assert isinstance(contents, dict)
    for name, content in contents.items():
        destination = staging / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    core_series = authoritative["core_series"]
    outer_series = authoritative["outer_series"]
    assert isinstance(core_series, bytes)
    assert isinstance(outer_series, bytes)
    (staging / "series.prepend").write_bytes(core_series)
    (staging / "series.orig").write_bytes(outer_series)
    (staging / "series.merged").write_bytes(
        _with_final_newline(core_series) + outer_series
    )
    (staging / "manifest.json").write_text(
        json.dumps(_manifest(authoritative), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _replace_directory(staging: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise PatchWorkspaceError(
                f"generated patch root must be a directory: {destination}"
            )
        backup = Path(
            tempfile.mkdtemp(prefix=".patches-backup-", dir=destination.parent)
        )
        backup.rmdir()
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except OSError as error:
        if backup is not None and backup.exists():
            os.replace(backup, destination)
        raise PatchWorkspaceError("could not publish generated patch workspace") from error
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def _require_popped_or_unprepared(source_dir: Path | None, root: Path) -> bool:
    if source_dir is None:
        return False
    source_dir = source_dir.expanduser().resolve()
    metadata = source_dir / ".pc"
    if not metadata.is_dir():
        return False
    pointer_path = metadata / ".quilt_patches"
    try:
        pointer_value = pointer_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PatchWorkspaceError(
            f"could not read Quilt patch pointer: {pointer_path}"
        ) from error
    pointer = Path(pointer_value).expanduser()
    if not pointer.is_absolute():
        pointer = source_dir / pointer
    if pointer.resolve() != root:
        applied_path = metadata / "applied-patches"
        if applied_path.exists() or applied_path.is_symlink():
            try:
                legacy_applied = read_patch_list(applied_path)
            except QuiltStateError as error:
                raise PatchWorkspaceError(str(error)) from error
            if legacy_applied:
                raise PatchWorkspaceError(
                    f"legacy Quilt patch root {pointer.resolve()} is active; fully "
                    "pop that stack with its original QUILT_PATCHES, then run "
                    "he prepare-patches"
                )
        return True
    try:
        report = inspect_quilt_state(source_dir, root)
        report.comparison.require_valid_prefix()
    except QuiltStateError as error:
        raise PatchWorkspaceError(str(error)) from error
    if report.comparison.applied:
        raise PatchWorkspaceError(
            "generated patches cannot be replaced while Quilt patches are applied; "
            "run he pop first"
        )
    return False


def _migrate_popped_pointer(source_dir: Path, root: Path) -> None:
    """Move fully-popped Quilt metadata to the lane-local catalog."""
    pointer = source_dir / ".pc" / ".quilt_patches"
    metadata = pointer.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise PatchWorkspaceError(f"Quilt patch pointer must be a regular file: {pointer}")
    temporary = pointer.with_name(".quilt_patches.arcium-migrate")
    try:
        temporary.write_text(str(root) + "\n", encoding="utf-8")
        os.replace(temporary, pointer)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise PatchWorkspaceError(
            f"could not migrate Quilt patch pointer to {root}"
        ) from error


def prepare(worktree: Path, build_root: Path, source_dir: Path | None = None) -> Path:
    """Atomically materialize authoritative patches inside one build lane."""
    worktree = worktree.expanduser().resolve()
    root = generated_root(build_root)
    migrate_pointer = _require_popped_or_unprepared(source_dir, root)
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _authoritative_lock(worktree):
        authoritative = _authoritative_state(worktree)
        staging = Path(tempfile.mkdtemp(prefix=".patch-workspace-", dir=root.parent))
        old_pointer: bytes | None = None
        pointer_path = (
            source_dir.expanduser().resolve() / ".pc" / ".quilt_patches"
            if migrate_pointer and source_dir
            else None
        )
        if pointer_path is not None:
            old_pointer = pointer_path.read_bytes()
        try:
            _write_workspace(staging, authoritative)
            if _authoritative_state(worktree) != authoritative:
                raise PatchWorkspaceError(
                    "authoritative patch catalogs changed during preparation"
                )
            if migrate_pointer:
                assert source_dir is not None
                _migrate_popped_pointer(source_dir.expanduser().resolve(), root)
            _replace_directory(staging, root)
        except Exception:
            rollback_error: OSError | None = None
            if pointer_path is not None and old_pointer is not None:
                try:
                    _replace_bytes(pointer_path, old_pointer, "arcium-rollback")
                except OSError as error:
                    rollback_error = error
            shutil.rmtree(staging, ignore_errors=True)
            if rollback_error is not None:
                raise PatchWorkspaceError(
                    "patch workspace publication failed and the Quilt pointer "
                    "could not be restored"
                ) from rollback_error
            raise
    return root


def _load_manifest(root: Path) -> dict[str, object]:
    try:
        value = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PatchWorkspaceError(
            "generated patch manifest is missing or invalid"
        ) from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PatchWorkspaceError("generated patch manifest has an unsupported schema")
    return value


def validate(worktree: Path, build_root: Path) -> Path:
    """Require a byte-identical generated view of both authoritative catalogs."""
    worktree = worktree.expanduser().resolve()
    root = generated_root(build_root)
    manifest = _load_manifest(root)
    authoritative = _authoritative_state(worktree)
    if manifest != _manifest(authoritative):
        raise PatchWorkspaceError(
            "generated patch workspace is stale; fully pop Quilt and run "
            "he prepare-patches"
        )
    contents = authoritative["contents"]
    assert isinstance(contents, dict)
    for name, content in contents.items():
        generated = _regular_bytes(root / name, f"generated patch {name}")
        if generated != content:
            raise PatchWorkspaceError(
                f"generated patch differs from its authoritative source: {name}; "
                "run he save-patch if this is an intentional refreshed top patch"
            )
    core_series = authoritative["core_series"]
    outer_series = authoritative["outer_series"]
    assert isinstance(core_series, bytes)
    assert isinstance(outer_series, bytes)
    expected_series = {
        "series.prepend": core_series,
        "series.orig": outer_series,
        "series.merged": _with_final_newline(core_series) + outer_series,
    }
    for name, expected_bytes in expected_series.items():
        if _regular_bytes(root / name, f"generated {name}") != expected_bytes:
            raise PatchWorkspaceError(
                f"generated {name} is stale; fully pop Quilt and run "
                "he prepare-patches"
            )
    return root


def _refresh_style(patch: bytes, override: str | None) -> list[str]:
    """Preserve the authoritative patch's existing path/header convention."""
    style = override
    if style is None:
        if patch.startswith(b"Index: src/") or b"\nIndex: src/" in patch:
            style = "p1"
        elif patch.startswith(b"--- a/") or b"\n--- a/" in patch:
            style = "ab"
        else:
            raise PatchWorkspaceError(
                "could not determine patch header style; rerun he save-patch "
                "with --style p1 or --style ab"
            )
    if style == "p1":
        return ["-p", "1"]
    if style == "ab":
        return ["-p", "ab", "--no-index"]
    raise PatchWorkspaceError(f"unsupported patch header style: {style}")


def save_patch(
    worktree: Path,
    build_root: Path,
    source_dir: Path,
    *,
    style: str | None = None,
) -> str:
    """Refresh and export only the active top patch to its authoritative repo."""
    worktree = worktree.expanduser().resolve()
    source_dir = source_dir.expanduser().resolve()
    root = generated_root(build_root)
    manifest = _load_manifest(root)
    try:
        report = inspect_quilt_state(source_dir, root)
        report.comparison.require_valid_prefix()
    except QuiltStateError as error:
        raise PatchWorkspaceError(str(error)) from error
    if not report.comparison.applied:
        raise PatchWorkspaceError("no applied top patch is available to save")
    top = report.comparison.applied[-1]
    owners = manifest.get("owners")
    hashes = manifest.get("hashes")
    if not isinstance(owners, dict) or not isinstance(hashes, dict):
        raise PatchWorkspaceError(
            "generated patch manifest has invalid ownership data"
        )
    owner = owners.get(top)
    baseline = hashes.get(top)
    if owner not in {"core", "outer"} or not isinstance(baseline, str):
        raise PatchWorkspaceError(f"top patch has no authoritative owner: {top}")
    authoritative_root = (
        worktree / "helium-chromium" / "patches"
        if owner == "core"
        else worktree / "patches"
    )
    authoritative_path = authoritative_root / top
    current = _regular_bytes(
        authoritative_path, f"authoritative {owner} patch {top}"
    )
    if _sha256_bytes(current) != baseline:
        raise PatchWorkspaceError(
            f"authoritative patch changed after lane preparation: {top}; "
            "regenerate the lane before saving"
        )

    environment = os.environ.copy()
    environment.update(
        {"QUILT_PATCHES": str(root), "QUILT_SERIES": "series.merged"}
    )
    for inherited_option in (
        "QUILT_DIFF_ARGS",
        "QUILT_NO_DIFF_INDEX",
        "QUILT_REFRESH_ARGS",
    ):
        environment.pop(inherited_option, None)
    with _authoritative_lock(worktree):
        # Re-check immediately before refreshing: another lane may have edited it.
        current = _regular_bytes(authoritative_path, f"authoritative {owner} patch {top}")
        if _sha256_bytes(current) != baseline:
            raise PatchWorkspaceError(f"authoritative patch changed before saving: {top}")
        result = subprocess.run(
            [
                "quilt",
                "--quiltrc",
                "-",
                "refresh",
                "--no-timestamps",
                *_refresh_style(current, style),
            ],
            cwd=source_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stdout + result.stderr).strip()
            raise PatchWorkspaceError(detail or f"quilt refresh failed for {top}")
        refreshed = _regular_bytes(root / top, f"refreshed generated patch {top}")
        previous = current
        after_refresh = _regular_bytes(
            authoritative_path, f"authoritative {owner} patch {top}"
        )
        if _sha256_bytes(after_refresh) != baseline:
            raise PatchWorkspaceError(
                f"authoritative patch changed during save: {top}; generated refresh preserved"
            )
        manifest_path = root / "manifest.json"
        old_manifest = manifest_path.read_bytes()
        hashes[top] = _sha256_bytes(refreshed)
        manifest["hashes"] = hashes
        new_manifest = (
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        authoritative_replaced = False
        manifest_replaced = False
        try:
            _replace_bytes(authoritative_path, refreshed, "arcium-save")
            authoritative_replaced = True
            _replace_bytes(manifest_path, new_manifest, "arcium-save")
            manifest_replaced = True
        except (OSError, UnicodeError) as error:
            rollback_errors: list[OSError] = []
            if authoritative_replaced:
                try:
                    _replace_bytes(authoritative_path, previous, "arcium-rollback")
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            if manifest_replaced:
                try:
                    _replace_bytes(manifest_path, old_manifest, "arcium-rollback")
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise PatchWorkspaceError(
                    f"could not save or fully restore authoritative patch: {top}"
                ) from rollback_errors[0]
            raise PatchWorkspaceError(f"could not save authoritative patch: {top}") from error
    return top


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--style", choices=("p1", "ab"))
    parser.add_argument("action", choices=("prepare", "validate", "save"))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.action == "prepare":
            root = prepare(
                arguments.worktree, arguments.build_root, arguments.source
            )
            print(f"generated patch workspace prepared: {root}")
        elif arguments.action == "validate":
            root = validate(arguments.worktree, arguments.build_root)
            print(f"generated patch workspace current: {root}")
        else:
            if arguments.source is None:
                raise PatchWorkspaceError("save requires --source")
            saved = save_patch(
                arguments.worktree,
                arguments.build_root,
                arguments.source,
                style=arguments.style,
            )
            print(f"saved authoritative patch: {saved}")
    except (OSError, PatchWorkspaceError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
