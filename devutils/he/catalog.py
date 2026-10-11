"""The lane copy of the merged patch catalog.

Upstream's `he merge` copies core patches into the outer `patches/` directory
in git. Here the merged view lives in `<build dir>/.arcium/patches`, so one
build dir can serve any source worktree and nothing generated lands in git.
The layout and `manifest.json` (schema 1) match the previous tooling, so
existing build dirs keep working.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterator

from . import quilt, records
from .common import HeError, Paths, read_json, sha256_bytes, write_atomic, write_json

MANIFEST = "manifest.json"


@contextmanager
def authoritative_lock(paths: Paths) -> Iterator[None]:
    """Serialize writes to authoritative catalogs across every build dir."""
    result = subprocess.run(
        ["git", "-C", str(paths.worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise HeError(f"{paths.worktree} is not a git checkout")
    # Same file name as the previous tooling, so old and new exclude each other.
    lock = Path(result.stdout.strip()) / "arcium-authoritative.lock"
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _authoritative(paths: Paths) -> dict:
    core_series = (paths.core_patches / "series").read_bytes()
    outer_series = (paths.outer_patches / "series").read_bytes()
    core = quilt.read_list(paths.core_patches / "series")
    outer = quilt.read_list(paths.outer_patches / "series")
    overlap = sorted(set(core) & set(outer))
    if overlap:
        raise HeError("core and macOS patch catalogs both list: " + ", ".join(overlap))
    contents, owners = {}, {}
    for owner, root, names in (("core", paths.core_patches, core), ("outer", paths.outer_patches, outer)):
        for name in names:
            path = root / name
            if not path.is_file() or path.is_symlink():
                raise HeError(f"{owner} series lists a missing patch: {name}")
            contents[name] = path.read_bytes()
            owners[name] = owner
    return {"core": core, "outer": outer, "core_series": core_series,
            "outer_series": outer_series, "contents": contents, "owners": owners}


def _merged_series(core_series: bytes, outer_series: bytes) -> bytes:
    if core_series and not core_series.endswith(b"\n"):
        core_series += b"\n"
    return core_series + outer_series


def manifest(paths: Paths) -> dict:
    value = read_json(paths.catalog / MANIFEST)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise HeError(f"no patch catalog in {paths.build_dir}; run he merge")
    return value


def owner_path(paths: Paths, owner: str, name: str) -> Path:
    return (paths.core_patches if owner == "core" else paths.outer_patches) / name


def require_popped(paths: Paths, action: str) -> None:
    if quilt.applied(paths.src):
        raise HeError(f"{action} needs a fully popped stack; run he pop first")


def merge(paths: Paths) -> None:
    """Copy both authoritative catalogs into the build dir."""
    require_popped(paths, "he merge")
    paths.state.mkdir(parents=True, exist_ok=True)
    with authoritative_lock(paths):
        state = _authoritative(paths)
        staging = Path(tempfile.mkdtemp(prefix=".patches-", dir=paths.state))
        try:
            for name, content in state["contents"].items():
                (staging / name).parent.mkdir(parents=True, exist_ok=True)
                (staging / name).write_bytes(content)
            (staging / "series.prepend").write_bytes(state["core_series"])
            (staging / "series.orig").write_bytes(state["outer_series"])
            (staging / "series.merged").write_bytes(_merged_series(state["core_series"], state["outer_series"]))
            write_json(staging / MANIFEST, {
                "schema_version": 1,
                "core": list(state["core"]),
                "outer": list(state["outer"]),
                "owners": state["owners"],
                "hashes": {name: sha256_bytes(data) for name, data in state["contents"].items()},
                "core_series_sha256": sha256_bytes(state["core_series"]),
                "outer_series_sha256": sha256_bytes(state["outer_series"]),
            })
            old = None
            if paths.catalog.exists():
                old = paths.catalog.with_name(f".patches-old-{os.getpid()}")
                os.replace(paths.catalog, old)
            os.replace(staging, paths.catalog)
            if old is not None:
                shutil.rmtree(old, ignore_errors=True)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    # A fully popped tree may still point at an older catalog location.
    pc_pointer = paths.src / ".pc" / ".quilt_patches"
    if pc_pointer.exists() and quilt.pointer(paths.src) != paths.catalog:
        write_atomic(pc_pointer, f"{paths.catalog}\n".encode())
    records.clear_applied(paths)


def drift(paths: Paths) -> list[str]:
    """How the lane copy differs from the selected worktree's catalogs."""
    current = manifest(paths)
    problems = []
    try:
        state = _authoritative(paths)
    except (OSError, HeError) as error:
        return [f"cannot read authoritative catalogs: {error}"]
    if sha256_bytes(state["core_series"]) != current.get("core_series_sha256") or \
            sha256_bytes(state["outer_series"]) != current.get("outer_series_sha256"):
        problems.append("series order or membership changed in the worktree")
    hashes = current.get("hashes", {})
    for name, content in state["contents"].items():
        if name in hashes and hashes[name] != sha256_bytes(content):
            problems.append(f"{name} changed in the worktree")
    return problems


