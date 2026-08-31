#!/usr/bin/env python3
"""Read-only source, lane, Quilt, receipt, and Dev-bundle preflight.

This module is the small inspection boundary for ``he context``.  It owns no
build state and deliberately delegates validation to the existing lane,
Quilt, replay, execution, and package helpers.  The default output is a
compact human summary; ``--json`` emits the same privacy-safe document for
agents and scripts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
from typing import Callable, Mapping
from collections.abc import Sequence

# Several of the existing devutils modules intentionally support direct
# script execution and therefore import their siblings by top-level name.
# Make that established layout work when this module is imported as
# ``devutils.development_context`` as well.
_DEVUTILS_DIR = str(Path(__file__).resolve().parent)
if _DEVUTILS_DIR not in sys.path:
    sys.path.insert(0, _DEVUTILS_DIR)

try:
    from .build_lane import LaneError, LaneReport, LaneSpec, inspect_lane
    from .build_execution import ExecutionError, require_current_execution
    from .build_receipt import ReceiptError
    from .build_receipt_cli import require_current_packaged_build
    from .quilt_state import QuiltStateError, QuiltStateReport, inspect_quilt_state
    from .replay_contract import ReplayError, require_current_replay_proof
except ImportError:  # pragma: no cover - exercised by the direct CLI entry point
    from build_lane import LaneError, LaneReport, LaneSpec, inspect_lane
    from build_execution import ExecutionError, require_current_execution
    from build_receipt import ReceiptError
    from build_receipt_cli import require_current_packaged_build
    from quilt_state import QuiltStateError, QuiltStateReport, inspect_quilt_state
    from replay_contract import ReplayError, require_current_replay_proof


_OBJECT_ID = re.compile(r"[0-9a-f]{40,64}\Z")
_RECEIPT_KINDS = ("replay", "build", "package")


class ContextError(RuntimeError):
    """The selected source checkout is missing or ambiguous."""


@dataclass(frozen=True)
class RepositoryState:
    """Aggregate Git state without retaining potentially private filenames."""

    root: Path
    head: str
    branch: str | None
    dirty: bool
    dirty_records: int

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "head": self.head,
            "branch": self.branch,
            "dirty": self.dirty,
            "dirty_records": self.dirty_records,
        }


@dataclass(frozen=True)
class ContextPaths:
    worktree: Path
    build_root: Path
    source_dir: Path
    out_dir: Path
    core_dir: Path
    dev_app: Path


def select_warm_lane(
    candidates: Sequence[Mapping[str, object]],
    context_checker: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Select a verified warm lane without creating files or probing builds.

    Candidates must already be ordered by preference (normally heavy, local).
    The returned document contains ``selected`` or rejection ``reasons`` and
    preserves absolute paths intentionally so shell callers can use them.
    """
    reasons: list[str] = []
    for candidate in candidates:
        name = str(candidate.get("name") or "candidate")
        root = str(candidate.get("build_root") or "-")
        try:
            document = context_checker(candidate)
        except Exception as error:  # selector must fail closed on probe errors
            reasons.append(f"{name} ({root}): {error}")
            continue
        if bool(document.get("ok")) and document.get("dev_bundle", {}).get("freshness") == "current":
            return {"selected": dict(candidate), "reasons": reasons}
        limits = document.get("limits")
        detail = "; ".join(str(item) for item in limits) if isinstance(limits, Sequence) and not isinstance(limits, (str, bytes)) else "context is not current"
        reasons.append(f"{name} ({root}): {detail}")
    return {
        "selected": None,
        "reasons": reasons or ["no warm lane candidates were supplied"],
        "error": "no verified warm lane available; run he replay and he dev-bundle, or explicitly prepare a lane",
    }


def _git_text(repo: Path, *arguments: str) -> str:
    """Run one bounded, non-shell Git query and retain no command output on failure."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ContextError(f"could not inspect Git state in {repo}") from error
    if result.returncode:
        raise ContextError(f"could not inspect Git state in {repo}")
    return result.stdout.strip()


def _git_status_count(repo: Path) -> int:
    """Count changed records while never exposing their paths."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
                "-z",
            ],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise ContextError(f"could not inspect Git state in {repo}") from error
    if result.returncode:
        raise ContextError(f"could not inspect Git state in {repo}")
    output = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout).encode()
    return output.count(b"\0")


