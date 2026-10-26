"""Local-first dispatch, policy boundaries, and worker failure recovery."""
from contextlib import nullcontext
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import agent, compile, remote
from he.common import HeError, Paths, read_json, write_json


class RoutingTest(unittest.TestCase):
    def test_client_limits_preserve_stricter_caps_and_unrelated_settings(self):
        value=remote.client_limits({'SISO_LIMITS':'preproc=1,scandeps=5,custom=7,local=1'})
        self.assertEqual(value['SISO_LIMITS'],'custom=7,local=1,preproc=1,scandeps=2')
        for setting in ('preproc=0','scandeps=no','local=-1'):
            with self.assertRaises(HeError):remote.client_limits({'SISO_LIMITS':setting})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.paths = Paths(root, root / 'build')
        self.paths.out.mkdir(parents=True)
        (self.paths.out / 'args.gn').write_text('use_siso = true\nuse_remoteexec = true\nuse_reclient = false\n')
        self.config = dict(version=1, enabled=True, build_dir=str(self.paths.build_dir),
                           machine=remote.machine_identity(),
                           project='arcium-builds-test', zone='us-central1-a',
                           worker='arcium-build-' + 'a' * 20, threshold=500, remote_jobs=64,
                           auto_min_compiles=1, auto_basis='fixture measured crossover',
                           credentials_dir=str(root / 'credentials'))
        self.events = []
        test = self
        class Session:
            def __init__(self, paths, config):
                test.events.append('session')
            def start(self):
                test.events.append('start')
            def close(self, *, failed_start=False):
                test.events.append('rollback' if failed_start else 'stop')
        self.Session = Session
        self.runner = patch('he.compile.resources.run', side_effect=self.execute).start()
        self.addCleanup(patch.stopall)
        patch('he.compile.remote.require_ready').start()
        self.output = '[501/501] CXX obj/example.o\n'
        patch('he.compile.activity.sample', return_value=SimpleNamespace(record=lambda:{'state':'active'})).start()
        self.build_status = 0

    def enable(self):
        write_json(self.paths.state / 'remote-build.json', self.config)

    def execute(self, paths, command, **kwargs):
        self.events.append(('plan' if kwargs.get('phase') == 'plan' else 'build', command, kwargs))
        return subprocess.CompletedProcess(command, self.build_status if kwargs.get('phase') != 'plan' else 0,
                                           self.output if kwargs.get('phase') == 'plan' else '', '')

    def run_build(self, **kwargs):
        return compile.run(self.paths, ['chrome'], jobs=8, session_factory=self.Session, **kwargs)

    def test_default_local_has_no_plan_or_cloud_even_with_ambient_endpoint(self):
        with patch.dict(os.environ, SISO_REAPI_ADDRESS='untrusted:1234', SISO_CREDENTIAL_HELPER='secret-tool',
                        RBE_service_no_security='true'):
            self.assertEqual(self.run_build(), 0)
        self.assertEqual(len(self.events), 1)
        _, command, opts = self.events[0]
        self.assertIn('--offline', command)
        self.assertNotIn('SISO_REAPI_ADDRESS', opts['environment'])
        self.assertNotIn('SISO_CREDENTIAL_HELPER', opts['environment'])
        self.assertNotIn('RBE_service_no_security', opts['environment'])

    def test_small_and_boundary_plans_do_not_construct_cloud_client(self):
        self.enable()
        for count in (0, 1, 500):
            self.events.clear()
            self.output = f'[{count}/{count}] compile\n' if count else 'ninja: no work to do.\n'
            self.run_build()
            self.assertEqual([x[0] for x in self.events], ['plan', 'build'])
            self.assertIn('--offline', self.events[-1][1])

    def test_large_runs_once_remotely_with_independent_jobs_then_stops(self):
        self.enable()
        self.run_build(guarded=True, approved=True)
        self.assertEqual([e[0] if isinstance(e, tuple) else e for e in self.events],
                         ['plan', 'session', 'start', 'build', 'stop'])
        command = self.events[-2][1]
        self.assertNotIn('--offline', command)
        self.assertIn('-strict_remote', command)
        self.assertIn('-local_jobs={HELIUM_BUILD_JOBS}', command)
        self.assertIn('-remote_jobs=64', command)
        self.assertEqual(self.events[-2][2]['jobs'], 2)
        self.assertEqual(self.events[-2][2]['environment']['SISO_LIMITS'], 'local=2,preproc=2,scandeps=2')

    def test_manual_enrollment_never_allocates_automatically(self):
        self.config.pop('auto_min_compiles')
        self.enable()
        self.run_build(approved=True)
        self.assertEqual([x[0] for x in self.events], ['plan', 'build'])
        self.run_build(execution='remote', approved=True)
        self.assertIn('start', self.events)

    def test_idle_away_unknown_and_link_only_remain_local(self):
        self.enable()
        for state in ('idle', 'away', 'unknown'):
            self.events.clear()
            with patch('he.compile.activity.sample', return_value=SimpleNamespace(record=lambda:{'state':state})):
                self.run_build(approved=True)
            self.assertEqual([x[0] for x in self.events], ['plan', 'build'])
            self.assertEqual(self.events[-1][2]['jobs'], 8)
        self.events.clear()
        self.output = '[999/999] LINK chrome\n'
        self.run_build(approved=True)
        self.assertEqual([x[0] for x in self.events], ['plan', 'build'])

    def test_activity_is_rechecked_after_plan_and_immediately_before_allocation(self):
        self.enable()
        active = SimpleNamespace(record=lambda:{'state':'active'})
        idle = SimpleNamespace(record=lambda:{'state':'idle'})
        for readings in ([active,idle], [active,active,idle]):
            self.events.clear()
            with patch('he.compile.activity.sample', side_effect=readings):
                self.run_build(approved=True)
            self.assertEqual([x[0] for x in self.events], ['plan', 'build'])
            self.assertEqual(self.events[-1][2]['jobs'], 8)

    def test_compile_counter_ignores_generators_links_and_duplicate_ordinals(self):
        self.paths.state.mkdir(parents=True,exist_ok=True)
        (self.paths.state/'last-plan.txt').write_text('[1/6] CC a.o\n[2/6] CXX b.o\n[3/6] OBJC c.o\n[4/6] OBJCXX d.o\n[4/6] OBJCXX d.o\n[5/6] ACTION generator\n[6/6] LINK chrome\n')
        self.assertEqual(remote.planned_compiles(self.paths),4)

    def test_budget_refusal_does_not_start_worker_or_discard_snapshot(self):
        self.enable()
        with patch('he.timestamps.discard') as discard:
            with self.assertRaisesRegex(HeError, 'plans 501 edges'):
                self.run_build(guarded=True)
            discard.assert_not_called()
        self.assertEqual(len(self.events), 1)

    def test_unknown_plan_refuses_agent_and_forced_remote_but_auto_stays_local(self):
        self.enable()
        self.output = 'new unrecognized output\n'
        for options in ({'guarded': True, 'approved': True}, {'execution': 'remote'}):
            with self.assertRaisesRegex(HeError, 'cannot count'):
                self.run_build(**options)
        self.events.clear()
        self.run_build()
        self.assertEqual([x[0] for x in self.events], ['plan', 'build'])
        self.assertIn('--offline', self.events[-1][1])

    def test_disable_is_immediate_with_remote_ready_gn_and_has_no_human_plan(self):
        self.enable()
        self.config['enabled'] = False
        self.enable()
        self.run_build()
        self.assertEqual([x[0] for x in self.events], ['build'])
        self.assertIn('--offline', self.events[0][1])

    def test_explicit_local_skips_plan_and_cloud(self):
        self.enable()
        self.run_build(execution='local')
        self.assertEqual([x[0] for x in self.events], ['build'])
        self.assertEqual(self.events[-1][2]['jobs'], 2)

    def test_auto_basis_must_be_a_real_nonempty_string(self):
        for basis in (None, '', '  ', 123, [], {}):
            self.config['auto_basis'] = basis
            self.enable()
            with self.assertRaisesRegex(HeError,'benchmark basis'):
                remote.policy(self.paths)

    def test_real_arcium_raw_plan_counts_and_rejects_unsupported_work(self):
        text=(Path(__file__).parent/'fixtures/siso/arcium-objcxx-plan.txt').read_text()
        self.paths.state.mkdir(parents=True,exist_ok=True)
        target=self.paths.state/'last-plan.txt';target.write_text(text)
        self.assertEqual(remote.planned_compiles(self.paths),1)
        target.write_text(text.split('build finished')[0])
        self.assertIsNone(remote.planned_compiles(self.paths))
        target.write_text(text+text.split('build finished')[0])
        self.assertIsNone(remote.planned_compiles(self.paths))
        target.write_text(text+text)
        self.assertEqual(remote.planned_compiles(self.paths),1)
        command='../../third_party/llvm-build/Release+Asserts/bin/clang++ --target=arm64-apple-macos -c ../../foo.mm -o obj/foo.o'
        self.assertTrue(remote.raw_compile(command))
        for extra in (' @args.rsp',' -fmodules',' -fmodule-file=foo',' && echo foo','&&echo foo',';echo foo',' -emit-pch'):
            self.assertFalse(remote.raw_compile(command+extra))
        self.assertFalse(remote.raw_compile(command.replace('arm64-apple-macos','x86_64-linux-gnu')))
        self.assertFalse(remote.raw_compile('python3 generate.py -c foo.cc -o foo.o'))

    def test_preflight_failure_rolls_back_before_local_fallback(self):
        self.enable()
        self.Session.start = lambda session: (_ for _ in ()).throw(HeError('quota'))
        self.run_build()
        self.assertEqual([e[0] if isinstance(e, tuple) else e for e in self.events],
                         ['plan', 'session', 'rollback', 'build'])
        self.assertIn('--offline', self.events[-1][1])
        self.assertFalse(self.events[-1][2].get('admit_busy_cpu',False))

    def test_only_remote_candidates_plan_under_cpu_pressure(self):
        self.enable()
        self.run_build(approved=True)
        self.assertTrue(self.events[0][2]['admit_busy_cpu'])
        self.assertTrue(self.events[-2][2]['admit_busy_cpu'])
        self.events.clear()
        with patch('he.compile.activity.sample',return_value=SimpleNamespace(record=lambda:{'state':'idle'})):
            self.run_build(approved=True)
        self.assertFalse(self.events[0][2]['admit_busy_cpu'])
        self.events.clear()
        self.config['auto_min_compiles']=None
        self.enable()
        self.run_build(approved=True)
        self.assertFalse(self.events[0][2]['admit_busy_cpu'])

    def test_cleanup_failure_prevents_local_fallback(self):
        self.enable()
        self.Session.start = lambda session: (_ for _ in ()).throw(HeError('quota'))
        self.Session.close = lambda session, **kw: (_ for _ in ()).throw(HeError('cleanup incomplete'))
        with self.assertRaisesRegex(HeError, 'cleanup incomplete'):
            self.run_build()
        self.assertFalse(any(isinstance(x, tuple) and x[0] == 'build' for x in self.events))

    def test_remote_execution_failure_stops_without_local_retry(self):
        self.enable()
        self.build_status = 1
        self.assertEqual(self.run_build(), 1)
        self.assertEqual(sum(isinstance(x, tuple) and x[0] == 'build' for x in self.events), 1)
        self.assertEqual(self.events[-1], 'stop')

    def test_startup_interrupt_rolls_back_without_local_retry(self):
        self.enable()
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):
            self.events.clear()
            self.Session.start = lambda session: os.kill(os.getpid(), signum)
            with self.assertRaises(compile.Interrupted):
                self.run_build()
            self.assertEqual(self.events[-1], 'rollback')
            self.assertFalse(any(isinstance(x, tuple) and x[0] == 'build' for x in self.events))

    def test_compilation_interrupt_stops_worker_without_local_retry(self):
        self.enable()
        execute = self.execute
        def interrupt(paths, command, **options):
            if options.get('phase') != 'plan':
                os.kill(os.getpid(), signal.SIGTERM)
            return execute(paths, command, **options)
        self.runner.side_effect = interrupt
        with self.assertRaises(compile.Interrupted):
            self.run_build()
        self.assertEqual(self.events[-1], 'stop')

    def test_explicit_local_works_with_copied_policy(self):
        self.config['build_dir'] = '/another/developer/build'
        self.enable()
        self.run_build(execution='local')
        self.assertEqual([x[0] for x in self.events], ['build'])

    def test_official_and_development_contexts_keep_their_output_and_architecture(self):
        self.enable()
        root = self.paths.worktree
        for kind, output in [('daily', 'Default'), ('diagnostics', 'Diagnostics'), ('official', 'Default')]:
            for arch in ('arm64', 'x64'):
                context = remote.CompileContext(root, self.paths.build_dir, self.paths.src / 'out' / output, kind)
                context.out.mkdir(parents=True, exist_ok=True)
                text = f'target_cpu = "{arch}"\nuse_siso = true\nuse_remoteexec = true\nuse_reclient = false\n'
                (context.out / 'args.gn').write_text(text)
                self.events.clear()
                compile.run(context, ['chrome', 'chromedriver'], jobs=8, session_factory=self.Session)
                self.assertIn(str(context.out), self.events[-2][1])
                self.assertEqual((context.out / 'args.gn').read_text(), text)


