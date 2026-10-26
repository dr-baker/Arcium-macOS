"""Native attribution, streaming output, evidence failures, and clock scopes."""
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from he import agent, evidence, resources
from he.common import HeError, Paths, read_json, sha256_file


class NativeMetricsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file=Path(self.temp.name)/'metrics.json'

    def write(self, records):
        self.file.write_text(''.join(json.dumps(x)+'\n' for x in records))

    def test_parallel_action_time_is_separate_from_last_native_wall(self):
        self.write([dict(build_id='one',duration_nanos=100),
            dict(step_id='a',duration_nanos=1000000000,exec_nanos=1000000000,is_local=True,max_rss=2000),
            dict(step_id='b',duration_nanos=1000000000,exec_nanos=1000000000,is_remote=True),
            dict(build_id='one',duration_nanos=1500000000)])
        value=evidence.summarize_metrics(self.file,'one')
        self.assertTrue(value['available'])
        self.assertEqual(value['native_wall_seconds'],1.5)
        self.assertEqual(value['action_timings']['exec']['total_action_seconds'],2)
        self.assertEqual(value['counts']['steps'],2)
        self.assertEqual(value['max_local_command_rss_bytes'],2000)
        self.assertIsNone(value['client_input_upload_seconds'])
        self.assertIsNone(value['action_timings']['input_fetch']['total_action_seconds'])

    def test_stale_mixed_and_missing_summary_are_unknown(self):
        for records in ([dict(step_id='a',is_local=True,max_rss=100)],
                        [dict(build_id='old',duration_nanos=100)],
                        [dict(build_id='one',duration_nanos=100),dict(step_id='a',duration_nanos=500)],
                        [dict(build_id='one',duration_nanos=100),dict(build_id='old',duration_nanos=200)]):
            with self.subTest(records=records):
                self.write(records)
                value=evidence.summarize_metrics(self.file,'one')
                self.assertFalse(value['available'])
                self.assertNotIn('counts',value)

    def test_cpu_is_local_command_rusage_and_missing_is_unknown(self):
        self.write([dict(step_id='a',is_local=True,utime_nanos=2e9,stime_nanos=1e9),
                    dict(step_id='b',is_remote=True,utime_nanos=99e9,stime_nanos=99e9),
                    dict(step_id='c',is_local=True),dict(build_id='one',duration_nanos=1e9)])
        cpu=evidence.summarize_metrics(self.file,'one')['local_command_cpu']
        self.assertEqual(cpu['total_seconds'],3)
        self.assertEqual(cpu['actions_measured'],1)
        self.assertEqual(cpu['local_actions'],2)
        self.write([dict(step_id='b',is_remote=True),dict(build_id='one',duration_nanos=1e9)])
        self.assertIsNone(evidence.summarize_metrics(self.file,'one')['local_command_cpu']['total_seconds'])

    def test_truncated_tail_is_not_a_complete_metrics_file(self):
        self.write([dict(build_id='one',duration_nanos=100)])
        with self.file.open('a') as f:
            f.write('{"step_id":')
        self.assertFalse(evidence.summarize_metrics(self.file,'one')['available'])

    def test_reservoir_memory_is_bounded_and_quantiles_are_labeled(self):
        values=evidence.Distribution()
        for index in range(20000):
            values.add(index)
        self.assertEqual(len(values.values),4096)
        self.assertEqual(values.report()['quantiles'],'reservoir_sample_4096')
        self.assertEqual(values.count,20000)


class EvidenceExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name).resolve()
        self.paths=Paths(root,root/'build')
        self.paths.out.mkdir(parents=True)
        self.sensors=SimpleNamespace(sample=lambda:resources.Sample(10,80,0))
        self.last_result=None

    def build(self, script, *, capture=True, phase='build'):
        @evidence.recorded_build
        def run(paths,targets):
            self.last_result=resources.run(paths,[sys.executable,'-c',script],jobs=2,
                sensors=self.sensors,interval=.01,capture_output=capture,phase=phase)
            return self.last_result.returncode
        status=run(self.paths,['real-test-target'])
        manifest=list((self.paths.state/'build-evidence').glob('*/manifest.json'))[-1]
        return status,manifest.parent,read_json(manifest)

    def test_large_interleaved_binary_output_without_final_newline_is_lossless(self):
        script="import os\nfor _ in range(32):\n os.write(1,b'a'*32768+b'\\xff')\n os.write(2,b'b'*32768+b'\\xfe')\n"
        status,directory,manifest=self.build(script)
        self.assertEqual(status,0)
        self.assertEqual(manifest['evidence_status'],'complete')
        self.assertEqual((directory/'00-build/stdout.txt').read_bytes(),(b'a'*32768+b'\xff')*32)
        self.assertEqual((directory/'00-build/stderr.txt').read_bytes(),(b'b'*32768+b'\xfe')*32)
        self.assertIn('\ufffd',self.last_result.stdout)
        phase=next(p for p in manifest['phases'] if p['name']=='build')
        self.assertGreaterEqual(phase['duration_seconds'],phase['attributes']['child_wall_seconds'])
        self.assertEqual(manifest['build_status'],'success')
        self.assertTrue((directory/'phases.trace.json').is_file())
        self.assertNotIn('environment',manifest)

    def test_large_plan_is_lossless_and_guard_counts_full_spool_not_excerpt(self):
        script=("import os\nos.write(1,b'rebuild manifest finished\\n')\n"
                "for _ in range(4096): os.write(1,b'clang '+b'x'*8192+b'\\n')\n"
                "os.write(1,b'build finished\\n')\n")
        status,directory,manifest=self.build(script,phase='plan')
        self.assertEqual(status,0)
        self.assertEqual(manifest['evidence_status'],'complete')
        self.assertGreater(self.last_result.stdout_path.stat().st_size,32*1024*1024)
        self.assertLess(len(self.last_result.stdout),3*1024*1024)
        count,excerpt=agent.read_plan(self.paths,self.last_result)
        self.assertEqual(count,4096)
        full_hash=sha256_file(self.paths.state/'last-plan.txt')
        with self.assertRaisesRegex(HeError,'4096 edges'):
            agent.guard_build(self.paths,['chrome'],budget=500,approved=False,problems=[],
                              output=excerpt,edge_count=count,plan_saved=True)
        self.assertEqual(sha256_file(self.paths.state/'last-plan.txt'),full_hash)
        self.assertEqual(full_hash,sha256_file(self.last_result.stdout_path))

    def test_broken_console_does_not_change_successful_build_exit(self):
        class Broken:
            def write(self,data):
                raise BrokenPipeError()
            def flush(self):
                pass
        with patch('sys.stdout',Broken()):
            status,directory,manifest=self.build("print('complete')",capture=False)
        self.assertEqual(status,0)
        self.assertEqual(manifest['build_status'],'success')
        self.assertEqual(manifest['evidence_status'],'incomplete')
        self.assertEqual((directory/'00-build/stdout.txt').read_text(),'complete\n')

    def test_disk_full_sink_keeps_draining_and_preserves_build_result(self):
        original=Path.open
        class Full:
            def write(self,data):
                raise OSError(errno.ENOSPC,'full')
            def close(self):
                pass
        def open_file(path,*args,**kwargs):
            if path.name=='stdout.txt' and args and args[0]=='wb':
                return Full()
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',open_file), patch('sys.stdout'):
            status,directory,manifest=self.build("import os;os.write(1,b'x'*1000000)",capture=False)
        self.assertEqual(status,0)
        self.assertEqual(manifest['evidence_status'],'incomplete')
        self.assertEqual(manifest['build_status'],'success')

    def test_sigterm_while_streaming_is_failed_and_finalized(self):
        script="import os,signal,time;os.write(1,b'partial');os.kill(os.getppid(),signal.SIGTERM);time.sleep(30)"
        status,directory,manifest=self.build(script)
        self.assertEqual(status,143)
        self.assertEqual(manifest['build_status'],'failed')
        self.assertEqual(manifest['returncode'],143)
        self.assertTrue((directory/'00-build/stdout.txt').is_file())

    def test_initial_evidence_failure_prevents_launch(self):
        with patch('he.evidence.BuildEvidence',side_effect=OSError('not writable')):
            with self.assertRaisesRegex(Exception,'cannot create durable'):
                self.build("raise RuntimeError('must never run')")
        self.assertIsNone(self.last_result)

    def test_unrelated_native_build_is_unattributed_even_when_files_changed(self):
        trace=evidence.BuildEvidence(self.paths,['chrome'],{})
        directory=trace.directory/'phase'
        directory.mkdir()
        (self.paths.out/'siso_metadata.json').write_text(json.dumps({'build_id':'current'}))
        (self.paths.out/'siso_metrics.json').write_text(json.dumps({'build_id':'previous','duration_nanos':1})+'\n')
        value=trace.native(directory,{})
        trace.finish(0)
        self.assertFalse(value['available'])
        self.assertTrue((directory/'siso_metrics.json').is_file())
        self.assertNotIn('counts',value)

    def test_cleanup_failure_is_separate_from_successful_compilation(self):
        @evidence.recorded_build
        def run(paths,targets):
            result=resources.run(paths,[sys.executable,'-c','pass'],jobs=1,
                                 sensors=self.sensors,interval=.01,capture_output=True)
            with evidence.phase('worker_cleanup'):
                raise RuntimeError('stop failed')
        with self.assertRaisesRegex(RuntimeError,'stop failed'):
            run(self.paths,['chrome'])
        record=read_json(next((self.paths.state/'build-evidence').glob('*/manifest.json')))
        self.assertEqual(record['build_status'],'success')
        self.assertEqual(record['cleanup_status'],'error')
        self.assertEqual(record['outcome'],'exception')

    def test_native_archive_failure_does_not_replace_successful_build(self):
        with patch.object(evidence.BuildEvidence,'native',side_effect=AttributeError('bad metadata')):
            status,directory,record=self.build('pass')
        self.assertEqual(status,0)
        self.assertEqual(record['build_status'],'success')
        self.assertEqual(record['evidence_status'],'incomplete')

    def test_slow_console_does_not_block_resource_supervisor(self):
        import time
        class Slow:
            def write(self,data):
                time.sleep(2.5)
            def flush(self):
                pass
        started=time.monotonic()
        with patch('sys.stderr',Slow()):
            status,directory,record=self.build("import os;os.write(2,b'complete')",capture=False)
        self.assertEqual(status,0)
        self.assertLess(time.monotonic()-started,2.4)
        self.assertEqual(record['evidence_status'],'incomplete')
        self.assertEqual((directory/'00-build/stderr.txt').read_text(),'complete')

    def test_logging_directory_failure_cannot_prevent_cloud_cleanup(self):
        from cloud_build.gcp_remote import Cloud
        client=Cloud(SimpleNamespace(project='arcium-test-project',zone='us-central1-a',gcloud='/fake/gcloud',
                                    state_dir=self.paths.state/'cloud'))
        original=Path.mkdir
        def mkdir(path,*args,**kwargs):
            if path.name.startswith('cloud-'):
                raise OSError(errno.ENOSPC,'full')
            return original(path,*args,**kwargs)
        @evidence.recorded_build
        def run(paths,targets):
            with evidence.phase('worker_cleanup'):
                client.run('compute','instances','stop','worker')
            return 0
        with patch.object(Path,'mkdir',mkdir), patch.object(client,'_run',
                return_value=subprocess.CompletedProcess([],0,'stopped','')) as command:
            self.assertEqual(run(self.paths,['chrome']),0)
        command.assert_called_once()
        record=read_json(next((self.paths.state/'build-evidence').glob('*/manifest.json')))
        self.assertEqual(record['cleanup_status'],'ok')
        self.assertEqual(record['evidence_status'],'incomplete')


if __name__=='__main__':
    unittest.main()
