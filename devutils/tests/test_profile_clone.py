"""Contract tests for one-time Chromium profile seeding."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import profile_clone  # noqa: E402


class ProfileCloneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="profile-clone-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.temporary, ignore_errors=True))

    def test_clone_removes_runtime_links_and_never_reseeds(self) -> None:
        source = self.temporary / "installed"
        destination = self.temporary / "isolated" / "peek"
        source.mkdir()
        (source / "Local State").write_text("installed", encoding="utf-8")
        for name in (
            "RunningChromeVersion",
            "SingletonCookie",
            "SingletonLock",
            "SingletonSocket",
        ):
            (source / name).symlink_to("runtime")

        def no_clone(*_args: object, **_kwargs: object) -> object:
            raise subprocess.CalledProcessError(1, "cp")

        self.assertEqual(
            profile_clone.clone_profile_once(
                source, destination, copy_runner=no_clone
            ),
            "fallback-copy",
        )
        self.assertEqual(
            (destination / "Local State").read_text(encoding="utf-8"),
            "installed",
        )
        self.assertFalse(
            any((destination / name).exists() for name in profile_clone._TRANSIENT_ENTRIES)
        )

        (destination / "Local State").write_text("special build", encoding="utf-8")
        self.assertEqual(
            profile_clone.clone_profile_once(source, destination), "existing"
        )
        self.assertEqual(
            (destination / "Local State").read_text(encoding="utf-8"),
            "special build",
        )

    def test_clone_rejects_unexpected_symlinks(self) -> None:
        source = self.temporary / "installed"
        destination = self.temporary / "isolated" / "peek"
        source.mkdir()
        (source / "unexpected").symlink_to("elsewhere")

        with self.assertRaisesRegex(
            profile_clone.ProfileCloneError, "contains symlinks"
        ):
            profile_clone.clone_profile_once(source, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
