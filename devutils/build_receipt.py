#!/usr/bin/env python3
"""Create deterministic, privacy-safe source and build receipts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import tempfile
from typing import Iterable, Mapping

_OBJECT_ID = re.compile(r"[0-9a-f]{40,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHROMIUM_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){3}")
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
RECEIPT_SCHEMA = 3

# These are the outer-repository files that can change the generated build or
# the Dev package.  Keep this list explicit: documentation, AGENTS.md, tests,
# and other development-only files must not invalidate a runnable proof.
MATERIAL_BUILD_INPUTS = (
    "dev.sh",
    "env.sh",
    "retrieve_and_unpack_resource.sh",
    "requirements-dev.txt",
    "downloads.ini",
    "flags.macos.gn",
    "revision.txt",
    "resources",
    "devutils/arcium_app.py",
    "devutils/build_execution.py",
    "devutils/build_lane.py",
    "devutils/build_preparation.py",
    "devutils/prepare_test_assets.py",
    "devutils/build_receipt.py",
    "devutils/build_receipt_cli.py",
    "devutils/check_source.py",
    "devutils/check_patch_files.py",
    "devutils/gclient_identity.py",
    "devutils/helium_dev.py",
    "devutils/helium_acquisition.sh",
    "devutils/helium_dev_build.py",
    "devutils/helium_dev_bundle.py",
    "devutils/lane_transaction.py",
    "devutils/patch_workspace.py",
    "devutils/profile_clone.py",
    "devutils/quilt_state.py",
    "devutils/replay_contract.py",
    "devutils/replay_timestamps.py",
    "devutils/set_quilt_vars.sh",
    "devutils/setup_dawn_go.sh",
    "devutils/setup_python.sh",
)


# Diagnostics are imported beside the executing builder. A canonical harness
# can select another source worktree that has no diagnostics copy.
EXECUTOR_BUILD_INPUTS = (
    "dev.sh",
    "entitlements/app-entitlements.plist",
    "entitlements/helper-entitlements.plist",
    "entitlements/helper-gpu-entitlements.plist",
    "entitlements/helper-renderer-entitlements.plist",
    "devutils/arcium_app.py",
    "devutils/build_backend.py",
    "devutils/build_diagnostics.py",
    "devutils/build_execution.py",
    "devutils/build_lane.py",
    "devutils/build_preparation.py",
    "devutils/prepare_test_assets.py",
    "devutils/build_lane_cli.py",
    "devutils/build_receipt.py",
    "devutils/build_receipt_cli.py",
    "devutils/check_source.py",
    "devutils/gclient_identity.py",
    "devutils/helium_dev.py",
    "devutils/helium_acquisition.sh",
    "devutils/helium_dev_build.py",
    "devutils/helium_dev_bundle.py",
    "devutils/helium_dev_runtime.py",
    "devutils/lane_transaction.py",
    "devutils/patch_workspace.py",
    "devutils/profile_clone.py",
    "devutils/quilt_state.py",
    "devutils/quilt_state_cli.py",
    "devutils/replay_contract.py",
    "devutils/replay_timestamps.py",
)


CORE_PREPARATION_INPUTS = (
    "utils/generate_resources.py",
    "utils/replace_resources.py",
    "utils/helium_version.py",
    "utils/prune_binaries.py",
    "utils/clone.py",
    "utils/downloads.py",
    "utils/_common.py",
    "utils/_extraction.py",
    "utils/third_party/schema.py",
    "utils/depot_tools.patch",
    "utils/gsutil.patch",
    "downloads.ini",
    "deps.ini",
    "pruning.list",
    "flags.gn",
    "version.txt",
    "revision.txt",
    "chromium_version.txt",
    "resources/generate_resources.txt",
    "resources/helium_resources.txt",
)


MATERIAL_INPUTS_ENV = "HELIUM_DEV_MATERIAL_INPUTS_AT_ENTRY"


HARNESS_SCRIPT_ENV = "HELIUM_DEV_HARNESS_SCRIPT"


HARNESS_SHA256_ENV = "HELIUM_DEV_HARNESS_SHA256"


ACQUISITION_SCRIPT_ENV = "HELIUM_DEV_ACQUISITION_SCRIPT"


ACQUISITION_SHA256_ENV = "HELIUM_DEV_ACQUISITION_SHA256"


ACQUISITION_TARGET_ENV = "HELIUM_DEV_ACQUISITION_TARGET"


PYTHON_SETUP_SCRIPT_ENV = "HELIUM_DEV_PYTHON_SETUP_SCRIPT"


PYTHON_SETUP_SHA256_ENV = "HELIUM_DEV_PYTHON_SETUP_SHA256"


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


def _hash_material_path(root: Path, path: Path, digest: "hashlib._Hash") -> None:
    """Hash one declared material path without following symlinks."""
    relative = path.relative_to(root).as_posix()
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ReceiptError(f"could not inspect material build input: {relative}") from error
    if stat.S_ISDIR(metadata.st_mode):
        kind = b"dir"
        content = b""
    elif stat.S_ISREG(metadata.st_mode):
        kind = b"file"
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ReceiptError(f"could not read material build input: {relative}") from error
    elif stat.S_ISLNK(metadata.st_mode):
        kind = b"symlink"
        try:
            content = os.readlink(path).encode("utf-8", errors="surrogateescape")
        except OSError as error:
            raise ReceiptError(f"could not read material build input: {relative}") from error
    else:
        raise ReceiptError(f"unsupported material build input: {relative}")
    for field in (
        relative.encode("utf-8", errors="surrogateescape"),
        kind,
        str(stat.S_IMODE(metadata.st_mode)).encode("ascii"),
        content,
    ):
        digest.update(str(len(field)).encode("ascii"))
        digest.update(b":")
        digest.update(field)
        digest.update(b"\n")


def _declared_inputs_sha256(root: Path, declarations: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for declared in declarations:
        path = root / declared
        if not path.exists() and not path.is_symlink():
            raise ReceiptError(f"declared material build input is missing: {declared}")
        paths = [path]
        if path.is_dir() and not path.is_symlink():
            paths.extend(
                sorted(
                    path.rglob("*"),
                    key=lambda child: child.relative_to(root).as_posix(),
                )
            )
        for candidate in paths:
            _hash_material_path(root, candidate, digest)
    return digest.hexdigest()


def _resource_manifest(root: Path, name: str, field_counts: set[int]) -> list[list[str]]:
    path = root / "resources" / name
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ReceiptError(f"could not read core resource manifest: {name}") from error
    entries = []
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) not in field_counts:
            raise ReceiptError(f"invalid core resource manifest: {name}:{number}")
        # The utilities interpret plain relative paths. Refuse paths outside
        # resources so every consumed source is covered by this digest.
        for value in (fields[0], fields[-1]) if name == "generate_resources.txt" else (fields[0],):
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ReceiptError(f"resource path escapes declared inputs: {name}:{number}")
        entries.append(fields)
    return entries


def core_preparation_inputs_sha256(worktree: Path) -> str:
    """Bind selected core recipes and manifest-selected original resources."""
    root = worktree / "helium-chromium"
    generated = _resource_manifest(root, "generate_resources.txt", {2, 3})
    copied = _resource_manifest(root, "helium_resources.txt", {2})
    outputs = {fields[-1] for fields in generated}
    inputs = {fields[0] for fields in generated}
    inputs.update(fields[0] for fields in copied if fields[0] not in outputs)
    declarations = (*CORE_PREPARATION_INPUTS, *("resources/" + name for name in sorted(inputs)))
    return _declared_inputs_sha256(root, declarations)


def validate_harness_script(script: Path) -> None:
    """Refuse definitions from a shell sourced before its file was edited."""
    sourced = os.environ.get(HARNESS_SHA256_ENV)
    if sourced is not None and sourced != sha256_file(script):
        raise ReceiptError("development shell changed after sourcing; re-source dev.sh before retrying")


def acquisition_script() -> Path:
    root = Path(__file__).resolve().parents[1]
    script = Path(os.environ.get(ACQUISITION_SCRIPT_ENV, str(root / "devutils/helium_acquisition.sh"))).expanduser().resolve()
    sourced = os.environ.get(ACQUISITION_SHA256_ENV)
    if sourced is not None and sourced != sha256_file(script):
        raise ReceiptError("acquisition helper changed after sourcing; re-source dev.sh before retrying")
    return script


def executor_inputs_sha256(worktree: Path) -> str:
    """Hash the actual helper checkout and the shell that invoked it."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    digest.update(_declared_inputs_sha256(root, EXECUTOR_BUILD_INPUTS).encode("ascii"))
    script = Path(os.environ.get(HARNESS_SCRIPT_ENV, str(root / "dev.sh")))
    script = script.expanduser().resolve()
    validate_harness_script(script)
    digest.update(sha256_file(script).encode("ascii"))
    digest.update(sha256_file(acquisition_script()).encode("ascii"))
    setup = Path(os.environ.get(PYTHON_SETUP_SCRIPT_ENV, str(worktree / "devutils/setup_python.sh"))).expanduser().resolve()
    sourced = os.environ.get(PYTHON_SETUP_SHA256_ENV)
    if sourced is not None and sourced != sha256_file(setup):
        raise ReceiptError("Python setup helper changed after sourcing; re-source dev.sh before retrying")
    digest.update(sha256_file(setup).encode("ascii"))
    return digest.hexdigest()


