#!/usr/bin/env python3

"""Exercise product notes and provenance in the GitHub release body."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/github_generate_release_note.sh"


class ReleaseNotesTest(unittest.TestCase):
    """Run the copied CI entrypoint against small real Git repositories."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.core = self.root / "helium-chromium"
        self.core.mkdir()
        self.environment = os.environ.copy()
        self.environment.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Release test",
            GIT_AUTHOR_EMAIL="release-test@example.invalid",
            GIT_COMMITTER_NAME="Release test",
            GIT_COMMITTER_EMAIL="release-test@example.invalid",
            GITHUB_REPOSITORY="example/arcium",
            GITHUB_RUN_ID="123",
        )
        self.environment.pop("RELEASE_NOTES_FILE", None)
        self.environment.pop("REQUIRE_RELEASE_NOTES", None)
        self.environment.pop("RELEASE_TAG", None)
        self.environment.pop("REQUIRE_RELEASE_TAG", None)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        readlink = bin_dir / "greadlink"
        readlink.write_text('#!/bin/sh\n[ "$1" = -f ] || exit 2\nprintf \'%s\\n\' "$2"\n')
        readlink.chmod(0o755)
        self.environment["PATH"] = f"{bin_dir}:{self.environment['PATH']}"
        shutil.copy2(SCRIPT, self.root / "github_generate_release_note.sh")
        shutil.copy2(ROOT / ".github/scripts/github_prepare_release.sh",
                     self.root / "github_prepare_release.sh")
        for repo in (self.root, self.core):
            self.git(repo, "init", "--quiet")
        utils = self.core / "utils"
        utils.mkdir()
        (utils / "helium_version.py").write_text('print("0.15.1.1")\n')
        self.git(self.core, "add", "utils/helium_version.py")
        self.git(self.core, "commit", "--quiet", "-m", "core baseline")
        self.record_core()
        self.git(self.root, "commit", "--quiet", "-m", "product baseline")
        self.git(self.root, "tag", "previous")
        (self.core / "change.txt").write_text("new browser behavior\n")
        self.git(self.core, "add", "change.txt")
        self.git(self.core, "commit", "--quiet", "-m", "browser change")
        self.record_core()
        self.git(self.root, "commit", "--quiet", "-m", "product change")
        for arch in ("arm64", "x86_64"):
            (self.root / f"arcium_0.15.1.1_{arch}-macos.dmg.hashes.md").write_text(
                f"{arch} artifact hash\n"
            )
        self.notes = self.root / "docs/releases/preview.md"
        self.notes.parent.mkdir(parents=True)
        self.notes.write_text("# Arcium preview\n\nVisual polish!\n")

    def git(self, repo: Path, *arguments: str) -> str:
        """Keep fixture Git calls independent of the developer's configuration."""
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            env=self.environment,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()

    def record_core(self) -> None:
        """Record a real gitlink without requiring a network submodule clone."""
        revision = self.git(self.core, "rev-parse", "HEAD")
        self.git(self.root, "update-index", "--add", "--cacheinfo",
                 f"160000,{revision},helium-chromium")

    def generate(self, **variables: str) -> subprocess.CompletedProcess[str]:
        """Run release generation as CI does after copying scripts to root."""
        return subprocess.run(
            [str(self.root / "github_generate_release_note.sh")],
            cwd=self.root,
            env={**self.environment, **variables},
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_curated_notes_lead_assets_and_source_history(self) -> None:
        """Product copy leads while hashes and exact source history survive."""
        result = self.generate(RELEASE_NOTES_FILE="docs/releases/preview.md",
                               REQUIRE_RELEASE_NOTES="1")
        self.assertEqual(0, result.returncode, result.stdout)
        body = (self.root / "github_release_note.md").read_text()
        self.assertTrue(body.startswith(self.notes.read_text()))
        self.assertLess(body.index("Visual polish!"), body.index("arm64 artifact hash"))
        for expected in ("x86_64 artifact hash", "browser change", "product change",
                         "<details>", "https://github.com/example/arcium/actions/runs/123"):
            self.assertIn(expected, body)
        second = self.generate(RELEASE_NOTES_FILE="docs/releases/preview.md")
        self.assertEqual(0, second.returncode, second.stdout)
        self.assertEqual(body, (self.root / "github_release_note.md").read_text())

    def test_invalid_explicit_notes_fail_without_erasing_existing_body(self) -> None:
        """Missing and empty notes cannot silently publish a technical log."""
        output = self.root / "github_release_note.md"
        output.write_text("previous body\n")
        for path in ("docs/releases/missing.md", "docs/releases/empty.md"):
            with self.subTest(path=path):
                (self.root / "docs/releases/empty.md").touch()
                result = self.generate(RELEASE_NOTES_FILE=path)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("nonempty file", result.stdout)
                self.assertEqual("previous body\n", output.read_text())

    def test_required_notes_fail_when_omitted(self) -> None:
        """A release dispatch must explicitly choose its product notes."""
        result = self.generate(REQUIRE_RELEASE_NOTES="1")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Set RELEASE_NOTES_FILE", result.stdout)

    def test_standalone_announcements_fallback(self) -> None:
        """Existing standalone callers can still use announcements."""
        (self.root / "announcements.md").write_text("Existing announcement\n")
        result = self.generate()
        self.assertEqual(0, result.returncode, result.stdout)
        body = (self.root / "github_release_note.md").read_text()
        self.assertTrue(body.startswith("## Arcium for macOS 0.15.1.1\n"))
        self.assertIn("Existing announcement", body)
        self.assertIn("arm64 artifact hash", body)

    def test_ci_pipeline_propagates_missing_notes(self) -> None:
        """The explicit Bash CI shell must not let tee hide a failed generator."""
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
             "./github_generate_release_note.sh | tee github_actions_release.log"],
            cwd=self.root,
            env={**self.environment, "REQUIRE_RELEASE_NOTES": "1"},
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Set RELEASE_NOTES_FILE", result.stdout)
        self.assertFalse((self.root / "github_release_note.md").exists())

    def test_missing_asset_hash_fails_generation(self) -> None:
        """A broken artifact pipeline cannot produce successful release notes."""
        (self.root / "arcium_0.15.1.1_arm64-macos.dmg.hashes.md").unlink()
        result = self.generate(RELEASE_NOTES_FILE="docs/releases/preview.md")
        self.assertNotEqual(0, result.returncode)

    def test_product_tag_is_separate_from_artifact_build_version(self) -> None:
        """Product preview tags must not rename the downloaded build artifacts."""
        output = self.root / "prepare-output"
        result = subprocess.run(
            [str(self.root / "github_prepare_release.sh")],
            cwd=self.root,
            env={**self.environment, "RELEASE_TAG": "0.2.0-preview.2",
                 "REQUIRE_RELEASE_TAG": "1", "GITHUB_OUTPUT": str(output)},
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(0, result.returncode, result.stdout)
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual("0.2.0-preview.2", values["release_tag_version"])
        self.assertEqual("Arcium 0.2.0-preview.2", values["release_name"])
        self.assertEqual("arcium_0.15.1.1_arm64-macos.dmg", values["arm64_file_name"])
        self.assertEqual("arcium_0.15.1.1_x86_64-macos.dmg", values["x64_file_name"])

    def test_required_product_tag_cannot_be_omitted_or_invalid(self) -> None:
        """CI must choose a valid product tag before emitting release metadata."""
        for tag in ("", "bad tag", "bad\noutput=value"):
            with self.subTest(tag=tag):
                output = self.root / "prepare-output"
                result = subprocess.run(
                    [str(self.root / "github_prepare_release.sh")],
                    cwd=self.root,
                    env={**self.environment, "RELEASE_TAG": tag,
                         "REQUIRE_RELEASE_TAG": "1", "GITHUB_OUTPUT": str(output)},
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
