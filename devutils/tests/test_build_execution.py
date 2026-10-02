"""Tests for runnable Chromium artifact execution receipts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_execution import (  # noqa: E402
    ExecutionError,
    ExecutionReceipt,
    component_runtime_libraries,
    record_execution,
    require_current_execution,
    tree_sha256,
)
from build_receipt import SourceReceipt, material_inputs_sha256  # noqa: E402
from build_preparation import acquisition_target, input_digest, prepared_build_digest, record_stage
from devutils.tests.test_build_receipt import material_fixture
from replay_contract import ReplayReceipt  # noqa: E402


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


class BuildExecutionTests(unittest.TestCase):
    def replay(self) -> ReplayReceipt:
        source = SourceReceipt.create(
            core_commit="2" * 40,
            gitlink_commit="2" * 40,
            chromium_version="151.0.7922.71",
            patch_series_sha256=_HASH_A,
        )
        return ReplayReceipt.create(
            source=source,
            applied_series_sha256=_HASH_B,
            patched_tree_sha256=_HASH_C,
            series_name="series.merged",
        )

    def artifacts(self, build_root: Path) -> None:
        material_fixture(build_root.parent / "worktree")
        out = build_root / "src" / "out" / "Default"
        executable = out / "Helium.app" / "Contents" / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"browser")
        (out / "libchrome_dll.dylib").write_bytes(b"component")
        (out / "libtest_gpu.dylib").write_bytes(b"gpu component")
        (out / "args.gn").write_text("  is_component_build\t= true  # component fixture\n", encoding="utf-8")

    def test_receipt_is_deterministic_and_binds_replay_and_lane(self) -> None:
        replay = self.replay()
        first = ExecutionReceipt.create(
            replay=replay,
            lane="heavy",
            action="build-full",
            targets=("chrome", "chrome"),
            gn_args_sha256=_HASH_A,
            artifacts={"Helium.app": _HASH_B},
        )
        second = ExecutionReceipt.create(
            replay=replay,
            lane="heavy",
            action="build-full",
            targets=("chrome",),
            gn_args_sha256=_HASH_A,
            artifacts={"Helium.app": _HASH_B},
        )
        self.assertEqual(first, second)
        self.assertEqual(first.replay_receipt_id, replay.receipt_id)
        self.assertEqual(first.to_dict()["schema"], 3)

    def test_tree_digest_changes_when_artifact_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            root.mkdir()
            artifact = root / "Contents"
            artifact.write_bytes(b"first")
            before = tree_sha256(root)
            artifact.write_bytes(b"second")
            self.assertNotEqual(before, tree_sha256(root))

    def test_tree_digest_rejects_symlinked_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "real-app"
            target.mkdir()
            link = root / "Helium.app"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ExecutionError, "must not be a symlink"):
                tree_sha256(link)

    def test_recorded_execution_rejects_mutated_artifact_and_wrong_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            build_root = Path(temporary) / "build"
            self.artifacts(build_root)
            replay = self.replay()
            with patch(
                "build_execution.require_current_replay_proof",
                return_value=replay,
            ), patch("build_preparation.require_current_replay_proof", return_value=replay):
                worktree = Path(temporary) / "worktree"
                metadata = build_root / ".arcium"
                metadata.mkdir()
                (metadata / "source-mode").write_text("lite\n", encoding="utf-8")
                (metadata / "acquisition-target").write_text(acquisition_target() + "\n", encoding="utf-8")
                version = build_root / "src/chrome/VERSION"
                version.parent.mkdir(parents=True)
                version.write_text("MAJOR=151\n", encoding="utf-8")
                out = build_root / "src/out/Default"
                (out / "gn").write_bytes(b"fake gn")
                (out / "build.ninja").write_text("graph\n", encoding="utf-8")
                for stage in ("acquisition", "resources", "version", "gn-defaults", "configured"):
                    record_stage(worktree, build_root, stage, input_digest(worktree, build_root, stage))
                preparation_at_entry = prepared_build_digest(worktree, build_root)
                record_execution(
                    worktree,
                    build_root,
                    lane="heavy",
                    action="build-full",
                    targets=("chrome",),
                    material_inputs_at_entry=material_inputs_sha256(worktree),
                    prepared_inputs_at_entry=preparation_at_entry,
                )
                self.assertIsNotNone(
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="heavy"
                    )
                )
                with self.assertRaisesRegex(ExecutionError, "different lane"):
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="local"
                    )
                dev_script = Path(temporary) / "worktree" / "dev.sh"
                original_script = dev_script.read_bytes()
                dev_script.write_text("changed\n", encoding="utf-8")
                with self.assertRaisesRegex(ExecutionError, "changed"):
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="heavy"
                    )
                # Restore the input so the next rejection must concern the
                # runtime library, rather than the earlier source mutation.
                dev_script.write_bytes(original_script)
                component = (
                    build_root / "src" / "out" / "Default" / "libtest_gpu.dylib"
                )
                component.write_bytes(b"changed")
                with self.assertRaisesRegex(ExecutionError, "changed"):
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="heavy"
                    )


    def test_component_expression_cannot_omit_runtime_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            (out / "libchrome_dll.dylib").write_bytes(b"runtime")
            for expression in ("is_component_build = is_debug", "is_component_build = true\nis_component_build = false"):
                with self.subTest(expression=expression):
                    (out / "args.gn").write_text(expression + "\n")
                    with self.assertRaises(ExecutionError):
                        component_runtime_libraries(out)


if __name__ == "__main__":
    unittest.main()
