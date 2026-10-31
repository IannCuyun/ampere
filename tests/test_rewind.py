import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ampere.mpdclient import Backend
from ampere.rewind import RewindService


def local_time(year, month, day, hour=12):
    return int(time.mktime((year, month, day, hour, 0, 0, 0, 0, -1)))


class RewindServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = local_time(2026, 7, 30, 18)
        self.service = RewindService(clock=lambda: self.now)
        self.library = {
            "Rock/A/one.flac": {
                "file": "Rock/A/one.flac", "title": "One",
                "artist": "Alpha", "duration": 180,
            },
            "Folk/B/two.flac": {
                "file": "Folk/B/two.flac", "title": "Two",
                "artist": "Beta", "duration": 240,
            },
        }

    def test_stats_aggregate_tracks_artists_genres_and_recent_windows(self):
        result = self.service.stats(
            counts={"Rock/A/one.flac": 3, "Folk/B/two.flac": 2},
            library=self.library,
            entries=[(self.now - 86400, "Rock/A/one.flac"),
                     (self.now - 10 * 86400, "Folk/B/two.flac")],
            artist_path=lambda file, artist: file.rsplit("/", 1)[0])
        self.assertEqual(result["totalPlays"], 5)
        self.assertEqual(result["tracksPlayed"], 2)
        self.assertEqual((result["week"], result["month"]), (1, 2))
        self.assertEqual(result["monthArtists"], 2)
        self.assertEqual(["Alpha", "Beta"], [
            row["name"] for row in result["monthTopArtists"]])
        self.assertEqual(result["topArtists"][0]["name"], "Alpha")
        self.assertEqual(result["topGenres"][0]["genre"], "Rock")

    def test_history_exposes_the_timestamp_name_consumed_by_qml(self):
        played = self.now - 60
        result = self.service.history(
            entries=[(played, "Rock/A/one.flac")], library=self.library)
        self.assertEqual(result["rows"][0]["ts"], played)
        self.assertEqual(result["rows"][0]["t"], played)
        self.assertEqual(len(result["days"]), 14)
        self.assertEqual(sum(day["count"] for day in result["days"]), 1)
        today = result["days"][-1]
        self.assertEqual(today["file"], "Rock/A/one.flac")
        self.assertEqual(today["title"], "One")
        self.assertEqual(today["artist"], "Alpha")
        self.assertEqual(today["records"], 1)

    def test_history_day_art_uses_most_played_file_with_recent_tie_break(self):
        older = self.now - 180
        newer = self.now - 60
        result = self.service.history(
            entries=[
                (older, "Folk/B/two.flac"),
                (older + 1, "Rock/A/one.flac"),
                (newer, "Rock/A/one.flac"),
            ],
            library=self.library,
        )

        today = result["days"][-1]
        self.assertEqual(today["file"], "Rock/A/one.flac")
        self.assertEqual(today["count"], 3)
        self.assertEqual(today["records"], 2)

    def test_chapters_and_recap_share_the_same_period_policy(self):
        july = local_time(2026, 7, 5)
        june = local_time(2026, 6, 5)
        entries = [(july, "Rock/A/one.flac"),
                   (july + 1, "Rock/A/one.flac"),
                   (june, "Folk/B/two.flac")]
        chapters = self.service.chapters(
            entries=entries,
            first_played={"Rock/A/one.flac": july,
                          "Folk/B/two.flac": june},
            library=self.library)
        self.assertEqual([row["key"] for row in chapters],
                         ["2026", "2026-07", "2026-06"])
        self.assertEqual(chapters[1]["topTracks"][0]["plays"], 2)
        label, files = self.service.recap_files(entries, "2026-07")
        self.assertEqual(label, "Jul 2026")
        self.assertEqual(files, ["Rock/A/one.flac"])

    def test_sound_profile_weights_only_played_files(self):
        result = self.service.sound_profile(
            counts={"Rock/A/one.flac": 3, "Folk/B/two.flac": 1},
            energies={"Rock/A/one.flac": .85, "Folk/B/two.flac": .25},
            bpms={"Rock/A/one.flac": 140, "Folk/B/two.flac": 80},
            keys={"Rock/A/one.flac": 14, "Folk/B/two.flac": 2},
            entries=[(self.now, "Rock/A/one.flac")],
            key_label=lambda key: (f"K{key}", "1A"))
        self.assertEqual(result["energyHist"][8], 3)
        self.assertEqual(result["medianBpm"], 140)
        self.assertAlmostEqual(result["minorShare"], .75)

    def test_song_story_ranks_recent_plays_and_finds_time_of_day(self):
        evening = local_time(2026, 7, 29, 19)
        entries = [
            (evening, "Rock/A/one.flac"),
            (evening - 86400, "Rock/A/one.flac"),
            (evening - 2 * 86400, "Rock/A/one.flac"),
            (evening, "Folk/B/two.flac"),
            (evening - 1, "Folk/B/two.flac"),
            (evening - 2, "Folk/B/two.flac"),
            (self.now + 86400, "Folk/B/two.flac"),  # future corruption
        ]
        story = self.service.song_story(
            "Rock/A/one.flac", entries=entries,
            first_played={"Rock/A/one.flac": evening - 2 * 86400},
            play_count=12)
        self.assertEqual(story, {
            "firstHeard": evening - 2 * 86400,
            "plays": 12, "rankMonth": 1, "hourWord": "an evening"})

    def test_top_artists_aggregate_tracks_and_resolve_presentation_path(self):
        library = dict(self.library)
        library["Rock/A/three.flac"] = {
            "file": "Rock/A/three.flac", "artist": "Alpha", "duration": 200}
        rows = self.service.top_artists(
            counts={"Rock/A/one.flac": 3, "Rock/A/three.flac": 4,
                    "Folk/B/two.flac": 5, "missing.flac": 100},
            library=library, limit=2,
            artist_path=lambda file, _artist: file.rsplit("/", 1)[0])
        self.assertEqual([(row["name"], row["plays"]) for row in rows],
                         [("Alpha", 7), ("Beta", 5)])
        self.assertEqual(rows[0]["path"], "Rock/A")
        self.assertEqual(rows[0]["cover"], "Rock/A")


