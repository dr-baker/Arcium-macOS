import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).resolve().parents[1] / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
FILE = prepare.PREFIX + 'fixture.swift'


class ReplayTests(unittest.TestCase):
    def testNewFileAndSubsequentPatch(self):
        files = {}
        prepare.apply_patch(files, f'--- /dev/null\n+++ b/{FILE}\n@@ -0,0 +1,2 @@\n+one\n+two\n', 'create')
        prepare.apply_patch(files, f'--- a/{FILE}\n+++ b/{FILE}\n@@ -1,2 +1,2 @@\n one\n-two\n+three\n', 'edit')
        self.assertEqual(files[FILE], ['one', 'three'])

    def testMissingPreimageFailsInsteadOfUsingChromium(self):
        with self.assertRaisesRegex(ValueError, 'missing preimage'):
            prepare.apply_patch({}, f'--- a/{FILE}\n+++ b/{FILE}\n@@ -1 +1 @@\n-before\n+after\n', 'missing')

    def testQuotedResourcePathWithSpaces(self):
        path = prepare.PREFIX + 'Resources/yellow-blue grain.json'
        files = {}
        prepare.apply_patch(files, f'--- /dev/null\n+++ "b/{path}"\n@@ -0,0 +1 @@\n+{{}}\n', 'resource')
        self.assertEqual(files[path], ['{}'])

    def testUniqueOffsetAcceptedButAmbiguousContextRejected(self):
        patch = f'--- a/{FILE}\n+++ b/{FILE}\n@@ -1 +1 @@\n-old\n+new\n'
        files = {FILE: ['prefix', 'old']}
        prepare.apply_patch(files, patch, 'offset')
        self.assertEqual(files[FILE], ['prefix', 'new'])
        with self.assertRaisesRegex(ValueError, 'not unique'):
            prepare.apply_patch({FILE: ['prefix', 'old', 'old']}, patch, 'ambiguous')

    def testUnrelatedChromiumFilesAreIgnored(self):
        files = {}
        prepare.apply_patch(files, '--- a/chrome/unrelated.cc\n+++ b/chrome/unrelated.cc\n@@ -1 +1 @@\n-old\n+new\n', 'unrelated')
        self.assertEqual(files, {})


if __name__ == '__main__': unittest.main()
