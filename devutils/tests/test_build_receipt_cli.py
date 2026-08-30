"""Integration checks for lane receipts tied to real Git and Quilt state."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "devutils" / "build_receipt_cli.py"
sys.path.insert(0, str(ROOT / "devutils"))
from build_receipt import ReceiptError  # noqa: E402
from build_receipt_cli import _publish_packaged_build  # noqa: E402


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class BuildReceiptCliTests(unittest.TestCase):
    def test_package_publication_requires_same_transaction_digest(self) -> None:
        receipt = MagicMock()
        receipt.artifacts = {"Helium Dev.app": "a" * 64}
        with patch(
            "build_receipt_cli._current_packaged_receipt", return_value=receipt
        ), patch("build_receipt_cli.write_receipt_atomic") as write:
            with self.assertRaisesRegex(ReceiptError, "changed"):
                _publish_packaged_build(
                    Path("/worktree"),
                    Path("/build"),
                    "heavy",
                    expected_package_sha256="b" * 64,
                )
        write.assert_not_called()

    def test_source_receipt_records_matching_outer_core_and_quilt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core_source = root / "core-source"
            core_source.mkdir()
            git(core_source, "init", "-q")
            (core_source / "README").write_text("core\n", encoding="utf-8")
            (core_source / "chromium_version.txt").write_text(
                "151.0.7922.71\n", encoding="utf-8"
            )
            git(core_source, "add", "README", "chromium_version.txt")
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
            (build_root / "src" / "chrome").mkdir()
            (build_root / "src" / "chrome" / "VERSION").write_text(
                "MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=71\n", encoding="utf-8"
            )
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

            out = build_root / "src" / "out" / "Default"
            executable = out / "Helium Dev.app" / "Contents" / "MacOS" / "Helium"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"browser")
            (out / "libchrome_dll.dylib").write_bytes(b"component")
            (out / "args.gn").write_text("is_component_build = true\n", encoding="utf-8")
            packaged = subprocess.run(
                [
                    "python3",
                    str(CLI),
                    "--worktree",
                    str(worktree),
                    "--build-root",
                    str(build_root),
                    "--lane",
                    "worktree",
                    "packaged-build",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(packaged.returncode, 2)
            self.assertIn("invalid choice", packaged.stderr)
            self.assertFalse((build_root / ".arcium" / "receipts" / "build.json").exists())


if __name__ == "__main__":
    unittest.main()
