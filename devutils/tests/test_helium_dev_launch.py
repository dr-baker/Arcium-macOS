"""Launch receipts must belong to the child and profile we actually started."""

import itertools
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import helium_dev
from helium_dev_runtime import ProfileSpec
from build_execution import capture_material_inputs
from devutils.tests.test_build_receipt import material_fixture


class DevLaunchTests(unittest.TestCase):
    def test_receipt_requires_launched_pid_and_profile_owner(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        material_fixture(root)
        paths = SimpleNamespace(worktree=root, executable_path=root / 'Helium', source_dir=root / 'build/src')
        profile = ProfileSpec('isolated', 'test', root / 'profile')
        material_at_entry = capture_material_inputs(root)
        for observed, owner, exited in ((123, 123, False), (456, 123, False),
                                        (123, 456, False), (123, None, False),
                                        (123, 123, True)):
            child = Mock(pid=123)
            child.poll.return_value = 0 if exited else None
            snapshot = f'{observed} {paths.executable_path} --user-data-dir={profile.user_data_dir}'
            with self.subTest(observed=observed, owner=owner, exited=exited), \
                 patch('helium_dev._prepare_selected_profile'), \
                 patch('helium_dev.manifest_path_for', return_value=Path('/fixture/receipt.json')), \
                 patch('helium_dev._ps_snapshot', side_effect=itertools.chain([''], itertools.repeat(snapshot))), \
                 patch('helium_dev.live_singleton_owner', side_effect=itertools.chain([None], itertools.repeat(owner))), \
                 patch('helium_dev.subprocess.Popen', return_value=child), \
                 patch('helium_dev.time.monotonic', side_effect=itertools.count()), \
                 patch('helium_dev.time.sleep'), \
                 patch('helium_dev.os.killpg') as kill, \
                 patch('helium_dev._process_started_at', return_value=0), \
                 patch('helium_dev._manifest_for', return_value={'ok': True}), \
                 patch('helium_dev.write_manifest_atomic') as write:
                if observed == owner == 123 and not exited:
                    result = helium_dev._run_locked(paths, profile, (), action='run', registry_root=root / 'registry', material_at_entry=material_at_entry)
                    self.assertTrue(result['ok'])
                    write.assert_called_once()
                    kill.assert_not_called()
                else:
                    with self.assertRaises(helium_dev.HarnessError):
                        helium_dev._run_locked(paths, profile, (), action='run', registry_root=root / 'registry', material_at_entry=material_at_entry)
                    write.assert_not_called()
                    if exited:
                        kill.assert_not_called()
                    else:
                        self.assertEqual(kill.call_args.args[0], child.pid)


if __name__ == '__main__':
    unittest.main()
