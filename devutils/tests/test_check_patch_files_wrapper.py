"""Tests for active patch-series selection in the outer validator."""

import tempfile
import unittest
from pathlib import Path

from devutils.check_patch_files import active_series, validate_patches_dir


_PATCH = """--- a/file.txt
+++ b/file.txt
@@ -1 +1 @@
-old
+new
"""


class CheckPatchFilesWrapperTest(unittest.TestCase):
    def _write_catalog(self, series_name):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        patches_dir = Path(temp_dir.name)
        (patches_dir / "a.patch").write_text(_PATCH, encoding="utf-8")
        (patches_dir / series_name).write_text("a.patch\n", encoding="utf-8")
        return patches_dir

    def test_unmerged_series_is_checked(self):
        patches_dir = self._write_catalog("series")
        self.assertEqual(active_series(patches_dir).name, "series")
        self.assertFalse(validate_patches_dir(patches_dir))

    def test_merged_series_ignores_merge_metadata(self):
        patches_dir = self._write_catalog("series.merged")
        (patches_dir / "series.orig").write_text("old\n", encoding="utf-8")
        (patches_dir / "series.prepend").write_text("old\n", encoding="utf-8")
        self.assertEqual(active_series(patches_dir).name, "series.merged")
        self.assertFalse(validate_patches_dir(patches_dir))

    def test_ambiguous_series_state_is_rejected(self):
        patches_dir = self._write_catalog("series")
        (patches_dir / "series.merged").write_text("a.patch\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Ambiguous patch catalog"):
            active_series(patches_dir)

    def test_unlisted_patch_remains_a_warning(self):
        patches_dir = self._write_catalog("series.merged")
        (patches_dir / "extra.patch").write_text(_PATCH, encoding="utf-8")
        self.assertTrue(validate_patches_dir(patches_dir))


if __name__ == "__main__":
    unittest.main()
