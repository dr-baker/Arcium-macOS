#!/usr/bin/env python3
"""Bind runnable Chromium artifacts to one verified replay and build action."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from build_receipt import (
    RECEIPT_SCHEMA,
    ReceiptError,
    material_inputs_sha256,
    sha256_file,
    write_receipt_atomic,
)
from replay_contract import ReplayError, ReplayReceipt, require_current_replay_proof


_SHA256 = re.compile(r"[0-9a-f]{64}")
_LANE = re.compile(r"[a-z][a-z0-9-]{0,31}")
_ACTIONS = {"build-full", "relink-resources"}


class ExecutionError(RuntimeError):
    """A runnable artifact lacks current build-execution proof."""


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def tree_sha256(root: Path) -> str:
    """Hash one artifact tree without following symlinks."""
    root = root.expanduser().absolute()
    if root.is_symlink():
        raise ExecutionError(f"artifact tree must not be a symlink: {root}")
    if not root.is_dir():
        raise ExecutionError(f"artifact tree is missing: {root}")
    digest = hashlib.sha256()
    paths = [root, *sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())]
    for path in paths:
        relative = "." if path == root else path.relative_to(root).as_posix()
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ExecutionError(f"could not inspect artifact path: {relative}") from error
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            kind = b"dir"
            content = b""
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"file"
            try:
                content = path.read_bytes()
            except OSError as error:
                raise ExecutionError(f"could not read artifact path: {relative}") from error
        elif stat.S_ISLNK(metadata.st_mode):
            kind = b"symlink"
            try:
                content = os.readlink(path).encode("utf-8", errors="surrogateescape")
            except OSError as error:
                raise ExecutionError(f"could not read artifact symlink: {relative}") from error
        else:
            raise ExecutionError(f"unsupported artifact path type: {relative}")
        fields = (
            relative.encode("utf-8", errors="surrogateescape"),
            kind,
            str(mode).encode("ascii"),
            content,
        )
        for field in fields:
            digest.update(str(len(field)).encode("ascii"))
            digest.update(b":")
            digest.update(field)
            digest.update(b"\n")
    return digest.hexdigest()


def _artifact_digests(build_root: Path) -> dict[str, str]:
    out = build_root / "src" / "out" / "Default"
    return {
        "Helium.app": tree_sha256(out / "Helium.app"),
        "Helium.app/Contents/MacOS/Helium": sha256_file(
            out / "Helium.app" / "Contents" / "MacOS" / "Helium"
        ),
        "libchrome_dll.dylib": sha256_file(out / "libchrome_dll.dylib"),
    }


@dataclass(frozen=True)
class ExecutionReceipt:
    source_receipt_id: str
    replay_receipt_id: str
    lane: str
    action: str
    targets: tuple[str, ...]
    gn_args_sha256: str
    material_inputs_sha256: str
    applied_series_sha256: str
    artifacts: dict[str, str]
    receipt_id: str

    @classmethod
    def create(
        cls,
        *,
        replay: ReplayReceipt,
        lane: str,
        action: str,
        targets: Iterable[str],
        gn_args_sha256: str,
        artifacts: dict[str, str],
        material_inputs_sha256: str = "0" * 64,
    ) -> "ExecutionReceipt":
        normalized_targets = tuple(dict.fromkeys(str(target) for target in targets))
        if not _LANE.fullmatch(lane):
            raise ReceiptError("execution lane is invalid")
        if action not in _ACTIONS:
            raise ReceiptError("execution action is not runnable-product proof")
        if not normalized_targets or any(target.startswith("-") for target in normalized_targets):
            raise ReceiptError("execution targets are invalid")
        digests = {
            "gn_args_sha256": gn_args_sha256,
            "material_inputs_sha256": material_inputs_sha256,
            "applied_series_sha256": replay.applied_series_sha256,
            **artifacts,
        }
        if any(not _SHA256.fullmatch(value) for value in digests.values()):
            raise ReceiptError("execution artifact digest is invalid")
        payload: dict[str, object] = {
            "schema": RECEIPT_SCHEMA,
            "source_receipt_id": replay.source.receipt_id,
            "replay_receipt_id": replay.receipt_id,
            "lane": lane,
            "action": action,
            "targets": list(normalized_targets),
            "gn_args_sha256": gn_args_sha256,
            "applied_series_sha256": replay.applied_series_sha256,
            "artifacts": dict(sorted(artifacts.items())),
        }
        receipt_id = hashlib.sha256(_canonical_json(payload)).hexdigest()
        return cls(
            source_receipt_id=replay.source.receipt_id,
            replay_receipt_id=replay.receipt_id,
            lane=lane,
            action=action,
            targets=normalized_targets,
            gn_args_sha256=gn_args_sha256,
            material_inputs_sha256=material_inputs_sha256,
            applied_series_sha256=replay.applied_series_sha256,
            artifacts=dict(sorted(artifacts.items())),
            receipt_id=receipt_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "source_receipt_id": self.source_receipt_id,
            "replay_receipt_id": self.replay_receipt_id,
            "lane": self.lane,
            "action": self.action,
            "targets": list(self.targets),
            "gn_args_sha256": self.gn_args_sha256,
            "material_inputs_sha256": self.material_inputs_sha256,
            "applied_series_sha256": self.applied_series_sha256,
            "artifacts": dict(self.artifacts),
        }


def execution_path(build_root: Path) -> Path:
    return build_root.resolve() / ".arcium" / "receipts" / "execution.json"


def invalidate_execution(build_root: Path) -> None:
    for name in ("execution.json", "build.json"):
        try:
            (build_root.resolve() / ".arcium" / "receipts" / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ExecutionError(f"could not invalidate stale receipt: {name}") from error


def record_execution(
    worktree: Path,
    build_root: Path,
    *,
    lane: str,
    action: str,
    targets: Iterable[str],
) -> ExecutionReceipt:
    replay = require_current_replay_proof(worktree, build_root / "src")
    try:
        args_digest = sha256_file(build_root / "src" / "out" / "Default" / "args.gn")
        receipt = ExecutionReceipt.create(
            replay=replay,
            lane=lane,
            action=action,
            targets=targets,
            gn_args_sha256=args_digest,
            artifacts=_artifact_digests(build_root),
            material_inputs_sha256=material_inputs_sha256(worktree),
        )
        write_receipt_atomic(execution_path(build_root), receipt)  # type: ignore[arg-type]
        return receipt
    except (OSError, ReceiptError) as error:
        raise ExecutionError("could not record current build execution") from error


def _read_execution(path: Path, replay: ReplayReceipt) -> ExecutionReceipt:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
            raise ValueError("schema")
        receipt = ExecutionReceipt.create(
            replay=replay,
            lane=str(value["lane"]),
            action=str(value["action"]),
            targets=tuple(str(target) for target in value["targets"]),
            gn_args_sha256=str(value["gn_args_sha256"]),
            artifacts={str(name): str(digest) for name, digest in value["artifacts"].items()},
            material_inputs_sha256=str(value["material_inputs_sha256"]),
        )
    except (OSError, KeyError, TypeError, ValueError, ReceiptError) as error:
        raise ExecutionError("build execution receipt is missing or malformed; rebuild") from error
    if value.get("receipt_id") != receipt.receipt_id:
        raise ExecutionError("build execution receipt checksum is invalid; rebuild")
    return receipt


def require_current_execution(
    worktree: Path,
    build_root: Path,
    *,
    lane: str,
) -> ExecutionReceipt:
    replay = require_current_replay_proof(worktree, build_root / "src")
    path = execution_path(build_root)
    if not path.is_file():
        raise ExecutionError("no current runnable build proof; rebuild after he replay")
    receipt = _read_execution(path, replay)
    if receipt.lane != lane:
        raise ExecutionError("runnable build proof belongs to a different lane; rebuild")
    try:
        current_args = sha256_file(build_root / "src" / "out" / "Default" / "args.gn")
        current_artifacts = _artifact_digests(build_root)
        current_material_inputs = material_inputs_sha256(worktree)
    except (OSError, ReceiptError) as error:
        raise ExecutionError("could not validate runnable build artifacts") from error
    if (
        receipt.gn_args_sha256 != current_args
        or receipt.material_inputs_sha256 != current_material_inputs
        or receipt.artifacts != current_artifacts
    ):
        raise ExecutionError("runnable build artifacts changed after the recorded build; rebuild")
    return receipt
