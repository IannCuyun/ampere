import random
import time
import unittest

from ampere.intelligence import (
    TrackFeatures, beam_sequence, discovery_score, key_compatibility,
    transition_intent,
)


class TransitionIntentTests(unittest.TestCase):
    def track(self, title, energy, bpm=120, cue=.85, vocal=.15):
        return TrackFeatures(title, title=title, artist=title, bpm=bpm,
                             energy=energy, cue_quality=cue, vocal=vocal)

    def test_emotional_song_is_given_room(self):
        a = self.track("A Dying God Coming Into Human Flesh", .32, 82,
                       vocal=.72)
        b = self.track("Aftermath", .42, 105)
        intent = transition_intent(a, b, .7)
        self.assertEqual(intent.style, "soft")
        self.assertIn("emotionally", intent.reason)

    def test_slam_serves_an_energy_lift(self):
        a = self.track("Warmup", .55, 112)
        b = self.track("Peak", .86, 146)
        intent = transition_intent(a, b, .4)
        self.assertEqual(intent.style, "slam")
        self.assertIn("raising", intent.reason)

    def test_energy_drop_does_not_slam(self):
        a = self.track("Peak", .9, 145)
        b = self.track("Landing", .48, 112)
        self.assertNotEqual(transition_intent(a, b, .7).style, "slam")


class DiscoveryTests(unittest.TestCase):
    def test_neglected_compatible_track_beats_overplayed_one(self):
        now = time.time()
        rare = TrackFeatures("rare", plays=0, last_played=0)
        common = TrackFeatures("common", plays=80, last_played=now - 86400)
        rare_score, rare_reasons = discovery_score(
            rare, now=now, compatibility=.75, rng=random.Random(4))
        common_score, _ = discovery_score(
            common, now=now, compatibility=.9, rng=random.Random(4))
        self.assertGreater(rare_score, common_score)
        self.assertIn("unplayed", rare_reasons)


class SetPlanningTests(unittest.TestCase):
    def test_key_compatibility_prefers_harmonic_neighbors(self):
        self.assertEqual(key_compatibility(4, 4), 1.0)
        self.assertGreater(key_compatibility(4, 9),
                           key_compatibility(4, 5))
        self.assertEqual(key_compatibility(-1, 4), 0.5)

    def test_beam_spreads_artists_and_follows_arc(self):
        tracks = [
            TrackFeatures("a1", artist="A", energy=.2, bpm=100, cue_quality=.7),
            TrackFeatures("a2", artist="A", energy=.4, bpm=105, cue_quality=.7),
            TrackFeatures("b1", artist="B", energy=.55, bpm=110, cue_quality=.7),
            TrackFeatures("c1", artist="C", energy=.82, bpm=120, cue_quality=.8),
            TrackFeatures("d1", artist="D", energy=.45, bpm=112, cue_quality=.7),
        ]
        arc = lambda x: .25 + .6 * x if x < .75 else .5
        result = beam_sequence(tracks, count=5, shape=arc,
                               rng=random.Random(8))
        self.assertEqual({t.file for t in result}, {t.file for t in tracks})
        adjacent = list(zip(result, result[1:]))
        self.assertFalse(any(a.artist == b.artist for a, b in adjacent))
        peak = max(range(len(result)), key=lambda i: result[i].energy)
        self.assertGreaterEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
