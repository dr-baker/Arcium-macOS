"""Black-box checks for the small public ``he`` development loop."""

from __future__ import annotations

import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEV_SH = ROOT / "dev.sh"


def run_zsh(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/zsh", "-c", f"source {DEV_SH!s}; {script}"],
        check=False,
        capture_output=True,
        text=True,
    )


class DevShellCommandsTests(unittest.TestCase):
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
            heavy = Path(temporary) / "heavy"
            (heavy / "src/out/Default").mkdir(parents=True)
            (heavy / "src/out/Default/build.ninja").write_text(
                "warm\n", encoding="utf-8"
            )
            command = (
                f"unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT; "
                f"HELIUM_DEV_HEAVY_ROOT={shlex.quote(str(heavy))}; "
                "export HELIUM_DEV_HEAVY_ROOT; "
                f"source {shlex.quote(str(DEV_SH))}; "
                "printf '%s\\n' \"$HELIUM_DEV_LANE\" \"$HELIUM_DEV_BUILD_ROOT\""
            )
            result = subprocess.run(
                ["/bin/zsh", "-c", command],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["heavy", str(heavy)])

    def test_resourcing_auto_lane_does_not_become_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            heavy = Path(temporary) / "heavy"
            command = (
                "unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT HELIUM_DEV_AUTO_SELECTED; "
                f"HELIUM_DEV_HEAVY_ROOT={shlex.quote(str(heavy))}; export HELIUM_DEV_HEAVY_ROOT; "
                f"HELIUM_DEV_WORKTREE={shlex.quote(str(ROOT))}; export HELIUM_DEV_WORKTREE; "
                f"source {shlex.quote(str(DEV_SH))}; "
                f"mkdir -p {shlex.quote(str(heavy / 'src/out/Default'))}; "
                f"touch {shlex.quote(str(heavy / 'src/out/Default/build.ninja'))}; "
                f"source {shlex.quote(str(DEV_SH))}; "
                "printf '%s\\n' \"$HELIUM_DEV_LANE\" \"$HELIUM_DEV_BUILD_ROOT\""
            )
            result = subprocess.run(["/bin/zsh", "-c", command], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["heavy", str(heavy)])

    def test_automatic_patch_pushes_never_refresh_catalog_files(self) -> None:
        script = DEV_SH.read_text(encoding="utf-8")
        self.assertNotIn("quilt push -a --refresh", script)
        self.assertIn('QUILT_PATCH_OPTS="$QUILT_PATCH_OPTS --fuzz=0" quilt push -a', script)

    def test_pull_uses_fail_closed_autostash_rebase(self) -> None:
        script = DEV_SH.read_text(encoding="utf-8")
        self.assertNotIn('git -C "$dir" stash', script)
        self.assertIn('git -C "$dir" fetch || return', script)
        self.assertIn('git -C "$dir" rebase --autostash origin/main || return', script)

    def test_reset_deletes_warm_source_before_releasing_transaction(self) -> None:
        script = DEV_SH.read_text(encoding="utf-8")
        self.assertIn('rm -rf "${_src_dir}x" || return', script)
        self.assertNotIn('rm -rf "${_src_dir}x" &', script)

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
        self.assertIn("prepare-patches - rebuilds the selected lane's generated patch catalog", advanced.stderr)
        self.assertIn("save-patch - refreshes and exports only the active top patch", advanced.stderr)

    def test_dev_passes_only_profile_identity_to_relink(self) -> None:
        script = DEV_SH.read_text(encoding="utf-8")
        self.assertIn(
            '___helium_relink --resources "${_profile_args[@]}"', script
        )
        self.assertIn('[[ "$_argument" = --isolated=* ]]', script)

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
            "_dev_lane=local; _out_dir=$(mktemp -d); "
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
            "___helium_configure(){ echo configure; }; "
            "___helium_relink(){ echo relink:$*; }; "
            "___helium_configure_inner(){ echo configure; }; "
            "___helium_lane_transaction(){ shift; ___helium_arcium_inner \"$@\"; }; "
            "he arcium"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["preflight", "check", "configure", "relink:--resources", "install"],
        )

        refused = run_zsh(
            "___helium_lane_transaction(){ shift; ___helium_arcium_inner \"$@\"; }; "
            "he arcium extra"
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("takes no options", refused.stderr)

    def test_setup_stops_at_first_failed_stage(self) -> None:
        result = run_zsh(
            "_src_dir=$(mktemp -d)/src; _download_cache=${_src_dir}/downloads; "
            "_out_dir=${_src_dir}/out/Default; "
            "___helium_lane_preflight(){ return 0; }; "
            "___helium_setup_python(){ echo python; }; "
            "___helium_info_pull(){ echo pull; return 7; }; "
            "___helium_toolchain(){ echo toolchain; }; "
            "___helium_resources(){ echo resources; }; "
            "___helium_setup_gn(){ echo gn; }; "
            "___helium_version(){ echo version; }; "
            "___helium_setup_presetup_inner"
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["python", "pull"])

    def test_full_source_setup_skips_product_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src"
            result = run_zsh(
                f"_src_dir={source!s}; _download_cache={root / 'downloads'!s}; "
                f"_out_dir={source / 'out/Default'!s}; _source_mode=full; "
                "___helium_lane_preflight(){ :; }; "
                "___helium_setup_python(){ :; }; "
                "___helium_info_pull(){ mkdir -p \"$_src_dir\"; }; "
                "___helium_python(){ echo unexpected-python:$*; return 9; }; "
                "___helium_toolchain(){ echo toolchain; }; "
                "___helium_resources_inner(){ echo resources; }; "
                "___helium_setup_gn(){ echo gn; }; "
                "___helium_version(){ echo version; }; "
                "___helium_setup_presetup_inner"
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

    def test_configure_stops_after_failed_siso_setup(self) -> None:
        result = run_zsh(
            "_src_dir=$(mktemp -d); _out_dir=${_src_dir}/out/Default; "
            "___helium_setup_python(){ echo python; }; "
            "___helium_setup_siso(){ echo siso; return 8; }; "
            "___helium_configure_inner"
        )
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["python", "siso"])

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
            retriever = root / "retrieve_and_unpack_resource.sh"
            retriever.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RETRIEVE_CALLS\"\nexit 9\n",
                encoding="utf-8",
            )
            retriever.chmod(0o755)
            calls = root / "calls"
            result = run_zsh(
                f"_root_dir={root!s}; _src_dir={root / 'src'!s}; "
                f"_out_dir={root / 'src/out/Default'!s}; "
                f"RETRIEVE_CALLS={calls!s}; export RETRIEVE_CALLS; ___helium_info_pull"
            )
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), ["-d -g", "-g"])
            self.assertFalse((root / "src" / "out").exists())

    def test_full_source_retrieval_uses_clone_and_records_the_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            retriever = root / "retrieve_and_unpack_resource.sh"
            retriever.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RETRIEVE_CALLS\"\n",
                encoding="utf-8",
            )
            retriever.chmod(0o755)
            calls = root / "calls"
            marker = root / "build/.arcium/source-mode"
            result = run_zsh(
                f"_root_dir={root!s}; _src_dir={root / 'build/src'!s}; "
                f"_out_dir={root / 'build/src/out/Default'!s}; "
                f"_source_mode_marker={marker!s}; _source_mode=full; "
                f"RETRIEVE_CALLS={calls!s}; export RETRIEVE_CALLS; ___helium_info_pull"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), ["-g"])
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
            "_subs_cache=/nonexistent/arcium-subs; "
            "python3(){ echo domain; }; "
            "___helium_name_substitution_inner(){ echo name; return 7; }; "
            "___helium_substitution_inner sub"
        )
        self.assertEqual(applied.returncode, 7, applied.stderr)
        self.assertEqual(applied.stdout.splitlines(), ["name"])


if __name__ == "__main__":
    unittest.main()