def material_inputs_sha256(worktree: Path) -> str:
    """Bind selected source inputs and actual executor inputs independently."""
    root = worktree.expanduser().resolve()
    if __package__:
        from .build_backend import BackendError, selected_backend
    else:
        from build_backend import BackendError, selected_backend
    try:
        backend = hashlib.sha256(_canonical_json(selected_backend().identity())).hexdigest()
    except BackendError as error:
        raise ReceiptError(str(error)) from error
    digest = hashlib.sha256()
    for origin, value in (
        (b"selected-source", _declared_inputs_sha256(root, MATERIAL_BUILD_INPUTS)),
        (b"selected-core-preparation", core_preparation_inputs_sha256(root)),
        (b"actual-executors", executor_inputs_sha256(root)),
        (b"selected-backend", backend),
    ):
        digest.update(origin + b":" + value.encode("ascii") + b"\n")
    return digest.hexdigest()


def material_inputs_at_entry(worktree: Path) -> str:
    """Check inherited transaction inputs before executing another stage."""
    current = material_inputs_sha256(worktree)
    inherited = os.environ.get(MATERIAL_INPUTS_ENV)
    if inherited is not None and inherited != current:
        raise ReceiptError("material inputs changed after transaction entry; retry from stable inputs")
    return current


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
    core_commit: str
    gitlink_commit: str
    chromium_version: str
    patch_series_sha256: str
    receipt_id: str

    @classmethod
    def create(
        cls,
        *,
        core_commit: str,
        gitlink_commit: str,
        chromium_version: str,
        patch_series_sha256: str,
    ) -> "SourceReceipt":
        payload = {
            "schema": RECEIPT_SCHEMA,
            "core_commit": _require_object_id("core_commit", core_commit),
            "gitlink_commit": _require_object_id("gitlink_commit", gitlink_commit),
            "chromium_version": chromium_version,
            "patch_series_sha256": _require_sha256(
                "patch_series_sha256", patch_series_sha256
            ),
        }
        if payload["core_commit"] != payload["gitlink_commit"]:
            raise ReceiptError("outer gitlink does not select the recorded core commit")
        if not _CHROMIUM_VERSION.fullmatch(chromium_version):
            raise ReceiptError("chromium_version must contain four numeric components")
        receipt_id = hashlib.sha256(_canonical_json(payload)).hexdigest()
        return cls(receipt_id=receipt_id, **{key: value for key, value in payload.items() if key != "schema"})

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "core_commit": self.core_commit,
            "gitlink_commit": self.gitlink_commit,
            "chromium_version": self.chromium_version,
            "patch_series_sha256": self.patch_series_sha256,
        }


