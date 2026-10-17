"""Build guards against subprocess output from the build tools."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import agent  # noqa: E402
from he.common import HeError, Paths  # noqa: E402


class BuildGuardTest(unittest.TestCase):
    def test_non_utf8_diagnostics_preserve_edge_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = Paths(root, root / "build")
            runner = paths.src / "third_party/depot_tools/autoninja.py"
            runner.parent.mkdir(parents=True)
            runner.write_text(
                "import sys\n"
                "sys.stdout.buffer.write(b'[1/2] compile\\n[2/2] link\\n')\n"
                "sys.stderr.buffer.write(b'diagnostic: \\xff\\n')\n"
            )

            with self.assertRaisesRegex(HeError, "plans 2 edges"):
                agent.guard_build(paths, ["chrome"], budget=1,
                                  approved=False, problems=[])

            plan = (paths.state / "last-plan.txt").read_text()
            self.assertIn("[2/2] link", plan)
            self.assertIn("diagnostic: \ufffd", plan)


if __name__ == "__main__":
    unittest.main()
