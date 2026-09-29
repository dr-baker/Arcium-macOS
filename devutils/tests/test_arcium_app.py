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

    def test_component_libraries_are_bundled_for_stable_launch(self) -> None:
        app = self._app("Arcium.app")
        out_dir = self.temporary / "out"
        out_dir.mkdir()
        (out_dir / "args.gn").write_text(
            "is_component_build = true\n", encoding="utf-8"
        )
        (out_dir / "libc++_chrome.dylib").write_bytes(b"runtime")
        (out_dir / "libbase.dylib").write_bytes(b"base")

        count = arcium_app.copy_component_libraries(out_dir, app)

        self.assertEqual(count, 2)
        frameworks = app / "Contents" / "Frameworks"
        self.assertEqual((frameworks / "libc++_chrome.dylib").read_bytes(), b"runtime")
        self.assertEqual((frameworks / "libbase.dylib").read_bytes(), b"base")

    def test_non_component_build_does_not_bundle_loose_libraries(self) -> None:
        app = self._app("Arcium.app")
        out_dir = self.temporary / "out"
        out_dir.mkdir()
        (out_dir / "args.gn").write_text(
            "is_component_build = false\n", encoding="utf-8"
        )
        (out_dir / "libbase.dylib").write_bytes(b"base")

        self.assertEqual(arcium_app.copy_component_libraries(out_dir, app), 0)
        self.assertFalse((app / "Contents" / "Frameworks" / "libbase.dylib").exists())

    def test_signing_identity_requires_one_stable_developer_id(self) -> None:
        output = (
            '  1) AAAA "Apple Development: Example"\n'
            '  2) BBBB "Developer ID Application: Daniel Example (TEAM)"\n'
        )
        with patch.dict(os.environ, {arcium_app.SIGNING_IDENTITY_ENV: ""}), \
             patch("arcium_app.subprocess.run") as run:
            run.return_value.stdout = output
            self.assertEqual(
                arcium_app.resolve_signing_identity(),
                "Developer ID Application: Daniel Example (TEAM)",
            )
            run.assert_called_with(
                ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
                check=True,
                capture_output=True,
                text=True,
            )
            run.return_value.stdout = '1) AAAA "Apple Development: X"\n'
            with self.assertRaisesRegex(arcium_app.ArciumError, "stable Developer ID"):
                arcium_app.resolve_signing_identity()

    def test_signing_identity_respects_explicit_choice(self) -> None:
        identities = (
            '1) AAAA "Developer ID Application: First (TEAM)"\n'
            '2) BBBB "Developer ID Application: Second (TEAM)"\n'
        )
        with patch("arcium_app.subprocess.run") as run:
            run.return_value.stdout = identities
            with patch.dict(os.environ, {arcium_app.SIGNING_IDENTITY_ENV: "Developer ID Application: Second (TEAM)"}):
                self.assertEqual(
                    arcium_app.resolve_signing_identity(),
                    "Developer ID Application: Second (TEAM)",
                )
            with patch.dict(os.environ, {arcium_app.SIGNING_IDENTITY_ENV: "missing"}):
                with self.assertRaisesRegex(arcium_app.ArciumError, "available signing identity"):
                    arcium_app.resolve_signing_identity()

    def test_signing_visits_nested_code_inside_out_with_helper_entitlements(self) -> None:
        app = self._app("Arcium.app")
        frameworks = app / "Contents" / "Frameworks"
        framework = frameworks / "Helium Framework.framework"
        version = framework / "Versions" / "151.0"
        libraries = version / "Libraries"
        libraries.mkdir(parents=True)
        (framework / "Versions" / "Current").symlink_to("151.0")
        (framework / "Libraries").symlink_to("Versions/Current/Libraries")
        binary_paths = [
            app / "Contents" / "MacOS" / "Helium",
            version / "Helium Framework",
            libraries / "libEGL.dylib",
            libraries / "libGLESv2.dylib",
            frameworks / "libbase.dylib",
            version / "Helpers" / "chrome_crashpad_handler",
        ]
        helpers = {}
        for suffix in ("", " (Renderer)", " (GPU)", " (Alerts)"):
            helper = version / "Helpers" / f"Helium Helper{suffix}.app"
            helpers[suffix] = helper
            binary_paths.append(helper / "Contents" / "MacOS" / f"Helium Helper{suffix}")
        for binary in binary_paths:
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture")
        resource = version / "Resources" / "data.bin"
        resource.parent.mkdir()
        resource.write_bytes(b"resource")

        with patch("arcium_app.subprocess.run") as run:
            arcium_app.sign_and_verify(app, "Developer ID Application: Test")

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands[-1],
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        )
        signing = commands[:-1]
        targets = [Path(command[-1]) for command in signing]
        self.assertEqual(targets[-1], app)
        self.assertEqual(len(targets), len(set(targets)))
        self.assertNotIn(resource, targets)
        for binary in binary_paths:
            self.assertIn(binary, targets)
        self.assertIn(framework, targets)
        for target in targets:
            for ancestor in target.parents:
                if ancestor in targets:
                    self.assertLess(targets.index(target), targets.index(ancestor))
        self.assertFalse(any("Current" in target.parts for target in targets))
        self.assertNotIn(framework / "Libraries" / "libEGL.dylib", targets)

        expected = {
            app: "app-entitlements.plist",
            framework: "helper-entitlements.plist",
            frameworks / "Helium Helper.app": "helper-entitlements.plist",
            helpers[""]: "helper-entitlements.plist",
            helpers[" (Renderer)"]: "helper-renderer-entitlements.plist",
            helpers[" (GPU)"]: "helper-gpu-entitlements.plist",
        }
        jit_targets = []
        for command, target in zip(signing, targets):
            self.assertNotIn("--deep", command)
            self.assertEqual(command[command.index("--sign") + 1], "Developer ID Application: Test")
            self.assertEqual(command[command.index("--options") + 1], "runtime")
            if target in expected:
                entitlement_path = Path(command[command.index("--entitlements") + 1])
                self.assertEqual(entitlement_path, DEVUTILS.parent / "entitlements" / expected[target])
                with entitlement_path.open("rb") as handle:
                    entitlements = plistlib.load(handle)
                if entitlements.get("com.apple.security.cs.allow-jit"):
                    jit_targets.append(target)
            else:
                self.assertNotIn("--entitlements", command)
        self.assertCountEqual(jit_targets, [helpers[" (Renderer)"], helpers[" (GPU)"]])

    def test_signing_failure_stops_before_verification(self) -> None:
        app = self._app("Arcium.app")
        with patch(
            "arcium_app.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "codesign"),
        ) as run:
            with self.assertRaisesRegex(arcium_app.ArciumError, "signing or verification failed"):
                arcium_app.sign_and_verify(app, "Developer ID Application: Test")
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("--verify", run.call_args.args[0])

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
        with patch("arcium_app.subprocess.Popen", return_value=FakeProcess()) as spawn:
            pid = arcium_app.launch_arcium(app, Path("/profiles/arcium"))
        self.assertEqual(pid, 4242)
        spawn.assert_called_once()
        arguments = spawn.call_args.args[0]
        self.assertIn("--user-data-dir=/profiles/arcium", arguments)
        self.assertFalse(any("mock-keychain" in value for value in arguments))

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
