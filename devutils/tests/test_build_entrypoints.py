"""The architecture check rejects ordinary ways to bypass build supervision."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('entrypoints', ROOT / 'devutils/check_build_entrypoints.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class EntrypointsTest(unittest.TestCase):
    def test_shell_launches_and_wrappers(self):
        for command in ('ninja -C out chrome', '/usr/local/bin/autoninja -C out chrome',
                        'timeout -k 7m -s SIGTERM 30s ninja chrome',
                        'env A=B /tools/siso ninja -C out chrome',
                        'command ninja -n chrome', 'exec ninja -t clean',
                        "bash -c 'ninja chrome'", "bash -lc 'ninja chrome'", "zsh -lc 'ninja chrome'",
                        "env -S 'ninja -C out chrome'", "env --split-string='ninja chrome'",
                        'sudo -n ninja chrome', 'sudo -u builder ninja chrome', 'command -- ninja chrome',
                        'exec -- ninja chrome', 'exec -a builder ninja chrome', 'time -p ninja chrome',
                        'command ninja -v chrome', 'command -- ninja -v chrome',
                        'NINJA=/tools/ninja\n"$NINJA" chrome',
                        'ninja \\\n+ -C out chrome', "python3 -c 'import subprocess; subprocess.run([\"ninja\"])'"):
            with self.subTest(command=command):
                self.assertTrue(checker.violations('new.sh', command))

    def test_python_arrays_assignments_aliases_and_builders(self):
        for source in ('subprocess.run(["ninja", "chrome"])',
                       'cmd=["python3",str(root/"autoninja.py"),"chrome"]; subprocess.Popen(cmd)',
                       'tool="/tools/ninja"; subprocess.run([tool,"chrome"])',
                       'from subprocess import run as launch\nlaunch("ninja chrome",shell=True)',
                       'os.system("timeout 30 ninja chrome")',
                       'def builder():\n return ["ninja", "chrome"]',
                       'asyncio.create_subprocess_exec("ninja", "chrome")',
                       'subprocess.run(["bash", "-lc", "ninja chrome"])',
                       'subprocess.run(["zsh", "-lc", "ninja chrome"])',
                       'subprocess.run(["env", "-S", "ninja chrome"])'):
            with self.subTest(source=source):
                self.assertTrue(checker.violations('new.py', source))

    def test_read_only_queries_and_installs_are_allowed(self):
        for command in ('brew install ninja coreutils', 'echo ninja', 'ninja --version',
                        'ninja -C out -t commands chrome', 'ninja -t query chrome',
                        'ninja -tcompdb', 'he agent build chrome'):
            with self.subTest(command=command):
                self.assertFalse(checker.violations('new.sh', command))
        self.assertFalse(checker.violations('new.sh', 'command -v ninja'))
        self.assertFalse(checker.violations('new.sh', 'command -pv ninja'))
        for command in ('ninja -t clean', 'ninja -t recompact', 'ninja -t restat',
                        'ninja -n chrome', 'ninja -t commands -t clean'):
            self.assertTrue(checker.violations('new.sh', command))

    def test_approved_functions_are_narrow_and_fixtures_are_excluded(self):
        self.assertFalse(checker.violations('devutils/he/resources.py',
                                           'def build_command():\n return ["ninja","chrome"]'))
        self.assertTrue(checker.violations('devutils/he/resources.py',
                                          'def another():\n return ["ninja","chrome"]'))
        self.assertFalse(checker.violations('devutils/tests/fixture.py', 'subprocess.run(["ninja"])'))
        self.assertFalse(checker.violations('devutils/command-bar-studio/sdk.py',
                                           'def build():\n return ["ninja","-f","private.ninja"]'))
        self.assertTrue(checker.violations('devutils/command-bar-studio/sdk.py',
                                          'def another():\n return ["ninja","chrome"]'))

    def test_yaml_and_executable_documentation(self):
        self.assertTrue(checker.violations('new.yml', '  run: "ninja -C out chrome"'))
        self.assertTrue(checker.violations('new.yml', '  run: |\n    ninja chrome'))
        self.assertFalse(checker.violations('new.md', 'Avoid raw ninja.'))
        self.assertTrue(checker.violations('new.md', '```sh\nninja chrome\n```'))

    def test_repository_uses_approved_build_entrypoints(self):
        self.assertEqual(checker.check(ROOT), [])


if __name__ == '__main__':
    unittest.main()
