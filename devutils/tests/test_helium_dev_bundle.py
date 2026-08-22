"""Focused tests for worktree-local Helium Dev bundle packaging."""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
import helium_dev  # noqa: E402
from helium_dev_bundle import BundleError, package_dev_bundle  # noqa: E402


class HeliumDevBundleTests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, Path, Path, dict[str, bytes]]:
        temporary = Path(tempfile.mkdtemp(prefix="helium-dev-bundle-test-"))
        self.addCleanup(lambda: shutil.rmtree(temporary, ignore_errors=True))
        root = temporary / "worktree"
        source = root / "build" / "src"
        output = source / "out" / "Default"
        app = output / "Helium.app"
        contents = app / "Contents"
        executable = contents / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"release executable")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        framework = (
            contents
            / "Frameworks"
            / "Helium Framework.framework"
            / "Versions"
            / "1"
        )
        helper = framework / "Helpers" / "Helium Helper.app" / "Contents"
        helper.mkdir(parents=True)
        framework.mkdir(parents=True, exist_ok=True)
        plists = {
            contents / "Info.plist": {
                "CFBundleExecutable": "Helium",
                "CFBundleIdentifier": "net.imput.helium",
                "CFBundleDisplayName": "Helium",
                "CFBundleName": "Helium",
            },
            framework / "Resources" / "Info.plist": {
                "CFBundleIdentifier": "net.imput.helium.framework",
                "CFBundleName": "Helium Framework",
            },
            helper / "Info.plist": {
                "CFBundleExecutable": "Helium Helper",
                "CFBundleIdentifier": "net.imput.helium.helper",
                "CFBundleDisplayName": "Helium Helper",
                "CFBundleName": "Helium Helper",
            },
        }
        for path, info in plists.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                plistlib.dump(info, handle)
        output.mkdir(parents=True, exist_ok=True)
        component = output / "libchrome_dll.dylib"
        component.write_bytes(b"component")
        graph = output / "build.ninja"
        graph.write_text("graph\n", encoding="utf-8")
        args = output / "args.gn"
        args.write_text("target_cpu = \"arm64\"\n", encoding="utf-8")
        # Make the freshness relationship deterministic even on filesystems
        # with coarse timestamp resolution.
        graph_time = 1_700_000_000_000_000_000
        os.utime(graph, ns=(graph_time, graph_time))
        for path in (executable, component):
            os.utime(path, ns=(graph_time + 2, graph_time + 2))
        source_bytes = {str(path.relative_to(app)): path.read_bytes() for path in plists}
        return root, app, output, source_bytes

    def test_package_rewrites_only_copy_and_keeps_executable_names(self) -> None:
        root, source_app, output, source_bytes = self._fixture()
        signer_calls: list[Path] = []

        def signer(path: Path) -> None:
            signer_calls.append(path)

        def no_clone(*_args: object, **_kwargs: object) -> object:
            raise subprocess.CalledProcessError(1, "cp")

        result = package_dev_bundle(root, copy_runner=no_clone, signer=signer)
        destination = output / "Helium Dev.app"
        self.assertEqual(result["copy_method"], "fallback-copy")
        self.assertEqual(result["bundle_identifier"], "net.imput.helium.dev")
        self.assertEqual(result["display_name"], "Helium Dev")
        self.assertEqual(len(signer_calls), 1)
        self.assertEqual(signer_calls[0].name, destination.name)
        self.assertTrue(signer_calls[0].parent.name.startswith(".helium-dev-bundle-"))
        self.assertTrue(destination.is_dir())
        self.assertTrue((destination / "Contents" / "MacOS" / "Helium").is_file())

        copied_ids: list[str] = []
        copied_executables: dict[str, str] = {}
        for path in sorted(destination.rglob("Info.plist")):
            with path.open("rb") as handle:
                info = plistlib.load(handle)
            if isinstance(info.get("CFBundleIdentifier"), str):
                copied_ids.append(info["CFBundleIdentifier"])
            if isinstance(info.get("CFBundleExecutable"), str):
                copied_executables[str(path.relative_to(destination))] = info["CFBundleExecutable"]
            if isinstance(info.get("CFBundleName"), str):
                self.assertTrue(info["CFBundleName"].endswith(" Dev"))
        self.assertTrue(copied_ids)
        self.assertTrue(all(value.endswith(".dev") for value in copied_ids))
        self.assertEqual(copied_executables["Contents/Info.plist"], "Helium")
        self.assertEqual(
            copied_executables[
                "Contents/Frameworks/Helium Framework.framework/Versions/1/Helpers/"
                "Helium Helper.app/Contents/Info.plist"
            ],
            "Helium Helper",
        )
        for relative_path, content in source_bytes.items():
            self.assertEqual((source_app / relative_path).read_bytes(), content)

    def test_stale_source_and_existing_destination_fail_closed(self) -> None:
        root, _source_app, output, _source_bytes = self._fixture()
        graph = output / "build.ninja"
        newer = 1_800_000_000_000_000_000
        os.utime(graph, ns=(newer, newer))
        with self.assertRaisesRegex(BundleError, "older than build.ninja"):
            package_dev_bundle(root, signer=lambda _path: None)
        self.assertFalse((output / "Helium Dev.app").exists())

        root, _source_app, output, _source_bytes = self._fixture()
        (output / "Helium Dev.app").mkdir()
        with self.assertRaisesRegex(BundleError, "refusing to overwrite"):
            package_dev_bundle(root, signer=lambda _path: None)

    def test_failed_signing_cleans_owned_staging_directory(self) -> None:
        root, _source_app, output, _source_bytes = self._fixture()

        def signer(_path: Path) -> None:
            raise BundleError("signature test failure")

        with self.assertRaisesRegex(BundleError, "signature test failure"):
            package_dev_bundle(root, signer=signer)
        self.assertFalse((output / "Helium Dev.app").exists())
        self.assertEqual(list(output.glob(".helium-dev-bundle-*")), [])

    def test_run_preflight_does_not_launch_or_create_profile(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="helium-preflight-test-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        executable = root / "Helium Dev.app" / "Contents" / "MacOS" / "Helium"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fixture")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        component = root / "libchrome_dll.dylib"
        component.write_bytes(b"component")
        paths = helium_dev.WorktreePaths(
            worktree=root,
            source_dir=root,
            out_dir=root,
            app_path=executable.parents[2],
            executable_path=executable,
            bundle_identifier="net.imput.helium.dev",
            component_path=component,
            siso_path=root / "siso",
            autoninja_path=root / "autoninja.py",
        )
        with patch("helium_dev.resolve_worktree_paths", return_value=paths), patch(
            "helium_dev._ps_snapshot", return_value=""
        ), patch("helium_dev.subprocess.Popen") as popen:
            result = helium_dev.runtime_action(
                "run",
                str(root),
                [
                    "--preflight",
                    "--fresh",
                    "preflight",
                    "--enable-features=CustomFeature",
                ],
                home=root / "home",
                registry_root=root / "registry",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "run-preflight")
        self.assertEqual(result["process_state"], "not-running")
        self.assertIn("launch-not-started", result["proof_gates"])
        self.assertEqual(result["feature_bundle"], "personal-production")
        self.assertEqual(
            result["effective_features"],
            ["HeliumFavoritesAndPins", "CustomFeature"],
        )
        self.assertEqual(result["disabled_features"], ["DialMediaRouteProvider"])
        popen.assert_not_called()
        self.assertFalse((root / "home").exists())


if __name__ == "__main__":
    unittest.main()
