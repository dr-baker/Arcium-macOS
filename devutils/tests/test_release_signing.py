"""Exercise release packaging with fake signing and notarization tools."""

import base64
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "sign_and_package_app.sh"
CI_SCRIPT = SCRIPT.parent / ".github/scripts/github_prepare_artifacts.sh"
PREPARE_RELEASE_SCRIPT = SCRIPT.parent / ".github/scripts/github_prepare_release.sh"
SOURCE_APP = "out/Default/Helium.app"
RELEASE_APP = "out/Default/Arcium.app"
SETTINGS_LIBRARY = f"{RELEASE_APP}/Contents/Frameworks/libArciumSettingsUI.dylib"
SOURCE_SETTINGS_LIBRARY = (
    f"{SOURCE_APP}/Contents/Frameworks/libArciumSettingsUI.dylib"
)


class ReleaseSigningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arcium signing ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.trace = self.root / "calls.jsonl"
        shutil.copy2(SCRIPT, self.root / SCRIPT.name)
        for name in (
            "helium-chromium/chromium_version.txt",
            "helium-chromium/revision.txt",
            "revision.txt",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        resource_config = self.root / "resources/dmg.json"
        resource_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCRIPT.parent / "resources/dmg.json", resource_config)
        source_app = self.root / SOURCE_APP
        source_contents = source_app / "Contents"
        source_frameworks = source_contents / "Frameworks"
        source_frameworks.mkdir(parents=True)
        (source_frameworks / "libArciumSettingsUI.dylib").write_bytes(b"settings")
        self.source_info = source_contents / "Info.plist"
        with self.source_info.open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": "Helium",
                    "CFBundleIdentifier": "net.imput.helium",
                    "CFBundleDisplayName": "Helium",
                    "CFBundleName": "Helium",
                },
                handle,
            )
        helper_info = (
            source_frameworks / "Helium Helper.app" / "Contents" / "Info.plist"
        )
        helper_info.parent.mkdir(parents=True)
        with helper_info.open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": "Helium Helper",
                    "CFBundleIdentifier": "net.imput.helium.helper",
                },
                handle,
            )
        self.original_source_info = self.source_info.read_bytes()
        (self.root / "devutils").symlink_to(SCRIPT.parent / "devutils")
        self.environment = {
            "PATH": f"{self.tools}:{os.defpath}",
            "TMPDIR": str(self.root),
            "OUT_DMG_PATH": str(self.root / "release.dmg"),
            "EXPECTED_RELEASE_APP": RELEASE_APP,
            "CALL_TRACE": str(self.trace),
            "MACOS_CERTIFICATE_NAME": "Developer ID Application: Fixture",
            "PROD_MACOS_NOTARIZATION_TEAM_ID": "FIXTURETEAM",
            "PROD_MACOS_NOTARIZATION_APPLE_ID": "fixture@example.invalid",
            "PROD_MACOS_NOTARIZATION_PWD": "fixture-password-must-not-be-logged",
        }
        tool = f"#!{sys.executable}\n" + r'''
import json
import os
import plistlib
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALL_TRACE"], "a") as trace:
    trace.write(json.dumps([name, *args]) + "\n")
if name == "greadlink":
    print(Path(args[-1]).resolve())
elif name == "python3":
    if args and Path(args[0]).name in ("release_bundle.py", "release_dmg.py"):
        os.execv(sys.executable, [sys.executable, *args])
    print("1.0.0")
elif name == "codesign":
    if args[-1] == os.environ["EXPECTED_RELEASE_APP"] and "--sign" in args:
        info_path = Path(args[-1]) / "Contents" / "Info.plist"
        with info_path.open("rb") as info_file:
            if plistlib.load(info_file).get("CFBundleIdentifier") != "net.imput.arcium":
                sys.exit(9)
        preferences = Path(args[-1]) / "Contents/Resources/initial_preferences"
        if not json.loads(preferences.read_text())["helium"]["browser"]["mru_tab_cycling"]:
            sys.exit(12)
    if args[-1] == os.environ.get("FAIL_SIGN_TARGET") and "--sign" in args:
        sys.exit(7)
    if args[-1] == os.environ.get("FAIL_VERIFY_TARGET") and "--verify" in args:
        sys.exit(8)
elif name == "appdmg":
    with Path(args[0]).open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if (
        config.get("title") != "Arcium"
        or not config.get("icon", "").endswith("Arcium.app/Contents/Resources/app.icns")
        or Path(config["contents"][0]["path"]).name != "Arcium.app"
        or config["contents"][1]["path"] != "/Applications"
        or not Path(config["background"]).is_file()
    ):
        sys.exit(10)
    app_path = Path(config["contents"][0]["path"])
    if not app_path.is_dir():
        sys.exit(11)
    Path(args[-1]).touch()
elif name == "ditto":
    Path(args[-1]).touch()
elif name == "zstd":
    Path(args[args.index("-o") + 1]).write_bytes(sys.stdin.buffer.read())
elif name in ("md5sum", "sha1sum", "sha256sum"):
    size = {"md5sum": 32, "sha1sum": 40, "sha256sum": 64}[name]
    print(f'{"a" * size}  {args[-1]}')
'''
        for name in (
            "greadlink", "xattr", "codesign", "ditto", "xcrun", "appdmg",
            "security", "python3", "gsync", "zstd", "md5sum", "sha1sum",
            "sha256sum",
        ):
            path = self.tools / name
            path.write_text(tool)
            path.chmod(0o755)

    def run_packaging(self, **overrides):
        environment = self.environment | overrides
        result = subprocess.run(
            ["/bin/bash", "-x", str(self.root / SCRIPT.name)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        calls = (
            [json.loads(line) for line in self.trace.read_text().splitlines()]
            if self.trace.exists()
            else []
        )
        return result, calls

    def test_signs_and_verifies_settings_before_sealing_app(self):
        result, calls = self.run_packaging()
        self.assertEqual(0, result.returncode, result.stderr)
        settings_sign = next(
            i for i, call in enumerate(calls)
            if call[0] == "codesign" and "--sign" in call
            and call[-1] == SETTINGS_LIBRARY
        )
        settings_verify = next(
            i for i, call in enumerate(calls)
            if call[0] == "codesign" and "--verify" in call
            and call[-1] == SETTINGS_LIBRARY
        )
        app_sign = next(
            i for i, call in enumerate(calls)
            if call[0] == "codesign" and "--sign" in call and call[-1] == RELEASE_APP
        )
        self.assertIn(self.environment["MACOS_CERTIFICATE_NAME"], calls[settings_sign])
        self.assertLess(settings_sign, settings_verify)
        self.assertLess(settings_verify, app_sign)
        app_call = calls[app_sign]
        self.assertEqual(
            str(self.root / "entitlements/app-entitlements.plist"),
            app_call[app_call.index("--entitlements") + 1],
        )
        self.assertTrue((self.root / "release.dmg").is_file())
        self.assertEqual(self.source_info.read_bytes(), self.original_source_info)
        self.assertFalse((self.root / RELEASE_APP).exists())
        self.assertTrue((self.root / SOURCE_SETTINGS_LIBRARY).is_file())
        identifiers = [
            call[call.index("--identifier") + 1]
            for call in calls
            if call[0] == "codesign" and "--identifier" in call
        ]
        self.assertIn("net.imput.arcium.settings", identifiers)
        self.assertIn("net.imput.arcium.framework", identifiers)
        self.assertIn("net.imput.arcium", identifiers)
        self.assertFalse(
            any(value.startswith("net.imput.helium") for value in identifiers)
        )
        self.assertNotIn(
            self.environment["PROD_MACOS_NOTARIZATION_PWD"],
            result.stdout + result.stderr,
        )

    def test_missing_settings_stops_before_signing_or_packaging(self):
        (self.root / SOURCE_SETTINGS_LIBRARY).unlink()
        result, calls = self.run_packaging()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("SettingsUI library is missing", result.stderr)
        self.assertFalse(any(call[0] in ("codesign", "xcrun", "appdmg") for call in calls))

    def test_settings_signing_failure_stops_notarization_and_packaging(self):
        result, calls = self.run_packaging(FAIL_SIGN_TARGET=SETTINGS_LIBRARY)
        self.assertEqual(7, result.returncode)
        self.assertFalse(any(call[0] in ("xcrun", "appdmg") for call in calls))
        self.assertFalse(any(call[0] == "codesign" and call[-1] == RELEASE_APP for call in calls))

    def test_settings_verification_failure_stops_notarization_and_packaging(self):
        result, calls = self.run_packaging(FAIL_VERIFY_TARGET=SETTINGS_LIBRARY)
        self.assertEqual(8, result.returncode)
        self.assertFalse(any(call[0] in ("xcrun", "appdmg") for call in calls))

    def test_adhoc_package_does_not_contact_notary(self):
        result, calls = self.run_packaging(MACOS_CERTIFICATE_NAME="")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(call[0] == "xcrun" for call in calls))
        self.assertTrue((self.root / "release.dmg").is_file())

    def test_release_download_names_match_arcium_dmg_names(self):
        caller = self.root / PREPARE_RELEASE_SCRIPT.name
        shutil.copy2(PREPARE_RELEASE_SCRIPT, caller)
        output = self.root / "github-output.txt"
        result = subprocess.run(
            ["/bin/bash", "-x", str(caller)],
            cwd=self.root,
            env=self.environment | {"GITHUB_OUTPUT": str(output)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "x64_file_name=arcium_1.0.0_x86_64-macos.dmg\n"
            "arm64_file_name=arcium_1.0.0_arm64-macos.dmg\n"
            "release_tag_version=1.0.0\n"
            "release_name=Arcium 1.0.0\n",
            output.read_text(),
        )

    def test_ci_caller_does_not_trace_signing_credentials(self):
        caller = self.root / CI_SCRIPT.name
        shutil.copy2(CI_SCRIPT, caller)
        (self.root / "build_finished_arm64.log").touch()
        (self.root / "build/src").mkdir(parents=True)
        package_script = self.root / SCRIPT.name
        package_script.write_text(
            '#!/bin/bash\n'
            'printf \'%s\\n\' \'["package-child"]\' >> "$CALL_TRACE"\n'
            'exit 97\n'
        )
        package_script.chmod(0o755)
        secrets = {
            "MACOS_CERTIFICATE": base64.b64encode(b"certificate-fixture").decode(),
            "MACOS_CI_KEYCHAIN_PWD": "fixture-ci-keychain-password",
            "MACOS_CERTIFICATE_PWD": "fixture-certificate-password",
            "PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_B64":
                base64.b64encode(b"profile-fixture").decode(),
        }
        result = subprocess.run(
            ["/bin/bash", "-x", str(caller), "arm64"],
            cwd=self.root,
            env=self.environment | secrets,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(97, result.returncode, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertIn(["package-child"], calls)
        self.assertTrue(any(call[0] == "security" for call in calls))
        for secret in secrets.values():
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_ci_upload_uses_arcium_dmg_and_preserves_gn_app(self):
        caller = self.root / CI_SCRIPT.name
        shutil.copy2(CI_SCRIPT, caller)
        (self.root / "build_finished_arm64.log").touch()
        source_app = self.root / "build/src" / SOURCE_APP
        source_app.parent.mkdir(parents=True)
        shutil.copytree(self.root / SOURCE_APP, source_app)
        source_info = source_app / "Contents" / "Info.plist"
        source_info_bytes = source_info.read_bytes()
        output = self.root / "github-output.txt"
        self.environment.update(
            {
                "GITHUB_OUTPUT": str(output),
                "GITHUB_REPOSITORY": "fixture/arcium",
                "GITHUB_RUN_ID": "12345",
            }
        )

        sparkle_stub = self.root / "github_prep_sparkle_deltas.sh"
        sparkle_stub.write_text(
            '#!/bin/bash\n'
            'printf "deltas<<EOF\\nEOF\\n" >> "$GITHUB_OUTPUT"\n'
        )
        sparkle_stub.chmod(0o755)
        result = subprocess.run(
            ["/bin/bash", "-x", str(caller), "arm64"],
            cwd=self.root,
            env=self.environment | {
                "MACOS_CERTIFICATE": base64.b64encode(b"certificate-fixture").decode(),
                "MACOS_CI_KEYCHAIN_PWD": "fixture-ci-keychain-password",
                "MACOS_CERTIFICATE_PWD": "fixture-certificate-password",
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)

        filename = "arcium_1.0.0_arm64-macos.dmg"
        self.assertIn(f"file_name={filename}", output.read_text())
        self.assertTrue((self.root / "release_asset" / filename).is_file())
        self.assertTrue((self.root / f"{filename}.hashes.md").is_file())
        self.assertTrue(
            (self.root / "upload_part_build" / "build_src.tar.zst").is_file()
        )
        self.assertFalse(list(self.root.glob("helium_*.dmg")))
        self.assertEqual(source_info.read_bytes(), source_info_bytes)
        self.assertTrue(
            (source_app / "Contents/Frameworks/libArciumSettingsUI.dylib").is_file()
        )
        self.assertFalse((source_app.parent / "Arcium.app").exists())


if __name__ == "__main__":
    unittest.main()