def _style(patch: bytes, override: str | None) -> list[str]:
    """Keep the authoritative patch's header convention when refreshing."""
    style = override
    if style is None:
        if patch.startswith(b"Index: src/") or b"\nIndex: src/" in patch:
            style = "p1"
        elif patch.startswith(b"--- a/") or b"\n--- a/" in patch:
            style = "ab"
        else:
            raise HeError("could not tell this patch's header style; pass --style p1 or --style ab")
    return ["-p", "1"] if style == "p1" else ["-p", "ab", "--no-index"]


def _export(paths: Paths, current: dict, name: str, content: bytes) -> None:
    """Write one lane patch back to its owner, refusing concurrent edits."""
    owner = current["owners"].get(name)
    if owner not in ("core", "outer"):
        raise HeError(f"{name} has no authoritative owner")
    target = owner_path(paths, owner, name)
    baseline = current["hashes"].get(name)
    if not target.is_file() or sha256_bytes(target.read_bytes()) != baseline:
        raise HeError(f"{target} changed since he merge; reconcile it, then he pop; he merge; he push")
    write_atomic(target, content)
    current["hashes"][name] = sha256_bytes(content)


def save_patch(paths: Paths, style: str | None = None) -> str:
    """Refresh the top patch and write it back to its owning repository."""
    current = manifest(paths)
    applied = quilt.applied(paths.src)
    if not applied:
        raise HeError("no patch is applied")
    top = applied[-1]
    owner = current["owners"].get(top)
    if owner is None:
        raise HeError(f"{top} is not in the merged catalog; create new patches in the authoritative series")
    with authoritative_lock(paths):
        target = owner_path(paths, owner, top)
        if sha256_bytes(target.read_bytes()) != current["hashes"].get(top):
            raise HeError(f"{target} changed since he merge; reconcile it before saving")
        environment = {k: v for k, v in os.environ.items()
                       if k not in ("QUILT_DIFF_ARGS", "QUILT_REFRESH_ARGS", "QUILT_NO_DIFF_INDEX")}
        environment.update(QUILT_PATCHES=str(paths.catalog), QUILT_SERIES="series.merged")
        result = subprocess.run(
            ["quilt", "--quiltrc", "-", "refresh", "--no-timestamps", *_style(target.read_bytes(), style)],
            cwd=paths.src, env=environment, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise HeError((result.stdout + result.stderr).strip() or f"quilt refresh failed for {top}")
        _export(paths, current, top, (paths.catalog / top).read_bytes())
        write_json(paths.catalog / MANIFEST, current)
    records.sync_applied(paths, rebaseline=(top,))
    return top


def unmerge(paths: Paths) -> list[str]:
    """Upstream's unmerge: write lane edits back, then drop the merged view.

    Refreshed patches go back to their owners. Patches added to series.merged
    with `quilt new` go to the macOS catalog, after the nearest preceding
    macOS patch. While patches are applied the catalog stays in place.
    """
    current = manifest(paths)
    merged = quilt.read_list(paths.catalog / "series.merged")
    known = set(current["owners"])
    removed = sorted(known - set(merged))
    if removed:
        raise HeError("series.merged dropped patches; remove them from their owning series by hand: " + ", ".join(removed))
    written = []
    with authoritative_lock(paths):
        for name in merged:
            if name not in known:
                continue
            content = (paths.catalog / name).read_bytes()
            if sha256_bytes(content) != current["hashes"][name]:
                _export(paths, current, name, content)
                written.append(name)
        new = [name for name in merged if name not in known]
        if new:
            outer_series = paths.outer_patches / "series"
            lines = outer_series.read_text(encoding="utf-8").splitlines()
            for name in new:
                target = paths.outer_patches / name
                content = (paths.catalog / name).read_bytes()
                if target.exists() and target.read_bytes() != content:
                    raise HeError(f"{target} already exists with other content")
                write_atomic(target, content)
                previous = [n for n in merged[: merged.index(name)] if current["owners"].get(n) == "outer" or n in new]
                anchor = previous[-1] if previous else None
                index = 0
                if anchor is not None:
                    index = next(i for i, line in enumerate(lines) if quilt.read_list_line(line) == anchor) + 1
                lines.insert(index, name)
                current["owners"][name] = "outer"
                current["hashes"][name] = sha256_bytes(content)
                current["outer"] = [n for n in merged if current["owners"].get(n) == "outer"]
                written.append(name)
            outer_bytes = ("\n".join(lines) + "\n").encode()
            write_atomic(outer_series, outer_bytes)
            current["outer_series_sha256"] = sha256_bytes(outer_bytes)
        write_json(paths.catalog / MANIFEST, current)
    if not quilt.applied(paths.src):
        shutil.rmtree(paths.catalog)
        records.clear_applied(paths)
    return written
