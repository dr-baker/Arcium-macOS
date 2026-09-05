"""Deterministic contract tests for the safe Helium Dev runtime primitives."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import helium_dev_runtime as runtime  # noqa: E402


class RuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.registry = self.root / "registry"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def profile(self, mode: str = "isolated", name: str | None = "test") -> runtime.ProfileSpec:
        return runtime.resolve_profile(mode, name, home=self.home)

    def manifest(self, spec: runtime.ProfileSpec) -> dict[str, object]:
        return runtime.build_manifest(
            ok=True,
            run_id="run-1",
            action="run",
            main_pid=123,
            process_count=2,
            started_at="1970-01-01T00:01:40+00:00",
            worktree="/worktree",
            source_dir="/source",
            app_path="/app",
            executable_path="/app/Contents/MacOS/Helium",
            profile=spec,
            component_path="/component",
            component_sha256="abc",
            component_mtime=99.0,
            artifact_state="current",
            manifest_path="/registry/runs/isolated--test.json",
        )

    def test_normal_profile_is_the_historic_dev_profile(self) -> None:
        spec = runtime.resolve_profile(home=self.home)
        self.assertEqual(spec.mode, "normal")
        self.assertEqual(
            spec.user_data_dir,
            self.home / "Library/Application Support/net.imput.helium.dev",
        )
        self.assertEqual(spec.profile_directory, "Default")

    def test_live_singleton_owner_ignores_stale_profile_locks(self) -> None:
        spec = runtime.resolve_profile(home=self.home)
        spec.user_data_dir.mkdir(parents=True)
        (spec.user_data_dir / "SingletonLock").symlink_to("mac.lan-123")
        with unittest.mock.patch("helium_dev_runtime.os.kill") as kill:
            self.assertEqual(runtime.live_singleton_owner(spec), 123)
            kill.assert_called_once_with(123, 0)
        with unittest.mock.patch(
            "helium_dev_runtime.os.kill", side_effect=ProcessLookupError
        ):
            self.assertIsNone(runtime.live_singleton_owner(spec))

    def test_named_profiles_are_safe_and_fresh_is_create_only(self) -> None:
        isolated = self.profile("isolated", "one.two")
        self.assertIn("profiles/isolated/one.two", str(isolated.user_data_dir))
        fresh = self.profile("fresh", "once")
        runtime.prepare_profile(fresh)
        with self.assertRaisesRegex(runtime.RuntimeInputError, "already exists"):
            runtime.prepare_profile(fresh)
        for unsafe in ("../x", "", "has space", "/tmp/x", "."):
            with self.assertRaises(runtime.RuntimeInputError):
                runtime.normalize_profile_name(unsafe)

    def test_argument_conflicts_and_flag_normalization(self) -> None:
        with self.assertRaisesRegex(runtime.RuntimeInputError, "user-data-dir"):
            runtime.parse_runtime_arguments(["--user-data-dir=/release"])
        with self.assertRaisesRegex(runtime.RuntimeInputError, "exactly one"):
            runtime.parse_runtime_arguments(["--isolated", "a", "--fresh=b"])
        with self.assertRaisesRegex(runtime.RuntimeInputError, "fixed to Default"):
            runtime.parse_runtime_arguments(["--profile-directory=A"])
        parsed = runtime.parse_runtime_arguments(["--isolated=one", "--incognito"])
        spec = runtime.resolve_profile(
            parsed.profile_mode,
            parsed.profile_name,
            home=self.home,
            profile_directory=parsed.profile_directory,
        )
        launch = runtime.launch_arguments(spec, parsed.passthrough)
        self.assertIn("--use-mock-keychain", launch)
        self.assertIn("--no-first-run", launch)
        self.assertIn("--disable-session-crashed-bubble", launch)
        self.assertIn("--incognito", launch)
        self.assertEqual(sum(item.startswith("--user-data-dir=") for item in launch), 1)

    def test_named_profiles_seed_from_installed_by_default(self) -> None:
        parsed = runtime.parse_runtime_arguments(["--isolated", "peek"])
        self.assertEqual(parsed.seed_from, "installed")
        self.assertEqual(
            runtime.profile_seed_source(parsed.seed_from, home=self.home),
            self.home / "Library/Application Support/net.imput.helium",
        )

        parsed = runtime.parse_runtime_arguments(
            ["--fresh=peek", "--seed-from", "dev"]
        )
        self.assertEqual(parsed.seed_from, "dev")
        self.assertNotIn("--seed-from", parsed.passthrough)
        self.assertEqual(
            runtime.profile_seed_source(parsed.seed_from, home=self.home),
            self.home / "Library/Application Support/net.imput.helium.dev",
        )

        with self.assertRaisesRegex(runtime.RuntimeInputError, "requires"):
            runtime.parse_runtime_arguments(["--seed-from=installed"])
        with self.assertRaisesRegex(runtime.RuntimeInputError, "installed, dev, or empty"):
            runtime.parse_runtime_arguments(
                ["--isolated", "peek", "--seed-from=unknown"]
            )

    def test_production_feature_bundle_is_enabled_once_by_default(self) -> None:
        spec = self.profile()
        launch = runtime.launch_arguments(spec)
        enabled = [item for item in launch if item.startswith("--enable-features=")]
        disabled = [item for item in launch if item.startswith("--disable-features=")]
        self.assertEqual(enabled, ["--enable-features=HeliumFavoritesAndPins"])
        self.assertEqual(disabled, ["--disable-features=DialMediaRouteProvider"])
        self.assertEqual(
            runtime.effective_feature_list(),
            ("HeliumFavoritesAndPins",),
        )
        self.assertNotIn(
            "BrowserInitiatedAutomaticPictureInPicture",
            runtime.effective_feature_list(),
        )

    def test_feature_switches_merge_deduplicate_and_honor_explicit_disable(self) -> None:
        spec = self.profile()
        launch = runtime.launch_arguments(
            spec,
            (
                "--enable-features=CustomFeature,HeliumFavoritesAndPins",
                "--enable-features",
                "CustomFeature",
                "--disable-features=OtherFeature,CustomFeature",
                "--incognito",
            ),
        )
        self.assertEqual(
            [item for item in launch if item.startswith("--enable-features=")],
            ["--enable-features=HeliumFavoritesAndPins"],
        )
        self.assertEqual(
            [item for item in launch if item.startswith("--disable-features=")],
            ["--disable-features=DialMediaRouteProvider,OtherFeature,CustomFeature"],
        )
        self.assertEqual(launch[-1], "--incognito")
        self.assertEqual(
            runtime.effective_feature_list(
                ("--enable-features=CustomFeature", "--disable-features=CustomFeature")
            ),
            ("HeliumFavoritesAndPins",),
        )

    def test_unsafe_experimental_feature_cannot_enter_production_bundle(self) -> None:
        spec = self.profile()
        for feature in (
            "BrowserInitiatedAutomaticPictureInPicture",
            "BrowserInitiatedAutomaticPictureInPicture<TrialGroup",
        ):
            with self.assertRaisesRegex(runtime.RuntimeInputError, "experimental feature"):
                runtime.launch_arguments(spec, ("--enable-features=" + feature,))
        launch = runtime.launch_arguments(
            spec,
            ("--disable-features=BrowserInitiatedAutomaticPictureInPicture",),
        )
        self.assertNotIn(
            "BrowserInitiatedAutomaticPictureInPicture",
            next(item for item in launch if item.startswith("--enable-features=")),
        )

    def test_feature_switches_are_rejected_when_missing_values(self) -> None:
        spec = self.profile()
        for argument in ("--enable-features", "--disable-features", "--enable-features="):
            with self.assertRaises(runtime.RuntimeInputError):
                runtime.launch_arguments(spec, (argument,))

    def test_manifest_is_fixed_schema_atomic_and_private(self) -> None:
        spec = self.profile()
        path = runtime.manifest_path_for(spec, self.registry)
        manifest = self.manifest(spec)
        manifest["manifest_path"] = str(path)
        runtime.write_manifest_atomic(path, manifest)
        loaded = runtime.read_manifest(path)
        self.assertEqual(loaded, manifest)
        self.assertEqual(set(loaded or ()), set(runtime.MANIFEST_FIELDS))
        self.assertEqual(loaded["feature_bundle"], runtime.PRODUCTION_FEATURE_BUNDLE)
        self.assertEqual(loaded["effective_features"], ["HeliumFavoritesAndPins"])
        self.assertEqual(loaded["disabled_features"], ["DialMediaRouteProvider"])
        self.assertNotIn("BrowserInitiatedAutomaticPictureInPicture", json.dumps(loaded))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(list(path.parent.glob("*.tmp")))
        malformed = dict(manifest)
        malformed["private_child_pids"] = [1]
        with self.assertRaisesRegex(runtime.RuntimeInputError, "schema"):
            runtime.write_manifest_atomic(path, malformed)
        with self.assertRaisesRegex(runtime.RuntimeInputError, "started_at"):
            runtime.build_manifest(
                ok=True,
                run_id="run-2",
                action="status",
                main_pid=None,
                process_count=0,
                started_at=100.0,
                worktree=None,
                source_dir=None,
                app_path=None,
                executable_path=None,
                profile=spec,
            )

    def test_manifest_can_report_the_effective_user_feature_overrides(self) -> None:
        manifest = runtime.build_manifest(
            ok=True,
            run_id="run-2",
            action="run",
            main_pid=123,
            process_count=1,
            started_at="1970-01-01T00:01:40+00:00",
            worktree="/worktree",
            source_dir="/source",
            app_path="/app",
            executable_path="/app/Contents/MacOS/Helium",
            profile=self.profile(),
            passthrough=("--enable-features=CustomFeature",),
        )
        self.assertEqual(manifest["feature_bundle"], runtime.PRODUCTION_FEATURE_BUNDLE)
        self.assertEqual(
            manifest["effective_features"],
            ["HeliumFavoritesAndPins", "CustomFeature"],
        )
        self.assertEqual(manifest["disabled_features"], ["DialMediaRouteProvider"])

    def test_lock_live_ownership_and_stale_file_overwrite(self) -> None:
        spec = self.profile()
        lock = runtime.acquire_profile_lock(spec, root=self.registry, run_id="first", pid=11)
        with self.assertRaises(runtime.LockBusyError):
            runtime.acquire_profile_lock(spec, root=self.registry, run_id="second", pid=12)
        self.assertTrue(lock.release())
        stale = runtime.lock_path_for(spec, self.registry)
        stale.write_text(json.dumps({"pid": 999, "run_id": "stale"}), encoding="utf-8")
        acquired = runtime.acquire_profile_lock(spec, root=self.registry, run_id="new", pid=12)
        self.assertEqual(json.loads(stale.read_text()) ["run_id"], "new")
        self.assertTrue(acquired.release())

    def test_exact_main_process_discovery_rejects_lookalikes_and_children(self) -> None:
        executable = "/Work/Helium Dev.app/Contents/MacOS/Helium"
        profile = "/Profiles/Application Support/one"
        text = "\n".join(
            (
                "  10 %s --user-data-dir=%s --no-first-run" % (executable, profile),
                "  11 %s --user-data-dir=%s --type=renderer" % (executable, profile),
                "  12 %s --user-data-dir=/Profiles/Application Support/two" % executable,
                "  13 /Other/Helium --user-data-dir=%s" % profile,
            )
        )
        cohort = runtime.discover_chromium_processes(
            text, executable_path=executable, user_data_dir=profile
        )
        self.assertEqual(cohort.main_pid, 10)
        self.assertEqual(cohort.pids, (10, 11))
        duplicate = text + "\n  14 %s --user-data-dir=%s" % (
            executable,
            profile,
        )
        self.assertIsNone(
            runtime.discover_chromium_processes(
                duplicate, executable_path=executable, user_data_dir=profile
            ).main_pid
        )

    def test_artifact_freshness_states(self) -> None:
        component = self.root / "component"
        component.write_bytes(b"component")
        self.assertEqual(
            runtime.classify_artifact_state(
                component_path=component,
                expected_component_path=component,
                component_mtime=100,
                process_started_at=99,
            ),
            "process-predates-artifact",
        )
        self.assertEqual(
            runtime.classify_artifact_state(
                component_path=component,
                expected_component_path=component,
                component_mtime=100,
                process_started_at=100,
            ),
            "current",
        )
        self.assertEqual(
            runtime.classify_artifact_state(
                component_path=component,
                expected_component_path=self.root / "other",
            ),
            "wrong-component-path",
        )
        self.assertEqual(
            runtime.classify_artifact_state(
                component_path=component, expected_component_path=component
            ),
            "unverified",
        )

    def test_fresh_restart_reuses_only_a_real_directory_and_rejects_symlinks(self) -> None:
        fresh = self.profile("fresh", "restartable")
        runtime.prepare_profile(fresh)
        self.assertEqual(runtime.prepare_profile(fresh, allow_existing_fresh=True), fresh)
        linked = self.profile("isolated", "linked")
        linked.user_data_dir.parent.mkdir(parents=True, exist_ok=True)
        linked.user_data_dir.symlink_to(self.root / "other")
        with self.assertRaisesRegex(runtime.RuntimeInputError, "must not be a symlink"):
            runtime.prepare_profile(linked)

    def test_stop_revalidates_scope_before_sigterm(self) -> None:
        executable = "/Work/Helium"
        profile = "/Profiles/one"
        ps_text = "\n".join(
            (
                "20 %s --user-data-dir=%s" % (executable, profile),
                "21 %s --user-data-dir=%s --type=renderer" % (executable, profile),
                "22 %s --user-data-dir=/other" % executable,
            )
        )
        signalled: list[tuple[int, int]] = []
        result = runtime.stop_scoped_processes(
            lambda: ps_text,
            lambda pid, sig: signalled.append((pid, sig)),
            executable_path=executable,
            user_data_dir=profile,
            expected_main_pid=20,
        )
        self.assertTrue(result["ok"])
        self.assertEqual([pid for pid, _sig in signalled], [20, 21])
        with self.assertRaisesRegex(runtime.RuntimeInputError, "no longer matches"):
            runtime.build_stop_plan(
                ps_text,
                executable_path=executable,
                user_data_dir=profile,
                expected_main_pid=999,
            )

    def test_structured_result_is_json_ready_and_stdout_free(self) -> None:
        result = runtime.structured_result(ok=False, action="status", error="unverified")
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertFalse(result["ok"])
if __name__ == "__main__":
    unittest.main()
