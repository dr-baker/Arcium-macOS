"""Exercise the real session rollback and recovery with a fake Cloud API."""
from contextlib import nullcontext
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import compile
from he.common import HeError, Paths, read_json
from cloud_build.gcp_remote import startup_script


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.paths = Paths(root, root / 'build')
        self.paths.state.mkdir(parents=True)
        self.config = dict(worker='arcium-build-'+'b'*20, project='arcium-test-project', zone='us-central1-a',
                           retain_boot=True,
                           credentials_dir=str(root / 'auth'))
        self.vm = None
        self.disk = None
        self.calls = []
        self.cloud = SimpleNamespace(name=self.config['worker'], state=root / 'cloud', env={},
                    resource_lock=lambda: nullcontext(), owned=lambda value: value,
                    describe=self.describe, create=self.create, run=self.cloud_run,
                    command=lambda *args: ['fake-cloud', *args])
        self.cloud.state.mkdir()
        self.tunnel = Mock(pid=12345)
        self.tunnel.poll.return_value = None
        patch('cloud_build.gcp_remote.Cloud', return_value=self.cloud).start()
        patch('he.compile.subprocess.Popen', return_value=self.tunnel).start()
        patch('he.compile.socket.create_connection', return_value=nullcontext()).start()
        probe = Mock()
        probe.getsockname.return_value = ('127.0.0.1', 55051)
        patch('he.compile.socket.socket', return_value=nullcontext(probe)).start()
        patch('he.compile.os.killpg').start()
        self.addCleanup(patch.stopall)
        self.session = compile.CloudSession(self.paths, self.config)

    def describe(self, *args, **kwargs):
        return self.vm if args[:2] == ('compute', 'instances') else self.disk

    def create(self):
        self.calls.append('create')
        self.vm = {'id': 'original', 'status': 'RUNNING',
                   'metadata': {'items': [{'key':'startup-script','value':startup_script()}]}}
        self.disk = {'id': 'cache'}

    def cloud_run(self, *args, **kwargs):
        if args[:2] == ('compute', 'instances'):
            self.calls.append(args[2])
            if args[2] == 'delete':
                self.vm = None
            elif args[2] == 'stop':
                self.vm['status'] = 'TERMINATED'
            elif args[2] == 'start':
                self.vm['status'] = 'RUNNING'
        elif args[:2] == ('compute', 'disks'):
            self.calls.append('delete-cache')
            self.disk = None
        return SimpleNamespace(returncode=0)

    def test_success_stops_new_vm_and_preserves_cache(self):
        self.session.start()
        record = read_json(self.session.journal)
        self.assertEqual(record['phase'], 'building')
        self.assertEqual(record['instance_id'], 'original')
        self.session.close()
        self.assertEqual(self.calls, ['create', 'stop'])
        self.assertIsNotNone(self.disk)
        self.assertFalse(self.session.journal.exists())

    def test_cache_only_removes_created_vm_preserves_cache_and_borrowed_vm(self):
        self.config['retain_boot'] = False
        self.session.start()
        self.session.close()
        self.assertEqual(self.calls, ['create', 'delete'])
        self.assertIsNotNone(self.disk)
        self.calls.clear()
        self.vm = {'id':'old', 'status':'TERMINATED',
                   'metadata':{'items':[{'key':'startup-script','value':startup_script()}]}}
        self.session = compile.CloudSession(self.paths,self.config)
        self.session.start()
        self.session.close()
        self.assertEqual(self.calls, ['start', 'stop'])

    def test_borrowed_running_worker_is_not_stopped(self):
        self.vm = {'id': 'borrowed', 'status': 'RUNNING',
                   'metadata': {'items': [{'key':'startup-script','value':startup_script()}]}}
        self.disk = {'id': 'existing-cache'}
        self.session.start()
        self.session.close()
        self.assertEqual(self.calls, [])

    def test_outdated_bootstrap_fails_before_mutating_running_or_stopped_worker(self):
        for state in ('RUNNING','TERMINATED'):
            with self.subTest(state=state):
                self.vm = {'id':'retained','status':state,
                           'metadata':{'items':[{'key':'startup-script','value':'old bootstrap'}]}}
                self.disk = {'id':'retained-cache'}
                with self.assertRaisesRegex(HeError,'without --delete-cache'):
                    self.session.start()
                self.session.close(failed_start=True)
                self.assertEqual(self.calls,[])
                self.assertFalse(self.session.journal.exists())
                self.assertEqual(self.vm['status'],state)
                self.assertEqual(self.disk['id'],'retained-cache')

    def test_fresh_iap_visibility_is_retried_before_persistent_tunnel(self):
        attempts=[]
        original=self.cloud.run
        def probe(*args,**kwargs):
            if args[:2]==('compute','ssh'):
                attempts.append(kwargs['timeout'])
                return SimpleNamespace(returncode=255 if len(attempts)==1 else 0,
                                       stderr='IAP 4047 Failed to lookup instance',stdout='')
            return original(*args,**kwargs)
        self.cloud.run=probe
        def tunnel(*args,**kwargs):
            self.assertEqual(len(attempts),2)
            return self.tunnel
        with patch('he.compile.time.sleep'), patch('he.compile.subprocess.Popen',side_effect=tunnel):
            self.session.start()
        self.assertEqual(read_json(self.session.journal)['phase'],'building')
        self.assertTrue(all(0<t<=20 for t in attempts))
        self.session.close()
        self.assertEqual(self.calls,['create','stop'])

    def test_reported_bootstrap_failure_stops_readiness_without_retrying(self):
        original=self.cloud.run
        def run(*args,**kwargs):
            if args[:2]==('compute','ssh'):
                return SimpleNamespace(returncode=70,stderr='ARCIUM_BOOTSTRAP_FAILED',stdout='')
            return original(*args,**kwargs)
        self.cloud.run=run
        with patch('he.compile.time.sleep') as sleep:
            with self.assertRaisesRegex(HeError,'bootstrap failed'):
                self.session.start()
            sleep.assert_not_called()
        self.session.close(failed_start=True)
        self.assertEqual(self.calls,['create','delete','delete-cache'])

    def test_unready_worker_exhausts_one_deadline_and_rolls_back(self):
        original=self.cloud.run
        def unready(*args,**kwargs):
            if args[:2]==('compute','ssh'):
                return SimpleNamespace(returncode=255,stdout='',stderr='IAP 4047')
            return original(*args,**kwargs)
        self.cloud.run=unready
        now=[0]
        with patch('he.compile.time.monotonic',side_effect=lambda:now[0]), \
             patch('he.compile.time.sleep',side_effect=lambda n:now.__setitem__(0,now[0]+n)), \
             patch('he.compile.subprocess.Popen') as tunnel:
            with self.assertRaisesRegex(HeError,'five minutes'):
                self.session.start()
            tunnel.assert_not_called()
        self.assertEqual(now[0],300)
        self.session.close(failed_start=True)
        self.assertEqual(self.calls,['create','delete','delete-cache'])

    def test_failed_creation_removes_new_orphan_disk(self):
        def partial():
            self.disk = {'id': 'new-cache'}
            raise HeError('allocation declined after disk creation')
        self.cloud.create = partial
        with self.assertRaises(HeError):
            self.session.start()
        self.session.close(failed_start=True)
        self.assertEqual(self.calls, ['delete-cache'])
        self.assertFalse(self.session.journal.exists())

    def test_ambiguous_api_timeout_requires_recovery_before_fallback(self):
        self.cloud.create = Mock(side_effect=subprocess.TimeoutExpired(['gcloud'], 180))
        with self.assertRaises(subprocess.TimeoutExpired):
            self.session.start()
        with self.assertRaisesRegex(HeError, 'explicit reconciliation'):
            self.session.close(failed_start=True)
        self.assertTrue(read_json(self.session.journal)['ambiguous_operation'])

    def test_failed_start_preserves_existing_cache(self):
        self.disk = {'id': 'existing-cache'}
        self.session.start()
        self.session.close(failed_start=True)
        self.assertEqual(self.calls, ['create', 'delete'])
        self.assertIsNotNone(self.disk)

    def test_tunnel_cleanup_error_still_stops_vm_and_keeps_journal(self):
        self.session.start()
        with patch('he.compile.os.killpg', side_effect=OSError('tunnel signal failure')):
            with self.assertRaisesRegex(HeError, 'cleanup incomplete'):
                self.session.close()
        self.assertIn('stop', self.calls)
        self.assertTrue(self.session.journal.exists())
        self.assertIsNone(self.session.lock)

    def test_instance_replacement_is_never_stopped(self):
        self.session.start()
        self.vm['id'] = 'replacement'
        with self.assertRaisesRegex(HeError, 'identity changed'):
            self.session.close()
        self.assertNotIn('stop', self.calls)
        self.assertTrue(self.session.journal.exists())

    def test_sigterm_during_tunnel_start_rolls_back_vm(self):
        import os
        with patch('he.compile.subprocess.Popen', side_effect=lambda *a, **kw: os.kill(os.getpid(), signal.SIGTERM)):
            with self.assertRaises(compile.Interrupted), compile.interruptions():
                self.session.start()
        self.session.close(failed_start=True)
        self.assertEqual(self.calls, ['create', 'delete', 'delete-cache'])


if __name__ == '__main__':
    unittest.main()
