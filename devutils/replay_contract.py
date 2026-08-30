#!/usr/bin/env python3
"""Establish and validate the expensive, explicit Quilt replay proof.

``he check`` is deliberately a fast provenance check.  This module owns the
stronger contract required before compiling or packaging: the selected source
must have been popped and strictly replayed from the declared series, and the
proof must still describe the current outer/core commits and patch bytes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from build_receipt import (
    RECEIPT_SCHEMA,
    ReceiptError,
    SourceReceipt,
    require_expected_chromium_version,
    write_receipt_atomic,
)
from quilt_state import QuiltStateError, inspect_quilt_state


class ReplayError(RuntimeError):
    """The replay proof is missing, stale, or could not be established."""


@dataclass(frozen=True)
class ReplayReceipt:
    source: SourceReceipt
    applied_series_sha256: str
    patched_tree_sha256: str
    series_name: str
    receipt_id: str

    @classmethod
    def create(
        cls,
        *,
        source: SourceReceipt,
        applied_series_sha256: str,
        patched_tree_sha256: str,
        series_name: str,
    ) -> "ReplayReceipt":
        if len(applied_series_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in applied_series_sha256
        ):
            raise ReceiptError("applied_series_sha256 must be a SHA-256 digest")
        if len(patched_tree_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in patched_tree_sha256
        ):
            raise ReceiptError("patched_tree_sha256 must be a SHA-256 digest")
        if not series_name or "/" in series_name or "\\" in series_name:
            raise ReceiptError("series_name must be a simple Quilt series filename")
        payload = {
            "schema": RECEIPT_SCHEMA,
            "source_receipt_id": source.receipt_id,
            "applied_series_sha256": applied_series_sha256,
            "patched_tree_sha256": patched_tree_sha256,
            "series_name": series_name,
        }
        receipt_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            source=source,
            applied_series_sha256=applied_series_sha256,
            patched_tree_sha256=patched_tree_sha256,
            series_name=series_name,
            receipt_id=receipt_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "source": self.source.to_dict(),
            "applied_series_sha256": self.applied_series_sha256,
            "patched_tree_sha256": self.patched_tree_sha256,
            "series_name": self.series_name,
        }


def receipt_path(build_root: Path) -> Path:
    return build_root.resolve() / ".arcium" / "receipts" / "replay.json"


def invalidate_downstream_receipts(build_root: Path) -> None:
    """Remove proof that cannot survive a new replay attempt."""
    receipt_dir = build_root.resolve() / ".arcium" / "receipts"
    for name in ("replay.json", "execution.json", "build.json"):
        try:
            (receipt_dir / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ReplayError(f"could not invalidate stale receipt: {name}") from error


def _git(repo: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReplayError(f"could not inspect Git state in {repo}") from error
    return result.stdout.strip()


def current_source_identity(worktree: Path, source_dir: Path) -> SourceReceipt:
    """Compute source inputs without trusting Quilt's applied ledger."""
    outer = _git(worktree, "rev-parse", "HEAD")
    core_dir = worktree / "helium-chromium"
    core = _git(core_dir, "rev-parse", "HEAD")
    fields = _git(worktree, "ls-tree", "HEAD", "helium-chromium").split()
    if len(fields) < 3 or fields[1] != "commit":
        raise ReplayError("outer repository has no helium-chromium gitlink")
    gitlink = fields[2]
    report = inspect_quilt_state(source_dir, worktree / "patches")
    report.comparison.require_valid_prefix()
    return SourceReceipt.create(
        outer_commit=outer,
        core_commit=core,
        gitlink_commit=gitlink,
        chromium_version=require_expected_chromium_version(core_dir, source_dir),
        patch_series_sha256=report.declared_sha256,
    )


def current_source_receipt(worktree: Path, source_dir: Path) -> tuple[SourceReceipt, str]:
    """Compute current complete source identity and applied-series digest."""
    source = current_source_identity(worktree, source_dir)
    report = inspect_quilt_state(source_dir, worktree / "patches")
    report.comparison.require_complete()
    return source, report.applied_sha256


def _patched_tree_sha256(worktree: Path, source_dir: Path) -> str:
    """Hash every path owned by the complete applied Quilt stack."""
    result = subprocess.run(
        ["quilt", "--quiltrc", "-", "files", "-a"],
        cwd=source_dir,
        env=_quilt_environment(worktree),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ReplayError("could not enumerate patch-owned source paths")
    paths = sorted(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))
    digest = hashlib.sha256()
    root = source_dir.resolve()
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ReplayError(f"unsafe patch-owned source path: {relative}")
        path = root / candidate
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            kind = b"missing"
            mode = 0
            content = b""
        except OSError as error:
            raise ReplayError(f"could not inspect patch-owned path: {relative}") from error
        else:
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISREG(metadata.st_mode):
                kind = b"file"
                try:
                    content = path.read_bytes()
                except OSError as error:
                    raise ReplayError(
                        f"could not read patch-owned path: {relative}"
                    ) from error
            elif stat.S_ISLNK(metadata.st_mode):
                kind = b"symlink"
                try:
                    content = os.readlink(path).encode("utf-8", errors="surrogateescape")
                except OSError as error:
                    raise ReplayError(
                        f"could not read patch-owned symlink: {relative}"
                    ) from error
            else:
                raise ReplayError(f"unsupported patch-owned path type: {relative}")
        name = relative.encode("utf-8", errors="surrogateescape")
        for field in (name, kind, str(mode).encode("ascii"), content):
            digest.update(str(len(field)).encode("ascii"))
            digest.update(b":")
            digest.update(field)
            digest.update(b"\n")
    return digest.hexdigest()


