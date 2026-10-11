"""End-to-end `he` commands against the mini-Chromium fixture.

These drive the real dev.sh, Quilt, Ninja, and clang++ on a toy tree.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minichromium import CORE_PATCH, LONG_PATCH, OUTER_PATCH, PRISTINE, TOOLS, MiniChromium, run  # noqa: E402

REQUIRED = all(shutil.which(tool) for tool in ("quilt", "ninja", "clang++", "bash", "git"))


@unittest.skipUnless(REQUIRED, "needs quilt, ninja, clang++, bash, and git")
class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MiniChromium()
        self.addCleanup(self.m.cleanup)

    # Catalog -----------------------------------------------------------------

    def test_merge_keeps_git_clean_and_writes_lane_catalog(self) -> None:
        self.m.he("merge")
        status = run(["git", "status", "--porcelain"], cwd=self.m.worktree).stdout
        self.assertEqual(status, "")
        merged = (self.m.build_dir / ".arcium" / "patches" / "series.merged").read_text()
        self.assertIn(CORE_PATCH, merged)
        self.assertIn(OUTER_PATCH, merged)

    def test_merge_refuses_while_patches_are_applied(self) -> None:
        self.m.he("merge")
        self.m.he("push")
        result = self.m.he("merge", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fully popped", result.stderr)

    # Strict push ---------------------------------------------------------------

    def _shift_long_cc_context(self) -> None:
        """Change a context line near the long patch's hunk, as an upstream bump would."""
        path = self.m.src / "long.cc"
        path.write_text(path.read_text().replace("return 8;", "return 8; // moved"))

    def test_push_stops_on_fuzz_and_refresh_restores_upstream_behavior(self) -> None:
        self.m.he("merge")
        self._shift_long_cc_context()
        before = (self.m.build_dir / ".arcium" / "patches" / LONG_PATCH).read_bytes()
        strict = self.m.he("push", check=False)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIn("push stopped", strict.stderr)
        applied = (self.m.src / ".pc" / "applied-patches").read_text().split()
        self.assertEqual(applied, [CORE_PATCH, OUTER_PATCH])
        self.assertEqual((self.m.build_dir / ".arcium" / "patches" / LONG_PATCH).read_bytes(), before)
        self.m.he("push", "--refresh")
        self.assertNotEqual((self.m.build_dir / ".arcium" / "patches" / LONG_PATCH).read_bytes(), before)

    # Timestamp keeper ------------------------------------------------------------

    def test_pop_and_push_without_edits_rebuilds_nothing(self) -> None:
        self.m.ready()
        self.m.he("pop")
        self.m.he("push")
        self.assertEqual(self.m.would_rebuild(), set())

    def test_keeper_off_rebuilds_every_popped_file(self) -> None:
        self.m.ready()
        self.m.he("pop", HELIUM_KEEP_TIMESTAMPS="0")
        self.m.he("push", HELIUM_KEEP_TIMESTAMPS="0")
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_header_edit_in_early_patch_rebuilds_only_its_consumers(self) -> None:
        self.m.ready()
        self.m.he("pop", CORE_PATCH)
        header = self.m.src / "h.h"
        header.write_text(header.read_text() + "int k();\n")
        self.m.he("save-patch")
        self.m.he("push")
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o"})
        saved = (self.m.worktree / "helium-chromium" / "patches" / CORE_PATCH).read_text()
        self.assertIn("+int k();", saved)

    def test_he_build_while_popped_drops_the_snapshot(self) -> None:
        self.m.ready()
        self.m.he("pop")
        result = self.m.he("build")
        self.assertIn("timestamp snapshot discarded", result.stderr)
        self.m.he("push")
        # Objects were compiled from unpatched sources; they must rebuild.
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_raw_ninja_while_popped_skips_restoration(self) -> None:
        self.m.ready()
        self.m.he("pop")
        self.m.ninja("chrome")
        result = self.m.he("push")
        self.assertIn("timestamps not restored", result.stderr)
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_failing_action_that_overwrites_output_skips_restoration(self) -> None:
        self.m.ready()
        self.m.he("pop")
        # A failed build step can leave a rewritten output without a log entry.
        (self.m.out / "obj" / "a.o").write_bytes(b"partial")
        result = self.m.he("push")
        self.assertIn("timestamps not restored", result.stderr)

    def test_failed_push_keeps_the_original_snapshot(self) -> None:
        self.m.ready()
        self.m.he("pop")
        journal = self.m.build_dir / ".arcium" / "timestamps.json"
        original = journal.read_bytes()
        self._shift_long_cc_context()
        self.assertNotEqual(self.m.he("push", check=False).returncode, 0)
        self.assertEqual(journal.read_bytes(), original)
        # Undo the simulated upstream change and finish the push.
        (self.m.src / "long.cc").write_text(PRISTINE["long.cc"])
        self.m.he("push")
        self.assertFalse(journal.exists())
        # Every file ended byte-identical to the snapshot, so nothing rebuilds.
        self.assertEqual(self.m.would_rebuild(), set())

    def test_corrupt_snapshot_is_discarded_and_push_succeeds(self) -> None:
        self.m.ready()
        self.m.he("pop")
        (self.m.build_dir / ".arcium" / "timestamps.json").write_text("{not json")
        result = self.m.he("push")
        self.assertIn("unreadable", result.stderr)
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    # Records and checks ----------------------------------------------------------

    def test_check_reports_worktree_patch_changes(self) -> None:
        self.m.ready()
        self.assertEqual(self.m.he("check").returncode, 0)
        self.m.write_patch(OUTER_PATCH, core=False, files={"a.cc": '#include "h.h"\nint a() { return f() + 2; }\n'})
        result = self.m.he("check", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{OUTER_PATCH} changed in the worktree", result.stdout)

    def test_check_reports_lane_copy_changed_after_apply(self) -> None:
        self.m.ready()
        copy = self.m.build_dir / ".arcium" / "patches" / LONG_PATCH
        copy.write_text(copy.read_text() + "\n")
        result = self.m.he("check", check=False)
        self.assertIn("changed in the lane catalog after it was applied", result.stdout)

    def test_pushing_the_suffix_does_not_rebaseline_the_prefix(self) -> None:
        self.m.ready()
        self.m.he("pop", CORE_PATCH)
        # Edit the still-applied core patch's lane copy without refreshing.
        copy = self.m.build_dir / ".arcium" / "patches" / CORE_PATCH
        copy.write_text(copy.read_text().replace("+int g();", "+int g(); // edited"))
        self.m.he("push")
        result = self.m.he("check", check=False)
        self.assertIn(f"{CORE_PATCH} changed in the lane catalog after it was applied", result.stdout)

    def test_stamps_report_changed_resources(self) -> None:
        self.m.ready()
        (self.m.worktree / "resources" / "icon.txt").write_text("new icon\n")
        result = self.m.he("check", check=False)
        self.assertIn("resources inputs changed", result.stdout)

    def test_mismatched_chromium_version_is_refused(self) -> None:
        self.m.he("merge")
        (self.m.worktree / "helium-chromium" / "chromium_version.txt").write_text("155.0.8059.39\n")
        result = self.m.he("push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pins 155.0.8059.39", result.stderr)

    # save-patch and unmerge --------------------------------------------------------

    def test_save_patch_refuses_after_a_concurrent_authoritative_edit(self) -> None:
        self.m.ready()
        self.m.he("pop", OUTER_PATCH)
        self.m.write_patch(OUTER_PATCH, core=False, files={"a.cc": '#include "h.h"\nint a() { return 7; }\n'})
        result = self.m.he("save-patch", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since he merge", result.stderr)

    def test_unmerge_exports_new_patches_like_upstream(self) -> None:
        self.m.he("merge")
        self.m.he("push")
        self.m.quilt("new", "personal/new.patch")
        self.m.quilt("add", "b.cc")
        (self.m.src / "b.cc").write_text("int b() { return 3; }\n")
        self.m.quilt("refresh")
        self.m.he("pop")
        self.m.he("unmerge")
        series = (self.m.worktree / "patches" / "series").read_text().split()
        self.assertEqual(series[-1], "personal/new.patch")
        self.assertTrue((self.m.worktree / "patches" / "personal" / "new.patch").is_file())
        self.assertFalse((self.m.build_dir / ".arcium" / "patches").exists())

    # Locks ----------------------------------------------------------------------

    def test_second_command_is_refused_while_the_lock_is_held(self) -> None:
        self.m.he("merge")
        lock = self.m.build_dir / ".arcium" / "lane.lock"
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.m.he("push", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is busy", result.stderr)

    # Worktree switching -----------------------------------------------------------

    def test_switching_worktrees_rebuilds_only_differing_patches(self) -> None:
        self.m.ready()
        other = self.m.root / "other"
        run(["git", "worktree", "add", "-q", str(other)], cwd=self.m.worktree)
        for name in ("env.sh",):
            shutil.copy2(self.m.worktree / name, other / name)
        (other / "devutils").mkdir(exist_ok=True)
        shutil.copy2(self.m.worktree / "devutils" / "setup_python.sh", other / "devutils" / "setup_python.sh")
        (other / "patches" / OUTER_PATCH).write_text(
            (other / "patches" / OUTER_PATCH).read_text().replace("return 2;", "return 5;"))
        self.m.he("pop")
        self.m.he("merge", HELIUM_DEV_WORKTREE=str(other))
        self.m.he("push", HELIUM_DEV_WORKTREE=str(other))
        self.assertEqual(self.m.would_rebuild(), {"obj/b.o"})

    # Scratch ----------------------------------------------------------------------

    def test_scratch_supports_patch_authoring_and_refuses_builds(self) -> None:
        self.m.ready()
        created = self.m.he("scratch", "worker")
        root = self.m.build_dir / ".arcium" / "scratch" / "worker"
        self.assertIn(str(root), created.stdout)
        self.assertFalse((root / "src" / "out").exists())
        pointer = (root / "src" / ".pc" / ".quilt_patches").read_text().strip()
        self.assertEqual(pointer, str(root / ".arcium" / "patches"))
        worker = {"HELIUM_BUILD_DIR": str(root)}
        self.m.he("pop", CORE_PATCH, **worker)
        (root / "src" / "p.cc").write_text("int f() { return 0; }\n// p\n// worker\n")
        self.m.he("save-patch", **worker)
        self.m.he("push", **worker)
        saved = (self.m.worktree / "helium-chromium" / "patches" / CORE_PATCH).read_text()
        self.assertIn("+// worker", saved)
        # The shared build dir was untouched and still has its applied stack.
        self.assertEqual((self.m.src / "p.cc").read_text(), "int f() { return 0; }\n// p\n")
        refused = self.m.he("build", check=False, **worker)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("scratch", refused.stderr)
        self.m.he("scratch", "--remove", "worker")
        self.assertFalse(root.exists())

    # Configuration ------------------------------------------------------------------

    def test_dev_env_supplies_build_dir_and_environment_wins(self) -> None:
        config = self.m.home / ".config" / "arcium"
        config.mkdir(parents=True)
        (config / "dev.env").write_text(f'HELIUM_BUILD_DIR="{self.m.build_dir}"\nNOT_OURS=1\n')
        env = self.m.env()
        env.pop("HELIUM_BUILD_DIR")
        script = f'source "{TOOLS / "dev.sh"}" >/dev/null && echo "$_build_dir|${{NOT_OURS:-}}"'
        result = run(["bash", "-c", script], env=env)
        self.assertEqual(result.stdout.strip(), f"{self.m.build_dir}|")
        env["HELIUM_BUILD_DIR"] = str(self.m.root / "elsewhere")
        result = run(["bash", "-c", script], env=env)
        self.assertEqual(result.stdout.strip(), f"{self.m.root / 'elsewhere'}|")

    def test_dev_sh_sources_in_zsh(self) -> None:
        if not shutil.which("zsh"):
            self.skipTest("zsh not installed")
        script = f'source "{TOOLS / "dev.sh"}" >/dev/null && echo "$_build_dir" && he check >/dev/null; echo $?'
        result = run(["zsh", "-c", script], env=self.m.env(), check=False)
        self.assertEqual(result.stdout.splitlines()[0], str(self.m.build_dir))

    def test_release_build_ignores_development_settings(self) -> None:
        script = (
            f'export HELIUM_BUILD_DIR=/nowhere _build_dir=/nowhere; '
            f'unset _build_dir HELIUM_BUILD_DIR HELIUM_DEV_WORKTREE HELIUM_TMPDIR; '
            f'_root_dir="{self.m.worktree}"; source "{self.m.worktree}/env.sh"; echo "$_src_dir"'
        )
        result = run(["bash", "-c", script], env=self.m.env())
        self.assertEqual(result.stdout.strip(), f"{self.m.worktree}/build/src")
        self.assertIn("unset _build_dir HELIUM_BUILD_DIR HELIUM_DEV_WORKTREE", (TOOLS / "build.sh").read_text())


if __name__ == "__main__":
    unittest.main()
