"""Resource backoff contracts; no Chromium build or artificial host pressure."""

from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import agent, resources  # noqa: E402
from he.common import HeError, Paths  # noqa: E402
from he.lane import Lane  # noqa: E402

HEALTHY = resources.Sample(30, 60, 0)
BUSY = resources.Sample(95, 60, 0)
LOW_MEMORY = resources.Sample(40, 10, 0)


class ResourcePolicyTest(unittest.TestCase):
    def test_sustained_cpu_pressure_and_slow_recovery(self):
        policy = resources.Policy()
        self.assertTrue(policy.update(HEALTHY, 0))
        self.assertFalse(policy.update(HEALTHY, 20))
        self.assertFalse(policy.update(BUSY, 21))
        self.assertFalse(policy.update(BUSY, 26))
        self.assertTrue(policy.update(BUSY, 27))
        self.assertTrue(policy.update(HEALTHY, 28))
        self.assertTrue(policy.update(HEALTHY, 47))
        self.assertFalse(policy.update(HEALTHY, 48))

    def test_memory_and_swap_backoff_immediately_and_recovery_resets(self):
        policy = resources.Policy()
        policy.update(HEALTHY, 0)
        policy.update(HEALTHY, 20)
        self.assertTrue(policy.update(LOW_MEMORY, 21))
        policy.update(HEALTHY, 22)
        policy.update(resources.Sample(80, 60, 0), 35)
        self.assertTrue(policy.update(HEALTHY, 40))
        self.assertFalse(policy.update(HEALTHY, 60))
        self.assertTrue(policy.update(resources.Sample(20, 70, 20), 61))

    def test_sensor_failure_is_conservative_but_known_memory_pressure_wins(self):
        self.assertTrue(resources.Policy().update(resources.Sample(None, None), 0))
        self.assertEqual(resources.Sample(None, 5).reason, LOW_MEMORY.reason)

    def test_local_limits_cover_remote_offline_conversion_and_preserve_lower_cap(self):
        self.assertEqual(resources.siso_limits(2, "scandeps=3,local=24"), (2, "scandeps=3,local=2"))
        self.assertEqual(resources.siso_limits(2, "local=1"), (1, "local=1"))
        self.assertEqual(resources.siso_limits(2, "local=8,local=1"), (1, "local=1"))
        for value in ("local=0", "local=banana"):
            with self.assertRaises(HeError):
                resources.siso_limits(2, value)

    def test_default_and_explicit_job_ceiling_validation(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resources.jobs_ceiling(), max(1, min(13, (os.cpu_count() or 2) - 1)))
        with mock.patch.dict(os.environ, {"HELIUM_BUILD_JOBS": "3"}):
            self.assertEqual(resources.jobs_ceiling(), 3)
            self.assertEqual(resources.jobs_ceiling(1), 1)
        with mock.patch.dict(os.environ, {"HELIUM_BUILD_JOBS": "invalid"}):
            self.assertEqual(resources.jobs_ceiling(1), 1)
        for value in (0, -1):
            with self.assertRaises(HeError):
                resources.jobs_ceiling(value)

    def test_swap_growth_uses_reported_page_size_and_elapsed_time(self):
        sensors = resources.Sensors()
        memory = "System-wide memory free percentage: 50%"
        first = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nSwapouts: 100."
        second = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nSwapouts: 4196."
        with mock.patch.object(sensors, "_cpu", return_value=30), \
                mock.patch.object(resources, "_query", side_effect=[memory, first, memory, second]), \
                mock.patch.object(resources.time, "monotonic", side_effect=[1, 3]):
            self.assertIsNone(sensors.sample().swap_mib_per_second)
            self.assertEqual(sensors.sample().swap_mib_per_second, 32)

    def test_cache_client_mode_preserves_shared_storage_and_rejects_incompatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory), Path(directory) / "build")
            paths.out.mkdir(parents=True)
            (paths.out / "args.gn").write_text('cc_wrapper="sccache"\n')
            environment = {"PATH": "/fake", "SCCACHE_CONF": str(Path(directory) / "config")}
            with mock.patch.object(resources.shutil, "which", return_value="/fake/sccache"), \
                    mock.patch.object(resources, "_query", return_value="sccache 0.17.0"):
                self.assertIn("shared cache storage", resources.cache_environment(paths, environment))
                self.assertEqual(environment["SCCACHE_CLIENT_SIDE"], "1")
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, {**environment, "SCCACHE_ERROR_LOG": ""})
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, {**environment, "SCCACHE_DIST_SCHEDULER_URL": "configured"})
                Path(environment["SCCACHE_CONF"]).write_text('[dist]\nscheduler_url="configured"\n')
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, environment)

    def test_unverified_cache_version_refuses_unthrottled_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory), Path(directory) / "build")
            paths.out.mkdir(parents=True)
            (paths.out / "args.gn").write_text('cc_wrapper="sccache"\n')
            with mock.patch.object(resources.shutil, "which", return_value="/fake/sccache"), \
                    mock.patch.object(resources, "_query", return_value="sccache 0.16.0"):
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, {"SCCACHE_CONF": str(Path(directory) / "missing")})

    def test_cache_config_precedence_json_and_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = Paths(root, root / "build")
            paths.out.mkdir(parents=True)
            (paths.out / "args.gn").write_text('cc_wrapper="sccache"\n')
            preferred = root / "Library/Application Support/Mozilla.sccache/config"
            legacy = root / "Library/Preferences/Mozilla.sccache/config"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('[dist]\nscheduler_url="configured"\n')
            environment = {"HOME": str(root)}
            with mock.patch.object(resources.shutil, "which", return_value="/fake/sccache"), \
                    mock.patch.object(resources, "_query", return_value="sccache 0.17.0"):
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, environment)
                preferred.parent.mkdir(parents=True)
                preferred.write_text("")
                self.assertIn("shared cache", resources.cache_environment(paths, environment))
                config = root / "cache.json"
                config.write_text('{"dist": {}}')
                self.assertIn("shared cache", resources.cache_environment(paths, {**environment, "SCCACHE_CONF": str(config)}))
                config.write_text('{"dist": {"scheduler_url": "configured"}}')
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, {**environment, "SCCACHE_CONF": str(config)})
                with self.assertRaises(HeError):
                    resources.cache_environment(paths, {**environment, "SCCACHE_CONF": "relative/config"})