def inspect_repository(repo: Path) -> RepositoryState:
    """Read one repository's branch, commit, and aggregate dirty state."""

    repo = repo.expanduser().resolve()
    head = _git_text(repo, "rev-parse", "HEAD")
    if not _OBJECT_ID.fullmatch(head):
        raise ContextError(f"Git returned an invalid HEAD for {repo}")
    branch = _git_text(repo, "branch", "--show-current") or None
    dirty_records = _git_status_count(repo)
    return RepositoryState(
        root=repo,
        head=head,
        branch=branch,
        dirty=dirty_records > 0,
        dirty_records=dirty_records,
    )


def resolve_context_paths(
    worktree: str | os.PathLike[str],
    build_root: str | os.PathLike[str] | None = None,
) -> ContextPaths:
    """Resolve the selected worktree and generated source/output paths."""

    root = Path(worktree).expanduser().resolve()
    build = root / "build" if build_root is None else Path(build_root).expanduser().resolve()
    source = build / "src"
    out = source / "out" / "Default"
    return ContextPaths(
        worktree=root,
        build_root=build,
        source_dir=source,
        out_dir=out,
        core_dir=root / "helium-chromium",
        dev_app=out / "Helium Dev.app",
    )


def inspect_core(paths: ContextPaths) -> dict[str, object]:
    """Compare the checked-out core commit with the outer Gitlink."""

    try:
        core_head = _git_text(paths.core_dir, "rev-parse", "HEAD")
        if not _OBJECT_ID.fullmatch(core_head):
            raise ContextError(f"Git returned an invalid core HEAD for {paths.core_dir}")
        tree = _git_text(paths.worktree, "ls-tree", "HEAD", "--", "helium-chromium")
    except ContextError as error:
        return {
            "path": str(paths.core_dir),
            "available": False,
            "head": None,
            "gitlink": None,
            "match": False,
            "error": str(error),
        }

    lines = [line for line in tree.splitlines() if line.strip()]
    fields = lines[0].split() if len(lines) == 1 else []
    if len(fields) != 4 or fields[0] != "160000" or fields[1] != "commit" or fields[3] != "helium-chromium":
        return {
            "path": str(paths.core_dir),
            "available": False,
            "head": core_head,
            "gitlink": None,
            "match": False,
            "error": "outer repository has no unambiguous helium-chromium gitlink",
        }
    gitlink = fields[2]
    if not _OBJECT_ID.fullmatch(gitlink):
        return {
            "path": str(paths.core_dir),
            "available": False,
            "head": core_head,
            "gitlink": gitlink,
            "match": False,
            "error": "outer repository has an invalid helium-chromium gitlink",
        }
    return {
        "path": str(paths.core_dir),
        "available": True,
        "head": core_head,
        "gitlink": gitlink,
        "match": core_head == gitlink,
        "error": None if core_head == gitlink else "checked-out core HEAD does not match the outer gitlink",
    }


def _lane_spec(
    paths: ContextPaths,
    lane: str,
    expected_volume_uuid: str | None,
) -> LaneSpec:
    heavy = lane == "heavy"
    return LaneSpec(
        name=lane,
        root=paths.build_root,
        minimum_free_bytes=0,
        expected_volume_uuid=expected_volume_uuid if heavy else None,
        require_external=heavy,
        require_case_sensitive_apfs=heavy,
        warn_if_unencrypted=heavy,
        warn_if_ownership_disabled=heavy,
    )


def inspect_selected_lane(
    paths: ContextPaths,
    lane: str,
    *,
    expected_volume_uuid: str | None = None,
    lane_inspector: Callable[[LaneSpec], LaneReport] | None = None,
) -> dict[str, object]:
    """Inspect only the selected lane; never create it or reserve its lock."""

    spec = _lane_spec(paths, lane, expected_volume_uuid)
    inspector = inspect_lane if lane_inspector is None else lane_inspector
    root = str(paths.build_root)
    try:
        report = inspector(spec)
    except (LaneError, OSError) as error:
        return {
            "name": lane,
            "root": root,
            "available": False,
            "ok": False,
            "volume": None,
            "diagnostics": [],
            "error": str(error),
        }

    volume = report.volume
    diagnostics = [
        {
            "severity": item.severity,
            "code": item.code,
            "message": item.message,
        }
        for item in report.diagnostics
    ]
    return {
        "name": lane,
        "root": root,
        "available": report.ok,
        "ok": report.ok,
        "volume": {
            "mount_point": str(volume.mount_point),
            "volume_uuid": volume.volume_uuid,
            "filesystem": volume.filesystem_name,
            "free_bytes": volume.free_bytes,
            "writable": volume.writable,
            "external": volume.external,
            "case_sensitive": volume.case_sensitive,
            "solid_state": volume.solid_state,
        },
        "diagnostics": diagnostics,
        "error": None,
    }


