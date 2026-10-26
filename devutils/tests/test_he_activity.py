"""Conservative console-activity interpretation; no GUI interaction required."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from he import activity


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.reading = activity.Activity(1000, 100, idle_seconds=1,
                    on_console=True, login_done=True, display_asleep=False)

    def test_recent_input_requires_a_valid_awake_console_session(self):
        self.assertEqual(self.reading.status(now=101)[0], 'active')
        for changes, expected in [({'on_console':False}, 'away'),
                ({'login_done':False}, 'away'), ({'display_asleep':True}, 'away'),
                ({'locked_hint':True}, 'away'), ({'idle_seconds':300}, 'idle'),
                ({'on_console':None}, 'unknown'), ({'display_asleep':None}, 'unknown'),
                ({'idle_seconds':float('nan')}, 'unknown'), ({'idle_seconds':-1}, 'unknown')]:
            with self.subTest(changes=changes):
                self.assertEqual(replace(self.reading, **changes).status(now=101)[0], expected)

    def test_stale_and_clock_discontinuity_are_unknown(self):
        for now in (99, 111, float('inf')):
            self.assertEqual(self.reading.status(now=now)[0], 'unknown')

    def test_missing_lock_hint_is_not_reported_as_unlocked(self):
        with patch('he.activity.time.monotonic', return_value=101):
            record = self.reading.record()
        self.assertIsNone(record['locked_hint'])
        self.assertFalse(record['lock_hint_available'])
        self.assertEqual(record['state'], 'active')

    def test_missing_gui_session_is_unknown_even_with_zero_idle(self):
        cg, cf = Mock(), Mock()
        cg.CGSessionCopyCurrentDictionary.return_value = None
        with patch('he.activity.sys.platform','darwin'), patch('he.activity._native',return_value=(cg,cf)):
            reading = activity.sample()
        self.assertEqual(reading.status()[0], 'unknown')
        cg.CGEventSourceSecondsSinceLastEventType.assert_not_called()

    def test_native_dictionary_is_released_on_error(self):
        cg, cf = Mock(), Mock()
        cg.CGSessionCopyCurrentDictionary.return_value = 123
        cg.CGMainDisplayID.side_effect = OSError('unavailable')
        with patch('he.activity.sys.platform','darwin'), patch('he.activity._native',return_value=(cg,cf)):
            self.assertEqual(activity.sample().status()[0], 'unknown')
        cf.CFRelease.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
