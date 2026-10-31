import random
import unittest

from ampere.mpdclient import Backend
from ampere.smartmix import QueueOrderPlan, SmartMixPlanner


def song(file, artist="Artist"):
    return {"file": file, "artist": artist, "title": file.rsplit("/", 1)[-1]}


class SmartMixPlannerTests(unittest.TestCase):
    def planner(self, seed=17):
        return SmartMixPlanner(rng=random.Random(seed), clock=lambda: 2_000_000_000)

    def test_selection_rejects_empty_seed_and_nonpositive_limit(self):
        songs = [song("Rock/A/one.flac")]
        self.assertEqual(self.planner().select({}, songs), [])
        self.assertEqual(self.planner().select(songs[0], songs, limit=0), [])

    def test_selection_uses_embedded_genre_not_directory_taxonomy(self):
        seed = {**song("Custom/Metal/seed.flac", "Seed"),
                "genres": ["Darkwave"]}
        same_folder_wrong_tag = {
            **song("Custom/Metal/wrong.flac", "Wrong"),
            "genres": ["Country"],
        }
        different_folder_matching_tag = {
            **song("Elsewhere/Pop/match.flac", "Match"),
            "genres": ["Darkwave"],
        }
        picks = self.planner(2).select(
            seed, [seed, same_folder_wrong_tag,
                   different_folder_matching_tag],
            counts={same_folder_wrong_tag["file"]: 4,
                    different_folder_matching_tag["file"]: 4},
            energies={seed["file"]: .5,
                      same_folder_wrong_tag["file"]: .5,
                      different_folder_matching_tag["file"]: .5},
            limit=2)

        self.assertEqual(different_folder_matching_tag["file"],
                         picks[0]["file"])

    def test_selection_excludes_seed_and_dislikes_and_respects_limit(self):
        seed = song("Rock/A/seed.flac", "Seed")
        songs = [seed] + [song(f"Rock/A/{i}.flac", f"Artist {i}") for i in range(6)]
        picks = self.planner().select(
            seed, songs, disliked=["Rock/A/1.flac"], limit=3)
        files = [item["file"] for item in picks]
        self.assertEqual(len(files), 3)
        self.assertNotIn(seed["file"], files)
        self.assertNotIn("Rock/A/1.flac", files)

    def test_selection_favors_compatible_neglected_tracks_and_spaces_artists(self):
        seed = song("Rock/A/seed.flac", "Seed")
        near = song("Rock/A/near.flac", "Near")
        near_two = song("Rock/A/near-two.flac", "Near")
        fresh = song("Rock/A/fresh.flac", "Fresh")
        distant = song("Jazz/B/distant.flac", "Distant")
        songs = [seed, near, near_two, fresh, distant]
        picks = self.planner().select(
            seed, songs,
            counts={near["file"]: 0, near_two["file"]: 0,
                    fresh["file"]: 1, distant["file"]: 100},
            energies={item["file"]: .5 for item in songs}, limit=4)
        near_files = {near["file"], near_two["file"]}
        self.assertIn(picks[0]["file"], near_files)
        artists = [item["artist"] for item in picks[:3]]
        self.assertEqual(len(artists), len(set(artists)))
        self.assertIn(picks[-1]["file"], near_files)
        self.assertNotEqual(picks[0]["file"], picks[-1]["file"])

    def test_selection_makes_fit_primary_over_unrelated_discovery(self):
        seed = {**song("Mixed/seed.flac", "Seed"),
                "genres": ["Darkwave"]}
        strong_fit = {**song("Mixed/familiar.flac", "Familiar"),
                      "genres": ["Darkwave"]}
        unrelated_discovery = {
            **song("Mixed/unplayed.flac", "Unplayed"),
            "genres": ["Country"],
        }
        picks = self.planner(4).select(
            seed, [seed, strong_fit, unrelated_discovery],
            counts={strong_fit["file"]: 100,
                    unrelated_discovery["file"]: 0},
            last_played={strong_fit["file"]: 1_999_999_000},
            energies={item["file"]: .5 for item in
                      [seed, strong_fit, unrelated_discovery]},
            bpms={item["file"]: 100 for item in
                  [seed, strong_fit, unrelated_discovery]},
            limit=2)

        self.assertEqual(strong_fit["file"], picks[0]["file"])

    def test_malformed_metadata_fields_are_tolerated_independently(self):
        seed = song("Rock/A/seed.flac")
        candidate = song("Rock/A/candidate.flac", "Other")
        picks = self.planner().select(
            seed, [seed, candidate], ratings={candidate["file"]: "bad"},
            last_played={candidate["file"]: object()},
            bpms={seed["file"]: "bad", candidate["file"]: None})
        self.assertEqual(picks, [candidate])

    def test_short_window_advances_frontier_without_reordering(self):
        queue = [song(f"Rock/A/{i}.flac") for i in range(3)]
        plan = self.planner().order_window(
            queue, queue_pos=0, frontier=0, window_size=8)
        self.assertFalse(plan.reorderable)
        self.assertEqual(plan.frontier, len(queue))
        self.assertEqual(plan.songs, ())

    def test_smooth_ordering_preserves_window_and_follows_energy(self):
        queue = [song("Rock/A/current.flac", "Current"),
                 song("Rock/A/high.flac", "High"),
                 song("Rock/A/low.flac", "Low"),
                 song("Rock/A/mid.flac", "Mid"),
                 song("Rock/A/outside.flac", "Outside")]
        energies = {queue[0]["file"]: .1, queue[1]["file"]: .9,
                    queue[2]["file"]: .2, queue[3]["file"]: .5}
        plan = self.planner().order_window(
            queue, queue_pos=0, frontier=0, window_size=3,
            energies=energies)
        self.assertTrue(plan.reorderable)
        self.assertEqual(plan.start, 0)
        self.assertEqual(plan.frontier, 3)
        self.assertEqual(plan.songs[0]["file"], queue[2]["file"])
        self.assertEqual({s["file"] for s in plan.songs},
                         {s["file"] for s in queue[1:4]})
        self.assertNotIn(queue[4], plan.songs)

    def test_arc_order_is_seeded_and_avoids_recent_artist_when_possible(self):
        queue = [song("Rock/A/current.flac", "Current")]
        queue += [song("Rock/A/a1.flac", "A"), song("Rock/A/a2.flac", "A"),
                  song("Rock/A/b.flac", "B"), song("Rock/A/c.flac", "C")]
        energies = {item["file"]: .55 for item in queue}
        kwargs = dict(queue_pos=0, frontier=0, window_size=4,
                      energies=energies, arc=True, fresh=True)
        first = self.planner().order_window(queue, **kwargs)
        second = self.planner().order_window(queue, **kwargs)
        self.assertEqual(first, second)
        artists = [item["artist"] for item in first.songs[:3]]
        self.assertEqual(len(artists), len(set(artists)))

    def test_ordering_prefers_an_embedded_genre_neighbor_on_equal_audio_fit(self):
        current = {**song("Custom/current.flac", "Current"),
                   "genres": ["Darkwave"]}
        wrong = {**song("Custom/wrong.flac", "Wrong"),
                 "genres": ["Country"]}
        right = {**song("Elsewhere/right.flac", "Right"),
                 "genres": ["Darkwave"]}
        third = {**song("Elsewhere/third.flac", "Third"),
                 "genres": ["Darkwave"]}
        queue = [current, wrong, right, third]
        energies = {item["file"]: .5 for item in queue}
        bpms = {item["file"]: 100 for item in queue}

        plan = self.planner(3).order_window(
            queue, queue_pos=0, frontier=0, window_size=3,
            energies=energies, bpms=bpms, fresh=False)

        self.assertIn(
            plan.songs[0]["file"],
            {right["file"], third["file"]})
        self.assertGreater(
            next(index for index, item in enumerate(plan.songs)
                 if item["file"] == wrong["file"]),
            0)


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class _ApplyPlanner:
    def __init__(self, plan):
        self.plan = plan

    def order_window(self, *_args, **_kwargs):
        return self.plan


