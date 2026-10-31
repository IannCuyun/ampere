import unittest

from PySide6.QtCore import QObject

from ampere.mpdclient import Backend


class SilentFailureFeedbackTests(unittest.TestCase):
    """Every dead-end user action surfaces one honest errorOccurred toast."""

    @staticmethod
    def backend():
        backend = Backend.__new__(Backend)
        QObject.__init__(backend)
        backend._drop_disliked = lambda files, keep="": []
        backend._taste_mutation_busy = True
        backend.errors = []
        backend.errorOccurred.connect(backend.errors.append)
        backend._request_queue_intent = lambda *a, **k: True
        backend._request_soft_queue_intent = lambda *a, **k: True
        return backend

    def test_empty_queue_actions_explain_themselves(self):
        backend = self.backend()
        self.assertFalse(backend.queueFiles([]))
        self.assertFalse(backend.queueAlbum([""]))
        self.assertFalse(backend.playNext(""))
        self.assertEqual(
            ["Nothing to queue", "Nothing to queue", "Nothing to play next"],
            backend.errors)

    def test_fully_filtered_explicit_play_explains_itself(self):
        backend = self.backend()
        self.assertFalse(backend._play_explicit(
            ["bad.flac"], 0, keep_disliked=False))
        self.assertEqual(
            ["Nothing playable here — every track is out of rotation"],
            backend.errors)

    def test_busy_taste_mutation_explains_itself(self):
        backend = self.backend()
        self.assertFalse(backend.toggleLike("song.flac"))
        self.assertEqual(["Still saving your last rating"], backend.errors)
        backend.errors.clear()
        self.assertFalse(backend.toggleLike(""))
        self.assertEqual([], backend.errors)


if __name__ == "__main__":
    unittest.main()
