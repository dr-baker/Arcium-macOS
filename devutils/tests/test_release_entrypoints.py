#!/usr/bin/env python3

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "build.sh"
CI_RESOURCE_SCRIPT = ROOT / ".github/scripts/github_fetch_resources.sh"
SANITY_SCRIPT = ROOT / ".github/scripts/sanity-check.sh"
PATCH_UTILITY = ROOT / "helium-chromium/utils/patches.py"


class ReleaseEntrypointsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.patch_invocation_log = self.root / "patch-invocation.txt"

    def write_executable(self, path: Path, contents: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)

    def entrypoint_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.bin_dir}:{environment['PATH']}"
        environment["PATCH_INVOCATION_LOG"] = str(self.patch_invocation_log)
        return environment

    def install_python_stub(self) -> None:
        self.write_executable(
            self.bin_dir / "python3",
            "#!/bin/bash\n"
            "if [[ \"$1\" == */utils/patches.py && \"$2\" == apply ]]; then\n"
            "  printf '%s\\n' \"$@\" > \"$PATCH_INVOCATION_LOG\"\n"
            "  exit 97\n"
            "fi\n"
            "exit 0\n",
        )

    def assert_patch_entrypoint_is_strict(self) -> None:
        arguments = self.patch_invocation_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual("apply", arguments[1])
        self.assertEqual("--no-fuzz", arguments[2])

    def test_sanity_check_build_exit_statuses_and_setup(self) -> None:
        src_dir = self.root / "source"
        (self.root / "dev.sh").write_text(
            f"_root_dir={str(ROOT)!r}\n"
            f"HELIUM_DEV_BUILD_ROOT={str(self.root / 'build')!r}\n"
            f"_src_dir={str(src_dir)!r}\n"
            f"_out_dir={str(src_dir / 'out/Default')!r}\n"
            "mkdir -p \"$_src_dir\"\n"
            "he() {\n"
            "  printf '%s\\n' \"$*\" >> \"$HE_CALLS\"\n"
            "  case \"$1\" in\n"
            "    setup) [ \"$2\" = --force ] || return 2\n"
            "      printf '%s\\n' \"${SETUP_OUTPUT:-source prepared}\"\n"
            "      return \"${SETUP_STATUS:-0}\" ;;\n"
            "    reset) return 2 ;;\n"
            "    *) return 2 ;;\n"
            "  esac\n"
            "}\n",
            encoding="utf-8",
        )
        calls = self.root / "he-calls.txt"
        self.write_executable(self.bin_dir / "sudo", "#!/bin/bash\nexit 0\n")
        self.write_executable(self.bin_dir / "brew", "#!/bin/bash\nexit 0\n")
        self.write_executable(self.bin_dir / "pip3.14", "#!/bin/bash\nexit 0\n")
        self.write_executable(
            self.bin_dir / "timeout",
            '#!/bin/bash\necho smoke >> "$HE_CALLS"\n'
            f'{sys.executable!r} - <<\'PY\'\n'
            'from datetime import datetime, timezone\n'
            'import json, os\n'
            'from pathlib import Path\n'
            'path = Path("build/.arcium/build-evidence/smoke/manifest.json")\n'
            'path.parent.mkdir(parents=True, exist_ok=True)\n'
            'now = datetime.now(timezone.utc).isoformat()\n'
            'status = int(os.environ["SMOKE_STATUS"])\n'
            'path.write_text(json.dumps({"started_at": now, "finished_at": now,\n'
            '    "returncode": 143 if status == 124 else status,\n'
            '    "phases": [{"name": "build", "attributes": {"child_started_offset_nanos": 0}}]}))\n'
            'PY\nexit "$SMOKE_STATUS"\n',
        )

        environment = self.entrypoint_environment()
        environment["HE_CALLS"] = str(calls)
        cases = [(status, 0, "source prepared", expected)
                 for status, expected in ((0, 0), (124, 0), (1, 1), (125, 1), (127, 1), (137, 1))]
        offset = "Hunk #1 succeeded at 20 (offset 5 lines)."
        cases.extend(((0, 0, offset, 0), (0, 1, "patch failed", 1),
                      (0, 2, offset, 2)))
        for status, setup_status, output, expected in cases:
            with self.subTest(status=status, setup_status=setup_status, output=output):
                calls.unlink(missing_ok=True)
                result = subprocess.run(
                    [str(SANITY_SCRIPT)],
                    cwd=self.root,
                    env={**environment, "SMOKE_STATUS": str(status),
                         "SETUP_STATUS": str(setup_status), "SETUP_OUTPUT": output},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )

                self.assertEqual(expected, result.returncode, result.stdout)
                expected_calls = "setup --force\n" + ("" if setup_status else "smoke\n")
                self.assertEqual(expected_calls, calls.read_text(encoding="utf-8"))
                if expected and not setup_status:
                    self.assertIn(f"failed with status code {status}", result.stdout)

    def test_local_build_passes_no_fuzz_to_patch_utility(self) -> None:
        self.install_python_stub()
        (self.root / "helium-chromium/utils").mkdir(parents=True)
        (self.root / "helium-chromium/pruning.list").touch()
        (self.root / "helium-chromium/flags.gn").touch()
        (self.root / "flags.macos.gn").touch()
        self.write_executable(
            self.root / "retrieve_and_unpack_resource.sh",
            "#!/bin/bash\nexit 0\n",
        )
        self.write_executable(
            self.root / "devutils/setup_dawn_go.sh",
            "#!/bin/bash\nexit 0\n",
        )
        self.write_executable(
            self.bin_dir / "greadlink",
            "#!/bin/bash\n[ \"$1\" = -f ] || exit 2\nprintf '%s\\n' \"$2\"\n",
        )
        (self.root / "env.sh").write_text(
            f"_src_dir={str(self.root / 'build/src')!r}\n"
            f"_download_cache={str(self.root / 'build/download_cache')!r}\n"
            f"_main_repo={str(self.root / 'helium-chromium')!r}\n"
            f"_depot_tools_dir={str(self.root / 'build/depot_tools')!r}\n"
            "___helium_setup_python() { :; }\n",
            encoding="utf-8",
        )
        shutil.copy2(BUILD_SCRIPT, self.root / "build.sh")

        result = subprocess.run(
            [str(self.root / "build.sh")],
            cwd=self.root,
            env=self.entrypoint_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(97, result.returncode, result.stdout)
        self.assert_patch_entrypoint_is_strict()

    def test_ci_resource_fetch_passes_no_fuzz_to_patch_utility(self) -> None:
        self.install_python_stub()
        script_root = self.root / ".github/scripts"
        script_root.mkdir(parents=True)
        shutil.copy2(CI_RESOURCE_SCRIPT, script_root / "github_fetch_resources.sh")
        (script_root / "helium-chromium/utils").mkdir(parents=True)
        (script_root / "helium-chromium/pruning.list").touch()
        self.write_executable(
            self.bin_dir / "greadlink",
            "#!/bin/bash\n[ \"$1\" = -f ] || exit 2\nprintf '%s\\n' \"$2\"\n",
        )
        self.write_executable(self.bin_dir / "sudo", "#!/bin/bash\nexit 0\n")
        self.write_executable(
            script_root / "retrieve_and_unpack_resource.sh",
            "#!/bin/bash\nexit 0\n",
        )
        self.write_executable(
            script_root / "devutils/setup_dawn_go.sh",
            "#!/bin/bash\nexit 0\n",
        )

        result = subprocess.run(
            [str(script_root / "github_fetch_resources.sh"), "arm64"],
            cwd=self.root,
            env=self.entrypoint_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(97, result.returncode, result.stdout)
        self.assert_patch_entrypoint_is_strict()

    def test_patch_utility_turns_no_fuzz_into_strict_patch_option(self) -> None:
        fake_patch_log = self.root / "fake-patch-arguments.txt"
        self.write_executable(
            self.bin_dir / "patch",
            "#!/bin/bash\n"
            "if [[ \"$1\" == --version ]]; then\n"
            "  echo 'GNU patch test stub'\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' \"$@\" > \"$FAKE_PATCH_LOG\"\n",
        )
        target = self.root / "source"
        target.mkdir()
        patch_dir = self.root / "patches"
        patch_dir.mkdir()
        (patch_dir / "series").write_text("fixture.patch\n", encoding="utf-8")
        (patch_dir / "fixture.patch").write_text("", encoding="utf-8")
        environment = self.entrypoint_environment()
        environment["FAKE_PATCH_LOG"] = str(fake_patch_log)
        environment.pop("PATCH_BIN", None)

        result = subprocess.run(
            [
                sys.executable,
                str(PATCH_UTILITY),
                "apply",
                "--no-fuzz",
                str(target),
                str(patch_dir),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stdout)
        patch_arguments = fake_patch_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("--fuzz=0", patch_arguments)


if __name__ == "__main__":
    unittest.main()
