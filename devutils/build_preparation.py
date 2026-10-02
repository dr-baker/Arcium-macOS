#!/usr/bin/env python3
"""Prove that selected recipes were consumed into the current build inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import sys

from build_receipt import (
    HARNESS_SCRIPT_ENV,
    ACQUISITION_TARGET_ENV,
    acquisition_script,
    ReceiptError,
    _declared_inputs_sha256,
    _resource_manifest,
    material_inputs_at_entry,
    sha256_file,
    validate_harness_script,
)

from replay_contract import ReplayError, require_current_replay_proof


_REPAIR = {
    "acquisition": "prepare a new unused build lane with he presetup; preserve this lane",
    "resources": "he resources",
    "version": "he version",
    "gn-defaults": "he configure --refresh-defaults (deliberately rewrites args.gn)",
    "test-assets": "he configure",
    "configured": "he configure (preserves args.gn)",
}


def _receipt_path(build_root: Path, stage: str) -> Path:
    return build_root / ".arcium" / "receipts" / f"prepared-{stage}.json"


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _resource_entries(worktree: Path) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    core = worktree / "helium-chromium"
    generated = _resource_manifest(core, "generate_resources.txt", {2, 3})
    copied = _resource_manifest(core, "helium_resources.txt", {2})
    platform = _resource_manifest(worktree, "platform_resources.txt", {2})
    return generated, copied, platform


def _producer_digest() -> str:
    helper_root = Path(__file__).resolve().parents[1]
    script = Path(os.environ.get(HARNESS_SCRIPT_ENV, str(helper_root / "dev.sh"))).expanduser().resolve()
    validate_harness_script(script)
    return _json_digest({
        "shell": sha256_file(script),
        "preparation-helper": sha256_file(Path(__file__)),
        "receipt-helper": sha256_file(helper_root / "devutils/build_receipt.py"),
    })


def acquisition_target() -> str:
    target = os.environ.get(ACQUISITION_TARGET_ENV, platform.machine())
    if target not in {"arm64", "x86_64"}:
        raise ReceiptError(f"unsupported acquisition architecture: {target}")
    return target


def input_digest(worktree: Path, build_root: Path, stage: str) -> str:
    """Hash only inputs consumed by this preparation stage and its producer."""
    core = worktree / "helium-chromium"
    inputs: dict[str, str] = {}
    if stage == "acquisition":
        inputs["producer"] = sha256_file(acquisition_script())
        inputs["target-architecture"] = acquisition_target()
        inputs["core"] = _declared_inputs_sha256(core, (
            "utils/clone.py", "utils/downloads.py", "utils/_common.py",
            "utils/_extraction.py", "utils/third_party/schema.py",
            "utils/depot_tools.patch", "utils/gsutil.patch", "utils/prune_binaries.py",
            "downloads.ini", "deps.ini", "pruning.list", "chromium_version.txt",
        ))
        inputs["platform"] = _declared_inputs_sha256(worktree, (
            "retrieve_and_unpack_resource.sh", "devutils/setup_python.sh",
            "requirements-dev.txt", "downloads.ini",
        ))
        return _json_digest(inputs)
    acquisition = require_stage(worktree, build_root, "acquisition")
    inputs["producer"] = _producer_digest()
    if stage == "test-assets":
        from prepare_test_assets import recipe_inputs
        inputs["acquisition"] = acquisition["receipt_id"]
        inputs["source-mode"] = acquisition["acquisition"]["source_mode"]
        inputs["recipe"] = _json_digest(recipe_inputs(build_root / "src"))
    elif stage == "resources":
        generated, copied, platform_copies = _resource_entries(worktree)
        outputs = {entry[-1] for entry in generated}
        raw = {entry[0] for entry in generated}
        raw.update(entry[0] for entry in copied if entry[0] not in outputs)
        inputs["core"] = _declared_inputs_sha256(core, (
            "utils/generate_resources.py", "utils/replace_resources.py",
            "resources/generate_resources.txt", "resources/helium_resources.txt",
            *("resources/" + name for name in sorted(raw)),
        ))
        inputs["platform"] = _declared_inputs_sha256(worktree, (
            "resources/platform_resources.txt",
            *("resources/" + name for name in sorted({entry[0] for entry in platform_copies})),
        ))
    elif stage == "version":
        inputs["core"] = _declared_inputs_sha256(core, (
            "utils/helium_version.py", "version.txt", "chromium_version.txt", "revision.txt",
        ))
        inputs["platform"] = _declared_inputs_sha256(worktree, ("revision.txt",))
        # Chromium fields are producer inputs; Helium fields are generated.
        version = build_root / "src/chrome/VERSION"
        try:
            fields = [line for line in version.read_text().splitlines() if not line.startswith("HELIUM_")]
        except (OSError, UnicodeError) as error:
            raise ReceiptError("could not read Chromium version inputs") from error
        inputs["chromium-fields"] = _json_digest(fields)
    elif stage == "gn-defaults":
        inputs["core"] = _declared_inputs_sha256(core, ("flags.gn",))
        inputs["platform"] = _declared_inputs_sha256(worktree, ("flags.macos.gn",))
    elif stage == "configured":
        if acquisition["acquisition"]["source_mode"] == "full":
            inputs["test-assets"] = require_stage(worktree, build_root, "test-assets")["receipt_id"]
        defaults = require_stage(worktree, build_root, "gn-defaults", check_outputs=False)
        inputs["default-fragment-lineage"] = defaults["receipt_id"]
        out = build_root / "src/out/Default"
        inputs["args"] = sha256_file(out / "args.gn")
        inputs["gn"] = sha256_file(out / "gn")
        inputs["setup-dawn"] = sha256_file(worktree / "devutils/setup_dawn_go.sh")
        inputs["replay"] = require_current_replay_proof(worktree, build_root / "src").receipt_id
        inputs["version-output"] = sha256_file(build_root / "src/chrome/VERSION")
    else:
        raise ReceiptError(f"unknown preparation stage: {stage}")
    return _json_digest(inputs)


def output_digests(worktree: Path, build_root: Path, stage: str) -> dict[str, str]:
    paths: dict[str, Path] = {}
    source = build_root / "src"
    out = source / "out/Default"
    if stage == "acquisition":
        # This is immutable recipe lineage, not a hash of the mutable source
        # tree or downloaded toolchain. Existing acquisition verifies downloads.
        marker = build_root / ".arcium/source-mode"
        try:
            mode = marker.read_text().strip()
        except (OSError, UnicodeError) as error:
            raise ReceiptError("acquisition source mode marker is missing") from error
        requested = os.environ.get("HELIUM_DEV_SOURCE_MODE")
        if mode not in {"full", "lite"} or requested not in {None, "full", "lite"} or (requested == "full" and mode != "full"):
            raise ReceiptError("acquisition source mode differs; prepare a new unused build lane")
        paths["resolved-source-mode"] = marker
        target_marker = build_root / ".arcium/acquisition-target"
        try:
            if target_marker.read_text().strip() != acquisition_target():
                raise ReceiptError("acquisition architecture differs; prepare a new unused build lane")
        except (OSError, UnicodeError) as error:
            raise ReceiptError("acquisition target marker is missing") from error
        paths["target-architecture"] = target_marker
    elif stage == "test-assets":
        from prepare_test_assets import output_digests as test_asset_outputs
        return test_asset_outputs(source)
    elif stage == "resources":
        generated, copied, platform_copies = _resource_entries(worktree)
        for entry in generated:
            paths["core-generated/" + entry[-1]] = worktree / "helium-chromium/resources" / entry[-1]
        for entry in (*copied, *platform_copies):
            destination = Path(entry[1])
            if destination.is_absolute() or ".." in destination.parts:
                raise ReceiptError("resource destination escapes selected Chromium source")
            paths["chromium/" + destination.as_posix()] = source / destination
    elif stage == "version":
        paths["chrome/VERSION"] = source / "chrome/VERSION"
    elif stage == "gn-defaults":
        paths["args.gn"] = out / "args.gn"
    elif stage == "configured":
        paths = {path.relative_to(out).as_posix(): path for path in out.rglob("*.ninja")}
        if "build.ninja" not in paths:
            raise ReceiptError("configured build graph is missing build.ninja")
    else:
        raise ReceiptError(f"unknown preparation stage: {stage}")
    for path in paths.values():
        if path.is_symlink() or not path.is_file():
            raise ReceiptError(f"prepared output is missing or not a regular file: {path}")
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def record_stage(worktree: Path, build_root: Path, stage: str, expected: str) -> dict[str, object]:
    current = input_digest(worktree, build_root, stage)
    if current != expected:
        raise ReceiptError(f"{stage} inputs changed during preparation; retry {_REPAIR[stage]}")
    payload: dict[str, object] = {"schema": 1, "stage": stage, "inputs_sha256": current,
                                 "outputs": output_digests(worktree, build_root, stage)}
    if stage == "acquisition":
        payload["acquisition"] = {
            "source_mode": (build_root / ".arcium/source-mode").read_text().strip(),
            "target_cpu": acquisition_target(),
        }
    payload["receipt_id"] = _json_digest(payload)
    destination = _receipt_path(build_root, stage)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f".tmp.{os.getpid()}")
    try:
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def require_stage(worktree: Path, build_root: Path, stage: str, *, check_outputs: bool = True) -> dict[str, object]:
    if stage == "configured":
        # Preserve the explicit default-refresh repair when lineage is stale.
        require_stage(worktree, build_root, "gn-defaults", check_outputs=False)
    try:
        payload = json.loads(_receipt_path(build_root, stage).read_text())
        identity = payload.pop("receipt_id")
        if payload.get("schema") != 1 or payload.get("stage") != stage or _json_digest(payload) != identity:
            raise ValueError("invalid preparation receipt")
        payload["receipt_id"] = identity
        if stage == "acquisition" and payload.get("acquisition") != {
            "source_mode": (build_root / ".arcium/source-mode").read_text().strip(),
            "target_cpu": acquisition_target(),
        }:
            raise ValueError("acquisition identity changed")
        if payload["inputs_sha256"] != input_digest(worktree, build_root, stage):
            raise ValueError("preparation inputs changed")
        if check_outputs and payload["outputs"] != output_digests(worktree, build_root, stage):
            raise ValueError("prepared output membership or bytes changed")
        return payload
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ReceiptError(f"{stage} preparation is missing or stale; run {_REPAIR[stage]}") from error


def prepared_build_digest(worktree: Path, build_root: Path) -> str:
    stages = ["acquisition", "resources", "version", "configured"]
    if require_stage(worktree, build_root, "acquisition")["acquisition"]["source_mode"] == "full":
        stages.append("test-assets")
    return _json_digest({stage: require_stage(worktree, build_root, stage)["receipt_id"]
                         for stage in stages})


def invalidate_acquisition(build_root: Path) -> None:
    """Invalidate old lane proof before source replacement or reset begins."""
    receipts = build_root / ".arcium/receipts"
    paths = {receipts / "replay.json", receipts / "execution.json",
             build_root / ".arcium/source-mode", build_root / ".arcium/acquisition-target"}
    paths.update(receipts.glob("prepared-*.json"))
    paths.update(receipts.glob("build*.json"))
    for path in sorted(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise ReceiptError(f"could not invalidate old acquisition proof: {path.name}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("operation", choices=("begin", "finish", "require", "invalidate"))
    parser.add_argument("stage", choices=tuple(_REPAIR))
    parser.add_argument("expected", nargs="?")
    arguments = parser.parse_args(argv)
    worktree = arguments.worktree.expanduser().resolve()
    build_root = arguments.build_root.expanduser().resolve()
    try:
        material_inputs_at_entry(worktree)
        if arguments.operation == "invalidate":
            if arguments.stage != "acquisition":
                raise ReceiptError("only acquisition invalidation is supported")
            invalidate_acquisition(build_root)
        elif arguments.operation == "begin":
            print(input_digest(worktree, build_root, arguments.stage))
        elif arguments.operation == "finish":
            if arguments.expected is None:
                raise ReceiptError("finish requires the preparation entry digest")
            record_stage(worktree, build_root, arguments.stage, arguments.expected)
        else:
            require_stage(worktree, build_root, arguments.stage,
                          check_outputs=arguments.stage != "gn-defaults")
    except (ReceiptError, ReplayError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
