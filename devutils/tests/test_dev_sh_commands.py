"""Black-box checks for the small public ``he`` development loop."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEV_SH = ROOT / "dev.sh"
sys.path.insert(0, str(ROOT))

from devutils.tests.test_build_receipt import material_fixture  # noqa: E402


class ShellFixture:
    """Keep every selected shell path in a disposable worktree and lane."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.worktree = self.root / "worktree"
        self.build_root = self.root / "build"
        self.heavy_root = self.root / "heavy"
        self.python_env = self.root / "python-env"
        self.temp = self.root / "tmp"
        (self.worktree / "devutils").mkdir(parents=True)
        self.temp.mkdir()
        shutil.copy2(
            ROOT / "devutils/setup_python.sh",
            self.worktree / "devutils/setup_python.sh",
        )
        (self.worktree / "requirements-dev.txt").write_text(
            "# No fixture dependencies.\n", encoding="utf-8"
        )
        (self.python_env / "bin").mkdir(parents=True)
        (self.python_env / "bin/python3").symlink_to(sys.executable)
        subprocess.run(
            [
                "/usr/bin/git", "-c", "init.templateDir=", "-c",
                "init.defaultBranch=main", "init", "--quiet", str(self.worktree),
            ],
            cwd=self.worktree,
            env=self.environment(),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def environment(self) -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("HELIUM_DEV_", "QUILT_", "GIT_"))
            and key not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
        }
        environment.update({
            "HELIUM_DEV_WORKTREE": str(self.worktree),
            "HELIUM_DEV_LANE": "worktree",
            "HELIUM_DEV_BUILD_ROOT": str(self.build_root),
            "HELIUM_DEV_HEAVY_ROOT": str(self.heavy_root),
            "HELIUM_DEV_DOWNLOAD_CACHE": str(self.build_root / "downloads"),
            "HELIUM_DEV_PYTHON_ENV": str(self.python_env),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": str(self.python_env / "bin") + os.pathsep + os.defpath,
            "TMPDIR": str(self.temp),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return environment

    def command(self, script: str, *, before_source: str = "") -> list[str]:
        prefix = before_source + "; " if before_source else ""
        return [
            "/bin/zsh", "-f", "-c",
            f"{prefix}source {shlex.quote(str(DEV_SH))} || exit $?; {script}",
        ]

    def material_inputs(self) -> None:
        material_fixture(self.worktree)


def run_zsh(
    script: str, *, fixture: ShellFixture | None = None, before_source: str = "",
) -> subprocess.CompletedProcess[str]:
    if fixture is None:
        with tempfile.TemporaryDirectory(prefix="arcium-shell-test-") as temporary:
            return run_zsh(
                script, fixture=ShellFixture(Path(temporary)),
                before_source=before_source,
            )
    return subprocess.run(
        fixture.command(script, before_source=before_source),
        cwd=fixture.worktree,
        env=fixture.environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


class DevShellCommandsTests(unittest.TestCase):
    def test_external_harness_checks_preparation_without_source_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            fixture.material_inputs()
            diagnostics = fixture.worktree / "devutils/build_diagnostics.py"
            diagnostics.unlink(missing_ok=True)
            metadata = fixture.build_root / ".arcium"
            metadata.mkdir(parents=True)
            (metadata / "source-mode").write_text("lite\n", encoding="utf-8")
            (metadata / "acquisition-target").write_text(platform.machine() + "\n", encoding="utf-8")
            producer_marker = fixture.root / "producer-invoked"
            setup_receipt = (
                "import sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'devutils')!r}); "
                "from build_preparation import input_digest, record_stage; "
                "worktree=Path(sys.argv[1]); lane=Path(sys.argv[2]); "
                "record_stage(worktree, lane, 'acquisition', input_digest(worktree, lane, 'acquisition'))"
            )
            result = run_zsh(
                f"___helium_python -c {shlex.quote(setup_receipt)} "
                f"{shlex.quote(str(fixture.worktree))} {shlex.quote(str(fixture.build_root))} || exit $?; "
                f"tripwire(){{ print invoked >> {shlex.quote(str(producer_marker))}; return 99; }}; "
                "___helium_acquire_inner(){ tripwire; }; "
                "___helium_resources_inner(){ tripwire; }; "
                "___helium_version_inner(){ tripwire; }; "
                "___helium_setup_python(){ tripwire; }; "
                "___helium_setup_gn(){ tripwire; }; "
                "___helium_preparation require acquisition",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(diagnostics.exists())
            self.assertFalse(producer_marker.exists())
            self.assertFalse((fixture.build_root / "src").exists())

    def test_he_python_does_not_write_bytecode_into_the_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "probe.py").write_text("VALUE = 1\n", encoding="utf-8")
            result = run_zsh(
                f"cd {shlex.quote(str(root))}; "
                "___helium_python -c 'import probe; assert probe.VALUE == 1'"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "__pycache__").exists())

    def test_source_prefers_a_structurally_warm_heavy_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            heavy = fixture.heavy_root
            (heavy / "src/out/Default").mkdir(parents=True)
            (heavy / "src/out/Default/build.ninja").write_text(
                "warm\n", encoding="utf-8"
            )
            result = run_zsh(
                "printf '%s\\n' \"$HELIUM_DEV_LANE\" \"$HELIUM_DEV_BUILD_ROOT\"",
                fixture=fixture,
                before_source="unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["heavy", str(heavy)])

    def test_resourcing_auto_lane_does_not_become_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            heavy = fixture.heavy_root
            command = (
                f"mkdir -p {shlex.quote(str(heavy / 'src/out/Default'))}; "
                f"touch {shlex.quote(str(heavy / 'src/out/Default/build.ninja'))}; "
                f"source {shlex.quote(str(DEV_SH))} || exit $?; "
                "printf '%s\\n' \"$HELIUM_DEV_LANE\" \"$HELIUM_DEV_BUILD_ROOT\""
            )
            result = run_zsh(
                command, fixture=fixture,
                before_source="unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["heavy", str(heavy)])

    def test_patch_push_uses_zero_fuzz_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "src"
            source.mkdir()
            result = run_zsh(
                f"_src_dir={shlex.quote(str(source))}; "
                "quilt(){ printf '%s\\n' \"$QUILT_PATCH_OPTS\" \"$*\"; }; "
                "___helium_quilt_push_inner"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                ["--unified --reject-format=unified --fuzz=0", "--quiltrc - push -a"],
            )
            self.assertNotIn("refresh", result.stdout)

    def test_pull_stops_after_failed_autostash_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            result = run_zsh(
                "___helium_quilt_pop_inner(){ echo quilt-pop; }; "
                "___helium_prepare_patches_inner(){ echo prepare; }; "
                "___helium_quilt_push_inner(){ echo quilt-push; }; "
                "git(){ echo \"git:$*\"; if [[ \"$*\" = *rebase* ]]; then return 7; fi; return 0; }; "
                "___helium_pull_inner",
                fixture=fixture,
            )

            self.assertEqual(result.returncode, 7)
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    "quilt-pop",
                    f"git:-C {fixture.worktree} fetch",
                    f"git:-C {fixture.worktree} rebase --autostash origin/main",
                ],
            )
            self.assertNotIn("quilt-push", result.stdout)
            self.assertNotIn("prepare", result.stdout)

    def test_reset_removes_warm_source_synchronously(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ShellFixture(root)
            fixture.material_inputs()
            source = fixture.build_root / "src"
            source.mkdir(parents=True)
            (source / "marker").write_text("warm\n", encoding="utf-8")
            subs_cache = fixture.build_root / "subs.tar.gz"
            namesubs_cache = fixture.build_root / "namesubs.tar"
            deletion_started = root / "deletion-started"
            release_deletion = root / "release-deletion"
            reset_returned = root / "reset-returned"
            subs_cache.write_text("subs\n", encoding="utf-8")
            namesubs_cache.write_text("namesubs\n", encoding="utf-8")
            metadata = fixture.build_root / ".arcium"
            (metadata / "receipts").mkdir(parents=True)
            stale_proof = [
                metadata / "source-mode",
                metadata / "acquisition-target",
                metadata / "receipts/prepared-acquisition.json",
                metadata / "receipts/replay.json",
                metadata / "receipts/execution.json",
                metadata / "receipts/build.json",
            ]
            for path in stale_proof:
                path.write_text("lite\n", encoding="utf-8")
            script = (
                f"_deletion_started={shlex.quote(str(deletion_started))}; "
                f"_release_deletion={shlex.quote(str(release_deletion))}; "
                f"_reset_returned={shlex.quote(str(reset_returned))}; "
                "rm(){ if [[ \"$1\" = -rf ]]; then "
                "print started > \"$_deletion_started\"; "
                "while [[ ! -e \"$_release_deletion\" ]]; do sleep 0.01; done; "
                "fi; command rm \"$@\"; }; "
                "___helium_reset_inner --warm-output --approved || exit; "
                "print returned > \"$_reset_returned\""
            )
            process = subprocess.Popen(
                fixture.command(script),
                cwd=fixture.worktree, env=fixture.environment(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                deadline = time.monotonic() + 3
                while not deletion_started.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(deletion_started.exists(), "reset never started deletion")
                self.assertFalse(reset_returned.exists())
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
                self.assertFalse(reset_returned.exists(), "reset returned before deletion completed")
            finally:
                release_deletion.touch()
                _stdout, stderr = process.communicate(timeout=5)

            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(reset_returned.read_text(encoding="utf-8"), "returned\n")
            self.assertFalse(source.exists())
            self.assertFalse(Path(f"{source}x").exists())
            self.assertFalse(subs_cache.exists())
            self.assertFalse(namesubs_cache.exists())
            self.assertTrue(all(not path.exists() for path in stale_proof))

    def test_menu_leads_with_public_development_loop(self) -> None:
        result = run_zsh("he")
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "bootstrap --approved [--full-source] [--allow-internal] - one-time cold browser build",
            result.stderr,
        )
        self.assertIn("arcium - update, install, and launch", result.stderr)
        self.assertIn("check - validate the active patch catalog", result.stderr)
        self.assertIn("context [--json] - show source, lane, proof", result.stderr)
        self.assertIn("replay - pop and strictly replay", result.stderr)
        self.assertIn("dev [profile options] - rebuild and run a labeled Dev app", result.stderr)
        self.assertNotIn("presetup", result.stderr)

        advanced = run_zsh("he help --advanced")
        self.assertEqual(advanced.returncode, 0)
        self.assertIn("presetup", advanced.stderr)
        self.assertIn("version - stamp the selected Chromium source with the current Arcium version", advanced.stderr)
        self.assertIn("prepare-patches - rebuilds the selected lane's generated patch catalog", advanced.stderr)
        self.assertIn("save-patch - refreshes and exports only the active top patch", advanced.stderr)

    def test_public_version_uses_guarded_transaction_and_preserves_result(self) -> None:
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code):
                result = run_zsh(
                    "___helium_lane_transaction(){ "
                    "printf 'transaction:%s:%s\\n' \"$#\" \"$1\"; "
                    f"return {exit_code}; }}; he version"
                )
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ["transaction:1:version"])
                self.assertEqual(result.stderr, "")

    def test_public_version_runs_in_locked_material_transaction(self) -> None:
        for producer_status, missing_input in ((0, False), (7, False), (0, True)):
            with self.subTest(producer_status=producer_status, missing_input=missing_input):
                with tempfile.TemporaryDirectory() as temporary:
                    fixture = ShellFixture(Path(temporary))
                    fixture.material_inputs()
                    harness = fixture.root / "instrumented-harness"
                    harness.mkdir()
                    (harness / "devutils").symlink_to(ROOT / "devutils", target_is_directory=True)
                    producer = fixture.root / "harmless-version-producer.py"
                    producer.write_text(
                        "import fcntl, json, os, sys\n"
                        "from pathlib import Path\n"
                        f"sys.path.insert(0, {str(ROOT / 'devutils')!r})\n"
                        "from build_receipt import MATERIAL_INPUTS_ENV, material_inputs_at_entry\n"
                        "root = Path(os.environ['HELIUM_DEV_WORKTREE'])\n"
                        "assert os.environ[MATERIAL_INPUTS_ENV] == material_inputs_at_entry(root)\n"
                        "lock = Path(os.environ['HELIUM_DEV_BUILD_ROOT']) / '.arcium/lane.lock'\n"
                        "descriptor = int(os.environ['HELIUM_DEV_LANE_LOCK_FD'])\n"
                        "owned, selected = os.fstat(descriptor), lock.stat()\n"
                        "assert (owned.st_dev, owned.st_ino) == (selected.st_dev, selected.st_ino)\n"
                        "assert json.loads(lock.read_text())['action'] == 'version'\n"
                        "with lock.open() as competing:\n"
                        "    try:\n"
                        "        fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                        "    except BlockingIOError:\n"
                        "        pass\n"
                        "    else:\n"
                        "        raise AssertionError('producer ran without the lane lock')\n"
                        "print('producer:version')\n",
                        encoding="utf-8",
                    )
                    # Keep the real dispatcher, wrapper and Python transaction.
                    # Only the child producer is replaced in this disposable copy.
                    (harness / "dev.sh").write_text(
                        DEV_SH.read_text(encoding="utf-8")
                        + "\n___helium_version_inner(){ "
                        f"___helium_python {shlex.quote(str(producer))} || return; "
                        f"return {producer_status}; }}\n",
                        encoding="utf-8",
                    )
                    metadata = plistlib.dumps({
                        "MountPoint": str(fixture.root), "VolumeUUID": "fixture-volume",
                        "FilesystemType": "apfs", "FilesystemName": "Case-sensitive APFS",
                        "WritableVolume": True, "Internal": True,
                    }).decode("utf-8")
                    diskutil = fixture.python_env / "bin/diskutil"
                    diskutil.write_text(
                        "#!/bin/sh\ncat <<'PLIST'\n" + metadata + "PLIST\n", encoding="utf-8"
                    )
                    diskutil.chmod(0o700)
                    if missing_input:
                        (fixture.worktree / "flags.macos.gn").unlink()
                    result = run_zsh(
                        f"_helium_harness_root={shlex.quote(str(harness))}; he version",
                        fixture=fixture,
                    )

                    self.assertEqual(result.returncode, 2 if missing_input else producer_status, result.stderr)
                    if missing_input:
                        self.assertEqual(result.stdout, "")
                        self.assertIn("flags.macos.gn", result.stderr)
                        self.assertFalse(fixture.build_root.exists())
                    else:
                        self.assertEqual(result.stdout.splitlines(), ["producer:version"])
                        self.assertEqual(result.stderr, "")
                        lock = fixture.build_root / ".arcium/lane.lock"
                        self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["action"], "version")

    def test_explicit_help_succeeds_without_dispatching_producers(self) -> None:
        for command in ("he", "he help", "he -h", "he --help", "he help --advanced"):
            with self.subTest(command=command):
                result = run_zsh(
                    "___helium_lane_transaction(){ echo unexpected-producer; return 99; }; "
                    + command
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage: he <command>", result.stderr)

    def test_unsupported_public_commands_fail_without_dispatching_producers(self) -> None:
        for command in ("versoin", "unknown-command", "--advanced"):
            with self.subTest(command=command):
                result = run_zsh(
                    "___helium_lane_transaction(){ echo unexpected-producer; return 99; }; "
                    f"he {shlex.quote(command)}"
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("unknown command: " + command, result.stderr)

    def test_help_rejects_unsupported_arguments(self) -> None:
        for command in ("he help --unsupported", "he help --advanced extra", "he --help extra"):
            with self.subTest(command=command):
                result = run_zsh(
                    "___helium_lane_transaction(){ echo unexpected-producer; return 99; }; "
                    + command
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage: he help [--advanced]", result.stderr)

    def test_reset_refuses_without_explicit_warm_output_approval(self) -> None:
        result = run_zsh(
            "___helium_lane_transaction(){ shift; ___helium_reset_inner \"$@\"; }; "
            "he reset"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("reset preserves the warm build", result.stderr)

    def test_sync_patches_uses_the_guarded_lane_transaction(self) -> None:
        result = run_zsh(
            "___helium_lane_preflight(){ return 0; }; "
            "___helium_lane_transaction(){ echo action:$1; }; "
            "he sync-patches"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["action:sync-patches"])

    def test_pop_target_uses_the_guarded_lane_transaction(self) -> None:
        result = run_zsh(
            "___helium_lane_transaction(){ printf '%s\\n' \"$*\"; }; "
            "he pop personal/arcium-pins.patch"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "pop personal/arcium-pins.patch"
        )

    def test_check_validates_extracted_quilt_source_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src"
            patches = root / "patches"
            backup = source / ".pc" / "personal" / "change.patch" / "chrome"
            current = source / "chrome"
            backup.mkdir(parents=True)
            current.mkdir(parents=True)
            (root / "devutils").mkdir()
            (root / "devutils" / "check_patch_files.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            checker = root / "devutils" / "check_patch_files.sh"
            checker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            checker.chmod(0o755)
            patches.mkdir()
            (patches / "series.merged").write_text(
                "personal/change.patch\n", encoding="utf-8"
            )
            (patches / "personal").mkdir()
            (patches / "personal" / "change.patch").write_text(
                "patch\n", encoding="utf-8"
            )
            (source / ".pc" / ".quilt_patches").write_text(
                str(patches) + "\n", encoding="utf-8"
            )
            (source / ".pc" / ".quilt_series").write_text(
                "series.merged\n", encoding="utf-8"
            )
            (source / ".pc" / "applied-patches").write_text(
                "personal/change.patch\n", encoding="utf-8"
            )
            (backup / "example.cc").write_text("old\n", encoding="utf-8")
            target = current / "example.cc"
            target.write_text("new\n", encoding="utf-8")

            command_prefix = (
                f"_root_dir={shlex.quote(str(root))}; "
                f"_src_dir={shlex.quote(str(source))}; "
            )
            clean = run_zsh(command_prefix + "___helium_check_source")
            self.assertEqual(clean.returncode, 0, clean.stderr)

            target.write_text("new \n", encoding="utf-8")
            invalid = run_zsh(command_prefix + "___helium_check_source")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("trailing whitespace", invalid.stderr)

    def test_dev_runs_check_configure_relink_bundle_and_launch(self) -> None:
        result = run_zsh(
            "___helium_check(){ echo check; }; "
            "___helium_require_replay_proof(){ echo replay-proof; }; "
            "___helium_configure_inner(){ echo configure; }; "
            "___helium_relink(){ echo relink:$*; }; "
            "___helium_dev_bundle(){ echo bundle; }; "
            "___helium_run(){ echo run:$*; }; "
            "___helium_lane_transaction(){ shift; ___helium_dev_inner \"$@\"; }; "
            "he dev --isolated smoke"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "check",
                "replay-proof",
                "configure",
                "relink:--resources --isolated smoke",
                "bundle",
                "run:--isolated smoke",
            ],
        )

    def test_bootstrap_requires_approval_before_setup(self) -> None:
        result = run_zsh(
            "___helium_setup(){ echo setup; }; "
            "___helium_build_full(){ echo build:$*; }; "
            "___helium_dev_bundle(){ echo bundle; }; "
            "___helium_lane_transaction(){ shift; ___helium_bootstrap_inner \"$@\"; }; "
            "he bootstrap"
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("setup", result.stdout)

    def test_direct_heavy_build_routes_temporary_traffic_to_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            build_root = Path(temporary) / "build"
            result = run_zsh(
                f"_dev_lane=heavy; _build_dir={build_root!s}; "
                "___helium_lane_preflight(){ return 0; }; "
                "___helium_harness(){ printf '%s\\n' \"$TMPDIR\"; }; "
                "___helium_build_full --approved"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(build_root / ".arcium" / "tmp"),
            )

    def test_expensive_work_refuses_unapproved_local_storage(self) -> None:
        build = run_zsh(
            "_dev_lane=local; "
            "___helium_lane_preflight(){ echo preflight; }; "
            "___helium_harness(){ echo harness; }; "
            "___helium_build_full --approved"
        )
        self.assertEqual(build.returncode, 2)
        self.assertNotIn("preflight", build.stdout)
        self.assertNotIn("harness", build.stdout)
        self.assertIn("requires explicit approval for internal storage", build.stderr)

        bootstrap = run_zsh(
            "_dev_lane=local; "
            "___helium_lane_transaction(){ echo transaction; }; "
            "___helium_bootstrap --approved"
        )
        self.assertEqual(bootstrap.returncode, 2)
        self.assertNotIn("transaction", bootstrap.stdout)
        self.assertIn("requires explicit approval for internal storage", bootstrap.stderr)

    def test_expensive_local_work_requires_separate_capability(self) -> None:
        build = run_zsh(
            "_dev_lane=local; "
            "___helium_lane_preflight(){ :; }; "
            "___helium_prepare_lane_temp(){ :; }; "
            "___helium_harness(){ echo \"$*\"; }; "
            "___helium_build_full --approved --allow-internal"
        )
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertEqual(build.stdout.strip(), "build-full --approved")

    def test_local_bootstrap_forwards_internal_capability_to_full_build(self) -> None:
        result = run_zsh(
            "_dev_lane=local; "
            "___helium_lane_transaction(){ shift; ___helium_bootstrap_inner \"$@\"; }; "
            "___helium_lane_preflight(){ :; }; "
            "___helium_setup_inner(){ :; }; "
            "___helium_prepare_lane_temp(){ :; }; "
            "___helium_harness(){ echo \"$*\"; }; "
            "___helium_dev_bundle(){ :; }; "
            "___helium_bootstrap --approved --allow-internal"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "build-full --approved --edge-budget 100000"
        )

    def test_arcium_runs_one_guarded_update_flow(self) -> None:
        result = run_zsh(
            "python3(){ if [[ $* == *preflight* ]]; then echo preflight; else echo install; fi; }; "
            "___helium_check(){ echo check; }; "
            "___helium_require_replay_proof(){ echo replay-proof; }; "
            "___helium_configure(){ echo configure; }; "
            "___helium_relink(){ echo relink:$*; }; "
            "___helium_configure_inner(){ echo configure; }; "
            "___helium_lane_transaction(){ shift; ___helium_arcium_inner \"$@\"; }; "
            "he arcium"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["preflight", "check", "replay-proof", "configure", "relink:--resources", "install"],
        )

        refused = run_zsh(
            "___helium_lane_transaction(){ shift; ___helium_arcium_inner \"$@\"; }; "
            "he arcium extra"
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("use he arcium", refused.stderr)

    def test_setup_stops_at_first_failed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            fixture.material_inputs()
            result = run_zsh(
                "___helium_lane_preflight(){ return 0; }; "
                "___helium_setup_python(){ echo python; }; "
                "___helium_info_pull(){ echo pull; return 7; }; "
                "___helium_toolchain(){ echo toolchain; }; "
                "___helium_resources_inner(){ echo resources; }; "
                "___helium_setup_gn(){ echo gn; }; "
                "___helium_version_inner(){ echo version; }; "
                "___helium_setup_presetup_inner",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["python", "pull"])
            self.assertFalse(
                (fixture.build_root / ".arcium/receipts/prepared-acquisition.json").exists()
            )

    def test_full_source_setup_skips_product_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            fixture.material_inputs()
            result = run_zsh(
                "_source_mode=full; export HELIUM_DEV_SOURCE_MODE=full; "
                "___helium_lane_preflight(){ :; }; "
                "___helium_setup_python(){ :; }; "
                "___helium_info_pull(){ "
                "mkdir -p \"$_out_dir\" \"$_build_dir/.arcium\"; "
                "print full > \"$_source_mode_marker\"; }; "
                "python3(){ "
                "if [[ \"$1\" = \"$_main_repo/utils/prune_binaries.py\" ]]; then "
                "echo unexpected-python:$*; return 9; fi; command python3 \"$@\"; }; "
                "___helium_toolchain(){ echo toolchain; }; "
                "___helium_resources_inner(){ echo resources; }; "
                "___helium_setup_gn(){ echo gn; }; "
                "___helium_version_inner(){ echo version; }; "
                "___helium_setup_presetup_inner",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("unexpected-python", result.stdout)
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    "preserving full Chromium source and test data",
                    "toolchain",
                    "resources",
                    "gn",
                    "version",
                ],
            )
            self.assertTrue(
                (fixture.build_root / ".arcium/receipts/prepared-acquisition.json").exists()
            )

    def test_pending_recovery_blocks_configuration_before_lane_mutation(self) -> None:
        for option in ("", "--refresh-defaults"):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as temporary:
                fixture = ShellFixture(Path(temporary))
                fixture.material_inputs()
                out = fixture.build_root / "src/out/Default"
                out.mkdir(parents=True)
                journal = fixture.build_root / ".arcium/replay-timestamps.json"
                journal.parent.mkdir(parents=True)
                journal.write_bytes(b"pending fixture recovery\n")
                bootstrap_marker = fixture.root / "bootstrap-invoked"
                bootstrap = fixture.build_root / "src/tools/gn/bootstrap/bootstrap.py"
                bootstrap.parent.mkdir(parents=True)
                bootstrap.write_text(
                    "from pathlib import Path\nimport sys\n"
                    f"Path({str(bootstrap_marker)!r}).write_text('invoked\\n')\n"
                    "Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'fixture gn')\n"
                    "print('bootstrap')\n",
                    encoding="utf-8",
                )
                dawn = fixture.worktree / "devutils/setup_dawn_go.sh"
                dawn.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                dawn.chmod(0o755)
                result = run_zsh(
                    "___helium_setup_python(){ :; }; "
                    "print lite > \"$_source_mode_marker\"; "
                    "print \"$HELIUM_DEV_ACQUISITION_TARGET\" > \"$_build_dir/.arcium/acquisition-target\"; "
                    "print 'is_component_build = true' > \"$_out_dir/args.gn\"; "
                    "for stage in acquisition gn-defaults; do "
                    "entry=\"$(___helium_preparation begin \"$stage\")\" || exit $?; "
                    "___helium_preparation finish \"$stage\" \"$entry\" || exit $?; done; "
                    "python3(){ "
                    "if [[ \"$1\" = \"$_helium_harness_root/devutils/prepare_test_assets.py\" ]]; then "
                    "echo test-assets; return 0; fi; command python3 \"$@\"; }; "
                    "___helium_setup_gn(){ echo unexpected-default-refresh; return 9; }; "
                    "___helium_setup_siso(){ echo siso; }; "
                    f"___helium_configure_inner {option}",
                    fixture=fixture,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("timestamp recovery is pending", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse(bootstrap_marker.exists())
                self.assertEqual((out / "args.gn").read_text(), "is_component_build = true\n")
                self.assertEqual(journal.read_bytes(), b"pending fixture recovery\n")

    def test_configure_stops_after_failed_siso_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ShellFixture(Path(temporary))
            fixture.material_inputs()
            result = run_zsh(
                "mkdir -p \"$_out_dir\" \"$_build_dir/.arcium\"; "
                "print lite > \"$_source_mode_marker\"; "
                "print \"$HELIUM_DEV_ACQUISITION_TARGET\" > \"$_build_dir/.arcium/acquisition-target\"; "
                "print 'is_component_build = true' > \"$_out_dir/args.gn\"; "
                "for stage in acquisition gn-defaults; do "
                "entry=\"$(___helium_preparation begin \"$stage\")\" || exit $?; "
                "___helium_preparation finish \"$stage\" \"$entry\" || exit $?; done; "
                "___helium_setup_python(){ echo python; }; "
                "python3(){ "
                "if [[ \"$1\" = \"$_helium_harness_root/devutils/prepare_test_assets.py\" ]]; then "
                "echo test-assets; return 0; fi; command python3 \"$@\"; }; "
                "___helium_setup_siso(){ echo siso; return 8; }; "
                "___helium_require_replay_proof(){ :; }; "
                "___helium_configure_inner",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 8, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["python", "test-assets", "siso"])

    def test_siso_setup_recreates_marker_omitted_by_full_source_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "src"
            configure = source / "build/config/siso/configure_siso.py"
            configure.parent.mkdir(parents=True)
            configure.write_text("pass\n", encoding="utf-8")
            siso = source / "third_party/siso/cipd/siso"
            siso.parent.mkdir(parents=True)
            siso.write_text("#!/bin/sh\n", encoding="utf-8")
            siso.chmod(0o755)
            result = run_zsh(
                f"_src_dir={shlex.quote(str(source))}; "
                f"_siso_path={shlex.quote(str(siso))}; "
                "___helium_python(){ printf '%s\\n' \"$*\"; }; "
                "___helium_setup_siso"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                f"{configure} --rbe_instance "
                "projects/rbe-chrome-untrusted/instances/default_instance",
            )

    def test_source_retrieval_stops_when_archive_and_git_fallback_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ShellFixture(root)
            retriever = fixture.worktree / "retrieve_and_unpack_resource.sh"
            retriever.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RETRIEVE_CALLS\"\nexit 9\n",
                encoding="utf-8",
            )
            retriever.chmod(0o755)
            calls = root / "calls"
            result = run_zsh(
                f"RETRIEVE_CALLS={shlex.quote(str(calls))}; "
                "export RETRIEVE_CALLS; ___helium_info_pull",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                [f"-d -g {platform.machine()}", f"-g {platform.machine()}"],
            )
            self.assertFalse((fixture.build_root / "src/out").exists())

    def test_full_source_retrieval_uses_clone_and_records_the_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ShellFixture(root)
            retriever = fixture.worktree / "retrieve_and_unpack_resource.sh"
            retriever.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RETRIEVE_CALLS\"\n",
                encoding="utf-8",
            )
            retriever.chmod(0o755)
            calls = root / "calls"
            marker = fixture.build_root / ".arcium/source-mode"
            result = run_zsh(
                "_source_mode=full; export HELIUM_DEV_SOURCE_MODE=full; "
                f"RETRIEVE_CALLS={shlex.quote(str(calls))}; "
                "export RETRIEVE_CALLS; ___helium_info_pull",
                fixture=fixture,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                [f"-g {platform.machine()}"],
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "full\n")

    def test_full_source_bootstrap_reaches_the_lane_transaction(self) -> None:
        result = run_zsh(
            "_dev_lane=heavy; "
            "___helium_lane_transaction(){ printf '%s\\n' \"$*\" \"$HELIUM_DEV_SOURCE_MODE\"; }; "
            "___helium_bootstrap --approved --full-source"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["bootstrap --approved --full-source", "full"],
        )

    def test_substitution_stops_before_later_stage_after_failure(self) -> None:
        reverted = run_zsh(
            "python3(){ echo domain; return 6; }; "
            "___helium_name_substitution_inner(){ echo name; }; "
            "___helium_substitution_inner unsub"
        )
        self.assertEqual(reverted.returncode, 6, reverted.stderr)
        self.assertEqual(reverted.stdout.splitlines(), ["domain"])

        applied = run_zsh(
            "python3(){ echo domain; }; "
            "___helium_name_substitution_inner(){ echo name; return 7; }; "
            "___helium_substitution_inner sub"
        )
        self.assertEqual(applied.returncode, 7, applied.stderr)
        self.assertEqual(applied.stdout.splitlines(), ["name"])


if __name__ == "__main__":
    unittest.main()
