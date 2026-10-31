import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from devutils.sparkle_feed import build_feed_url, validate_public_key


BUILD_SCRIPT = REPO_ROOT / ".github/scripts/github_before_build.sh"
PUBLIC_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
FEED_BASE_URL = "https://updates.example.invalid/arcium"


class SparkleFeedTests(unittest.TestCase):
    def test_architecture_feed_urls_are_built_from_configured_base(self):
        self.assertEqual(
            "https://updates.example.invalid/arcium/mac/appcast-arm64.xml",
            build_feed_url(FEED_BASE_URL, "arm64"),
        )
        self.assertEqual(
            "https://updates.example.invalid/arcium/mac/appcast-x86_64.xml",
            build_feed_url(FEED_BASE_URL + "/", "x86_64"),
        )

    def test_invalid_feed_configuration_is_rejected(self):
        for base_url, arch in (
            ("http://updates.example.invalid/arcium", "arm64"),
            (FEED_BASE_URL + "?channel=stable", "arm64"),
            (FEED_BASE_URL + "/appcast.xml", "arm64"),
            ("https://user:pass@updates.example.invalid/arcium", "arm64"),
            ("https://updates.example.invalid/arcium", "x64"),
        ):
            with self.subTest(base_url=base_url, arch=arch):
                with self.assertRaises(ValueError):
                    build_feed_url(base_url, arch)

    def test_public_key_must_be_canonical_32_byte_base64(self):
        validate_public_key(PUBLIC_KEY)
        for invalid_key in (
            "key\"\n",
            base64.b64encode(bytes(31)).decode("ascii"),
            base64.b64encode(bytes(33)).decode("ascii"),
            PUBLIC_KEY[:-1],
        ):
            with self.subTest(invalid_key=invalid_key):
                with self.assertRaises(ValueError):
                    validate_public_key(invalid_key)


class GitHubBuildConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "build/src/out/Default").mkdir(parents=True)
        (self.root / "build/src/buildtools/mac").mkdir(parents=True)
        (self.root / "helium-chromium").mkdir()
        (self.root / "devutils").mkdir()
        (self.root / "helium-chromium/flags.gn").write_text("is_debug = false\n")

        self.script = self.root / "github_before_build.sh"
        shutil.copy2(BUILD_SCRIPT, self.script)
        shutil.copy2(REPO_ROOT / "devutils/sparkle_feed.py", self.root / "devutils")
        self.stub_bin = self.root / "stub-bin"
        self.stub_bin.mkdir()

        readlink_stub = self.stub_bin / "greadlink"
        readlink_stub.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "print(pathlib.Path(sys.argv[-1]).resolve())\n"
        )
        readlink_stub.chmod(0o755)

        gn = self.root / "build/src/buildtools/mac/gn"
        gn.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$GN_STUB_LOG\"\n"
        )
        gn.chmod(0o755)

    def tearDown(self):
        self.temporary.cleanup()

    def run_build_setup(self, arch, *, public_key="", feed_base_url=""):
        log = self.root / "gn-calls.log"
        env = os.environ.copy()
        env["PATH"] = f"{self.stub_bin}{os.pathsep}{env.get('PATH', '')}"
        env["GN_STUB_LOG"] = str(log)
        env.pop("PROD_MACOS_SPARKLE_ED_PUB_KEY", None)
        env.pop("PROD_MACOS_SPARKLE_FEED_BASE_URL", None)
        if public_key:
            env["PROD_MACOS_SPARKLE_ED_PUB_KEY"] = public_key
        if feed_base_url:
            env["PROD_MACOS_SPARKLE_FEED_BASE_URL"] = feed_base_url
        result = subprocess.run(
            ["bash", str(self.script), arch],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, log

    def test_missing_both_values_keeps_sparkle_disabled(self):
        result, log = self.run_build_setup("arm64")
        self.assertEqual(0, result.returncode, result.stderr)
        args = (self.root / "build/src/out/Default/args.gn").read_text()
        self.assertNotIn("enable_sparkle=true", args)
        self.assertNotIn("sparkle_feed_url", args)
        self.assertTrue(log.exists())

    def test_missing_feed_base_fails_before_gn(self):
        result, log = self.run_build_setup("arm64", public_key=PUBLIC_KEY)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires both PROD_MACOS_SPARKLE_ED_PUB_KEY", result.stderr)
        self.assertFalse(log.exists())

    def test_missing_public_key_fails_before_gn(self):
        result, log = self.run_build_setup("arm64", feed_base_url=FEED_BASE_URL)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires both PROD_MACOS_SPARKLE_ED_PUB_KEY", result.stderr)
        self.assertFalse(log.exists())

    def test_valid_arm64_configuration_writes_full_feed_to_gn_args(self):
        result, log = self.run_build_setup(
            "arm64", public_key=PUBLIC_KEY, feed_base_url=FEED_BASE_URL
        )
        self.assertEqual(0, result.returncode, result.stderr)
        args = (self.root / "build/src/out/Default/args.gn").read_text()
        self.assertIn('target_cpu = "arm64"', args)
        self.assertIn("enable_sparkle=true", args)
        self.assertIn(f'sparkle_ed_key="{PUBLIC_KEY}"', args)
        self.assertIn(
            f'sparkle_feed_url="{FEED_BASE_URL}/mac/appcast-arm64.xml"', args
        )
        self.assertIn("gen out/Default --fail-on-unused-args", log.read_text())

    def test_valid_x86_64_configuration_writes_full_feed_to_gn_args(self):
        result, log = self.run_build_setup(
            "x86_64", public_key=PUBLIC_KEY, feed_base_url=FEED_BASE_URL
        )
        self.assertEqual(0, result.returncode, result.stderr)
        args = (self.root / "build/src/out/Default/args.gn").read_text()
        self.assertIn('target_cpu = "x64"', args)
        self.assertIn("enable_sparkle=true", args)
        self.assertIn(
            f'sparkle_feed_url="{FEED_BASE_URL}/mac/appcast-x86_64.xml"', args
        )
        self.assertIn("gen out/Default --fail-on-unused-args", log.read_text())

    def test_invalid_base_fails_before_gn(self):
        result, log = self.run_build_setup(
            "arm64", public_key=PUBLIC_KEY, feed_base_url="http://updates.invalid"
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Sparkle configuration error:", result.stderr)
        self.assertFalse(log.exists())

    def test_invalid_public_key_fails_before_gn(self):
        result, log = self.run_build_setup(
            "arm64", public_key=base64.b64encode(bytes(31)).decode("ascii"),
            feed_base_url=FEED_BASE_URL
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Sparkle configuration error:", result.stderr)
        self.assertFalse(log.exists())

    def test_unknown_architecture_fails_before_gn(self):
        result, log = self.run_build_setup(
            "x64", public_key=PUBLIC_KEY, feed_base_url=FEED_BASE_URL
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Unsupported macOS build architecture", result.stderr)
        self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
