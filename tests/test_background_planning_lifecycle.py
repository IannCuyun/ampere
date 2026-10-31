import unittest
from contextlib import contextmanager
from unittest.mock import patch

from mpd.base import ConnectionError as MPDConnectionError

from ampere.mpdclient import Backend, PlanningEvidenceUnavailable
from ampere.queue_sequencing import QueueSequencer
from ampere.stickers import StickerFamilyResult


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, *message):
        self.messages.append(message)


class BackgroundPlanningLifecycleTests(unittest.TestCase):
    def test_gapless_planning_requires_verified_or_retained_tail_snapshot(self):
        backend = type("Harness", (), {})()
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_args, **_kwargs: StickerFamilyResult(
                False, {}, False),
        })()

        with self.assertRaises(PlanningEvidenceUnavailable):
            Backend._gapless_extend(backend, ["album/01.flac"])

    def test_planning_family_requires_verified_or_retained_snapshot(self):
        backend = type("Harness", (), {})()
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_args, **_kwargs: StickerFamilyResult(
                False, {}, False),
        })()

        with self.assertRaises(PlanningEvidenceUnavailable):
            Backend._planning_sticker_map(backend, "rating")

        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_args, **_kwargs: StickerFamilyResult(
                False, {"a.flac": "8"}, True),
        })()
        self.assertEqual(
            {"a.flac": "8"},
            Backend._planning_sticker_map(backend, "rating"))

    def test_shuffle_aborts_before_random_mode_when_gapless_truth_is_missing(self):
        backend = type("Harness", (), {})()
        backend.errorOccurred = Signal()
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_args, **_kwargs: StickerFamilyResult(
                False, {}, False),
        })()
        backend._queue_sequencer = QueueSequencer(shuffle=lambda _items: None)
        backend._search_index = []
        backend._collapse_versions = lambda files: files
        backend._drop_disliked = lambda files: files
        backend._gapless_extend = lambda files: Backend._gapless_extend(
            backend, files)
        backend._shuffle_order = lambda files: Backend._shuffle_order(
            backend, files)
        backend._set_random_mode = lambda _enabled: self.fail(
            "random mode must not change after inconclusive planning")
        backend.playFiles = lambda *_args: self.fail(
            "queue must not change after inconclusive planning")

        Backend._shuffle_now(backend, ["album/01.flac"])

        self.assertIn("queue was not changed",
                      backend.errorOccurred.messages[0][0])

    def test_rejected_smart_mix_launch_releases_busy(self):
        backend = type("Harness", (), {})()
        backend._mix_busy = False
        backend._mix_retry_at = 0.0
        backend._mix_failure_reported = False
        backend.errorOccurred = Signal()
        backend._start_worker = lambda *_args, **_kwargs: False
        backend._finish_mix_maps_failure = lambda message=(
            "Smart mix analysis failed; the queue was not changed"
        ): Backend._finish_mix_maps_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=50.0):
            Backend._mix_extend(backend)

        self.assertFalse(backend._mix_busy)
        self.assertEqual(80.0, backend._mix_retry_at)
        self.assertIn("could not start", backend.errorOccurred.messages[0][0])

    def test_smart_mix_scan_failure_preserves_queue_and_deduplicates_warning(self):
        backend = type("Harness", (), {})()
        backend._mix_busy = True
        backend._mix_retry_at = 0.0
        backend._mix_failure_reported = False
        backend._queue = [{"id": 1, "file": "one.flac"}]
        backend._mix_frontier = 0
        backend.errorOccurred = Signal()
        backend._finish_mix_maps_failure = lambda message=(
            "Smart mix analysis failed; the queue was not changed"
        ): Backend._finish_mix_maps_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=100.0):
            Backend._on_mix_maps(backend, {"error": "scan_failed"})
            Backend._on_mix_maps(backend, {"error": "scan_failed"})

        self.assertFalse(backend._mix_busy)
        self.assertEqual(0, backend._mix_frontier)
        self.assertEqual([{"id": 1, "file": "one.flac"}], backend._queue)
        self.assertEqual(130.0, backend._mix_retry_at)
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_smart_mix_success_rearms_failure_reporting(self):
        backend = type("Harness", (), {})()
        backend._mix_busy = True
        backend._mix_retry_at = 99.0
        backend._mix_failure_reported = True
        backend._queue = []
        backend._queue_pos = -1
        backend._mix_frontier = -1
        backend.MIX_WINDOW = 80
        backend._mix_arc = False
        backend._smart_mix = type("Planner", (), {
            "order_window": lambda *_args, **_kwargs: type("Plan", (), {
                "reorderable": False, "frontier": 0})()
        })()
        backend.errorOccurred = Signal()
        backend._finish_mix_maps_success = lambda: \
            Backend._finish_mix_maps_success(backend)

        Backend._on_mix_maps(
            backend, {"energies": {}, "bpms": {}, "fresh": False})

        self.assertFalse(backend._mix_busy)
        self.assertEqual(0.0, backend._mix_retry_at)
        self.assertFalse(backend._mix_failure_reported)

    def test_rejected_smart_mix_reorder_preserves_frontier_and_backs_off(self):
        backend = type("Harness", (), {})()
        backend._mix_busy = True
        backend._mix_retry_at = 0.0
        backend._mix_failure_reported = False
        backend._mix_frontier = 2
        backend._queue = [{"id": 1}, {"id": 2}]
        backend._queue_pos = 0
        backend.MIX_WINDOW = 80
        backend._mix_arc = False
        backend.errorOccurred = Signal()
        backend._smart_mix = type("Planner", (), {
            "order_window": lambda *_args, **_kwargs: type("Plan", (), {
                "reorderable": True,
                "frontier": 9,
                "songs": ({"id": 2},),
                "start": 0,
            })(),
        })()
        backend._finish_mix_maps_failure = lambda message=(
            "Smart mix analysis failed; the queue was not changed"
        ): Backend._finish_mix_maps_failure(backend, message)
        backend._finish_mix_maps_success = lambda: \
            Backend._finish_mix_maps_success(backend)
        backend._finish_mix_reorder = lambda frontier, success: \
            Backend._finish_mix_reorder(backend, frontier, success)
        backend._request_queue_intent = lambda _kind, _request, \
                on_finished=None: (on_finished(False) or True)

        with patch("ampere.mpdclient.time.monotonic", return_value=500.0):
            Backend._on_mix_maps(backend, {
                "energies": {}, "bpms": {}, "fresh": False,
            })

        self.assertEqual(2, backend._mix_frontier)
        self.assertFalse(backend._mix_busy)
        self.assertEqual(530.0, backend._mix_retry_at)
        self.assertTrue(backend._mix_failure_reported)
        self.assertIn("could not be confirmed",
                      backend.errorOccurred.messages[0][0])

    def test_malformed_smart_mix_plan_enters_failure_lifecycle(self):
        backend = type("Harness", (), {})()
        backend._mix_busy = True
        backend._mix_retry_at = 0.0
        backend._mix_failure_reported = False
        backend._mix_frontier = 4
        backend._queue = []
        backend._queue_pos = -1
        backend.MIX_WINDOW = 80
        backend._mix_arc = False
        backend.errorOccurred = Signal()
        backend._smart_mix = type("Planner", (), {
            "order_window": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("malformed plan")),
        })()
        backend._finish_mix_maps_failure = lambda message=(
            "Smart mix analysis failed; the queue was not changed"
        ): Backend._finish_mix_maps_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=600.0):
            Backend._on_mix_maps(backend, {
                "energies": {}, "bpms": {}, "fresh": False,
            })

        self.assertEqual(4, backend._mix_frontier)
        self.assertFalse(backend._mix_busy)
        self.assertEqual(630.0, backend._mix_retry_at)

    def test_radio_failure_backs_off_and_keeps_warning_to_one_per_episode(self):
        backend = type("Harness", (), {})()
        backend._radio_busy = True
        backend._radio_retry_at = 0.0
        backend._radio_failure_reported = False
        backend.errorOccurred = Signal()
        backend._finish_radio_failure = lambda message=(
            "Autoplay failed; Ampere will retry shortly"
        ): Backend._finish_radio_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=200.0):
            Backend._on_radio_ready(backend, {"error": "scan_failed"})
            Backend._on_radio_ready(backend, {"error": "scan_failed"})

        self.assertFalse(backend._radio_busy)
        self.assertEqual(230.0, backend._radio_retry_at)
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_rejected_radio_launch_releases_busy(self):
        backend = type("Harness", (), {})()
        backend._autoplay_on = True
        backend._radio_busy = False
        backend._radio_retry_at = 0.0
        backend._radio_failure_reported = False
        backend._repeat = False
        backend._state = "play"
        backend._queue_pos = 0
        backend._queue = [{"file": "current.flac"}]
        backend.errorOccurred = Signal()
        backend._start_worker = lambda *_args, **_kwargs: False
        backend._finish_radio_failure = lambda message=(
            "Autoplay failed; Ampere will retry shortly"
        ): Backend._finish_radio_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=75.0):
            Backend._maybe_radio_refill(backend)

        self.assertFalse(backend._radio_busy)
        self.assertEqual(105.0, backend._radio_retry_at)
        self.assertIn("could not start", backend.errorOccurred.messages[0][0])

    def test_autoplay_success_rearms_failure_reporting_and_appends(self):
        backend = type("Harness", (), {})()
        backend._radio_busy = True
        backend._radio_retry_at = 99.0
        backend._radio_failure_reported = True
        appended = []
        backend._finish_radio_append = lambda success: \
            Backend._finish_radio_append(backend, success)
        backend._request_queue_intent = lambda _kind, request, \
                on_finished=None: (
                    appended.extend(request["files"])
                    or on_finished(True) or True)

        Backend._on_radio_ready(backend, {"files": ["next.flac"]})

        self.assertEqual(["next.flac"], appended)
        self.assertFalse(backend._radio_busy)
        self.assertEqual(0.0, backend._radio_retry_at)
        self.assertFalse(backend._radio_failure_reported)

    def test_disabling_autoplay_rejects_an_inflight_publication(self):
        backend = type("Harness", (), {})()
        backend._autoplay_generation = 2
        backend._radio_busy = True
        backend._request_queue_intent = lambda *_args, **_kwargs: self.fail(
            "a stale Autoplay plan must never append")

        result = Backend._on_radio_ready(backend, {
            "files": ["next.flac"],
            "generation": 1,
            "owner": "autoplay",
        })

        self.assertFalse(result)
        self.assertFalse(backend._radio_busy)

    def test_replacing_the_selected_queue_rejects_old_autoplay_picks(self):
        backend = type("Harness", (), {})()
        backend._autoplay_generation = 3
        backend._autoplay_on = True
        backend._context_shuffle_mode = "off"
        backend._radio_busy = True
        backend._repeat = False
        backend._dj_on = False
        backend._state = "play"
        backend._queue_pos = 0
        backend._song = {"id": "new", "file": "new.flac"}
        backend._queue = [dict(backend._song)]
        backend._request_queue_intent = lambda *_args, **_kwargs: self.fail(
            "picks planned for the replaced queue must never append")

        result = Backend._on_radio_ready(backend, {
            "files": ["old-pick.flac"],
            "generation": 3,
            "owner": "autoplay",
            "freshness": (0, "old", "old.flac", (("old", "old.flac"),)),
        })

        self.assertFalse(result)
        self.assertFalse(backend._radio_busy)

    def test_autoplay_append_failure_enters_backoff_without_false_success(self):
        backend = type("Harness", (), {})()
        backend._radio_busy = True
        backend._radio_retry_at = 0.0
        backend._radio_failure_reported = False
        backend.errorOccurred = Signal()
        backend._finish_radio_failure = lambda message=(
            "Autoplay failed; Ampere will retry shortly"
        ): Backend._finish_radio_failure(backend, message)
        backend._finish_radio_append = lambda success: \
            Backend._finish_radio_append(backend, success)
        backend._request_queue_intent = lambda _kind, _request, \
                on_finished=None: (on_finished(False) or True)

        with patch("ampere.mpdclient.time.monotonic", return_value=300.0):
            Backend._on_radio_ready(backend, {"files": ["next.flac"]})

        self.assertFalse(backend._radio_busy)
        self.assertEqual(330.0, backend._radio_retry_at)
        self.assertTrue(backend._radio_failure_reported)
        self.assertIn("could not update", backend.errorOccurred.messages[0][0])

    def test_empty_autoplay_result_backs_off_instead_of_heartbeat_looping(self):
        backend = type("Harness", (), {})()
        backend._radio_busy = True
        backend._radio_retry_at = 0.0
        backend._radio_failure_reported = False
        backend.errorOccurred = Signal()
        backend._append_files = lambda *_args, **_kwargs: self.fail(
            "an empty plan must never enter queue publication")
        backend._finish_radio_failure = lambda message=(
            "Autoplay failed; Ampere will retry shortly"
        ): Backend._finish_radio_failure(backend, message)

        with patch("ampere.mpdclient.time.monotonic", return_value=400.0):
            Backend._on_radio_ready(backend, {"files": []})

        self.assertFalse(backend._radio_busy)
        self.assertEqual(430.0, backend._radio_retry_at)
        self.assertIn("no new tracks", backend.errorOccurred.messages[0][0])

    def test_mood_launch_defers_all_planning_to_owned_worker(self):
        backend = type("Harness", (), {})()
        backend._queue = [{"id": 1, "file": "current.flac"}]
        backend._curated_plan_busy = False
        backend._curated_plan_key = None
        backend.errorOccurred = Signal()
        launched = []
        backend._start_worker = lambda work, **_kwargs: (
            launched.append(work) or True)
        backend._start_curated_plan = lambda *args, **kwargs: \
            Backend._start_curated_plan(backend, *args, **kwargs)
        backend._play_curated_session = lambda *_args, **_kwargs: self.fail(
            "queue must not change before worker publication")

        self.assertTrue(Backend.startMoodRadio(backend, "hyped"))

        self.assertEqual([{"id": 1, "file": "current.flac"}], backend._queue)
        self.assertTrue(backend._curated_plan_busy)
        self.assertEqual(("mood", "hyped"), backend._curated_plan_key)
        self.assertEqual(1, len(launched))

    def test_curated_worker_uses_scoped_client_and_publishes_result(self):
        backend = type("Harness", (), {})()
        backend._curated_plan_busy = False
        backend._curated_plan_key = None
        backend._workers = object()
        backend.errorOccurred = Signal()
        backend._curatedPlanReady = Signal()
        scoped = object()
        calls = []
        backend._mood_picks = lambda mood, count, cli: (
            calls.append((mood, count, cli)) or ["planned.flac"])
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        @contextmanager
        def client_scope(*_args, **_kwargs):
            yield scoped

        with patch("ampere.mpdclient.temporary_mpd_client", client_scope):
            self.assertTrue(Backend._start_curated_plan(
                backend, "mood", "hyped"))

        self.assertEqual([("hyped", 25, scoped)], calls)
        self.assertEqual([({
            "kind": "mood", "key": "hyped",
            "files": ["planned.flac"], "name": "",
        },)], backend._curatedPlanReady.messages)

    def test_curated_plan_rejects_duplicate_and_releases_failed_launch(self):
        backend = type("Harness", (), {})()
        backend._curated_plan_busy = True
        backend._curated_plan_key = ("mood", "hyped")
        backend.errorOccurred = Signal()

        self.assertFalse(Backend._start_curated_plan(
            backend, "profile", "warm", profile={"id": "warm"}))
        self.assertEqual(("mood", "hyped"), backend._curated_plan_key)

        backend._curated_plan_busy = False
        backend._curated_plan_key = None
        backend._start_worker = lambda *_args, **_kwargs: False
        self.assertFalse(Backend._start_curated_plan(
            backend, "mood", "hyped"))
        self.assertFalse(backend._curated_plan_busy)
        self.assertIsNone(backend._curated_plan_key)

    def test_curated_plan_failure_preserves_queue_and_reports_outcome(self):
        backend = type("Harness", (), {})()
        backend._curated_plan_busy = True
        backend._curated_plan_key = ("mood", "hyped")
        backend._queue = [{"id": 1, "file": "current.flac"}]
        backend.errorOccurred = Signal()
        backend.moodRadioStartFinished = Signal()
        backend.soundProfileStartFinished = Signal()
        backend._play_curated_session = lambda *_args, **_kwargs: self.fail(
            "failed planning must not mutate the queue")

        Backend._on_curated_plan_ready(backend, {
            "kind": "mood", "key": "hyped", "files": None,
            "error": "planning_failed",
        })

        self.assertFalse(backend._curated_plan_busy)
        self.assertIsNone(backend._curated_plan_key)
        self.assertEqual([{"id": 1, "file": "current.flac"}], backend._queue)
        self.assertIn("queue was not changed",
                      backend.errorOccurred.messages[0][0])
        self.assertEqual([("hyped", 0, False)],
                         backend.moodRadioStartFinished.messages)

    def test_curated_plan_success_commits_on_result_handler_only(self):
        # Mood is the only curated kind since Saved Sound Profiles retired
        # (6157232); the profile branches emitted signals that no longer
        # existed (repaired 2026-08-23).
        backend = type("Harness", (), {})()
        backend._curated_plan_busy = True
        backend._curated_plan_key = ("mood", "dark")
        backend.errorOccurred = Signal()
        backend.moodRadioStartFinished = Signal()
        committed = []

        def play(files, **kwargs):
            committed.append((list(files), kwargs.get("mood")))
            kwargs["on_finished"](True)
            return True

        backend._play_curated_session = play

        Backend._on_curated_plan_ready(backend, {
            "kind": "mood", "key": "dark",
            "files": ["one.flac", "two.flac"],
        })

        self.assertEqual([(["one.flac", "two.flac"], "dark")], committed)
        self.assertEqual([("dark", 2, True)],
                         backend.moodRadioStartFinished.messages)
        self.assertFalse(backend._curated_plan_busy)

    def test_stale_curated_result_cannot_release_or_commit_active_plan(self):
        backend = type("Harness", (), {})()
        backend._curated_plan_busy = True
        backend._curated_plan_key = ("profile", "new")
        backend._play_curated_session = lambda *_args, **_kwargs: self.fail(
            "stale result must not commit")

        Backend._on_curated_plan_ready(backend, {
            "kind": "profile", "key": "old", "files": ["old.flac"],
        })

        self.assertTrue(backend._curated_plan_busy)
        self.assertEqual(("profile", "new"), backend._curated_plan_key)

    def test_mood_planner_aborts_before_scoring_on_exemplar_outage(self):
        class Client:
            def listplaylistinfo(self, _name):
                raise MPDConnectionError("lost")

        backend = type("Harness", (), {"_cmd": Client()})()
        backend._playcounts = lambda *_args: self.fail(
            "scoring must not continue from incomplete exemplar evidence")

        with self.assertRaises(RuntimeError):
            Backend._mood_picks(backend, "hyped")

    def test_smart_picker_aborts_before_selection_on_taste_outage(self):
        backend = type("Harness", (), {})()
        backend._library_planning_ready = False
        backend._cached_listening_evidence = lambda: \
            Backend._cached_listening_evidence(backend)
        backend._smart_mix = type("Planner", (), {
            "select": lambda *_args, **_kwargs: self.fail(
                "selection must not run from incomplete taste evidence"),
        })()

        with self.assertRaises(PlanningEvidenceUnavailable):
            Backend._smart_picks(backend, {"file": "seed.flac"})

    def test_smart_picker_uses_one_cached_generation_without_sticker_io(self):
        backend = type("Harness", (), {})()
        backend._library_planning_ready = True
        backend._library_playcounts = {"candidate.flac": 3}
        backend._library_planning_ratings = {"candidate.flac": "8"}
        backend._library_last_played = {"candidate.flac": "123"}
        backend._library_energies = {"candidate.flac": .7}
        backend._library_bpms = {"candidate.flac": 124.0}
        backend._cached_listening_evidence = lambda: \
            Backend._cached_listening_evidence(backend)
        backend._planning_counts = lambda *_args: self.fail("scanned counts")
        backend._planning_sticker_map = lambda *_args: self.fail(
            "scanned stickers")
        backend._planning_energies = lambda *_args: self.fail(
            "scanned energy")
        captured = {}
        backend._smart_mix = type("Planner", (), {
            "select": lambda self, seed, songs, **kwargs: (
                captured.update(kwargs) or [seed]),
        })()
        backend._library = type("Library", (), {
            "songs": ({"file": "candidate.flac"},),
        })()
        backend._disliked = []
        backend._liked = []

        result = Backend._smart_picks(
            backend, {"file": "Rock/seed.flac"})

        self.assertEqual([{"file": "Rock/seed.flac"}], result)
        self.assertEqual({"candidate.flac": 3}, captured["counts"])
        self.assertEqual({"candidate.flac": "8"}, captured["ratings"])
        self.assertEqual({"candidate.flac": "123"},
                         captured["last_played"])
        self.assertEqual({"candidate.flac": .7}, captured["energies"])
        self.assertEqual({"candidate.flac": 124.0}, captured["bpms"])


if __name__ == "__main__":
    unittest.main()
