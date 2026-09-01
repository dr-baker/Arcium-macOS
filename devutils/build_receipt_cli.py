#!/usr/bin/env python3
"""Publish source and packaged-build receipts for one selected lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from build_receipt import (
    BuildReceipt,
    ReceiptError,
    SourceReceipt,
    current_source_receipt,
    material_inputs_sha256,
    sha256_file,
    write_receipt_atomic,
)
from build_execution import ExecutionError, require_current_execution, tree_sha256
from helium_dev_bundle import DevBundleIdentity, resolve_dev_identity
from quilt_state import QuiltStateError
from replay_contract import ReplayError, require_current_replay_proof


def _source_receipt(worktree: Path, source_dir: Path) -> tuple[SourceReceipt, str]:
    return current_source_receipt(worktree, source_dir, require_complete=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--lane", choices=("local", "heavy", "worktree"), required=True)
    parser.add_argument("action", choices=("source", "packaged-check"))
    return parser


def _current_packaged_receipt(
    worktree: Path,
    build_root: Path,
    lane: str,
    identity: DevBundleIdentity | None = None,
) -> BuildReceipt:
    selected_identity = resolve_dev_identity() if identity is None else identity
    source_dir = build_root / "src"
    source, applied_sha256 = _source_receipt(worktree, source_dir)
    replay = require_current_replay_proof(worktree, source_dir)
    execution = require_current_execution(worktree, build_root, lane=lane)
    out_dir = source_dir / "out" / "Default"
    app = out_dir / selected_identity.app_name
    artifacts = {
        selected_identity.app_name: tree_sha256(app),
        f"{selected_identity.app_name}/Contents/MacOS/Helium": sha256_file(
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
        material_inputs_sha256=material_inputs_sha256(worktree),
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
    identity: DevBundleIdentity | None = None,
) -> BuildReceipt:
    """Publish only from the lane-locked package transaction."""
    selected_identity = resolve_dev_identity() if identity is None else identity
    receipt = _current_packaged_receipt(
        worktree, build_root, lane, selected_identity
    )
    if receipt.artifacts.get(selected_identity.app_name) != expected_package_sha256:
        raise ReceiptError("packaged bundle changed before receipt publication")
    write_receipt_atomic(
        build_root / ".arcium" / "receipts" / selected_identity.receipt_name,
        receipt,
    )
    return receipt


def require_current_packaged_build(
    worktree: Path,
    build_root: Path,
    lane: str,
    identity: DevBundleIdentity | None = None,
) -> BuildReceipt:
    selected_identity = resolve_dev_identity() if identity is None else identity
    path = build_root / ".arcium" / "receipts" / selected_identity.receipt_name
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReceiptError("no current packaged build proof; run he dev-bundle") from error
    current = _current_packaged_receipt(
        worktree, build_root, lane, selected_identity
    )
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
