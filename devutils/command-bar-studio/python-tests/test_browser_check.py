import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('browser_check', Path(__file__).resolve().parents[1] / 'browser_check.py')
check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)


class MaterialRuntimeTests(unittest.TestCase):
    def test_owned_copy_is_removed_but_matching_existing_copy_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'production.dylib'; source.write_bytes(b'production')
            target = root / 'Frameworks/production.dylib'
            with check.material_runtime(source, target): self.assertEqual(target.read_bytes(), b'production')
            self.assertFalse(target.parent.exists())
            target.parent.mkdir(); target.write_bytes(b'production')
            with check.material_runtime(source, target): pass
            self.assertEqual(target.read_bytes(), b'production')

    def test_conflicting_or_changed_copy_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'production.dylib'; source.write_bytes(b'production')
            target = root / 'Frameworks/production.dylib'; target.parent.mkdir(); target.write_bytes(b'other')
            with self.assertRaisesRegex(RuntimeError, 'conflicting'):
                with check.material_runtime(source, target): pass
            self.assertEqual(target.read_bytes(), b'other'); target.unlink()
            with self.assertRaisesRegex(RuntimeError, 'Preserve changed'):
                with check.material_runtime(source, target): target.write_bytes(b'changed during run')
            self.assertEqual(target.read_bytes(), b'changed during run')