def inspect_quilt(
    paths: ContextPaths,
    *,
    quilt_inspector: Callable[[Path, Path], QuiltStateReport] | None = None,
) -> dict[str, object]:
    """Read Quilt metadata when present and report partial state safely."""

    if not paths.source_dir.is_dir():
        return {
            "available": False,
            "state": "missing",
            "declared_count": None,
            "applied_count": None,
            "top": None,
            "complete": False,
            "valid_prefix": False,
            "error": f"generated source checkout is missing: {paths.source_dir}",
        }
    metadata = paths.source_dir / ".pc"
    if not metadata.is_dir():
        return {
            "available": False,
            "state": "unavailable",
            "declared_count": None,
            "applied_count": None,
            "top": None,
            "complete": False,
            "valid_prefix": False,
            "error": "Quilt metadata is unavailable",
        }

    inspector = inspect_quilt_state if quilt_inspector is None else quilt_inspector
    try:
        generated = paths.build_root / ".arcium" / "patches"
        report = inspector(paths.source_dir, generated)
    except (QuiltStateError, OSError) as error:
        return {
            "available": False,
            "state": "ambiguous",
            "declared_count": None,
            "applied_count": None,
            "top": None,
            "complete": False,
            "valid_prefix": False,
            "error": str(error),
        }

    comparison = report.comparison
    applied_count = len(comparison.applied)
    declared_count = len(comparison.declared)
    if not comparison.valid_prefix:
        state = "ambiguous"
    elif comparison.complete:
        state = "complete"
    elif applied_count == 0:
        state = "popped"
    else:
        state = "partial"
    next_patch = (
        comparison.declared[applied_count]
        if comparison.valid_prefix and applied_count < declared_count
        else None
    )
    detail = comparison.detail
    if detail is None and next_patch is not None:
        detail = f"Quilt series is only partially applied: next patch is {next_patch}"
    return {
        "available": True,
        "state": state,
        "declared_count": declared_count,
        "applied_count": applied_count,
        "top": comparison.applied[-1] if comparison.applied else None,
        "next_patch": next_patch,
        "complete": comparison.complete,
        "valid_prefix": comparison.valid_prefix,
        "declared_sha256": report.declared_sha256,
        "applied_sha256": report.applied_sha256,
        "error": detail,
    }