def require_expected_chromium_version(core_dir: Path, source_dir: Path) -> str:
    """Bind generated source to the Chromium archive selected by Arcium core."""
    try:
        expected = (core_dir / "chromium_version.txt").read_text(
            encoding="utf-8"
        ).strip()
        fields: dict[str, str] = {}
        for line in (source_dir / "chrome" / "VERSION").read_text(
            encoding="utf-8"
        ).splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"MAJOR", "MINOR", "BUILD", "PATCH"}:
                fields[key] = value
    except OSError as error:
        raise ReceiptError("could not inspect the selected Chromium version") from error
    if not _CHROMIUM_VERSION.fullmatch(expected):
        raise ReceiptError("core chromium_version.txt is malformed")
    try:
        actual = ".".join(fields[key] for key in ("MAJOR", "MINOR", "BUILD", "PATCH"))
    except KeyError as error:
        raise ReceiptError("generated chrome/VERSION is incomplete") from error
    if actual != expected:
        raise ReceiptError(
            f"generated Chromium version {actual} does not match selected {expected}"
        )
    return expected


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


def current_source_receipt(
    worktree: Path, source_dir: Path, *, require_complete: bool
) -> tuple[SourceReceipt, str]:
    """Build one source identity for replay and receipt consumers."""
    try:
        from .quilt_state import inspect_quilt_state
    except ImportError:
        from quilt_state import inspect_quilt_state

    core_dir = worktree / "helium-chromium"
    core = _git(core_dir, "rev-parse", "HEAD")
    fields = _git(worktree, "ls-tree", "HEAD", "helium-chromium").split()
    if len(fields) < 3 or fields[1] != "commit":
        raise ReceiptError("outer repository has no helium-chromium gitlink")
    configured_root = os.environ.get("HELIUM_DEV_GENERATED_PATCH_ROOT")
    fixture_root = worktree / "patches"
    if configured_root:
        generated_root = Path(configured_root).expanduser().resolve()
    elif (fixture_root / "series.merged").is_file() and not (
        fixture_root / "series"
    ).is_file():
        generated_root = fixture_root
    else:
        raise ReceiptError(
            "generated patch root is not configured; source dev.sh before building"
        )
    report = inspect_quilt_state(source_dir, generated_root)
    if require_complete:
        report.comparison.require_complete()
    else:
        report.comparison.require_valid_prefix()
    return (
        SourceReceipt.create(
            core_commit=core,
            gitlink_commit=fields[2],
            chromium_version=require_expected_chromium_version(core_dir, source_dir),
            patch_series_sha256=report.declared_sha256,
        ),
        report.applied_sha256,
    )


