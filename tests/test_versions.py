import unittest

from ampere.mpdclient import Backend, PlanningEvidenceUnavailable
from ampere.stickers import ExclusiveStickerResult
from ampere.versions import VersionPolicy


class VersionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.songs = [
            {"file": "album/original.flac", "artist": "The Artist",
             "title": "Signal"},
            {"file": "single/radio.flac", "artist": "The Artist",
             "title": "Signal (Radio Edit)"},
            {"file": "live/live.flac", "artist": "The Artist, Guest",
             "title": "Signal - Live"},
            {"file": "other.flac", "artist": "Someone Else",
             "title": "Signal"},
        ]

    def test_normalization_groups_common_version_suffixes(self):
        groups = VersionPolicy.groups(self.songs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(next(iter(groups.values())), [
            "album/original.flac", "single/radio.flac", "live/live.flac"])

    def test_explicit_preference_wins_over_play_count(self):
        result = VersionPolicy.collapse(
            [song["file"] for song in self.songs],
            groups=VersionPolicy.groups(self.songs),
            playcounts={"album/original.flac": 50, "single/radio.flac": 2},
            preferences={"single/radio.flac": "1"})
        self.assertEqual(result, ["single/radio.flac", "other.flac"])

    def test_most_played_wins_without_preference_and_order_breaks_ties(self):
        groups = VersionPolicy.groups(self.songs)
        most_played = VersionPolicy.collapse(
            ["single/radio.flac", "album/original.flac"], groups=groups,
            playcounts={"album/original.flac": 4, "single/radio.flac": 1},
            preferences={})
        tied = VersionPolicy.collapse(
            ["single/radio.flac", "album/original.flac"], groups=groups,
            playcounts={}, preferences={})
        self.assertEqual(most_played, ["album/original.flac"])
        # Stable library-group order is the existing deterministic tie-break.
        self.assertEqual(tied, ["album/original.flac"])

    def test_single_present_version_is_never_removed(self):
        result = VersionPolicy.collapse(
            ["live/live.flac", "other.flac"],
            groups=VersionPolicy.groups(self.songs),
            playcounts={}, preferences={})
        self.assertEqual(result, ["live/live.flac", "other.flac"])

    def test_preference_target_resolves_to_all_siblings(self):
        self.assertEqual(
            VersionPolicy.siblings("single/radio.flac", songs=self.songs),
            ["album/original.flac", "single/radio.flac", "live/live.flac"])
        self.assertEqual(VersionPolicy.siblings("missing", songs=self.songs), [])

    def test_doctor_rows_preserve_counts_and_preference_state(self):
        rows = VersionPolicy.doctor_groups(
            groups=VersionPolicy.groups(self.songs),
            playcounts={"album/original.flac": 9},
            preferences={"live/live.flac": "1"})
        self.assertEqual(rows[0]["artist"], "The Artist")
        self.assertEqual(rows[0]["title"], "Signal")
        self.assertEqual(rows[0]["files"][0]["plays"], 9)
        self.assertTrue(rows[0]["files"][2]["pref"])


class PreferredVersionPublicationTests(unittest.TestCase):
    def test_backend_collapses_from_cached_snapshot_without_sticker_io(self):
        backend = type("Harness", (), {})()
        backend._library = type("Library", (), {"songs": [
            {"file": "album/original.flac", "artist": "The Artist",
             "title": "Signal"},
            {"file": "single/radio.flac", "artist": "The Artist",
             "title": "Signal (Radio Edit)"},
        ]})()
        backend._library_planning_ready = True
        backend._library_playcounts = {"album/original.flac": 20}
        backend._library_preferences = {"single/radio.flac": "1"}
        backend._version_groups = lambda: Backend._version_groups(backend)
        backend._playcounts = lambda: self.fail("read playCount stickers")
        backend._sticker_map = lambda *_args: self.fail("read preference stickers")

        result = Backend._collapse_versions(
            backend, ["album/original.flac", "single/radio.flac"])

        self.assertEqual(["single/radio.flac"], result)

    def test_backend_refuses_version_collapse_before_snapshot_is_ready(self):
        backend = type("Harness", (), {})()
        backend._library_planning_ready = False

        with self.assertRaises(PlanningEvidenceUnavailable):
            Backend._collapse_versions(backend, ["song.flac"])

    def test_backend_publishes_commit_and_failure_outcomes(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, *message):
                self.messages.append(message)

        backend = type("Harness", (), {})()
        backend._library = type("Library", (), {"songs": [
            {"file": "album/original.flac", "artist": "The Artist",
             "title": "Signal"},
            {"file": "single/radio.flac", "artist": "The Artist",
             "title": "Signal (Radio Edit)"},
        ]})()
        backend.doctorChanged = Signal()
        backend.errorOccurred = Signal()
        backend._library_preferences = {"album/original.flac": "1"}
        backend._preferred_version_busy = True
        Backend._on_preferred_version_ready(backend, {
            "file": "single/radio.flac",
            "siblings": ("album/original.flac", "single/radio.flac"),
            "result": ExclusiveStickerResult(True),
        })
        self.assertEqual([()], backend.doctorChanged.messages)
        self.assertEqual([], backend.errorOccurred.messages)
        self.assertEqual({"single/radio.flac": "1"},
                         backend._library_preferences)

        prior = dict(backend._library_preferences)
        Backend._on_preferred_version_ready(backend, {
            "file": "single/radio.flac",
            "siblings": ("album/original.flac", "single/radio.flac"),
            "result": ExclusiveStickerResult(False, False),
        })
        self.assertIn("need repair", backend.errorOccurred.messages[-1][0])
        self.assertEqual(prior, backend._library_preferences)

    def test_backend_admits_only_one_preference_worker(self):
        backend = type("Harness", (), {})()
        backend._library = type("Library", (), {"songs": [
            {"file": "album/original.flac", "artist": "The Artist",
             "title": "Signal"},
            {"file": "single/radio.flac", "artist": "The Artist",
             "title": "Signal (Radio Edit)"},
        ]})()
        backend._preferred_version_busy = False
        launched = []
        backend._start_worker = lambda work, **_kwargs: (
            launched.append(work) or True)

        self.assertTrue(Backend.preferVersion(
            backend, "single/radio.flac"))
        self.assertFalse(Backend.preferVersion(
            backend, "album/original.flac"))
        self.assertEqual(1, len(launched))


if __name__ == "__main__":
    unittest.main()
