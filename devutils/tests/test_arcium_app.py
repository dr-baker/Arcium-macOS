"""Focused tests for the stable installed Arcium workflow."""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import arcium_app  # noqa: E402


class Completed:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout


class FakeProcess:
    pid = 4242


class ArciumAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="arcium-app-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.temporary, ignore_errors=True))

    def _app(self, name: str = "Helium.app") -> Path:
        app = self.temporary / name
        contents = app / "Contents"
        executable = contents / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"browser")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        helper = contents / "Frameworks" / "Helium Helper.app" / "Contents"
        helper.mkdir(parents=True)
        for path, info in (
            (
                contents / "Info.plist",
                {
                    "CFBundleExecutable": "Helium",
                    "CFBundleIdentifier": "net.imput.helium",
                    "CFBundleDisplayName": "Helium",
                    "CFBundleName": "Helium",
                },
            ),
            (
                helper / "Info.plist",
                {
                    "CFBundleExecutable": "Helium Helper",
                    "CFBundleIdentifier": "net.imput.helium.helper",
                    "CFBundleName": "Helium Helper",
                },
            ),
        ):
            with path.open("wb") as handle:
                plistlib.dump(info, handle)
        return app

    def test_metadata_uses_stable_identity_and_keeps_executables(self) -> None:
        app = self._app("Arcium.app")
        changed = arcium_app.rewrite_arcium_metadata(app)
        self.assertEqual(changed, 2)
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            root = plistlib.load(handle)
        self.assertEqual(root["CFBundleIdentifier"], "net.imput.arcium")
        self.assertEqual(root["CFBundleDisplayName"], "Arcium")
        self.assertEqual(root["CFBundleExecutable"], "Helium")
        helper_path = (
            app
            / "Contents"
            / "Frameworks"
            / "Helium Helper.app"
            / "Contents"
            / "Info.plist"
        )
        with helper_path.open("rb") as handle:
            helper = plistlib.load(handle)
        self.assertEqual(helper["CFBundleIdentifier"], "net.imput.arcium.helper")
        self.assertEqual(helper["CFBundleExecutable"], "Helium Helper")

    def test_signing_identity_requires_one_stable_developer_id(self) -> None:
        output = (
            '  1) AAAA "Apple Development: Example"\n'
            '  2) BBBB "Developer ID Application: Daniel Example (TEAM)"\n'
        )

        def runner(*_args: object, **_kwargs: object) -> Completed:
            return Completed(output)

        identity = arcium_app.resolve_signing_identity({}, runner)  # type: ignore[arg-type]
        self.assertEqual(identity, "Developer ID Application: Daniel Example (TEAM)")

        with self.assertRaisesRegex(arcium_app.ArciumError, "stable Developer ID"):
            arcium_app.resolve_signing_identity(
                {}, lambda *_args, **_kwargs: Completed('1) AAAA "Apple Development: X"\n')
            )

    def test_profile_migration_is_one_time_and_leaves_source_unchanged(self) -> None:
        source = self.temporary / "net.imput.helium"
        destination = self.temporary / "Arcium"
        source.mkdir()
        (source / "Local State").write_text("original", encoding="utf-8")
        (source / "SingletonLock").symlink_to("stale-browser-lock")

        def no_clone(*_args: object, **_kwargs: object) -> object:
            raise subprocess.CalledProcessError(1, "cp")

        method = arcium_app.initialize_profile(source, destination, copy_runner=no_clone)
        self.assertEqual(method, "fallback-copy")
        self.assertEqual((destination / "Local State").read_text(), "original")
        self.assertFalse((destination / "SingletonLock").exists())
        self.assertTrue((source / "SingletonLock").is_symlink())
        (destination / "Local State").write_text("arcium", encoding="utf-8")
        self.assertEqual(arcium_app.initialize_profile(source, destination), "existing")
        self.assertEqual((source / "Local State").read_text(), "original")
        self.assertEqual((destination / "Local State").read_text(), "arcium")

    def test_process_guard_covers_installed_browsers_and_profiles(self) -> None:
        source = Path("/profiles/helium")
        target = Path("/profiles/arcium")
        install = Path("/Applications/Arcium.app")
        text = "\n".join(
            (
                "100 /Applications/Helium.app/Contents/MacOS/Helium",
                "101 /Applications/Arcium.app/Contents/MacOS/Helium --user-data-dir=/profiles/arcium",
                "102 /tmp/Helium Dev.app/Contents/MacOS/Helium --user-data-dir=/profiles/dev --use-mock-keychain",
            )
        )
        self.assertEqual(
            arcium_app.process_conflicts(
                text,
                source_profile=source,
                target_profile=target,
                install_path=install,
            ),
            ("100", "101"),
        )

        unsafe_dev = (
            "103 /tmp/Helium Dev.app/Contents/MacOS/Helium --no-first-run"
        )
        self.assertEqual(
            arcium_app.process_conflicts(
                unsafe_dev,
                source_profile=source,
                target_profile=target,
                install_path=install,
            ),
            ("103",),
        )

    def test_profile_migration_rejects_non_lock_symlinks(self) -> None:
        source = self.temporary / "source"
        destination = self.temporary / "destination"
        source.mkdir()
        (source / "linked-data").symlink_to("elsewhere")
        with self.assertRaisesRegex(arcium_app.ArciumError, "contains symlinks"):
            arcium_app.initialize_profile(source, destination)
        self.assertFalse(destination.exists())

    def test_launch_uses_real_keychain_path_without_mock_switch(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        calls: list[list[str]] = []

        def popen(argv: list[str], **_kwargs: object) -> FakeProcess:
            calls.append(argv)
            return FakeProcess()

        pid = arcium_app.launch_arcium(app, Path("/profiles/arcium"), popen=popen)  # type: ignore[arg-type]
        self.assertEqual(pid, 4242)
        self.assertEqual(len(calls), 1)
        self.assertIn("--user-data-dir=/profiles/arcium", calls[0])
        self.assertFalse(any("mock-keychain" in value for value in calls[0]))

    def test_update_requires_current_execution_before_profile_changes(self) -> None:
        with patch(
            "arcium_app.require_current_execution",
            side_effect=arcium_app.ExecutionError("rebuild first"),
        ), patch("arcium_app.initialize_profile") as initialize:
            with self.assertRaisesRegex(arcium_app.ArciumError, "rebuild first"):
                arcium_app.update_action(
                    self.temporary,
                    build_root=self.temporary / "build",
                    home=self.temporary / "home",
                    install_path=self.temporary / "Arcium.app",
                    launch=False,
                )
        initialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
