"""The preview archive must notarize Arcium.app, not an installer wrapper."""
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_preview import archive_browser


class PreviewArchiveTest(unittest.TestCase):
    def test_archive_contains_the_browser_and_its_initial_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            browser = root / "browser/Arcium.app"
            resources = browser / "Contents/Resources"
            resources.mkdir(parents=True)
            (resources / "initial_preferences").write_text('{"fixture":true}')
            executable = browser / "Contents/MacOS/Helium"
            executable.parent.mkdir()
            executable.write_bytes(b"browser")
            info = {
                "CFBundleExecutable": "Helium",
                "CFBundleIdentifier": "net.imput.arcium",
                "CFBundleShortVersionString": "151.0.0",
                "CFBundleVersion": "151.0.0",
            }
            with (browser / "Contents/Info.plist").open("wb") as handle:
                plistlib.dump(info, handle)
            archive = root / "Arcium.xcarchive"
            with patch("package_preview.capture", return_value="arm64"), \
                 patch("he.apps.verify_signature") as verify:
                archive_browser(browser, archive, "Developer ID Application: Fixture", "TEAM")
            archived_app = archive / "Products/Applications/Arcium.app"
            verify.assert_called_once_with(archived_app)
            self.assertEqual(b"browser", (archived_app / "Contents/MacOS/Helium").read_bytes())
            self.assertEqual('{"fixture":true}', (archived_app / "Contents/Resources/initial_preferences").read_text())
            with (archive / "Info.plist").open("rb") as handle:
                archived_info = plistlib.load(handle)
            self.assertEqual("Arcium", archived_info["Name"])
            properties = archived_info["ApplicationProperties"]
            self.assertEqual("Applications/Arcium.app", properties["ApplicationPath"])
            self.assertEqual(["arm64"], properties["Architectures"])
            self.assertEqual("net.imput.arcium", properties["CFBundleIdentifier"])
            self.assertFalse(list(archive.rglob("Install-Arcium.app")))


if __name__ == "__main__":
    unittest.main()
