"""Disposable shell, preparation, and executor fixtures for backend switching."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_backend as backend  # noqa: E402
import build_preparation as preparation  # noqa: E402
import helium_dev  # noqa: E402
from build_lane import acquire_lane_lock  # noqa: E402
from build_receipt import ReceiptError, material_inputs_sha256  # noqa: E402
from devutils.tests.test_dev_sh_commands import ShellFixture, run_zsh  # noqa: E402


def write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def backend_fixture(fixture: ShellFixture) -> None:
    fixture.material_inputs()
    source = fixture.build_root / "src"
    write(fixture.worktree / "helium-chromium/flags.gn", "is_official_build = true\n")
    write(fixture.worktree / "flags.macos.gn", "symbol_level = 1\n")
    write(fixture.python_env / "bin/sccache", "#!/bin/sh\nexit 0\n", executable=True)
    write(fixture.build_root / ".arcium/source-mode", "lite\n")
    write(fixture.build_root / ".arcium/acquisition-target", platform.machine() + "\n")
    write(source / "out/Default/gn", "fixture gn\n")
    write(source / "chrome/VERSION", "MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=71\n")
    siso = source / "build/config/siso"
    write(siso / "backend_config/google.star", "# fixture Google backend\n")
    write(siso / "backend_config/nativelink.star", "# fixture NativeLink backend\n")
    # These producers stand in for pinned upstream tools. They accept their
    # actual argv and write their actual output paths, without downloads.
    write(siso / "configure_siso.py", '''import argparse
from pathlib import Path
import shutil
p = argparse.ArgumentParser()
p.add_argument('--rbe_instance')
p.add_argument('--reapi_address')
p.add_argument('--reapi_instance')
p.add_argument('--reapi_backend_config_path')
a = p.parse_args()
root = Path(__file__).parent
if a.reapi_address:
    text = f'SISO_REAPI_INSTANCE={a.reapi_instance}\\nSISO_REAPI_ADDRESS={a.reapi_address}\\n'
    config = a.reapi_backend_config_path
else:
    assert a.rbe_instance == 'projects/rbe-chrome-untrusted/instances/default_instance'
    text = 'SISO_PROJECT=rbe-chrome-untrusted\\nSISO_REAPI_INSTANCE=default_instance\\n'
    config = 'google.star'
(root / '.sisoenv').write_text(text)
shutil.copyfile(root / 'backend_config' / config, root / 'backend_config/backend.star')
''')
    write(source / "tools/clang/scripts/update.py", '''import argparse
import fcntl
import json
import os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--host-os')
p.add_argument('--output-dir', type=Path)
a = p.parse_args()
assert a.host_os == 'linux'
lane = Path(os.environ['HELIUM_DEV_BUILD_ROOT'])
with (lane / '.arcium/lane.lock').open() as competing:
    try:
        fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise RuntimeError('toolchain preparation ran without the lane lock')
(a.output_dir / 'bin').mkdir(parents=True, exist_ok=True)
(a.output_dir / 'bin/clang').write_text('fixture Linux clang\\n')
(a.output_dir / 'cr_build_revision').write_text('fixture pinned revision\\n')
(lane / 'linux-toolchain-invoked').write_text(json.dumps(dict(os.environ)))
''')
    cfg = source / "buildtools/reclient_cfgs/chromium-browser-clang"
    write(cfg / "clang_remote_wrapper", "#!/bin/bash\n# fixture wrapper\n")
    write(cfg / "rewrapper_mac.cfg", "platform=cpu_count=1\n")
    write(source / "third_party/siso/cipd/siso", f"#!{sys.executable}\n" + '''import sys
kind = sys.argv[2]
print({'rule': 'cc', 'inputs': 'obj/fixture.o', 'commands': 'clang obj/fixture.o -o output'}[kind])
''', executable=True)
    write(source / "third_party/depot_tools/autoninja.py", '''import json
import os
from pathlib import Path
import sys
lane = Path(os.environ['HELIUM_DEV_BUILD_ROOT'])
with (lane / 'executor-environments.jsonl').open('a') as out:
    out.write(json.dumps({'argv': sys.argv[1:], 'environment': dict(os.environ)}) + '\\n')
if '-n' in sys.argv:
    (Path(sys.argv[sys.argv.index('-C') + 1]) / 'siso_explain').write_text('fixture graph is current\\n')
print('1 edges')
''')


def prepare_shell(fixture: ShellFixture, environment: dict[str, str], *, refresh_defaults: bool = True) -> None:
    source = fixture.build_root / "src"
    (source / "out/Default").mkdir(parents=True, exist_ok=True)
    lock = fixture.build_root / ".arcium/lane.lock"
    with patch.dict(os.environ, environment, clear=True), acquire_lane_lock(lock, {"action": "fixture"}):
        acquisition = preparation.input_digest(fixture.worktree, fixture.build_root, "acquisition")
        preparation.record_stage(fixture.worktree, fixture.build_root, "acquisition", acquisition)
        result = run_zsh(
            ("___helium_setup_gn || exit $?; " if refresh_defaults else
             "___helium_preparation require gn-defaults || exit $?; ") +
            "entry=\"$(___helium_preparation begin backend)\" || exit $?; "
            "___helium_python \"$_helium_harness_root/devutils/build_backend.py\" "
            "--source-dir \"$_src_dir\" || exit $?; "
            "___helium_preparation finish backend \"$entry\"",
            fixture=fixture,
        )
        if result.returncode:
            raise AssertionError(result.stderr)


class BuildBackendTests(unittest.TestCase):
    def test_shell_preparation_selects_native_then_restores_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            backend_fixture(fixture)
            self.assertFalse((fixture.worktree / "devutils/build_backend.py").exists())
            self.assertFalse(Path(backend.__file__).resolve().is_relative_to(fixture.worktree))
            source = fixture.build_root / "src"
            remote = fixture.environment() | {
                "SISO_REAPI_ADDRESS": "fixture.invalid:50051",
                "SISO_REAPI_CAS_ADDRESS": "unsupported.invalid:50051",
            }
            remote.pop("RBE_service_no_security", None)
            remote.pop("SISO_REAPI_INSTANCE", None)
            prepare_shell(fixture, remote)
            args = (source / "out/Default/args.gn").read_text()
            self.assertIn("use_remoteexec = true", args)
            self.assertNotIn("cc_wrapper", args)
            with patch.dict(os.environ, remote, clear=True):
                receipt = preparation.require_stage(fixture.worktree, fixture.build_root, "backend")
                self.assertEqual(receipt["backend"], backend.selected_backend().identity())
                defaults = preparation.require_stage(fixture.worktree, fixture.build_root, "gn-defaults")
            tool_environment = json.loads((fixture.build_root / "linux-toolchain-invoked").read_text())
            self.assertEqual(tool_environment["SISO_REAPI_INSTANCE"], "main")
            self.assertEqual(tool_environment["RBE_service_no_security"], "false")
            self.assertNotIn("SISO_REAPI_CAS_ADDRESS", tool_environment)
            self.assertEqual(receipt["backend"]["no_security"], "false")
            args_file = source / "out/Default/args.gn"
            args_file.write_text(args.replace("symbol_level = 1", "symbol_level = 2"))
            preserved = args_file.read_bytes()
            changed_remote = remote | {
                "SISO_REAPI_ADDRESS": "changed.invalid:50051", "SISO_REAPI_INSTANCE": "changed",
                "RBE_service_no_security": "true",
            }
            prepare_shell(fixture, changed_remote, refresh_defaults=False)
            self.assertEqual(args_file.read_bytes(), preserved)
            with patch.dict(os.environ, changed_remote, clear=True):
                self.assertEqual(defaults, preparation.require_stage(fixture.worktree, fixture.build_root,
                                                                    "gn-defaults", check_outputs=False))
                changed = preparation.require_stage(fixture.worktree, fixture.build_root, "backend")
                self.assertNotEqual(changed["receipt_id"], receipt["receipt_id"])
                self.assertEqual(changed["backend"]["no_security"], "true")
            changed_tool_environment = json.loads((fixture.build_root / "linux-toolchain-invoked").read_text())
            self.assertEqual(changed_tool_environment["RBE_service_no_security"], "true")
            self.assertNotIn("SISO_REAPI_CAS_ADDRESS", changed_tool_environment)
            marker = fixture.build_root / "linux-toolchain-invoked"
            marker.unlink()
            local = fixture.environment() | {
                "SISO_REAPI_INSTANCE": "old-instance", "RBE_service_no_security": "true",
                "SISO_REAPI_CAS_ADDRESS": "unsupported.invalid:50051",
            }
            local.pop("SISO_REAPI_ADDRESS", None)
            prepare_shell(fixture, local)
            args = (source / "out/Default/args.gn").read_text()
            self.assertIn('cc_wrapper="sccache"', args)
            self.assertNotIn("use_remoteexec", args)
            self.assertEqual((source / "build/config/siso/.sisoenv").read_text(),
                             "SISO_PROJECT=rbe-chrome-untrusted\nSISO_REAPI_INSTANCE=default_instance\n")
            self.assertEqual((source / "build/config/siso/backend_config/backend.star").read_bytes(),
                             (source / "build/config/siso/backend_config/google.star").read_bytes())
            self.assertFalse(marker.exists())
            cleaned = backend.selected_backend(local).environment(local)
            self.assertNotIn("SISO_REAPI_INSTANCE", cleaned)
            self.assertNotIn("RBE_service_no_security", cleaned)
            self.assertNotIn("SISO_REAPI_CAS_ADDRESS", cleaned)
            self.assertFalse((fixture.worktree / "devutils/build_backend.py").exists())
            with patch.dict(os.environ, local, clear=True), patch("helium_dev.ensure_gclient_identity"):
                result = helium_dev.build_action("compile", str(fixture.worktree), ("obj/fixture.o",),
                                                 build_root=fixture.build_root)
                self.assertTrue(result["ok"], result)
            records = [json.loads(line) for line in (fixture.build_root / "executor-environments.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 2)
            for record in records:
                self.assertNotIn("SISO_REAPI_CAS_ADDRESS", record["environment"])
                self.assertNotIn("SISO_REAPI_ADDRESS", record["environment"])
                self.assertNotIn("RBE_service_no_security", record["environment"])

    def test_guarded_actions_share_backend_and_reject_drift_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            backend_fixture(fixture)
            environment = fixture.environment() | {
                "SISO_REAPI_ADDRESS": "fixture.invalid:50051", "SISO_REAPI_INSTANCE": "custom-instance",
                "SISO_PROJECT": "stale-project",
                "SISO_REAPI_CAS_ADDRESS": "unsupported.invalid:50051", "RBE_service_no_security": "false",
            }
            prepare_shell(fixture, environment)
            source = fixture.build_root / "src"
            log = fixture.build_root / "executor-environments.jsonl"
            with patch.dict(os.environ, environment, clear=True), patch(
                "helium_dev.ensure_gclient_identity"
            ), patch("helium_dev.require_current_replay_proof"), patch(
                "build_preparation.require_current_replay_proof", return_value=SimpleNamespace(receipt_id="a" * 64)
            ), patch("helium_dev.record_execution", return_value=SimpleNamespace(
                receipt_id="e" * 64, replay_receipt_id="a" * 64, source_receipt_id="b" * 64,
            )):
                for stage in ("resources", "version", "configured"):
                    if stage == "configured":
                        write(source / "out/Default/build.ninja", "# fixture configured graph\n")
                    preparation.record_stage(fixture.worktree, fixture.build_root, stage,
                                             preparation.input_digest(fixture.worktree, fixture.build_root, stage))
                for action, arguments in (("compile", ("obj/fixture.o",)), ("relink", ()),
                                          ("build-full", ("--approved",))):
                    result = helium_dev.build_action(action, str(fixture.worktree), arguments,
                                                     build_root=fixture.build_root)
                    self.assertTrue(result["ok"], result)
                records = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(len(records), 6)
                for record in records:
                    self.assertEqual(record["environment"]["SISO_REAPI_ADDRESS"], "fixture.invalid:50051")
                    self.assertEqual(record["environment"]["SISO_REAPI_INSTANCE"], "custom-instance")
                    self.assertEqual(record["environment"]["RBE_service_no_security"], "false")
                    self.assertNotIn("SISO_PROJECT", record["environment"])
                    self.assertNotIn("SISO_REAPI_CAS_ADDRESS", record["environment"])
                baseline = material_inputs_sha256(fixture.worktree)
                for change in ({"SISO_REAPI_INSTANCE": "changed-instance"}, {"RBE_service_no_security": "true"}):
                    with patch.dict(os.environ, change):
                        self.assertNotEqual(material_inputs_sha256(fixture.worktree), baseline)
                        for action, arguments in (("compile", ("obj/fixture.o",)), ("relink", ()),
                                                  ("build-full", ("--approved",))):
                            with self.assertRaisesRegex(ReceiptError, "preparation is missing or stale"):
                                helium_dev.build_action(action, str(fixture.worktree), arguments,
                                                         build_root=fixture.build_root)
                with patch.dict(os.environ, {"RBE_service_no_security": "yes"}):
                    with self.assertRaisesRegex(backend.BackendError, "must be true or false"):
                        helium_dev.build_action("compile", str(fixture.worktree), ("obj/fixture.o",),
                                                 build_root=fixture.build_root)
                (source / "build/config/siso/.sisoenv").write_text("SISO_REAPI_INSTANCE=drift\n")
                with self.assertRaisesRegex(ReceiptError, "backend preparation"):
                    helium_dev.build_action("compile", str(fixture.worktree), ("obj/fixture.o",),
                                             build_root=fixture.build_root)
                self.assertEqual(len(log.read_text().splitlines()), 6)

    def test_missing_core_backend_cannot_clobber_siso_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            backend_fixture(fixture)
            source = fixture.build_root / "src"
            write(source / "out/Default/args.gn", "use_remoteexec = true\n")
            write(source / "build/config/siso/.sisoenv", "prior config\n")
            write(source / "build/config/siso/backend_config/backend.star", "prior backend\n")
            (source / "build/config/siso/backend_config/nativelink.star").unlink()
            with patch.dict(os.environ, {"SISO_REAPI_ADDRESS": "fixture.invalid:50051"}):
                with self.assertRaisesRegex(backend.BackendError, "backend-config prerequisite"):
                    backend.prepare_backend(source, backend.selected_backend())
            self.assertEqual((source / "build/config/siso/.sisoenv").read_text(), "prior config\n")
            self.assertEqual((source / "build/config/siso/backend_config/backend.star").read_text(), "prior backend\n")
            self.assertFalse((fixture.build_root / "linux-toolchain-invoked").exists())


if __name__ == "__main__":
    unittest.main()
