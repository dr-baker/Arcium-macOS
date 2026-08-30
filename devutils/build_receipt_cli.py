#!/usr/bin/env python3
"""Publish source and packaged-build receipts for one selected lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_receipt import (
    BuildReceipt,
    ReceiptError,
    SourceReceipt,
    require_expected_chromium_version,
    sha256_file,
    write_receipt_atomic,
)
from build_execution import ExecutionError, require_current_execution, tree_sha256
from quilt_state import QuiltStateError, inspect_quilt_state
from replay_contract import ReplayError, require_current_replay_proof


def _git(repo: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceiptError(f"could not inspect Git state in {repo}") from error
    return result.stdout.strip()


def _source_receipt(worktree: Path, source_dir: Path) -> tuple[SourceReceipt, str]:
    outer = _git(worktree, "rev-parse", "HEAD")
    core_dir = worktree / "helium-chromium"
    core = _git(core_dir, "rev-parse", "HEAD")
    fields = _git(worktree, "ls-tree", "HEAD", "helium-chromium").split()
    if len(fields) < 3 or fields[1] != "commit":
        raise ReceiptError("outer repository has no helium-chromium gitlink")
    gitlink = fields[2]
    report = inspect_quilt_state(source_dir, worktree / "patches")
    report.comparison.require_complete()
    return (
        SourceReceipt.create(
            outer_commit=outer,
            core_commit=core,
            gitlink_commit=gitlink,
            chromium_version=require_expected_chromium_version(core_dir, source_dir),
            patch_series_sha256=report.declared_sha256,
        ),
        report.applied_sha256,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--lane", choices=("local", "heavy", "worktree"), required=True)
    parser.add_argument("action", choices=("source", "packaged-check"))
    return parser


def _current_packaged_receipt(
    worktree: Path, build_root: Path, lane: str
) -> BuildReceipt:
    source_dir = build_root / "src"
    source, applied_sha256 = _source_receipt(worktree, source_dir)
    replay = require_current_replay_proof(worktree, source_dir)
    execution = require_current_execution(worktree, build_root, lane=lane)
    out_dir = source_dir / "out" / "Default"
    app = out_dir / "Helium Dev.app"
    artifacts = {
        "Helium Dev.app": tree_sha256(app),
        "Helium Dev.app/Contents/MacOS/Helium": sha256_file(
            app / "Contents" / "MacOS" / "Helium"
        ),
        "libchrome_dll.dylib": sha256_file(out_dir / "libchrome_dll.dylib"),
    }
    gates = ["series-verified", "replayed", "configured", "compiled"]
    if execution.action == "relink-resources":
        gates.append("resource-relinked")
    gates.append("packaged")
    return BuildReceipt.create(
        source=source,
        replay_receipt_id=replay.receipt_id,
        execution_receipt_id=execution.receipt_id,
        lane=lane,
        status="complete",
        gn_args_sha256=sha256_file(out_dir / "args.gn"),
        applied_series_sha256=applied_sha256,
        targets=execution.targets,
        proof_gates=gates,
        artifacts=artifacts,
    )


def _publish_packaged_build(
    worktree: Path,
    build_root: Path,
    lane: str,
    *,
    expected_package_sha256: str,
) -> BuildReceipt:
    """Publish only from the lane-locked package transaction."""
    receipt = _current_packaged_receipt(worktree, build_root, lane)
    if receipt.artifacts.get("Helium Dev.app") != expected_package_sha256:
        raise ReceiptError("packaged bundle changed before receipt publication")
    write_receipt_atomic(
        build_root / ".arcium" / "receipts" / "build.json", receipt
    )
    return receipt


def require_current_packaged_build(
    worktree: Path, build_root: Path, lane: str
) -> BuildReceipt:
    path = build_root / ".arcium" / "receipts" / "build.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReceiptError("no current packaged build proof; run he dev-bundle") from error
    current = _current_packaged_receipt(worktree, build_root, lane)
    if stored != current.to_dict():
        raise ReceiptError("packaged build proof is stale; run he dev-bundle")
    return current


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    worktree = arguments.worktree.expanduser().resolve()
    build_root = arguments.build_root.expanduser().resolve()
    source_dir = build_root / "src"
    receipt_dir = build_root / ".arcium" / "receipts"
    try:
        source, applied_sha256 = _source_receipt(worktree, source_dir)
        write_receipt_atomic(receipt_dir / "source.json", source)
        if arguments.action == "source":
            print(f"source receipt: {source.receipt_id}")
            return 0

        if arguments.action == "packaged-check":
            receipt = require_current_packaged_build(
                worktree, build_root, arguments.lane
            )
            print(f"build receipt: {receipt.receipt_id}")
            return 0
        raise ReceiptError("packaged build receipts are published by he dev-bundle")
    except (
        OSError,
        ExecutionError,
        QuiltStateError,
        ReplayError,
        ReceiptError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
