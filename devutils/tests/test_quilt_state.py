"""Tests for fail-closed Quilt provenance inspection."""

import tempfile
import unittest
from pathlib import Path

from devutils.quilt_state import (
    QuiltStateError,
    compare_patch_lists,
    inspect_quilt_state,
    patch_list_sha256,
    patch_series_sha256,
    read_patch_list,
)


class QuiltStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "src"
        self.patches = root / "patches"
        (self.source / ".pc").mkdir(parents=True)
        self.patches.mkdir()
        (self.source / ".pc" / ".quilt_patches").write_text(
            str(self.patches), encoding="utf-8"
        )
        (self.source / ".pc" / ".quilt_series").write_text(
            "series.merged\n", encoding="utf-8"
        )

    def write_state(self, declared: tuple[str, ...], applied: tuple[str, ...]) -> None:
        (self.patches / "series.merged").write_text(
            "\n".join(declared) + "\n", encoding="utf-8"
        )
        for name in declared:
            patch_path = self.patches / name
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            if not patch_path.exists():
                patch_path.write_text(f"patch {name}\n", encoding="utf-8")
        (self.source / ".pc" / "applied-patches").write_text(
            "\n".join(applied) + "\n", encoding="utf-8"
        )

    def test_complete_and_partial_prefix_states_are_distinct(self) -> None:
        declared = ("a.patch", "b.patch", "c.patch")
        partial = compare_patch_lists(declared, declared[:2])
        self.assertTrue(partial.valid_prefix)
        self.assertFalse(partial.complete)
        with self.assertRaisesRegex(QuiltStateError, "next patch is c.patch"):
            partial.require_complete()
        complete = compare_patch_lists(declared, declared)
        self.assertTrue(complete.complete)
        complete.require_complete()

    def test_missing_middle_patch_is_rejected_even_when_top_is_last(self) -> None:
        comparison = compare_patch_lists(
            ("a.patch", "missing.patch", "b.patch", "last.patch"),
            ("a.patch", "b.patch", "last.patch"),
        )
        self.assertFalse(comparison.valid_prefix)
        self.assertEqual(comparison.divergence_index, 1)
        self.assertIn("skip declared patch missing.patch", comparison.detail)

    def test_extra_and_reordered_patches_are_rejected(self) -> None:
        extra = compare_patch_lists(("a.patch",), ("a.patch", "extra.patch"))
        self.assertIn("not declared", extra.detail)
        reordered = compare_patch_lists(
            ("a.patch", "b.patch", "c.patch"),
            ("a.patch", "c.patch", "b.patch"),
        )
        self.assertFalse(reordered.valid_prefix)
        self.assertIn("skip declared patch b.patch", reordered.detail)

    def test_series_parser_ignores_comments_and_options(self) -> None:
        path = self.patches / "series.merged"
        path.write_text(
            "# comment\n\na.patch -p1 # option\nfolder/b.patch\n",
            encoding="utf-8",
        )
        self.assertEqual(read_patch_list(path), ("a.patch", "folder/b.patch"))

    def test_series_parser_rejects_path_traversal(self) -> None:
        path = self.patches / "series.merged"
        path.write_text("../outside.patch\n", encoding="utf-8")
        with self.assertRaisesRegex(QuiltStateError, "unsafe patch name"):
            read_patch_list(path)

    def test_inspection_verifies_pointers_and_ordered_digests(self) -> None:
        self.write_state(("a.patch", "b.patch"), ("a.patch",))
        report = inspect_quilt_state(self.source, self.patches)
        self.assertTrue(report.comparison.valid_prefix)
        self.assertFalse(report.comparison.complete)
        self.assertNotEqual(report.declared_sha256, report.applied_sha256)
        self.assertNotEqual(
            patch_list_sha256(("a.patch", "b.patch")),
            patch_list_sha256(("b.patch", "a.patch")),
        )

    def test_declared_digest_changes_when_patch_content_changes(self) -> None:
        declared = ("a.patch", "b.patch")
        self.write_state(declared, declared)
        first = patch_series_sha256(self.patches, declared)
        (self.patches / "b.patch").write_text("changed\n", encoding="utf-8")
        self.assertNotEqual(first, patch_series_sha256(self.patches, declared))

    def test_declared_digest_changes_when_series_options_change(self) -> None:
        declared = ("a.patch",)
        self.write_state(declared, declared)
        first = patch_series_sha256(self.patches, declared)
        (self.patches / "series.merged").write_text(
            "a.patch -p1\n", encoding="utf-8"
        )
        self.assertNotEqual(first, patch_series_sha256(self.patches, declared))

    def test_stale_patch_directory_provenance_is_rejected(self) -> None:
        self.write_state(("a.patch",), ("a.patch",))
        stale = self.patches.parent / "other-worktree" / "patches"
        stale.mkdir(parents=True)
        (self.source / ".pc" / ".quilt_patches").write_text(
            str(stale), encoding="utf-8"
        )
        with self.assertRaisesRegex(QuiltStateError, "provenance mismatch"):
            inspect_quilt_state(self.source, self.patches)

    def test_wrong_series_pointer_is_rejected(self) -> None:
        self.write_state(("a.patch",), ("a.patch",))
        (self.source / ".pc" / ".quilt_series").write_text(
            "series\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(QuiltStateError, "series mismatch"):
            inspect_quilt_state(self.source, self.patches)

    def test_duplicate_declared_or_applied_history_is_rejected(self) -> None:
        self.write_state(("a.patch", "a.patch"), ("a.patch",))
        with self.assertRaisesRegex(QuiltStateError, "duplicate patches in series.merged"):
            inspect_quilt_state(self.source, self.patches)
        self.write_state(("a.patch",), ("a.patch", "a.patch"))
        with self.assertRaisesRegex(QuiltStateError, "duplicate patches in applied-patches"):
            inspect_quilt_state(self.source, self.patches)


if __name__ == "__main__":
    unittest.main()
