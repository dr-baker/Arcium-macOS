"""Ownership lookup remains useful and read-only without generated source."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from patch_lookup import _source_path, locate, main  # noqa: E402
from patch_workspace import PatchWorkspaceError, prepare  # noqa: E402


class PatchLookupTests(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path, Path]:
        worktree, build = base / "worktree", base / "missing-lane"
        core, outer = worktree / "helium-chromium/patches", worktree / "patches"
        core.mkdir(parents=True)
        outer.mkdir()
        (core / "series").write_text("declaration.patch\nconsumer.patch\n")
        (outer / "series").write_text("native.patch\n")
        (core / "declaration.patch").write_text(
            "--- /dev/null\n+++ b/chrome/pref.h\n@@ -0,0 +1,2 @@\n"
            "+const char kPinned[] = \"pinned\";\n+const char kOther[] = \"other\";\n"
        )
        (core / "consumer.patch").write_text(
            "Index: src/chrome/view.cc\n--- src.orig/chrome/view.cc\n+++ src/chrome/view.cc\n"
            "@@ -10,2 +10,2 @@\n kPinned context\n-kPinned removed\n+kPinned added\n"
        )
        (outer / "native.patch").write_text(
            "--- a/chrome/view.cc\n+++ b/chrome/view.cc\n@@ -20 +20 @@\n"
            "-kPinned old native\n+kPinned new native\n"
        )
        return worktree, build, build / "src"

    def test_missing_lane_preserves_authority_order_and_line_kinds_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            worktree, build, source = self._fixture(base)
            before = {str(path): path.read_bytes() for path in base.rglob("*") if path.is_file()}
            report = locate(worktree, "kPinned", build_root=build, source=source)
            self.assertEqual(report["lane"]["generated_catalog"], "missing")
            self.assertEqual(report["total_patch_file_matches"], 3)
            pref, view = report["groups"]
            self.assertEqual(pref["sourcepath"], "chrome/pref.h")
            self.assertEqual([owner["series_position"] for owner in view["owners"]], [2, 3])
            self.assertEqual([owner["owner"] for owner in view["owners"]], ["core", "outer"])
            consumer = view["owners"][0]
            self.assertEqual(consumer["counts"], {"added": 1, "context": 1, "removed": 1})
            self.assertEqual(consumer["excerpts"][1]["old_line"], 11)
            self.assertEqual(consumer["excerpts"][1]["new_line"], None)
            self.assertFalse(consumer["generated_source_exists"])
            self.assertFalse(build.exists())
            after = {str(path): path.read_bytes() for path in base.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_stale_lane_preserves_observed_top_without_claiming_applied_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            subprocess.run(["git", "init", "-q", str(worktree)], check=True, capture_output=True)
            root = prepare(worktree, build)
            metadata = source / ".pc"
            metadata.mkdir(parents=True)
            (metadata / ".quilt_patches").write_text(str(root))
            (metadata / ".quilt_series").write_text("series.merged")
            (metadata / "applied-patches").write_text("declaration.patch\n")
            current = locate(worktree, "kPinned", build_root=build, source=source)
            self.assertEqual(current["lane"]["generated_catalog"], "current")
            self.assertEqual(current["groups"][0]["owners"][0]["generated_patch_state"], "top")
            patch = worktree / "helium-chromium/patches/declaration.patch"
            patch.write_text(patch.read_text().replace("kOther", "kChanged"))
            stale = locate(worktree, "kPinned", build_root=build, source=source)
            self.assertEqual(stale["lane"]["generated_catalog"], "stale")
            self.assertEqual(stale["lane"]["top"], "declaration.patch")
            self.assertEqual(stale["groups"][0]["owners"][0]["generated_patch_state"], "unknown")

    def test_lane_validation_uses_the_same_authoritative_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, build, source = self._fixture(Path(temporary))
            import patch_lookup
            subprocess.run(["git", "init", "-q", str(worktree)], check=True, capture_output=True)
            prepare(worktree, build)
            with mock.patch.object(patch_lookup, "_authoritative_state", wraps=patch_lookup._authoritative_state) as read:
                locate(worktree, "kPinned", build_root=build, source=source)
            read.assert_called_once_with(worktree.resolve())

    def test_invalid_utf8_in_optional_lane_metadata_preserves_cli_matches(self) -> None:
        for damaged in ("manifest.json", "applied-patches", ".quilt_patches", ".quilt_series"):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as temporary:
                worktree, build, source = self._fixture(Path(temporary))
                subprocess.run(["git", "init", "-q", str(worktree)], check=True, capture_output=True)
                root = prepare(worktree, build)
                metadata = source / ".pc"
                metadata.mkdir(parents=True)
                (metadata / ".quilt_patches").write_text(str(root))
                (metadata / ".quilt_series").write_text("series.merged")
                (metadata / "applied-patches").write_text("declaration.patch\n")
                target = root / damaged if damaged == "manifest.json" else metadata / damaged
                target.write_bytes(b"\xff\n")
                before = {path: path.read_bytes() for path in build.rglob("*") if path.is_file()}
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main([
                        "--worktree", str(worktree), "--build-root", str(build),
                        "--source", str(source), "--json", "kPinned",
                    ])
                self.assertEqual(result, 0, stderr.getvalue())
                self.assertEqual(stderr.getvalue(), "")
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["total_patch_file_matches"], 3)
                if damaged == "manifest.json":
                    self.assertEqual(report["lane"]["generated_catalog"], "stale")
                    self.assertIn("decode", report["lane"]["catalog_detail"])
                else:
                    self.assertEqual(report["lane"]["quilt_status"], "invalid")
                    self.assertIn("decode", report["lane"]["quilt_detail"])
                self.assertTrue(all(
                    owner["generated_patch_state"] == "unknown"
                    for group in report["groups"] for owner in group["owners"]
                ))
                self.assertEqual(before, {path: path.read_bytes() for path in build.rglob("*") if path.is_file()})

    def test_exact_paths_globs_limits_and_unsafe_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, _, _ = self._fixture(Path(temporary))
            exact = locate(worktree, "chrome/view.cc")
            self.assertEqual(exact["mode"], "path")
            self.assertEqual(exact["total_patch_file_matches"], 2)
            self.assertEqual(locate(worktree, "view.cc", mode="path")["total_patch_file_matches"], 0)
            bounded = locate(worktree, "chrome/*", limit=1)
            self.assertEqual(bounded["mode"], "glob")
            self.assertEqual(bounded["omitted_patch_file_matches"], 2)
            self.assertEqual(locate(worktree, "kPINNED", ignore_case=True)["total_patch_file_matches"], 3)
            for query in ("/chrome/view.cc", "chrome/../view.cc", ""):
                with self.subTest(query=query), self.assertRaises(PatchWorkspaceError):
                    locate(worktree, query)

    def test_source_content_that_resembles_headers_is_a_hunk_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, _, _ = self._fixture(Path(temporary))
            patch = worktree / "helium-chromium/patches/consumer.patch"
            patch.write_text("--- a/chrome/view.cc\n+++ b/chrome/view.cc\n@@ -1 +1 @@\n--- kPinned old text\n+++ kPinned new text\n")
            report = locate(worktree, "kPinned")
            owner = report["groups"][1]["owners"][0]
            self.assertEqual(owner["sourcepath"], "chrome/view.cc")
            self.assertEqual(owner["counts"], {"added": 1, "removed": 1, "context": 0})

    def test_binary_rename_and_hunk_heading_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worktree, _, _ = self._fixture(Path(temporary))
            patch = worktree / "helium-chromium/patches/consumer.patch"
            patch.write_text('diff --git a/chrome/old.bin b/chrome/new.bin\nsimilarity index 100%\nrename from chrome/old.bin\nrename to chrome/new.bin\n')
            report = locate(worktree, "chrome/old.bin")
            self.assertEqual(report["total_patch_file_matches"], 1)
            self.assertEqual(report["groups"][0]["sourcepath"], "chrome/new.bin")
            patch.write_text('diff --git a/chrome/icon.bin b/chrome/icon.bin\nBinary files a/chrome/icon.bin and b/chrome/icon.bin differ\n')
            self.assertEqual(locate(worktree, "chrome/icon.bin")["total_patch_file_matches"], 1)
            patch.write_text('diff --git a/chrome/spaced name.bin b/chrome/spaced name.bin\nBinary files a/chrome/spaced name.bin and b/chrome/spaced name.bin differ\n')
            self.assertEqual(locate(worktree, "chrome/spaced name.bin")["total_patch_file_matches"], 1)
            patch.write_text('diff --git a/chrome/view.cc b/chrome/view.cc\n--- a/chrome/view.cc\n+++ b/chrome/view.cc\n@@ -1 +1 @@ void kOnlyInHeading()\n-old\n+new\n')
            report = locate(worktree, "kOnlyInHeading")
            owner = report["groups"][0]["owners"][0]
            self.assertEqual(owner["counts"], {"added": 0, "context": 0, "removed": 0})
            self.assertEqual(owner["matching_hunk_headings"], 1)
            self.assertEqual(locate(worktree, "chrome/view.cc")["total_patch_file_matches"], 2)
            patch.write_text('--- a/chrome/view.cc\n+++ b/chrome/view.cc\n@@ -1 +1 @@\n context\n+stray\n')
            with self.assertRaisesRegex(PatchWorkspaceError, "outside a unified hunk"):
                locate(worktree, "stray")

    def test_unified_space_and_git_quoted_utf8_paths(self) -> None:
        self.assertEqual(_source_path("a/chrome/spaced name.cc\t2026-01-01"), "chrome/spaced name.cc")
        self.assertEqual(_source_path(r'"a/chrome/\303\251.cc"'), "chrome/é.cc")


if __name__ == "__main__":
    unittest.main()
