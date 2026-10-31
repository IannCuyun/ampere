import unittest

from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, *message):
        self.messages.append(message)


class Media:
    def __init__(self):
        self.begun = []

    def begin(self, file, kind):
        self.begun.append((file, kind))
        return 4

    def accepts(self, generation, file, current_file):
        return generation == 4 and file == current_file


class SongMetadataPublicationTests(unittest.TestCase):
    def test_new_song_clears_stale_metadata_and_tail_before_worker_launch(self):
        backend = type("Harness", (), {})()
        backend._audio_info = "MP3 · 128 kbps"
        backend._rg_track_db = -8.0
        backend._lyrics = [{"line": "previous"}]
        backend._lyrics_synced = True
        backend._tail_cut = 45.0
        backend._media = Media()
        backend.statusChanged = Signal()
        backend.lyricsChanged = Signal()
        backend._arm_trim = lambda: None
        backend._start_worker = lambda *_args, **_kwargs: False

        Backend._start_song_meta(backend, "Artist/new.flac", 240)

        self.assertEqual("FLAC", backend._audio_info)
        self.assertIsNone(backend._rg_track_db)
        self.assertEqual([], backend._lyrics)
        self.assertFalse(backend._lyrics_synced)
        self.assertEqual(0.0, backend._tail_cut)
        self.assertEqual([("Artist/new.flac", "metadata")],
                         backend._media.begun)
        self.assertTrue(backend.statusChanged.messages)
        self.assertTrue(backend.lyricsChanged.messages)

    def test_current_worker_result_refines_fade_with_returned_tags(self):
        backend = type("Harness", (), {})()
        backend._media = Media()
        backend._song = {"file": "Artist/current.flac"}
        backend.statusChanged = Signal()
        backend.lyricsChanged = Signal()
        backend._arm_trim = lambda: None
        backend.fade_tags = []
        backend._apply_fade_xfade = lambda end, gain: (
            backend.fade_tags.append((end, gain)))
        result = {
            "info": "FLAC", "rg": -7.0, "lyrics": [], "synced": False,
            "tail": 0.0, "mixramp_end": "-30 200; -10 190",
            "replay_gain_text": "-7 dB",
        }

        Backend._on_song_meta(backend, 3, "Artist/current.flac", result)
        Backend._on_song_meta(backend, 4, "Artist/current.flac", result)

        self.assertEqual(
            [("-30 200; -10 190", "-7 dB")], backend.fade_tags)


if __name__ == "__main__":
    unittest.main()
