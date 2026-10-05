#!/usr/bin/env python3
"""Persist repository-local lane choice and resolve shell overrides read-only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

LANES = ("local", "heavy", "worktree")
DEFAULT_UUID = "75279EDB-CF1D-4EBF-8C7C-FD7249DCBCAF"


class SelectionError(RuntimeError):
    pass


def selection_path(worktree: Path) -> Path:
    result = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, timeout=10)
    if result.returncode or not result.stdout.strip():
        raise SelectionError("could not locate repository-local lane configuration")
    return Path(result.stdout.strip()) / "arcium" / "lane-selection.json"


def validate(document: object) -> dict:
    if not isinstance(document, dict) or document.get("version") != 1 or set(document) - {"version", "lane", "root", "source_mode", "volume_uuid"}:
        raise SelectionError("invalid saved lane selection")
    if document.get("lane") not in LANES:
        raise SelectionError("lane must be local, heavy, or worktree")
    root = document.get("root")
    if root is not None and (not isinstance(root, str) or not Path(root).is_absolute() or any(ord(c) < 32 for c in root)):
        raise SelectionError("lane root must be an absolute path without control characters")
    if document.get("source_mode") not in (None, "lite", "full"):
        raise SelectionError("source mode must be lite or full")
    uuid = document.get("volume_uuid")
    if uuid is not None and (not isinstance(uuid, str) or not re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", uuid)):
        raise SelectionError("volume UUID must be a UUID")
    if document["lane"] != "heavy" and uuid:
        raise SelectionError("volume UUID applies only to a heavy lane")
    if document["lane"] == "heavy" and root and not uuid:
        raise SelectionError("a custom heavy root requires --expected-volume-uuid")
    return document


def load(worktree: Path) -> dict | None:
    path = selection_path(worktree)
    try:
        return validate(json.loads(path.read_text()))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise SelectionError(f"could not read saved lane selection: {path}") from error


def save(worktree: Path, document: dict) -> None:
    document = validate(document)
    path = selection_path(worktree)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="lane-selection-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(document, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def resolve(worktree: Path, env: dict[str, str]) -> dict:
    saved = load(worktree)
    common = selection_path(worktree).parent.parent
    canonical = common.parent
    local = canonical / "build"
    heavy = Path(env.get("HELIUM_DEV_HEAVY_ROOT") or "/Volumes/T9/ArciumBuild/build")
    explicit_lane = env.get("HELIUM_DEV_LANE")
    explicit_root = env.get("HELIUM_DEV_BUILD_ROOT")
    if explicit_root and not explicit_lane:
        raise SelectionError("HELIUM_DEV_BUILD_ROOT requires an explicit HELIUM_DEV_LANE")
    if explicit_lane:
        selected = {"lane": explicit_lane, "root": explicit_root}
        origin = "environment"
    elif saved:
        selected = saved
        origin = "saved"
    else:
        selected = {"lane": "heavy" if (heavy / "src/out/Default/build.ninja").is_file() else "local"}
        origin = "automatic"
    lane = selected["lane"]
    if lane not in LANES:
        raise SelectionError("HELIUM_DEV_LANE must be local, heavy, or worktree")
    defaults = {"heavy": heavy, "local": local, "worktree": worktree / "build"}
    root = Path(selected.get("root") or defaults[lane]).expanduser().absolute()
    mode = env.get("HELIUM_DEV_SOURCE_MODE") or selected.get("source_mode")
    if not mode:
        try:
            mode = (root / ".arcium/source-mode").read_text().splitlines()[0]
        except (OSError, IndexError):
            mode = "lite"
    if mode not in ("lite", "full"):
        raise SelectionError("HELIUM_DEV_SOURCE_MODE must be lite or full")
    uuid = env.get("HELIUM_DEV_HEAVY_VOLUME_UUID") or selected.get("volume_uuid") or DEFAULT_UUID
    managed = " ".join(key for key in ("LANE", "BUILD_ROOT", "SOURCE_MODE", "HEAVY_VOLUME_UUID") if not env.get("HELIUM_DEV_" + key))
    return {"managed": managed, "lane": lane, "root": str(root), "source_mode": mode, "volume_uuid": uuid, "origin": origin, "config_path": str(selection_path(worktree)), "saved": saved}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--shell", action="store_true")
    commands.add_parser("show")
    commands.add_parser("clear")
    select = commands.add_parser("select")
    select.add_argument("lane", choices=LANES)
    select.add_argument("--root", type=Path)
    select.add_argument("--source-mode", choices=("lite", "full"))
    select.add_argument("--expected-volume-uuid")
    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            save(args.worktree, {"version": 1, "lane": args.lane, "root": str(args.root.expanduser()) if args.root else None, "source_mode": args.source_mode, "volume_uuid": args.expected_volume_uuid})
            return 0
        if args.command == "clear":
            selection_path(args.worktree).unlink(missing_ok=True)
            return 0
        document = resolve(args.worktree, dict(os.environ))
        if args.command == "resolve" and args.shell:
            for variable, key in (("_dev_lane", "lane"), ("_build_dir", "root"), ("_source_mode", "source_mode"), ("_heavy_volume_uuid", "volume_uuid"), ("_lane_selection_origin", "origin"), ("_lane_selection_config", "config_path"), ("_lane_selection_managed", "managed")):
                print(f"{variable}={shlex.quote(document[key])}")
        else:
            print(json.dumps(document, sort_keys=True))
        return 0
    except (SelectionError, OSError, subprocess.TimeoutExpired) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
