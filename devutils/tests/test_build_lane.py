"""Tests for deterministic local and removable build-lane selection."""

import tempfile
import unittest
from pathlib import Path

from devutils.build_lane import (
    LaneError,
    LaneSpec,
    VolumeInfo,
    acquire_lane_lock,
    diagnose_lane,
    inspect_lane,
)


class BuildLaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.mount = Path(self.temporary.name)
        self.root = self.mount / "ArciumBuild"
        self.volume = VolumeInfo(
            mount_point=self.mount,
            volume_uuid="volume-1",
            filesystem_type="apfs",
            filesystem_name="Case-sensitive APFS",
            free_bytes=100,
            writable=True,
            external=True,
            encrypted=True,
            ownership_enabled=True,
            solid_state=True,
            bus_protocol="USB",
        )
        self.spec = LaneSpec(
            name="heavy",
            root=self.root,
            minimum_free_bytes=75,
            expected_volume_uuid="volume-1",
            require_external=True,
            require_case_sensitive_apfs=True,
            warn_if_unencrypted=True,
            warn_if_ownership_disabled=True,
        )

    def test_healthy_external_lane_passes(self) -> None:
        report = diagnose_lane(self.spec, self.volume)
        self.assertTrue(report.ok)
        self.assertEqual(report.diagnostics, ())
        report.require_ok()

    def test_probe_is_injected_without_touching_storage(self) -> None:
        calls = []

        def probe(path):
            calls.append(path)
            return self.volume

        report = inspect_lane(self.spec, volume_probe=probe)
        self.assertTrue(report.ok)
        self.assertEqual(calls, [self.root])

    def test_wrong_uuid_and_internal_volume_fail(self) -> None:
        volume = VolumeInfo(**{
            **self.volume.__dict__,
            "volume_uuid": "other",
            "external": False,
        })
        report = diagnose_lane(self.spec, volume)
        self.assertFalse(report.ok)
        self.assertEqual(
            {item.code for item in report.diagnostics},
            {"wrong-volume", "not-external"},
        )
        with self.assertRaises(LaneError):
            report.require_ok()

    def test_filesystem_and_free_space_fail_closed(self) -> None:
        volume = VolumeInfo(**{
            **self.volume.__dict__,
            "filesystem_type": "exfat",
            "filesystem_name": "ExFAT",
            "free_bytes": 10,
        })
        report = diagnose_lane(self.spec, volume)
        self.assertEqual(
            {item.code for item in report.diagnostics},
            {"filesystem", "case-sensitivity", "free-space"},
        )

    def test_encryption_and_ownership_are_advisory(self) -> None:
        volume = VolumeInfo(**{
            **self.volume.__dict__,
            "encrypted": False,
            "ownership_enabled": False,
        })
        report = diagnose_lane(self.spec, volume)
        self.assertTrue(report.ok)
        self.assertEqual(
            {item.code for item in report.diagnostics},
            {"unencrypted", "ownership-disabled"},
        )

    def test_lane_root_must_be_on_the_probed_mount(self) -> None:
        spec = LaneSpec("heavy", Path("/elsewhere/build"), 1)
        report = diagnose_lane(spec, self.volume)
        self.assertFalse(report.ok)
        self.assertEqual(report.diagnostics[0].code, "wrong-mount")

    def test_lane_lock_reports_owner_and_refuses_contention(self) -> None:
        lock_path = self.mount / "locks" / "heavy.lock"
        with acquire_lane_lock(lock_path, {"action": "build"}):
            payload = lock_path.read_text(encoding="utf-8")
            self.assertIn('"action":"build"', payload)
            with self.assertRaisesRegex(LaneError, "already locked"):
                with acquire_lane_lock(lock_path, {"action": "other"}):
                    self.fail("contended lane lock was acquired")


if __name__ == "__main__":
    unittest.main()
