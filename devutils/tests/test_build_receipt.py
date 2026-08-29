"""Tests for portable source and build receipts."""

import json
import stat
import tempfile
import unittest
from pathlib import Path

from devutils.build_receipt import (
    BuildReceipt,
    ReceiptError,
    SourceReceipt,
    sha256_file,
    write_receipt_atomic,
)


_OUTER = "1" * 40
_CORE = "2" * 40
_HASH_A = "a" * 64
_HASH_B = "b" * 64


class BuildReceiptTest(unittest.TestCase):
    def source(self) -> SourceReceipt:
        return SourceReceipt.create(
            outer_commit=_OUTER,
            core_commit=_CORE,
            gitlink_commit=_CORE,
            patch_series_sha256=_HASH_A,
        )

    def test_source_receipt_is_deterministic_and_requires_gitlink_match(self) -> None:
        first = self.source()
        second = self.source()
        self.assertEqual(first.receipt_id, second.receipt_id)
        with self.assertRaisesRegex(ReceiptError, "gitlink"):
            SourceReceipt.create(
                outer_commit=_OUTER,
                core_commit=_CORE,
                gitlink_commit="3" * 40,
                patch_series_sha256=_HASH_A,
            )

    def test_build_receipt_contains_no_absolute_artifact_paths(self) -> None:
        receipt = BuildReceipt.create(
            source=self.source(),
            lane="heavy",
            status="complete",
            gn_args_sha256=_HASH_A,
            applied_series_sha256=_HASH_A,
            targets=("//chrome:chrome", "//chrome:chrome", "obj/example.o"),
            proof_gates=("replayed", "compiled", "packaged"),
            artifacts={"Helium Dev.app": _HASH_B},
        )
        self.assertEqual(receipt.targets, ("//chrome:chrome", "obj/example.o"))
        self.assertEqual(receipt.artifacts["Helium Dev.app"], _HASH_B)
        with self.assertRaisesRegex(ReceiptError, "unsafe artifact"):
            BuildReceipt.create(
                source=self.source(),
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
                lane="local",
                status="incomplete",
                gn_args_sha256=_HASH_A,
                applied_series_sha256=_HASH_A,
                proof_gates=("magic",),
            )
        with self.assertRaisesRegex(ReceiptError, "SHA-256"):
            BuildReceipt.create(
                source=self.source(),
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
            self.assertEqual(payload["outer_commit"], _OUTER)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_file_hashing_streams_artifact_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"arcium")
            self.assertEqual(len(sha256_file(path)), 64)


if __name__ == "__main__":
    unittest.main()
