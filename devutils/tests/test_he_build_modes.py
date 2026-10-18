"""Daily installs and named diagnostic apps must use different compiled output."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minichromium import MiniChromium, TOOLS, run  # noqa: E402
from he import apps, builds, records  # noqa: E402
from he.common import HeError, Paths  # noqa: E402

REQUIRED = all(shutil.which(tool) for tool in ("quilt", "ninja", "clang", "clang++", "codesign"))


@unittest.skipUnless(REQUIRED, "needs quilt, ninja, clang, and codesign")
class BuildModesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MiniChromium()
        self.addCleanup(self.m.cleanup)
        self.addCleanup(self._stop)
        self.m.ready()
        self.m.make_app()
        self.daily = Paths(self.m.worktree, self.m.build_dir)
        self.checked = Paths(self.m.worktree, self.m.build_dir, "diagnostics")
        shutil.copytree(self.daily.out, self.checked.out)
        args = self.checked.out / "args.gn"
        args.write_text(args.read_text().replace("dcheck_always_on=false", "dcheck_always_on=true")
                        .replace("enable_expensive_dchecks=false", "enable_expensive_dchecks=true"))
        records.record_stamp(self.checked, "gn-defaults")
        builds.record_completed(self.checked, ["chrome"])

    def _stop(self) -> None:
        for lock in self.m.home.rglob("SingletonLock"):
            if pid := apps.profile_owner(lock.parent):
                os.kill(pid, signal.SIGTERM)

    def test_default_named_app_is_checked_and_daily_is_an_explicit_option(self) -> None:
        checked = json.loads(self.m.he("agent", "run", "--profile", "checked", "--labeled", "--json",
                                       HELIUM_DEV_BUILD_MODE="").stdout)
        daily = json.loads(self.m.he("agent", "run", "--daily", "--profile", "fast", "--labeled", "--json",
                                     HELIUM_DEV_BUILD_MODE="").stdout)
        self.assertTrue(checked["diagnostics"])
        self.assertEqual(checked["build_mode"], "diagnostics")
        self.assertTrue(checked["app"].startswith(str(self.checked.out) + "/"))
        self.assertFalse(daily["diagnostics"])
        self.assertTrue(daily["app"].startswith(str(self.daily.out) + "/"))
        bundles = json.loads((self.daily.state / "dev-bundles.json").read_text())
        self.assertIn("diagnostics:Helium Dev - checked.app", bundles)
        self.assertIn("daily:Helium Dev - fast.app", bundles)

    def test_agent_build_uses_selected_graph_and_records_only_completed_chrome(self) -> None:
        (self.checked.out / builds.RECEIPT).unlink()
        self.m.he("agent", "build", "--diagnostics", "chromedriver")
        self.assertFalse((self.checked.out / builds.RECEIPT).exists())
        self.m.he("agent", "build", "--diagnostics", "chrome")
        self.assertEqual(builds.require_completed(self.checked.out, "diagnostics")["build_mode"], "diagnostics")
        self.assertEqual(builds.require_completed(self.daily.out, "daily")["build_mode"], "daily")

    def test_daily_commands_do_not_change_next_invocations_default(self) -> None:
        script = (f'source "{TOOLS / "dev.sh"}" >/dev/null\n'
                  'he agent arcium status --json >/dev/null\n'
                  'he agent check --daily --json >/dev/null\n'
                  'he agent check --json\n')
        result = run(["bash", "-c", script], env=self.m.env(HELIUM_DEV_BUILD_MODE=""))
        status = json.loads(result.stdout)
        self.assertEqual(status["build_mode"], "diagnostics")
        self.assertEqual(status["output_dir"], str(self.checked.out))

    def test_arcium_forces_daily_even_when_diagnostics_are_selected(self) -> None:
        status = json.loads(self.m.he("agent", "arcium", "status", "--json",
                                     HELIUM_DEV_BUILD_MODE="diagnostics").stdout)
        self.assertEqual(status["build_mode"], "daily")
        self.assertEqual(status["output_dir"], str(self.daily.out))

    def test_stale_receipt_refuses_launch_before_creating_a_profile(self) -> None:
        args = self.checked.out / "args.gn"
        args.write_text(args.read_text() + "# changed after compilation\n")
        result = self.m.he("agent", "run", "--diagnostics", "--profile", "never-created", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no verified completed diagnostics build", result.stderr)
        self.assertFalse((self.m.home / "Library/Application Support/Helium Development").exists())

    def test_unverified_daily_install_is_refused_before_profile_migration(self) -> None:
        (self.daily.out / builds.RECEIPT).unlink()
        install = self.m.root / "Applications/Arcium.app"
        result = self.m.he("agent", "arcium", "--no-build", "--no-launch", check=False,
                           HELIUM_TEST_MODE="1", HELIUM_ARCIUM_TEST_INSTALL_PATH=str(install))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no verified completed daily build", result.stderr)
        self.assertFalse(install.exists())
        self.assertFalse((self.m.home / "Library/Application Support/Arcium").exists())

    def test_gn_stamps_and_configuration_are_checked_per_output(self) -> None:
        self.assertEqual(records.stamp_drift(self.daily), [])
        self.assertEqual(records.stamp_drift(self.checked), [])
        args = self.checked.out / "args.gn"
        args.write_text(args.read_text() + "dcheck_always_on = false\n")
        self.assertTrue(records.stamp_drift(self.checked))
        self.assertEqual(records.stamp_drift(self.daily), [])
        with self.assertRaisesRegex(HeError, "requires dcheck_always_on=true"):
            builds.record_completed(self.checked, ["chrome"])

    def test_conflicting_modes_are_rejected(self) -> None:
        result = self.m.he("agent", "build", "--daily", "--diagnostics", "chrome", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("choose --daily or --diagnostics", result.stderr)

    def test_generated_modes_override_release_check_defaults(self) -> None:
        (self.m.worktree / "flags.macos.gn").write_text(
            "is_debug=false\ndcheck_always_on=false\nenable_expensive_dchecks=false\n")
        for paths in (self.checked, self.daily):
            script = (f'source "{TOOLS / "dev.sh"}" >/dev/null\n'
                      '___helium_setup_gn\n')
            run(["bash", "-c", script], env=self.m.env(HELIUM_DEV_BUILD_MODE=paths.build_mode))
            self.assertEqual(builds.configuration_problems(paths.out, paths.build_mode), [])
            self.assertIn("is_component_build=true", (paths.out / "args.gn").read_text())

    def test_failed_build_does_not_certify_output(self) -> None:
        (self.checked.out / builds.RECEIPT).unlink()
        (self.m.src / "a.cc").write_text("this does not compile\n")
        result = self.m.he("agent", "build", "--diagnostics", "chrome", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.checked.out / builds.RECEIPT).exists())

    def test_raw_launch_refuses_changed_components(self) -> None:
        (self.daily.out / "libone.dylib").touch()
        result = self.m.he("agent", "run", "--daily", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no verified completed daily build", result.stderr)


if __name__ == "__main__":
    unittest.main()
