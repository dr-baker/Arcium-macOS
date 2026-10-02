"""Persistent replay recovery exercised only against disposable source trees."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import replay_contract as replay
import replay_timestamps as timestamps


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'src'
        self.source.mkdir()
        self.catalog = self.root / 'patches'
        self.catalog.mkdir()
        (self.catalog / 'series.merged').write_text('a.patch\n')
        self.file = self.source / 'file'
        self.file.write_bytes(b'original')
        self.old = 2_000_000_000
        self.new = 9_000_000_000
        os.utime(self.file, ns=(self.old, self.old))
        self.snapshot = self.root / '.arcium/replay-timestamps.json'
        self.identity = SimpleNamespace(receipt_id='a' * 64, chromium_version='1')

    def capture(self, **overrides):
        kwargs = dict(worktree=self.root, patch_root=self.catalog,
                      source_receipt_id=self.identity.receipt_id,
                      source_identity={'chromium_version': '1'}, paths=['file'])
        kwargs.update(overrides)
        return timestamps.recovery_timestamps(self.source, **kwargs)

    def attempt(self, *, fail=False, applied=True, changed=False, proof_fail=False):
        comparison = SimpleNamespace(applied=['a.patch'] if applied else [],
                                     require_valid_prefix=lambda: None)
        def run(_source, _environment, *args):
            self.file.write_bytes(b'intermediate' if fail else b'changed' if changed else b'original')
            os.utime(self.file, ns=(self.new, self.new))
            return subprocess.CompletedProcess(args, int(fail and args[0] == 'push'))
        def publish(*args):
            if proof_fail:
                raise replay.ReplayError('proof failed')
            path = replay.receipt_path(self.root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic proof')
            return SimpleNamespace(source=self.identity)
        with ExitStack() as stack:
            for name, kwargs in {
                '_require_core_patch_copies': {},
                'inspect_quilt_state': {'return_value': SimpleNamespace(comparison=comparison)},
                'current_source_identity': {'return_value': self.identity},
                '_patch_owned_paths': {'return_value': ['file']},
                '_run_quilt': {'side_effect': run},
                '_validate_replayed_state': {},
                '_write_proof': {'side_effect': publish},
            }.items():
                stack.enter_context(patch.object(replay, name, **kwargs))
            return replay.replay(self.root, self.source)

    def test_failure_then_recovery_uses_original_snapshot_with_empty_ledger(self):
        with self.assertRaises(replay.ReplayError):
            self.attempt(fail=True)
        initial = self.snapshot.read_bytes()
        self.assertEqual(self.file.stat().st_mtime_ns, self.new)
        with self.assertRaises(replay.ReplayError):
            self.attempt(fail=True, applied=False)
        self.assertEqual(self.snapshot.read_bytes(), initial)
        self.attempt(applied=False)
        self.assertEqual(self.file.stat().st_mtime_ns, self.old)
        self.assertFalse(self.snapshot.exists())

    def test_repaired_patch_identity_can_recover_but_changed_file_stays_dirty(self):
        for changed in [False, True]:
            with self.subTest(changed=changed):
                self.file.write_bytes(b'original')
                os.utime(self.file, ns=(self.old, self.old))
                with self.assertRaises(replay.ReplayError):
                    self.attempt(fail=True)
                self.identity = SimpleNamespace(receipt_id='b' * 64, chromium_version='1')
                self.attempt(changed=changed)
                self.assertEqual(self.file.stat().st_mtime_ns, self.new if changed else self.old)

    def test_proof_failure_preserves_snapshot_without_restoring(self):
        with self.assertRaises(replay.ReplayError):
            self.attempt(proof_fail=True)
        self.assertEqual(self.file.stat().st_mtime_ns, self.new)
        self.assertTrue(self.snapshot.exists())
        self.attempt()
        self.assertEqual(self.file.stat().st_mtime_ns, self.old)

    def test_snapshot_retirement_failure_invalidates_proof_before_restoring(self):
        unlink = os.unlink
        def refuse_snapshot(path, *args, **kwargs):
            if path == 'replay-timestamps.json':
                raise PermissionError('locked')
            return unlink(path, *args, **kwargs)
        with patch.object(timestamps.os, 'unlink', side_effect=refuse_snapshot):
            with self.assertRaises(replay.ReplayError):
                self.attempt()
        self.assertEqual(self.file.stat().st_mtime_ns, self.new)
        self.assertTrue(self.snapshot.exists())
        self.assertFalse(replay.receipt_path(self.root).exists())
        self.attempt()
        self.assertEqual(self.file.stat().st_mtime_ns, self.old)

    def test_completed_snapshot_cannot_hide_later_reverted_content(self):
        self.attempt()
        self.assertFalse(self.snapshot.exists())
        self.file.write_bytes(b'later built content')
        os.utime(self.file, ns=(self.new, self.new))
        # A subsequent replay returns to original content after another build.
        self.attempt()
        self.assertEqual(self.file.stat().st_mtime_ns, self.new)

    def test_existing_snapshot_does_not_evaluate_intermediate_paths(self):
        expected = self.capture()
        def forbidden():
            raise AssertionError('intermediate source was enumerated')
            yield
        self.assertEqual(self.capture(paths=forbidden()), expected)

    def test_corruption_and_context_changes_refuse_without_replacing_original(self):
        self.capture()
        original = self.snapshot.read_bytes()
        for overrides in [{'worktree': self.root / 'other'}, {'patch_root': self.root / 'other'},
                          {'source_identity': {'chromium_version': '2'}}]:
            with self.subTest(overrides=overrides), self.assertRaises(timestamps.TimestampRecoveryError):
                self.capture(**overrides)
            self.assertEqual(self.snapshot.read_bytes(), original)
        self.snapshot.write_bytes(b'{corrupt')
        with self.assertRaises(timestamps.TimestampRecoveryError):
            self.capture()
        self.assertEqual(self.snapshot.read_bytes(), b'{corrupt')

    def test_replaced_source_directory_refuses_snapshot(self):
        self.capture()
        self.source.rename(self.root / 'old-src')
        self.source.mkdir()
        with self.assertRaises(timestamps.TimestampRecoveryError):
            self.capture()

    def test_untrusted_paths_rejected_even_with_matching_checksum(self):
        self.capture()
        original = json.loads(self.snapshot.read_text())
        for name in ['../outside', '/outside', '.pc/file', 'out/file', './file']:
            with self.subTest(name=name):
                value = dict(original)
                value['files'] = {name: original['files']['file']}
                value.pop('sha256')
                value['sha256'] = hashlib.sha256(timestamps._json_bytes(value)).hexdigest()
                self.snapshot.write_text(json.dumps(value))
                with self.assertRaises(timestamps.TimestampRecoveryError):
                    self.capture()

    def test_symlinked_snapshot_and_state_directory_are_refused(self):
        external = self.root / 'external'
        external.write_bytes(b'untouched')
        self.snapshot.parent.mkdir()
        self.snapshot.symlink_to(external)
        with self.assertRaises(timestamps.TimestampRecoveryError):
            self.capture()
        self.assertEqual(external.read_bytes(), b'untouched')
        self.snapshot.unlink()
        self.snapshot.parent.rmdir()
        destination = self.root / 'external-dir'
        destination.mkdir()
        self.snapshot.parent.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(timestamps.TimestampRecoveryError):
            self.capture()
        self.assertEqual(list(destination.iterdir()), [])

    def test_unencodable_recovery_path_is_rejected_before_snapshot_consumption(self):
        self.capture()
        document = json.loads(self.snapshot.read_text())
        document['files'] = {'\ud800': document['files']['file']}
        document.pop('sha256')
        document['sha256'] = hashlib.sha256(timestamps._json_bytes(document)).hexdigest()
        self.snapshot.write_text(json.dumps(document))
        original = self.snapshot.read_bytes()
        with self.assertRaisesRegex(replay.ReplayError, 'cannot use replay timestamp'):
            self.attempt()
        self.assertEqual(self.snapshot.read_bytes(), original)
        self.assertEqual(self.file.stat().st_mtime_ns, self.old)
        self.assertFalse(replay.receipt_path(self.root).exists())

    def test_symlinked_file_or_ancestor_is_not_restored(self):
        folder = self.source / 'nested'
        folder.mkdir()
        nested = folder / 'file'
        nested.write_bytes(b'original')
        os.utime(nested, ns=(self.old, self.old))
        records = self.capture(paths=['nested/file'])
        outside = self.root / 'outside'
        folder.rename(outside)
        folder.symlink_to(outside, target_is_directory=True)
        os.utime(outside / 'file', ns=(self.new, self.new))
        self.assertEqual(timestamps.restore_timestamps(self.source, records), 0)
        self.assertEqual((outside / 'file').stat().st_mtime_ns, self.new)


if __name__ == '__main__':
    unittest.main()
