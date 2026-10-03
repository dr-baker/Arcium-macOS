"""Failure-path checks for the tab test gate, using fake test executables."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tab_invariants.py"
spec = importlib.util.spec_from_file_location("tab_invariants", MODULE_PATH)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


class TabInvariantGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def result(self, cases):
        path = self.root / "results.xml"
        path.write_text("<testsuites><testsuite>" + cases + "</testsuite></testsuites>")
        return path

    def test_exact_executed_inventory_passes(self):
        path = self.result('<testcase classname="Tabs" name="OwnsOnce" status="run"/>')
        self.assertEqual(gate.verify_xml(path, {"Tabs.OwnsOnce"}), 1)

    def test_empty_missing_skipped_duplicate_and_failed_results_fail(self):
        cases = ["", '<testcase classname="Tabs" name="Wrong"/>',
                 '<testcase classname="Tabs" name="OwnsOnce"><skipped/></testcase>',
                 '<testcase classname="Tabs" name="OwnsOnce" status="notrun"/>',
                 '<testcase classname="Tabs" name="OwnsOnce"><failure/></testcase>',
                 '<testcase classname="Tabs" name="OwnsOnce"/>' * 2]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(gate.GateFailure):
                gate.verify_xml(self.result(case), {"Tabs.OwnsOnce"})
        with self.assertRaises(gate.GateFailure):
            gate.verify_xml(self.root / "missing.xml", {"Tabs.OwnsOnce"})

    def test_launcher_summary_requires_one_success_for_every_test(self):
        path = self.root / "summary.json"
        expected = {"Tabs.OwnsOnce", "Tabs.KeepsSelection"}
        success = {name: [{"status": "SUCCESS"}] for name in expected}
        path.write_text(json.dumps({"per_iteration_data": [success]}))
        self.assertEqual(gate.verify_launcher_json(path, expected), 2)
        for bad in [[], [{}], [{"Tabs.OwnsOnce": [{"status": "SUCCESS"}]}],
                    [{name: [{"status": "SKIPPED"}] for name in expected}],
                    [{name: [{"status": "FAILURE"}, {"status": "SUCCESS"}]
                      for name in expected}]]:
            path.write_text(json.dumps({"per_iteration_data": bad}))
            with self.subTest(results=bad), self.assertRaises(gate.GateFailure):
                gate.verify_launcher_json(path, expected)

    def test_parameterized_inventory_preserves_seed_names(self):
        self.assertEqual(gate.listed_tests(
            "FixedSeeds/InvariantTest.\n  Ownership/0  # GetParam() = 1\n"
            "  Ownership/1  # GetParam() = 42\n"),
            {"FixedSeeds/InvariantTest.Ownership/0", "FixedSeeds/InvariantTest.Ownership/1"})

    def test_process_exit_and_absent_reports_fail_even_if_discovery_passes(self):
        binary = self.root / "fake_tests"
        suite = gate.Suite("fake_tests", ("Tabs.*",), ("Tabs.OwnsOnce",))
        for exit_code in [0, 1]:
            with self.subTest(exit_code=exit_code):
                binary.write_text(
                    '#!/usr/bin/env python3\nimport sys\n'
                    'if "--gtest_list_tests" in sys.argv:\n'
                    ' print("Tabs.\\n  OwnsOnce")\n'
                    ' sys.exit(0)\n'
                    f'sys.exit({exit_code})\n')
                binary.chmod(0o755)
                report = self.root / f"report-{exit_code}"
                report.mkdir()
                with self.assertRaises(gate.GateFailure):
                    gate.run_suite(suite, self.root, report, 10)

    def test_old_binary_with_no_required_tests_fails(self):
        binary = self.root / "fake_tests"
        binary.write_text('#!/usr/bin/env python3\nprint("Tabs.\\n  OldTest")\n')
        binary.chmod(0o755)
        with self.assertRaises(gate.GateFailure):
            gate.run_suite(gate.Suite("fake_tests", ("Tabs.*",),
                                     ("Tabs.OwnsOnce",)), self.root, self.root, 10)

    def test_service_tier_runs_focused_binary_with_launcher_accounting(self):
        suite = gate.SUITES["service"]
        self.assertEqual(suite.binary, "arcium_feature_settings_unit_tests")
        binary = self.root / suite.binary
        binary.write_text(
            '#!/usr/bin/env python3\nimport json, pathlib, sys\n'
            'if "--gtest_list_tests" in sys.argv:\n'
            ' print("HeliumSpaceServiceTest.\\n  ActionSequencesPreserveTabOwnership")\n'
            ' sys.exit(0)\n'
            'path = next(arg.split("=", 1)[1] for arg in sys.argv\n'
            ' if arg.startswith("--test-launcher-summary-output="))\n'
            'pathlib.Path(path).write_text(json.dumps({"per_iteration_data": [{\n'
            ' "HeliumSpaceServiceTest.ActionSequencesPreserveTabOwnership":\n'
            ' [{"status": "SUCCESS"}]}]}))\n')
        binary.chmod(0o755)
        report = self.root / "service-report"
        report.mkdir()
        result = gate.run_suite(suite, self.root, report, 10)
        self.assertEqual(result["passed"], 1)
        self.assertTrue((report / "launcher-summary.json").is_file())
        self.assertIn("--test-launcher-retry-limit=0", result["command"])


if __name__ == "__main__":
    unittest.main()
