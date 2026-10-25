"""Prevent mixed renderer/inspector revisions in the design app."""
import importlib.util
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
    def test_renderer_iteration_packages_current_inspector_too(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Mock()
            sdk.build.return_value = Path('/current/renderer')
            with patch.dict(sys.modules, {'sdk': sdk}), \
                 patch.object(native, 'STATE', Path(directory)), \
                 patch.object(native, 'latest_app', return_value=Path('/previous/app')), \
                 patch.object(native, 'build_settings', return_value=Path('/current/settings')) as settings, \
                 patch.object(native, 'package', return_value=Path('/new/app')) as package, \
                 patch.object(native, 'launch') as launch:
                native.iterate(4, launch_app=False)
                settings.assert_called_once_with(4)
                package.assert_called_once_with(
                    source_app=Path('/previous/app'),
                    settings_output=Path('/current/settings'),
                    executable_override=Path('/current/renderer'))
                launch.assert_not_called()

    def test_controls_iteration_does_not_reuse_previous_renderer(self):
        with patch.object(native, 'iterate') as iterate:
            native.controls(launch_app=False, jobs=3)
            iterate.assert_called_once_with(3, launch_app=False)

    def test_failed_inspector_build_never_packages_or_replaces_app(self):
        with patch.dict(sys.modules, {'sdk': Mock()}), \
             patch.object(native, 'build_settings', side_effect=RuntimeError('Swift failed')), \
             patch.object(native, 'package') as package, \
             patch.object(native, 'launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'Swift failed'):
                native.iterate(4)
            package.assert_not_called()
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
