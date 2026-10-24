"""Check the real DMG specification and safe publication without mounting volumes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_dmg import create_disk_image


class ReleaseDmgTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="arcium dmg ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / "browser" / "Arcium.app"
        self.app.mkdir(parents=True)
        self.destination = self.root / "release" / "Arcium.dmg"
        self.calls = []
        self.specification = None

    def run_tool(self, command, **kwargs):
        self.calls.append(command)
        self.assertTrue(kwargs["check"])
        if command[0] == "appdmg":
            self.specification = json.loads(Path(command[1]).read_text())
            Path(command[2]).write_bytes(b"disk image")

    def create(self, identity=None):
        with patch("release_dmg.shutil.which", return_value="/tools/appdmg"), \
             patch("release_dmg.subprocess.run", side_effect=self.run_tool):
            create_disk_image(self.app, self.destination, identity)

    def test_packages_browser_with_real_drag_target_and_retina_background(self):
        self.create()
        self.assertEqual(b"disk image", self.destination.read_bytes())
        config = self.specification
        self.assertEqual("Arcium", config["title"])
        self.assertEqual(str(self.app / "Contents/Resources/app.icns"), config["icon"])
        self.assertEqual([
            {"x": 160, "y": 226, "type": "file", "path": str(self.app), "name": "Arcium.app"},
            {"x": 480, "y": 226, "type": "link", "path": "/Applications"},
        ], config["contents"])
        background = Path(config["background"])
        self.assertTrue(background.is_file())
        self.assertTrue(background.with_stem(background.stem + "@2x").is_file())
        self.assertEqual({"width": 640, "height": 420}, config["window"]["size"])
        self.assertEqual(["codesign", "--verify", "--deep", "--strict", str(self.app)], self.calls[0])
        self.assertEqual([self.destination], list(self.destination.parent.iterdir()))

    def test_signs_and_verifies_image_before_publishing(self):
        self.create("Developer ID Application: Fixture")
        sign = next(call for call in self.calls if "--sign" in call)
        self.assertIn("--timestamp", sign)
        self.assertEqual("Developer ID Application: Fixture", sign[sign.index("--sign") + 1])
        self.assertEqual(["codesign", "--verify", "--strict", sign[-1]], self.calls[-1])

    def test_refuses_existing_output_and_dangling_symlink(self):
        self.destination.parent.mkdir()
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    self.destination.symlink_to(self.root / "missing")
                else:
                    self.destination.write_bytes(b"keep")
                with self.assertRaisesRegex(ValueError, "already exists"):
                    create_disk_image(self.app, self.destination)
                self.destination.unlink()

    def test_refuses_output_inside_source_and_symlink_source(self):
        with self.assertRaisesRegex(ValueError, "outside the app"):
            create_disk_image(self.app, self.app / "nested.dmg")
        alias = self.root / "Arcium.app"
        alias.symlink_to(self.app)
        with self.assertRaisesRegex(ValueError, "plain Arcium.app"):
            create_disk_image(alias, self.destination)

    def test_packaging_failure_leaves_no_output(self):
        def fail(command, **kwargs):
            self.run_tool(command, **kwargs)
            if command[0] == "appdmg":
                raise subprocess.CalledProcessError(1, command)
        with patch("release_dmg.shutil.which", return_value="/tools/appdmg"), \
             patch("release_dmg.subprocess.run", side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                create_disk_image(self.app, self.destination)
        self.assertEqual([], list(self.destination.parent.iterdir()))

    def test_does_not_overwrite_output_created_during_packaging(self):
        def race(command, **kwargs):
            self.run_tool(command, **kwargs)
            if command[0] == "appdmg":
                self.destination.write_bytes(b"keep")
        with patch("release_dmg.shutil.which", return_value="/tools/appdmg"), \
             patch("release_dmg.subprocess.run", side_effect=race):
            with self.assertRaises(FileExistsError):
                create_disk_image(self.app, self.destination)
        self.assertEqual(b"keep", self.destination.read_bytes())


if __name__ == "__main__":
    unittest.main()
