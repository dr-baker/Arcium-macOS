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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minichromium import CORE_PATCH, LONG_PATCH, OUTER_PATCH, PRISTINE, TOOLS, MiniChromium, run  # noqa: E402

REQUIRED = all(shutil.which(tool) for tool in ("quilt", "ninja", "clang++", "bash", "git"))


@unittest.skipUnless(REQUIRED, "needs quilt, ninja, clang++, bash, and git")
class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.m = MiniChromium()
        self.addCleanup(self.m.cleanup)

    def test_lane_shell_dispatch_reserves_and_guards_shared_mutations(self) -> None:
        from he.lane import Lane
        self.m.he("lane", "init", "--coordinator", "coordinator")
        state = self.m.build_dir / ".arcium"
        lane = Lane(state)
        lane.heartbeat(True)
        self.m.he("lane", "resume", "--note", "fixture delivery verified")
        request = json.loads(self.m.he("lane", "request", "--thread", "a", "--key", "build",
                                      "--note", "fixture integration").stdout)
        lane.offer_next()
        generation = lane.status()["offer"]["generation"]
        owner = json.loads(self.m.he("lane", "claim", request["id"], "--thread", "a",
                                    "--offer", str(generation)).stdout)
        refused = self.m.he("merge", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("reservation", refused.stderr)
        self.m.he("merge", HELIUM_LANE_TOKEN=owner["token"])
        self.m.he("push", HELIUM_LANE_TOKEN=owner["token"])
        self.assertEqual(lane.status()["owner"]["request"], request["id"])
        self.m.he("lane", "release", "--note", "fixture replay complete", HELIUM_LANE_TOKEN=owner["token"])
        stale = self.m.he("pop", check=False, HELIUM_LANE_TOKEN=owner["token"])
        self.assertNotEqual(stale.returncode, 0)

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

    def test_push_accepts_line_offsets_without_refreshing_patch(self) -> None:
        self.m.he("merge")
        path = self.m.src / "long.cc"
        path.write_text("// Extra line before unchanged context.\n" + path.read_text())
        patch = self.m.build_dir / ".arcium" / "patches" / LONG_PATCH
        before = patch.read_bytes()
        result = self.m.he("push")
        self.assertIn("offset 1 line", result.stdout)
        self.assertEqual(patch.read_bytes(), before)
        self.assertIn(LONG_PATCH, (self.m.src / ".pc" / "applied-patches").read_text().split())

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

    def test_merge_refuses_unsaved_lane_edits(self) -> None:
        self.m.ready()
        self.m.he("pop", LONG_PATCH)
        (self.m.src / "long.cc").write_text((self.m.src / "long.cc").read_text() + "// edit\n")
        self.m.quilt("refresh")
        self.m.he("pop")
        refused = self.m.he("merge", check=False)
        self.assertIn("not saved back", refused.stderr)
        self.m.he("merge", "--discard")
        self.assertNotIn("// edit", (self.m.worktree / "patches" / LONG_PATCH).read_text())

    def test_scratch_holds_only_owned_files_and_pulls_others(self) -> None:
        self.m.ready()
        root = self.m.build_dir / ".arcium" / "scratch" / "w"
        self.m.he("scratch", "w")
        self.assertTrue((root / "src" / "h.h").is_file())
        self.assertFalse((root / "src" / "unowned.cc").exists())
        worker = {"HELIUM_BUILD_DIR": str(root)}
        # Adding a file the scratch lacks would record it as a new file.
        self.m.quilt("add", "unowned.cc", cwd=root / "src")
        (root / "src" / "unowned.cc").write_text("int unowned() { return 1; }\n")
        refused = self.m.he("save-patch", **worker, check=False)
        self.assertIn("already exist in the shared tree", refused.stderr)
        self.m.quilt("remove", "unowned.cc", cwd=root / "src")
        (root / "src" / "unowned.cc").unlink(missing_ok=True)
        self.m.he("scratch-pull", "unowned.cc", **worker)
        self.m.quilt("add", "unowned.cc", cwd=root / "src")
        (root / "src" / "unowned.cc").write_text("int unowned() { return 1; }\n")
        self.m.he("save-patch", **worker)
        saved = (self.m.worktree / "patches" / LONG_PATCH).read_text()
        self.assertIn("-int unowned() { return 0; }", saved)

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
        self.m.ready()
        script = f'source "{TOOLS / "dev.sh"}" >/dev/null && echo "$_build_dir" && he pop >/dev/null 2>&1 && he push >/dev/null 2>&1 && he check'
        result = run(["zsh", "-c", script], env=self.m.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], str(self.m.build_dir))
        self.assertIn("ok: 3 patches applied and current", result.stdout)
        self.assertEqual(self.m.would_rebuild(), set())

    def test_release_build_ignores_development_settings(self) -> None:
        # build.sh refuses when <checkout>/build/src holds a Quilt tree. Put one
        # only there: refusing proves it ignored HELIUM_BUILD_DIR and dev.env.
        shutil.copy2(TOOLS / "build.sh", self.m.worktree / "build.sh")
        (self.m.worktree / "build" / "src" / ".pc").mkdir(parents=True)
        config = self.m.home / ".config" / "arcium"
        config.mkdir(parents=True)
        (config / "dev.env").write_text(f"HELIUM_BUILD_DIR={self.m.build_dir}\n")
        result = run(["bash", str(self.m.worktree / "build.sh"), "arm64"], env=self.m.env(), check=False)
        self.assertEqual(result.returncode, 2, result.stderr[-2000:])
        self.assertIn("Refusing to reset a development lane", result.stderr)
        self.assertTrue((self.m.src / "a.cc").exists())

    # Review round 1 regressions -----------------------------------------------------

    def test_symlinked_out_dir_still_detects_raw_builds(self) -> None:
        self.m.he("merge")
        self.m.he("push")
        target = self.m.root / "elsewhere" / "Default"
        target.parent.mkdir()
        shutil.move(str(self.m.out), str(target))
        self.m.out.symlink_to(target)
        ninja = target / "build.ninja"
        ninja.write_text(ninja.read_text().replace("../../", f"{self.m.src}/"))
        self.m.stamp_all()
        self.m.he("build")
        self.m.he("pop")
        self.m.ninja("chrome")
        result = self.m.he("push")
        self.assertIn("timestamps not restored", result.stderr)
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_touched_snapshot_is_not_trusted(self) -> None:
        self.m.ready()
        self.m.he("pop")
        self.m.ninja("chrome")
        os.utime(self.m.build_dir / ".arcium" / "timestamps.json")
        result = self.m.he("push")
        self.assertIn("modified after capture", result.stderr)
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_keeper_off_at_push_discards_the_snapshot(self) -> None:
        self.m.ready()
        self.m.he("pop")
        result = self.m.he("push", HELIUM_KEEP_TIMESTAMPS="0")
        self.assertIn("discarded", result.stderr)
        self.assertEqual(self.m.would_rebuild(), {"obj/a.o", "obj/b.o", "obj/p.o", "obj/long.o"})

    def test_raw_applied_prefix_stays_unrecorded_after_suffix_push(self) -> None:
        self.m.he("merge")
        self.m.quilt("push")
        copy = self.m.build_dir / ".arcium" / "patches" / CORE_PATCH
        copy.write_text(copy.read_text().replace("+int g();", "+int g(); // edited"))
        self.m.he("push")
        result = self.m.he("check", check=False)
        self.assertIn(f"{CORE_PATCH} was applied outside he", result.stdout)

    def test_pull_stops_when_lane_edits_conflict(self) -> None:
        self.m.ready()
        self.m.he("pop", OUTER_PATCH)
        (self.m.src / "a.cc").write_text('#include "h.h"\nint a() { return 9; }\n')
        self.m.quilt("refresh")
        self.m.write_patch(OUTER_PATCH, core=False, files={"a.cc": '#include "h.h"\nint a() { return 7; }\n'})
        lane = (self.m.build_dir / ".arcium" / "patches" / OUTER_PATCH).read_text()
        result = self.m.he("pull", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since he merge", result.stderr)
        self.assertEqual((self.m.build_dir / ".arcium" / "patches" / OUTER_PATCH).read_text(), lane)

    def test_retried_unmerge_does_not_duplicate_new_patches(self) -> None:
        self.m.he("merge")
        self.m.he("push")
        self.m.quilt("new", "personal/new.patch")
        self.m.quilt("add", "b.cc")
        (self.m.src / "b.cc").write_text("int b() { return 3; }\n")
        self.m.quilt("refresh")
        self.m.he("unmerge")  # patches applied: exports and keeps the catalog
        manifest = self.m.build_dir / ".arcium" / "patches" / "manifest.json"
        data = json.loads(manifest.read_text())
        data["owners"].pop("personal/new.patch")
        manifest.write_text(json.dumps(data))  # as if the manifest write had failed
        self.m.he("pop")
        self.m.he("unmerge")
        series = (self.m.worktree / "patches" / "series").read_text().split()
        self.assertEqual(series.count("personal/new.patch"), 1)

    def test_dev_env_keys_cannot_inject_commands(self) -> None:
        config = self.m.home / ".config" / "arcium"
        config.mkdir(parents=True)
        marker = self.m.root / "injected"
        (config / "dev.env").write_text(f"HELIUM_X:-$(touch {marker})=1\nHELIUM_OK=$(touch {marker})\n")
        env = self.m.env()
        result = run(["bash", "-c", f'source "{TOOLS / "dev.sh"}" >/dev/null && printf %s "$HELIUM_OK"'], env=env)
        self.assertFalse(marker.exists())
        self.assertEqual(result.stdout, f"$(touch {marker})")

    def test_terminating_he_stops_the_locked_command(self) -> None:
        self.m.he("merge")
        child_pid = self.m.root / "child.pid"
        lock = subprocess.Popen(
            ["python3", "-m", "he", "--worktree", str(self.m.worktree), "--build-dir", str(self.m.build_dir),
             "lock", "--label", "test", "--", "bash", "-c", f"echo $$ > {child_pid}; sleep 30"],
            env={**self.m.env(), "PYTHONPATH": str(TOOLS / "devutils")},
        )
        for _ in range(100):
            if child_pid.exists() and child_pid.read_text().strip():
                break
            import time; time.sleep(0.05)
        pid = int(child_pid.read_text())
        lock.terminate()
        lock.wait(timeout=10)
        with self.assertRaises(ProcessLookupError):
            for _ in range(50):
                os.kill(pid, 0)
                import time; time.sleep(0.1)
        handle = (self.m.build_dir / ".arcium" / "lane.lock").open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.close()

if __name__ == "__main__":
    unittest.main()
