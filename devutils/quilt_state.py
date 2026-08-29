#!/usr/bin/env python3
"""Inspect Quilt provenance without changing the applied source tree."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shlex


class QuiltStateError(ValueError):
    """The selected source tree has invalid or ambiguous Quilt metadata."""


def _patch_name(line: str, *, path: Path, line_number: int) -> str | None:
    try:
        fields = shlex.split(line, comments=True, posix=True)
    except ValueError as error:
        raise QuiltStateError(f"{path}:{line_number}: invalid series syntax: {error}") from error
    if not fields:
        return None
    name = fields[0]
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or name in {".", ".."}:
        raise QuiltStateError(f"{path}:{line_number}: unsafe patch name: {name}")
    return name


def read_patch_list(path: Path) -> tuple[str, ...]:
    """Read ordered patch names from a Quilt series or applied-patches file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise QuiltStateError(f"could not read Quilt list: {path}") from error
    result: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        name = _patch_name(line, path=path, line_number=line_number)
        if name is not None:
            result.append(name)
    return tuple(result)


def patch_list_sha256(patches: tuple[str, ...]) -> str:
    """Return a stable digest that preserves ordering and list boundaries."""
    payload = "".join(f"{len(name)}:{name}\n" for name in patches).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_unique(patches: tuple[str, ...], *, description: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for patch in patches:
        if patch in seen and patch not in duplicates:
            duplicates.append(patch)
        seen.add(patch)
    if duplicates:
        raise QuiltStateError(
            f"duplicate patches in {description}: {', '.join(duplicates)}"
        )


@dataclass(frozen=True)
class SeriesComparison:
    declared: tuple[str, ...]
    applied: tuple[str, ...]
    valid_prefix: bool
    complete: bool
    divergence_index: int | None
    expected: str | None
    actual: str | None
    detail: str | None

    def require_valid_prefix(self) -> None:
        if not self.valid_prefix:
            raise QuiltStateError(self.detail or "applied patches do not match the declared series")

    def require_complete(self) -> None:
        self.require_valid_prefix()
        if not self.complete:
            next_patch = self.declared[len(self.applied)]
            raise QuiltStateError(
                f"Quilt series is only partially applied: next patch is {next_patch}"
            )


def compare_patch_lists(
    declared: tuple[str, ...], applied: tuple[str, ...]
) -> SeriesComparison:
    """Compare applied patches with the only safe partial state: an exact prefix."""
    common = min(len(declared), len(applied))
    divergence = next(
        (index for index in range(common) if declared[index] != applied[index]),
        None,
    )
    if divergence is None and len(applied) <= len(declared):
        return SeriesComparison(
            declared=declared,
            applied=applied,
            valid_prefix=True,
            complete=len(applied) == len(declared),
            divergence_index=None,
            expected=None,
            actual=None,
            detail=None,
        )

    index = common if divergence is None else divergence
    expected = declared[index] if index < len(declared) else None
    actual = applied[index] if index < len(applied) else None
    if expected is None:
        detail = f"applied patch {actual} at position {index + 1} is not declared"
    elif actual is None:
        detail = f"declared patch {expected} at position {index + 1} is not applied"
    elif actual in declared[index + 1 :]:
        skipped = declared[index : declared.index(actual, index + 1)]
        detail = (
            f"applied patches skip declared patch {expected} at position {index + 1}; "
            f"the next applied patch is {actual}; skipped: {', '.join(skipped)}"
        )
    elif expected in applied[index + 1 :]:
        detail = (
            f"applied patch {actual} is extra or reordered at position {index + 1}; "
            f"expected {expected}"
        )
    else:
        detail = (
            f"patch mismatch at position {index + 1}: expected {expected}, got {actual}"
        )
    return SeriesComparison(
        declared=declared,
        applied=applied,
        valid_prefix=False,
        complete=False,
        divergence_index=index,
        expected=expected,
        actual=actual,
        detail=detail,
    )


def _read_metadata(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise QuiltStateError(f"could not read Quilt metadata: {path}") from error
    if not value or "\n" in value or "\x00" in value:
        raise QuiltStateError(f"invalid Quilt metadata: {path}")
    return value


@dataclass(frozen=True)
class QuiltStateReport:
    source_dir: Path
    patches_dir: Path
    series_name: str
    comparison: SeriesComparison
    declared_sha256: str
    applied_sha256: str


def inspect_quilt_state(
    source_dir: Path,
    patches_dir: Path,
    *,
    series_name: str = "series.merged",
) -> QuiltStateReport:
    """Verify Quilt pointers and compare the complete ordered patch histories."""
    source_dir = source_dir.resolve()
    patches_dir = patches_dir.resolve()
    pc_dir = source_dir / ".pc"
    pointer = Path(_read_metadata(pc_dir / ".quilt_patches")).expanduser()
    if not pointer.is_absolute():
        pointer = source_dir / pointer
    actual_patches_dir = pointer.resolve()
    if actual_patches_dir != patches_dir:
        raise QuiltStateError(
            "Quilt patch provenance mismatch: "
            f"metadata points to {actual_patches_dir}, expected {patches_dir}"
        )
    actual_series_name = _read_metadata(pc_dir / ".quilt_series")
    if actual_series_name != series_name:
        raise QuiltStateError(
            f"Quilt series mismatch: metadata names {actual_series_name}, "
            f"expected {series_name}"
        )
    declared = read_patch_list(patches_dir / series_name)
    applied = read_patch_list(pc_dir / "applied-patches")
    _require_unique(declared, description=series_name)
    _require_unique(applied, description="applied-patches")
    comparison = compare_patch_lists(declared, applied)
    return QuiltStateReport(
        source_dir=source_dir,
        patches_dir=patches_dir,
        series_name=series_name,
        comparison=comparison,
        declared_sha256=patch_list_sha256(declared),
        applied_sha256=patch_list_sha256(applied),
    )
