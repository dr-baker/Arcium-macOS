from __future__ import annotations

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


class FakeRunner:
    def __init__(self, *, edge_count: int = 2, missing_edge_count: bool = False) -> None:
        self.edge_count = edge_count
        self.missing_edge_count = missing_edge_count
        self.write_explain = True
        self.explain_text = ""
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args, *, cwd, env):
        argv = tuple(str(arg) for arg in args)
        self.calls.append(argv)
        if "query" in argv:
            kind = argv[argv.index("query") + 1]
            if kind == "rule":
                output = "rule: phony\ninputs: obj/example.o\n"
            else:
                output = "command = python3 linker_driver.py -o current-target\n"
            return CommandResult(args=argv, returncode=0, stdout=output)
        if "-n" in argv:
            if self.write_explain:
                (Path(argv[argv.index("-C") + 1]) / "siso_explain").write_text(self.explain_text)
            output = "ninja: no work to do.\n" if self.edge_count == 0 else f"[1/{self.edge_count}] CXX obj/example.o\n"
            if self.missing_edge_count:
                output = "ninja: Entering directory out/Default\n"
            return CommandResult(args=argv, returncode=0, stdout=output)
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

    def test_build_plan_is_autoninja_dry_run_after_graph_validation(self) -> None:
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertTrue(result.ok)
        self.assertEqual(result.edge_count, 2)
        self.assertIn("autoninja-dry-run", result.proof_gates)
        self.assertEqual(self.runner.calls[0][1:3], ("query", "rule"))
        self.assertIn("-n", self.runner.calls[-1])
        self.assertEqual(self.runner.calls[-1][-1], "obj/chrome/foo.o")

    def test_edge_budget_refuses_before_compile(self) -> None:
        self.runner.edge_count = 501
        result = self.builder.compile(("obj/chrome/foo.o",))
        self.assertFalse(result.ok)
        self.assertIn("above configured budget", result.error)
        self.assertTrue(all("-n" in call or "query" in call for call in self.runner.calls))

    def test_missing_edge_count_fails_closed(self) -> None:
        self.runner.missing_edge_count = True
        result = self.builder.build_plan(("obj/chrome/foo.o",))
        self.assertFalse(result.ok)
        self.assertIn("recognizable edge count", result.error)

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
        self.assertEqual(completed.targets, ("chrome", "chromedriver"))
        self.assertIn("-n", self.runner.calls[-2])
        self.assertNotIn("-n", self.runner.calls[-1])

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


if __name__ == "__main__":
    unittest.main()
