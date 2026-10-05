"""Exercise lane persistence and actual Bash/zsh sourcing in disposable repos."""
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from devutils import lane_selection
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "devutils"))
from devutils.lane_transaction import workflow_environment
UUID = "DAD732B3-4B10-4036-B0D7-0BE7D10F55CA"


class LaneSelectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        shutil.copy(ROOT / "dev.sh", self.root / "dev.sh")
        (self.root / "devutils").symlink_to(ROOT / "devutils", target_is_directory=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("HELIUM_DEV_")}
        self.env["HELIUM_DEV_HEAVY_ROOT"] = str(self.root / "no-heavy-lane")

    def shell(self, shell, script):
        return subprocess.run([shell, "-c", script], env=self.env, cwd=self.root, text=True, capture_output=True, check=True).stdout.strip()

    def test_selection_is_shared_but_worktree_build_roots_stay_separate(self):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
        other = self.root.parent / "source-worktree"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", "--detach", str(other)], check=True)
        lane_selection.save(self.root, {"version": 1, "lane": "local"})
        self.assertEqual(lane_selection.selection_path(self.root), lane_selection.selection_path(other))
        self.assertEqual(lane_selection.resolve(self.root, self.env)["root"], lane_selection.resolve(other, self.env)["root"])
        lane_selection.save(self.root, {"version": 1, "lane": "worktree"})
        self.assertEqual(Path(lane_selection.resolve(other, self.env)["root"]).resolve(), other.resolve() / "build")

    def test_saved_unavailable_heavy_stays_selected(self):
        missing = self.root / "unmounted-external/full"
        lane_selection.save(self.root, {"version": 1, "lane": "heavy", "root": str(missing), "source_mode": "full", "volume_uuid": UUID})
        resolved = lane_selection.resolve(self.root, self.env)
        self.assertEqual(resolved["root"], str(missing))
        self.assertEqual(resolved["lane"], "heavy")
        self.assertEqual(resolved["source_mode"], "full")
        self.assertFalse(missing.exists())
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                output = self.shell(shell, 'source dev.sh; printf "%s|%s|%s" "$HELIUM_DEV_LANE" "$HELIUM_DEV_BUILD_ROOT" "$HELIUM_DEV_SOURCE_MODE"')
                self.assertEqual(output, f"heavy|{missing}|full")

    def test_resourcing_clears_owned_values_preserves_independent_override(self):
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                output = self.shell(shell, '''
python3 devutils/lane_selection.py --worktree "$PWD" select heavy --root "$PWD/missing" --expected-volume-uuid DAD732B3-4B10-4036-B0D7-0BE7D10F55CA --source-mode full
source dev.sh
python3 devutils/lane_selection.py --worktree "$PWD" select local --source-mode lite
source dev.sh
printf '%s|%s|%s\\n' "$HELIUM_DEV_LANE" "$HELIUM_DEV_SOURCE_MODE" "$HELIUM_DEV_HEAVY_VOLUME_UUID"
export HELIUM_DEV_SOURCE_MODE=full
source dev.sh
printf '%s|%s' "$HELIUM_DEV_LANE" "$HELIUM_DEV_SOURCE_MODE"
''')
                self.assertEqual(output, f"local|lite|{lane_selection.DEFAULT_UUID}\nlocal|full")

    def test_explicit_override_survives_repeated_source(self):
        self.env.update(HELIUM_DEV_LANE="worktree", HELIUM_DEV_SOURCE_MODE="full")
        for shell in ("bash", "zsh"):
            output = self.shell(shell, 'source dev.sh; source dev.sh; printf "%s|%s|%s" "$HELIUM_DEV_LANE" "$HELIUM_DEV_SOURCE_MODE" "$HELIUM_DEV_LANE_SELECTION_ORIGIN"')
            self.assertEqual(output, "worktree|full|environment")

    def test_public_selection_commands_report_saved_and_environment_origins(self):
        tools = self.root / "tools"
        tools.mkdir()
        diskutil = tools / "diskutil"
        diskutil.write_text("#!/usr/bin/env python3\nimport plistlib,sys\n" +
            "sys.stdout.buffer.write(plistlib.dumps(" + repr({
                "MountPoint": str(self.root), "VolumeUUID": UUID,
                "FilesystemType": "apfs", "FilesystemName": "Case-sensitive APFS",
                "WritableVolume": True, "Internal": False,
            }) + "))\n")
        diskutil.chmod(0o755)
        hdiutil = tools / "hdiutil"
        hdiutil.write_text("#!/usr/bin/env python3\nimport plistlib,sys\nsys.stdout.buffer.write(plistlib.dumps({'images':[]}))\n")
        hdiutil.chmod(0o755)
        self.env["PATH"] = str(tools) + os.pathsep + self.env["PATH"]
        for shell in ("bash", "zsh"):
            output = self.shell(shell, 'source dev.sh; he lane select worktree --source-mode full >/dev/null; he lane show --json')
            document = json.loads(output)
            self.assertEqual(document["selection"]["origin"], "saved")
            self.assertEqual(document["lane"], "worktree")
            self.assertEqual(document["selection"]["config_path"], str(lane_selection.selection_path(self.root)))
        self.env.update(HELIUM_DEV_LANE="local")
        result = subprocess.run(["zsh", "-c", 'source dev.sh; he lane select worktree >/dev/null; he lane show --json'], cwd=self.root, env=self.env, text=True, capture_output=True, check=True)
        self.assertIn("explicit environment overrides are still active", result.stderr)
        self.assertEqual(json.loads(result.stdout)["selection"]["origin"], "environment")

    def test_transaction_child_keeps_locked_lane_when_saved_choice_changes(self):
        lane_selection.save(self.root, {"version": 1, "lane": "heavy", "root": str(self.root / "other"), "source_mode": "full", "volume_uuid": UUID})
        previous = {**self.env,
            "HELIUM_DEV_LANE": "local", "HELIUM_DEV_BUILD_ROOT": str(self.root / "build"),
            "HELIUM_DEV_SOURCE_MODE": "lite",
            "HELIUM_DEV_MANAGED_VARIABLES": "LANE BUILD_ROOT SOURCE_MODE HEAVY_VOLUME_UUID",
            "HELIUM_DEV_RESOLVED_LANE": "local", "HELIUM_DEV_RESOLVED_BUILD_ROOT": str(self.root / "build"),
            "HELIUM_DEV_RESOLVED_SOURCE_MODE": "lite",
        }
        self.env = workflow_environment(previous, build_root=self.root / "build", lane="local", worktree=self.root)
        for shell in ("bash", "zsh"):
            output = self.shell(shell, 'source dev.sh; printf "%s|%s|%s" "$HELIUM_DEV_LANE" "$HELIUM_DEV_BUILD_ROOT" "$HELIUM_DEV_SOURCE_MODE"')
            self.assertEqual(output, f"local|{self.root}/build|lite")

    def test_presetup_records_resolved_mode_in_shell_then_resource_reads_new_selection(self):
        for shell in ("bash", "zsh"):
            for resolved_mode in ("lite", "full"):
                with self.subTest(shell=shell, resolved_mode=resolved_mode):
                    self.env["FIXTURE_RESOLVED_MODE"] = resolved_mode
                    output = self.shell(shell, """
python3 devutils/lane_selection.py --worktree "$PWD" clear
source dev.sh || exit $?
___helium_lane_preflight(){ :; }
___helium_resources_inner(){ :; }
___helium_setup_gn(){ :; }
___helium_version_inner(){ :; }
___helium_acquire_inner(){
    _source_mode="$FIXTURE_RESOLVED_MODE"
    export HELIUM_DEV_SOURCE_MODE="$_source_mode"
}
___helium_setup_presetup_inner || exit $?
printf '%s|%s|%s\\n' "$_source_mode" "$HELIUM_DEV_SOURCE_MODE" "$HELIUM_DEV_RESOLVED_SOURCE_MODE"
python3 devutils/lane_selection.py --worktree "$PWD" select worktree --root "$PWD/next" --source-mode lite
source dev.sh || exit $?
printf '%s|%s' "$HELIUM_DEV_SOURCE_MODE" "$HELIUM_DEV_LANE_SELECTION_ORIGIN"
""")
                    self.assertEqual(output, f"{resolved_mode}|{resolved_mode}|{resolved_mode}\nlite|saved")

    def test_failed_resource_disables_cached_commands_until_recovery(self):
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                output = self.shell(shell, """
source dev.sh || exit $?
___helium_compile(){ printf 'compile-ran\\n'; }
python3 -c 'from pathlib import Path; import sys; sys.path.insert(0,"devutils"); import lane_selection; path=lane_selection.selection_path(Path.cwd()); path.parent.mkdir(exist_ok=True); path.write_text("{broken")'
source dev.sh >/dev/null 2>&1
printf 'source-status=%s\\n' "$?"
he compile inert-target >/dev/null 2>&1
printf 'compile-status=%s\\n' "$?"
python3 devutils/lane_selection.py --worktree "$PWD" clear
source dev.sh || exit $?
___helium_compile(){ printf 'compile-ran\\n'; }
he compile inert-target
""")
                self.assertEqual(output, "source-status=2\ncompile-status=2\ncompile-ran")
                self.assertFalse((self.root / "build").exists())

    def test_invalid_config_can_be_cleared_without_sourcing(self):
        path = lane_selection.selection_path(self.root)
        path.parent.mkdir()
        path.write_text('{"version":1,"lane":"unexpected"}')
        result = subprocess.run(["zsh", "-c", "source dev.sh"], env=self.env, cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        subprocess.run(["python3", "devutils/lane_selection.py", "--worktree", str(self.root), "clear"], cwd=self.root, check=True)
        self.assertIsNone(lane_selection.load(self.root))


if __name__ == "__main__":
    unittest.main()