class PolicyAndPlanTest(unittest.TestCase):
    def test_small_compatibility_worker_defaults_to_eight_remote_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            paths=Paths(root,root/'build')
            args=SimpleNamespace(project='arcium-builds-test',zone='us-central1-a',threshold=500,
                                 remote_jobs=None,cpus=8,credentials_dir=str(root/'credentials'))
            remote.setup(paths,args)
            config=remote.policy(paths)
            self.assertEqual((config['cpus'],config['remote_jobs']),(8,8))

    def test_captured_pinned_siso_plans(self):
        fixtures = Path(__file__).parent / 'fixtures/siso'
        self.assertEqual(agent.planned_edges((fixtures / 'pending-plan.txt').read_text()), 1)
        self.assertEqual(agent.planned_edges((fixtures / 'noop-plan.txt').read_text()), 0)
        truncated = (fixtures / 'pending-plan.txt').read_text().split('build finished')[0]
        self.assertIsNone(agent.planned_edges(truncated))

    def test_effective_gn_change_is_detected_without_changing_args_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = Paths(root, root / 'build')
            paths.out.mkdir(parents=True)
            (paths.out / 'args.gn').write_text('import("//config.gni")\n')
            write_json(remote.ready_file(paths), remote.fingerprint(paths))
            values = [dict(name=k, current={'value': v}) for k, v in
                      [('use_siso', 'true'), ('use_remoteexec', 'true'), ('use_reclient', 'true')]]
            with patch('he.remote.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(values))):
                with self.assertRaisesRegex(HeError, 'effective'):
                    remote.require_ready(paths)

    def test_plan_formats_and_truncation(self):
        for text, expected in [('ninja: no work to do.\n', 0), ('[1/14] CXX\n[14/14] LINK\n', 14),
                               ('rebuild manifest finished\nclang a.cc\nlink a.o\nbuild finished\n', 2),
                               ('rebuild manifest finished\nclang a.cc\n', None),
                               ('[1/14] truncated\n', None), ('loading build.ninja\n', None), ('', None)]:
            self.assertEqual(agent.planned_edges(text), expected)

    def test_regeneration_progress_and_command_literals_cannot_hide_siso_edges(self):
        lines = ['[1/1] Regenerating ninja files\n','rebuild manifest finished\n',
                 'clang -DVALUE="[1/1]" first.cc\n','clang second.cc\n','build finished\n']
        self.assertEqual(agent.planned_edges(iter(lines)),2)
        self.assertIsNone(agent.planned_edges(iter(lines[:-1])))

    def test_copied_policy_is_rejected_and_setup_assigns_new_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = Paths(root, root / 'a'), Paths(root, root / 'b')
            args = SimpleNamespace(project='arcium-builds-test', zone='us-central1-a', threshold=500,
                                   remote_jobs=64, credentials_dir=str(root / 'credentials'))
            remote.setup(a, args)
            first = remote.policy(a)
            write_json(b.state / 'remote-build.json', first)
            with self.assertRaisesRegex(HeError, 'another build directory'):
                remote.policy(b)
            remote.setup(b, args)
            self.assertNotEqual(remote.policy(b)['worker'], first['worker'])
            self.assertEqual((b.state / 'remote-build.json').stat().st_mode & 0o777, 0o600)

    def test_threshold_change_does_not_change_configuration_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = Paths(root, root / 'build')
            paths.out.mkdir(parents=True)
            (paths.out / 'args.gn').write_text('use_remoteexec = true\n')
            before = remote.fingerprint(paths)
            write_json(paths.state / 'remote-build.json', {'threshold': 900})
            self.assertEqual(remote.fingerprint(paths), before)
            source = paths.src / 'build/config/siso/.sisoenv'
            source.parent.mkdir(parents=True)
            source.write_text('SISO_REAPI_ADDRESS=other\n')
            self.assertNotEqual(remote.fingerprint(paths), before)

    def test_policy_copied_to_another_machine_gets_new_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = Paths(root, root / 'build')
            args = SimpleNamespace(project='arcium-builds-test', zone='us-central1-a', threshold=500,
                                   remote_jobs=64, credentials_dir=str(root / 'credentials'))
            with patch('he.remote.machine_identity', return_value='first-machine'):
                remote.setup(paths, args)
                first = remote.policy(paths)['worker']
            with patch('he.remote.machine_identity', return_value='second-machine'):
                with self.assertRaisesRegex(HeError, 'another build directory'):
                    remote.policy(paths)
                remote.setup(paths, args)
                self.assertNotEqual(remote.policy(paths)['worker'], first)


if __name__ == '__main__':
    unittest.main()
