"""Safety contracts for the independent renderer's frozen ABI boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'sdk.py'
spec = importlib.util.spec_from_file_location('studio_sdk', MODULE)
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


class FrozenSDKTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'src').mkdir()
        self.header = self.root / 'src/header.h'
        self.header.write_text('original declaration\n')
        self.manifest = {'frozen_hashes': {'header.h': sdk.digest(self.header)}, 'frozen_patch_sections': {}}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        self.override = patch.object(sdk, 'SDK', self.root)
        self.override.start(); self.addCleanup(self.override.stop)
        self.sections = patch.object(sdk, 'frozen_patch_sections', return_value={})
        self.sections.start(); self.addCleanup(self.sections.stop)

    def test_same_bytes_with_new_timestamp_are_allowed(self):
        sdk.validate()
        self.header.write_text('original declaration\n')
        sdk.validate()

    def test_modified_header_is_rejected_after_cached_validation(self):
        sdk.validate()
        self.header.write_text('different declaration\n')
        with self.assertRaisesRegex(RuntimeError, 'Frozen ABI input changed'):
            sdk.validate()

    def test_missing_library_is_rejected(self):
        self.header.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Missing frozen SDK input'):
            sdk.validate()

    def test_changed_owner_patch_is_rejected(self):
        with patch.object(sdk, 'frozen_patch_sections', return_value={'header.h': ['changed']}):
            with self.assertRaisesRegex(RuntimeError, 'Owning patches changed'):
                sdk.validate()

    def test_direct_source_mode_still_validates_frozen_inputs(self):
        self.header.write_text('incompatible declaration\n')
        with patch.object(sdk, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Frozen ABI input changed'):
                sdk.build(keep_edits=True)
            run.assert_not_called()


class HostSourceTests(unittest.TestCase):
    def test_tracked_host_replaces_bootstrap_snapshot(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for repo in (root, root / 'helium-chromium'):
                (repo / 'patches').mkdir(parents=True)
                (repo / 'patches/series').write_text('')
            lab = root / 'lab'; lab.mkdir()
            (lab / 'native_host.mm').write_text('fixed standalone host\n')
            frozen = root / 'sdk'; source = frozen / 'src'
            host = 'chrome/test/arcium_command_bar_studio_mac.mm'
            (source / host).parent.mkdir(parents=True)
            (source / host).write_text('old bootstrap host\n')
            (frozen / 'manifest.json').write_text(json.dumps({
                'frozen_files': [host], 'editable_sources': [host],
                'source_hashes': {host: sdk.digest(source / host)}}))
            prepare_spec = importlib.util.spec_from_file_location('prepare', MODULE.parent / 'prepare.py')
            prepare = importlib.util.module_from_spec(prepare_spec)
            prepare_spec.loader.exec_module(prepare)
            with patch.object(sdk, 'SDK', frozen), patch.object(sdk, 'ROOT', root), \
                 patch.object(sdk, 'LAB', lab), patch.dict(sys.modules, {'prepare': prepare}):
                sdk.sync()
            self.assertEqual((source / host).read_text(), 'fixed standalone host\n')
            self.assertEqual(json.loads((frozen / 'manifest.json').read_text())['source_hashes'][host],
                             sdk.digest(source / host))


if __name__ == '__main__': unittest.main()
