"""Tests for generated-lane depot_tools identity markers."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from gclient_identity import (  # noqa: E402
    GClientIdentityError,
    ensure_gclient_identity,
)


_FAKE_GCLIENT_PATHS = '''
import os

def GetPrimarySolutionPath(from_dir=None):
    path = os.path.abspath(from_dir or os.getcwd())
    while True:
        marker = os.path.join(path, ".gclient")
        entries = os.path.join(path, ".gclient_entries")
        if os.path.isfile(marker) and os.path.isfile(entries):
            scope = {}
            exec(open(marker, encoding="utf-8").read(), scope)
            return os.path.join(path, scope["solutions"][0]["name"])
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
'''


class GClientIdentityTests(unittest.TestCase):
    def _lane(self, base: Path) -> Path:
        root = base / "build"
        source = root / "src"
        (source / "out" / "Default").mkdir(parents=True)
        (source / "build" / "config" / "siso").mkdir(parents=True)
        (source / "build" / "config" / "siso" / ".sisoenv").write_text(
            "SISO_PROJECT=test\n", encoding="utf-8"
        )
        depot_tools = source / "third_party" / "depot_tools"
        depot_tools.mkdir(parents=True)
        (depot_tools / "gclient_paths.py").write_text(
            _FAKE_GCLIENT_PATHS, encoding="utf-8"
        )
        return root

    def test_generated_lane_gets_minimal_discovery_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._lane(Path(temporary))

            source = ensure_gclient_identity(root)

            self.assertEqual(source, (root / "src").resolve())
            self.assertIn('"name": "src"', (root / ".gclient").read_text())
            self.assertIn('"src":', (root / ".gclient_entries").read_text())
            self.assertEqual(ensure_gclient_identity(root), source)

    def test_existing_foreign_metadata_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._lane(Path(temporary))
            marker = root / ".gclient"
            marker.write_text("foreign\n", encoding="utf-8")

            with self.assertRaisesRegex(
                GClientIdentityError, "incomplete gclient metadata"
            ):
                ensure_gclient_identity(root)

            self.assertEqual(marker.read_text(encoding="utf-8"), "foreign\n")

    def test_valid_foreign_metadata_is_refused_without_a_real_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._lane(Path(temporary))
            ensure_gclient_identity(root)
            marker = root / ".gclient"
            marker.write_text(
                'solutions = [{"name": "src", "url": "foreign"}]\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                GClientIdentityError, "refusing foreign gclient metadata"
            ):
                ensure_gclient_identity(root)

    def test_ancestor_identity_is_replaced_by_exact_lane_local_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self._lane(base)
            (base / ".gclient").write_text(
                'solutions = [{"name": "build/src", "url": "foreign"}]\n',
                encoding="utf-8",
            )
            (base / ".gclient_entries").write_text(
                'entries = {"build/src": "foreign"}\n', encoding="utf-8"
            )

            source = ensure_gclient_identity(root)

            self.assertEqual(source, (root / "src").resolve())
            self.assertIn('"name": "src"', (root / ".gclient").read_text())
            self.assertIn('"src":', (root / ".gclient_entries").read_text())


if __name__ == "__main__":
    unittest.main()
