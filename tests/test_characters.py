import unittest

from ampere import characters


class CharacterVocabularyTests(unittest.TestCase):
    """Only the audited characters exist, and each one selects on the axis
    that survived (design/DECISIONS.md, 2026-08-22)."""

    def test_the_vocabulary_is_exactly_the_audited_ten(self):
        self.assertEqual(characters.KEYS, (
            "still", "mellow", "quiet-dark", "dark", "heavy-low",
            "subsonic", "driving", "punishing", "wall", "crushed"))

    def test_the_cut_axes_define_nothing(self):
        # Brightness works only as DARK, dynamic range only as CRUSHED, and
        # neither onset density nor tempo defines a character at all.
        source = (characters.__file__)
        text = open(source, encoding="utf-8").read()
        body = text.split("CHARACTERS = (", 1)[1]
        self.assertNotIn("busy", body)
        self.assertNotIn("bpm", body)
        for entry in characters.CHARACTERS:
            if entry["key"] not in ("dark", "quiet-dark"):
                self.assertNotIn("bright", entry["blurb"])

    def test_a_track_with_no_measurements_is_never_guessed_at(self):
        songs = [{"file": "a.flac", "artist": "A"}]
        picks = characters.select(
            songs, {}, character="mellow", durations={"a.flac": 300})
        self.assertEqual([], picks)

    def test_short_tracks_are_excluded_because_skits_contaminated_them(self):
        songs = [{"file": "skit.flac", "artist": "A"},
                 {"file": "song.flac", "artist": "B"}]
        feats = {"skit.flac": {"energy": .2, "dyn": 20.0},
                 "song.flac": {"energy": .2, "dyn": 20.0}}
        picks = characters.select(
            songs, feats, character="still",
            durations={"skit.flac": 41, "song.flac": 300})
        self.assertEqual(["song.flac"], picks)

    def test_dislikes_and_queued_never_enter_a_character(self):
        songs = [{"file": f"{n}.flac", "artist": n} for n in "abc"]
        feats = {f"{n}.flac": {"energy": .2} for n in "abc"}
        durations = {f"{n}.flac": 300 for n in "abc"}
        picks = characters.select(
            songs, feats, character="mellow", durations=durations,
            disliked={"a.flac"}, queued={"b.flac"})
        self.assertEqual(["c.flac"], picks)

    def test_best_fit_leads_and_artists_are_spread(self):
        songs = [{"file": "deep.flac", "artist": "X"},
                 {"file": "deeper.flac", "artist": "X"},
                 {"file": "other.flac", "artist": "Y"}]
        feats = {"deep.flac": {"bass": .93}, "deeper.flac": {"bass": .99},
                 "other.flac": {"bass": .95}}
        durations = {f: 300 for f in feats}
        picks = characters.select(
            songs, feats, character="subsonic", durations=durations)
        self.assertEqual(3, len(picks))
        self.assertNotEqual("X", songs[[s["file"] for s in songs].index(
            picks[1])]["artist"] if picks[0] == "deeper.flac" else "Y")

    def test_each_character_answers_its_own_boundary(self):
        cases = [("punishing", {"energy": .90}, {"energy": .80}),
                 ("driving", {"energy": .75}, {"energy": .90}),
                 ("subsonic", {"bass": .95}, {"bass": .80}),
                 ("heavy-low", {"bass": .80}, {"bass": .60}),
                 ("dark", {"bright": .20}, {"bright": .40}),
                 ("crushed", {"dyn": 4.0}, {"dyn": 9.0}),
                 ("wall", {"energy": .85, "dyn": 6.0},
                          {"energy": .85, "dyn": 12.0}),
                 ("still", {"energy": .30, "dyn": 15.0},
                           {"energy": .30, "dyn": 6.0})]
        for key, inside, outside in cases:
            self.assertTrue(characters.matches(key, inside), key)
            self.assertFalse(characters.matches(key, outside), key)

    def test_an_unknown_character_selects_nothing(self):
        self.assertEqual([], characters.select(
            [{"file": "a.flac"}], {"a.flac": {"energy": .1}},
            character="audiophile", durations={"a.flac": 300}))
        self.assertEqual("", characters.label("airy"))