def _read_receipt(path: Path) -> ReplayReceipt:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayError(f"could not read replay proof: {path}") from error
    if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
        raise ReplayError("replay proof is from an unsupported schema; run he replay")
    try:
        source_value = value["source"]
        if not isinstance(source_value, dict) or source_value.get("schema") != RECEIPT_SCHEMA:
            raise ReplayError("replay proof contains an unsupported source schema")
        source = SourceReceipt.create(
            outer_commit=str(source_value["outer_commit"]),
            core_commit=str(source_value["core_commit"]),
            gitlink_commit=str(source_value["gitlink_commit"]),
            chromium_version=str(source_value["chromium_version"]),
            patch_series_sha256=str(source_value["patch_series_sha256"]),
        )
        receipt = ReplayReceipt.create(
            source=source,
            applied_series_sha256=str(value["applied_series_sha256"]),
            patched_tree_sha256=str(value["patched_tree_sha256"]),
            series_name=str(value["series_name"]),
        )
    except (KeyError, TypeError, ValueError, ReceiptError) as error:
        raise ReplayError("replay proof is malformed; run he replay") from error
    if value.get("receipt_id") != receipt.receipt_id:
        raise ReplayError("replay proof checksum is invalid; run he replay")
    return receipt


def require_current_replay_proof(
    worktree: Path,
    source_dir: Path,
) -> ReplayReceipt:
    """Fail closed unless the replay receipt exactly matches current inputs."""
    path = receipt_path(source_dir.parent)
    if not path.is_file():
        raise ReplayError("no current Quilt replay proof; run he replay")
    receipt = _read_receipt(path)
    source, applied_sha256 = current_source_receipt(worktree, source_dir)
    if receipt.source != source:
        raise ReplayError(
            "Quilt replay proof is stale for the current source or patch bytes; run he replay"
        )
    if receipt.applied_series_sha256 != applied_sha256:
        raise ReplayError("Quilt replay proof does not match the applied series; run he replay")
    if receipt.patched_tree_sha256 != _patched_tree_sha256(worktree, source_dir):
        raise ReplayError("patch-owned source changed after replay; run he replay")
    if receipt.series_name != "series.merged":
        raise ReplayError("Quilt replay proof names the wrong series; run he replay")
    return receipt


def _write_proof(worktree: Path, source_dir: Path) -> ReplayReceipt:
    source, applied_sha256 = current_source_receipt(worktree, source_dir)
    receipt = ReplayReceipt.create(
        source=source,
        applied_series_sha256=applied_sha256,
        patched_tree_sha256=_patched_tree_sha256(worktree, source_dir),
        series_name="series.merged",
    )
    receipt_dir = receipt_path(source_dir.parent).parent
    write_receipt_atomic(receipt_dir / "source.json", source)
    write_receipt_atomic(receipt_path(source_dir.parent), receipt)
    return receipt


def _record_replay_proof(worktree: Path, source_dir: Path) -> ReplayReceipt:
    """Record proof immediately after this module completes strict replay."""
    report = inspect_quilt_state(source_dir, worktree / "patches")
    report.comparison.require_complete()
    if any(source_dir.rglob("*.rej")):
        raise ReplayError("patch rejects remain in the development source")
    return _write_proof(worktree, source_dir)


def _quilt_environment(worktree: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["QUILT_PATCHES"] = str(worktree / "patches")
    environment["QUILT_SERIES"] = "series.merged"
    environment["QUILT_PATCH_OPTS"] = (
        "--unified --reject-format=unified --fuzz=0"
    )
    return environment


def _run_quilt(
    source_dir: Path, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["quilt", "--quiltrc", "-", *arguments],
        cwd=source_dir,
        env=environment,
        check=False,
    )


def replay(worktree: Path, source_dir: Path) -> ReplayReceipt:
    """Pop and strictly replay the complete stack, then atomically publish proof."""
    before = current_source_identity(worktree, source_dir)
    path = receipt_path(source_dir.parent)
    invalidate_downstream_receipts(source_dir.parent)
    environment = _quilt_environment(worktree)
    for arguments in (("pop", "-a"), ("push", "-a")):
        result = _run_quilt(source_dir, environment, *arguments)
        if result.returncode:
            raise ReplayError(f"Quilt {' '.join(arguments)} failed; replay proof was not written")
    receipt = _record_replay_proof(worktree, source_dir)
    if receipt.source != before:
        path.unlink(missing_ok=True)
        raise ReplayError("source or patch identity changed during replay; run he replay again")
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("replay", "check"))
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    worktree = arguments.worktree.expanduser().resolve()
    source_dir = arguments.source.expanduser().resolve()
    try:
        if arguments.action == "replay":
            result = replay(worktree, source_dir)
        else:
            result = require_current_replay_proof(worktree, source_dir)
        print(f"replay proof: {result.receipt_id}")
        return 0
    except (OSError, QuiltStateError, ReplayError, ReceiptError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
