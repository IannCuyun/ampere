import threading
import unittest
from unittest.mock import patch

from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class AuditionHarness:
    def __init__(self):
        self._audition_lock = threading.Lock()
        self._audition_gen = 4
        self._audition_proc = None
        self.errorOccurred = Signal()

    def _audition_failed(self, gen, message):
        return Backend._audition_failed(self, gen, message)


class DjAuditionTests(unittest.TestCase):
    def test_current_failure_is_published_but_superseded_failure_is_silent(self):
        backend = AuditionHarness()

        self.assertTrue(Backend._audition_failed(
            backend, 4, "preview failed"))
        self.assertFalse(Backend._audition_failed(
            backend, 3, "stale failure"))

        self.assertEqual(["preview failed"], backend.errorOccurred.messages)

    def test_player_launch_failure_is_observable(self):
        backend = AuditionHarness()

        with patch("ampere.mpdclient.subprocess.Popen", side_effect=OSError):
            Backend._audition_play(backend, 4, ["pw-play", "preview.wav"])

        self.assertIsNone(backend._audition_proc)
        self.assertEqual(1, len(backend.errorOccurred.messages))
        self.assertIn("could not start", backend.errorOccurred.messages[0])

    def test_superseded_player_launch_is_not_attempted(self):
        backend = AuditionHarness()

        with patch("ampere.mpdclient.subprocess.Popen") as popen:
            Backend._audition_play(backend, 3, ["pw-play", "old.wav"])

        popen.assert_not_called()
        self.assertEqual([], backend.errorOccurred.messages)


if __name__ == "__main__":
    unittest.main()
