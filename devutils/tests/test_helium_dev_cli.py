"""Black-box command-output tests that never launch a browser."""

from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


WORKTREE = Path(__file__).resolve().parents[2]
CLI = WORKTREE / "devutils" / "helium_dev.py"
sys.path.insert(0, str(WORKTREE / "devutils"))
import helium_dev  # noqa: E402


class HeliumDevCliTests(unittest.TestCase):
    def test_json_error_never_contaminates_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    temporary,
                    "run",
                    "--json",
                    "--user-data-dir=/release-profile",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        document = json.loads(result.stdout)
        self.assertFalse(document["ok"])
        self.assertEqual(document["action"], "run")
        self.assertIn("user-data-dir", result.stderr)

    def test_build_full_cannot_bypass_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    temporary,
                    "build-full",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        document = json.loads(result.stdout)
        self.assertFalse(document["ok"])
        self.assertIn("requires explicit approved=True", result.stdout)

    def test_lock_contention_and_bad_build_argument_keep_json_stdout_clean(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("helium_dev.runtime_action", side_effect=helium_dev.LockBusyError("busy")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = helium_dev.main(["--root", "/unused", "status", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "busy")
        self.assertIn("busy", stderr.getvalue())

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = helium_dev.main(
                ["--root", "/unused", "build-plan", "--json", "--edge-budget", "not-a-number", "obj/a.o"]
            )
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])
        self.assertIn("invalid int value", stderr.getvalue())

    def test_ambiguous_runtime_status_is_not_reported_as_ok(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = root / "libchrome_dll.dylib"
            component.write_bytes(b"component")
            executable = root / "Helium Dev.app" / "Contents" / "MacOS" / "Helium"
            executable.parent.mkdir(parents=True)
            executable.write_text("fixture", encoding="utf-8")
            paths = helium_dev.WorktreePaths(
                root,
                root,
                root,
                root / "Helium Dev.app",
                executable,
                "local.test.helium",
                component,
                root / "siso",
                root / "autoninja.py",
            )
            profile = helium_dev.resolve_profile("isolated", "ambiguous", home=root / "home")
            ps_text = "\n".join(
                (
                    f"101 {executable} --user-data-dir={profile.user_data_dir}",
                    f"102 {executable} --user-data-dir={profile.user_data_dir}",
                )
            )
            with patch("helium_dev._quilt_top", return_value=(None, [])):
                manifest = helium_dev._manifest_for(
                    paths=paths,
                    profile=profile,
                    action="status",
                    cohort_text=ps_text,
                    run_id="run",
                    manifest_path=root / "manifest.json",
                )
        self.assertFalse(manifest["ok"])
        self.assertIsNone(manifest["main_pid"])


if __name__ == "__main__":
    unittest.main()
