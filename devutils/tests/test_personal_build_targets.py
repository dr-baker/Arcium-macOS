"""Production-only compilation plans from active personal patches."""
import json
from pathlib import Path
import shlex
import tempfile
import unittest

from devutils.personal_build_targets import inventory


class PersonalBuildTargetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='personal targets ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        self.src = self.build / 'src'
        self.out = self.src / 'out/Diagnostics'
        self.out.mkdir(parents=True)
        for prefix in ('helium-chromium/patches', 'patches'):
            patches = self.root / prefix
            (patches / 'personal').mkdir(parents=True)
            (patches / 'series').write_text('personal/active.patch # active\n')
            (patches / 'personal/active.patch').write_text('')

    def patch(self, *names):
        patch = self.root / 'patches/personal/active.patch'
        patch.write_text(''.join(f'--- a/{name}\n+++ b/{name}\n' for name in names))

    def source(self, name):
        path = self.src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def database(self, entries):
        (self.out / 'compile_commands.json').write_text(json.dumps(entries))

    def entry(self, name, output, **extra):
        return dict(directory=str(self.out), file=f'../../{name}',
                    command=shlex.join(['clang++', '-c', f'../../{name}', '-o', output]),
                    **extra)

    def test_only_active_personal_production_objects_are_selected(self):
        names = ['chrome/browser/feature.cc', 'chrome/browser/feature_unittest.cc',
                 'chrome/test/test_support.cc', 'chrome/browser/inactive.cc']
        for name in names:
            self.source(name)
        self.patch(*names[:3])
        (self.root / 'patches/personal/inactive.patch').write_text(
            '--- a/chrome/browser/inactive.cc\n+++ b/chrome/browser/inactive.cc\n')
        self.database([
            self.entry(names[0], 'obj/chrome/browser/feature/feature.o'),
            self.entry(names[0], 'obj/chrome/test/studio/feature.o'),
            self.entry(names[0], 'obj/chrome/browser/unit_tests/feature.o'),
            self.entry(names[1], 'obj/chrome/browser/unit_tests/feature_unittest.o'),
            self.entry(names[2], 'obj/chrome/test/support/test_support.o'),
            self.entry(names[3], 'obj/chrome/browser/inactive/inactive.o'),
        ])
        result = inventory(self.root, self.build)
        self.assertEqual(result['targets'], ['obj/chrome/browser/feature/feature.o'])
        self.assertEqual(result['matched_sources'], 1)
        self.assertEqual(result['unmatched_sources'], [])

    def test_reports_unconfigured_and_missing_sources(self):
        self.patch('chrome/browser/android.cc', 'chrome/browser/absent.cc')
        self.source('chrome/browser/android.cc')
        self.database([])
        result = inventory(self.root, self.build)
        self.assertEqual(result['targets'], [])
        self.assertEqual(result['unmatched_sources'], ['chrome/browser/android.cc'])
        self.assertEqual(result['missing_sources'], ['chrome/browser/absent.cc'])

    def test_accepts_arguments_and_explicit_output_without_duplicates(self):
        name = 'chrome/browser/native.mm'
        self.source(name)
        self.patch(name)
        output = 'obj/chrome/browser/native/native.o'
        self.database([
            dict(directory=str(self.out), file=str(self.src / name),
                 arguments=['clang++', '-c', str(self.src / name), '-o', output]),
            dict(directory=str(self.out), file=f'../../{name}', output=output),
        ])
        self.assertEqual(inventory(self.root, self.build)['targets'], [output])

    def test_rejects_objects_outside_selected_output(self):
        name = 'chrome/browser/feature.cc'
        self.source(name)
        self.patch(name)
        self.database([self.entry(name, '../Default/feature.o')])
        with self.assertRaisesRegex(ValueError, 'outside the selected output'):
            inventory(self.root, self.build)


if __name__ == '__main__':
    unittest.main()
