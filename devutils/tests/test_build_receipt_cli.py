"""Integration checks for lane receipts tied to real Git and Quilt state."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "devutils" / "build_receipt_cli.py"


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class BuildReceiptCliTests(unittest.TestCase):
    def test_source_receipt_records_matching_outer_core_and_quilt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core_source = root / "core-source"
            core_source.mkdir()
            git(core_source, "init", "-q")
            (core_source / "README").write_text("core\n", encoding="utf-8")
            git(core_source, "add", "README")
            git(
                core_source,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "core",
            )
            core_commit = git(core_source, "rev-parse", "HEAD")

            worktree = root / "outer"
            worktree.mkdir()
            git(worktree, "init", "-q")
            subprocess.run(
                ["git", "clone", "-q", str(core_source), str(worktree / "helium-chromium")],
                check=True,
            )
            patches = worktree / "patches"
            patches.mkdir()
            (patches / "series.merged").write_text("personal/feature.patch\n", encoding="utf-8")
            (patches / "personal").mkdir()
            (patches / "personal" / "feature.patch").write_text("patch\n", encoding="utf-8")
            git(worktree, "add", "patches")
            git(
                worktree,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{core_commit},helium-chromium",
            )
            git(
                worktree,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "outer",
            )

            build_root = root / "build"
            pc = build_root / "src" / ".pc"
            pc.mkdir(parents=True)
            (pc / ".quilt_patches").write_text(str(patches), encoding="utf-8")
            (pc / ".quilt_series").write_text("series.merged", encoding="utf-8")
            (pc / "applied-patches").write_text("personal/feature.patch\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(CLI),
                    "--worktree",
                    str(worktree),
                    "--build-root",
                    str(build_root),
                    "--lane",
                    "worktree",
                    "source",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(
                (build_root / ".arcium" / "receipts" / "source.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(receipt["core_commit"], core_commit)
            self.assertEqual(receipt["gitlink_commit"], core_commit)
            self.assertEqual(receipt["outer_commit"], git(worktree, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