class _ApplyPlayback:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reorder_window(self, song_ids, start):
        self.calls.append((list(song_ids), start))
        return self.result


class SmartMixApplicationTests(unittest.TestCase):
    def harness(self, result):
        harness = type("Harness", (), {})()
        songs = ({"id": 3, "file": "c"}, {"id": 2, "file": "b"},
                 {"id": 4, "file": "d"})
        harness._queue = [{"id": 1, "file": "current"}, *songs]
        harness._queue_pos = 0
        harness._mix_frontier = 0
        harness.MIX_WINDOW = 80
        harness._mix_arc = False
        harness._mix_busy = True
        harness._mix_retry_at = 0.0
        harness._mix_failure_reported = False
        harness._smart_mix = _ApplyPlanner(QueueOrderPlan(0, 3, songs))
        harness.intents = []
        harness.errorOccurred = _Signal()
        harness._finish_mix_maps_failure = lambda message=(
            "Smart mix analysis failed; the queue was not changed"
        ): Backend._finish_mix_maps_failure(harness, message)
        harness._finish_mix_maps_success = lambda: \
            Backend._finish_mix_maps_success(harness)
        harness._finish_mix_reorder = lambda frontier, success: \
            Backend._finish_mix_reorder(harness, frontier, success)
        harness._request_queue_intent = lambda kind, request, \
                on_finished=None: (
                    harness.intents.append((kind, request))
                    or on_finished(result) or True)
        return harness

    def test_verified_reorder_advances_frontier(self):
        harness = self.harness(True)

        Backend._on_mix_maps(
            harness, {"energies": {}, "bpms": {}, "fresh": False})

        self.assertEqual("reorder", harness.intents[0][0])
        self.assertEqual((3, 2, 4), harness.intents[0][1]["songIds"])
        self.assertEqual(3, harness._mix_frontier)
        self.assertFalse(harness._mix_busy)

    def test_unverified_reorder_keeps_frontier_pending(self):
        harness = self.harness(False)

        Backend._on_mix_maps(
            harness, {"energies": {}, "bpms": {}, "fresh": False})

        self.assertEqual("reorder", harness.intents[0][0])
        self.assertEqual(0, harness._mix_frontier)
        self.assertFalse(harness._mix_busy)


if __name__ == "__main__":
    unittest.main()
