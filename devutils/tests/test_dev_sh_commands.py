"""Black-box checks for the small public ``he`` development loop."""

from __future__ import annotations

import subprocess
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

    def test_menu_leads_with_public_development_loop(self) -> None:
        result = run_zsh("he")
        self.assertEqual(result.returncode, 0)
        self.assertIn("bootstrap --approved - one-time cold browser build", result.stderr)
        self.assertIn("check - validate and strictly apply", result.stderr)
        self.assertIn("dev [profile options] - incrementally rebuild", result.stderr)
        self.assertNotIn("presetup", result.stderr)

        advanced = run_zsh("he help --advanced")
        self.assertEqual(advanced.returncode, 0)
        self.assertIn("presetup", advanced.stderr)

    def test_reset_refuses_without_explicit_warm_output_approval(self) -> None:
        result = run_zsh("he reset")
        self.assertEqual(result.returncode, 2)
        self.assertIn("reset preserves the warm build", result.stderr)

    def test_dev_runs_check_configure_relink_bundle_and_launch(self) -> None:
        result = run_zsh(
            "___helium_check(){ echo check; }; "
            "___helium_configure(){ echo configure; }; "
            "___helium_relink(){ echo relink:$*; }; "
            "___helium_dev_bundle(){ echo bundle; }; "
            "___helium_run(){ echo run:$*; }; "
            "he dev --isolated smoke"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["check", "configure", "relink:--resources", "bundle", "run:--isolated smoke"],
        )

    def test_bootstrap_requires_approval_before_setup(self) -> None:
        result = run_zsh(
            "___helium_setup(){ echo setup; }; "
            "___helium_build_full(){ echo build:$*; }; "
            "___helium_dev_bundle(){ echo bundle; }; "
            "he bootstrap"
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("setup", result.stdout)


if __name__ == "__main__":
    unittest.main()
