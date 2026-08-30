"""Black-box checks for the small public ``he`` development loop."""

from __future__ import annotations

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
        self.assertIn("bootstrap --approved - one-time cold browser build", result.stderr)
        self.assertIn("arcium - update, install, and launch", result.stderr)
        self.assertIn("check - validate the active patch catalog", result.stderr)
        self.assertIn("sync-patches - refresh generated core copies", result.stderr)
        self.assertIn("replay - pop and strictly replay", result.stderr)
        self.assertIn("dev [profile options] - incrementally rebuild", result.stderr)
        self.assertNotIn("presetup", result.stderr)

        advanced = run_zsh("he help --advanced")
        self.assertEqual(advanced.returncode, 0)
        self.assertIn("presetup", advanced.stderr)
        self.assertIn("sync-patches - refreshes generated core copies", advanced.stderr)

    def test_reset_refuses_without_explicit_warm_output_approval(self) -> None:
        result = run_zsh("he reset")
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
            ["check", "replay-proof", "configure", "relink:--resources", "bundle", "run:--isolated smoke"],
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

    def test_configure_stops_after_failed_siso_setup(self) -> None:
        result = run_zsh(
            "_src_dir=$(mktemp -d); _out_dir=${_src_dir}/out/Default; "
            "___helium_setup_python(){ echo python; }; "
            "___helium_setup_siso(){ echo siso; return 8; }; "
            "___helium_configure_inner"
        )
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["python", "siso"])

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
