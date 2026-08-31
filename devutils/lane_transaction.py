#!/usr/bin/env python3
"""Run one complete shell workflow while holding its generated-lane lock."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from build_lane import LaneError, LaneSpec, acquire_lane_lock, inspect_lane


_FUNCTIONS = {
    "arcium": "___helium_arcium_inner",
    "bootstrap": "___helium_bootstrap_inner",
    "configure": "___helium_configure_inner",
    "dev": "___helium_dev_inner",
    "format": "___helium_format_inner",
    "lint": "___helium_lint_inner",
    "merge": "___helium_prepare_patches_inner",
    "name-substitution": "___helium_name_substitution_inner",
    "pop": "___helium_quilt_pop_inner",
    "presetup": "___helium_setup_presetup_inner",
    "prepare-patches": "___helium_prepare_patches_inner",
    "pull": "___helium_pull_inner",
    "push": "___helium_quilt_push_inner",
    "reset": "___helium_reset_inner",
    "resources": "___helium_resources_inner",
    "sync-patches": "___helium_sync_patches_inner",
    "setup": "___helium_setup_inner",
    "save-patch": "___helium_save_patch_inner",
    "substitution": "___helium_substitution_inner",
    "tidy": "___helium_tidy_inner",
    "translate": "___helium_apply_translations_inner",
    "transgen": "___helium_generate_translations_inner",
    "unmerge": "___helium_patches_unmerge_inner",
}


def workflow_environment(
    current: dict[str, str],
    *,
    build_root: Path,
    lane: str,
    worktree: Path,
) -> dict[str, str]:
    """Bind child tools and temporary traffic to the selected lane."""

    environment = dict(current)
    environment.update(
        {
            "HELIUM_DEV_BUILD_ROOT": str(build_root),
            "HELIUM_DEV_LANE": lane,
            "HELIUM_DEV_WORKTREE": str(worktree),
        }
    )
    if lane == "heavy":
        environment["TMPDIR"] = str(build_root / ".arcium" / "tmp")
    return environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--lane", choices=("local", "heavy", "worktree"), required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--expected-volume-uuid")
    parser.add_argument("action", choices=tuple(_FUNCTIONS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    worktree = arguments.worktree.expanduser().resolve()
    build_root = arguments.build_root.expanduser().resolve()
    script = arguments.script.expanduser().resolve()
    if not script.is_file():
        print(f"development shell is missing: {script}", file=sys.stderr)
        return 2
    workflow_arguments = list(arguments.arguments)
    if workflow_arguments[:1] == ["--"]:
        workflow_arguments.pop(0)
    lock_path = build_root / ".arcium" / "lane.lock"
    heavy = arguments.lane == "heavy"
    spec = LaneSpec(
        name=arguments.lane,
        root=build_root,
        minimum_free_bytes=0,
        expected_volume_uuid=arguments.expected_volume_uuid if heavy else None,
        require_external=heavy,
        require_case_sensitive_apfs=heavy,
        warn_if_unencrypted=heavy,
        warn_if_ownership_disabled=heavy,
    )
    owner = {
        "action": arguments.action,
        "lane": arguments.lane,
        "worktree": str(worktree),
    }
    environment = workflow_environment(
        os.environ,
        build_root=build_root,
        lane=arguments.lane,
        worktree=worktree,
    )
    try:
        inspect_lane(spec).require_ok()
        with acquire_lane_lock(lock_path, owner) as descriptor:
            inspect_lane(spec).require_ok()
            if heavy:
                temporary_root = build_root / ".arcium" / "tmp"
                temporary_root.mkdir(parents=True, exist_ok=True)
            environment["HELIUM_DEV_LANE_LOCK_FD"] = str(descriptor)
            completed = subprocess.run(
                [
                    "zsh",
                    "-c",
                    'source "$1"; shift; "$@"',
                    "arcium-lane",
                    str(script),
                    _FUNCTIONS[arguments.action],
                    *workflow_arguments,
                ],
                check=False,
                env=environment,
                pass_fds=(descriptor,),
            )
    except (LaneError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
