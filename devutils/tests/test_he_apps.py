"""Dev profiles, the installed Arcium app, and the agent path, end to end.

A stub browser stands in for Chromium: it holds the profile's SingletonLock
the way Chromium does and quits on SIGTERM. Signing is ad hoc, which the
installer allows only with HELIUM_TEST_MODE=1 and HELIUM_TEST_ALLOW_AD_HOC=1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minichromium import CORE_PATCH, TOOLS, MiniChromium, run  # noqa: E402
from he import apps  # noqa: E402

REQUIRED = all(shutil.which(tool) for tool in ("quilt", "ninja", "clang", "clang++", "codesign"))


def json_tail(text: str) -> dict:
    """The JSON object printed last, after any build output."""
    lines = text.splitlines()
    return json.loads("\n".join(lines[max(i for i, line in enumerate(lines) if line == "{"):]))


def plist(path: Path) -> dict:
    with path.open("rb") as handle:
        return plistlib.load(handle)


@unittest.skipUnless(REQUIRED, "needs quilt, ninja, clang, and codesign")
class AppsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MiniChromium()
        self.addCleanup(self.m.cleanup)
        self.addCleanup(self._kill_stubs)
        self.m.ready()
        self.m.make_app()
        self.support = self.m.home / "Library" / "Application Support"
        self.install = self.m.root / "Applications" / "Arcium.app"
        self.arcium_env = {
            "HELIUM_TEST_MODE": "1",
            "HELIUM_ARCIUM_TEST_INSTALL_PATH": str(self.install),
            "HELIUM_TEST_HELIUM_APP": str(self.m.root / "Applications" / "Helium.app"),
            "ARCIUM_CODESIGN_IDENTITY": "-",
            "HELIUM_TEST_ALLOW_AD_HOC": "1",
            "HELIUM_ARCIUM_QUIT": "term",
        }

    def _kill_stubs(self) -> None:
        for lock in self.m.home.rglob("SingletonLock"):
            pid = apps.profile_owner(lock.parent)
            if pid is not None:
                os.kill(pid, signal.SIGTERM)

    def profile(self, name: str) -> Path:
        return self.support / "Helium Development" / "profiles" / "isolated" / name

    # Dev profiles ------------------------------------------------------------

    def test_named_profile_runs_the_shared_dev_identity(self) -> None:
        result = json.loads(self.m.he("run", "--profile", "alpha", "--json", "--enable-features=Extra").stdout)
        app = self.m.out / "Helium Dev.app"
        self.assertEqual(result["app"], str(app))
        self.assertEqual(plist(app / "Contents" / "Info.plist")["CFBundleIdentifier"], "net.imput.helium.dev")
        helper = app / "Contents" / "Frameworks" / "Helium Helper.app" / "Contents" / "Info.plist"
        self.assertEqual(plist(helper)["CFBundleIdentifier"], "net.imput.helium.helper.dev")
        args = (self.profile("alpha") / "stub-args").read_text().splitlines()
        self.assertIn("--use-mock-keychain", args)
        self.assertIn("--enable-features=HeliumFavoritesAndPins,Extra", args)
        self.assertEqual(apps.profile_owner(self.profile("alpha")), result["pid"])
        self.assertIn("stopped", self.m.he("stop", "--profile", "alpha").stdout)
        self.assertIsNone(apps.profile_owner(self.profile("alpha")))

    def test_labeled_profiles_run_side_by_side_with_their_own_bundles(self) -> None:
        self.m.he("run", "--profile", "alpha")
        beta = json.loads(self.m.he("run", "--profile", "beta", "--labeled", "--json").stdout)
        labeled = self.m.out / "Helium Dev - beta.app"
        self.assertEqual(beta["app"], str(labeled))
        identifier = plist(labeled / "Contents" / "Info.plist")["CFBundleIdentifier"]
        self.assertRegex(identifier, r"^net\.imput\.helium\.dev\.[0-9a-f]{16}$")
        self.assertLess(len(identifier) + 70, 128)
        self.assertIsNotNone(apps.profile_owner(self.profile("alpha")))
        self.assertIsNotNone(apps.profile_owner(self.profile("beta")))

    def test_profile_flags_and_existing_profiles_are_refused(self) -> None:
        refused = self.m.he("run", "--profile", "alpha", "--user-data-dir=/tmp/x", check=False)
        self.assertIn("set by he run", refused.stderr)
        self.m.he("run", "--profile", "alpha")
        again = self.m.he("run", "--profile", "alpha", check=False)
        self.assertIn("already running", again.stderr)
        self.m.he("stop", "--profile", "alpha")
        new = self.m.he("run", "--profile", "gamma", "--new", check=False)
        self.assertEqual(new.returncode, 0, new.stderr)
        self.m.he("stop", "--profile", "gamma")
        self.assertIn("already exists", self.m.he("run", "--profile", "gamma", "--new", check=False).stderr)
        self.assertNotEqual(self.m.he("run", "--fresh", "delta", check=False).returncode, 0)

    def test_new_profiles_start_with_the_sidebar_items_and_tabs(self) -> None:
        self.m.he("run", "--profile", "lived-in")
        prefs = json.loads((self.profile("lived-in") / "Default" / "Preferences").read_text())
        self.assertEqual(prefs["helium"]["browser"]["layout"], 2)
        self.assertEqual(len(prefs["helium"]["favorites"]), 4)
        self.assertEqual(prefs["helium"]["spaces"][0]["pins"][2]["type"], "folder")
        args = (self.profile("lived-in") / "stub-args").read_text().splitlines()
        self.assertIn("https://example.com/", args)
        self.m.he("stop", "--profile", "lived-in")
        self.m.he("run", "--profile", "lived-in")
        self.assertNotIn("https://example.com/",
                         (self.profile("lived-in") / "stub-args").read_text().splitlines())

    def test_empty_profiles_start_blank(self) -> None:
        self.m.he("run", "--profile", "blank", "--empty")
        self.assertFalse((self.profile("blank") / "Default" / "Preferences").exists())
        self.assertNotIn("https://example.com/",
                         (self.profile("blank") / "stub-args").read_text().splitlines())

    def test_seeding_copies_a_stopped_profile_once(self) -> None:
        seed = self.m.root / "seed"
        (seed / "Default").mkdir(parents=True)
        (seed / "Default" / "Bookmarks").write_text("marks")
        self.m.he("run", "--profile", "seeded", "--seed-from", str(seed))
        self.assertEqual((self.profile("seeded") / "Default" / "Bookmarks").read_text(), "marks")

    def test_a_running_dev_app_is_not_replaced_by_a_new_build(self) -> None:
        self.m.he("run", "--profile", "alpha")
        (self.m.out / "Helium.app" / "Contents" / "Resources").mkdir()
        (self.m.out / "Helium.app" / "Contents" / "Resources" / "new").write_text("rebuilt")
        refused = self.m.he("run", "--profile", "other", check=False)
        self.assertIn("running an older build", refused.stderr)

    def test_dev_bundles_do_not_count_as_build_output(self) -> None:
        self.m.he("pop")
        self.m.he("run", "--profile", "alpha")
        result = self.m.he("push")
        self.assertIn("restored timestamps", result.stderr)

    def test_stop_refuses_a_profile_owned_by_something_else(self) -> None:
        profile = self.profile("foreign")
        profile.mkdir(parents=True)
        stub = subprocess.Popen([str(self.m.root / "stub" / "browser"), f"--user-data-dir={profile}"])
        self.addCleanup(lambda: (stub.kill(), stub.wait()))
        for _ in range(50):
            if apps.profile_owner(profile):
                break
            time.sleep(0.05)
        refused = self.m.he("stop", "--profile", "foreign", check=False)
        self.assertIn("not a Dev app", refused.stderr)

    # Installed Arcium -----------------------------------------------------------

    def _seed_helium_profile(self) -> None:
        helium = self.support / "net.imput.helium" / "Default"
        helium.mkdir(parents=True)
        (helium / "History").write_text("visits")

    def test_install_packages_signs_migrates_and_launches(self) -> None:
        self._seed_helium_profile()
        result = self.m.he("arcium", "--json", **self.arcium_env)
        data = json_tail(result.stdout)
        info = plist(self.install / "Contents" / "Info.plist")
        self.assertEqual(info["CFBundleIdentifier"], "net.imput.arcium")
        self.assertEqual(info["CrProductDirName"], "Arcium")
        helper = self.install / "Contents" / "Frameworks" / "Helium Helper.app" / "Contents" / "Info.plist"
        self.assertEqual(plist(helper)["CFBundleIdentifier"], "net.imput.arcium.helper")
        self.assertTrue((self.install / "Contents" / "Frameworks" / "libone.dylib").is_file())
        self.assertEqual(data["component_libraries"], 2)
        self.assertEqual((self.support / "Arcium" / "Default" / "History").read_text(), "visits")
        self.assertEqual(apps.profile_owner(self.support / "Arcium"), data["pid"])
        status = json.loads(self.m.he("arcium", "status", "--json", **self.arcium_env).stdout)
        self.assertTrue(status["signature_ok"])
        self.assertTrue(status["running"]["installed"])
        self.assertTrue(status["matches_build"])
        (self.m.out / "libone.dylib").touch()
        relinked = json.loads(self.m.he("arcium", "status", "--json", **self.arcium_env).stdout)
        self.assertFalse(relinked["matches_build"])

    def test_install_restarts_a_running_arcium(self) -> None:
        self._seed_helium_profile()
        first = json_tail(self.m.he("arcium", "--json", **self.arcium_env).stdout)["pid"]
        self.assertNotEqual(self.m.he("arcium", "iterate", **self.arcium_env, check=False).returncode, 0)
        second = json_tail(self.m.he("arcium", "--json", **self.arcium_env).stdout)
        self.assertTrue(second["restarted"])
        self.assertNotEqual(second["pid"], first)
        self.assertFalse(apps.alive(first))

    def test_failure_before_publication_keeps_the_installed_app(self) -> None:
        self._seed_helium_profile()
        self.m.he("arcium", "--no-launch", **self.arcium_env)
        before = (self.install / "Contents" / "Info.plist").read_bytes()
        failed = self.m.he("arcium", **{**self.arcium_env, "ARCIUM_CODESIGN_IDENTITY": "Nobody"}, check=False)
        self.assertIn("names no available signing identity", failed.stderr)
        self.assertEqual((self.install / "Contents" / "Info.plist").read_bytes(), before)
        self.assertEqual(list(self.install.parent.glob(".Arcium.app.*")), [])

    def test_failure_after_publication_keeps_both_bundles_and_the_profile(self) -> None:
        self._seed_helium_profile()
        self.m.he("arcium", "--no-launch", **self.arcium_env)
        broken = self.m.out / "Helium.app" / "Contents" / "MacOS" / "Helium"
        broken.unlink()
        broken.write_text("#!/bin/sh\nexit 1\n")
        broken.chmod(0o755)
        history = (self.support / "Arcium" / "Default" / "History").read_text()
        failed = self.m.he("arcium", "--no-build", **self.arcium_env, check=False)
        self.assertIn("did not start cleanly", failed.stderr)
        self.assertIn("Previous bundle kept at", failed.stderr)
        self.assertEqual(len(list(self.install.parent.glob(".Arcium.app.previous-*"))), 1)
        self.assertEqual((self.install / "Contents" / "MacOS" / "Helium").read_text(), "#!/bin/sh\nexit 1\n")
        self.assertEqual((self.support / "Arcium" / "Default" / "History").read_text(), history)

    def test_install_refuses_a_mock_keychain_arcium(self) -> None:
        self._seed_helium_profile()
        self.m.he("arcium", "--no-launch", **self.arcium_env)
        executable = self.install / "Contents" / "MacOS" / "Helium"
        stub = subprocess.Popen([str(executable), f"--user-data-dir={self.support / 'Arcium'}", "--use-mock-keychain"])
        self.addCleanup(lambda: (stub.kill(), stub.wait()))
        for _ in range(50):
            if apps.profile_owner(self.support / "Arcium"):
                break
            time.sleep(0.05)
        refused = self.m.he("arcium", **self.arcium_env, check=False)
        self.assertIn("mock Keychain", refused.stderr)

    def test_install_needs_a_stable_signing_identity(self) -> None:
        env = {**self.arcium_env, "ARCIUM_CODESIGN_IDENTITY": "-", "HELIUM_TEST_ALLOW_AD_HOC": "0"}
        refused = self.m.he("arcium", "--no-build", **env, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse(self.install.exists())

    # Review round 2 regressions ----------------------------------------------------

    def test_single_dash_profile_switches_are_refused(self) -> None:
        for flag in ("-user-data-dir=/tmp/x", "--User-Data-Dir=/tmp/x", "-use-mock-keychain"):
            refused = self.m.he("run", "--profile", "alpha", flag, check=False)
            self.assertIn("is set by he run", refused.stderr, flag)
        self.assertIsNone(apps.profile_owner(self.profile("alpha")))

    def test_symlinked_profiles_are_refused(self) -> None:
        helium = self.support / "net.imput.helium"
        helium.mkdir(parents=True)
        (self.support / "Arcium").symlink_to(helium)
        refused = self.m.he("arcium", "--no-build", **self.arcium_env, check=False)
        self.assertIn("symlink", refused.stderr)
        self.profile("linked").parent.mkdir(parents=True)
        self.profile("linked").symlink_to(helium)
        refused = self.m.he("run", "--profile", "linked", check=False)
        self.assertIn("symlink", refused.stderr)

    def test_a_lingering_crash_handler_does_not_block_an_update(self) -> None:
        self._seed_helium_profile()
        self.m.he("arcium", "--no-launch", "--no-build", **self.arcium_env)
        handler = self.install / "Contents/Helpers/chrome_crashpad_handler"
        crashpad = subprocess.Popen([str(handler), "--monitor-self"])
        self.addCleanup(lambda: (crashpad.kill(), crashpad.wait()))
        time.sleep(0.3)
        self.m.he("arcium", "--no-build", **self.arcium_env)

    def test_install_refuses_other_instances_of_the_installed_app(self) -> None:
        self._seed_helium_profile()
        self.m.he("arcium", "--no-launch", "--no-build", **self.arcium_env)
        other = self.m.root / "other-profile"
        other.mkdir()
        stub = subprocess.Popen([str(self.install / "Contents" / "MacOS" / "Helium"), f"--user-data-dir={other}"])
        self.addCleanup(lambda: (stub.kill(), stub.wait()))
        time.sleep(0.3)
        refused = self.m.he("arcium", "--no-build", **self.arcium_env, check=False)
        self.assertIn("other Arcium instances", refused.stderr)

    def test_failed_agent_build_does_not_install(self) -> None:
        (self.m.src / "a.cc").write_text("this does not compile\n")
        failed = self.m.he("agent", "arcium", "--approved", **self.arcium_env, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.install.exists())

    def test_status_is_unlocked_and_read_only(self) -> None:
        status = json.loads(self.m.he("arcium", "status", "--json", **self.arcium_env).stdout)
        self.assertFalse(status["installed"])
        self.assertFalse(self.install.exists())

    def test_install_refuses_to_move_aside_a_non_arcium_directory(self) -> None:
        self.install.mkdir(parents=True)
        (self.install / "keep").write_text("mine")
        self._seed_helium_profile()
        refused = self.m.he("arcium", "--no-build", **self.arcium_env, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual((self.install / "keep").read_text(), "mine")

    def test_stop_refuses_a_reused_lock_pid(self) -> None:
        beta = json.loads(self.m.he("run", "--profile", "beta", "--json").stdout)
        alpha = self.profile("alpha")
        alpha.mkdir(parents=True)
        (alpha / "SingletonLock").symlink_to(f"{__import__('socket').gethostname()}-{beta['pid']}")
        refused = self.m.he("stop", "--profile", "alpha", check=False)
        self.assertIn("was not started on it", refused.stderr)
        self.assertTrue(apps.alive(beta["pid"]))

    def test_migration_refuses_a_profile_locked_by_another_host(self) -> None:
        self._seed_helium_profile()
        (self.support / "net.imput.helium" / "SingletonLock").symlink_to("other-host.local-12345")
        refused = self.m.he("arcium", "--no-build", **self.arcium_env, check=False)
        self.assertIn("another host", refused.stderr)
        self.assertFalse((self.support / "Arcium").exists())

    # Agent path -------------------------------------------------------------------

    def test_agent_build_needs_targets_and_respects_the_budget(self) -> None:
        self.assertIn("explicit targets", self.m.he("agent", "build", check=False).stderr)
        (self.m.src / "a.cc").touch()
        (self.m.src / "b.cc").touch()
        refused = self.m.he("agent", "build", "chrome", "--edge-budget", "1", check=False)
        self.assertIn("above the budget", refused.stderr)
        self.assertIn("First planned commands", refused.stderr)
        self.assertTrue((self.m.build_dir / ".arcium" / "last-plan.txt").is_file())
        self.m.he("agent", "build", "chrome", "--edge-budget", "1", "--approved")
        self.assertIn("--approved belongs to he agent build", self.m.he("build", "--approved", check=False).stderr)

    def test_agent_build_refuses_a_pending_snapshot_and_strict_problems(self) -> None:
        self.m.he("pop")
        self.assertIn("snapshot is pending", self.m.he("agent", "build", "chrome", check=False).stderr)
        self.m.he("push")
        (self.m.worktree / "resources" / "icon.txt").write_text("changed\n")
        self.assertIn("he check reports problems", self.m.he("agent", "build", "chrome", check=False).stderr)

    def test_check_json_reports_state(self) -> None:
        status = json.loads(self.m.he("check", "--json").stdout)
        self.assertEqual(status["patches"]["applied"], status["patches"]["series"])
        self.assertFalse(status["timestamp_snapshot_pending"])
        self.assertEqual(status["problems"], [])

    def test_agent_prefix_passes_other_commands_through(self) -> None:
        self.assertIn("ok:", self.m.he("agent", "check").stdout)
        self.m.he("agent", "replay")

    def test_agent_arcium_needs_approval_only_to_restart(self) -> None:
        self._seed_helium_profile()
        first = json_tail(self.m.he("agent", "arcium", "--json", **self.arcium_env).stdout)
        refused = self.m.he("agent", "arcium", **self.arcium_env, check=False)
        self.assertIn("pass --approved", refused.stderr)
        self.assertTrue(apps.alive(first["pid"]))
        self.m.he("agent", "arcium", "--approved", **self.arcium_env)
        self.assertFalse(apps.alive(first["pid"]))


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class RemoteExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MiniChromium()
        self.addCleanup(self.m.cleanup)
        siso = self.m.src / "build" / "config" / "siso"
        siso.mkdir(parents=True)
        (siso / "configure_siso.py").write_text(
            "import sys, pathlib\npathlib.Path(sys.argv[0]).with_name('args.txt').write_text(' '.join(sys.argv[1:]))\n")
        (self.m.worktree / "helium-chromium" / "flags.gn").write_text("is_official_build=true\n")

    def call(self, function: str, **env: str) -> subprocess.CompletedProcess:
        script = f'source "{TOOLS / "dev.sh"}" >/dev/null && {function}'
        return run(["bash", "-c", script], env=self.m.env(**env), check=False)

    def test_remote_backend_uses_nativelink_and_keeps_tls(self) -> None:
        result = self.call("___helium_configure_siso", SISO_REAPI_ADDRESS="grpc.example:443")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.m.src / "build/config/siso/args.txt").read_text()
        self.assertIn("--reapi_address=grpc.example:443", args)
        self.assertIn("--reapi_instance=main", args)
        self.assertIn("--reapi_backend_config_path=nativelink.star", args)
        self.call("___helium_setup_gn", SISO_REAPI_ADDRESS="grpc.example:443")
        gn = (self.m.out / "args.gn").read_text()
        self.assertIn("use_remoteexec = true", gn)
        self.assertNotIn("cc_wrapper", gn)

    def test_local_backend_regenerates_chromium_defaults(self) -> None:
        self.call("___helium_configure_siso")
        self.assertIn("--rbe_instance=", (self.m.src / "build/config/siso/args.txt").read_text())

    def test_plaintext_setting_is_validated(self) -> None:
        result = self.call("___helium_configure_siso", SISO_REAPI_ADDRESS="x:1", RBE_service_no_security="yes")
        self.assertIn("must be true or false", result.stderr)


if __name__ == "__main__":
    unittest.main()
