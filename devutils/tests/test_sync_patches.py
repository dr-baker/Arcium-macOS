"""Tests for safe synchronization of generated core patch copies."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync_patches import SyncError, sync_generated_patches  # noqa: E402


class SyncPatchesTests(unittest.TestCase):
    def fixture(self, applied: str = "") -> tuple[Path, Path, bytes, bytes]:
        temporary = Path(tempfile.mkdtemp(prefix="sync-patches-test-"))
        self.addCleanup(lambda: shutil.rmtree(temporary, ignore_errors=True))
        outer = temporary / "outer"
        core = outer / "helium-chromium" / "patches"
        generated = outer / "patches"
        source = temporary / "build" / "src"
        (core / "personal").mkdir(parents=True)
        (generated / "personal").mkdir(parents=True)
        (source / ".pc").mkdir(parents=True)
        (core / "series").write_text("personal/core.patch\n", encoding="utf-8")
        (core / "personal" / "core.patch").write_bytes(b"authoritative core\n")
        platform_series = b"helium/macos/platform.patch\n"
        platform_patch = b"platform bytes\n"
        (generated / "series.orig").write_bytes(platform_series)
        (generated / "helium" / "macos").mkdir(parents=True)
        (generated / "helium" / "macos" / "platform.patch").write_bytes(platform_patch)
        (generated / "series.merged").write_text(
            "personal/core.patch\n" + platform_series.decode("utf-8"), encoding="utf-8"
        )
        (generated / "series.prepend").write_text(
            "personal/core.patch\n", encoding="utf-8"
        )
        (generated / "personal" / "core.patch").write_bytes(b"stale generated\n")
        (source / ".pc" / ".quilt_patches").write_text(
            str(generated), encoding="utf-8"
        )
        (source / ".pc" / ".quilt_series").write_text(
            "series.merged\n", encoding="utf-8"
        )
        (source / ".pc" / "applied-patches").write_text(applied, encoding="utf-8")
        return outer, source, platform_series, platform_patch

    def test_sync_refreshes_generated_files_and_preserves_platform_files(self) -> None:
        outer, source, platform_series, platform_patch = self.fixture()
        sync_generated_patches(outer, source)

        patches = outer / "patches"
        self.assertEqual(
            (patches / "personal" / "core.patch").read_bytes(),
            b"authoritative core\n",
        )
        self.assertEqual(
            (patches / "series.prepend").read_bytes(),
            b"personal/core.patch\n",
        )
        self.assertEqual(
            (patches / "series.merged").read_bytes(),
            b"personal/core.patch\n" + platform_series,
        )
        self.assertEqual((patches / "series.orig").read_bytes(), platform_series)
        self.assertEqual(
            (patches / "helium" / "macos" / "platform.patch").read_bytes(),
            platform_patch,
        )
        self.assertEqual(
            (outer / "helium-chromium" / "patches" / "personal" / "core.patch").read_bytes(),
            b"authoritative core\n",
        )

    def test_sync_refuses_when_quilt_is_not_fully_popped(self) -> None:
        outer, source, _platform_series, _platform_patch = self.fixture(
            "personal/core.patch\n"
        )
        generated = outer / "patches" / "personal" / "core.patch"
        before = generated.read_bytes()

        with self.assertRaisesRegex(SyncError, "fully popped"):
            sync_generated_patches(outer, source)

        self.assertEqual(generated.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
