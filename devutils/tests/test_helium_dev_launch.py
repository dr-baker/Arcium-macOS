"""Launch receipts must belong to the child and profile we actually started."""

import itertools
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import helium_dev
from devutils.tests.test_build_receipt import material_fixture


class DevLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        material_fixture(self.root)
        self.home = self.root / 'home'
        self.registry = self.root / 'registry'
        self.profile = helium_dev.resolve_profile('isolated', 'test', home=self.home)
        self.paths = SimpleNamespace(
            worktree=self.root,
            executable_path=self.root / 'Helium',
            source_dir=self.root / 'build/src',
            app_path=self.root / 'Helium Dev.app',
            component_path=self.root / 'build/src/out/Default/libchrome_dll.dylib',
        )
        self.paths.component_path.parent.mkdir(parents=True)
        self.paths.component_path.write_bytes(b'fixture')
        self.manifest_path = helium_dev.manifest_path_for(self.profile, self.registry)
        self.write_manifest = helium_dev.write_manifest_atomic

    def run_fixture(self):
        return helium_dev.runtime_action(
            'run', str(self.root), ['--isolated', 'test', '--seed-from', 'empty'],
            home=self.home, registry_root=self.registry,
        )

    def foreign_manifest(self):
        return helium_dev.build_manifest(
            ok=True, run_id='other-run', action='run', main_pid=456, process_count=1,
            started_at=None, worktree=self.root, source_dir=self.paths.source_dir,
            app_path=self.paths.app_path, executable_path=self.paths.executable_path,
            profile=self.profile, manifest_path=self.manifest_path,
        )

    @contextmanager
    def controlled_launch(self, child, *, observed=123, owner=123):
        snapshot = f'{observed} {self.paths.executable_path} --user-data-dir={self.profile.user_data_dir}'
        with patch('helium_dev._prepare_selected_profile'), \
             patch('helium_dev.require_current_packaged_build'), \
             patch('helium_dev.resolve_worktree_paths', return_value=self.paths), \
             patch('helium_dev._ps_snapshot', side_effect=itertools.chain([''], itertools.repeat(snapshot))), \
             patch('helium_dev.live_singleton_owner', side_effect=itertools.chain([None], itertools.repeat(owner))), \
             patch('helium_dev.subprocess.Popen', return_value=child), \
             patch('helium_dev.time.monotonic', side_effect=itertools.count()), \
             patch('helium_dev.time.sleep'), \
             patch('helium_dev._process_started_at', return_value=0), \
             patch('helium_dev._quilt_top', return_value=('fixture.patch', [])), \
             patch('helium_dev.write_manifest_atomic', wraps=self.write_manifest) as write:
            yield write

    def test_receipt_requires_launched_pid_and_profile_owner(self):
        for observed, owner, exited in ((123, 123, False), (456, 123, False),
                                        (123, 456, False), (123, None, False),
                                        (123, 123, True)):
            child = Mock(pid=123, _child_created=True)
            child.poll.return_value = 0 if exited else None
            # A foreign observed main must survive even when our child ignores TERM.
            resistant = observed == 456
            if resistant:
                child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 2), 0]
            with self.subTest(observed=observed, owner=owner, exited=exited), \
                 self.controlled_launch(child, observed=observed, owner=owner) as write:
                if observed == owner == 123 and not exited:
                    result = self.run_fixture()
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['main_pid'], child.pid)
                    write.assert_called_once()
                    child.terminate.assert_not_called()
                    child.wait.assert_not_called()
                    self.assertFalse(child._child_created)
                else:
                    with self.assertRaises(helium_dev.HarnessError):
                        self.run_fixture()
                    write.assert_not_called()
                    if exited:
                        child.terminate.assert_not_called()
                    else:
                        child.terminate.assert_called_once_with()
                    if resistant:
                        child.kill.assert_called_once_with()
                        self.assertEqual(child.wait.call_count, 2)
                    else:
                        child.kill.assert_not_called()
                        child.wait.assert_called_once_with(timeout=2)

    def test_final_material_drift_removes_receipt_and_reaps_under_profile_lock(self):
        flags = self.root / 'flags.macos.gn'
        original_flags = flags.read_text()
        for boundary in ('publication', 'final-discovery'):
            flags.write_text(original_flags)
            child = Mock(pid=123, _child_created=True)
            child.poll.return_value = None

            def publish_then_drift(path, manifest):
                self.assertTrue(child._child_created)
                self.write_manifest(path, manifest)
                flags.write_text('changed after launch\n')

            snapshot_calls = itertools.count(1)
            snapshot = f'123 {self.paths.executable_path} --user-data-dir={self.profile.user_data_dir}'

            def discover_then_drift():
                call = next(snapshot_calls)
                if call == 3:
                    self.assertTrue(child._child_created)
                    self.assertTrue(self.manifest_path.exists())
                    flags.write_text('changed during final process discovery\n')
                return '' if call == 1 else snapshot

            def terminate_under_lock():
                with self.assertRaises(helium_dev.LockBusyError):
                    helium_dev.acquire_profile_lock(self.profile, root=self.registry)

            child.terminate.side_effect = terminate_under_lock
            with self.subTest(boundary=boundary), self.controlled_launch(child) as write, ExitStack() as stack:
                if boundary == 'publication':
                    write.side_effect = publish_then_drift
                else:
                    ps = stack.enter_context(patch('helium_dev._ps_snapshot', side_effect=discover_then_drift))
                with self.assertRaisesRegex(helium_dev.ExecutionError, 'material inputs changed'):
                    self.run_fixture()
                if boundary == 'final-discovery':
                    self.assertEqual(ps.call_count, 3)
            self.assertFalse(self.manifest_path.exists())
            self.assertTrue(child._child_created)
            child.terminate.assert_called_once_with()
            child.wait.assert_called_once_with(timeout=2)
            lock = helium_dev.acquire_profile_lock(self.profile, root=self.registry)
            self.assertTrue(lock.release())

    def test_write_failure_preserves_prior_foreign_manifest(self):
        foreign = self.foreign_manifest()
        self.write_manifest(self.manifest_path, foreign)
        child = Mock(pid=123, _child_created=True)
        child.poll.return_value = None
        with self.controlled_launch(child) as write:
            write.side_effect = OSError('fixture publication failed')
            with self.assertRaisesRegex(OSError, 'fixture publication failed'):
                self.run_fixture()
        self.assertEqual(helium_dev.read_manifest(self.manifest_path), foreign)
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=2)

    def test_final_profile_owner_change_preserves_foreign_manifest(self):
        child = Mock(pid=123, _child_created=True)
        child.poll.return_value = None
        foreign = self.foreign_manifest()

        def replaced_write(path, manifest):
            self.write_manifest(path, manifest)
            self.write_manifest(path, foreign)

        with self.controlled_launch(child) as write, patch(
            'helium_dev.live_singleton_owner', side_effect=[None, 123, 456]
        ):
            write.side_effect = replaced_write
            with self.assertRaisesRegex(helium_dev.HarnessError, 'lost its verified browser'):
                self.run_fixture()
        self.assertEqual(helium_dev.read_manifest(self.manifest_path), foreign)
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=2)

    def test_interrupted_publication_removes_only_its_own_manifest(self):
        for replace in (False, True):
            child = Mock(pid=123, _child_created=True)
            child.poll.return_value = None
            foreign = self.foreign_manifest()

            def interrupted_write(path, manifest):
                self.write_manifest(path, manifest)
                if replace:
                    self.write_manifest(path, foreign)
                raise KeyboardInterrupt

            with self.subTest(concurrent_replacement=replace), self.controlled_launch(child) as write:
                write.side_effect = interrupted_write
                with self.assertRaises(KeyboardInterrupt):
                    self.run_fixture()
            if replace:
                self.assertEqual(helium_dev.read_manifest(self.manifest_path), foreign)
            else:
                self.assertFalse(self.manifest_path.exists())
            child.terminate.assert_called_once_with()
            child.wait.assert_called_once_with(timeout=2)


if __name__ == '__main__':
    unittest.main()
