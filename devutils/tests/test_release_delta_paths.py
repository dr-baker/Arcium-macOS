"""Keep Sparkle deltas aligned with the app bundle inside each release DMG."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


DEVUTILS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEVUTILS))
from generate_sparkle_deltas import (  # noqa: E402
    generate_delta_for,
    get_asset_url,
    get_historic_dmg_urls,
    mounted_release_app_path,
)


class ReleaseDeltaPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="arcium-delta-path-")
        self.addCleanup(self.temporary.cleanup)
        self.mountpoint = Path(self.temporary.name)

    def test_release_requires_arcium_bundle(self) -> None:
        (self.mountpoint / "Helium.app").mkdir()

        with self.assertRaisesRegex(FileNotFoundError, "no Arcium.app"):
            mounted_release_app_path(self.mountpoint)

        arcium_app = self.mountpoint / "Arcium.app"
        arcium_app.mkdir()
        self.assertEqual(mounted_release_app_path(self.mountpoint), str(arcium_app))

    def test_historic_assets_select_arcium_when_releases_are_mixed(self) -> None:
        release = {
            "tag_name": "v2.0-arcium",
            "assets": [
                {
                    "name": "helium_1_arm64-macos.dmg",
                    "browser_download_url": "https://example.test/helium-arm.dmg",
                },
                {
                    "name": "arcium_2_arm64-macos.dmg",
                    "browser_download_url": "https://example.test/arcium-arm.dmg",
                },
                {
                    "name": "helium_1_x86_64-macos.dmg",
                    "browser_download_url": "https://example.test/helium-x86.dmg",
                },
                {
                    "name": "arcium_2_x86_64-macos.dmg",
                    "browser_download_url": "https://example.test/arcium-x86.dmg",
                },
            ],
        }
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: [release],
        )

        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=Mock(return_value=response))}):
            urls = get_historic_dmg_urls()

        self.assertEqual(
            urls,
            {
                "v2.0": (
                    "https://example.test/arcium-arm.dmg",
                    "https://example.test/arcium-x86.dmg",
                )
            },
        )

    def test_historic_selection_skips_missing_arcium_arches(self) -> None:
        release = {
            "tag_name": "v1.5",
            "assets": [
                {
                    "name": "helium_1_arm64-macos.dmg",
                    "browser_download_url": "https://example.test/helium-arm.dmg",
                },
                {
                    "name": "arcium_1_x86_64-macos.dmg",
                    "browser_download_url": "https://example.test/arcium-x86.dmg",
                },
            ],
        }
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: [release],
        )

        with patch.dict(sys.modules, {"requests": SimpleNamespace(get=Mock(return_value=response))}):
            urls = get_historic_dmg_urls()

        self.assertEqual(urls, {"v1.5": (None, "https://example.test/arcium-x86.dmg")})

    def test_delta_downloads_selected_arcium_asset_and_uses_arcium_bundle(self) -> None:
        class DownloadResponse:
            content = b"dmg bytes"

            def raise_for_status(self) -> None:
                return None

            def __enter__(self) -> "DownloadResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        download_response = DownloadResponse()
        request = Mock(return_value=download_response)
        diff = Mock()

        class MountedImage:
            def __init__(self, dmg: str, mountpoint: str) -> None:
                self.mountpoint = Path(mountpoint)

            def __enter__(self) -> None:
                (self.mountpoint / "Arcium.app").mkdir()

            def __exit__(self, *_args: object) -> None:
                return None

        urls = ("https://example.test/arcium-arm.dmg", None)
        delta_args = (
            Path("new-arm.dmg"),
            Path("new-x86.dmg"),
            str(self.mountpoint / "deltas"),
        )
        with (
            patch.dict(sys.modules, {"requests": SimpleNamespace(get=request)}),
            patch("generate_sparkle_deltas.mount", MountedImage),
            patch("generate_sparkle_deltas.do_diff", diff),
        ):
            generate_delta_for("v2.0", urls, delta_args)

        request.assert_called_once_with(
            "https://example.test/arcium-arm.dmg",
            headers={},
            stream=True,
        )
        diff.assert_called_once()
        old_app, new_app, output_path = diff.call_args.args
        self.assertEqual(Path(old_app).name, "Arcium.app")
        self.assertEqual(Path(new_app).name, "Arcium.app")
        self.assertEqual(output_path, f"{delta_args[2]}/v2.0-arm64.delta")

if __name__ == "__main__":
    unittest.main()
