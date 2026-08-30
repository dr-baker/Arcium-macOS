#!/usr/bin/env python3
"""Publish source and packaged-build receipts for one selected lane."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from build_receipt import (
    BuildReceipt,
    ReceiptError,
    SourceReceipt,
    sha256_file,
    write_receipt_atomic,
)
from quilt_state import QuiltStateError, inspect_quilt_state


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
            patch_series_sha256=report.declared_sha256,
        ),
        report.applied_sha256,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--lane", choices=("local", "heavy", "worktree"), required=True)
    parser.add_argument("action", choices=("source", "packaged-build"))
    return parser


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

        out_dir = source_dir / "out" / "Default"
        args_path = out_dir / "args.gn"
        component = out_dir / "libchrome_dll.dylib"
        executable = out_dir / "Helium Dev.app" / "Contents" / "MacOS" / "Helium"
        artifacts = {
            "libchrome_dll.dylib": sha256_file(component),
            "Helium Dev.app/Contents/MacOS/Helium": sha256_file(executable),
        }
        receipt = BuildReceipt.create(
            source=source,
            lane=arguments.lane,
            status="complete",
            gn_args_sha256=sha256_file(args_path),
            applied_series_sha256=applied_sha256,
            targets=("chrome_app",),
            proof_gates=(
                "series-verified",
                "replayed",
                "configured",
                "compiled",
                "resource-relinked",
                "packaged",
            ),
            artifacts=artifacts,
        )
        write_receipt_atomic(receipt_dir / "build.json", receipt)
        print(f"build receipt: {receipt.receipt_id}")
        return 0
    except (OSError, QuiltStateError, ReceiptError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
