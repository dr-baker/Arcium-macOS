#!/usr/bin/env python3
"""Run one complete shell workflow while holding its generated-lane lock."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from build_lane import LaneError, LaneSpec, acquire_lane_lock, heavy_lane_temp, inspect_lane


from build_execution import ExecutionError, material_guard


from build_receipt import (
    HARNESS_SCRIPT_ENV,
    HARNESS_SHA256_ENV,
    ACQUISITION_SCRIPT_ENV,
    ACQUISITION_SHA256_ENV,
    PYTHON_SETUP_SCRIPT_ENV,
    PYTHON_SETUP_SHA256_ENV,
    MATERIAL_INPUTS_ENV,
    ReceiptError,
    material_inputs_at_entry,
)


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
    "version": "___helium_version_inner",
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
    build_root = arguments.build_root.expanduser().absolute()
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
    # The child sources this exact shell; its helper modules remain those of
    # the executing lane_transaction.py checkout.
    previous_script = os.environ.get(HARNESS_SCRIPT_ENV)
    previous_digest = os.environ.get(HARNESS_SHA256_ENV)
    previous_sourced_helpers = {key: os.environ.get(key) for key in (ACQUISITION_SCRIPT_ENV, ACQUISITION_SHA256_ENV, PYTHON_SETUP_SCRIPT_ENV, PYTHON_SETUP_SHA256_ENV)}
    prior_path = Path(previous_script or Path(__file__).resolve().parents[1] / "dev.sh")
    if prior_path.expanduser().resolve() != script:
        # A custom --script will be freshly sourced in the child. Keep the
        # existing sourced-definition evidence when it is the same script.
        os.environ.pop(HARNESS_SHA256_ENV, None)
        environment.pop(HARNESS_SHA256_ENV, None)
        for key in previous_sourced_helpers:
            os.environ.pop(key, None)
            environment.pop(key, None)
    os.environ[HARNESS_SCRIPT_ENV] = str(script)
    environment[HARNESS_SCRIPT_ENV] = str(script)
    try:
        material_at_entry = material_inputs_at_entry(worktree)
        inspect_lane(spec).require_ok()
        if heavy:
            heavy_lane_temp(spec)  # Pure validation before creating the lock path.
        with acquire_lane_lock(lock_path, owner) as descriptor, material_guard(
            worktree, build_root, expected=material_at_entry
        ):
            inspect_lane(spec).require_ok()
            if heavy:
                environment["TMPDIR"] = str(heavy_lane_temp(spec, create=True))
                environment["HELIUM_DEV_HEAVY_VOLUME_UUID"] = spec.expected_volume_uuid
            environment["HELIUM_DEV_LANE_LOCK_FD"] = str(descriptor)
            environment[MATERIAL_INPUTS_ENV] = material_at_entry
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
    except (LaneError, ExecutionError, ReceiptError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        for key, previous in previous_sourced_helpers.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        if previous_digest is None:
            os.environ.pop(HARNESS_SHA256_ENV, None)
        else:
            os.environ[HARNESS_SHA256_ENV] = previous_digest
        if previous_script is None:
            os.environ.pop(HARNESS_SCRIPT_ENV, None)
        else:
            os.environ[HARNESS_SCRIPT_ENV] = previous_script
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
