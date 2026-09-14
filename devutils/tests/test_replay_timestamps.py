"""Timestamp safety and replay transaction tests, using temporary source trees."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import replay_contract as replay
import replay_timestamps as timestamps


class TimestampTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'src'
        self.root.mkdir()

    def write(self, name, data=b'same'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, ns=(1_000_000_000, 2_000_000_000))
        return path

    def test_unchanged_replacement_changed_content_mode_addition_and_deletion(self):
        paths = {name: self.write(name) for name in ['same', 'changed', 'mode', 'deleted']}
        records = timestamps.snapshot_timestamps(self.root, [*paths, 'new'])
        paths['same'].unlink()  # Quilt may replace inodes.
        paths['same'].write_bytes(b'same')
        paths['changed'].write_bytes(b'edit')
        paths['mode'].chmod(0o600)
        paths['deleted'].unlink()
        new = self.write('new')
        os.utime(new, ns=(3_000_000_000, 4_000_000_000))
        mtimes = {name: path.stat().st_mtime_ns for name, path in paths.items() if path.exists()}
        self.assertEqual(timestamps.restore_timestamps(self.root, records), 1)
        self.assertEqual(paths['same'].stat().st_mtime_ns, 2_000_000_000)
        for name in ['changed', 'mode']:
            self.assertEqual(paths[name].stat().st_mtime_ns, mtimes[name])
        self.assertEqual(new.stat().st_mtime_ns, 4_000_000_000)
        self.assertFalse(paths['deleted'].exists())

    def test_unsafe_paths_never_restore(self):
        outside = self.root.parent / 'outside'
        outside.write_bytes(b'same')
        before = outside.stat().st_mtime_ns
        (self.root / 'link').symlink_to(outside)
        (self.root / 'parent-link').symlink_to(self.root.parent, target_is_directory=True)
        os.link(outside, self.root / 'hardlink')
        os.mkfifo(self.root / 'fifo')
        names = ['link', 'parent-link/outside', 'hardlink', 'fifo', '../outside',
                 str(outside), '', '.', 'nested/../../outside']
        for excluded in ['out', 'obj', 'gen', '.pc', '.git', '.arcium']:
            self.write(excluded + '/file')
            names.append(excluded + '/file')
        self.assertEqual(timestamps.snapshot_timestamps(self.root, names), {})
        self.assertEqual(outside.stat().st_mtime_ns, before)

    def test_symlink_or_hardlink_replacement_is_skipped(self):
        for replacement in ['file-symlink', 'directory-symlink', 'hardlink']:
            with self.subTest(replacement=replacement):
                source = self.write(replacement + '/file')
                records = timestamps.snapshot_timestamps(self.root, [replacement + '/file'])
                outside = self.root.parent / replacement
                outside.mkdir()
                target = outside / 'file'
                target.write_bytes(b'same')
                before = target.stat().st_mtime_ns
                source.unlink()
                if replacement == 'file-symlink':
                    source.symlink_to(target)
                elif replacement == 'directory-symlink':
                    source.parent.rmdir()
                    source.parent.symlink_to(outside, target_is_directory=True)
                else:
                    os.link(target, source)
                self.assertEqual(timestamps.restore_timestamps(self.root, records), 0)
                self.assertEqual(target.stat().st_mtime_ns, before)

    def test_mutation_during_hash_is_skipped(self):
        path = self.write('file')
        original_read = os.read
        def mutate(fd, count):
            data = original_read(fd, count)
            if data:
                path.write_bytes(b'edit')
            return data
        with patch.object(timestamps.os, 'read', side_effect=mutate):
            self.assertEqual(timestamps.snapshot_timestamps(self.root, ['file']), {})

    def test_restore_uses_verified_descriptor_if_path_is_replaced(self):
        path = self.write('file')
        records = timestamps.snapshot_timestamps(self.root, ['file'])
        original = timestamps._stable_record
        def replace(fd):
            record = original(fd)
            path.unlink()
            path.write_bytes(b'replacement')
            os.utime(path, ns=(5_000_000_000, 6_000_000_000))
            return record
        with patch.object(timestamps, '_stable_record', side_effect=replace):
            timestamps.restore_timestamps(self.root, records)
        self.assertEqual(path.stat().st_mtime_ns, 6_000_000_000)


    @unittest.skipUnless(shutil.which('quilt') and shutil.which('ninja'), 'requires Quilt and Ninja')
    def test_real_quilt_replay_keeps_unchanged_ninja_edge_clean(self):
        patches = self.root.parent / 'patches'
        patches.mkdir()
        (patches / 'series.merged').write_text('header.patch\n')
        (patches / 'header.patch').write_text(
            '--- a/header.h\n+++ b/header.h\n@@ -1 +1 @@\n-base\n+patched\n')
        header = self.write('header.h', b'base\n')
        environment = os.environ.copy()
        environment.update(QUILT_PATCHES=str(patches), QUILT_SERIES='series.merged',
                           QUILT_PATCH_OPTS='--fuzz=0')
        def quilt(*args):
            subprocess.run(['quilt', '--quiltrc', '-', *args], cwd=self.root,
                           env=environment, check=True, capture_output=True)
        def ninja(*args):
            return subprocess.run(['ninja', *args], cwd=self.root, check=True,
                                  capture_output=True, text=True).stdout
        # A partial stack only owns the applied prefix; later additions are absent.
        (patches / 'series.merged').write_text('header.patch\nnew.patch\n')
        (patches / 'new.patch').write_text(
            '--- /dev/null\n+++ b/new.h\n@@ -0,0 +1 @@\n+new\n')
        quilt('push')
        with patch.dict(os.environ, {'HELIUM_DEV_GENERATED_PATCH_ROOT': str(patches)}):
            self.assertEqual(replay._patch_owned_paths(self.root.parent, self.root), ['header.h'])
        quilt('push', '-a')
        # Backdate only this fixture input to avoid filesystem clock granularity.
        os.utime(header, ns=(1_000_000_000, 2_000_000_000))
        (self.root / 'build.ninja').write_text(
            'rule copy\n  command = cp $in $out\nbuild output: copy header.h\n')
        ninja()
        clean_plan = ninja('-n')
        self.assertIn('no work to do', clean_plan)
        with patch.dict(os.environ, {'HELIUM_DEV_GENERATED_PATCH_ROOT': str(patches)}):
            paths = replay._patch_owned_paths(self.root.parent, self.root)
            records = timestamps.snapshot_timestamps(self.root, paths)
            proof_before = replay._patched_tree_sha256(self.root.parent, self.root)
            quilt('pop', '-a')
            quilt('push', '-a')
            # Make the replay-induced dirty edge deterministic even on coarse clocks.
            output_time = (self.root / 'output').stat().st_mtime_ns
            os.utime(header, ns=(output_time + 2_000_000_000, output_time + 2_000_000_000))
            self.assertIn('[1/1]', ninja('-n'))
            self.assertEqual(timestamps.restore_timestamps(self.root, records), 2)
            self.assertEqual(ninja('-n'), clean_plan)
            self.assertEqual(replay._patched_tree_sha256(self.root.parent, self.root), proof_before)
            header.write_bytes(b'changed\n')
            os.utime(header, ns=(output_time + 2_000_000_000, output_time + 2_000_000_000))
            self.assertEqual(timestamps.restore_timestamps(self.root, records), 1)
            self.assertIn('[1/1]', ninja('-n'))


class ReplayTransactionTests(unittest.TestCase):
    def test_success_and_failures_restore_only_after_validation_before_proof(self):
        for failure in [None, 'pop', 'push', 'validation', 'identity']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'src'
                source.mkdir()
                (root / 'patches').mkdir()
                (root / 'patches/series.merged').write_text('a.patch\n')
                events = []
                identity = object()
                comparison = SimpleNamespace(applied=['a.patch'], require_valid_prefix=lambda: None)
                def run(_source, env, *args):
                    self.assertIn('--fuzz=0', env['QUILT_PATCH_OPTS'])
                    events.append(args[0])
                    return subprocess.CompletedProcess(args, int(failure == args[0]))
                def validate(*args):
                    events.append('validate')
                    if failure == 'validation':
                        raise replay.ReplayError('invalid replay')
                receipt = SimpleNamespace(source=identity)
                with patch.object(replay, '_require_core_patch_copies'), \
                     patch.object(replay, 'inspect_quilt_state', return_value=SimpleNamespace(comparison=comparison)), \
                     patch.object(replay, 'current_source_identity', side_effect=[identity, object() if failure == 'identity' else identity]), \
                     patch.object(replay, 'invalidate_downstream_receipts', side_effect=lambda *_: events.append('invalidate')), \
                     patch.object(replay, '_patch_owned_paths', return_value=['file']), \
                     patch.object(replay, 'snapshot_timestamps', side_effect=lambda *_: events.append('snapshot') or {}), \
                     patch.object(replay, '_run_quilt', side_effect=run), \
                     patch.object(replay, '_validate_replayed_state', side_effect=validate), \
                     patch.object(replay, 'restore_timestamps', side_effect=lambda *_: events.append('restore')), \
                     patch.object(replay, '_write_proof', side_effect=lambda *_: events.append('proof') or receipt):
                    if failure:
                        with self.assertRaises(replay.ReplayError):
                            replay.replay(root, source)
                        self.assertNotIn('restore', events)
                        self.assertNotIn('proof', events)
                    else:
                        self.assertIs(replay.replay(root, source), receipt)
                        self.assertEqual(events, ['invalidate', 'snapshot', 'pop', 'push', 'validate', 'restore', 'proof'])

    def test_busy_lane_prevents_direct_replay(self):
        from build_lane import acquire_lane_lock
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with acquire_lane_lock(root / '.arcium/lane.lock', {'action': 'fixture'}), \
                 patch.object(replay, 'replay') as execute:
                self.assertEqual(replay.main(['replay', '--worktree', str(root),
                                              '--source', str(root / 'src')]), 2)
                execute.assert_not_called()

    def test_both_entrypoints_hold_lock_during_replay(self):
        import helium_dev
        for entry in ['cli', 'harness']:
            events = []
            @contextmanager
            def lock(*args):
                events.append('lock')
                yield 1
                events.append('unlock')
            def execute(*args):
                self.assertEqual(events, ['lock'])
                events.append('replay')
                return SimpleNamespace(receipt_id='proof')
            module = replay if entry == 'cli' else helium_dev
            with patch.object(module, 'acquire_lane_lock', side_effect=lock), \
                 patch.object(module, 'replay' if entry == 'cli' else 'replay_quilt', side_effect=execute):
                if entry == 'cli':
                    self.assertEqual(replay.main(['replay', '--worktree', '/tmp/fixture', '--source', '/tmp/fixture/build/src']), 0)
                else:
                    helium_dev.replay_action('/tmp/fixture')
            self.assertEqual(events, ['lock', 'replay', 'unlock'])


if __name__ == '__main__':
    unittest.main()
