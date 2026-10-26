"""Keep runtime values and production defaults on the same versioned schema."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json

spec = importlib.util.spec_from_file_location(
    'studio_design_types', Path(__file__).resolve().parents[1] / 'design_tokens.py')
design = importlib.util.module_from_spec(spec)
spec.loader.exec_module(design)


class DesignTokenTests(unittest.TestCase):
    def test_cli_design_edit_is_atomic_and_preserves_scenario_state(self):
        native_spec = importlib.util.spec_from_file_location('native_design_cli', design.ROOT / 'devutils/command-bar-studio/native.py')
        native = importlib.util.module_from_spec(native_spec); native_spec.loader.exec_module(native)
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); path = state / 'scenario.json'
            document = {'schema': 'arcium-ui-workshop', 'version': 1, 'component': 'command-bar',
                        'query': 'retained', 'scope': 'saved', 'selected_key': 'pin:1',
                        'layout': {'labels': 1, 'result_count': 8}}
            path.write_text(json.dumps(document))
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                native.edit_design(state, ['row_height=50', 'glow_softness=true'])
            self.assertEqual(path.read_bytes(), original)
            native.edit_design(state, ['row_height=50', 'text_color=#abcdef',
                                       'glow_width=1.5', 'glow_height=0.5', 'glow_softness=30',
                                       'collapsed_glow_height=0'])
            updated = json.loads(path.read_text())
            self.assertEqual(updated['layout']['design'], {'row_height': 50, 'text_color': '#ABCDEF',
                'glow_width': 1.5, 'glow_height': 0.5, 'glow_softness': 30,
                'collapsed_glow_height': 0})
            before_invalid = path.read_bytes()
            for edits in (['glow_width=0.24'], ['glow_height=3.01'], ['glow_width=true'],
                          ['glow_width=1.25', 'glow_height=0'],
                          ['collapsed_glow_height=-0.01'], ['collapsed_glow_height=1.01'],
                          ['collapsed_glow_height=true']):
                with self.assertRaises(ValueError): native.edit_design(state, edits)
                self.assertEqual(path.read_bytes(), before_invalid)
            native.edit_design(state, ['collapsed_glow_height=1'])
            self.assertEqual(json.loads(path.read_text())['layout']['design']['collapsed_glow_height'], 1)
            native.edit_design(state, ['collapsed_glow_height=0.25'])
            self.assertNotIn('collapsed_glow_height', json.loads(path.read_text())['layout']['design'])
            for key in ('query', 'scope', 'selected_key'):
                self.assertEqual(updated[key], document[key])
            native.edit_design(state, [], reset=True)
            self.assertEqual(json.loads(path.read_text()), document)

    def test_each_generation_executes_its_own_swift_generator(self):
        native_spec = importlib.util.spec_from_file_location('native_design_verifier', design.ROOT / 'devutils/command-bar-studio/native.py')
        native = importlib.util.module_from_spec(native_spec); native_spec.loader.exec_module(native)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ('helium-chromium/devutils/command_design.py',
                             'helium-chromium/devutils/ui/command_bar_design.json',
                             'devutils/command-bar-studio/design_tokens.py',
                             str(design.CORE_PATCH.relative_to(design.ROOT)),
                             str(design.MAC_PATCH.relative_to(design.ROOT))):
                output = root / relative; output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes((design.ROOT / relative).read_bytes())
            native.verify_design_inputs(root)
            generator = root / 'devutils/command-bar-studio/design_tokens.py'
            generator.write_text(generator.read_text().replace('// Generated from core devutils/', '// New generator from core devutils/'))
            with self.assertRaisesRegex(ValueError, 'Stale generated'):
                native.verify_design_inputs(root)

    def test_checked_in_production_types_match_canonical_schema(self):
        design.verify()

    def test_nonempty_color_default_and_explicit_theme_override_are_supported(self):
        core = design.module()
        value = {'tokens': [{'key': 'text_color', 'label': 'Text', 'group': 'Colors',
                             'type': 'color', 'default': '#123456'}]}
        cpp = core.cpp(value)
        swift = design.swift(value)
        self.assertIn('SkColorSetA(0x123456, 255)', cpp)
        self.assertIn('result.text_color = std::nullopt', cpp)
        self.assertIn('initialColor: "#123456"', swift)
        self.assertIn('colors[token.id] ?? token.initialColor', swift)
