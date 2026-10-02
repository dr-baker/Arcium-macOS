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
            "Internal": True,
        }).decode("utf-8")
        diskutil.write_text("#!/bin/sh\ncat <<'PLIST'\n" + metadata + "PLIST\n", encoding="utf-8")
        diskutil.chmod(0o700)
        return {**os.environ, "PATH": str(tools) + ":/usr/bin:/bin:/usr/sbin:/sbin"}

    def test_heavy_lane_routes_temporary_traffic_to_build_volume(self) -> None:
        environment = workflow_environment(
            {"TMPDIR": "/internal/temp"},
            build_root=Path("/Volumes/T9/ArciumBuild/build"),
            lane="heavy",
            worktree=Path("/worktree"),
        )
        self.assertEqual(
            environment["TMPDIR"],
            "/Volumes/T9/ArciumBuild/build/.arcium/tmp",
        )

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
