"""Tests for source whitespace checks across Git and Quilt source lanes."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from devutils.check_source import SourceCheckError, check_source


class SourceCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "src"
        self.source.mkdir()
        (self.source / ".pc").mkdir()

    def write_quilt_source(self, before: str, after: str) -> None:
        patch = "personal/change.patch"
        backup = self.source / ".pc" / patch
        backup.mkdir(parents=True)
        (backup / "chrome" / "example.cc").parent.mkdir(parents=True)
        (backup / "chrome" / "example.cc").write_text(before, encoding="utf-8")
        (self.source / "chrome").mkdir()
        (self.source / "chrome" / "example.cc").write_text(after, encoding="utf-8")
        (self.source / ".pc" / "applied-patches").write_text(
            patch + "\n", encoding="utf-8"
        )

    def test_non_git_extracted_source_passes_for_clean_patch_changes(self) -> None:
        self.write_quilt_source("old\n", "new\n")
        check_source(self.source)

    def test_non_git_extracted_source_rejects_trailing_whitespace(self) -> None:
        self.write_quilt_source("old\n", "new \n")
        with self.assertRaisesRegex(SourceCheckError, "trailing whitespace"):
            check_source(self.source)

    def test_non_git_extracted_source_rejects_conflict_markers(self) -> None:
        self.write_quilt_source(
            "old\n", "<<<<<<< ours\nnew\n=======\nother\n>>>>>>> theirs\n"
        )
        with self.assertRaisesRegex(SourceCheckError, "leftover conflict marker"):
            check_source(self.source)

    def test_git_source_keeps_existing_diff_check(self) -> None:
        subprocess.run(["git", "-C", str(self.source), "init", "-q"], check=True)
        tracked = self.source / "tracked.cc"
        tracked.write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.source), "add", "tracked.cc"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.source),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        tracked.write_text("new \n", encoding="utf-8")
        with self.assertRaisesRegex(SourceCheckError, "trailing whitespace"):
            check_source(self.source)


if __name__ == "__main__":
    unittest.main()
