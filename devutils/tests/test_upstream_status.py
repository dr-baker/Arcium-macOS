import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("upstream_status", Path(__file__).parents[1] / "upstream_status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class UpstreamStatusTest(unittest.TestCase):
    def test_patch_refresh_preserves_semantic_changes(self):
        patch = '--- a/a.cc\n+++ b/a.cc\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n'
        refreshed = 'Index: src/a.cc\n' + '=' * 67 + '\n' + patch.replace('a/a.cc', 'src.orig/a.cc').replace('b/a.cc', 'src/a.cc').replace('-1,2 +1,2', '-8,2 +8,2')
        self.assertEqual(status.patch_content(patch), status.patch_content(refreshed))
        self.assertNotEqual(status.patch_content(patch), status.patch_content(refreshed.replace('+new', '+different')))

    def test_report_uses_committed_heads_and_identifies_real_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return status.git(root, *args)
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            patch = '--- a/a.cc\n+++ b/a.cc\n@@ -1 +1 @@\n-old\n+new\n'
            (root / 'fix.patch').write_text(patch)
            (root / 'recipe').write_text('base\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            git('branch', 'incoming')
            (root / 'fix.patch').write_text(patch.replace('@@ -1 +1 @@', '@@ -2 +2 @@'))
            (root / 'recipe').write_text('local\n')
            git('commit', '-qam', 'local')
            local = git('rev-parse', 'HEAD')
            git('checkout', '-q', 'incoming')
            (root / 'fix.patch').write_text(patch.replace('+new', '+upstream'))
            (root / 'recipe').write_text('upstream\n')
            git('commit', '-qam', 'upstream')
            git('checkout', '-q', '--detach', local)
            (root / 'recipe').write_text('uncommitted\n')
            result = status.report(root, 'incoming')
            self.assertEqual(result['incoming_commits'], 1)
            self.assertEqual(result['local_commits'], 1)
            self.assertEqual(result['local_patch_refreshes'], ['fix.patch'])
            self.assertEqual(result['overlapping_changes'], ['recipe'])
            self.assertTrue(result['working_tree'])
            self.assertEqual((root / 'recipe').read_text(), 'uncommitted\n')


if __name__ == '__main__':
    unittest.main()