@dataclass(frozen=True)
class BuildReceipt:
    source: SourceReceipt
    replay_receipt_id: str
    execution_receipt_id: str
    lane: str
    status: str
    gn_args_sha256: str
    material_inputs_sha256: str
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
        replay_receipt_id: str,
        execution_receipt_id: str,
        lane: str,
        status: str,
        gn_args_sha256: str,
        applied_series_sha256: str,
        material_inputs_sha256: str = "0" * 64,
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
            "schema": RECEIPT_SCHEMA,
            "source_receipt_id": source.receipt_id,
            "replay_receipt_id": _require_sha256(
                "replay_receipt_id", replay_receipt_id
            ),
            "execution_receipt_id": _require_sha256(
                "execution_receipt_id", execution_receipt_id
            ),
            "lane": lane,
            "status": status,
            "gn_args_sha256": _require_sha256("gn_args_sha256", gn_args_sha256),
            "material_inputs_sha256": _require_sha256(
                "material_inputs_sha256", material_inputs_sha256
            ),
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
            replay_receipt_id=str(payload["replay_receipt_id"]),
            execution_receipt_id=str(payload["execution_receipt_id"]),
            lane=lane,
            status=status,
            gn_args_sha256=str(payload["gn_args_sha256"]),
            material_inputs_sha256=str(payload["material_inputs_sha256"]),
            applied_series_sha256=str(payload["applied_series_sha256"]),
            targets=normalized_targets,
            proof_gates=normalized_gates,
            artifacts=normalized_artifacts,
            receipt_id=receipt_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "source": self.source.to_dict(),
            "replay_receipt_id": self.replay_receipt_id,
            "execution_receipt_id": self.execution_receipt_id,
            "lane": self.lane,
            "status": self.status,
            "gn_args_sha256": self.gn_args_sha256,
            "material_inputs_sha256": self.material_inputs_sha256,
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
