"""Tests for complete generated-lane shell transactions."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "devutils" / "lane_transaction.py"


class LaneTransactionTests(unittest.TestCase):
    def test_transaction_holds_lock_and_propagates_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(build_root.exists())


if __name__ == "__main__":
    unittest.main()
