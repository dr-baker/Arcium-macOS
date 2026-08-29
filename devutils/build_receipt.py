#!/usr/bin/env python3
"""Create deterministic, privacy-safe source and build receipts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping


_OBJECT_ID = re.compile(r"[0-9a-f]{40,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BUILD_TARGET = re.compile(
    r"(?:[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*|"
    r"//[A-Za-z0-9_./+-]+:[A-Za-z0-9_.+-]+)"
)
_PROOF_GATES = {
    "series-verified",
    "replayed",
    "configured",
    "compiled",
    "resource-relinked",
    "packaged",
    "launched",
    "behavior-observed",
    "persistence-observed",
    "teardown-observed",
}


class ReceiptError(ValueError):
    """A source or build receipt is malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ReceiptError(f"could not hash artifact: {path}") from error
    return digest.hexdigest()


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_object_id(name: str, value: str) -> str:
    if not _OBJECT_ID.fullmatch(value):
        raise ReceiptError(f"{name} must be a full Git object ID")
    return value


def _require_sha256(name: str, value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ReceiptError(f"{name} must be a SHA-256 digest")
    return value


def _safe_build_target(target: str) -> bool:
    if not _BUILD_TARGET.fullmatch(target) or target.startswith("-"):
        return False
    if target.startswith("//"):
        path_part = target[2:].split(":", maxsplit=1)[0]
        return ".." not in Path(path_part).parts
    return ".." not in Path(target).parts


@dataclass(frozen=True)
class SourceReceipt:
    outer_commit: str
    core_commit: str
    gitlink_commit: str
    patch_series_sha256: str
    receipt_id: str

    @classmethod
    def create(
        cls,
        *,
        outer_commit: str,
        core_commit: str,
        gitlink_commit: str,
        patch_series_sha256: str,
    ) -> "SourceReceipt":
        payload = {
            "schema": 1,
            "outer_commit": _require_object_id("outer_commit", outer_commit),
            "core_commit": _require_object_id("core_commit", core_commit),
            "gitlink_commit": _require_object_id("gitlink_commit", gitlink_commit),
            "patch_series_sha256": _require_sha256(
                "patch_series_sha256", patch_series_sha256
            ),
        }
        if payload["core_commit"] != payload["gitlink_commit"]:
            raise ReceiptError("outer gitlink does not select the recorded core commit")
        receipt_id = hashlib.sha256(_canonical_json(payload)).hexdigest()
        return cls(receipt_id=receipt_id, **{key: value for key, value in payload.items() if key != "schema"})

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "receipt_id": self.receipt_id,
            "outer_commit": self.outer_commit,
            "core_commit": self.core_commit,
            "gitlink_commit": self.gitlink_commit,
            "patch_series_sha256": self.patch_series_sha256,
        }


@dataclass(frozen=True)
class BuildReceipt:
    source: SourceReceipt
    lane: str
    status: str
    gn_args_sha256: str
    applied_series_sha256: str
    targets: tuple[str, ...]
    proof_gates: tuple[str, ...]
    artifacts: Mapping[str, str]
    receipt_id: str

    @classmethod
    def create(
        cls,
        *,
        source: SourceReceipt,
        lane: str,
        status: str,
        gn_args_sha256: str,
        applied_series_sha256: str,
        targets: Iterable[str] = (),
        proof_gates: Iterable[str] = (),
        artifacts: Mapping[str, str] | None = None,
    ) -> "BuildReceipt":
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", lane):
            raise ReceiptError("lane must be a stable lowercase identifier")
        if status not in {"incomplete", "complete"}:
            raise ReceiptError("status must be incomplete or complete")
        normalized_targets = tuple(dict.fromkeys(str(target) for target in targets))
        if any(not _safe_build_target(target) for target in normalized_targets):
            raise ReceiptError("targets must be nonempty generated-build labels or paths")
        normalized_gates = tuple(dict.fromkeys(str(gate) for gate in proof_gates))
        unknown = set(normalized_gates).difference(_PROOF_GATES)
        if unknown:
            raise ReceiptError(f"unknown proof gates: {', '.join(sorted(unknown))}")
        normalized_artifacts = dict(sorted((artifacts or {}).items()))
        for name, digest in normalized_artifacts.items():
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ReceiptError(f"unsafe artifact name: {name}")
            _require_sha256(f"artifact {name}", digest)
        payload: dict[str, object] = {
            "schema": 1,
            "source_receipt_id": source.receipt_id,
            "lane": lane,
            "status": status,
            "gn_args_sha256": _require_sha256("gn_args_sha256", gn_args_sha256),
            "applied_series_sha256": _require_sha256(
                "applied_series_sha256", applied_series_sha256
            ),
            "targets": list(normalized_targets),
            "proof_gates": list(normalized_gates),
            "artifacts": normalized_artifacts,
        }
        receipt_id = hashlib.sha256(_canonical_json(payload)).hexdigest()
        return cls(
            source=source,
            lane=lane,
            status=status,
            gn_args_sha256=str(payload["gn_args_sha256"]),
            applied_series_sha256=str(payload["applied_series_sha256"]),
            targets=normalized_targets,
            proof_gates=normalized_gates,
            artifacts=normalized_artifacts,
            receipt_id=receipt_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "receipt_id": self.receipt_id,
            "source": self.source.to_dict(),
            "lane": self.lane,
            "status": self.status,
            "gn_args_sha256": self.gn_args_sha256,
            "applied_series_sha256": self.applied_series_sha256,
            "targets": list(self.targets),
            "proof_gates": list(self.proof_gates),
            "artifacts": dict(self.artifacts),
        }


def write_receipt_atomic(path: Path, receipt: SourceReceipt | BuildReceipt) -> Path:
    """Publish a complete private receipt with one atomic file replacement."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt.to_dict(), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
