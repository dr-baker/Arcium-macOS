"""Public previews must not package Chromium's placeholder legal notices."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_preview import verify_credits


class PreviewCreditsTest(unittest.TestCase):
    def test_missing_or_sample_credits_block_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'build full credits'):
                verify_credits(out)
            credits = out / 'gen/components/resources/about_credits.html'
            credits.parent.mkdir(parents=True)
            credits.write_text('Sample credits. Set generate_about_credits=true.')
            with self.assertRaisesRegex(RuntimeError, 'credits are incomplete'):
                verify_credits(out)

    def test_required_project_notices_are_checked_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            credits = out / 'gen/components/resources/about_credits.html'
            credits.parent.mkdir(parents=True)
            notices = ('Helium', 'Chromium', 'GNU GENERAL PUBLIC LICENSE')
            for missing in notices:
                with self.subTest(missing=missing):
                    credits.write_text('\n'.join(n for n in notices if n != missing))
                    with self.assertRaisesRegex(RuntimeError, 'credits are incomplete'):
                        verify_credits(out)
            credits.write_text('\n'.join(notices))
            verify_credits(out)


if __name__ == '__main__':
    unittest.main()
