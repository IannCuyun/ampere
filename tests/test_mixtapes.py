import random
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from ampere.mpdclient import Backend
from ampere.mixtapes import MixtapePlanner
from ampere.versions import VersionPolicy


def song(file, duration=300, artist="Artist"):
    return {"file": file, "duration": duration, "artist": artist,
            "title": file.rsplit("/", 1)[-1], "album": "Album"}


class MixtapePlannerTests(unittest.TestCase):
    def planner(self):
        return MixtapePlanner(rng=random.Random(17))

    def test_exact_fit_is_viable_and_preserves_the_selected_set(self):
        library = {f"Genre/A/{index}.flac": song(
            f"Genre/A/{index}.flac", artist=f"Artist {index % 4}")
                   for index in range(10)}
        plan = self.planner().plan(
            30, "", library=library,
            energies={file: index / 10 for index, file in enumerate(library)},
            bpms={file: 90 + index * 3 for index, file in enumerate(library)})
        self.assertTrue(plan.viable)
        self.assertEqual(plan.target_seconds, 1800)
        self.assertEqual(plan.total_seconds, 1800)
        self.assertEqual(len(plan.files), 6)
        self.assertEqual(len(set(plan.files)), 6)

    def test_path_dislikes_and_version_preference_are_hard_filters(self):
        library = {
            "Rock/A/original.flac": song("Rock/A/original.flac", 180),
            "Rock/A/radio.flac": song("Rock/A/radio.flac", 180),
            **{f"Rock/A/{i}.flac": song(f"Rock/A/{i}.flac", 180)
               for i in range(6)},
            "Rock/B/outside.flac": song("Rock/B/outside.flac", 180),
        }
        # Give the siblings matching identity; filenames do not define groups.
        library["Rock/A/original.flac"].update(title="Signal", artist="Alpha")
        library["Rock/A/radio.flac"].update(title="Signal (Radio Edit)", artist="Alpha")
        groups = VersionPolicy.groups(list(library.values()))
        plan = self.planner().plan(
            10, "Rock/A", library=library,
            disliked=["Rock/A/0.flac"], liked=["Rock/A/radio.flac"],
            version_groups=groups,
            preferences={"Rock/A/radio.flac": "1"})
        self.assertTrue(plan.viable)
        self.assertIn("Rock/A/radio.flac", plan.files)
        self.assertNotIn("Rock/A/original.flac", plan.files)
        self.assertNotIn("Rock/A/0.flac", plan.files)
        self.assertNotIn("Rock/B/outside.flac", plan.files)

    def test_duration_search_fails_honestly_when_no_set_meets_tolerance(self):
        library = {f"Genre/{i}.flac": song(f"Genre/{i}.flac", 240)
                   for i in range(8)}
        plan = self.planner().plan(30, "", library=library)
        self.assertFalse(plan.viable)
        self.assertEqual(plan.files, ())

    def test_liked_and_neglected_tracks_win_equal_duration_contention(self):
        library = {f"Genre/{i}.flac": song(f"Genre/{i}.flac", 200)
                   for i in range(12)}
        liked = "Genre/11.flac"
        plan = self.planner().plan(
            10, "", library=library, liked=[liked],
            counts={file: (0 if file == "Genre/10.flac" else 50)
                    for file in library})
        self.assertTrue(plan.viable)
        self.assertIn(liked, plan.files)
        self.assertIn("Genre/10.flac", plan.files)

    def test_too_few_eligible_tracks_reports_nonviable_pool(self):
        library = {f"Genre/{i}.flac": song(f"Genre/{i}.flac", 180)
                   for i in range(4)}
        plan = self.planner().plan(10, "", library=library)
        self.assertFalse(plan.viable)
        self.assertEqual(plan.eligible_count, 4)


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class PlannerStub:
    def __init__(self):
        self.kwargs = None

    def plan(self, _minutes, _path, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(viable=True, files=("Genre/song.flac",))


class MixtapeBackendTests(unittest.TestCase):
    def backend(self):
        backend = type("MixtapeAdapter", (), {})()
        backend._library = SimpleNamespace(
            by_file={"Genre/song.flac": song("Genre/song.flac")})
        backend._disliked = []
        backend._liked = []
        backend._mixtapes = PlannerStub()
        backend._mixtape_worker = lambda *_args: None
        backend._start_mixtape_plan = (
            lambda minutes, path, *, mood:
            Backend._start_mixtape_plan(
                backend, minutes, path, mood=mood))
        backend._version_groups = lambda: {"versions": ["Genre/song.flac"]}
        backend._request_generated_playlist_save = \
            lambda _purpose, _name, _files, **_context: True
        backend.playFiles = lambda _files, _index: True
        backend._mixtape_busy = False
        backend._workers = object()
        backend.mixtapeBusyChanged = type("Signal", (), {
            "__init__": lambda self: setattr(self, "count", 0),
            "emit": lambda self: setattr(self, "count", self.count + 1),
        })()
        backend.mixtapeFinished = type("Signal", (), {
            "__init__": lambda self: setattr(self, "events", []),
            "emit": lambda self, *args: self.events.append(args),
        })()
        backend.errorOccurred = Signal()
        return backend

    def test_start_is_non_blocking_busy_and_rejects_duplicate(self):
        backend = self.backend()
        launches = []
        backend._start_worker = lambda target, *, args, name: (
            launches.append((target, args, name)) or True)

        started = Backend.startMixtape(backend, 30, "")
        duplicate = Backend.startMixtape(backend, 45, "")

        self.assertTrue(started)
        self.assertFalse(duplicate)
        self.assertTrue(backend._mixtape_busy)
        self.assertEqual("ampere-mixtape", launches[0][2])
        self.assertEqual(1, backend.mixtapeBusyChanged.count)

    def test_ampy_start_carries_mood_and_duration_to_one_worker(self):
        backend = self.backend()
        launches = []
        backend._start_worker = lambda target, *, args, name: (
            launches.append((target, args, name)) or True)

        self.assertFalse(Backend.startAmpySession(backend, 45, "unknown"))
        self.assertTrue(Backend.startAmpySession(backend, 60, "dark"))

        self.assertEqual(1, len(launches))
        self.assertEqual((60, ""), launches[0][1][:2])
        self.assertEqual("dark", launches[0][1][3])
        self.assertEqual("ampere-mixtape", launches[0][2])
        self.assertTrue(backend._mixtape_busy)

    def test_worker_uses_one_scoped_client_for_verified_families(self):
        backend = self.backend()
        backend._planning_counts = lambda cli: {"Genre/song.flac": 4}
        backend._planning_energies = lambda cli: {"Genre/song.flac": .7}
        families = {
            "joi_bpm": {"Genre/song.flac": "124"},
            "joi_pref": {"Genre/song.flac": "1"},
        }
        client = object()
        seen = []
        backend._planning_sticker_map = lambda name, cli: (
            seen.append(cli) or families[name])
        backend._mixtapeReady = type("Signal", (), {
            "__init__": lambda self: setattr(self, "events", []),
            "emit": lambda self, value: self.events.append(value),
        })()
        snapshot = {
            "library": backend._library.by_file,
            "disliked": (), "liked": (),
            "version_groups": backend._version_groups(),
        }

        @contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            Backend._mixtape_worker(backend, 30, "", snapshot)

        self.assertEqual({"Genre/song.flac": 4},
                         backend._mixtapes.kwargs["counts"])
        self.assertEqual({"Genre/song.flac": .7},
                         backend._mixtapes.kwargs["energies"])
        self.assertIs(families["joi_bpm"],
                      backend._mixtapes.kwargs["bpms"])
        self.assertIs(families["joi_pref"],
                      backend._mixtapes.kwargs["preferences"])
        self.assertTrue(all(item is client for item in seen))
        self.assertEqual(("Genre/song.flac",),
                         backend._mixtapeReady.events[0]["files"])

    def test_ampy_worker_limits_duration_planner_to_mood_candidates(self):
        backend = self.backend()
        library = {
            f"Metal & Rock/A/{index}.flac": song(
                f"Metal & Rock/A/{index}.flac", artist=f"Artist {index}")
            for index in range(8)
        }
        backend._library.by_file = library
        backend._planning_counts = lambda _cli: {}
        backend._planning_energies = lambda _cli: {}
        backend._planning_sticker_map = lambda _name, _cli: {}
        chosen = tuple(list(library)[:6])
        backend._sessions = SimpleNamespace(
            mood_picks=lambda *_args, **_kwargs: list(chosen))
        backend._mixtapeReady = type("Signal", (), {
            "__init__": lambda self: setattr(self, "events", []),
            "emit": lambda self, value: self.events.append(value),
        })()
        snapshot = {
            "library": library,
            "disliked": (), "liked": (), "queued": (),
            "version_groups": {},
        }

        @contextmanager
        def scoped_client(*_args, **_kwargs):
            yield object()

        playlist_result = SimpleNamespace(success=True, files=())
        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client), \
                patch("ampere.mpdclient.PlaylistService.client_files_result",
                      return_value=playlist_result):
            Backend._mixtape_worker(backend, 45, "", snapshot, "dark")

        self.assertEqual(set(chosen),
                         set(backend._mixtapes.kwargs["library"]))
        self.assertEqual("dark", backend._mixtapeReady.events[0]["mood"])

    def test_ready_hands_commit_to_generated_playlist_worker(self):
        backend = self.backend()
        backend._mixtape_busy = True
        actions = []
        backend._request_generated_playlist_save = \
            lambda purpose, name, files, **context: (
                actions.append((purpose, name, tuple(files), context)) or True)
        backend.playFiles = lambda files, index: (
            actions.append(("play", tuple(files), index)) or True)

        Backend._on_mixtape_ready(backend, {
            "minutes": 30, "path": "", "files": ("Genre/song.flac",),
        })

        self.assertEqual(["mixtape"], [action[0] for action in actions])
        self.assertEqual([], backend.mixtapeFinished.events)
        self.assertFalse(backend._mixtape_busy)

    def test_ampy_ready_uses_mood_specific_generated_playlist_name(self):
        backend = self.backend()
        backend._mixtape_busy = True
        actions = []
        backend._request_generated_playlist_save = \
            lambda purpose, name, files, **context: (
                actions.append((purpose, name, tuple(files))) or True)

        Backend._on_mixtape_ready(backend, {
            "minutes": 45, "path": "", "mood": "dark",
            "files": ("Genre/song.flac",),
        })

        self.assertEqual(
            [("mixtape", "Ampy · Dark · 45m", ("Genre/song.flac",))],
            actions)

    def test_failed_evidence_or_save_never_starts_playback(self):
        backend = self.backend()
        backend._mixtape_busy = True
        backend.playFiles = lambda *_args: self.fail("queue changed")

        Backend._on_mixtape_ready(backend, None)
        backend._mixtape_busy = True
        backend._request_generated_playlist_save = lambda *_args, **_kwargs: False
        Backend._on_mixtape_ready(backend, {
            "minutes": 30, "path": "", "files": ("Genre/song.flac",),
        })

        self.assertEqual([("", 0, False), ("", 0, False)],
                         backend.mixtapeFinished.events)

    def test_generated_commit_starts_mixtape_only_after_success_publication(self):
        backend = self.backend()
        backend._generated_playlist_busy = True
        backend._request_collection_refresh = lambda: True
        plays = []
        backend.playFiles = lambda files, index: (
            plays.append((tuple(files), index)) or True)

        Backend._on_generated_playlist_ready(backend, {
            "purpose": "mixtape", "name": "Mixtape · library · 30m",
            "files": ("Genre/song.flac",), "context": {},
            "success": True,
        })

        self.assertEqual([(("Genre/song.flac",), 0)], plays)
        self.assertEqual(
            [("Mixtape · library · 30m", 1, True)],
            backend.mixtapeFinished.events)
        self.assertFalse(backend._generated_playlist_busy)


if __name__ == "__main__":
    unittest.main()
