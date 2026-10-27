import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('studio_run', Path(__file__).resolve().parents[1] / 'run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.build_patch = patch.object(runner, 'BUILD', self.build)
        self.build_patch.start(); self.addCleanup(self.build_patch.stop)
        self.old = {'pid': 123, 'executable': '/old/Studio.app/Contents/MacOS/ArciumCommandBarStudio'}
        self.identity = patch.object(runner, 'process_executable',
                                     return_value=Path(self.old['executable']), create=True)
        self.identity_mock = self.identity.start(); self.addCleanup(self.identity.stop)
        (self.build / 'running.json').write_text(json.dumps(self.old))
        self.app = self.build / 'new/Studio.app'

    def ready_process(self, *args, **kwargs):
        (self.build / 'launch-ready.json').write_text(json.dumps({'pid': 456, 'bundle': str(self.app)}))
        return Mock(pid=456, poll=Mock(return_value=None))

    def testCrashingReplacementDoesNotQuitOldApp(self):
        with patch.object(runner.subprocess, 'Popen', return_value=Mock(returncode=-5, poll=Mock(return_value=-5))), patch.object(runner, 'command') as command:
            with self.assertRaisesRegex(RuntimeError, 'previous app was left open'):
                runner.launch(self.app)
            command.assert_not_called()
        self.assertEqual(json.loads((self.build / 'running.json').read_text()), self.old)

    def testReadyReplacementNormallyQuitsOnlyRecordedPid(self):
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), patch.object(runner, 'command') as command:
            runner.launch(self.app)
            command.assert_called_once_with([self.app / 'Contents/MacOS/ArciumCommandBarStudio', '--quit-owned', '123', self.old['executable']])
        self.assertEqual(json.loads((self.build / 'running.json').read_text())['pid'], 456)

    def testRefusedOldQuitClosesReplacementAndKeepsOldRecord(self):
        failure = subprocess.CalledProcessError(2, ['quit'])
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), patch.object(runner, 'command', side_effect=[failure, None]) as command:
            with self.assertRaisesRegex(RuntimeError, 'replacement was closed'):
                runner.launch(self.app)
            self.assertEqual(command.call_args_list[1].args[0][2], '456')
        self.assertEqual(json.loads((self.build / 'running.json').read_text()), self.old)

    def testReusedPidDoesNotQuitUnrelatedProcessOrBlockReplacement(self):
        self.identity_mock.return_value = Path('/unrelated/Browser')
        def quit_owned(arguments):
            if arguments[2] == '123':
                raise subprocess.CalledProcessError(2, arguments)
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), \
             patch.object(runner, 'command', side_effect=quit_owned) as command:
            runner.launch(self.app)
            command.assert_not_called()
        self.assertEqual(json.loads((self.build / 'running.json').read_text())['pid'], 456)

    def testUnknownPidIdentityStillRequiresGuardedQuit(self):
        self.identity_mock.return_value = None
        failure = subprocess.CalledProcessError(2, ['quit'])
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), \
             patch.object(runner, 'command', side_effect=[failure, None]) as command:
            with self.assertRaisesRegex(RuntimeError, 'replacement was closed'):
                runner.launch(self.app)
            self.assertEqual(command.call_args_list[0].args[0][2], '123')
            self.assertEqual(command.call_args_list[1].args[0][2], '456')
        self.assertEqual(json.loads((self.build / 'running.json').read_text()), self.old)

    def testSupersededDuringReadinessClosesOnlyCandidateAndKeepsWriter(self):
        lease = self.build / 'writer'; lease.write_text('123')
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), patch.object(runner, 'command') as command:
            with self.assertRaisesRegex(RuntimeError, 'superseded'):
                runner.launch(self.app, before_replace=Mock(side_effect=RuntimeError('superseded')), writer_lease=lease)
            command.assert_called_once_with([self.app / 'Contents/MacOS/ArciumCommandBarStudio', '--quit-owned', '456', str(self.app / 'Contents/MacOS/ArciumCommandBarStudio')])
        self.assertEqual(lease.read_text(), '123')
        self.assertEqual(json.loads((self.build / 'running.json').read_text()), self.old)

    def testCancellationDuringReadinessClosesOnlyCandidate(self):
        lease = self.build / 'writer'; lease.write_text('123')
        process = Mock(pid=456, poll=Mock(return_value=None))
        with patch.object(runner.subprocess, 'Popen', return_value=process), \
             patch.object(runner.time, 'sleep', side_effect=KeyboardInterrupt), \
             patch.object(runner, 'command') as command:
            with self.assertRaises(KeyboardInterrupt):
                runner.launch(self.app, writer_lease=lease)
            command.assert_called_once_with([self.app / 'Contents/MacOS/ArciumCommandBarStudio',
                '--quit-owned', '456', str(self.app / 'Contents/MacOS/ArciumCommandBarStudio')])
        self.assertEqual(lease.read_text(), '123')
        self.assertEqual(json.loads((self.build / 'running.json').read_text()), self.old)

    def testScenarioWriterTransfersOnlyAfterPreviousAppQuit(self):
        lease = self.build / 'writer'; lease.write_text('123')
        def quit_owned(arguments): self.assertEqual(lease.read_text(), '123')
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process), patch.object(runner, 'command', side_effect=quit_owned):
            runner.launch(self.app, writer_lease=lease)
        self.assertEqual(lease.read_text(), '456')

    def testScenarioArgumentsBelongToNewProcess(self):
        with patch.object(runner.subprocess, 'Popen', side_effect=self.ready_process) as popen, patch.object(runner, 'command'):
            runner.launch(self.app, extra_args=('--scenario-file=/isolated/scenario.json',))
            self.assertIn('--scenario-file=/isolated/scenario.json', popen.call_args.args[0])

    def testWatcherIncludesNativeAndResourceInputs(self):
        inputs = runner.watch_files()
        for file in [runner.LAB / 'run.py', runner.ROOT / 'resources/platform_resources.txt', runner.ROOT / 'devutils/glass-lab/Sources/GlassNative/include/GlassNative.h']:
            self.assertIn(str(file), inputs)
        self.assertNotIn(str(runner.LAB / 'Sources/ArciumCommandBarStudio/ProductionContract.swift'), inputs)

    def testEditsDuringInitialWatchBuildAreRebuilt(self):
        revision = {'value': 1}
        def build(jobs):
            revision['value'] = 2
            return self.app
        with patch.object(runner.sys, 'argv', ['run.py', 'watch', '--jobs', '2']), \
             patch.object(runner, 'build', side_effect=build) as builds, \
             patch.object(runner, 'launch'), \
             patch.object(runner, 'watch_files', side_effect=lambda: {'input': revision['value']}), \
             patch.object(runner.time, 'sleep', side_effect=[None, None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt): runner.main()
            self.assertEqual(builds.call_count, 2)


if __name__ == '__main__': unittest.main()