class BackendCharacterWiringTests(unittest.TestCase):
    """The backend exposes the vocabulary and obeys the shared policies."""

    def test_the_surface_can_read_the_vocabulary(self):
        from ampere.mpdclient import Backend
        rows = Backend.soundCharacters.fget(object())
        self.assertEqual(10, len(rows))
        self.assertEqual({"key", "label", "blurb"}, set(rows[0]))
        self.assertEqual("still", rows[0]["key"])

    def test_features_never_default_a_missing_measurement(self):
        from ampere.mpdclient import Backend

        class Harness:
            def _planning_sticker_map(self, name, cli=None):
                return {"a.flac": "0.9"} if name == "joi_bass" else {}

        features = Backend._character_features(Harness())
        self.assertEqual({"a.flac": {"bass": 0.9}}, features)

    def test_an_unknown_character_reaches_nothing(self):
        from ampere.mpdclient import Backend
        self.assertEqual([], Backend._character_picks(object(), "audiophile"))


class MixHistoryTests(unittest.TestCase):
    """A built mix is kept so it can be replayed or ported to a playlist."""

    def harness(self):
        from ampere.mpdclient import Backend

        class Settings:
            def __init__(self): self.patches = []
            def try_patch(self, patch):
                self.patches.append(patch)
                return type("R", (), {"success": True, "messages": ()})()

        class Harness:
            _sound_mixes = []
            played = None
            added = None
            errors = ()

            def __init__(self):
                self._settings = Settings()
                self._sound_mixes = []
                self.errors = []
                self.soundMixesChanged = type(
                    "S", (), {"emit": lambda _s: None})()
                self.errorOccurred = type(
                    "S", (), {"emit": lambda _s, m: self.errors.append(m)})()

            def playFiles(self, files, start):
                self.played = (list(files), start)

            def addToPlaylist(self, name, files):
                self.added = (name, list(files))

        return Backend, Harness()

    def test_building_plays_now_and_keeps_the_mix(self):
        Backend, h = self.harness()
        h._character_picks = lambda key, count=25: ["a.flac", "b.flac"]
        mix_id = Backend.buildCharacterMix(h, "subsonic", 25)
        self.assertTrue(mix_id)
        self.assertEqual((["a.flac", "b.flac"], 0), h.played)
        self.assertEqual("subsonic", h._sound_mixes[0]["character"])
        self.assertEqual("SUBSONIC", h._sound_mixes[0]["label"])

    def test_an_empty_character_says_so_and_keeps_nothing(self):
        Backend, h = self.harness()
        h._character_picks = lambda key, count=25: []
        self.assertEqual("", Backend.buildCharacterMix(h, "subsonic", 25))
        self.assertEqual([], h._sound_mixes)
        self.assertIsNone(h.played)
        self.assertTrue(h.errors)

    def test_a_kept_mix_replays_and_ports_to_a_playlist(self):
        Backend, h = self.harness()
        h._character_picks = lambda key, count=25: ["a.flac"]
        mix_id = Backend.buildCharacterMix(h, "dark", 25)
        h.played = None
        self.assertTrue(Backend.playSoundMix(h, mix_id))
        self.assertEqual((["a.flac"], 0), h.played)
        self.assertTrue(Backend.saveSoundMixAs(h, mix_id, " Night Drive "))
        self.assertEqual(("Night Drive", ["a.flac"]), h.added)
        self.assertFalse(Backend.saveSoundMixAs(h, mix_id, "   "))

    def test_forgetting_a_mix_is_durable_and_idempotent(self):
        Backend, h = self.harness()
        h._character_picks = lambda key, count=25: ["a.flac"]
        mix_id = Backend.buildCharacterMix(h, "dark", 25)
        self.assertTrue(Backend.forgetSoundMix(h, mix_id))
        self.assertEqual([], h._sound_mixes)
        self.assertFalse(Backend.forgetSoundMix(h, mix_id))
        self.assertEqual({"sound_mixes": []}, h._settings.patches[-1])
