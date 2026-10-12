"""Unit tests for devutils/he that need no Quilt or compiler."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import __main__ as cli, agent, quilt, records, scratch, test_assets, timestamps  # noqa: E402
from he.common import HeError, make_paths  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="he-", dir="/tmp")).resolve()
        self.paths = make_paths(self.root / "w", self.root / "b")
        (self.paths.catalog).mkdir(parents=True)
        (self.paths.src / ".pc").mkdir(parents=True)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def apply(self, *names: str) -> None:
        (self.paths.src / ".pc" / "applied-patches").write_text("".join(f"{n}\n" for n in names))
        for name in names:
            (self.paths.src / ".pc" / name).mkdir(parents=True, exist_ok=True)

    def series(self, *names: str) -> None:
        (self.paths.catalog / "series.merged").write_text("".join(f"{n}\n" for n in names))
        for name in names:
            (self.paths.catalog / name).parent.mkdir(parents=True, exist_ok=True)
            (self.paths.catalog / name).write_text(f"patch {name}\n")


class QuiltTest(Fixture):
    def test_series_comments_options_and_unsafe_names(self) -> None:
        path = self.root / "series"
        path.write_text("# comment\n\na.patch -p1\nsub/b.patch # note\n")
        self.assertEqual(quilt.read_list(path), ("a.patch", "sub/b.patch"))
        path.write_text("../escape.patch\n")
        with self.assertRaises(HeError):
            quilt.read_list(path)

    def test_patch_files_skip_quilt_metadata(self) -> None:
        self.apply("p.patch")
        backup = self.paths.src / ".pc" / "p.patch"
        (backup / "dir").mkdir()
        (backup / "dir" / "x.cc").write_text("")
        (backup / ".timestamp").write_text("")
        self.assertEqual(quilt.patch_files(self.paths.src, "p.patch"), ["dir/x.cc"])


class AppliedRecordTest(Fixture):
    def test_new_patches_take_the_lane_hash_and_old_ones_keep_theirs(self) -> None:
        self.series("a.patch", "b.patch")
        records.mark_before_push(self.paths)
        self.apply("a.patch")
        records.sync_applied(self.paths)
        first = json.loads((self.paths.state / "applied.json").read_text())["patches"]["a.patch"]
        (self.paths.catalog / "a.patch").write_text("edited\n")
        records.mark_before_push(self.paths)
        self.apply("a.patch", "b.patch")
        records.sync_applied(self.paths)
        current = json.loads((self.paths.state / "applied.json").read_text())["patches"]
        self.assertEqual(current["a.patch"], first)
        self.assertIn("b.patch", current)
        self.assertEqual(len(records.applied_drift(self.paths)), 1)
        records.sync_applied(self.paths, rebaseline=("a.patch",))
        self.assertEqual(records.applied_drift(self.paths), [])

    def test_patches_applied_before_the_push_stay_unrecorded(self) -> None:
        self.series("a.patch", "b.patch")
        self.apply("a.patch")  # applied outside he
        records.mark_before_push(self.paths)
        self.apply("a.patch", "b.patch")
        records.sync_applied(self.paths)
        current = json.loads((self.paths.state / "applied.json").read_text())["patches"]
        self.assertEqual(set(current), {"b.patch"})


class TimestampTest(Fixture):
    def test_partial_stack_is_not_captured(self) -> None:
        self.series("a.patch", "b.patch")
        self.apply("a.patch")
        message = timestamps.capture(self.paths)
        self.assertIn("not fully applied", message)
        self.assertFalse(timestamps.pending(self.paths))

    def test_keeper_switch(self) -> None:
        self.series("a.patch")
        self.apply("a.patch")
        with mock.patch.dict(os.environ, {"HELIUM_KEEP_TIMESTAMPS": "0"}):
            self.assertIn("off", timestamps.capture(self.paths))
        self.assertFalse(timestamps.pending(self.paths))

    def test_unsafe_journal_paths_are_ignored(self) -> None:
        for relative in ("../x", "/abs", "out/Default/a.o", ".pc/p/x", ".git/config"):
            self.assertFalse(timestamps._safe(relative), relative)
        self.assertTrue(timestamps._safe("chrome/browser/x.cc"))


class ScratchAndTmpTest(Fixture):
    def test_scratch_names_are_validated(self) -> None:
        with self.assertRaises(HeError):
            scratch.scratch_root(self.paths, "../escape")

    def test_scratch_needs_a_fully_applied_stack(self) -> None:
        self.series("a.patch")
        with self.assertRaises(HeError):
            scratch.create(self.paths, "w")

    def test_tmpdir_rejects_paths_too_long_for_sccache(self) -> None:
        with mock.patch.dict(os.environ, {"HELIUM_TMPDIR": "/tmp/" + "x" * 100}):
            with self.assertRaises(HeError):
                cli._tmpdir(self.paths)


class AgentAndAssetsTest(Fixture):
    def test_planned_edges_reads_ninja_and_siso_progress(self) -> None:
        self.assertEqual(agent.planned_edges("[1/4] cc a\n[2/4] cc b\n"), 4)
        self.assertEqual(agent.planned_edges("ninja: no work to do.\n"), 0)
        siso = ("build start: Ready 1 Pending 1\nrebuild manifest finished\n"
                "schedule pending:1+ready:0 (node:9 edge:2)\n1m09.24s schedule pending:7+ready:2 (node:9 edge:9)\n"
                "clang++ -c a.cc -o a.o\nrm -rf x && cp -Rc y x\n\nbuild finished\nlocal:0 remote:0 skip:7\n")
        self.assertEqual(agent.planned_edges(siso), 2)
        self.assertEqual(agent.planned_edges("rebuild manifest finished\nbuild finished\n"), 0)

    def test_test_font_archives_cannot_escape_their_directory(self) -> None:
        import io
        import tarfile
        archive = self.root / "fonts.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            data = b"x"
            info = tarfile.TarInfo("../escape.ttf")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(HeError):
            test_assets._archive_members(archive)


class InstallerUnitTest(Fixture):
    def test_install_path_override_needs_test_mode(self) -> None:
        from arcium import install
        with mock.patch.dict(os.environ, {"HELIUM_ARCIUM_TEST_INSTALL_PATH": "/tmp/elsewhere.app"}, clear=False):
            os.environ.pop("HELIUM_TEST_MODE", None)
            self.assertEqual(install.install_path(), install.DEFAULT_INSTALL_PATH)

    def test_interrupted_publish_puts_the_previous_bundle_back(self) -> None:
        import plistlib
        from arcium import install
        app = self.root / "Arcium.app"
        staging = self.root / ".Arcium.app.install"
        for bundle in (app, staging):
            (bundle / "Contents").mkdir(parents=True)
            with (bundle / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": "net.imput.arcium", "CrProductDirName": "Arcium"}, handle)
        real_replace = os.replace
        calls = []

        def interrupted(source, destination):
            calls.append(source)
            real_replace(source, destination)
            if len(calls) == 1:
                raise KeyboardInterrupt

        with mock.patch.object(install.os, "replace", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                install._publish(staging, app)
        self.assertTrue((app / "Contents" / "Info.plist").is_file())
        self.assertTrue(staging.exists())


if __name__ == "__main__":
    unittest.main()
