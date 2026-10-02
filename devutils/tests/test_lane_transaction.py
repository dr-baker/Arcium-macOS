"""Tests for complete generated-lane shell transactions."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devutils.tests.test_build_receipt import material_fixture
from lane_transaction import workflow_environment  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "devutils" / "lane_transaction.py"


class LaneTransactionTests(unittest.TestCase):
    def _fixture_environment(self, root: Path) -> dict[str, str]:
        material_fixture(root)
        tools = root / "fake-tools"
        tools.mkdir()
        diskutil = tools / "diskutil"
        metadata = plistlib.dumps({
            "MountPoint": str(root.resolve()),
            "VolumeUUID": "fixture-volume",
            "FilesystemType": "apfs",
            "FilesystemName": "Case-sensitive APFS",
            "WritableVolume": True,
            "Internal": False,
            "GlobalPermissionsEnabled": True,
        }).decode("utf-8")
        diskutil.write_text("#!/bin/sh\ncat <<'PLIST'\n" + metadata + "PLIST\n", encoding="utf-8")
        diskutil.chmod(0o700)
        return {**os.environ, "PATH": str(tools) + ":/usr/bin:/bin:/usr/sbin:/sbin"}

    def test_environment_defers_temp_creation_to_the_verified_locked_region(self) -> None:
        environment = workflow_environment(
            {"TMPDIR": "/internal/temp"},
            build_root=Path("/Volumes/T9/ArciumBuild/build"),
            lane="heavy",
            worktree=Path("/worktree"),
        )
        self.assertEqual(
            environment["TMPDIR"],
            "/internal/temp",
        )

    def test_heavy_transaction_creates_short_temp_only_while_locked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ac-", dir="/private/tmp") as temporary:
            root = Path(temporary).resolve()
            environment = self._fixture_environment(root)
            observed = root / "observed-temp"
            script = root / "dev.sh"
            script.write_text(
                "___helium_configure_inner(){ python3 -c 'import fcntl,json,os; "
                "from pathlib import Path; p=Path(os.environ[\"TMPDIR\"]); "
                "assert p.is_dir() and p.stat().st_mode & 0o777 == 0o700; "
                "lock=Path(os.environ[\"HELIUM_DEV_BUILD_ROOT\"])/\".arcium/lane.lock\"; "
                "assert json.loads(lock.read_text())[\"action\"] == \"configure\"; "
                "assert os.environ[\"HELIUM_DEV_MATERIAL_INPUTS_AT_ENTRY\"]; "
                "fd=int(os.environ[\"HELIUM_DEV_LANE_LOCK_FD\"]); "
                "assert os.fstat(fd).st_ino==lock.stat().st_ino; "
                "Path(os.environ[\"OBSERVED_TEMP\"]).write_text(str(p))'; return 7; }\n",
                encoding="utf-8",
            )
            environment["OBSERVED_TEMP"] = str(observed)
            build_root = root / ("long-build-lane-" * 10)
            result = subprocess.run(
                [sys.executable, str(CLI), "--worktree", str(root), "--build-root", str(build_root),
                 "--lane", "heavy", "--expected-volume-uuid", "fixture-volume", "--script", str(script), "configure"],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            selected = Path(observed.read_text(encoding="utf-8"))
            self.assertEqual(selected.parent.parent, root)
            self.assertLess(len(os.fsencode(str(selected) + "/sccacheXXXXXX/sock")), 104)
            self.assertFalse((build_root / ".arcium/tmp").exists())

    def test_heavy_transaction_rejects_lexical_symlink_before_lock_creation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ac-", dir="/private/tmp") as temporary:
            root = Path(temporary).resolve()
            environment = self._fixture_environment(root)
            target = root / "target"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            script = root / "dev.sh"
            script.write_text("___helium_configure_inner(){ echo unexpected-producer; }\n")
            result = subprocess.run(
                [sys.executable, str(CLI), "--worktree", str(root), "--build-root", str(alias / "build"),
                 "--lane", "heavy", "--expected-volume-uuid", "fixture-volume", "--script", str(script), "configure"],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse((target / "build").exists())
            self.assertFalse((root / f".arcium-tmp-{os.geteuid()}").exists())

    def test_heavy_transaction_passes_validated_cli_pin_to_the_real_sourced_shell(self) -> None:
        for ambient in (None, "stale-ambient-volume"):
            with self.subTest(ambient=ambient), tempfile.TemporaryDirectory(prefix="ac-", dir="/private/tmp") as temporary:
                root = Path(temporary).resolve()
                environment = self._fixture_environment(root)
                environment.pop("HELIUM_DEV_HEAVY_VOLUME_UUID", None)
                if ambient is not None:
                    environment["HELIUM_DEV_HEAVY_VOLUME_UUID"] = ambient
                (root / "fake-tools/python3").symlink_to(sys.executable)
                for helper in ("setup_python.sh", "helium_acquisition.sh"):
                    (root / "devutils" / helper).write_bytes((ROOT / "devutils" / helper).read_bytes())
                observed = root / "observed-pin.json"
                environment["OBSERVED_PIN"] = str(observed)
                script = root / "dev.sh"
                script.write_text(
                    (ROOT / "dev.sh").read_text()
                    + "\n___helium_configure_inner(){ ___helium_python -c 'import json,os,sys; "
                    "from pathlib import Path; Path(os.environ[\"OBSERVED_PIN\"]).write_text("
                    "json.dumps([os.environ[\"HELIUM_DEV_HEAVY_VOLUME_UUID\"],sys.argv[1]]))' "
                    '"$_heavy_volume_uuid"; }\n',
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, str(CLI), "--worktree", str(root), "--build-root", str(root / "build"),
                     "--lane", "heavy", "--expected-volume-uuid", "fixture-volume", "--script", str(script), "configure"],
                    env=environment, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(observed.read_text()), ["fixture-volume", "fixture-volume"])

    def test_transaction_holds_lock_and_propagates_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self._fixture_environment(root)
            script = root / "dev.sh"
            script.write_text(
                "___helium_configure_inner() { "
                "python3 -c 'import json,os; "
                "fd=int(os.environ[\"HELIUM_DEV_LANE_LOCK_FD\"]); "
                "p=os.environ[\"HELIUM_DEV_BUILD_ROOT\"]+\"/.arcium/lane.lock\"; "
                "a=os.fstat(fd); b=os.stat(p); assert (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino); "
                "d=json.load(open(p)); assert d[\"action\"] == \"configure\"'; "
                "return 7; }\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(CLI),
                    "--worktree",
                    str(root),
                    "--build-root",
                    str(root / "build"),
                    "--lane",
                    "worktree",
                    "--script",
                    str(script),
                    "configure",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            payload = json.loads(
                (root / "build" / ".arcium" / "lane.lock").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["action"], "configure")

    def test_heavy_preflight_does_not_create_lane_on_wrong_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self._fixture_environment(root)
            script = root / "dev.sh"
            script.write_text("___helium_configure_inner() { return 0; }\n", encoding="utf-8")
            build_root = root / "missing-t9" / "build"
            result = subprocess.run(
                [
                    "python3",
                    str(CLI),
                    "--worktree",
                    str(root),
                    "--build-root",
                    str(build_root),
                    "--lane",
                    "heavy",
                    "--expected-volume-uuid",
                    "not-this-volume",
                    "--script",
                    str(script),
                    "configure",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(build_root.exists())

    def test_worktree_lane_preserves_callers_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self._fixture_environment(root)
            script = root / "dev.sh"
            observed = root / "observed-temp"
            script.write_text(
                f'___helium_configure_inner() {{ printf "%s" "$TMPDIR" > {observed}; }}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(CLI),
                    "--worktree",
                    str(root),
                    "--build-root",
                    str(root / "build"),
                    "--lane",
                    "worktree",
                    "--script",
                    str(script),
                    "configure",
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **environment,
                    "TMPDIR": str(root / "callers-temp"),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(observed.read_text(encoding="utf-8"), str(root / "callers-temp"))


if __name__ == "__main__":
    unittest.main()
