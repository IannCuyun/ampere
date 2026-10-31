import unittest
import random
from contextlib import contextmanager
from unittest.mock import patch

from ampere.mpdclient import Backend
from ampere.home import HomeProjection
from ampere.library import LibraryRepository
from ampere.shelves import ShelfService
from ampere.rewind import RewindService


class ShelfSummaryTests(unittest.TestCase):
    def test_library_totals_are_read_from_the_verified_cache(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.publish_stats({
            "songs": "12", "albums": "3", "artists": "2",
            "db_playtime": "5400",
        })
        backend._call = lambda *_args, **_kwargs: self.fail("read MPD stats")

        self.assertEqual({
            "songs": 12, "albums": 3, "artists": 2,
            "genres": 0,
            "playtimeHours": 1.5,
        }, Backend.stats(backend))

    def test_rediscovery_is_not_ready_from_a_partial_cache(self):
        backend = type("BackendHarness", (), {
            "_smart_shelves": {"deep": [{"file": "deep.flac"}]},
        })()

        result = Backend.cachedRediscovery(backend)

        self.assertFalse(result["ready"])
        self.assertEqual([], result["files"])

    def test_cached_library_summary_never_scans_on_the_calling_thread(self):
        backend = type("BackendHarness", (), {})()
        backend._library_summary = {
            "shelves": [{"shelf": "deep", "count": 7}],
            "artists": [{"name": "Artist"}],
        }
        backend._smart_shelves = {
            "deep": [{"file": "Rock/Artist/deep.flac"}],
            "loved": [{"file": "Rock/Artist/deep.flac"},
                      {"file": "Rock/Artist/loved.flac"}],
        }
        backend._rewind_overview = {
            "ready": True,
            "stats": {"totalPlays": 7},
            "history": {"rows": [{"title": "A"}]},
            "chapters": [{"key": "2026"}],
        }
        backend._enrichment = type("Coordinator", (), {
            "launch": lambda self, *args, **kwargs: "started",
        })()
        backend._library_summary_worker = lambda: None
        backend._on_library_summary_finished = lambda: None
        backend._sticker_map = lambda *_args: self.fail("scanned stickers")
        backend._playcounts = lambda *_args: self.fail("scanned play counts")

        result = Backend.librarySummary(backend)
        tracks = Backend.cachedSmartShelf(backend, "deep")
        rediscovery = Backend.cachedRediscovery(backend)
        rewind = Backend.rewindOverview(backend)
        launch = Backend.requestLibrarySummary(backend)

        self.assertEqual(7, result["shelves"][0]["count"])
        self.assertEqual("Artist", result["artists"][0]["name"])
        self.assertEqual("Rock/Artist/deep.flac", tracks[0]["file"])
        self.assertTrue(rediscovery["ready"])
        self.assertEqual(["Rock/Artist/deep.flac", "Rock/Artist/loved.flac"],
                         rediscovery["files"])
        self.assertEqual(7, rewind["stats"]["totalPlays"])
        self.assertEqual("started", launch)

    def test_failed_worker_result_preserves_summary_and_warns_once(self):
        backend = type("BackendHarness", (), {})()
        backend._library_summary = {
            "shelves": [{"shelf": "deep", "count": 7}],
            "artists": [],
        }
        backend._smart_shelves = {
            "deep": [{"file": "Rock/Artist/deep.flac"}],
        }
        backend._library_playcounts = {"Rock/Artist/deep.flac": 7}
        backend._library_summary_failed = False
        backend.errorOccurred = type("Signal", (), {
            "__init__": lambda self: setattr(self, "messages", []),
            "emit": lambda self, message: self.messages.append(message),
        })()
        backend.librarySummaryChanged = type("Signal", (), {
            "emit": lambda self: None,
        })()

        Backend._on_library_summary_ready(backend, None)
        Backend._on_library_summary_ready(backend, None)

        self.assertEqual(7, backend._library_summary["shelves"][0]["count"])
        self.assertEqual("Rock/Artist/deep.flac",
                         backend._smart_shelves["deep"][0]["file"])
        self.assertEqual(7, backend._library_playcounts[
            "Rock/Artist/deep.flac"])
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_worker_uses_its_scoped_client_and_publishes_one_digest(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.replace([
            {"file": "Rock/Artist/Album/a.flac", "title": "A",
             "artist": "Artist", "album": "Album", "duration": 300},
        ])
        backend._summary_shelves = ShelfService(clock=lambda: 2_000_000_000)
        backend._home = HomeProjection()
        backend._rewind = RewindService()
        backend._play_history = type("History", (), {
            "snapshot": lambda self: type("Snapshot", (), {
                "entries": ((1_900_000_000, "Rock/Artist/Album/a.flac"),),
                "first_played": {"Rock/Artist/Album/a.flac": 1_900_000_000},
            })(),
        })()
        backend._disliked = []
        backend._liked = []
        backend._workers = object()
        backend.artistPath = lambda _file, _artist: "Rock/Artist"
        emitted = []
        backend._librarySummaryReady = type("Signal", (), {
            "emit": lambda self, value: emitted.append(value),
        })()
        client = type("Client", (), {
            "stats": lambda self: {
                "songs": "1", "albums": "1", "artists": "1",
                "db_playtime": "3600",
            },
            "search": lambda self, _query: [{
                "file": "Rock/Artist/Album/a.flac",
                "last-modified": "2026-07-30",
            }],
        })()
        calls = []

        class Result:
            available = True
            retained = False

            def __init__(self, values):
                self.values = values

        backend._stickers = type("Stickers", (), {
            "values_result": lambda self, name, scoped: (
                calls.append((name, scoped)) or Result({
                    "Rock/Artist/Album/a.flac": "4" if name == "playCount"
                    else "120" if name == "resumePos"
                    else ".7" if name == "joi_energy"
                    else "124" if name == "joi_bpm"
                    else "1900000000"
                }))
        })()

        @contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            Backend._library_summary_worker(backend)

        self.assertEqual(7, len(calls))
        self.assertTrue(all(scoped is client for _, scoped in calls))
        self.assertEqual("Artist", emitted[0]["artists"][0]["name"])
        self.assertEqual(1, emitted[0]["shelves"][0]["count"])
        self.assertEqual("A", emitted[0]["tracks"]["arrivals"][0]["title"])
        self.assertEqual(120, emitted[0]["tracks"]["unfinished"][0][
            "resumePosition"])
        self.assertEqual(4, emitted[0]["rewind"]["stats"]["totalPlays"])
        self.assertEqual("A",
                         emitted[0]["rewind"]["history"]["rows"][0]["title"])

        backend._library_summary = {"shelves": [], "artists": []}
        backend._library_playcounts = {}
        backend._library_last_played = {}
        backend._library_planning_ratings = {}
        backend._library_preferences = {}
        backend._library_planning_ready = False
        backend._library_energies = {}
        backend._library_bpms = {}
        backend._smart_shelves = {}
        backend._rewind_overview = {
            "ready": False, "stats": {}, "history": {}, "chapters": [],
        }
        backend._library_summary_failed = False
        backend.errorOccurred = type("Signal", (), {
            "__init__": lambda self: setattr(self, "messages", []),
            "emit": lambda self, message: self.messages.append(message),
        })()
        backend._search_catalog = type("Catalog", (), {
            "replace_playcounts": lambda self, values: setattr(
                self, "playcounts", dict(values)),
        })()
        backend.librarySummaryChanged = type("Signal", (), {
            "emit": lambda self: None,
        })()
        backend.libraryStatsChanged = type("Signal", (), {
            "emit": lambda self: None,
        })()
        Backend._on_library_summary_ready(backend, emitted[0])
        self.assertEqual(4, backend._search_catalog.playcounts[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual(4, backend._library_playcounts[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual("1900000000", backend._library_last_played[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual("1900000000", backend._library_planning_ratings[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual(.7, backend._library_energies[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual(124, backend._library_bpms[
            "Rock/Artist/Album/a.flac"])
        self.assertEqual("1900000000", backend._library_preferences[
            "Rock/Artist/Album/a.flac"])
        self.assertTrue(backend._library_planning_ready)
        self.assertEqual(1, Backend.stats(backend)["songs"])

        malformed = dict(emitted[0])
        malformed["playcounts"] = {"replacement.flac": "not-a-count"}
        Backend._on_library_summary_ready(backend, malformed)
        self.assertEqual({"Rock/Artist/Album/a.flac": 4},
                         backend._library_playcounts)
        malformed = dict(emitted[0])
        malformed["energies"] = {"replacement.flac": 2.0}
        Backend._on_library_summary_ready(backend, malformed)
        self.assertEqual({"Rock/Artist/Album/a.flac": .7},
                         backend._library_energies)

        malformed = dict(emitted[0])
        malformed["preferences"] = None
        Backend._on_library_summary_ready(backend, malformed)
        self.assertEqual({"Rock/Artist/Album/a.flac": "1900000000"},
                         backend._library_preferences)
        self.assertTrue(backend._library_planning_ready)

        malformed = dict(emitted[0])
        malformed["lastPlayed"] = None
        Backend._on_library_summary_ready(backend, malformed)
        self.assertEqual({"Rock/Artist/Album/a.flac": "1900000000"},
                         backend._library_last_played)
        self.assertEqual({"Rock/Artist/Album/a.flac": "1900000000"},
                         backend._library_planning_ratings)


class ShelfServiceTests(unittest.TestCase):
    NOW = 2_000_000_000

    def setUp(self):
        self.service = ShelfService(clock=lambda: self.NOW,
                                    rng=random.Random(7))
        self.library = {
            "Rock/Alt/a.flac": {"file": "Rock/Alt/a.flac", "title": "A"},
            "Rock/Alt/b.flac": {"file": "Rock/Alt/b.flac", "title": "B"},
            "Rock/Alt/c.flac": {"file": "Rock/Alt/c.flac", "title": "C"},
        }
        self.index = [{"song": song} for song in self.library.values()]

    def select(self, name, **overrides):
        values = dict(library=self.library, search_index=self.index,
                      disliked=[], liked=[], last_raw={}, counts={}, ratings={},
                      arrivals=[])
        values.update(overrides)
        return self.service.select(name, **values)

    def test_history_orders_recent_first_and_hides_disliked(self):
        rows = self.select(
            "history", disliked=["Rock/Alt/b.flac"],
            last_raw={"Rock/Alt/a.flac": self.NOW - 20,
                      "Rock/Alt/b.flac": self.NOW - 10,
                      "Rock/Alt/c.flac": self.NOW - 30})
        self.assertEqual([row["title"] for row in rows], ["A", "C"])

    def test_loved_combines_likes_and_four_star_ratings(self):
        old = self.NOW - 30 * 86400
        rows = self.select(
            "loved", liked=["Rock/Alt/a.flac"],
            ratings={"Rock/Alt/b.flac": "8", "Rock/Alt/c.flac": "bad"},
            last_raw={"Rock/Alt/a.flac": old,
                      "Rock/Alt/b.flac": old - 100})
        self.assertEqual([row["title"] for row in rows], ["B", "A"])

    def test_arrivals_use_mpd_modified_time_order(self):
        rows = self.select("arrivals", arrivals=[
            {"file": "Rock/Alt/a.flac", "last-modified": "2026-01-01"},
            {"file": "Rock/Alt/c.flac", "last-modified": "2026-02-01"},
        ])
        self.assertEqual([row["title"] for row in rows], ["C", "A"])

    def test_arrival_snapshot_rejects_malformed_replacement(self):
        expected = self.service.publish_arrivals([{
            "file": "Rock/Alt/a.flac", "last-modified": "2026-01-01",
        }])
        result = self.service.publish_arrivals([{"missing": "file"}])

        self.assertTrue(expected.success)
        self.assertFalse(result.success)
        self.assertEqual(expected.rows, result.rows)

    def test_verified_empty_arrivals_are_retained_evidence(self):
        self.assertTrue(self.service.publish_arrivals([]).success)
        unavailable = self.service.publish_arrivals(None)
        self.assertFalse(unavailable.success)
        self.assertTrue(unavailable.retained)
        self.assertEqual((), unavailable.rows)


if __name__ == "__main__":
    unittest.main()
