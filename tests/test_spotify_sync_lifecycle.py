import unittest

from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class Enrichment:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def launch(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.outcome


class SpotifySyncLifecycleTests(unittest.TestCase):
    def backend(self, outcome="started"):
        backend = type("Harness", (), {})()
        backend._enrichment = Enrichment(outcome)
        backend._search_index = [{"song": {
            "file": "Artist/song.flac", "title": "Song",
            "artist": "Artist"}}]
        backend._spot_worker = lambda *_args: None
        backend.spotSyncDone = Signal()
        return backend

    def test_invalid_name_does_not_launch(self):
        backend = self.backend()

        Backend.syncSpotifyPlaylist(backend, "   ")

        self.assertEqual([], backend._enrichment.calls)
        self.assertIn("needs a playlist name", backend.spotSyncDone.messages[0])

    def test_duplicate_and_shutdown_rejections_are_explicit(self):
        for outcome, phrase in (("busy", "already running"),
                                ("stopping", "could not start")):
            with self.subTest(outcome=outcome):
                backend = self.backend(outcome)
                Backend.syncSpotifyPlaylist(backend, "Road Trip")
                self.assertIn(phrase, backend.spotSyncDone.messages[0])

    def test_started_sync_uses_named_exclusive_job(self):
        backend = self.backend()

        Backend.syncSpotifyPlaylist(backend, "Road Trip")

        args, kwargs = backend._enrichment.calls[0]
        self.assertEqual("spotify", args[0])
        self.assertEqual(("Road Trip", [{
            "file": "Artist/song.flac", "title": "Song",
            "artist": "Artist"}]), kwargs["args"])
        self.assertEqual([], backend.spotSyncDone.messages)


if __name__ == "__main__":
    unittest.main()
