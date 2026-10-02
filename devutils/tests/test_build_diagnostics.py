"""Synthetic evidence fixtures; no build tools or real lanes are touched."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from devutils.build_diagnostics import BuildEvidence, CAPTURE_BYTES, MAX_FILES
from devutils.helium_dev_build import CommandResult
from devutils.tests import test_helium_dev_build as build_fixtures


NESTED_JSON = "[" * 30000 + "0" + "]" * 30000


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "args.gn").write_text("is_debug = true\n")

    def begin(self):
        return BuildEvidence(self.root / "archive", self.out, ("python", "autoninja", "-C", str(self.out), "chrome"))

    def read(self, path):
        return json.loads((path / "manifest.json").read_text())

    def test_stale_metrics_are_not_current_and_cache_is_unknown(self):
        (self.out / "siso_metrics.json").write_text('{"duration": 999, "build_id": "old"}')
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "new"}')
        result = self.read(evidence.finish(returncode=1, stderr="failed"))
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["siso_snapshots"]["siso_metrics.json"]["status"], "unchanged-not-current")
        self.assertEqual(result["siso_snapshots"]["siso_metrics.json"]["attribution"], "unknown")
        self.assertEqual(result["cache_delta"]["status"], "unknown")
        self.assertFalse((evidence.path / "siso_metrics.json").exists())

    def test_matching_ids_correlate_without_summing_duration(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        (self.out / "siso_metrics.json").write_text('{"build_id": "one", "duration_nanos": 100}\n{"step": {"name": "compile"}}\n{"build_id": "one", "duration_nanos": 200}\n')
        result = self.read(evidence.finish(returncode=0))
        metric = result["siso_snapshots"]["siso_metrics.json"]
        self.assertEqual(metric["attribution"], "matches-changed-metadata-build-id")
        self.assertIn("may-include-earlier-records", metric["scope"])
        self.assertEqual(metric["final_cumulative_duration_nanos"], 200)
        self.assertLess(result["command_wall_seconds"], 30)
        self.assertNotIn("duration", result)

    def test_mismatched_ids_are_unknown(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        (self.out / "siso_metrics.json").write_text('{"build_id": "other", "duration_nanos": 200}\n')
        result = self.read(evidence.finish(returncode=0))
        self.assertEqual(result["siso_snapshots"]["siso_metrics.json"]["attribution"], "unknown")

    def test_bounded_snapshots_and_output_are_explicit(self):
        evidence = self.begin()
        (self.out / "siso_explain").write_text("x" * (CAPTURE_BYTES + 100))
        result = self.read(evidence.finish(returncode=124, timed_out=True, stdout="x" * (CAPTURE_BYTES + 1)))
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["siso_snapshots"]["siso_explain"]["truncated"])
        self.assertTrue(result["output"]["stdout"]["truncated"])
        self.assertEqual((evidence.path / "siso_explain").stat().st_size, CAPTURE_BYTES)

    def test_file_count_is_bounded_and_omissions_are_explicit(self):
        evidence = self.begin()
        for index in range(MAX_FILES + 3):
            (self.out / f"siso_explain-{index:02}").write_text("fixture")
        result = self.read(evidence.finish(returncode=0))
        self.assertEqual(len(result["siso_snapshots"]), MAX_FILES)
        self.assertEqual(result["omitted_file_count"], 3)
        self.assertEqual(len(list(evidence.path.glob("siso_explain*"))), MAX_FILES)

    def test_unparseable_duration_remains_unknown(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        (self.out / "siso_metrics.json").write_text(json.dumps({"build_id": "one", "duration_nanos": "1" * 5000}))
        result = self.read(evidence.finish(returncode=0))
        snapshot = result["siso_snapshots"]["siso_metrics.json"]
        self.assertEqual(snapshot["attribution"], "unknown")
        self.assertEqual(snapshot["metrics_parse"], "malformed-or-unsupported-jsonl")
        self.assertNotIn("final_cumulative_duration_nanos", snapshot)

    def test_large_jsonl_keeps_final_duration_without_action_totals(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        metrics = self.out / "siso_metrics.json"
        metrics.write_text('{"step": {"name": "compile"}}\n' * 4000
                           + '{"build_id": "one", "duration_nanos": 12345}\n')
        result = self.read(evidence.finish(returncode=0))
        snapshot = result["siso_snapshots"][metrics.name]
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["final_cumulative_duration_nanos"], 12345)
        self.assertLessEqual((evidence.path / metrics.name).stat().st_size
                             + (evidence.path / snapshot["tail_file"]).stat().st_size, CAPTURE_BYTES)
        self.assertNotIn("action_count", snapshot)

    def test_malformed_jsonl_does_not_publish_duration(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        (self.out / "siso_metrics.json").write_text('{"build_id": "one", "duration_nanos": 100}\n{broken')
        result = self.read(evidence.finish(returncode=1))
        snapshot = result["siso_snapshots"]["siso_metrics.json"]
        self.assertEqual(snapshot["attribution"], "unknown")
        self.assertNotIn("final_cumulative_duration_nanos", snapshot)

    def test_unique_read_only_archive_and_finish_once(self):
        first = self.begin()
        path = first.finish(returncode=0)
        second = self.begin()
        self.assertNotEqual(path, second.finish(returncode=1))
        self.assertEqual((path / "manifest.json").stat().st_mode & 0o222, 0)
        self.assertEqual(path.stat().st_mode & 0o222, 0)
        with self.assertRaisesRegex(RuntimeError, "already finalized"):
            first.finish(returncode=1)

    def test_missing_inputs_and_symlinks_are_not_read(self):
        (self.out / "args.gn").unlink()
        evidence = self.begin()
        (self.out / "siso_explain").symlink_to(__file__)
        result = self.read(evidence.finish(returncode=None, error_type="OSError"))
        self.assertEqual(result["outcome"], "exception")
        self.assertEqual(result["args_at_start"]["status"], "missing-or-not-regular")
        self.assertEqual(result["siso_snapshots"]["siso_explain"]["status"], "missing-or-not-regular")

    def test_archive_root_symlink_is_refused(self):
        external = self.root / "other-lane"
        external.mkdir()
        (self.root / "archive").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            self.begin()
        self.assertEqual(list(external.iterdir()), [])

    def test_arcium_symlink_is_refused(self):
        external = self.root / "other-lane"
        external.mkdir()
        (self.root / ".arcium").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            BuildEvidence(self.root / ".arcium" / "build-evidence", self.out, ("autoninja",))
        self.assertEqual(list(external.iterdir()), [])

    def test_output_directory_symlink_is_refused_before_archiving(self):
        original = self.root / "original-out"
        self.out.rename(original)
        self.out.symlink_to(original, target_is_directory=True)
        with self.assertRaises(OSError):
            self.begin()
        self.assertFalse((self.root / "archive").exists())

    def test_output_replaced_by_symlink_is_never_read(self):
        (self.out / "siso_explain").write_text("previous invocation")
        evidence = self.begin()
        external = self.root / "other-lane"
        external.mkdir()
        marker = "EXTERNAL-LANE-MARKER"
        (external / "siso_explain").write_text(marker)
        (external / "siso_metadata.json").write_text('{"build_id": "external"}')
        self.out.rename(self.root / "original-out")
        self.out.symlink_to(external, target_is_directory=True)
        with patch("devutils.build_diagnostics.os.open", wraps=os.open) as opened:
            path = evidence.finish(returncode=7, stdout="command output")
        result = self.read(path)
        self.assertEqual(result["returncode"], 7)
        self.assertEqual(result["output_directory_status"], "changed-or-unavailable")
        self.assertEqual(result["siso_snapshots"]["siso_explain"]["status"],
                         "output-directory-changed-or-unavailable")
        self.assertNotIn("siso_metadata.json", result["siso_snapshots"])
        self.assertFalse(any(str(call.args[0]).startswith("siso_") for call in opened.call_args_list))
        self.assertFalse((path / "siso_explain").exists())
        self.assertTrue(all(marker.encode() not in item.read_bytes() for item in path.iterdir()))

    def test_replaced_archive_root_cannot_redirect_writes_and_closes_descriptors(self):
        evidence = self.begin()
        descriptors = list(evidence._directories.descriptors)
        external = self.root / "other-lane"
        external.mkdir()
        original = self.root / "original-archive"
        (self.root / "archive").rename(original)
        (self.root / "archive").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            evidence.finish(returncode=0, stdout="command output")
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual((original / evidence.path.name).stat().st_mode & 0o222, 0)
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_completed_archive_closes_owned_descriptors(self):
        evidence = self.begin()
        descriptors = list(evidence._directories.descriptors)
        evidence.finish(returncode=0)
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_constructor_failure_closes_owned_descriptors(self):
        original_open = os.open
        descriptors = []

        def opened(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            descriptors.append(descriptor)
            return descriptor

        with patch("devutils.build_diagnostics.os.open", side_effect=opened):
            with patch("devutils.build_diagnostics._write_new", side_effect=OSError("fixture")):
                with self.assertRaisesRegex(OSError, "fixture"):
                    self.begin()
        self.assertTrue(descriptors)
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_output_swap_during_open_uses_owned_directory(self):
        evidence = self.begin()
        source = self.out / "siso_explain"
        source.write_text("owned output")
        identity = source.stat().st_ino
        external = self.root / "other-lane"
        external.mkdir()
        marker = "EXTERNAL-LANE-MARKER"
        (external / source.name).write_text(marker)
        original_open = os.open
        opened_inode = []

        def swapping_open(name, flags, *args, **kwargs):
            if name == source.name:
                self.out.rename(self.root / "original-out")
                self.out.symlink_to(external, target_is_directory=True)
                descriptor = original_open(name, flags, *args, **kwargs)
                opened_inode.append(os.fstat(descriptor).st_ino)
                return descriptor
            return original_open(name, flags, *args, **kwargs)

        with patch("devutils.build_diagnostics.os.open", side_effect=swapping_open):
            path = evidence.finish(returncode=0)
        self.assertEqual(opened_inode, [identity])
        result = self.read(path)
        self.assertEqual(result["output_directory_status"], "changed-or-unavailable")
        self.assertEqual(result["siso_snapshots"][source.name]["status"],
                         "output-directory-changed-or-unavailable")
        self.assertTrue(all(marker.encode() not in item.read_bytes() for item in path.iterdir()))

    def test_archive_swap_during_write_uses_owned_directory(self):
        evidence = self.begin()
        external = self.root / "other-lane"
        external.mkdir()
        original = self.root / "original-archive"
        original_open = os.open

        def swapping_open(name, flags, *args, **kwargs):
            if name == "stdout.txt":
                (self.root / "archive").rename(original)
                (self.root / "archive").symlink_to(external, target_is_directory=True)
            return original_open(name, flags, *args, **kwargs)

        with patch("devutils.build_diagnostics.os.open", side_effect=swapping_open):
            with self.assertRaises(OSError):
                evidence.finish(returncode=0, stdout="owned command output")
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual((original / evidence.path.name / "stdout.txt").read_text(), "owned command output")

    def test_deeply_nested_metadata_and_metrics_are_bounded_and_unknown(self):
        self.assertEqual(len(NESTED_JSON.encode()), 60001)
        self.assertLess(len(NESTED_JSON), CAPTURE_BYTES)
        try:
            json.loads(NESTED_JSON)
        except RecursionError:
            parser_rejects_nesting = True
        else:
            parser_rejects_nesting = False
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text(NESTED_JSON)
        (self.out / "siso_metrics.json").write_text(NESTED_JSON)
        result = self.read(evidence.finish(returncode=0))
        self.assertEqual(result["outcome"], "success")
        snapshot = result["siso_snapshots"]["siso_metrics.json"]
        self.assertEqual(snapshot["attribution"], "unknown")
        self.assertNotIn("final_cumulative_duration_nanos", snapshot)
        self.assertEqual(result["cache_delta"]["status"], "unknown")
        if parser_rejects_nesting:
            self.assertEqual(result["siso_snapshots"]["siso_metadata.json"]["metadata_parse"],
                             "malformed-or-unsupported-json")
            self.assertEqual(snapshot["metrics_parse"], "malformed-or-unsupported-jsonl")

    def test_parser_recursion_failures_have_explicit_evidence(self):
        evidence = self.begin()
        (self.out / "siso_metadata.json").write_text('{"build_id": "one"}')
        (self.out / "siso_metrics.json").write_text('{"build_id": "one", "duration_nanos": 123}\n')
        # Python 3.14 accepts nesting that raises on 3.13. Inject the parser
        # failure as well so both supported interpreters exercise this branch.
        with patch("devutils.build_diagnostics.json.loads", side_effect=RecursionError("nested fixture")):
            path = evidence.finish(returncode=0)
        result = self.read(path)
        self.assertEqual(result["siso_snapshots"]["siso_metadata.json"]["metadata_parse"],
                         "malformed-or-unsupported-json")
        snapshot = result["siso_snapshots"]["siso_metrics.json"]
        self.assertEqual(snapshot["metrics_parse"], "malformed-or-unsupported-jsonl")
        self.assertEqual(snapshot["attribution"], "unknown")
        self.assertNotIn("final_cumulative_duration_nanos", snapshot)


class IntegrationTests(unittest.TestCase):
    setUp = build_fixtures.HeliumDevBuildTest.setUp
    tearDown = build_fixtures.HeliumDevBuildTest.tearDown

    def test_no_work_archives_only_dry_run_without_added_calls(self):
        self.runner.edge_count = 0
        result = self.builder.compile(("obj/example.o",))
        self.assertTrue(result.ok)
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(len(result.evidence_paths), 1)
        document = json.loads((Path(result.evidence_paths[0]) / "manifest.json").read_text())
        self.assertEqual(document["mode"], "dry-run")
        self.assertIn("no work to do", (Path(result.evidence_paths[0]) / "stdout.txt").read_text())

    def test_dry_run_and_build_get_separate_archives(self):
        result = self.builder.compile(("obj/example.o",))
        self.assertEqual(len(result.evidence_paths), 2)
        documents = [json.loads((Path(path) / "manifest.json").read_text()) for path in result.evidence_paths]
        self.assertEqual([item["mode"] for item in documents], ["dry-run", "build"])
        self.assertEqual(documents[1]["siso_snapshots"]["siso_explain"]["status"], "unchanged-not-current")

    def test_failed_dry_run_is_archived(self):
        self.runner.dry_run_error = "FAILED: fixture"
        result = self.builder.compile(("obj/example.o",))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.evidence_paths), 1)
        self.assertEqual(json.loads((Path(result.evidence_paths[0]) / "manifest.json").read_text())["returncode"], 1)

    def test_runner_exception_archived_and_preserved(self):
        with patch.object(self.builder, "runner", side_effect=OSError("fixture")):
            with self.assertRaisesRegex(OSError, "fixture"):
                self.builder._run(self.builder._autoninja_command(("chrome",), dry_run=False))
        paths = list((self.source.parent / ".arcium" / "build-evidence").glob("*/manifest.json"))
        self.assertEqual(len(paths), 1)
        self.assertEqual(json.loads(paths[0].read_text())["error_type"], "OSError")

    def test_diagnostic_failure_does_not_replace_build_result(self):
        with patch("devutils.helium_dev_build.BuildEvidence", side_effect=OSError("fixture")):
            result = self.builder.compile(("obj/example.o",))
        self.assertTrue(result.ok)
        self.assertTrue(any("evidence unavailable" in warning for warning in result.warnings))

    def test_failed_build_keeps_both_invocations(self):
        original_runner = self.runner
        def failing_build(args, **kwargs):
            if "query" not in args and "-n" not in args:
                return CommandResult(args=tuple(args), returncode=1, stderr="error: fixture")
            return original_runner(args, **kwargs)
        self.builder.runner = failing_build
        result = self.builder.compile(("obj/example.o",))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.evidence_paths), 2)
        document = json.loads((Path(result.evidence_paths[-1]) / "manifest.json").read_text())
        self.assertEqual(document["outcome"], "failed")
        self.assertEqual(document["mode"], "build")

    def test_finish_io_failure_does_not_replace_build_result(self):
        with patch("devutils.helium_dev_build.BuildEvidence.finish", side_effect=OSError("fixture")):
            result = self.builder.compile(("obj/example.o",))
        self.assertTrue(result.ok)
        self.assertTrue(any("evidence incomplete" in warning for warning in result.warnings))

    def test_nested_diagnostics_preserve_the_exact_command_result(self):
        argv = self.builder._autoninja_command(("obj/example.o",), dry_run=False)
        expected = CommandResult(args=tuple(argv), returncode=17, stdout="fixture stdout", stderr="fixture stderr")
        calls = []

        def runner(args, **kwargs):
            calls.append(tuple(args))
            (self.output / "siso_metadata.json").write_text(NESTED_JSON)
            (self.output / "siso_metrics.json").write_text(NESTED_JSON)
            return expected

        self.builder.runner = runner
        result = self.builder._run(argv)
        self.assertIs(result, expected)
        self.assertEqual(calls, [tuple(argv)])
        path = Path(self.builder._evidence_paths[-1])
        document = json.loads((path / "manifest.json").read_text())
        self.assertEqual(document["returncode"], 17)
        self.assertEqual((path / "stdout.txt").read_text(), expected.stdout)
        self.assertEqual((path / "stderr.txt").read_text(), expected.stderr)
        self.assertEqual(document["siso_snapshots"]["siso_metrics.json"]["attribution"], "unknown")

    def test_parser_recursion_failure_preserves_the_exact_command_result(self):
        argv = self.builder._autoninja_command(("obj/example.o",), dry_run=False)
        expected = CommandResult(args=tuple(argv), returncode=0, stdout="fixture stdout")

        def runner(args, **kwargs):
            (self.output / "siso_metadata.json").write_text(NESTED_JSON)
            (self.output / "siso_metrics.json").write_text(NESTED_JSON)
            return expected

        original_loads = json.loads

        def refusing_nested(value, *args, **kwargs):
            if value.strip() == NESTED_JSON:
                raise RecursionError("nested fixture")
            return original_loads(value, *args, **kwargs)

        self.builder.runner = runner
        with patch("devutils.build_diagnostics.json.loads", side_effect=refusing_nested):
            result = self.builder._run(argv)
        self.assertIs(result, expected)
        document = json.loads((Path(self.builder._evidence_paths[-1]) / "manifest.json").read_text())
        self.assertEqual(document["siso_snapshots"]["siso_metadata.json"]["metadata_parse"],
                         "malformed-or-unsupported-json")
        self.assertEqual(document["siso_snapshots"]["siso_metrics.json"]["metrics_parse"],
                         "malformed-or-unsupported-jsonl")

    def test_symlinked_archive_root_preserves_build_result_without_archive_writes(self):
        external = self.source.parent / "other-lane"
        external.mkdir()
        state = self.source.parent / ".arcium"
        state.mkdir()
        (state / "build-evidence").symlink_to(external, target_is_directory=True)
        result = self.builder.compile(("obj/example.o",))
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence_paths, ())
        self.assertEqual(list(external.iterdir()), [])
        self.assertTrue(any("evidence unavailable" in warning for warning in result.warnings))
