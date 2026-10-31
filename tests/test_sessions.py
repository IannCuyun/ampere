import unittest
import random

from ampere.sessions import SessionService


class SessionServiceTests(unittest.TestCase):
    def test_curated_sessions_are_mutually_exclusive_and_enable_refill(self):
        sessions = SessionService()
        sessions.commit_curated(mood="calm")
        self.assertEqual("mood", sessions.state.kind)
        self.assertTrue(sessions.state.radio_enabled)
        sessions.commit_curated(sonic_profile="bass")
        self.assertEqual("", sessions.state.mood)
        self.assertEqual("bass", sessions.state.sonic_profile)

    def test_disabling_radio_ends_curated_state(self):
        sessions = SessionService(radio_enabled=True)
        sessions.commit_curated(mood="dark")
        sessions.set_radio(False)
        self.assertEqual("manual", sessions.state.kind)

    def test_ending_curated_keeps_plain_radio_preference(self):
        sessions = SessionService(radio_enabled=True)
        sessions.commit_curated(mood="happy")
        self.assertTrue(sessions.end_curated())
        self.assertEqual("radio", sessions.state.kind)

    def test_radio_ranking_respects_energy_mode_and_queue(self):
        songs = [
            {"file": "Rap/A/one.flac", "artist": "A", "title": "One"},
            {"file": "Rap/B/two.flac", "artist": "B", "title": "Two"},
            {"file": "Rap/C/three.flac", "artist": "C", "title": "Three"},
        ]
        picks = SessionService().radio_picks(
            songs, seed=songs[0], queued={songs[1]["file"]},
            energies={songs[0]["file"]: .8, songs[2]["file"]: .9},
            mood="heavy", now=1000, rng=random.Random(1))
        self.assertEqual([songs[2]["file"]], picks)

    def test_mood_ranking_excludes_unlisted_genres_but_keeps_exemplars(self):
        songs = [
            {"file": "Folk/A/calm.flac", "artist": "A", "title": "Calm"},
            {"file": "Metal/B/loud.flac", "artist": "B", "title": "Loud"},
        ]
        spec = {"genres": {"Folk": .8}, "energy": (0, .45)}
        service = SessionService()
        self.assertEqual([songs[0]["file"]], service.mood_picks(
            songs, spec, energies={songs[0]["file"]: .2,
                                   songs[1]["file"]: .9},
            now=1000, rng=random.Random(2)))
        self.assertIn(songs[1]["file"], service.mood_picks(
            songs, spec, exemplars={songs[1]["file"]},
            energies={songs[1]["file"]: .9}, now=1000,
            rng=random.Random(2)))

    def test_sonic_ranking_gates_known_values_but_allows_unknowns(self):
        songs = [{"file": "known.flac"}, {"file": "outside.flac"},
                 {"file": "unknown.flac"}]
        picks = SessionService().sonic_picks(
            songs, {"energy": (.6, 1, .1)},
            {"energy": {"known.flac": .8, "outside.flac": .2}},
            now=1000, rng=random.Random(3))
        self.assertIn("known.flac", picks)
        self.assertIn("unknown.flac", picks)
        self.assertNotIn("outside.flac", picks)

    def test_curated_session_spread_uses_artist_tags_across_album_folders(self):
        files = [
            "Rap/Trap/A/First/01.flac", "Rap/Trap/A/Second/01.flac",
            "Rap/Trap/B/Only/01.flac", "Rap/Trap/C/Only/01.flac",
        ]
        artists = {
            files[0]: "Same Artist", files[1]: "same artist",
            files[2]: "Other", files[3]: "Third",
        }

        result = SessionService.artist_spread(files, artist_keys=artists)

        normalized = [artists[file].casefold() for file in result]
        self.assertFalse(any(
            left == right for left, right in zip(normalized, normalized[1:])))


if __name__ == "__main__":
    unittest.main()


class SessionOwnershipContractTests(unittest.TestCase):
    """One session owns the queue at a time, and one place answers which
    (ROADMAP 3.1, 2026-08-22).

    Both refills used to re-derive the active session for themselves, each
    with its own legacy fallback. They now ask Backend._session_kind, so the
    four transition layers cannot drift apart again.
    """

    class Harness:
        _repeat = False
        _dj_on = False
        _state = "play"
        _queue_pos = 0
        _queue = ({"file": "a"},)

    def kind_of(self, **attrs):
        from ampere.mpdclient import Backend
        harness = self.Harness()
        for key, value in attrs.items():
            setattr(harness, key, value)
        return Backend._session_kind(harness)

    def test_the_service_answers_when_it_has_a_session(self):
        sessions = SessionService()
        sessions.commit_curated(mood="dark")
        self.assertEqual("mood", self.kind_of(_sessions=sessions))
        sessions.set_smart_shuffle({"file": "seed.flac"})
        self.assertEqual("smart-shuffle", self.kind_of(_sessions=sessions))

    def test_smart_shuffle_outranks_autoplay_and_curated_outranks_both(self):
        self.assertEqual("smart-shuffle", self.kind_of(
            _autoplay_on=True, _context_shuffle_mode="smart"))
        self.assertEqual("mood", self.kind_of(
            _mood_on="dark", _autoplay_on=True,
            _context_shuffle_mode="smart"))

    def test_smart_shuffle_answers_only_when_nothing_outranks_it(self):
        self.assertEqual("smart-shuffle",
                         self.kind_of(_context_shuffle_mode="smart"))
        self.assertEqual("manual", self.kind_of(_context_shuffle_mode="off"))

    def test_repeat_and_dj_block_every_session_refill(self):
        from ampere.mpdclient import Backend
        for attr in ("_repeat", "_dj_on"):
            harness = self.Harness()
            setattr(harness, attr, True)
            self.assertTrue(Backend._refill_blocked(harness), attr)
        self.assertFalse(Backend._refill_blocked(self.Harness()))

    def test_one_dryness_threshold_serves_every_session(self):
        from ampere.mpdclient import Backend
        self.assertEqual(Backend.REFILL_AT, Backend.SMART_REFILL_AT)
        harness = self.Harness()
        harness._queue = tuple({"file": str(i)} for i in range(9))
        harness._queue_pos = 0
        self.assertFalse(Backend._queue_is_dry(harness))
        harness._queue_pos = 6
        self.assertTrue(Backend._queue_is_dry(harness))
