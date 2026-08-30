"""Tests for the explicit full-replay proof contract."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay_contract import (
    ReplayError,
    _write_proof,
    replay,
    receipt_path,
    require_current_replay_proof,
)


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class ReplayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        patched_tree = patch(
            "replay_contract._patched_tree_sha256", return_value="c" * 64
        )
        self.addCleanup(patched_tree.stop)
        patched_tree.start()

    def fixture(self) -> tuple[Path, Path]:
        temporary = Path(tempfile.mkdtemp(prefix="replay-contract-test-"))
        self.addCleanup(lambda: shutil.rmtree(temporary, ignore_errors=True))
        core = temporary / "core"
        core.mkdir()
        git(core, "init", "-q")
        (core / "README").write_text("core\n", encoding="utf-8")
        (core / "chromium_version.txt").write_text(
            "151.0.7922.71\n", encoding="utf-8"
        )
        git(core, "add", "README", "chromium_version.txt")
        git(core, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "core")
        core_commit = git(core, "rev-parse", "HEAD")

        outer = temporary / "outer"
        outer.mkdir()
        git(outer, "init", "-q")
        (outer / "helium-chromium").mkdir()
        git(outer / "helium-chromium", "init", "-q")
        git(outer / "helium-chromium", "remote", "add", "origin", str(core))
        git(outer / "helium-chromium", "fetch", "-q", "origin", "HEAD")
        git(outer / "helium-chromium", "reset", "-q", "--hard", "FETCH_HEAD")
        patches = outer / "patches" / "personal"
        patches.mkdir(parents=True)
        (outer / "patches" / "series.merged").write_text("personal/feature.patch\n", encoding="utf-8")
        (patches / "feature.patch").write_text("patch bytes\n", encoding="utf-8")
        git(outer, "add", "patches")
        git(outer, "update-index", "--add", "--cacheinfo", f"160000,{core_commit},helium-chromium")
        git(outer, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "outer")

        source = temporary / "build" / "src"
        (source / ".pc").mkdir(parents=True)
        (source / "chrome").mkdir()
        (source / "chrome" / "VERSION").write_text(
            "MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=71\n", encoding="utf-8"
        )
        (source / ".pc" / ".quilt_patches").write_text(str(outer / "patches"), encoding="utf-8")
        (source / ".pc" / ".quilt_series").write_text("series.merged\n", encoding="utf-8")
        (source / ".pc" / "applied-patches").write_text("personal/feature.patch\n", encoding="utf-8")
        return outer, source

    def test_missing_and_content_changed_proofs_fail_closed(self) -> None:
        outer, source = self.fixture()
        _write_proof(outer, source)
        self.assertIsNotNone(require_current_replay_proof(outer, source))

        patch = outer / "patches" / "personal" / "feature.patch"
        patch.write_text("new patch bytes\n", encoding="utf-8")
        with self.assertRaisesRegex(ReplayError, "stale"):
            require_current_replay_proof(outer, source)

        receipt = receipt_path(source.parent)
        receipt.unlink()
        with self.assertRaisesRegex(ReplayError, "no current"):
            require_current_replay_proof(outer, source)

    def test_docs_and_tooling_only_changes_do_not_stale_replay_proof(self) -> None:
        outer, source = self.fixture()
        _write_proof(outer, source)
        (outer / "docs").mkdir()
        (outer / "docs" / "building.md").write_text("updated\n", encoding="utf-8")
        (outer / "devutils").mkdir()
        (outer / "devutils" / "test_helper.py").write_text("updated\n", encoding="utf-8")
        git(outer, "add", "docs", "devutils")
        git(
            outer,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "docs and tooling",
        )
        self.assertIsNotNone(require_current_replay_proof(outer, source))

    def test_old_schema_receipt_is_rejected(self) -> None:
        outer, source = self.fixture()
        _write_proof(outer, source)
        path = receipt_path(source.parent)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ReplayError, "unsupported schema"):
            require_current_replay_proof(outer, source)

    def test_failed_push_invalidates_prior_proof(self) -> None:
        outer, source = self.fixture()
        _write_proof(outer, source)
        path = receipt_path(source.parent)
        self.assertTrue(path.is_file())

        results = (
            subprocess.CompletedProcess(["quilt", "pop", "-a"], 0),
            subprocess.CompletedProcess(["quilt", "push", "-a"], 1),
        )
        with patch("replay_contract._run_quilt", side_effect=results) as run:
            with self.assertRaisesRegex(ReplayError, "push -a failed"):
                replay(outer, source)

        self.assertFalse(path.exists())
        self.assertEqual(run.call_count, 2)
        for index, call in enumerate(run.call_args_list):
            expected = ("pop", "-a") if index == 0 else ("push", "-a")
            self.assertEqual(call.args[2:], expected)
            self.assertIn("--fuzz=0", call.args[1]["QUILT_PATCH_OPTS"])

    def test_replay_rejects_stale_generated_core_copy_before_quilt_mutation(self) -> None:
        outer, source = self.fixture()
        core_patches = outer / "helium-chromium" / "patches"
        core_patches.mkdir()
        (core_patches / "series").write_text(
            "personal/core.patch\n", encoding="utf-8"
        )
        (core_patches / "personal").mkdir()
        (core_patches / "personal" / "core.patch").write_text(
            "authoritative core bytes\n", encoding="utf-8"
        )
        generated_patches = outer / "patches" / "personal"
        (generated_patches / "core.patch").write_text(
            "stale generated bytes\n", encoding="utf-8"
        )
        (outer / "patches" / "series.merged").write_text(
            "personal/core.patch\npersonal/feature.patch\n", encoding="utf-8"
        )
        (source / ".pc" / "applied-patches").write_text("", encoding="utf-8")

        with patch("replay_contract._run_quilt") as run:
            with self.assertRaisesRegex(ReplayError, "stale.*core.patch"):
                replay(outer, source)

        run.assert_not_called()

    def test_replay_recovers_from_fully_popped_missing_ledger(self) -> None:
        outer, source = self.fixture()
        applied = source / ".pc" / "applied-patches"
        applied.unlink()

        def run_quilt(
            _source: Path, _environment: dict[str, str], *arguments: str
        ) -> subprocess.CompletedProcess[bytes]:
            if arguments == ("push", "-a"):
                applied.write_text("personal/feature.patch\n", encoding="utf-8")
            return subprocess.CompletedProcess(["quilt", *arguments], 0)

        with patch("replay_contract._run_quilt", side_effect=run_quilt):
            receipt = replay(outer, source)

        self.assertEqual(receipt.series_name, "series.merged")
        self.assertTrue(receipt_path(source.parent).is_file())


if __name__ == "__main__":
    unittest.main()
