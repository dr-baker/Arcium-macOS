"""Exercise the real shell orchestrator with inert stage implementations."""

from pathlib import Path
import shlex
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ArciumIterateTests(unittest.TestCase):
    def run_workflow(self, *arguments: str, fail: str = ""):
        script = f"source {shlex.quote(str(ROOT / 'dev.sh'))}; " + '''
stage() { print -r -- "$*"; [ "$1" != "$FAIL_STAGE" ]; }
___helium_python() { shift; stage python "$@"; }
___helium_check() { stage check; }
___helium_require_replay_proof() { stage replay-proof; }
___helium_configure_inner() { stage configure; }
___helium_build_full() { stage build-full "$@"; }
___helium_relink() { stage relink "$@"; }
___helium_lane_transaction() {
    stage lane-lock "$@" || return
    shift
    ___helium_arcium_inner "$@"
}
FAIL_STAGE="$1"
shift
_root_dir=/fixture
_build_dir=/fixture/build
_helium_harness_root=/fixture
___helium_arcium "$@"
'''
        return subprocess.run(["zsh", "-c", script, "test", fail, *arguments],
                              capture_output=True, text=True, check=False)

    def test_status_does_not_require_a_build_lane_or_restart(self):
        result = self.run_workflow("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["python --root /fixture status --json"])

    def test_iteration_retains_lock_and_full_build_options(self):
        result = self.run_workflow("iterate", "--approved", "--edge-budget", "123", "--jobs", "2", "--allow-internal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "lane-lock arcium iterate --approved --edge-budget 123 --jobs 2 --allow-internal",
            "python --root /fixture --build-root /fixture/build preflight --restart",
            "check", "replay-proof", "configure",
            "build-full --approved --edge-budget 123 --jobs 2 --allow-internal",
            "python --root /fixture --build-root /fixture/build update --restart",
        ])

    def test_failure_never_reaches_later_stages(self):
        for stage in ("lane-lock", "python", "check", "replay-proof", "configure", "build-full"):
            with self.subTest(stage=stage):
                result = self.run_workflow("iterate", "--approved", fail=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("update --restart", result.stdout)
                if stage in ("check", "replay-proof"):
                    self.assertNotIn("configure", result.stdout)

    def test_invalid_options_and_missing_approval_do_no_work(self):
        for args in ((), ("--edge-budget", "10"), ("--approved", "--edge-budget"),
                     ("--approved", "--edge-budget", "-1"), ("--approved", "chrome"),
                     ("--approved", "--force"), ("--approved", "--jobs"),
                     ("--approved", "--jobs", "0"), ("--approved", "--jobs", "000"),
                     ("--approved", "--jobs", "-1"), ("--approved", "--jobs", "1.5"),
                     ("--approved", "--jobs", "many")):
            with self.subTest(args=args):
                result = self.run_workflow("iterate", *args)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("python", result.stdout)
                self.assertNotIn("configure", result.stdout)

    def test_default_arcium_does_not_request_restart_or_full_build(self):
        result = self.run_workflow()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("relink --resources", result.stdout)
        self.assertNotIn("--restart", result.stdout)
        self.assertNotIn("build-full", result.stdout)

    def test_default_arcium_rejects_stale_replay_before_gn(self):
        result = self.run_workflow(fail="replay-proof")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("configure", result.stdout)
        self.assertNotIn("relink", result.stdout)


if __name__ == "__main__":
    unittest.main()