class OwnedProcessesTest(unittest.TestCase):
    def test_macos_birth_identity_has_microsecond_precision(self):
        self.assertEqual(ctypes.sizeof(resources._BSDInfo), 136)
        self.assertEqual(resources._BSDInfo.microseconds.offset, 128)
        first = resources.Process(1, 2, 3, "100.000001")
        second = resources.Process(1, 2, 3, "100.000002")
        self.assertFalse(resources.same_process(first, second))

    def test_cancellation_reaches_scheduler_but_excludes_detached_cache(self):
        child = mock.Mock(pid=100)
        child.poll.return_value = None
        uid = os.getuid()
        snapshot = {100: resources.Process(100, 90, uid, "root"),
                    101: resources.Process(101, 100, uid, "scheduler"),
                    102: resources.Process(102, 100, uid, "detached cache"),
                    200: resources.Process(200, 1, uid, "unrelated")}
        with mock.patch.object(resources, "processes", side_effect=lambda pid=None: snapshot if pid is None else {pid: snapshot[pid]}), \
                mock.patch.object(resources.os, "getpgrp", return_value=90), \
                mock.patch.object(resources.os, "getpgid", side_effect=lambda pid: 102 if pid == 102 else 90), \
                mock.patch.object(resources.os, "kill") as terminate:
            resources.OwnedPolicy(child).cancel(signal.SIGTERM)
        self.assertEqual(terminate.call_args_list, [mock.call(101, signal.SIGTERM), mock.call(100, signal.SIGTERM)])

    def test_policy_only_follows_owned_processes_and_retains_reparented_child(self):
        child = mock.Mock(pid=100)
        child.poll.return_value = None
        uid = os.getuid()
        root = resources.Process(100, 90, uid, "birth root")
        worker = resources.Process(101, 100, uid, "birth worker")
        unrelated = resources.Process(200, 1, uid, "shared cache")
        snapshot = {100: root, 101: worker, 200: unrelated}
        policy = resources.OwnedPolicy(child)
        with mock.patch.object(resources.TASKPOLICY.__class__, "is_file", return_value=True), \
                mock.patch.object(resources, "processes", side_effect=lambda pid=None: snapshot if pid is None else {pid: snapshot[pid]}), \
                mock.patch.object(resources.subprocess, "run", return_value=mock.Mock(returncode=0)) as change:
            self.assertEqual(policy.update(True), 2)
            self.assertEqual({int(c.args[0][-1]) for c in change.call_args_list}, {100, 101})
            snapshot[101] = resources.Process(101, 1, uid, "birth worker")
            self.assertEqual(policy.update(False), 2)
            snapshot[101] = resources.Process(101, 1, uid, "reused PID")
            change.reset_mock()
            policy.update(True)
            self.assertEqual({int(c.args[0][-1]) for c in change.call_args_list}, {100})

    def test_identity_revalidated_before_policy_change(self):
        child = mock.Mock(pid=100)
        child.poll.return_value = None
        original = resources.Process(100, 90, os.getuid(), "original")
        changed = resources.Process(100, 1, os.getuid(), "replacement")
        with mock.patch.object(resources.TASKPOLICY.__class__, "is_file", return_value=True), \
                mock.patch.object(resources, "processes", side_effect=[{100: original}, {100: changed}]), \
                mock.patch.object(resources.subprocess, "run") as mutate:
            resources.OwnedPolicy(child).update(True)
            mutate.assert_not_called()


class ResourceRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="he-resources-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = Paths(root, root / "build")
        self.paths.src.mkdir(parents=True)
        self.sensors = mock.Mock()
        self.sensors.sample.return_value = HEALTHY
        # Kernel policy changes are tested separately on a tiny owned process;
        # sandboxed unit tests inject policy support and pressure readings.
        taskpolicy = mock.patch.object(resources, "TASKPOLICY", Path("/nonexistent/taskpolicy"))
        taskpolicy.start()
        self.addCleanup(taskpolicy.stop)

    def run_script(self, script, **options):
        return resources.run(self.paths, [sys.executable, "-c", script, "{HELIUM_BUILD_JOBS}"],
                             jobs=2, sensors=self.sensors, interval=.01, capture_output=True, **options)

    def test_pressure_delays_launch_and_cap_reaches_child_without_changing_inputs(self):
        samples = iter([HEALTHY, LOW_MEMORY, HEALTHY])
        self.sensors.sample.side_effect = lambda: next(samples, HEALTHY)
        result = self.run_script("import os,sys;print(sys.argv[1], os.environ['SISO_LIMITS'])")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2 local=2")
        events = [json.loads(line) for line in (self.paths.state / "build-resources.jsonl").read_text().splitlines()]
        self.assertEqual(events[0]["state"], "waiting")
        self.assertEqual(events[-1]["state"], "finished")
        self.assertEqual(events[-1]["effective_jobs"], 2)

    def test_missing_sensor_uses_one_job_and_background_policy(self):
        self.sensors.sample.return_value = resources.Sample(None, None)
        result = self.run_script("import sys;print(sys.argv[1])")
        self.assertEqual(result.stdout.strip(), "1")
        self.assertEqual(resources.status(self.paths.state)["policy"], "background")

    def test_explicit_ceiling_applies_to_planning_despite_invalid_environment(self):
        runner = self.paths.src / "third_party/depot_tools/autoninja.py"
        runner.parent.mkdir(parents=True)
        runner.write_text("import os,sys\nassert sys.argv[sys.argv.index('-j')+1]=='1'\n"
                          "assert os.environ['SISO_LIMITS']=='local=1'\nprint('[1/1] compile')\n")
        with mock.patch.object(resources, "Sensors", return_value=self.sensors), \
                mock.patch.dict(os.environ, {"HELIUM_BUILD_JOBS": "invalid", "SISO_LIMITS": ""}):
            self.assertEqual(agent.guard_build(self.paths, ["chrome"], budget=1, approved=False,
                                               problems=[], jobs=1), 1)

    def test_nonzero_and_invalid_utf8_survive_capture(self):
        result = self.run_script("import sys;sys.stderr.buffer.write(b'bad \\xff');sys.exit(7)")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stderr, "bad \ufffd")
        self.assertEqual(resources.status(self.paths.state)["state"], "failed")

    def test_live_backoff_and_recovery_while_child_continues(self):
        samples = iter([HEALTHY, HEALTHY, LOW_MEMORY, HEALTHY, HEALTHY])
        self.sensors.sample.side_effect = lambda: next(samples, HEALTHY)
        with mock.patch.object(resources, "RECOVERY_SECONDS", 0), \
                mock.patch.object(resources.OwnedPolicy, "update") as policy:
            result = self.run_script("import time;time.sleep(.08)")
        self.assertEqual(result.returncode, 0)
        self.assertIn(mock.call(True), policy.call_args_list)
        self.assertIn(mock.call(False), policy.call_args_list)

    def test_sensor_exception_waits_for_child_and_records_failure(self):
        self.sensors.sample.side_effect = [HEALTHY, HEALTHY, RuntimeError("broken")]
        marker = self.paths.src / "finished"
        script = "import pathlib,time;time.sleep(.06);pathlib.Path('finished').touch()"
        with self.assertRaisesRegex(RuntimeError, "broken"):
            self.run_script(script)
        self.assertTrue(marker.exists())
        self.assertEqual(resources.status(self.paths.state)["state"], "failed")

    def test_interrupt_during_admission_never_launches_child(self):
        self.sensors.sample.return_value = LOW_MEMORY
        def interrupted_sleep(_seconds):
            os.kill(os.getpid(), signal.SIGTERM)
        with mock.patch.object(resources.time, "sleep", side_effect=interrupted_sleep):
            result = self.run_script("raise RuntimeError('must not launch')")
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertNotIn("child", resources.status(self.paths.state))

    def test_runner_directed_interrupt_cancels_descendants_before_launcher_exit(self):
        child = mock.Mock(pid=100, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        handlers = {}
        def install(signum, handler):
            previous = handlers.get(signum)
            handlers[signum] = handler
            return previous
        def wait(timeout=None):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            raise subprocess.TimeoutExpired("fake build", timeout)
        child.wait.side_effect = wait
        with mock.patch.object(resources.signal, "signal", side_effect=install), \
                mock.patch.object(resources.subprocess, "Popen", return_value=child), \
                mock.patch.object(resources.OwnedPolicy, "update"), \
                mock.patch.object(resources.OwnedPolicy, "cancel", side_effect=lambda _signum: setattr(child, "returncode", 0)) as cancel:
            result = self.run_script("unused")
        self.assertEqual(result.returncode, 143)
        self.assertGreaterEqual(cancel.call_count, 1)
        self.assertTrue(all(call == mock.call(signal.SIGTERM) for call in cancel.call_args_list))
        child.send_signal.assert_not_called()

    def test_monitor_failure_drain_remains_cancellable(self):
        child = mock.Mock(pid=100, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        handlers = {}
        def install(signum, handler):
            previous = handlers.get(signum)
            handlers[signum] = handler
            return previous
        waits = 0
        def wait(timeout=None):
            nonlocal waits
            waits += 1
            if waits == 2:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            raise subprocess.TimeoutExpired("fake build", timeout)
        child.wait.side_effect = wait
        self.sensors.sample.side_effect = [HEALTHY, HEALTHY, RuntimeError("broken sensor")]
        with mock.patch.object(resources.signal, "signal", side_effect=install), \
                mock.patch.object(resources.subprocess, "Popen", return_value=child), \
                mock.patch.object(resources.OwnedPolicy, "update"), \
                mock.patch.object(resources.OwnedPolicy, "cancel", side_effect=lambda _signum: setattr(child, "returncode", 0)) as cancel:
            with self.assertRaisesRegex(RuntimeError, "broken sensor"):
                self.run_script("unused")
        self.assertGreaterEqual(cancel.call_count, 1)
        self.assertEqual(resources.status(self.paths.state)["state"], "failed")

    def test_status_marks_stale_monitor_without_releasing_reservation(self):
        self.run_script("pass")
        path = self.paths.state / "build-resources.json"
        data = json.loads(path.read_text())
        data.update(state="running", updated=0)
        path.write_text(json.dumps(data))
        self.assertTrue(Lane(self.paths.state).status()["build_resources"]["stale"])


class ResourceShellTest(unittest.TestCase):
    def invoke(self, arguments, *, fail=False, agent_mode=False):
        with tempfile.TemporaryDirectory(prefix="he-resource-shell-") as directory:
            calls = Path(directory) / "calls"
            tools = Path(__file__).resolve().parents[2]
            script = '''source "$1" >/dev/null || exit 2
shift
___helium_refuse_in_scratch() { :; }
___helium_use_build_tmpdir() { :; }
___helium_he() {
    printf '%s\\n' "$*" >> "$RESOURCE_TEST_CALLS"
    if [ "$1" = build-run ] && [ "$RESOURCE_TEST_FAIL" = 1 ]; then return 7; fi
}
___helium_build "$@"
'''
            env = {**os.environ, "HELIUM_DEV_WORKTREE": str(tools), "HELIUM_BUILD_DIR": directory,
                   "HELIUM_AGENT_MODE": "1" if agent_mode else "", "RESOURCE_TEST_CALLS": str(calls),
                   "RESOURCE_TEST_FAIL": "1" if fail else "0"}
            result = subprocess.run(["bash", "-c", script, "bash", str(tools / "dev.sh"), *arguments],
                                    env=env, capture_output=True, text=True)
            return result, calls.read_text() if calls.exists() else ""

    def test_failed_resource_runner_cannot_certify_completed_output(self):
        result, calls = self.invoke(["--jobs", "3", "chrome"], fail=True)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("build-run --jobs 3 -- chrome", calls)
        self.assertNotIn("completed-build", calls)

    def test_raw_scheduler_options_cannot_override_the_ceiling(self):
        for option in ("-j16", "-local_jobs=16", "--local_jobs=16"):
            result, calls = self.invoke([option, "chrome"])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(calls, "")

    def test_success_records_completed_build_after_resource_runner(self):
        result, calls = self.invoke(["chrome"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(calls.index("build-run -- chrome"), calls.index("completed-build -- chrome"))

    def test_selected_ceiling_is_forwarded_to_both_build_phases(self):
        result, calls = self.invoke(["--jobs", "1", "chrome"], agent_mode=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agent-guard --jobs 1 chrome", calls)
        self.assertIn("build-run --jobs 1 -- chrome", calls)


if __name__ == "__main__":
    unittest.main()
