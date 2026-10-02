"""Focused tests for the stable installed Arcium workflow."""

from __future__ import annotations

import os
import itertools
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import arcium_app  # noqa: E402
from devutils.tests.test_build_receipt import material_fixture  # noqa: E402


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
        self.assertEqual(root["CrProductDirName"], arcium_app.DEFAULT_PROFILE_NAME)
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

    def test_existing_profile_does_not_depend_on_original_helium(self) -> None:
        source = self.temporary / "source"
        target = self.temporary / "profile"
        install = self.temporary / "Arcium.app"
        snapshot = "321 /Applications/Helium.app/Contents/MacOS/Helium"
        with patch("arcium_app.live_singleton_owner", side_effect=lambda spec: 321 if spec.user_data_dir == source else None):
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app.require_closed(source_profile=source, target_profile=target, install_path=install, ps_text=snapshot)
            arcium_app.require_closed(source_profile=None, target_profile=target, install_path=install, ps_text=snapshot)
            self.assertIsNone(arcium_app.restart_candidate(snapshot, source_profile=None, target_profile=target, install_path=install))

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

    def test_launch_preserves_profile_selection_and_crash_recovery(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        with patch("arcium_app.subprocess.Popen", return_value=FakeProcess()) as spawn:
            arcium_app.launch_arcium(app, Path("/profiles/arcium"))
        args = spawn.call_args.args[0]
        self.assertFalse(any(arg.startswith("--profile-directory") for arg in args))
        self.assertNotIn("--disable-session-crashed-bubble", args)

    def test_install_and_launch_reject_wrong_default_profile(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        plist = app / "Contents/Info.plist"
        for value in (None, "net.imput.helium", "../Arcium", "/tmp/Arcium"):
            with self.subTest(value=value):
                info = plistlib.loads(plist.read_bytes())
                info["CrProductDirName"] = value or ""
                plist.write_bytes(plistlib.dumps(info))
                with patch("arcium_app.subprocess.run") as run, patch("arcium_app.subprocess.Popen") as spawn:
                    with self.assertRaisesRegex(arcium_app.ArciumError, "default profile"):
                        arcium_app.verify_installed_arcium(app)
                    with self.assertRaisesRegex(arcium_app.ArciumError, "default profile"):
                        arcium_app.launch_arcium(app, Path("/profiles/arcium"))
                run.assert_not_called()
                spawn.assert_not_called()

    def test_dock_launch_requires_bundle_identity_and_profile_owner(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        profile = self.temporary / "Arcium"
        args = dict(source_profile=self.temporary / "source", target_profile=profile, install_path=app)
        snapshot = f"123 {app}/Contents/MacOS/Helium --flag-switches-begin --flag-switches-end"
        for owner in (123, 456, None):
            with self.subTest(owner=owner), patch("arcium_app.arcium_profile_path", return_value=profile), \
                 patch("arcium_app.live_singleton_owner", side_effect=lambda spec: owner if spec.user_data_dir == profile else None):
                if owner == 123:
                    self.assertEqual(arcium_app.restart_candidate(snapshot, **args), 123)
                else:
                    with self.assertRaises(arcium_app.ArciumError):
                        arcium_app.restart_candidate(snapshot, **args)
        with patch("arcium_app.arcium_profile_path", return_value=profile), \
             patch("arcium_app.live_singleton_owner", side_effect=lambda spec: 123 if spec.user_data_dir == profile else None):
            for suffix in (" --user-data-dir=/wrong", " --type=renderer", " --use-mock-keychain"):
                with self.subTest(suffix=suffix), self.assertRaises(arcium_app.ArciumError):
                    arcium_app.restart_candidate(snapshot + suffix, **args)
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            info["CrProductDirName"] = "net.imput.helium"
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app.restart_candidate(snapshot, **args)

    def test_status_distinguishes_stopped_correct_and_wrong_profile(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        profile = self.temporary / "Arcium"
        command = f"123 {app}/Contents/MacOS/Helium"
        for suffix, owner, state, ok in (
            (None, None, "stopped", True),
            ("", 123, "running", True),
            (" --user-data-dir=/other", None, "profile-mismatch", False),
            ("", 456, "profile-mismatch", False),
            (" --use-mock-keychain", 123, "running", False),
        ):
            with self.subTest(suffix=suffix, owner=owner), \
                 patch("arcium_app.arcium_profile_path", return_value=profile), \
                 patch("arcium_app.subprocess.run"), \
                 patch("arcium_app._ps_snapshot", return_value="" if suffix is None else command + suffix), \
                 patch("arcium_app.live_singleton_owner", return_value=owner):
                result = arcium_app.status_action(install_path=app)
                self.assertEqual(result["state"], state)
                self.assertEqual(result["ok"], ok)

    def test_renamed_executable_is_recognized_by_status_and_restart(self) -> None:
        app = self._app("Arcium.app")
        arcium_app.rewrite_arcium_metadata(app)
        plist = app / "Contents/Info.plist"
        info = plistlib.loads(plist.read_bytes())
        info["CFBundleExecutable"] = "Arcium"
        plist.write_bytes(plistlib.dumps(info))
        (app / "Contents/MacOS/Helium").rename(app / "Contents/MacOS/Arcium")
        profile = self.temporary / "profile"
        snapshot = f"123 {app}/Contents/MacOS/Arcium --user-data-dir={profile}"
        with patch("arcium_app._ps_snapshot", return_value=snapshot), \
             patch("arcium_app.arcium_profile_path", return_value=profile), \
             patch("arcium_app.live_singleton_owner", return_value=123), \
             patch("arcium_app.subprocess.run") as run:
            self.assertEqual(arcium_app.restart_candidate(snapshot, source_profile=None, target_profile=profile, install_path=app), 123)
            self.assertEqual(arcium_app.status_action(install_path=app)["state"], "running")
            arcium_app.request_graceful_quit(123, app)
            self.assertEqual(run.call_args.args[0][-2], str(app / "Contents/MacOS/Arcium"))

    def test_update_requires_current_execution_before_profile_changes(self) -> None:
        material_fixture(self.temporary)
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

    def _profiles(self) -> dict[str, Path]:
        if not (self.temporary / "Arcium.app").exists():
            arcium_app.rewrite_arcium_metadata(self._app("Arcium.app"))
        return dict(source_profile=self.temporary / "source", target_profile=self.temporary / "profile",
                    install_path=self.temporary / "Arcium.app")

    def _running(self, pid: int = 123) -> str:
        args = self._profiles()
        return f"{pid} {args['install_path']}/Contents/MacOS/Helium --user-data-dir={args['target_profile']}"

    def test_restart_rejects_other_profiles_and_ambiguous_main(self) -> None:
        args = self._profiles()
        self.assertEqual(arcium_app.restart_candidate(self._running(), **args), 123)
        for snapshot in (
            self._running() + "\n" + self._running(456),
            self._running().replace(str(args["target_profile"]), str(args["target_profile"]) + "-other"),
            self._running() + "\n456 /Applications/Helium.app/Contents/MacOS/Helium",
            self._running() + " --type=renderer",
        ):
            with self.subTest(snapshot=snapshot), self.assertRaises(arcium_app.ArciumError):
                arcium_app.restart_candidate(snapshot, **args)

    def test_live_profile_lock_blocks_even_when_process_snapshot_is_empty(self) -> None:
        with patch("arcium_app.live_singleton_owner", return_value=987):
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app.require_closed(**self._profiles(), ps_text="")
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app.restart_candidate("", **self._profiles())

    def test_changed_pid_is_not_quit(self) -> None:
        with patch("arcium_app._ps_snapshot", side_effect=[self._running(), self._running(456)]), \
             patch("arcium_app.request_graceful_quit") as request:
            with self.assertRaisesRegex(arcium_app.ArciumError, "process changed"):
                arcium_app.quit_for_restart(**self._profiles())
        request.assert_not_called()

    def test_quit_waits_for_exit_without_force(self) -> None:
        with patch("arcium_app._ps_snapshot", side_effect=[self._running(), self._running(), ""]), \
             patch("arcium_app.request_graceful_quit") as request:
            arcium_app.quit_for_restart(**self._profiles())
        request.assert_called_once_with(123, self._profiles()["install_path"])

    def test_cancelled_quit_stops_handoff(self) -> None:
        with patch("arcium_app._ps_snapshot", return_value=self._running()), \
             patch("arcium_app.request_graceful_quit"):
            with self.assertRaisesRegex(arcium_app.ArciumError, "not replaced"):
                arcium_app.quit_for_restart(**self._profiles(), timeout=0)

    def test_launch_requires_expected_process_and_live_profile_ownership(self) -> None:
        args = self._profiles()
        for observed_pid, owner in ((123, 123), (456, 123), (123, 456), (123, None)):
            with self.subTest(pid=observed_pid, owner=owner), \
                 patch("arcium_app._ps_snapshot", return_value=self._running(observed_pid)), \
                 patch("arcium_app.live_singleton_owner", return_value=owner), \
                 patch("arcium_app.time.monotonic", side_effect=itertools.count(0, .25)), \
                 patch("arcium_app.time.sleep"):
                if observed_pid == owner == 123:
                    arcium_app.verify_arcium_launch(args["install_path"], args["target_profile"], 123)
                else:
                    with self.assertRaisesRegex(arcium_app.ArciumError, "expected process"):
                        arcium_app.verify_arcium_launch(args["install_path"], args["target_profile"], 123)

    def test_install_verification_failure_restores_previous_directory(self) -> None:
        old = self.temporary / "installed"
        old.mkdir()
        (old / "version").write_text("old")
        candidate = self.temporary / "candidate"
        candidate.mkdir()
        (candidate / "version").write_text("new")

        def fail(path: Path) -> None:
            self.assertEqual((path / "version").read_text(), "new")
            raise arcium_app.ArciumError("bad signature")

        with self.assertRaisesRegex(arcium_app.ArciumError, "bad signature"):
            arcium_app._replace_directory(candidate, old, verifier=fail)
        self.assertEqual((old / "version").read_text(), "old")

    def test_failed_atomic_replace_restores_previous_directory(self) -> None:
        old = self.temporary / "installed"
        old.mkdir()
        (old / "version").write_text("old")
        candidate = self.temporary / "candidate"
        candidate.mkdir()
        replace = os.replace

        def fail(source: Path, target: Path) -> None:
            if source == candidate:
                raise OSError("rename failed")
            replace(source, target)

        with patch("arcium_app.os.replace", side_effect=fail), self.assertRaises(OSError):
            arcium_app._replace_directory(candidate, old)
        self.assertEqual((old / "version").read_text(), "old")

    def _update_fixture(self, stack: ExitStack):
        material_fixture(self.temporary)
        candidate = self._app("candidate.app")
        arcium_app.rewrite_arcium_metadata(candidate)
        destination = self.temporary / "installed.app"
        shutil.copytree(candidate, destination)
        (destination / "version").write_text("old")
        (candidate / "version").write_text("new")
        home = self.temporary / "home"
        arcium_app.arcium_profile_path(home).mkdir(parents=True)
        paths = SimpleNamespace(worktree=self.temporary, source_dir=self.temporary / "build/src")
        mocks = {}
        for name, values in {
            "require_current_execution": {},
            "resolve_signing_identity": {"return_value": "Developer ID Application: Test"},
            "_package_arcium_locked": {"return_value": {"app_path": str(candidate)}},
            "verify_installed_arcium": {},
            "_ps_snapshot": {"return_value": ""},
            "quit_for_restart": {},
            "launch_arcium": {"return_value": 4242},
            "verify_arcium_launch": {},
        }.items():
            mocks[name] = stack.enter_context(patch("arcium_app." + name, **values))
        return paths, home, destination, mocks

    def test_preparation_failure_never_quits_or_replaces(self) -> None:
        for failing in ("_package_arcium_locked", "verify_installed_arcium"):
            with self.subTest(failing=failing), ExitStack() as stack:
                # Each subtest needs distinct fixtures.
                with tempfile.TemporaryDirectory() as temporary:
                    original = self.temporary
                    self.temporary = Path(temporary)
                    try:
                        paths, home, destination, mocks = self._update_fixture(stack)
                        mocks[failing].side_effect = arcium_app.ArciumError("prepare failed")
                        with self.assertRaisesRegex(arcium_app.ArciumError, "prepare failed"):
                            arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True)
                        mocks["quit_for_restart"].assert_not_called()
                        self.assertEqual((destination / "version").read_text(), "old")
                    finally:
                        self.temporary = original

    def test_handoff_prepares_then_quits_and_verifies_launch(self) -> None:
        with ExitStack() as stack:
            paths, home, destination, mocks = self._update_fixture(stack)
            events = []
            mocks["verify_installed_arcium"].side_effect = lambda path: events.append("verify-installed" if path == destination else "verify-staged")
            mocks["quit_for_restart"].side_effect = lambda **kwargs: events.append("quit")
            mocks["verify_arcium_launch"].side_effect = lambda *args: events.append("verify-launch")
            result = arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True)
            self.assertEqual(events, ["verify-staged", "quit", "verify-installed", "verify-launch"])
            self.assertEqual(result["pid"], 4242)
            self.assertEqual((destination / "version").read_text(), "new")
            self.assertFalse(list(destination.parent.glob(".installed.app.previous-*")))

    def test_failed_launch_retains_previous_bundle_without_profile_rollback(self) -> None:
        with ExitStack() as stack:
            paths, home, destination, mocks = self._update_fixture(stack)
            mocks["launch_arcium"].side_effect = OSError("launch failed")
            with self.assertRaisesRegex(arcium_app.ArciumError, "Previous bundle retained"):
                arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True)
            previous, = destination.parent.glob(".installed.app.previous-*")
            self.assertEqual((previous / "version").read_text(), "old")

    def test_fresh_conflict_after_quit_prevents_install(self) -> None:
        with ExitStack() as stack:
            paths, home, destination, mocks = self._update_fixture(stack)
            mocks["quit_for_restart"].side_effect = lambda **kwargs: setattr(
                mocks["_ps_snapshot"], "return_value", f"456 {destination}/Contents/MacOS/Helium")
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True, ps_text="")
            self.assertEqual((destination / "version").read_text(), "old")
            mocks["launch_arcium"].assert_not_called()

    def test_update_existing_profile_allows_independent_helium(self) -> None:
        with ExitStack() as stack:
            paths, home, destination, mocks = self._update_fixture(stack)
            mocks["_ps_snapshot"].return_value = "321 /Applications/Helium.app/Contents/MacOS/Helium"
            stack.enter_context(patch("arcium_app.live_singleton_owner", side_effect=lambda spec: 321 if spec.user_data_dir == arcium_app.source_profile_path(home) else None))
            result = arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True)
            self.assertTrue(result["ok"])
            mocks["launch_arcium"].assert_called_once()

    def test_default_update_refuses_running_browser_before_packaging(self) -> None:
        with ExitStack() as stack:
            paths, home, destination, mocks = self._update_fixture(stack)
            mocks["_ps_snapshot"].return_value = f"123 {destination}/Contents/MacOS/Helium"
            with self.assertRaises(arcium_app.ArciumError):
                arcium_app._update_action_locked(paths, home=home, install_path=destination)
            mocks["_package_arcium_locked"].assert_not_called()
            mocks["quit_for_restart"].assert_not_called()

    def test_profile_failure_and_cancelled_quit_never_replace_app(self) -> None:
        for failure in ("initialize_profile", "quit_for_restart"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                original = self.temporary
                self.temporary = Path(temporary)
                try:
                    paths, home, destination, mocks = self._update_fixture(stack)
                    stack.enter_context(patch("arcium_app." + failure, side_effect=arcium_app.ArciumError("blocked")))
                    with self.assertRaisesRegex(arcium_app.ArciumError, "blocked"):
                        arcium_app._update_action_locked(paths, home=home, install_path=destination, restart=True)
                    self.assertEqual((destination / "version").read_text(), "old")
                    mocks["launch_arcium"].assert_not_called()
                    if failure == "initialize_profile":
                        mocks["quit_for_restart"].assert_not_called()
                finally:
                    self.temporary = original


if __name__ == "__main__":
    unittest.main()
