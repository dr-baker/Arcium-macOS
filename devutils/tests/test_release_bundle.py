"""Tests for staging the official Arcium release bundle."""

from __future__ import annotations

import plistlib
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
from arcium import bundle as arcium_app  # noqa: E402
from arcium.bundle import ArciumError  # noqa: E402
from release_bundle import ReleaseBundleError, stage_release_bundle  # noqa: E402


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="arcium-release-bundle-"))
        self.addCleanup(lambda: shutil.rmtree(self.temporary, ignore_errors=True))
        self.source = self.temporary / "Helium.app"
        self.destination = self.temporary / "out" / "Default" / "Arcium.app"
        self._make_source_app()

    def _write_plist(self, path: Path, info: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            plistlib.dump(info, handle)

    def _make_source_app(self) -> None:
        contents = self.source / "Contents"
        executable = contents / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"release browser executable")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self._write_plist(
            contents / "Info.plist",
            {
                "CFBundleExecutable": "Helium",
                "CFBundleIdentifier": "net.imput.helium",
                "CFBundleDisplayName": "Helium",
                "CFBundleName": "Helium",
            },
        )
        self._write_plist(
            contents / "Frameworks" / "Helium Helper.app" / "Contents" / "Info.plist",
            {
                "CFBundleExecutable": "Helium Helper",
                "CFBundleIdentifier": "net.imput.helium.helper",
                "CFBundleName": "Helium Helper",
            },
        )
        self._write_plist(
            contents
            / "Frameworks"
            / "Helium Framework.framework"
            / "Versions"
            / "A"
            / "Resources"
            / "Info.plist",
            {
                "CFBundleExecutable": "Helium Framework",
                "CFBundleIdentifier": "net.imput.helium.framework",
                "CFBundleName": "Helium Framework",
            },
        )

    @staticmethod
    def _read_plist(path: Path) -> dict[str, object]:
        with path.open("rb") as handle:
            return plistlib.load(handle)

    def test_staging_rewrites_only_the_copy_and_keeps_binary_names(self) -> None:
        original_root_bytes = (self.source / "Contents" / "Info.plist").read_bytes()
        original_executable = (self.source / "Contents" / "MacOS" / "Helium").read_bytes()

        staged = stage_release_bundle(self.source, self.destination)

        self.assertEqual(staged["bundle_identifier"], arcium_app.ARCIUM_BUNDLE_ID)
        self.assertEqual(staged["display_name"], "Arcium")
        self.assertEqual(staged["executable_name"], "Helium")
        expected_path = self.destination.parent.resolve() / self.destination.name
        self.assertEqual(staged["app_path"], str(expected_path))

        root = self._read_plist(self.destination / "Contents" / "Info.plist")
        self.assertEqual(root["CFBundleIdentifier"], "net.imput.arcium")
        self.assertEqual(root["CFBundleDisplayName"], "Arcium")
        self.assertEqual(root["CFBundleName"], "Arcium")
        self.assertEqual(root["CrProductDirName"], "Arcium")
        self.assertEqual(root["CFBundleExecutable"], "Helium")
        self.assertEqual(
            (self.destination / "Contents/Resources/initial_preferences").read_bytes(),
            arcium_app.INITIAL_PREFERENCES.read_bytes(),
        )
        self.assertFalse((self.source / "Contents/Resources/initial_preferences").exists())
        helper = self._read_plist(
            self.destination
            / "Contents/Frameworks/Helium Helper.app/Contents/Info.plist"
        )
        self.assertEqual(helper["CFBundleIdentifier"], "net.imput.arcium.helper")
        self.assertEqual(helper["CFBundleExecutable"], "Helium Helper")
        framework = self._read_plist(
            self.destination
            / "Contents/Frameworks/Helium Framework.framework/Versions/A/Resources/Info.plist"
        )
        self.assertEqual(
            framework["CFBundleIdentifier"], "net.imput.arcium.framework"
        )

        self.assertEqual(
            (self.source / "Contents" / "Info.plist").read_bytes(),
            original_root_bytes,
        )
        self.assertEqual(
            (self.source / "Contents" / "MacOS" / "Helium").read_bytes(),
            original_executable,
        )

    def test_staging_refuses_an_existing_destination(self) -> None:
        self.destination.mkdir(parents=True)
        marker = self.destination / "owned"
        marker.write_text("keep")

        with self.assertRaisesRegex(ReleaseBundleError, "refusing to overwrite"):
            stage_release_bundle(self.source, self.destination)

        self.assertEqual(marker.read_text(), "keep")

    def test_staging_rejects_a_destination_parent_aliased_into_source(self) -> None:
        alias = self.temporary / "source-contents-alias"
        alias.symlink_to(self.source / "Contents", target_is_directory=True)
        destination = alias / "Arcium.app"
        original = (self.source / "Contents" / "Info.plist").read_bytes()

        with self.assertRaisesRegex(ReleaseBundleError, "outside the source app"):
            stage_release_bundle(self.source, destination)

        self.assertEqual(
            (self.source / "Contents" / "Info.plist").read_bytes(), original
        )
        self.assertFalse((self.source / "Contents" / "Arcium.app").exists())

    def test_failed_metadata_rewrite_removes_partial_stage(self) -> None:
        (self.source / "Contents" / "Info.plist").unlink()

        with self.assertRaises(ArciumError):
            stage_release_bundle(self.source, self.destination)

        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
