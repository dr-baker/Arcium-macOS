import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("patch_candidates", Path(__file__).parents[1] / "patch_candidates.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PatchCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = self.root / "old", self.root / "new"
        self.name = "personal/feature.patch"
        self.file = "ui/window.cc"
        self.patch = self.root / "feature.patch"
        self.patch.write_text("--- a/ui/window.cc\n+++ b/ui/window.cc\n@@ -1,3 +1,3 @@\n-old\n+local\n keep\n tail\n")
        for src in (self.old, self.new):
            before = src / ".pc" / self.name / self.file
            before.parent.mkdir(parents=True)
            before.write_text("old\nkeep\ntail\n")
            current = src / self.file
            current.parent.mkdir(parents=True)
            current.write_text("current source must stay unchanged\n")

    def run_candidates(self):
        return module.candidates(self.old, self.new, self.name, self.patch,
                                 [self.file], self.root / "output")

    def test_preserves_both_changes_without_touching_sources(self):
        (self.new / ".pc" / self.name / self.file).write_text("old\nkeep\ntail\nupstream\n")
        before = {str(p): p.read_bytes() for src in (self.old, self.new) for p in src.rglob("*") if p.is_file()}
        report = self.run_candidates()
        self.assertEqual(report[0]["conflicts"], 0)
        self.assertEqual((self.root / "output" / self.file).read_text(), "local\nkeep\ntail\nupstream\n")
        self.assertTrue(all(Path(path).read_bytes() == content for path, content in before.items()))

    def test_conflict_is_a_candidate_not_a_silent_resolution(self):
        (self.new / ".pc" / self.name / self.file).write_text("upstream\nkeep\ntail\n")
        report = self.run_candidates()
        self.assertEqual(report[0]["conflicts"], 1)
        candidate = (self.root / "output" / self.file).read_text()
        self.assertIn("<<<<<<< new preimage", candidate)
        self.assertIn("||||||| old preimage", candidate)
        self.assertIn(">>>>>>> local patch", candidate)

    def test_already_applied_old_patch_is_rejected_not_reversed(self):
        (self.old / ".pc" / self.name / self.file).write_text("local\nkeep\ntail\n")
        self.assertIn("error", self.run_candidates()[0])
        self.assertFalse((self.root / "output" / self.file).exists())

    def test_added_file_reconstructs_from_empty_quilt_preimages(self):
        self.patch.write_text("--- /dev/null\n+++ b/ui/window.cc\n@@ -0,0 +1 @@\n+local\n")
        for src in (self.old, self.new):
            (src / ".pc" / self.name / self.file).write_text("")
        report = self.run_candidates()
        self.assertEqual(report[0]["conflicts"], 0)
        self.assertEqual((self.root / "output" / self.file).read_text(), "local\n")
        for src in (self.old, self.new):
            self.assertEqual((src / self.file).read_text(), "current source must stay unchanged\n")

    def test_added_file_rejects_nonempty_old_preimage(self):
        self.patch.write_text("--- /dev/null\n+++ b/ui/window.cc\n@@ -0,0 +1 @@\n+local\n")
        self.assertIn("error", self.run_candidates()[0])
        self.assertFalse((self.root / "output" / self.file).exists())

    def test_refuses_outputs_inside_source_and_traversal(self):
        with self.assertRaises(ValueError):
            module.candidates(self.old, self.new, self.name, self.patch,
                              [self.file], self.new / "output")
        with self.assertRaises(ValueError):
            module.candidates(self.old, self.new, "../feature.patch", self.patch,
                              [self.file], self.root / "output")


if __name__ == "__main__":
    unittest.main()