def _receipt_status(
    state: str,
    *,
    path: Path,
    receipt_id: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    return {
        "state": state,
        "fresh": state == "current",
        "path": str(path),
        "receipt_id": receipt_id,
        "detail": detail,
    }


def _receipt_error_state(error: Exception, path: Path) -> dict[str, object]:
    detail = str(error)
    lowered = detail.lower()
    if not path.exists() or "no current" in lowered or "missing" in lowered:
        state = "missing"
    elif "stale" in lowered or "changed" in lowered or "does not match" in lowered:
        state = "stale"
    else:
        state = "unavailable"
    return _receipt_status(state, path=path, detail=detail)


def _receipt_id(path: Path, field: str = "receipt_id") -> str | None:
    """Read one receipt ID without retaining or printing its other fields."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    result = value.get(field) if isinstance(value, dict) else None
    return result if isinstance(result, str) else None


def inspect_receipts(
    paths: ContextPaths,
    lane: str,
    *,
    replay_checker: Callable[[Path, Path], object] | None = None,
    execution_checker: Callable[..., object] | None = None,
    package_checker: Callable[..., object] | None = None,
) -> dict[str, dict[str, object]]:
    """Check replay, build-execution, and package proof in dependency order."""

    receipt_root = paths.build_root / ".arcium" / "receipts"
    replay_path = receipt_root / "replay.json"
    execution_path = receipt_root / "execution.json"
    package_path = receipt_root / "build.json"
    replay_check = require_current_replay_proof if replay_checker is None else replay_checker
    execution_check = (
        require_current_execution if execution_checker is None else execution_checker
    )
    package_check = (
        require_current_packaged_build if package_checker is None else package_checker
    )

    # A package receipt is the strongest existing proof: its validator checks
    # the source, replay, execution, and copied bundle contracts.  Reusing one
    # successful result avoids rehashing those trees for each upstream line.
    if package_path.is_file() or package_checker is not None:
        try:
            package = package_check(paths.worktree, paths.build_root, lane=lane)
        except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as error:
            package_status = _receipt_error_state(error, package_path)
            detail = str(error)
            if isinstance(error, ReplayError):
                replay_status = _receipt_error_state(error, replay_path)
                build_status = _receipt_status(
                    "blocked",
                    path=execution_path,
                    detail="requires a current Quilt replay proof",
                )
                package_status = _receipt_status(
                    "blocked", path=package_path, detail="requires a current Quilt replay proof"
                )
            elif isinstance(error, ExecutionError):
                replay_status = _receipt_status(
                    "current", path=replay_path, receipt_id=_receipt_id(replay_path)
                )
                build_status = _receipt_error_state(error, execution_path)
                package_status = _receipt_status(
                    "blocked", path=package_path, detail="requires a current build proof"
                )
            elif isinstance(error, ReceiptError) and "packaged build proof is stale" in detail.lower():
                # A stale package does not prove that its upstream receipts
                # are current; re-run both cheap validators independently.
                try:
                    replay = replay_check(paths.worktree, paths.source_dir)
                    replay_status = _receipt_status("current", path=replay_path,
                                                    receipt_id=getattr(replay, "receipt_id", None))
                except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as upstream_error:
                    replay_status = _receipt_error_state(upstream_error, replay_path)
                if replay_status["state"] == "current":
                    try:
                        execution = execution_check(paths.worktree, paths.build_root, lane=lane)
                        build_status = _receipt_status("current", path=execution_path,
                                                       receipt_id=getattr(execution, "receipt_id", None))
                    except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as upstream_error:
                        build_status = _receipt_error_state(upstream_error, execution_path)
                else:
                    build_status = _receipt_status("blocked", path=execution_path,
                                                   detail="requires a current Quilt replay proof")
            else:
                # The package validator could not establish which upstream
                # contract failed. Preserve its actionable detail and avoid a
                # second full tree walk merely to guess.
                replay_status = _receipt_status(
                    "unavailable", path=replay_path, detail="upstream proof was not established"
                )
                build_status = _receipt_status(
                    "blocked", path=execution_path, detail="requires a current Quilt replay proof"
                )
            return {"replay": replay_status, "build": build_status, "package": package_status}
        else:
            replay_status = _receipt_status(
                "current",
                path=replay_path,
                receipt_id=getattr(package, "replay_receipt_id", None),
            )
            build_status = _receipt_status(
                "current",
                path=execution_path,
                receipt_id=getattr(package, "execution_receipt_id", None),
            )
            package_status = _receipt_status(
                "current", path=package_path, receipt_id=getattr(package, "receipt_id", None)
            )
            return {"replay": replay_status, "build": build_status, "package": package_status}

    try:
        replay = replay_check(paths.worktree, paths.source_dir)
    except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as error:
        replay_status = _receipt_error_state(error, replay_path)
    else:
        replay_status = _receipt_status(
            "current", path=replay_path, receipt_id=getattr(replay, "receipt_id", None)
        )

    if replay_status["state"] != "current":
        build_status = _receipt_status(
            "blocked",
            path=execution_path,
            detail="requires a current Quilt replay proof",
        )
        package_status = _receipt_status(
            "blocked",
            path=package_path,
            detail="requires a current build proof",
        )
        return {"replay": replay_status, "build": build_status, "package": package_status}

    try:
        execution = execution_check(
            paths.worktree,
            paths.build_root,
            lane=lane,
        )
    except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as error:
        build_status = _receipt_error_state(error, execution_path)
    else:
        build_status = _receipt_status(
            "current", path=execution_path, receipt_id=getattr(execution, "receipt_id", None)
        )

    if build_status["state"] != "current":
        package_status = _receipt_status(
            "blocked",
            path=package_path,
            detail="requires a current build proof",
        )
        return {"replay": replay_status, "build": build_status, "package": package_status}

    try:
        package = package_check(paths.worktree, paths.build_root, lane=lane)
    except (ExecutionError, ReplayError, ReceiptError, QuiltStateError, OSError) as error:
        package_status = _receipt_error_state(error, package_path)
    else:
        package_status = _receipt_status(
            "current", path=package_path, receipt_id=getattr(package, "receipt_id", None)
        )
    return {"replay": replay_status, "build": build_status, "package": package_status}


def inspect_dev_bundle(paths: ContextPaths, package_status: Mapping[str, object]) -> dict[str, object]:
    """Validate the exact copied Dev bundle identity without launching it."""

    app = paths.dev_app
    base: dict[str, object] = {
        "path": str(app),
        "exists": app.exists() or app.is_symlink(),
        "exact": False,
        "bundle_identifier": None,
        "display_name": None,
        "executable": None,
        "freshness": "missing",
        "error": None,
    }
    if app.is_symlink():
        base["freshness"] = "ambiguous"
        base["error"] = "Dev bundle must not be a symlink"
        return base
    if not app.is_dir():
        base["error"] = f"Helium Dev.app is missing from {paths.out_dir}"
        return base
    plist_path = app / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        base["freshness"] = "ambiguous"
        base["error"] = f"could not read Dev bundle metadata: {error}"
        return base
    if not isinstance(info, dict):
        base["freshness"] = "ambiguous"
        base["error"] = "Dev bundle metadata is not a dictionary"
        return base

    bundle_identifier = info.get("CFBundleIdentifier")
    display_name = info.get("CFBundleDisplayName")
    executable_name = info.get("CFBundleExecutable")
    base["bundle_identifier"] = bundle_identifier
    base["display_name"] = display_name
    if not isinstance(executable_name, str) or not executable_name or "/" in executable_name or "\\" in executable_name:
        base["freshness"] = "ambiguous"
        base["error"] = "Dev bundle has no safe executable"
        return base
    executable = app / "Contents" / "MacOS" / executable_name
    base["executable"] = str(executable)
    if bundle_identifier != "net.imput.helium.dev" or display_name != "Helium Dev":
        base["freshness"] = "ambiguous"
        base["error"] = "bundle metadata is not the exact Helium Dev identity"
        return base
    if not executable.is_file() or not os.access(executable, os.X_OK):
        base["freshness"] = "ambiguous"
        base["error"] = "Helium Dev executable is missing or not executable"
        return base
    base["exact"] = True
    package_state = package_status.get("state")
    if package_state == "current":
        base["freshness"] = "current"
    elif package_state in {"stale", "missing"}:
        base["freshness"] = "stale" if package_state == "stale" else "unproven"
    else:
        base["freshness"] = "unproven"
    return base


def _append_limit(limits: list[str], value: object) -> None:
    if not isinstance(value, str) or not value or value in limits:
        return
    limits.append(value)


def _limits_for(
    *,
    core: Mapping[str, object],
    lane: Mapping[str, object],
    quilt: Mapping[str, object],
    receipts: Mapping[str, Mapping[str, object]],
    bundle: Mapping[str, object],
) -> list[str]:
    limits: list[str] = []
    if not core.get("available"):
        _append_limit(limits, core.get("error"))
    elif not core.get("match"):
        _append_limit(limits, core.get("error"))

    if not lane.get("available"):
        name = str(lane.get("name") or "selected")
        detail = lane.get("error")
        if name == "heavy":
            _append_limit(limits, f"T9 heavy lane unavailable; use the local or worktree lane ({detail or 'storage preflight failed'})")
        else:
            _append_limit(limits, f"{name} lane unavailable: {detail or 'storage preflight failed'}")
    for diagnostic in lane.get("diagnostics", ()):
        if isinstance(diagnostic, Mapping) and diagnostic.get("severity") == "error":
            _append_limit(limits, diagnostic.get("message"))

    if not quilt.get("available") or quilt.get("state") == "ambiguous":
        _append_limit(limits, quilt.get("error"))
    elif not quilt.get("complete"):
        _append_limit(limits, quilt.get("error"))

    for kind in _RECEIPT_KINDS:
        status = receipts.get(kind, {})
        if status.get("state") != "current":
            detail = status.get("detail") or f"{kind} proof is {status.get('state', 'unavailable')}"
            _append_limit(limits, detail)

    if not bundle.get("exact") or bundle.get("freshness") != "current":
        _append_limit(limits, bundle.get("error"))
        if bundle.get("freshness") in {"missing", "unproven", "stale"}:
            _append_limit(
                limits,
                "exact current Helium Dev.app is unavailable; run he dev-bundle after a current build",
            )
    return limits


def collect_context(
    worktree: str | os.PathLike[str],
    *,
    build_root: str | os.PathLike[str] | None = None,
    lane: str = "local",
    expected_volume_uuid: str | None = None,
    lane_inspector: Callable[[LaneSpec], LaneReport] | None = None,
    quilt_inspector: Callable[[Path, Path], QuiltStateReport] | None = None,
    replay_checker: Callable[[Path, Path], object] | None = None,
    execution_checker: Callable[..., object] | None = None,
    package_checker: Callable[..., object] | None = None,
) -> dict[str, object]:
    """Collect one complete, read-only development context document."""

    paths = resolve_context_paths(worktree, build_root)
    outer = inspect_repository(paths.worktree)
    core_state = inspect_repository(paths.core_dir)
    core = inspect_core(paths)
    lane_state = inspect_selected_lane(
        paths,
        lane,
        expected_volume_uuid=expected_volume_uuid,
        lane_inspector=lane_inspector,
    )
    quilt = inspect_quilt(paths, quilt_inspector=quilt_inspector)
    receipts = inspect_receipts(
        paths,
        lane,
        replay_checker=replay_checker,
        execution_checker=execution_checker,
        package_checker=package_checker,
    )
    bundle = inspect_dev_bundle(paths, receipts["package"])
    limits = _limits_for(
        core=core,
        lane=lane_state,
        quilt=quilt,
        receipts=receipts,
        bundle=bundle,
    )
    return {
        "ok": not limits,
        "action": "context",
        "source": {
            "worktree": str(paths.worktree),
            "build_root": str(paths.build_root),
            "source_dir": str(paths.source_dir),
            "out_dir": str(paths.out_dir),
            "exists": paths.source_dir.is_dir(),
        },
        "outer": outer.to_dict(),
        "core_repository": core_state.to_dict(),
        "core": core,
        "lane": lane_state,
        "quilt": quilt,
        "receipts": receipts,
        "dev_bundle": bundle,
        "limits": limits,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the selected Helium development context")
    parser.add_argument("--worktree", "--root", dest="worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--lane", choices=("local", "heavy", "worktree"), default="local")
    parser.add_argument("--expected-volume-uuid")
    parser.add_argument("--json", action="store_true")
    return parser


def _emit_human(document: Mapping[str, object]) -> None:
    outer = document["outer"]
    core = document["core"]
    lane = document["lane"]
    quilt = document["quilt"]
    receipts = document["receipts"]
    bundle = document["dev_bundle"]
    assert isinstance(outer, Mapping)
    assert isinstance(core, Mapping)
    assert isinstance(lane, Mapping)
    assert isinstance(quilt, Mapping)
    assert isinstance(receipts, Mapping)
    assert isinstance(bundle, Mapping)
    print(f"context: {'ready' if document.get('ok') else 'not ready'}")
    branch = outer.get("branch") or "detached"
    cleanliness = "dirty" if outer.get("dirty") else "clean"
    head = str(outer.get("head") or "-")[:12]
    print(f"source: {document['source']['worktree']} · {branch} · {cleanliness} · {head}")
    core_state = "match" if core.get("match") else "mismatch"
    print(f"core: {core_state} · {str(core.get('head') or '-')[:12]} · gitlink {str(core.get('gitlink') or '-')[:12]}")
    lane_state = "available" if lane.get("available") else "unavailable"
    print(f"lane: {lane.get('name')} · {lane.get('root')} · {lane_state}")
    if quilt.get("available"):
        print(
            f"quilt: {quilt.get('applied_count')}/{quilt.get('declared_count')} · "
            f"top {quilt.get('top') or '-'} · {quilt.get('state')}"
        )
    else:
        print(f"quilt: {quilt.get('state')} · {quilt.get('error') or '-'}")
    proof = " · ".join(
        f"{kind} {receipts.get(kind, {}).get('state', 'unavailable')}"
        for kind in _RECEIPT_KINDS
    )
    print(f"proof: {proof}")
    print(f"dev: {bundle.get('path')} · {bundle.get('freshness')}" )
    for limit in document.get("limits", ()):
        print(f"limit: {limit}")


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    json_mode = arguments.json
    try:
        document = collect_context(
            arguments.worktree,
            build_root=arguments.build_root,
            lane=arguments.lane,
            expected_volume_uuid=arguments.expected_volume_uuid,
        )
    except (ContextError, OSError) as error:
        document = {"ok": False, "action": "context", "error": str(error)}
        print(str(error), file=sys.stderr)
        if json_mode:
            json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
            sys.stdout.write("\n")
        return 2
    if json_mode:
        json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        _emit_human(document)
    return 0 if bool(document.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
