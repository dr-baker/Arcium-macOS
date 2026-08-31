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
    record_execution,
    require_current_execution,
    tree_sha256,
)
from build_receipt import MATERIAL_BUILD_INPUTS, SourceReceipt  # noqa: E402
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
        for declared in MATERIAL_BUILD_INPUTS:
            path = build_root.parent / "worktree" / declared
            if declared == "resources":
                path.mkdir(parents=True, exist_ok=True)
                (path / "icon.txt").write_text("icon\n", encoding="utf-8")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(declared + "\n", encoding="utf-8")
        out = build_root / "src" / "out" / "Default"
        executable = out / "Helium.app" / "Contents" / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"browser")
        (out / "libchrome_dll.dylib").write_bytes(b"component")
        (out / "args.gn").write_text("is_component_build = true\n", encoding="utf-8")

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
            ):
                record_execution(
                    Path(temporary) / "worktree",
                    build_root,
                    lane="heavy",
                    action="build-full",
                    targets=("chrome",),
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
                (Path(temporary) / "worktree" / "dev.sh").write_text(
                    "changed\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ExecutionError, "changed"):
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="heavy"
                    )
                component = build_root / "src" / "out" / "Default" / "libchrome_dll.dylib"
                component.write_bytes(b"changed")
                with self.assertRaisesRegex(ExecutionError, "changed"):
                    require_current_execution(
                        Path(temporary) / "worktree", build_root, lane="heavy"
                    )


if __name__ == "__main__":
    unittest.main()
