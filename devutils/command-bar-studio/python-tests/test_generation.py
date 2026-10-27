import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'studio_generation', Path(__file__).resolve().parents[1] / 'iteration.py')
iteration = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = iteration
spec.loader.exec_module(iteration)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'source'
        self.cache = Path(temporary.name) / 'cache'
        for repo, mapping in ((self.root, 'platform_resources.txt'),
                              (self.root / 'helium-chromium', 'helium_resources.txt')):
            (repo / 'patches').mkdir(parents=True)
            (repo / 'patches/series').write_text('fixture.patch\n')
            (repo / 'patches/fixture.patch').write_text('original patch\n')
            (repo / 'resources').mkdir()
            (repo / 'resources' / mapping).write_text('fixture.bin destination\n')
            (repo / 'resources/fixture.bin').write_bytes(b'original resource')
        lab = self.root / 'devutils/command-bar-studio'
        lab.mkdir(parents=True)
        (lab / 'native_host.mm').write_text('host')
        self.patch = self.root / 'patches/fixture.patch'

    def test_nested_sdk_lock_remains_exclusive_for_other_threads(self):
        import threading
        entered = threading.Event()
        def contender():
            with iteration.build_lock(self.cache): entered.set()
        with iteration.build_lock(self.cache):
            with iteration.build_lock(self.cache):
                worker = threading.Thread(target=contender)
                worker.start()
                self.assertFalse(entered.wait(.05))
            self.assertFalse(entered.is_set())
        worker.join(timeout=2)
        self.assertTrue(entered.is_set())
        self.assertFalse(worker.is_alive())

    def test_source_edit_cannot_change_captured_generation(self):
        generation = iteration.capture(self.root, self.cache)
        self.patch.write_text('new patch\n')
        self.assertEqual((generation.root / 'patches/fixture.patch').read_text(), 'original patch\n')
        with self.assertRaises(iteration.SupersededIteration):
            generation.require_current()

    def test_direct_sdk_edits_are_frozen_watched_and_supersede_candidates(self):
        source = self.cache.parent / 'sdk-renderer.cc'; source.write_text('experiment one')
        extra = {'.sdk-experiments/renderer.cc': source}
        generation = iteration.capture(self.root, self.cache, extra_files=extra)
        before = iteration.stamps(self.root, extra_files=extra)
        source.write_text('experiment two')
        self.assertNotEqual(before, iteration.stamps(self.root, extra_files=extra))
        self.assertEqual((generation.root / '.sdk-experiments/renderer.cc').read_text(), 'experiment one')
        with self.assertRaises(iteration.SupersededIteration): generation.require_current()
        self.assertNotEqual(generation.identity, iteration.capture(self.root, self.cache, extra_files=extra).identity)

    def test_resource_changes_supersede_generation(self):
        generation = iteration.capture(self.root, self.cache)
        (self.root / 'resources/fixture.bin').write_bytes(b'new resource')
        with self.assertRaises(iteration.SupersededIteration):
            generation.require_current()

    def test_build_configuration_changes_supersede_generation(self):
        config = self.root / 'flags.macos.gn'; config.write_text('old build flags')
        generation = iteration.capture(self.root, self.cache)
        config.write_text('new build flags')
        self.assertEqual((generation.root / 'flags.macos.gn').read_text(), 'old build flags')
        with self.assertRaises(iteration.SupersededIteration): generation.require_current()

    def test_unchanged_inputs_reuse_exact_generation(self):
        first = iteration.capture(self.root, self.cache)
        second = iteration.capture(self.root, self.cache)
        self.assertEqual(first.root, second.root)
        self.assertEqual(first.identity, second.identity)

    def test_design_schema_and_generator_are_frozen_and_supersede_candidates(self):
        generator = self.root / 'helium-chromium/devutils/command_design.py'
        schema = self.root / 'helium-chromium/devutils/ui/command_bar_design.json'
        schema.parent.mkdir(parents=True)
        schema.write_text('{"version":1}')
        generator.write_text('original generator')
        generation = iteration.capture(self.root, self.cache)
        self.assertEqual((generation.root / schema.relative_to(self.root)).read_text(), '{"version":1}')
        generator.write_text('new generator')
        with self.assertRaises(iteration.SupersededIteration): generation.require_current()
        next_generation = iteration.capture(self.root, self.cache)
        schema.write_text('{"version":2}')
        with self.assertRaises(iteration.SupersededIteration): next_generation.require_current()

    def test_modified_cached_generation_is_rejected(self):
        generation = iteration.capture(self.root, self.cache)
        cached = generation.root / 'patches/fixture.patch'
        cached.chmod(0o644)
        cached.write_text('unexpected change')
        with self.assertRaisesRegex(RuntimeError, 'generation was modified'):
            iteration.capture(self.root, self.cache)

    def test_publication_records_generation_atomically(self):
        generation = iteration.capture(self.root, self.cache)
        state = self.cache / 'instance'
        iteration.publish_latest(state, Path('/independent/app'), generation)
        result = json.loads((state / 'latest.json').read_text())
        self.assertEqual(result['generation'], generation.identity)
        self.assertEqual(result['app'], '/independent/app')
        self.assertFalse((state / 'latest.pending.json').exists())
