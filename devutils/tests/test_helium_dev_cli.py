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
from unittest.mock import MagicMock, patch


WORKTREE = Path(__file__).resolve().parents[2]
CLI = WORKTREE / "devutils" / "helium_dev.py"
sys.path.insert(0, str(WORKTREE / "devutils"))
import helium_dev  # noqa: E402
import helium_dev_runtime as runtime  # noqa: E402
from replay_contract import ReplayError  # noqa: E402


class HeliumDevCliTests(unittest.TestCase):
    def setUp(self) -> None:
        packaged = patch("helium_dev.require_current_packaged_build")
        self.addCleanup(packaged.stop)
        self.packaged_build = packaged.start()

    def test_cli_passes_external_build_root_to_runtime(self) -> None:
        with patch(
            "helium_dev.runtime_action",
            return_value={"ok": True, "action": "status"},
        ) as action:
            with redirect_stdout(io.StringIO()):
                code = helium_dev.main(
                    [
                        "--root",
                        "/worktree",
                        "--build-root",
                        "/Volumes/T9/ArciumBuild/build",
                        "status",
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)
        action.assert_called_once_with(
            "status",
            "/worktree",
            (),
            build_root="/Volumes/T9/ArciumBuild/build",
        )

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

    def test_approved_build_full_requires_replay_before_building(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "helium_dev.HeliumDevBuilder"
        ) as builder, patch(
            "helium_dev.require_current_replay_proof",
            side_effect=ReplayError("run he replay"),
        ):
            with self.assertRaisesRegex(ReplayError, "run he replay"):
                helium_dev.build_action(
                    "build-full",
                    temporary,
                    ("--approved",),
                )
        builder.return_value.build_full.assert_not_called()

    def test_run_requires_current_packaged_build(self) -> None:
        self.packaged_build.side_effect = helium_dev.ReceiptError(
            "packaged build proof is stale"
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(helium_dev.ReceiptError, "stale"):
                helium_dev.runtime_action("run", temporary, ())

    def test_missing_named_profile_seeds_from_installed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            source = (
                home / "Library" / "Application Support" / "net.imput.helium"
            )
            source.mkdir(parents=True)
            (source / "Local State").write_text("installed", encoding="utf-8")
            profile = helium_dev.resolve_profile(
                "isolated", "peek", home=home
            )
            with patch("helium_dev._ps_snapshot", return_value=""):
                helium_dev._prepare_selected_profile(
                    profile, "installed", action="run", home=home
                )
            self.assertEqual(
                (profile.user_data_dir / "Local State").read_text(encoding="utf-8"),
                "installed",
            )

            (profile.user_data_dir / "Local State").write_text(
                "special build", encoding="utf-8"
            )
            with patch(
                "helium_dev._ps_snapshot",
                return_value="123 /Applications/Helium.app/Contents/MacOS/Helium",
            ):
                helium_dev._prepare_selected_profile(
                    profile, "installed", action="run", home=home
                )
            self.assertEqual(
                (profile.user_data_dir / "Local State").read_text(encoding="utf-8"),
                "special build",
            )

    def test_profile_seed_refuses_a_running_source_browser(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            source = (
                home / "Library" / "Application Support" / "net.imput.helium"
            )
            source.mkdir(parents=True)
            profile = helium_dev.resolve_profile("isolated", "peek", home=home)
            ps_text = "123 /Applications/Helium.app/Contents/MacOS/Helium"
            with patch("helium_dev._ps_snapshot", return_value=ps_text):
                with self.assertRaisesRegex(helium_dev.HarnessError, "matching PIDs: 123"):
                    helium_dev._validate_profile_seed(
                        profile, "installed", home=home
                    )
            self.assertFalse(profile.user_data_dir.exists())

    def test_relink_artifact_probe_uses_the_named_bundle_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "helium_dev.HeliumDevBuilder"
        ) as builder, patch(
            "helium_dev.ensure_gclient_identity"
        ), patch(
            "helium_dev.require_current_replay_proof"
        ), patch(
            "helium_dev.invalidate_execution"
        ), patch(
            "helium_dev.resolve_dev_identity", wraps=helium_dev.resolve_dev_identity
        ) as resolve_identity, patch(
            "helium_dev._artifact_status_for_root"
        ) as artifact_status:
            result = MagicMock(ok=False)
            builder.return_value.relink.side_effect = lambda **kwargs: (
                kwargs["artifact_status_probe"](), result
            )[1]
            helium_dev.build_action(
                "relink",
                temporary,
                ("--resources", "--isolated", "peek"),
            )

        identity = resolve_identity("isolated", "peek")
        artifact_status.assert_called_once_with(
            Path(temporary).resolve(), None, identity=identity
        )

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

    def test_manifest_carries_custom_effective_features_from_launch_passthrough(self) -> None:
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
            profile = helium_dev.resolve_profile("isolated", "features", home=root / "home")
            ps_text = f"101 {executable} --user-data-dir={profile.user_data_dir}"
            with patch("helium_dev._quilt_top", return_value=(None, [])):
                manifest = helium_dev._manifest_for(
                    paths=paths,
                    profile=profile,
                    action="run",
                    cohort_text=ps_text,
                    run_id="run",
                    manifest_path=root / "manifest.json",
                    passthrough=("--enable-features=CustomFeature",),
                )
        self.assertEqual(manifest["feature_bundle"], runtime.PRODUCTION_FEATURE_BUNDLE)
        self.assertEqual(
            manifest["effective_features"],
            ["HeliumFavoritesAndPins", "CustomFeature"],
        )
        self.assertEqual(manifest["disabled_features"], ["DialMediaRouteProvider"])

    def test_status_manifest_inherits_features_from_prior_run(self) -> None:
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
            profile = helium_dev.resolve_profile("isolated", "prior", home=root / "home")
            manifest_path = root / "manifest.json"
            prior = runtime.build_manifest(
                ok=True,
                run_id="prior",
                action="run",
                main_pid=101,
                process_count=1,
                started_at="1970-01-01T00:01:40+00:00",
                worktree=root,
                source_dir=root,
                app_path=paths.app_path,
                executable_path=paths.executable_path,
                profile=profile,
                passthrough=("--enable-features=CustomFeature",),
                manifest_path=manifest_path,
            )
            runtime.write_manifest_atomic(manifest_path, prior)
            ps_text = ""
            with patch("helium_dev._quilt_top", return_value=(None, [])):
                manifest = helium_dev._manifest_for(
                    paths=paths,
                    profile=profile,
                    action="status",
                    cohort_text=ps_text,
                    run_id="status",
                    manifest_path=manifest_path,
                )
        self.assertEqual(
            manifest["effective_features"],
            ["HeliumFavoritesAndPins", "CustomFeature"],
        )
        self.assertEqual(manifest["disabled_features"], ["DialMediaRouteProvider"])


if __name__ == "__main__":
    unittest.main()