class RewindSoundProfileWorkerTests(unittest.TestCase):
    def test_song_story_uses_cached_count_without_sticker_io(self):
        backend = type("BackendHarness", (), {})()
        backend._rewind = RewindService(clock=lambda: 2_000_000_000)
        backend._library_playcounts = {"song.flac": 12}
        backend._stickers = type("Stickers", (), {
            "integer": lambda *_args: self.fail("read sticker"),
        })()
        backend._play_history = type("History", (), {
            "snapshot": lambda self: type("Snapshot", (), {
                "entries": ((1_900_000_000, "song.flac"),),
                "first_played": {"song.flac": 1_900_000_000},
            })(),
        })()

        story = Backend.songStory(backend, "song.flac")
        cold = Backend.songStory(backend, "unseen.flac")

        self.assertEqual(12, story["plays"])
        self.assertEqual(0, cold["plays"])

    def test_cached_profile_and_request_do_no_sticker_io_on_caller(self):
        backend = type("BackendHarness", (), {})()
        backend._sound_profile_snapshot = {
            "ready": True, "data": {"medianBpm": 132},
        }
        backend._enrichment = type("Coordinator", (), {
            "launch": lambda self, *args, **kwargs: "started",
        })()
        backend._sound_profile_worker = lambda: None
        backend._on_sound_profile_finished = lambda: None
        backend._playcounts = lambda: self.fail("read play counts")
        backend._sticker_map = lambda *_args: self.fail("read stickers")

        profile = Backend.soundProfile(backend)
        launch = Backend.requestSoundProfile(backend)

        self.assertTrue(profile["ready"])
        self.assertEqual(132, profile["medianBpm"])
        self.assertEqual("started", launch)

    def test_worker_uses_one_scoped_client_for_every_family(self):
        backend = type("BackendHarness", (), {})()
        backend._workers = object()
        backend._rewind = RewindService(clock=lambda: 2_000_000_000)
        backend._play_history = type("History", (), {
            "snapshot": lambda self: type("Snapshot", (), {
                "entries": ((1_900_000_000, "song.flac"),),
            })(),
        })()
        backend._dj_key_label = lambda key: (f"K{key}", "1A")
        emitted = []
        backend._soundProfileReady = type("Signal", (), {
            "emit": lambda self, value: emitted.append(value),
        })()
        client = object()
        calls = []
        values = {
            "playCount": {"song.flac": "3"},
            "joi_energy": {"song.flac": ".8"},
            "joi_bpm": {"song.flac": "140"},
            "joi_cues": {"song.flac": '{"key": 14}'},
        }

        class Result:
            available = True
            retained = False

            def __init__(self, rows):
                self.values = rows

        backend._stickers = type("Stickers", (), {
            "values_result": lambda self, name, scoped: (
                calls.append((name, scoped)) or Result(values[name])),
        })()

        @contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            Backend._sound_profile_worker(backend)

        self.assertEqual(4, len(calls))
        self.assertTrue(all(scoped is client for _, scoped in calls))
        self.assertEqual(140, emitted[0]["medianBpm"])
        self.assertEqual(3, emitted[0]["energyHist"][8])

    def test_failed_result_retains_profile_and_warns_once(self):
        backend = type("BackendHarness", (), {})()
        backend._sound_profile_snapshot = {
            "ready": True, "data": {"medianBpm": 132},
        }
        backend._sound_profile_failed = False
        backend.errorOccurred = type("Signal", (), {
            "__init__": lambda self: setattr(self, "messages", []),
            "emit": lambda self, message: self.messages.append(message),
        })()
        backend.soundProfileChanged = type("Signal", (), {
            "emit": lambda self: None,
        })()

        Backend._on_sound_profile_ready(backend, None)
        Backend._on_sound_profile_ready(backend, None)

        self.assertEqual(132, backend._sound_profile_snapshot["data"]["medianBpm"])
        self.assertEqual(1, len(backend.errorOccurred.messages))


if __name__ == "__main__":
    unittest.main()
