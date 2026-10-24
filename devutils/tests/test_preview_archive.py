"""The preview archive must notarize Arcium.app, not an installer wrapper."""
from pathlib import Path
import contextlib
import io
import plistlib
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_preview import archive_browser, main


class PreviewArchiveTest(unittest.TestCase):
    def test_staging_completes_provenance_and_notarization_scripts(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            out = root / "build/src/out/Default"
            credits = out / "gen/components/resources/about_credits.html"
            credits.parent.mkdir(parents=True)
            credits.write_text("Helium Chromium GNU GENERAL PUBLIC LICENSE")
            destination = root / "preview"
            identity = "Developer ID Application: Fixture"
            core_commit = "b" * 40
            outer_commit = "a" * 40

            def capture(*command, **kwargs):
                if command[0] == "git":
                    if "ls-files" in command:
                        return ""
                    if "ls-tree" in command:
                        return "160000 commit " + core_commit + "\thelium-chromium"
                    return core_commit if command[2].endswith("helium-chromium") else outer_commit
                if command[0] == "/usr/bin/lipo":
                    return "arm64"
                if command[0] == "/usr/bin/shasum":
                    return "c" * 64 + "  browser"
                self.fail("Unexpected external command: " + repr(command))

            def package(output, browser, signing_identity):
                self.assertEqual(out, output)
                self.assertEqual(identity, signing_identity)
                contents = browser / "Contents"
                (contents / "MacOS").mkdir(parents=True)
                (contents / "MacOS/Helium").write_bytes(b"fixture")
                with (contents / "Info.plist").open("wb") as handle:
                    plistlib.dump({
                        "CFBundleExecutable": "Helium",
                        "CFBundleIdentifier": "net.imput.arcium",
                        "CrProductDirName": "Arcium",
                        "CFBundleShortVersionString": "151.0.0",
                        "CFBundleVersion": "151.0.0",
                    }, handle)
                return {"copy": "fixture"}

            def create_image(browser, image, signing_identity):
                self.assertEqual(destination / "browser/Arcium.app", browser)
                self.assertEqual(identity, signing_identity)
                image.write_bytes(b"fixture image")

            paths = SimpleNamespace(src=out.parent.parent, catalog=root / "catalog")
            argv = ["package_preview.py", "--repo", str(repo), "--out-dir", str(out),
                    "--destination", str(destination), "--identity", identity,
                    "--stage", "--inside-lock"]
            with patch.object(sys, "argv", argv), \
                 patch("package_preview.capture", side_effect=capture), \
                 patch("package_preview.tracked_clean", return_value=True), \
                 patch("he.common.make_paths", return_value=paths), \
                 patch("he.catalog.drift", return_value=[]), \
                 patch("he.timestamps.pending", return_value=False), \
                 patch("he.quilt.applied", return_value=["fixture.patch"]), \
                 patch("he.quilt.read_list", return_value=["fixture.patch"]), \
                 patch("he.builds.require_completed", return_value={"mode": "daily"}), \
                 patch("arcium.install.package", side_effect=package), \
                 patch("release_dmg.create_disk_image", side_effect=create_image), \
                 patch("he.apps.verify_signature"), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main())
            provenance = json.loads((destination / "packaging-provenance.json").read_text())
            self.assertEqual(outer_commit, provenance["macos_commit"])
            self.assertEqual(core_commit, provenance["core_commit"])
            self.assertFalse(provenance["notarized"])
            self.assertEqual("c" * 64, provenance["browser_sha256"])
            self.assertTrue((destination / "Arcium.dmg").is_file())
            upload = (destination / "upload-notarization.sh").read_text()
            export = (destination / "export-notarized.sh").read_text()
            self.assertIn("-exportArchive", upload)
            self.assertIn("release_dmg.py", export)
            self.assertIn("stapler validate", export)
            self.assertIn("notarized/Arcium.app", export)
            self.assertNotIn("Install-Arcium.app", upload + export)

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
