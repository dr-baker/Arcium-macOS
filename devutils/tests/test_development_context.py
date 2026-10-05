"""Focused tests for the read-only development-context preflight."""

from __future__ import annotations

import io
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from devutils.build_lane import LaneError, LaneReport, LaneSpec, VolumeInfo
from devutils.quilt_state import SeriesComparison, QuiltStateReport
from devutils import development_context


def _run(*arguments: str, cwd: Path) -> str:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class DevelopmentContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.worktree = root / "helium-macos"
        self.core = self.worktree / "helium-chromium"
        self.worktree.mkdir()
        self.core.mkdir()
        for repository in (self.core, self.worktree):
            _run("git", "init", "-q", cwd=repository)
            _run("git", "config", "user.name", "Context Test", cwd=repository)
            _run("git", "config", "user.email", "context@example.invalid", cwd=repository)
        (self.core / "README").write_text("core\n", encoding="utf-8")
        _run("git", "add", "README", cwd=self.core)
        _run("git", "commit", "-q", "-m", "core", cwd=self.core)
        core_head = _run("git", "rev-parse", "HEAD", cwd=self.core)
        _run("git", "-C", str(self.worktree), "update-index", "--add", "--cacheinfo", f"160000,{core_head},helium-chromium", cwd=self.worktree)
        _run("git", "commit", "-q", "-m", "outer", cwd=self.worktree)
        self.build_root = self.worktree / "build"
        self.source_dir = self.build_root / "src"
        self.source_dir.mkdir(parents=True)
        (self.source_dir / ".pc").mkdir()

    def tearDown(self) -> None:
        # Keep this assertion explicit: the test must never need to clean up
        # source, Quilt, receipt, or lane state beyond its temporary fixture.
        self.assertTrue(self.worktree.exists())

    def _lane_inspector(self, spec: LaneSpec) -> LaneReport:
        volume = VolumeInfo(
            mount_point=self.build_root,
            volume_uuid="local-volume",
            filesystem_type="apfs",
            filesystem_name="APFS",
            free_bytes=100,
            writable=True,
            external=False,
            encrypted=True,
            ownership_enabled=True,
            solid_state=True,
            bus_protocol=None,
        )
        return LaneReport(spec=spec, volume=volume, diagnostics=())

    def _quilt_inspector(self, source: Path, patches: Path) -> QuiltStateReport:
        comparison = SeriesComparison(
            declared=("one.patch", "two.patch"),
            applied=("one.patch", "two.patch"),
            valid_prefix=True,
            complete=True,
            divergence_index=None,
            expected=None,
            actual=None,
            detail=None,
        )
        return QuiltStateReport(
            source_dir=source,
            patches_dir=patches,
            series_name="series.merged",
            comparison=comparison,
            declared_sha256="a" * 64,
            applied_sha256="b" * 64,
        )

    def _write_exact_dev_bundle(self) -> Path:
        app = self.source_dir / "out" / "Default" / "Helium Dev.app"
        executable = app / "Contents" / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_text("dev\n", encoding="utf-8")
        executable.chmod(0o755)
        with (app / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": "Helium",
                    "CFBundleIdentifier": "net.imput.helium.dev",
                    "CFBundleDisplayName": "Helium Dev",
                },
                handle,
            )
        return app

    def test_context_reports_composed_state_without_dirty_paths(self) -> None:
        (self.worktree / "private-name-that-must-not-appear").write_text("dirty\n", encoding="utf-8")
        app = self._write_exact_dev_bundle()
        replay = SimpleNamespace(receipt_id="r" * 64)
        execution = SimpleNamespace(receipt_id="e" * 64)
        package = SimpleNamespace(receipt_id="p" * 64)

        document = development_context.collect_context(
            self.worktree,
            product="dev",
            build_root=self.build_root,
            lane="local",
            lane_inspector=self._lane_inspector,
            quilt_inspector=self._quilt_inspector,
            replay_checker=lambda *_: replay,
            execution_checker=lambda *args, **kwargs: execution,
            package_checker=lambda *args, **kwargs: package,
        )

        self.assertTrue(document["ok"])
        self.assertTrue(document["outer"]["dirty"])
        self.assertGreaterEqual(document["outer"]["dirty_records"], 1)
        self.assertIn("core_repository", document)
        self.assertNotIn("private-name-that-must-not-appear", str(document))
        self.assertEqual(document["core"]["head"], document["core"]["gitlink"])
        self.assertEqual(document["quilt"]["applied_count"], 2)
        self.assertEqual(document["quilt"]["top"], "two.patch")
        self.assertEqual(document["receipts"]["package"]["state"], "current")
        self.assertEqual(document["dev_bundle"]["path"], str(app.resolve()))
        self.assertEqual(document["dev_bundle"]["freshness"], "current")

    def test_heavy_lane_limit_is_actionable_and_receipts_short_circuit(self) -> None:
        calls = []

        def unavailable(spec: LaneSpec) -> LaneReport:
            raise LaneError("no mounted volume at /Volumes/T9/ArciumBuild/build")

        def replay_checker(*args):
            calls.append("replay")
            raise development_context.ReplayError(
                "no current Quilt replay proof; run he replay"
            )

        def execution_checker(*args, **kwargs):
            calls.append("build")
            return SimpleNamespace(receipt_id="e" * 64)

        document = development_context.collect_context(
            self.worktree,
            product="dev",
            build_root=self.build_root,
            lane="heavy",
            lane_inspector=unavailable,
            replay_checker=replay_checker,
            execution_checker=execution_checker,
        )

        self.assertFalse(document["ok"])
        self.assertIn("selected heavy lane unavailable", "\n".join(document["limits"]))
        self.assertEqual(calls, ["replay"])
        self.assertEqual(document["receipts"]["build"]["state"], "blocked")
        self.assertEqual(document["receipts"]["package"]["state"], "blocked")

    def test_json_cli_emits_one_machine_readable_document(self) -> None:
        document = {"ok": True, "action": "context", "limits": []}
        output = io.StringIO()
        with patch.object(development_context, "collect_context", return_value=document):
            with redirect_stdout(output):
                code = development_context.main(
                    ["--worktree", str(self.worktree), "--lane", "local", "--json"]
                )
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), '{"action":"context","limits":[],"ok":true}\n')

    def test_arcium_context_cli_uses_installed_proof_without_dev_bundle(self) -> None:
        options = dict(
            build_root=self.build_root, lane_inspector=self._lane_inspector,
            quilt_inspector=self._quilt_inspector,
            replay_checker=lambda *_: SimpleNamespace(receipt_id="replay"),
            execution_checker=lambda *a, **k: SimpleNamespace(receipt_id="execution"),
            package_checker=lambda *a, **k: self.fail("Arcium context required Dev packaging"),
            installed_checker=lambda *a, **k: {
                "path": "/Applications/Arcium.app", "exists": True,
                "exact": True, "freshness": "current", "error": None,
                "receipt_id": "installed",
            },
            storage_probe=lambda *a: {"kind": "image", "image_path": "/disk/build.sparseimage", "host": {"mount_point": "/disk", "volume_uuid": "host-uuid", "filesystem": "APFS", "free_bytes": 50}, "available": True, "effective_free_bytes": 50},
        )
        real_collect = development_context.collect_context
        with patch.object(development_context, "collect_context", side_effect=lambda worktree, **kw: real_collect(worktree, **{**options, **kw})):
            output = io.StringIO()
            with redirect_stdout(output):
                code = development_context.main(["--worktree", str(self.worktree), "--build-root", str(self.build_root)])
        self.assertEqual(code, 0)
        self.assertIn("context: arcium", output.getvalue())
        self.assertIn("arcium: /Applications/Arcium.app · current", output.getvalue())
        self.assertIn("backing image: /disk/build.sparseimage", output.getvalue())
        self.assertIn("UUID host-uuid", output.getvalue())
        self.assertNotIn("dev:", output.getvalue())

    def test_conclusive_backing_host_failure_prevents_ready_context(self):
        document = development_context.collect_context(
            self.worktree, build_root=self.build_root,
            lane_inspector=self._lane_inspector, quilt_inspector=self._quilt_inspector,
            replay_checker=lambda *_: SimpleNamespace(receipt_id="replay"),
            execution_checker=lambda *a, **k: SimpleNamespace(receipt_id="execution"),
            product="arcium", installed_checker=lambda *a, **k: {
                "path": "/Applications/Arcium.app", "exact": True,
                "freshness": "current", "error": None,
            },
            storage_probe=lambda *a: {"kind": "image", "available": False,
                                      "error": "backing image host is not writable"},
        )
        self.assertFalse(document["ok"])
        self.assertFalse(document["lane"]["available"])
        self.assertIn("backing image host is not writable", document["limits"])

    def test_selector_prefers_first_verified_candidate_and_rejects_unready(self) -> None:
        candidates = [
            {"name": "heavy", "build_root": "/t9/build"},
            {"name": "local", "build_root": "/local/build"},
        ]
        docs = {
            "heavy": {"ok": False, "limits": ["T9 unavailable"]},
            "local": {"ok": True, "limits": [], "dev_bundle": {"freshness": "current"}},
        }
        result = development_context.select_warm_lane(candidates, lambda c: docs[str(c["name"])])
        self.assertEqual(result["selected"]["name"], "local")
        rejected = development_context.select_warm_lane(
            candidates, lambda c: {"ok": False, "limits": ["missing proof"]}
        )
        self.assertIsNone(rejected["selected"])
        self.assertIn("he replay", rejected["error"])


if __name__ == "__main__":
    unittest.main()
