"""Real small CI builds, interruption/resume, and architecture checks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he.ci import smoke_started

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(all(shutil.which(t) for t in ('ninja', 'greadlink', 'timeout', 'clang++')),
                     'needs Ninja, clang and GNU coreutils')
class CIBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.prepare(self.root)

    def prepare(self, root, arch='arm64'):
        root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / '.github/scripts/github_build.sh', root / 'github_build.sh')
        (root / 'devutils').symlink_to(ROOT / 'devutils', target_is_directory=True)
        src = root / 'build/src'
        out = src / 'out/Default'
        out.mkdir(parents=True)
        cpu = 'arm64' if arch == 'arm64' else 'x64'
        values = dict(target_cpu=json.dumps(cpu), use_siso='false', use_remoteexec='false', use_reclient='false')
        (out / 'values.json').write_text(json.dumps([dict(name=k, current=dict(value=v)) for k,v in values.items()]))
        (out / 'args.gn').write_text('\n'.join(k+' = '+v for k,v in values.items()) + '\nchrome_pgo_phase = 2\nis_official_build = true\n')
        gn = out / 'gn'
        gn.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nimport sys\nassert sys.argv[1]=="args"\nprint(Path(__file__).with_name("values.json").read_text())\n')
        gn.chmod(0o755)
        (src / 'unit.cc').write_text('int answer() { return 42; }\n')
        (src / 'wait.py').write_text('import time,sys\nfrom pathlib import Path\nPath("started").touch()\n'
                                    'time.sleep(float(Path("../../delay").read_text()))\n'
                                    'sys.exit(17 if Path("../../fail").exists() else 0)\n')
        (src / 'delay').write_text('0')
        target = 'arm64' if cpu == 'arm64' else 'x86_64'
        (out / 'build.ninja').write_text(f'rule cc\n  command = "{sys.executable}" ../../wait.py && clang++ --target={target}-apple-macos13 -c ../../unit.cc -o $out\n'
                                        'build unit.o: cc ../../unit.cc\nbuild chrome: phony unit.o\nbuild chromedriver: phony unit.o\n')

    def run_build(self, root=None, arch='arm64', remaining=None, extra=None):
        root = root or self.root
        if remaining is not None:
            (root / 'epoch_job_start.txt').write_text(str(int(time.time())-18000+remaining))
        else:
            (root / 'epoch_job_start.txt').unlink(missing_ok=True)
        output = root / 'github-output'
        output.write_text('')
        env = {**os.environ, 'GITHUB_OUTPUT': str(output), 'PYTHONPATH': str(ROOT/'devutils'),
               'HELIUM_BUILD_JOBS': '2', **(extra or {})}
        result = subprocess.run(['bash', str(root/'github_build.sh'), arch], cwd=root,
                                env=env, capture_output=True, text=True, timeout=30)
        return result, output.read_text()

    def manifests(self, root=None):
        return [json.loads(p.read_text()) for p in ((root or self.root)/'build/.arcium/build-evidence').glob('*/manifest.json')]

    def test_success_both_architectures_uses_lock_supervision_and_keeps_flags(self):
        for arch in ('arm64', 'x86_64'):
            with self.subTest(arch=arch):
                root = self.root / arch
                self.prepare(root, arch)
                out = root/'build/src/out/Default'
                flags = (out/'args.gn').read_bytes()
                result, output = self.run_build(root, arch)
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])
                self.assertIn('status=finished', output)
                self.assertTrue((root/f'build_finished_{arch}.log').exists())
                self.assertTrue((out/'unit.o').is_file())
                self.assertEqual((out/'args.gn').read_bytes(), flags)
                self.assertTrue((root/'build/.arcium/release.lock').is_file())
                self.assertFalse((root/'build/.arcium/lane-command.json').exists())
                manifest = self.manifests(root)[0]
                self.assertEqual(manifest['returncode'], 0)
                phase = next(p for p in manifest['phases'] if p['name']=='build')
                command = phase['attributes']['command']
                self.assertIn('ninja', command)
                self.assertEqual(command[command.index('-k')+1], '1')
                self.assertIn('child_started_offset_nanos', phase['attributes'])
                self.assertGreater(manifest['resource_events'], 0)

    def test_timeout_preserves_resume_on_a_fresh_runner(self):
        (self.root/'build/src/delay').write_text('20')
        result, output = self.run_build(remaining=2)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('status=running', output)
        self.assertNotIn('status=finished', output)
        self.assertFalse((self.root/'build_finished_arm64.log').exists())
        manifest = self.manifests()[0]
        self.assertEqual(manifest['returncode'], 143)
        self.assertTrue(manifest.get('finished_at'))
        self.assertTrue((self.root/'build/src/out/Default/started').exists())
        self.assertFalse((self.root/'build/.arcium/lane-command.json').exists())
        fresh = self.root/'fresh-runner'
        self.prepare(fresh)
        shutil.rmtree(fresh/'build/src')
        shutil.copytree(self.root/'build/src', fresh/'build/src')
        self.assertFalse((fresh/'build/.arcium').exists())
        (fresh/'build/src/delay').write_text('0')
        result, output = self.run_build(fresh)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('status=finished', output)
        self.assertEqual(len(self.manifests(fresh)), 1)

    def test_compiler_failure_has_evidence_and_no_finished_marker(self):
        (self.root/'build/src/fail').touch()
        result, output = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('status=finished', output)
        self.assertFalse((self.root/'build_finished_arm64.log').exists())
        self.assertNotEqual(self.manifests()[0]['returncode'], 0)

    def test_exhausted_budget_clears_stale_success_without_launching(self):
        (self.root/'build_finished_arm64.log').touch()
        result, output = self.run_build(remaining=-1)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('status=finished', output)
        self.assertFalse((self.root/'build_finished_arm64.log').exists())
        self.assertEqual(self.manifests(), [])

    def test_architecture_and_engine_mismatches_fail_before_compilation(self):
        result, _ = self.run_build(arch='x86_64')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target_cpu', result.stderr)
        (self.root/'build/src/out/Default/siso_fs_state').touch()
        result, _ = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Siso state', result.stderr)
        self.assertFalse((self.root/'build/src/out/Default/started').exists())

    def test_legacy_ninja_log_keeps_the_executor_and_gn_bytes(self):
        out = self.root/'build/src/out/Default'
        values=json.loads((out/'values.json').read_text())
        next(v for v in values if v['name']=='use_siso')['current']['value']='true'
        (out/'values.json').write_text(json.dumps(values))
        (out/'args.gn').write_text((out/'args.gn').read_text().replace('use_siso = false','use_siso = true'))
        flags=(out/'args.gn').read_bytes()
        (out/'.ninja_log').write_text('# ninja log v5\n')
        result, output = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('status=finished', output)
        self.assertEqual((out/'args.gn').read_bytes(),flags)
        self.assertEqual(self.manifests()[0]['executor'],'ninja')

    def test_hard_kill_exit_status_never_certifies_completion(self):
        # Simulate GNU timeout's hard-kill status without leaving an orphaned
        # process in the test runner. Actual cooperative SIGTERM is tested above.
        tools=self.root/'test-tools';tools.mkdir()
        timeout=tools/'timeout';timeout.write_text('#!/bin/sh\nexit 137\n');timeout.chmod(0o755)
        (self.root/'build_finished_arm64.log').touch()
        result, output=self.run_build(extra={'PATH':str(tools)+os.pathsep+os.environ['PATH']})
        self.assertEqual(result.returncode,137)
        self.assertNotIn('status=finished',output)
        self.assertFalse((self.root/'build_finished_arm64.log').exists())

    def test_remote_flags_and_development_lanes_are_refused(self):
        out=self.root/'build/src/out/Default'
        values=json.loads((out/'values.json').read_text())
        next(v for v in values if v['name']=='use_remoteexec')['current']['value']='true'
        (out/'values.json').write_text(json.dumps(values))
        result, _=self.run_build()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('remote execution',result.stderr)
        (self.root/'build/.arcium/lane.lock').touch()
        result, _=self.run_build()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('development lane',result.stderr)


class SmokeEvidenceTest(unittest.TestCase):
    def test_planning_timeout_and_hard_kill_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            path = state/'build-evidence/run/manifest.json'
            path.parent.mkdir(parents=True)
            value = dict(started_at=datetime.now(timezone.utc).isoformat(), finished_at='done', returncode=143,
                         phases=[dict(name='plan', attributes=dict(child_started_offset_nanos=1))])
            path.write_text(json.dumps(value))
            self.assertFalse(smoke_started(state, 0, 124))
            value['phases'][0]['name']='build'
            path.write_text(json.dumps(value))
            self.assertTrue(smoke_started(state, 0, 124))
            self.assertFalse(smoke_started(state, time.time_ns()+10**9, 124))
            self.assertFalse(smoke_started(state, 0, 137))
            value['finished_at']=None
            path.write_text(json.dumps(value))
            self.assertFalse(smoke_started(state, 0, 124))


if __name__ == '__main__':
    unittest.main()
