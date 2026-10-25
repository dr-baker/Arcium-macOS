"""Prevent mixed renderer/inspector revisions in the design app."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    'studio_native', Path(__file__).resolve().parents[1] / 'native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class CurrentProductionInputsTests(unittest.TestCase):
    def setUp(self):
        self.generation = Mock(root=Path('/immutable/inputs'), identity='generation')
        self.iteration = Mock()
        self.iteration.capture.return_value = self.generation
        self.iteration.build_lock.return_value = nullcontext()
        self.design = Mock()
        modules = patch.dict(sys.modules, {'iteration': self.iteration})
        modules.start(); self.addCleanup(modules.stop)
        verifier = patch.object(native, 'verify_design_inputs', self.design.verify)
        verifier.start(); self.addCleanup(verifier.stop)

    def test_renderer_iteration_packages_current_inspector_too(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Mock()
            sdk.build.return_value = Path('/current/renderer')
            with patch.dict(sys.modules, {'sdk': sdk}), \
                 patch.object(native, 'STATE', Path(directory)), \
                 patch.object(native, 'runtime_template', return_value=Path('/previous/app')), \
                 patch.object(native, 'build_settings', return_value=Path('/current/settings')) as settings, \
                 patch.object(native, 'package', return_value=Path('/new/app')) as package, \
                 patch.object(native, 'launch') as launch:
                native.iterate(4, launch_app=False)
                settings.assert_called_once_with(4, source_root=Path('/immutable/inputs'))
                package.assert_called_once_with(
                    source_app=Path('/previous/app'),
                    settings_output=Path('/current/settings'),
                    executable_override=Path('/current/renderer'), publish=False,
                    generation=self.generation, experimental=False)
                launch.assert_not_called()

    def test_controls_iteration_does_not_reuse_previous_renderer(self):
        with patch.object(native, 'iterate') as iterate:
            native.controls(launch_app=False, jobs=3)
            iterate.assert_called_once_with(3, launch_app=False)

    def test_stale_generated_design_types_fail_before_compiling_or_replacing_app(self):
        self.design.verify.side_effect = ValueError('stale design schema')
        sdk = Mock()
        with patch.dict(sys.modules, {'sdk': sdk}), \
             patch.object(native, 'package') as package, patch.object(native, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'stale design schema'): native.iterate(4)
            self.design.verify.assert_called_once_with(self.generation.root)
            sdk.build.assert_not_called()
            package.assert_not_called()
            launch.assert_not_called()
            self.iteration.publish_latest.assert_not_called()

    def test_experiment_build_uses_the_frozen_generation_and_checks_it_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Mock(); sdk.experiment_inputs.return_value = {'.sdk-experiments/renderer.cc': Path('/live/renderer.cc')}
            self.generation.files = {'.sdk-experiments/renderer.cc': 'captured-hash'}
            with patch.dict(sys.modules, {'sdk': sdk}), patch.object(native, 'STATE', Path(directory)), \
                 patch.object(native, 'runtime_template'), patch.object(native, 'build_settings'), \
                 patch.object(native, 'package'), patch.object(native, 'launch') as launch:
                native.iterate(4, keep_edits=True)
                sdk.build.assert_called_once_with(4, True, source_root=Path('/immutable/inputs'),
                    experiments={'renderer.cc': (Path('/immutable/inputs/.sdk-experiments/renderer.cc'), 'captured-hash')})
                self.assertEqual(launch.call_args.kwargs['before_replace'], self.generation.require_current)

    def test_failed_inspector_build_never_packages_or_replaces_app(self):
        with patch.dict(sys.modules, {'sdk': Mock()}), \
             patch.object(native, 'build_settings', side_effect=RuntimeError('Swift failed')), \
             patch.object(native, 'package') as package, \
             patch.object(native, 'launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'Swift failed'):
                native.iterate(4)
            package.assert_not_called()
            launch.assert_not_called()

    def test_edits_during_compilation_do_not_publish_or_launch(self):
        self.generation.require_current.side_effect = RuntimeError('superseded')
        with patch.dict(sys.modules, {'sdk': Mock()}), \
             patch.object(native, 'build_settings'), \
             patch.object(native, 'package') as package, \
             patch.object(native, 'launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'superseded'):
                native.iterate(4)
            package.assert_not_called()
            launch.assert_not_called()
            self.iteration.publish_latest.assert_not_called()

    def test_readiness_failure_retains_previous_published_app(self):
        with patch.dict(sys.modules, {'sdk': Mock()}), \
             patch.object(native, 'build_settings'), \
             patch.object(native, 'runtime_template'), \
             patch.object(native, 'package'), \
             patch.object(native, 'launch', side_effect=RuntimeError('not ready')):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                native.iterate(4)
            self.iteration.publish_latest.assert_not_called()

    def test_resource_change_during_packaging_does_not_publish(self):
        with patch.dict(sys.modules, {'sdk': Mock()}), \
             patch.object(native, 'build_settings'), \
             patch.object(native, 'runtime_template', side_effect=[Path('/runtime'), RuntimeError('resource changed')]), \
             patch.object(native, 'package'), patch.object(native, 'launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'resource changed'): native.iterate(4)
            launch.assert_not_called()
            self.iteration.publish_latest.assert_not_called()


class RuntimeInputsTests(unittest.TestCase):
    def test_modified_resource_and_retargeted_link_require_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); app = root / 'Studio.app'; app.mkdir()
            pak = app / 'ui_test.pak'; pak.write_bytes(b'original')
            (app / 'other.pak').write_bytes(b'original')
            link = app / 'current.pak'; link.symlink_to('ui_test.pak')
            lab = root / 'lab'; manifest_path = lab / '.build/native-sdk/manifest.json'
            manifest_path.parent.mkdir(parents=True)
            with patch.object(native, 'LAB', lab), patch.object(native, 'STATE_ROOT', root / 'state'):
                manifest_path.write_text(json.dumps({'runtime_template': str(app), 'runtime_inputs': native.runtime_inputs(app)}))
                self.assertEqual(native.runtime_template(), app)
                pak.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'runtime resources'): native.runtime_template()
                pak.write_bytes(b'original'); link.unlink(); link.symlink_to('other.pak')
                with self.assertRaisesRegex(RuntimeError, 'symlink mappings'): native.runtime_template()


class WatchRecoveryTests(unittest.TestCase):
    def test_malformed_patch_recovers_when_corrected_and_experimental_sources_are_watched(self):
        import prepare
        iteration = Mock(); sdk = Mock()
        extra = {'.sdk-experiments/renderer.cc': Path('/sdk/renderer.cc')}
        sdk.experiment_inputs.return_value = extra
        iteration.stamps.side_effect = [{'patch': 1}, {'patch': 1}, {'patch': 2}, {'patch': 2}]
        patches = iter(['--- a/renderer.cc\n+++ \n',
                        '--- /dev/null\n+++ b/renderer.cc\n@@ -0,0 +1 @@\n+fixed\n'])
        parsed = {}
        def build_patch(*args): prepare.apply_patch(parsed, next(patches), 'edited.patch')
        with patch.dict(sys.modules, {'iteration': iteration, 'sdk': sdk}), \
             patch.object(prepare, 'selected', return_value=True), \
             patch.object(native, 'iterate', side_effect=build_patch) as build, \
             patch.object(native.time, 'sleep', side_effect=[None, None, None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt): native.watch(4, True, .25)
            self.assertEqual(build.call_count, 2)
            self.assertEqual(parsed['renderer.cc'], ['fixed'])
            for call in iteration.stamps.call_args_list: self.assertEqual(call.kwargs['extra_files'], extra)


if __name__ == '__main__':
    unittest.main()
