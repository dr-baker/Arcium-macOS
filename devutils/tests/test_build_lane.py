"""Tests for deterministic local and removable build-lane selection."""

import tempfile
import unittest
import os
import socket
import stat
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from devutils.build_lane import (
    LaneError,
    LaneSpec,
    VolumeInfo,
    acquire_lane_lock,
    diagnose_lane,
    inspect_lane,
    heavy_lane_temp,
    heavy_temp_environment,
    MACOS_UNIX_PATH_BYTES,
    SCCACHE_SOCKET_SUFFIX,
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

    def test_lane_transaction_child_reuses_exact_parent_lock(self) -> None:
        lock_path = self.mount / "locks" / "heavy.lock"
        with acquire_lane_lock(lock_path, {"action": "parent"}) as descriptor:
            with patch.dict(
                "os.environ", {"HELIUM_DEV_LANE_LOCK_FD": str(descriptor)}
            ):
                with acquire_lane_lock(lock_path, {"action": "child"}):
                    payload = lock_path.read_text(encoding="utf-8")
                    self.assertIn('"action":"parent"', payload)

    def test_forged_inherited_descriptor_cannot_bypass_contention(self) -> None:
        lock_path = self.mount / "locks" / "heavy.lock"
        with acquire_lane_lock(lock_path, {"action": "parent"}):
            forged = os.open(lock_path, os.O_RDWR)
            self.addCleanup(os.close, forged)
            with patch.dict(
                "os.environ", {"HELIUM_DEV_LANE_LOCK_FD": str(forged)}
            ):
                with self.assertRaisesRegex(LaneError, "not owned"):
                    with acquire_lane_lock(lock_path, {"action": "forged"}):
                        self.fail("forged descriptor bypassed lane contention")


class HeavyTemporaryDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ac-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.mount = Path(self.temporary.name).resolve()
        self.spec = LaneSpec("heavy", self.mount / "ArciumBuild" / ("long-lane-" * 15), 0,
                             expected_volume_uuid="fixture-volume")
        self.volume = VolumeInfo(self.mount, "fixture-volume", "apfs", "Case-sensitive APFS",
                                 1024, True, True, True, True, True, "USB")

    def select(self, *, create=False, spec=None, volume=None):
        return heavy_lane_temp(spec or self.spec, create=create,
                               volume_probe=lambda _path: volume or self.volume)

    def test_long_lane_gets_short_owned_directory_and_real_unix_socket(self) -> None:
        old_socket = str(self.spec.root / ".arcium/tmp") + SCCACHE_SOCKET_SUFFIX
        self.assertGreaterEqual(len(os.fsencode(old_socket)), MACOS_UNIX_PATH_BYTES)
        with socket.socket(socket.AF_UNIX) as old:
            with self.assertRaisesRegex(OSError, "AF_UNIX path too long"):
                old.bind(old_socket)
        selected = self.select()
        self.assertFalse(selected.parent.exists())
        self.assertEqual(selected, self.select(create=True))
        self.assertEqual(selected, self.select(create=True))
        self.assertEqual(selected.parent.parent, self.mount)
        for path in (selected.parent, selected):
            metadata = path.stat()
            self.assertEqual(metadata.st_uid, os.geteuid())
            self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o700)
            self.assertEqual(metadata.st_dev, self.mount.stat().st_dev)
        socket_path = Path(str(selected) + SCCACHE_SOCKET_SUFFIX.replace("XXXXXX", "abcdef"))
        socket_path.parent.mkdir(mode=0o700)
        self.assertLess(len(os.fsencode(socket_path)), MACOS_UNIX_PATH_BYTES)
        with socket.socket(socket.AF_UNIX) as current:
            current.bind(str(socket_path))
            self.assertTrue(socket_path.exists())
        self.assertNotEqual(selected, self.select(spec=replace(self.spec, root=self.mount / "other-lane")))
        self.assertFalse(self.spec.root.exists())

    def test_budget_uses_bytes_and_preserves_the_exact_boundary(self) -> None:
        fixed = len(os.fsencode(f"/.arcium-tmp-{os.geteuid()}/" + "0" * 20 + SCCACHE_SOCKET_SUFFIX))
        longest_mount = MACOS_UNIX_PATH_BYTES - 1 - fixed
        prefix = len(os.fsencode(str(self.mount) + "/"))
        for bytes_over in (0, 1):
            mount = self.mount / ("m" * (longest_mount - prefix + bytes_over))
            mount.mkdir()
            volume = replace(self.volume, mount_point=mount)
            spec = replace(self.spec, root=mount / "lane")
            with self.subTest(bytes_over=bytes_over):
                if bytes_over:
                    with self.assertRaisesRegex(LaneError, "socket budget"):
                        self.select(create=True, spec=spec, volume=volume)
                    self.assertEqual(list(mount.iterdir()), [])
                else:
                    selected = self.select(create=True, spec=spec, volume=volume)
                    socket_path = Path(str(selected) + SCCACHE_SOCKET_SUFFIX.replace("XXXXXX", "abcdef"))
                    socket_path.parent.mkdir()
                    self.assertEqual(len(os.fsencode(socket_path)), MACOS_UNIX_PATH_BYTES - 1)
                    with socket.socket(socket.AF_UNIX) as current:
                        current.bind(str(socket_path))
        unicode_mount = self.mount / ("界" * 20)
        unicode_mount.mkdir()
        with self.assertRaisesRegex(LaneError, "socket budget"):
            self.select(create=True, spec=replace(self.spec, root=unicode_mount / "lane"),
                        volume=replace(self.volume, mount_point=unicode_mount))
        self.assertEqual(list(unicode_mount.iterdir()), [])

    def test_heavy_volume_contract_cannot_be_relaxed(self) -> None:
        for changes in ({"volume_uuid": "other"}, {"external": False}, {"writable": False},
                        {"filesystem_name": "APFS"}, {"filesystem_type": "exfat"}):
            with self.subTest(changes=changes), self.assertRaises(LaneError):
                self.select(create=True, volume=replace(self.volume, **changes))
        for spec in (replace(self.spec, expected_volume_uuid=None), replace(self.spec, name="local"),
                     replace(self.spec, root=self.mount / ".." / "elsewhere")):
            with self.subTest(spec=spec), self.assertRaises(LaneError):
                self.select(create=True, spec=spec)
        self.assertEqual(list(self.mount.iterdir()), [])

    def test_ownership_status_remains_advisory_for_public_compiler_scratch(self) -> None:
        for enabled in (False, None):
            with self.subTest(enabled=enabled):
                selected = self.select(create=True, volume=replace(self.volume, ownership_enabled=enabled))
                self.assertEqual(selected.stat().st_uid, os.geteuid())
                self.assertEqual(stat.S_IMODE(selected.stat().st_mode), 0o700)
        report = diagnose_lane(replace(self.spec, warn_if_ownership_disabled=True),
                               replace(self.volume, ownership_enabled=False))
        self.assertTrue(report.ok)
        self.assertEqual([item.code for item in report.diagnostics], ["ownership-disabled"])

    def test_symlink_lane_and_mount_are_rejected_before_creation(self) -> None:
        real = self.mount / "real"
        real.mkdir()
        alias = self.mount / "alias"
        alias.symlink_to(real, target_is_directory=True)
        for spec, volume in ((replace(self.spec, root=alias / "lane"), self.volume),
                             (replace(self.spec, root=alias / "lane"), replace(self.volume, mount_point=alias))):
            with self.subTest(volume=volume), self.assertRaises(LaneError):
                self.select(create=True, spec=spec, volume=volume)
        self.assertEqual(list(real.iterdir()), [])
        self.assertFalse((self.mount / f".arcium-tmp-{os.geteuid()}").exists())

    def test_symlink_and_shared_scratch_components_are_not_adopted(self) -> None:
        selected = self.select()
        outside = self.mount / "outside"
        outside.mkdir()
        selected.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LaneError):
            self.select(create=True)
        selected.parent.unlink()
        selected.parent.mkdir(mode=0o777)
        selected.parent.chmod(0o777)
        with self.assertRaisesRegex(LaneError, "mode 0700"):
            self.select(create=True)
        self.assertEqual(stat.S_IMODE(selected.parent.stat().st_mode), 0o777)
        selected.parent.chmod(0o700)
        selected.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LaneError):
            self.select(create=True)
        selected.unlink()
        selected.mkdir(mode=0o777)
        selected.chmod(0o777)
        with self.assertRaisesRegex(LaneError, "mode 0700"):
            self.select(create=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_foreign_owner_and_cross_device_components_are_rejected(self) -> None:
        selected = self.select(create=True)
        real_fstat = os.fstat
        for target, field, value in ((selected, 4, os.geteuid() + 1),
                                     (selected.parent, 2, self.mount.stat().st_dev + 1)):
            identity = (target.stat().st_dev, target.stat().st_ino)
            def hostile(fd):
                metadata = real_fstat(fd)
                if (metadata.st_dev, metadata.st_ino) == identity:
                    fields = list(metadata)
                    fields[field] = value
                    return os.stat_result(fields)
                return metadata
            with self.subTest(target=target), patch("devutils.build_lane.os.fstat", side_effect=hostile):
                with self.assertRaisesRegex(LaneError, "mode 0700"):
                    self.select(create=True)

    def test_volume_and_path_replacement_are_rejected_at_final_validation(self) -> None:
        with self.assertRaisesRegex(LaneError, "volume"):
            heavy_lane_temp(self.spec, volume_probe=lambda _path: replace(self.volume, volume_uuid="other"))
        selected = self.select(create=True)
        outside = self.mount / "outside"
        outside.mkdir()
        calls = 0
        def replace_parent(_path):
            nonlocal calls
            calls += 1
            if calls == 2:
                selected.parent.rename(self.mount / "quarantined")
                selected.parent.symlink_to(outside, target_is_directory=True)
            return self.volume
        with self.assertRaisesRegex(LaneError, "path changed"):
            heavy_lane_temp(self.spec, create=True, volume_probe=replace_parent)
        self.assertEqual(list(outside.iterdir()), [])

    def test_temp_environment_restores_the_caller_after_failure(self) -> None:
        with patch.dict(os.environ, {"TMPDIR": "caller-temp"}), patch(
            "devutils.build_lane.heavy_lane_temp", side_effect=lambda spec, create: self.select(create=create)
        ):
            with self.assertRaisesRegex(RuntimeError, "producer"):
                with heavy_temp_environment(self.spec) as selected:
                    self.assertEqual(os.environ["TMPDIR"], str(selected))
                    raise RuntimeError("producer")
            self.assertEqual(os.environ["TMPDIR"], "caller-temp")

    def test_late_same_volume_lane_symlink_is_rejected(self) -> None:
        parent = self.mount / "lane-parent"
        parent.mkdir()
        outside = self.mount / "outside"
        outside.mkdir()
        spec = replace(self.spec, root=parent / "lane")
        calls = 0
        def replace_parent(_path):
            nonlocal calls
            calls += 1
            if calls == 2:
                parent.rename(self.mount / "original-parent")
                parent.symlink_to(outside, target_is_directory=True)
            return self.volume
        with self.assertRaises(LaneError):
            heavy_lane_temp(spec, create=True, volume_probe=replace_parent)
        self.assertEqual(list(outside.iterdir()), [])

    def test_late_namespace_mode_or_identity_drift_is_rejected(self) -> None:
        for drift in ("user-mode", "lane-mode", "identity-mode", "identity-bytes"):
            spec = replace(self.spec, root=self.mount / drift)
            selected = self.select(spec=spec, create=True)
            target = (selected.parent if drift == "user-mode" else selected
                      if drift == "lane-mode" else selected / "lane.json")
            original_mode, original_bytes = stat.S_IMODE(target.stat().st_mode), None
            if drift == "identity-bytes":
                original_bytes = target.read_bytes()
            calls = 0
            def mutate(_path):
                nonlocal calls
                calls += 1
                if calls == 2:
                    if drift == "identity-bytes":
                        target.write_bytes(b"changed identity")
                    else:
                        target.chmod(0o777)
                return self.volume
            try:
                with self.subTest(drift=drift), self.assertRaises(LaneError):
                    heavy_lane_temp(spec, create=True, volume_probe=mutate)
            finally:
                target.chmod(original_mode)
                if original_bytes is not None:
                    target.write_bytes(original_bytes)

    def test_late_identity_deletion_rejects_publication_and_allows_clean_retry(self) -> None:
        selected = self.select(create=True)
        calls = 0

        def remove_identity(_path):
            nonlocal calls
            calls += 1
            if calls == 2:
                (selected / "lane.json").unlink()
            return self.volume

        with self.assertRaisesRegex(LaneError, "identity disappeared"):
            heavy_lane_temp(self.spec, create=True, volume_probe=remove_identity)
        self.assertEqual(list(selected.iterdir()), [])
        self.assertEqual(selected, self.select(create=True))
        self.assertTrue((selected / "lane.json").is_file())

    def test_lane_identity_rejects_collisions_symlinks_hardlinks_and_unknown_content(self) -> None:
        selected = self.select(create=True)
        with patch("devutils.build_lane.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = selected.name + "0" * 44
            with self.assertRaisesRegex(LaneError, "does not match"):
                self.select(create=True, spec=replace(self.spec, root=self.mount / "collision-lane"))
        identity = selected / "lane.json"
        original = identity.read_bytes()
        identity.write_text('{"lane":"another lane"}')
        with self.assertRaisesRegex(LaneError, "does not match"):
            self.select(create=True)
        self.assertEqual(identity.read_text(), '{"lane":"another lane"}')
        identity.write_bytes(original)
        outside = self.mount / "outside.json"
        identity.rename(outside)
        identity.symlink_to(outside)
        with self.assertRaises(LaneError):
            self.select(create=True)
        identity.unlink()
        os.link(outside, identity)
        with self.assertRaisesRegex(LaneError, "owned regular file"):
            self.select(create=True)
        identity.unlink()
        (selected / "unknown-content").write_text("preserve")
        with self.assertRaisesRegex(LaneError, "no matching lane identity"):
            self.select(create=True)
        self.assertEqual((selected / "unknown-content").read_text(), "preserve")

    def test_interrupted_new_identity_write_removes_only_its_marker_and_allows_retry(self) -> None:
        real_fdopen = os.fdopen
        for failure in (OSError("interrupted write"), KeyboardInterrupt()):
            spec = replace(self.spec, root=self.mount / type(failure).__name__)
            selected = self.select(spec=spec)

            class InterruptedOutput:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *_exception):
                    self.stream.close()

                def write(self, content):
                    self.stream.write(content[:3])
                    self.stream.flush()
                    raise failure

            with self.subTest(failure=type(failure).__name__), patch(
                "devutils.build_lane.os.fdopen",
                side_effect=lambda fd, mode: InterruptedOutput(real_fdopen(fd, mode)),
            ):
                with self.assertRaises(LaneError if isinstance(failure, OSError) else KeyboardInterrupt):
                    self.select(create=True, spec=spec)
            self.assertEqual(list(selected.iterdir()), [])
            self.assertEqual(selected, self.select(create=True, spec=spec))
            self.assertIn(str(spec.root), (selected / "lane.json").read_text())

    def test_failed_new_identity_write_preserves_replacement_and_unknown_scratch(self) -> None:
        selected = self.select()
        marker = selected / "lane.json"
        scratch = selected / "unknown-scratch"
        real_fdopen = os.fdopen

        class ReplacedOutput:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *_exception):
                self.stream.close()

            def write(self, content):
                self.stream.write(content[:3])
                self.stream.flush()
                marker.unlink()
                marker.write_bytes(b"replacement identity")
                marker.chmod(0o600)
                scratch.write_bytes(b"preserve scratch")
                raise KeyboardInterrupt()

        with patch("devutils.build_lane.os.fdopen",
                   side_effect=lambda fd, mode: ReplacedOutput(real_fdopen(fd, mode))):
            with self.assertRaises(KeyboardInterrupt):
                self.select(create=True)
        self.assertEqual(marker.read_bytes(), b"replacement identity")
        self.assertEqual(scratch.read_bytes(), b"preserve scratch")
        with self.assertRaisesRegex(LaneError, "does not match"):
            self.select(create=True)
        self.assertEqual(marker.read_bytes(), b"replacement identity")


if __name__ == "__main__":
    unittest.main()
