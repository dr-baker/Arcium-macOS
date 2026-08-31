"""A safe executable fixture for the launch, manifest, and scoped-stop path."""

from __future__ import annotations

import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import helium_dev  # noqa: E402


class HeliumDevLiveFixtureTests(unittest.TestCase):
    def test_run_discovers_unquoted_ps_then_scoped_stop(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("C compiler unavailable for executable fixture")
        with tempfile.TemporaryDirectory(prefix="helium dev fixture ") as temporary:
            root = Path(temporary)
            source = root / "build" / "src"
            app = source / "out" / "Default" / "Helium Dev.app"
            executable = app / "Contents" / "MacOS" / "Helium"
            executable.parent.mkdir(parents=True)
            with (app / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump(
                    {"CFBundleExecutable": "Helium", "CFBundleIdentifier": "local.test.helium"},
                    handle,
                )
            subprocess.run(
                [compiler, "-x", "c", "-", "-o", str(executable)],
                input="#include <unistd.h>\nint main(void) { for (;;) sleep(1); }\n",
                text=True,
                check=True,
                capture_output=True,
            )
            (source / "out" / "Default" / "libchrome_dll.dylib").write_bytes(b"fixture")
            home, registry = root / "home", root / "registry"
            pid: int | None = None
            try:
                with patch("helium_dev.require_current_packaged_build"):
                    launched = helium_dev.runtime_action(
                        "run",
                        str(root),
                        ["--isolated", "live-fixture"],
                        home=home,
                        registry_root=registry,
                    )
                pid = launched["main_pid"]
                self.assertTrue(launched["ok"])
                self.assertIsInstance(pid, int)
                self.assertEqual(launched["process_count"], 1)
                self.assertTrue(Path(str(launched["manifest_path"])).is_file())

                stopped = helium_dev.runtime_action(
                    "stop",
                    str(root),
                    ["--isolated", "live-fixture"],
                    home=home,
                    registry_root=registry,
                )
                self.assertTrue(stopped["ok"])
                self.assertEqual(stopped["process_count"], 0)
            finally:
                if isinstance(pid, int):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
