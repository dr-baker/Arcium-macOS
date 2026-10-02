"""Tests for portable source and build receipts."""

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devutils.build_receipt import (
    BuildReceipt,
    CORE_PREPARATION_INPUTS,
    EXECUTOR_BUILD_INPUTS,
    MATERIAL_BUILD_INPUTS,
    MATERIAL_INPUTS_ENV,
    ReceiptError,
    SourceReceipt,
    material_inputs_at_entry,
    material_inputs_sha256,
    sha256_file,
    write_receipt_atomic,
)


_CORE = "2" * 40
_HASH_A = "a" * 64
_HASH_B = "b" * 64


def material_fixture(root: Path) -> None:
    """Create selected inputs while hashing the real canonical executors."""
    for declared in MATERIAL_BUILD_INPUTS:
        path = root / declared
        if declared == "resources":
            path.mkdir(parents=True, exist_ok=True)
            (path / "icon.txt").write_text("icon\n", encoding="utf-8")
            (path / "platform_resources.txt").write_text("", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(declared + "\n", encoding="utf-8")
    for declared in CORE_PREPARATION_INPUTS:
        path = root / "helium-chromium" / declared
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "" if declared.startswith("resources/") else declared + "\n"
        path.write_text(content, encoding="utf-8")


class BuildReceiptTest(unittest.TestCase):
    def source(self) -> SourceReceipt:
        return SourceReceipt.create(
            core_commit=_CORE,
            gitlink_commit=_CORE,
            chromium_version="151.0.7922.71",
            patch_series_sha256=_HASH_A,
        )

    def test_source_receipt_is_deterministic_and_requires_gitlink_match(self) -> None:
        first = self.source()
        second = self.source()
        self.assertEqual(first.receipt_id, second.receipt_id)
        with self.assertRaisesRegex(ReceiptError, "gitlink"):
            SourceReceipt.create(
                core_commit=_CORE,
                gitlink_commit="3" * 40,
                chromium_version="151.0.7922.71",
                patch_series_sha256=_HASH_A,
            )

    def test_build_receipt_contains_no_absolute_artifact_paths(self) -> None:
        receipt = BuildReceipt.create(
            source=self.source(),
            replay_receipt_id=_HASH_B,
            execution_receipt_id=_HASH_A,
            lane="heavy",
            status="complete",
            gn_args_sha256=_HASH_A,
            applied_series_sha256=_HASH_A,
            targets=("//chrome:chrome", "//chrome:chrome", "obj/example.o"),
            proof_gates=("replayed", "compiled", "packaged"),
            artifacts={"Helium Dev.app": _HASH_B},
        )
        self.assertEqual(receipt.targets, ("//chrome:chrome", "obj/example.o"))
        self.assertEqual(receipt.to_dict()["replay_receipt_id"], _HASH_B)
        self.assertEqual(receipt.to_dict()["execution_receipt_id"], _HASH_A)
        self.assertEqual(receipt.to_dict()["schema"], 3)
        self.assertEqual(receipt.artifacts["Helium Dev.app"], _HASH_B)
        with self.assertRaisesRegex(ReceiptError, "unsafe artifact"):
            BuildReceipt.create(
                source=self.source(),
                replay_receipt_id=_HASH_B,
                execution_receipt_id=_HASH_A,
                lane="local",
                status="complete",
                gn_args_sha256=_HASH_A,
                applied_series_sha256=_HASH_A,
                artifacts={"/tmp/app": _HASH_B},
            )

    def test_unsafe_build_targets_are_rejected(self) -> None:
        for target in ("/tmp/output", "../output", "target with space", "-C"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ReceiptError, "generated-build"):
                    BuildReceipt.create(
                        source=self.source(),
                        replay_receipt_id=_HASH_B,
                        execution_receipt_id=_HASH_A,
                        lane="local",
                        status="incomplete",
                        gn_args_sha256=_HASH_A,
                        applied_series_sha256=_HASH_A,
                        targets=(target,),
                    )

    def test_unknown_proof_gate_and_invalid_digest_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReceiptError, "unknown proof"):
            BuildReceipt.create(
                source=self.source(),
                replay_receipt_id=_HASH_B,
                execution_receipt_id=_HASH_A,
                lane="local",
                status="incomplete",
                gn_args_sha256=_HASH_A,
                applied_series_sha256=_HASH_A,
                proof_gates=("magic",),
            )
        with self.assertRaisesRegex(ReceiptError, "SHA-256"):
            BuildReceipt.create(
                source=self.source(),
                replay_receipt_id=_HASH_B,
                execution_receipt_id=_HASH_A,
                lane="local",
                status="incomplete",
                gn_args_sha256="short",
                applied_series_sha256=_HASH_A,
            )

    def test_atomic_receipt_is_private_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipts" / "source.json"
            write_receipt_atomic(path, self.source())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["core_commit"], _CORE)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_file_hashing_streams_artifact_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"arcium")
            self.assertEqual(len(sha256_file(path)), 64)

    def test_material_inputs_ignore_docs_and_tooling_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            material_fixture(root)
            before = material_inputs_sha256(root)
            (root / "docs").mkdir()
            (root / "docs" / "building.md").write_text("docs\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("charter\n", encoding="utf-8")
            (root / "devutils" / "tests").mkdir()
            (root / "devutils" / "tests" / "test_only.py").write_text(
                "test\n", encoding="utf-8"
            )
            self.assertEqual(before, material_inputs_sha256(root))

    def test_material_build_input_change_invalidates_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            material_fixture(root)
            before = material_inputs_sha256(root)
            (root / "resources" / "icon.txt").write_text("changed\n", encoding="utf-8")
            self.assertNotEqual(before, material_inputs_sha256(root))
            before = material_inputs_sha256(root)
            (root / "devutils/replay_timestamps.py").write_text("changed helper\n")
            self.assertNotEqual(before, material_inputs_sha256(root))
            before = material_inputs_sha256(root)
            (root / "devutils/setup_dawn_go.sh").write_text("changed selected setup helper\n")
            self.assertNotEqual(before, material_inputs_sha256(root))

            executor = root / "executor"
            entitlements = (
                "entitlements/app-entitlements.plist",
                "entitlements/helper-entitlements.plist",
                "entitlements/helper-gpu-entitlements.plist",
                "entitlements/helper-renderer-entitlements.plist",
            )
            for relative in (*EXECUTOR_BUILD_INPUTS, *entitlements):
                path = executor / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative + "\n")
            with patch("devutils.build_receipt.__file__", str(executor / "devutils/build_receipt.py")):
                for relative in (*entitlements, "devutils/build_diagnostics.py"):
                    with self.subTest(executor_input=relative):
                        before = material_inputs_sha256(root)
                        path = executor / relative
                        path.write_text(path.read_text() + "changed executor input\n")
                        self.assertNotEqual(before, material_inputs_sha256(root))

    def test_external_executor_accepts_source_without_diagnostics_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            material_fixture(root)
            diagnostics = root / "devutils/build_diagnostics.py"
            diagnostics.unlink(missing_ok=True)
            before = material_inputs_at_entry(root)
            self.assertEqual(len(before), 64)
            # This file is not imported by the external executing harness.
            diagnostics.write_text("unused selected copy\n", encoding="utf-8")
            self.assertEqual(before, material_inputs_at_entry(root))
            setup = root / "devutils/setup_python.sh"
            setup.unlink()
            with self.assertRaisesRegex(ReceiptError, "missing: devutils/setup_python.sh"):
                material_inputs_at_entry(root)

    def test_actual_executor_diagnostics_remain_required_and_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "selected"
            material_fixture(selected)
            (selected / "devutils/build_diagnostics.py").unlink(missing_ok=True)
            before = material_inputs_at_entry(selected)
            executor = root / "executor"
            actual_executor = Path(__file__).resolve().parents[2]
            for relative in EXECUTOR_BUILD_INPUTS:
                destination = executor / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(actual_executor / relative, destination)
            with patch("devutils.build_receipt.__file__", str(executor / "devutils/build_receipt.py")):
                self.assertEqual(before, material_inputs_at_entry(selected))
                diagnostics = executor / "devutils/build_diagnostics.py"
                original = diagnostics.read_bytes()
                diagnostics.write_bytes(original + b"changed actual executor\n")
                self.assertNotEqual(before, material_inputs_at_entry(selected))
                with patch.dict(os.environ, {MATERIAL_INPUTS_ENV: before}):
                    with self.assertRaisesRegex(ReceiptError, "changed after transaction entry"):
                        material_inputs_at_entry(selected)
                diagnostics.write_bytes(original)
                self.assertEqual(before, material_inputs_at_entry(selected))
                diagnostics.unlink()
                with self.assertRaisesRegex(ReceiptError, "missing: devutils/build_diagnostics.py"):
                    material_inputs_at_entry(selected)


if __name__ == "__main__":
    unittest.main()
