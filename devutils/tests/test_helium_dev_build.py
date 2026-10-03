from __future__ import annotations

from contextlib import redirect_stderr
import io
import tempfile
from pathlib import Path
import sys
import unittest

from devutils.helium_dev_build import (
    ArtifactStatus,
    BuildPaths,
    CommandResult,
    DEFAULT_EDGE_BUDGET,
    HeliumDevBuilder,
    parse_dry_run_edge_count,
    parse_siso_query_commands,
    normalize_targets,
    subprocess_runner,
)
from devutils.build_backend import BuildBackend


class FakeRunner:
    def __init__(
        self,
        *,
        edge_count: int = 2,
        missing_edge_count: bool = False,
        truncate_output: bool = False,
        streamed_edge_count: int | None = None,
        streamed_edge_count_ambiguous: bool = False,
    ) -> None:
        self.edge_count = edge_count
        self.missing_edge_count = missing_edge_count
        self.truncate_output = truncate_output
        self.streamed_edge_count = streamed_edge_count
        self.streamed_edge_count_ambiguous = streamed_edge_count_ambiguous
        self.write_explain = True
        self.explain_text = ""
        self.dry_run_error: str | None = None
        self.calls: list[tuple[str, ...]] = []
        self.progress_totals: list[int | None] = []

    def __call__(self, args, *, cwd, env, progress_total=None):
        argv = tuple(str(arg) for arg in args)
        self.calls.append(argv)
        self.progress_totals.append(progress_total)
        if "query" in argv:
            kind = argv[argv.index("query") + 1]
            if kind == "rule":
                output = "rule: phony\ninputs: obj/example.o\n"
            else:
                output = "command = python3 linker_driver.py -o current-target\n"
            return CommandResult(args=argv, returncode=0, stdout=output)
        if "-n" in argv:
            if self.dry_run_error is not None:
                return CommandResult(
                    args=argv,
                    returncode=1,
                    stderr=self.dry_run_error,
                )
            if self.write_explain:
                (Path(argv[argv.index("-C") + 1]) / "siso_explain").write_text(self.explain_text)
            output = "ninja: no work to do.\n" if self.edge_count == 0 else f"[1/{self.edge_count}] CXX obj/example.o\n"
            if self.missing_edge_count:
                output = "ninja: Entering directory out/Default\n"
            return CommandResult(
                args=argv,
                returncode=0,
                stdout=output,
                stdout_truncated=self.truncate_output,
                streamed_edge_count=self.streamed_edge_count,
                streamed_edge_count_ambiguous=self.streamed_edge_count_ambiguous,
            )
        return CommandResult(args=argv, returncode=0, stdout="built\n")


class HeliumDevBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.source = root / "src"
        self.output = self.source / "out" / "Default"
        self.output.mkdir(parents=True)
        self.siso = self.source / "third_party" / "siso" / "cipd" / "siso"
        self.autoninja = self.source / "third_party" / "depot_tools" / "autoninja.py"
        self.siso.parent.mkdir(parents=True)
        self.autoninja.parent.mkdir(parents=True)
        self.siso.touch()
        self.autoninja.touch()
        self.runner = FakeRunner()
        self.builder = HeliumDevBuilder(
            BuildPaths(self.source, self.output, self.siso, self.autoninja, python_path="python3"),
            runner=self.runner,
            edge_budget=DEFAULT_EDGE_BUDGET,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_normalizes_and_rejects_unsafe_targets(self) -> None:
        self.assertEqual(normalize_targets(("obj/a.o", "obj/a.o", "//chrome:unit")), ("obj/a.o", "//chrome:unit"))
        for unsafe in ("", "/tmp/a.o", "../obj/a.o", "-C", "obj/a o", "obj/a;o"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(Exception):
                    normalize_targets((unsafe,))

    def test_parses_siso_command_formats_without_executing_them(self) -> None:
        self.assertEqual(
            parse_siso_query_commands("target: chrome_app\ncommand = python linker_driver.py -o app\n"),
            ("python linker_driver.py -o app",),
        )
        self.assertEqual(parse_siso_query_commands("zsh -e generated-link-line\n"), ("zsh -e generated-link-line",))
        self.assertEqual(parse_siso_query_commands("ninja: Entering directory out\nno commands\n"), ())

    def test_parses_ninja_and_siso_edge_totals(self) -> None:
        self.assertEqual(parse_dry_run_edge_count("[4/1,234] CXX obj/a.o\n"), 1234)
        self.assertEqual(parse_dry_run_edge_count("planned 17 actions\n"), 17)
        self.assertEqual(parse_dry_run_edge_count("ninja: no work to do.\n"), 0)
        self.assertIsNone(parse_dry_run_edge_count("ninja: entering directory out/Default\n"))
        self.assertIsNone(parse_dry_run_edge_count("ninja: no work to do.\nwarning: graph changed\n"))
        self.assertEqual(parse_dry_run_edge_count("ninja: no work to do.\n[1/61] CXX obj/a.o\n"), 61)
        self.assertEqual(parse_dry_run_edge_count("[1/61] CXX obj/a.o\n[2/61] CXX obj/b.o\n"), 61)
        self.assertIsNone(parse_dry_run_edge_count("[1/61] CXX obj/a.o\nplanned 60 actions\n"))

    def test_build_plan_is_autoninja_dry_run_after_graph_validation(self) -> None:
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertTrue(result.ok)
        self.assertEqual(result.edge_count, 2)
        self.assertIn("autoninja-dry-run", result.proof_gates)
        self.assertEqual(self.runner.calls[0][1:3], ("query", "rule"))
        self.assertIn("-n", self.runner.calls[-1])
        self.assertEqual(self.runner.calls[-1][-1], "obj/chrome/foo.o")

    def test_pending_recovery_blocks_compile_and_relink_but_allows_plans(self) -> None:
        snapshot = self.source.parent / ".arcium/replay-timestamps.json"
        snapshot.parent.mkdir()
        snapshot.write_text("pending recovery, including unreadable content")
        operations = (
            lambda: self.builder.compile(("obj/chrome/foo.o",)),
            self.builder.relink,
            lambda: self.builder.relink(resources=True),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.runner.calls.clear()
                result = operation()
                self.assertFalse(result.ok)
                self.assertIn("recovery is pending", result.error)
                self.assertTrue(self.runner.calls)
                self.assertTrue(all("-n" in call or "query" in call
                                    for call in self.runner.calls))
                self.assertNotIn("focused-compile", result.proof_gates)
                self.assertNotIn("component-relinked", result.proof_gates)
        plan = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertTrue(plan.ok)
        self.assertEqual(plan.edge_count, 2)
        self.assertTrue(snapshot.exists())

    def test_edge_budget_refuses_before_compile(self) -> None:
        self.runner.edge_count = 501
        result = self.builder.compile(("obj/chrome/foo.o",))
        self.assertFalse(result.ok)
        self.assertIn("above configured budget", result.error)
        self.assertTrue(all("-n" in call or "query" in call for call in self.runner.calls))

    def test_failed_dry_run_reports_the_actionable_build_error(self) -> None:
        self.runner.dry_run_error = (
            'shutdown diagnostics\n'
            '"../../chrome/test/data/example.json", needed by "generated", '
            'missing and no known rule to make it\n'
        )

        result = self.builder.build_plan(("obj/chrome/foo.o",))

        self.assertFalse(result.ok)
        self.assertIn("chrome/test/data/example.json", result.error)
        self.assertIn("missing and no known rule", result.error)

    def test_missing_edge_count_fails_closed(self) -> None:
        self.runner.missing_edge_count = True
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertFalse(result.ok)
        self.assertIn("recognizable edge count", result.error)

    def test_truncated_dry_run_uses_streamed_edge_count(self) -> None:
        self.runner.truncate_output = True
        self.runner.streamed_edge_count = 2
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertTrue(result.ok)
        self.assertEqual(result.edge_count, 2)

    def test_ambiguous_truncated_dry_run_fails_closed(self) -> None:
        self.runner.truncate_output = True
        self.runner.streamed_edge_count = 2
        self.runner.streamed_edge_count_ambiguous = True
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertFalse(result.ok)
        self.assertIn("conflicting edge totals", result.error)

    def test_compile_rejects_broad_targets(self) -> None:
        for target in ("chrome", "//chrome:chrome", "chrome:chrome", "libchrome_dll.dylib"):
            with self.subTest(target=target):
                result = self.builder.compile((target,))
                self.assertFalse(result.ok)
                self.assertIn("focused targets", result.error)
                self.assertEqual(self.runner.calls, [])

    def test_component_relink_queries_generated_command_then_builds_target(self) -> None:
        result = self.builder.relink(
            artifact_status_probe=lambda: ArtifactStatus(
                artifact_state="current", running_process_stale=False, warnings=("no scoped process",)
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.targets, ("libchrome_dll.dylib",))
        self.assertIn("generated-link-inputs-inspected", result.proof_gates)
        self.assertIn("generated-link-command-inspected", result.proof_gates)
        self.assertEqual(result.artifact_state, "current")
        self.assertFalse(result.running_process_stale)
        self.assertIn("no scoped process", result.warnings)
        self.assertEqual(self.runner.calls[1][2], "inputs")
        self.assertEqual(self.runner.calls[2][2], "commands")
        self.assertEqual(self.runner.calls[-1][-1], "libchrome_dll.dylib")

    def test_resources_relink_uses_explicit_chrome_app_target(self) -> None:
        result = self.builder.relink(resources=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.targets, ("chrome_app",))
        self.assertIn("bundle-resources-relinked", result.proof_gates)
        self.assertEqual(self.runner.calls[-1][-1], "chrome_app")

    def test_build_full_requires_real_approval_then_dry_runs(self) -> None:
        refused = self.builder.build_full(approved=False)
        self.assertFalse(refused.ok)
        self.assertEqual(self.runner.calls, [])
        completed = self.builder.build_full(approved=True)
        self.assertTrue(completed.ok)
        self.assertEqual(completed.targets, ("chrome",))
        self.assertIn("-n", self.runner.calls[-2])
        self.assertNotIn("-n", self.runner.calls[-1])
        self.assertIsNone(self.runner.progress_totals[-2])
        self.assertEqual(self.runner.progress_totals[-1], 2)
        self.assertEqual(self.runner.calls[-1], (
            "python3", str(self.builder.paths.autoninja_path), "-k", "0", "-C", str(self.builder.paths.out_dir), "chrome",
        ))

    def test_job_limit_uses_the_local_scheduler_for_plan_and_build(self) -> None:
        # An inert depot_tools boundary supplies parsed GN arguments. The real
        # coordinator must select the scheduler before issuing either command.
        self.autoninja.with_name("gn_helper.py").write_text('''
from pathlib import Path
def exists(output):
    return (Path(output) / 'args.gn').exists()
def args(output):
    return (line.strip().split('=') for line in (Path(output) / 'args.gn').read_text().splitlines())
''')
        for scheduler, backend, flags in (
            ("true", BuildBackend("local", "", "default_instance", "google.star"), ("-local_jobs=2",)),
            ("true", BuildBackend("nativelink", "localhost:50051", "main", "nativelink.star"), ("-local_jobs=2",)),
            ("false", BuildBackend("local", "", "default_instance", "google.star"), ("-j", "2")),
        ):
            with self.subTest(scheduler=scheduler, backend=backend.name):
                (self.output / "args.gn").write_text("use_siso=" + scheduler + "\n")
                self.builder.jobs = 2
                self.builder.backend = backend
                self.runner.calls.clear()
                result = self.builder.build_full(approved=True)
                self.assertTrue(result.ok, result.error)
                prefix = ("python3", str(self.builder.paths.autoninja_path), "-k", "0", "-C", str(self.builder.paths.out_dir), *flags)
                self.assertEqual(self.runner.calls[-2], (*prefix, "-n", "chrome"))
                self.assertEqual(self.runner.calls[-1], (*prefix, "chrome"))

        for invalid in (0, -1, 1.5, True):
            with self.subTest(jobs=invalid):
                self.builder.jobs = invalid
                self.runner.calls.clear()
                result = self.builder.compile(("obj/chrome/foo.o",))
                self.assertFalse(result.ok)
                self.assertIn("positive integer", result.error)
                self.assertEqual(self.runner.calls, [])

    def test_zero_edge_plan_never_executes_a_broad_build(self) -> None:
        self.runner.edge_count = 0
        result = self.builder.build_full(approved=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.edge_count, 0)
        self.assertIn("no-work-plan", result.proof_gates)
        self.assertTrue(all("-n" in call or "query" in call for call in self.runner.calls))

    def test_stale_or_missing_explain_refuses_before_execution(self) -> None:
        self.runner.edge_count = 0
        self.runner.explain_text = "output build.ninja.stamp older than most recent input BUILD.gn\n"
        stale = self.builder.build_full(approved=True)
        self.assertFalse(stale.ok)
        self.assertIn("stale generated graph", stale.error)
        self.assertTrue(all("-n" in call or "query" in call for call in self.runner.calls))
        self.runner.calls.clear()
        self.runner.write_explain = False
        missing = self.builder.build_full(approved=True)
        self.assertFalse(missing.ok)
        self.assertIn("fresh Siso explain", missing.error)

    def test_build_full_keeps_the_edge_budget_after_approval(self) -> None:
        self.runner.edge_count = DEFAULT_EDGE_BUDGET + 1
        result = self.builder.build_full(approved=True)
        self.assertFalse(result.ok)
        self.assertIn("above configured budget", result.error)
        self.assertTrue(all("-n" in call or "query" in call for call in self.runner.calls))

    def test_results_are_json_ready_without_build_output(self) -> None:
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        document = result.as_dict()
        self.assertTrue(document["ok"])
        self.assertEqual(document["commands"][-1][-2:], ["-n", "obj/chrome/foo.o"])
        self.assertNotIn("built", repr(document))

    def test_subprocess_runner_uses_argv_and_bounds_retained_output(self) -> None:
        result = subprocess_runner(
            (sys.executable, "-c", "print('x' * 100)"),
            cwd=self.source,
            env={},
            max_output_bytes=8,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout_truncated)
        self.assertLessEqual(len(result.stdout.encode()), 8)

    def test_subprocess_runner_parses_edge_total_beyond_retained_output(self) -> None:
        result = subprocess_runner(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 100000); sys.stdout.write('\\n[1/1,234] CXX obj/a.o\\n')",
            ),
            cwd=self.source,
            env={},
            max_output_bytes=8,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout_truncated)
        self.assertEqual(result.streamed_edge_count, 1234)
        self.assertFalse(result.streamed_edge_count_ambiguous)

    def test_subprocess_runner_reports_live_action_percentage_to_stderr(self) -> None:
        progress = io.StringIO()
        with redirect_stderr(progress):
            result = subprocess_runner(
                (
                    sys.executable,
                    "-c",
                    "print('[1/4] CXX one'); print('[2/4] CXX two'); print('[4/4] LINK app')",
                ),
                cwd=self.source,
                env={},
                progress_total=4,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("build progress: 50.0% (2/4 actions)", progress.getvalue())
        self.assertIn("build progress: finishing (4/4 actions)", progress.getvalue())
        self.assertIn("build progress: 100.0% (4/4 actions)", progress.getvalue())

    def test_subprocess_runner_estimates_progress_from_new_localexec_records(self) -> None:
        localexec = self.output / "siso_localexec"
        localexec.write_text("cmd: stale\naction: stale.o\n", encoding="utf-8")
        script = (
            "from pathlib import Path; import sys, time; "
            "path = Path(sys.argv[1]); "
            "handle = path.open('w', encoding='utf-8'); "
            "[(handle.write(f'action: obj/{i}.o\\n'), handle.flush(), time.sleep(.35)) "
            "for i in range(1, 5)]; handle.close()"
        )
        progress = io.StringIO()
        with redirect_stderr(progress):
            result = subprocess_runner(
                (sys.executable, "-c", script, str(localexec), "-C", str(self.output)),
                cwd=self.source,
                env={},
                progress_total=4,
            )
        self.assertEqual(result.returncode, 0)
        output = progress.getvalue()
        self.assertIn("build progress: estimated 25.0% (1/4 actions)", output)
        self.assertIn(
            "build progress: estimated 99.0% "
            "(4/4 observed actions; awaiting command completion)",
            output,
        )
        self.assertNotIn("estimated 100.0%", output)
        self.assertIn("build progress: 100.0% (4/4 actions)", output)

    def test_subprocess_runner_resets_localexec_when_log_is_replaced(self) -> None:
        localexec = self.output / "siso_localexec"
        localexec.write_text("cmd: old\naction: old-1\naction: old-2\n", encoding="utf-8")
        script = (
            "from pathlib import Path; import sys, time; "
            "path = Path(sys.argv[1]); time.sleep(.35); "
            "path.write_text('cmd: new\\naction: new-1\\n', encoding='utf-8'); time.sleep(.35)"
        )
        progress = io.StringIO()
        with redirect_stderr(progress):
            result = subprocess_runner(
                (sys.executable, "-c", script, str(localexec), "-C", str(self.output)),
                cwd=self.source,
                env={},
                progress_total=1,
            )
        self.assertEqual(result.returncode, 0)
        output = progress.getvalue()
        self.assertIn(
            "estimated 99.0% (1/1 observed actions; awaiting command completion)",
            output,
        )
        self.assertNotIn("2/1 actions", output)

    def test_subprocess_runner_never_claims_completion_for_failed_build(self) -> None:
        localexec = self.output / "siso_localexec"
        script = (
            "from pathlib import Path; import sys; "
            "Path(sys.argv[1]).write_text('action: failed.o\\n', encoding='utf-8'); "
            "raise SystemExit(1)"
        )
        progress = io.StringIO()
        with redirect_stderr(progress):
            result = subprocess_runner(
                (sys.executable, "-c", script, str(localexec), "-C", str(self.output)),
                cwd=self.source,
                env={},
                progress_total=1,
            )
        self.assertEqual(result.returncode, 1)
        output = progress.getvalue()
        self.assertNotIn("100.0%", output)


if __name__ == "__main__":
    unittest.main()
