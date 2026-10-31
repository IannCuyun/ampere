import unittest
from unittest.mock import patch

from ampere.library import LibraryIndexResult
from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class Coordinator:
    def __init__(self, pending=False):
        self.pending = pending

    def consume_pending(self, key):
        assert key == "index"
        value, self.pending = self.pending, False
        return value


class LibraryIndexIntegrationTests(unittest.TestCase):
    def backend(self, *, pending=False):
        calls = []
        backend = type("IndexAdapter", (), {})()
        backend._search_index = [{"stale": True}]
        backend._library_directory = {}
        backend.databaseUpdated = Signal()
        backend.libraryReadyChanged = Signal()
        backend._library_ready = False
        backend.lyricsIndexChanged = Signal()
        backend._replay_gain = "track"
        backend._dj_on = True
        backend._enrichment = Coordinator(pending)
        backend._start_rg_scan = lambda: calls.append("replaygain")
        backend._start_energy_scan = lambda: calls.append("energy")
        backend._start_dj_scan = lambda: calls.append("dj")
        backend._lyrics_index_ready = True
        backend._lyrics_index_result = object()
        backend._build_search_index = lambda: calls.append("rebuild")
        return backend, calls

    def test_failed_publication_skips_ready_signal_and_stale_enrichment(self):
        backend, calls = self.backend(pending=True)
        Backend._on_index_ready(backend, LibraryIndexResult(False))

        self.assertEqual([], backend.databaseUpdated.values)
        self.assertFalse(backend._library_ready)
        self.assertEqual([], backend.libraryReadyChanged.values)
        self.assertEqual([{"stale": True}], backend._search_index)
        self.assertEqual(["rebuild"], calls)

    def test_success_publishes_then_launches_fresh_generation_work(self):
        backend, calls = self.backend()
        index = ({"song": {"file": "fresh.flac"}},)
        directory = {"albums": ({"album": "Fresh"},)}
        Backend._on_index_ready(
            backend, LibraryIndexResult(
                True, 2, 1, index, directory=directory))

        self.assertEqual([()], backend.databaseUpdated.values)
        self.assertTrue(backend._library_ready)
        self.assertEqual([()], backend.libraryReadyChanged.values)
        self.assertEqual(list(index), backend._search_index)
        self.assertEqual(directory, backend._library_directory)
        self.assertEqual(["energy", "dj"], calls)
        self.assertFalse(backend._lyrics_index_ready)
        self.assertIsNone(backend._lyrics_index_result)
        self.assertEqual([()], backend.lyricsIndexChanged.values)

    def test_lyric_search_starts_optional_index_on_demand(self):
        backend = type("LyricAdapter", (), {})()
        backend._lyrics_index_ready = False
        backend._start_lyrics_index = lambda: calls.append("scan")
        backend._search_catalog = type("Catalog", (), {
            "lyric_query": lambda _self, text: [{"query": text}],
        })()
        calls = []

        result = Backend.searchLyrics(backend, "signal")

        self.assertEqual(["scan"], calls)
        self.assertEqual([{"query": "signal"}], result)

    def test_completed_lyric_index_publishes_and_releases_scan_heap(self):
        backend = type("LyricAdapter", (), {})()
        backend._lyrics_index_result = type("Result", (), {
            "published": True, "cancelled": False,
        })()
        backend.lyricsIndexChanged = Signal()
        backend._enrichment = type("Coordinator", (), {
            "consume_pending": lambda _self, key: False,
        })()

        with patch("ampere.mpdclient.release_unused_heap") as release:
            Backend._on_lyrics_finished(backend)

        self.assertTrue(backend._lyrics_index_ready)
        self.assertEqual([()], backend.lyricsIndexChanged.values)
        release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
