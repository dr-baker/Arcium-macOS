"""Safety contracts for the independent renderer's frozen ABI boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import shlex
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'sdk.py'
sys.path.insert(0, str(MODULE.parent))
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
        self.manifest = {'frozen_hashes': {'header.h': sdk.digest(self.header)}, 'frozen_patch_sections': {},
                         'dependency_provenance': {}, 'system_dependency_hashes': {}, 'graph_hashes': {},
                         'editable_sources': []}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        self.override = patch.object(sdk, 'SDK', self.root)
        self.override.start(); self.addCleanup(self.override.stop)
        self.sections = patch.object(sdk, 'frozen_patch_sections', return_value={})
        self.sections.start(); self.addCleanup(self.sections.stop)
        self.provenance = patch.object(sdk, 'dependency_provenance', return_value={})
        self.provenance.start(); self.addCleanup(self.provenance.stop)

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

    def test_cached_implementation_change_is_rejected(self):
        with patch.object(sdk, 'dependency_provenance', return_value={'cached.cc': 'changed'}):
            with self.assertRaisesRegex(RuntimeError, 'Cached implementation'):
                sdk.validate()

    def test_target_source_list_change_is_rejected(self):
        with patch.object(sdk, 'dependency_provenance', return_value={'BUILD.gn': 'new source'}):
            with self.assertRaisesRegex(RuntimeError, 'build definition changed'):
                sdk.validate()

    def test_external_sdk_header_change_is_rejected(self):
        external = self.root / 'AppleSDK.h'; external.write_text('original')
        self.manifest['system_dependency_hashes'] = {str(external): sdk.digest(external)}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        sdk.validate()
        external.write_text('changed ABI')
        with self.assertRaisesRegex(RuntimeError, 'External SDK input changed'):
            sdk.validate()

    def test_retargeted_live_sysroot_is_rejected(self):
        first = self.root / 'SDK1'; first.mkdir()
        second = self.root / 'SDK2'; second.mkdir()
        link = self.root / 'sysroot'; link.symlink_to(first)
        self.manifest['sysroot_mappings'] = {'sysroot': str(first.resolve())}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        sdk.validate(); link.unlink(); link.symlink_to(second)
        with self.assertRaisesRegex(RuntimeError, 'sysroot mapping changed'): sdk.validate()

    def test_changed_link_graph_is_rejected(self):
        graph = self.root / 'build.ninja'; graph.write_text('original graph')
        self.manifest['graph_hashes'] = {'build.ninja': sdk.digest(graph)}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        graph.write_text('different linked objects')
        with self.assertRaisesRegex(RuntimeError, 'Cached build graph/tool changed'):
            sdk.validate()


class ProvenanceTests(unittest.TestCase):
    def test_new_header_invalidates_source_verification_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'src/out/Default').mkdir(parents=True)
            (root / 'src/renderer.cc').write_text('renderer')
            manifest = {'compile_commands': [{'command': 'clang++ -c ../../renderer.cc -o renderer.o -MF renderer.d'}],
                        'system_sdks': [], 'frozen_hashes': {}, 'system_dependency_hashes': {}}
            with patch.object(sdk, 'SDK', root), patch.object(sdk, 'system_dependencies', return_value={}) as probe:
                sdk.validate_external_includes(manifest, {'renderer.cc': 'source'})
                sdk.validate_external_includes(manifest, {'renderer.cc': 'source'})
                self.assertEqual(probe.call_count, 1)
                (root / 'src/new-header.h').write_text('new include-search candidate')
                sdk.validate_external_includes(manifest, {'renderer.cc': 'source'})
                self.assertEqual(probe.call_count, 2)

    def test_new_local_header_cannot_enter_a_frozen_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); out = root / 'src/out/Default'; out.mkdir(parents=True)
            renderer = root / 'src/renderer.cc'; renderer.write_text('#include "new.h"')
            header = root / 'src/new.h'; header.write_text('mutable new header')
            def preprocess(argv, **kwargs):
                depfile = Path(argv[argv.index('-MF') + 1])
                depfile.write_text('renderer.o: ' + shlex.join([str(renderer), str(header)]))
            commands = [{'command': 'clang++ -c ../../renderer.cc -o renderer.o -MF renderer.d -MMD'}]
            with patch.object(sdk, 'run', side_effect=preprocess):
                with self.assertRaisesRegex(RuntimeError, 'Uncaptured local compiler input'):
                    sdk.system_dependencies(commands, out, [], include_linker=False, captured_local={})
                sdk.system_dependencies(commands, out, [], include_linker=False, captured_local={'new.h': 'captured'})
    def test_real_sections_reject_cached_code_graph_and_resources_but_allow_rebuilt_code(self):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for repo, mapping in ((root, 'platform_resources.txt'), (root / 'helium-chromium', 'helium_resources.txt')):
                (repo / 'patches').mkdir(parents=True)
                (repo / 'patches/series').write_text('fixture.patch\n')
                (repo / 'patches/fixture.patch').write_text('')
                (repo / 'resources').mkdir()
                (repo / 'resources' / mapping).write_text('image.bin image.out\n')
                (repo / 'resources/image.bin').write_bytes(b'image')
            owner = root / 'patches/fixture.patch'
            def section(name, value):
                return f'--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-old\n+{value}\n'
            def content(rebuilt='render', cached='library', graph='source-list'):
                return section('render.cc', rebuilt) + section('cached.cc', cached) + section('BUILD.gn', graph)
            owner.write_text(content())
            prepare_spec = importlib.util.spec_from_file_location('prepare', MODULE.parent / 'prepare.py')
            prepare = importlib.util.module_from_spec(prepare_spec); prepare_spec.loader.exec_module(prepare)
            with patch.object(sdk, 'ROOT', root), patch.dict(sys.modules, {'prepare': prepare}):
                before = sdk.dependency_provenance(['render.cc'])
                owner.write_text(content(rebuilt='edited renderer'))
                self.assertEqual(before, sdk.dependency_provenance(['render.cc']))
                owner.write_text(content(cached='changed library'))
                self.assertNotEqual(before, sdk.dependency_provenance(['render.cc']))
                owner.write_text(content(graph='added source'))
                self.assertNotEqual(before, sdk.dependency_provenance(['render.cc']))
                owner.write_text(content()); (root / 'resources/image.bin').write_bytes(b'new image')
                self.assertNotEqual(before, sdk.dependency_provenance(['render.cc']))
                (root / 'resources/image.bin').write_bytes(b'image')
                for name in __import__('iteration').CONFIGURATION_INPUTS:
                    config = root / name; config.write_text('new configuration')
                    self.assertNotEqual(before, sdk.dependency_provenance(['render.cc']), name)
                    config.unlink()
                owner.write_text('--- a/renderer.cc\n+++ \n')
                with self.assertRaisesRegex(ValueError, 'Incomplete patch header'):
                    sdk.dependency_provenance(['renderer.cc'])
                with self.assertRaisesRegex(ValueError, 'Incomplete patch header'):
                    sdk.frozen_patch_sections({'renderer.cc'})

    def test_compiler_reads_immutable_copy_even_after_experiment_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'src/out/Default').mkdir(parents=True)
            (root / 'src/renderer.cc').write_text('original source')
            manifest = {'editable_sources': ['renderer.cc'],
                        'compile_commands': [{'command': 'clang++ -c ../../renderer.cc -o renderer.o -MF renderer.d'}],
                        'link_arguments': ['clang++', 'renderer.o', '-o', 'arcium_command_bar_studio']}
            with patch.object(sdk, 'SDK', root):
                graph, hashes = sdk.frozen_source_graph(manifest)
                frozen = root / 'source-generations' / hashes['renderer.cc'] / 'renderer.cc'
                (root / 'src/renderer.cc').write_text('changed while compiling')
                self.assertEqual(frozen.read_text(), 'original source')
                self.assertIn(str(frozen), graph.read_text())
                self.assertNotIn('-c ../../renderer.cc', graph.read_text())

    def test_explicit_experiment_generation_overrides_later_live_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'src/out/Default').mkdir(parents=True)
            (root / 'src/renderer.cc').write_text('later live experiment')
            captured = root / 'captured.cc'; captured.write_text('captured experiment')
            expected = sdk.digest(captured)
            manifest = {'editable_sources': ['renderer.cc'],
                        'compile_commands': [{'command': 'clang++ -c ../../renderer.cc -o renderer.o -MF renderer.d'}],
                        'link_arguments': ['clang++', 'renderer.o', '-o', 'arcium_command_bar_studio']}
            with patch.object(sdk, 'SDK', root):
                _, hashes = sdk.frozen_source_graph(manifest, {'renderer.cc': (captured, expected)})
                self.assertEqual(hashes['renderer.cc'], expected)
                captured.write_text('invalid immutable edit')
                with self.assertRaisesRegex(RuntimeError, 'Immutable SDK experiment'):
                    sdk.frozen_source_graph(manifest, {'renderer.cc': (captured, expected)})


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
            # A direct experiment is ported verbatim, then edited again normally.
            (source / host).write_text('ported experiment\n')
            (lab / 'native_host.mm').write_text('ported experiment\n')
            with patch.object(sdk, 'SDK', frozen), patch.object(sdk, 'ROOT', root), \
                 patch.object(sdk, 'LAB', lab), patch.dict(sys.modules, {'prepare': prepare}):
                sdk.sync()
                (lab / 'native_host.mm').write_text('next production edit\n')
                sdk.sync()
            self.assertEqual((source / host).read_text(), 'next production edit\n')


if __name__ == '__main__': unittest.main()
