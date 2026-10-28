"""Prepared archives select host tools independently of the requested target."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('greadlink'), 'needs GNU readlink')
class SourceArchiveTest(unittest.TestCase):
    def test_acquisition_records_only_success_and_preserves_failed_extraction(self):
        for mode, status in [('prepared', 0), ('full', 0), ('prepared', 9), ('full', 9)]:
            with self.subTest(mode=mode, status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                calls = root / 'calls'
                acquire = root / 'retrieve_and_unpack_resource.sh'
                acquire.write_text('#!/bin/sh\n'
                                   'printf "acquire %s\\n" "$*" >> "$ACQUISITION_CALLS"\n'
                                   'mkdir -p "$HELIUM_DEV_BUILD_ROOT/src"\n'
                                   'echo partial > "$HELIUM_DEV_BUILD_ROOT/src/retained"\n'
                                   'exit "$ACQUISITION_STATUS"\n')
                acquire.chmod(0o755)
                script = '''source "$1" >/dev/null || exit 2
_root_dir="$2"
___helium_he() { printf 'record %s\\n' "$*" >> "$ACQUISITION_CALLS"; }
___helium_info_pull "$3"
'''
                result = subprocess.run(
                    ['bash', '-c', script, 'bash', str(ROOT / 'dev.sh'), str(root), mode],
                    env={**os.environ, 'HELIUM_DEV_WORKTREE': str(ROOT),
                         'HELIUM_BUILD_DIR': str(root / 'build'),
                         'ACQUISITION_CALLS': str(calls), 'ACQUISITION_STATUS': str(status)},
                    text=True, capture_output=True)
                lines = calls.read_text().splitlines()
                self.assertEqual(sum(line.startswith('acquire ') for line in lines), 1)
                self.assertEqual('-d' in lines[0].split(), mode == 'prepared')
                self.assertEqual((root / 'build/src/retained').read_text(), 'partial\n')
                if status:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(len(lines), 1)
                    if mode == 'prepared':
                        self.assertIn('fresh HELIUM_BUILD_DIR', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(lines[1], f'record acquisition record --source-mode {mode}')

    def test_both_target_architectures_use_the_host_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            shutil.copy2(ROOT / 'retrieve_and_unpack_resource.sh', root)
            (root / 'devutils').mkdir()
            (root / 'devutils/setup_python.sh').write_text(
                '___helium_setup_python() { :; }\n___helium_python() { python3 "$@"; }\n')
            (root / 'helium-chromium/utils').mkdir(parents=True)
            (root / 'helium-chromium/utils/downloads.py').write_text(
                'import json,os,sys\n'
                'with open(os.environ["ARCHIVE_CALLS"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            uname = bin_dir / 'uname'
            log = root / 'calls.jsonl'
            for host, overlay in [('arm64', 'arm64'), ('x86_64', 'x64')]:
                uname.write_text(f'#!/bin/sh\necho {host}\n')
                uname.chmod(0o755)
                for target in ['arm64', 'x86_64']:
                    with self.subTest(host=host, target=target):
                        log.unlink(missing_ok=True)
                        result = subprocess.run(
                            ['bash', str(root / 'retrieve_and_unpack_resource.sh'), '-d', '-g', target],
                            env={**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
                                 'ARCHIVE_CALLS': str(log), 'HELIUM_DEV_BUILD_ROOT': str(root / 'build')},
                            text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        calls = [json.loads(line) for line in log.read_text().splitlines()]
                        self.assertEqual([call[0] for call in calls], ['retrieve', 'unpack'])
                        for call in calls:
                            inputs = call[call.index('-i') + 1:call.index('-c')]
                            self.assertEqual(inputs, [str(root / 'helium-chromium/downloads.ini'),
                                                      str(root / f'downloads.{overlay}.ini'),
                                                      str(root / 'downloads.ini'),
                                                      str(root / 'helium-chromium/deps.ini')])


if __name__ == '__main__':
    unittest.main()
