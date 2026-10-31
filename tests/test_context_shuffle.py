import random
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject

from ampere.mpdclient import Backend
from ampere.queue_sequencing import QueueSequencer
from ampere.smartmix import QueueOrderPlan, SmartMixPlanner


class _Signal:
    def __init__(self): self.payloads = []
    def emit(self, payload): self.payloads.append(payload)


class ContextShuffleTests(unittest.TestCase):
    def setUp(self):
        self.playlist_rows = []
        self.client_patch = patch(
            "ampere.mpdclient.temporary_mpd_client", side_effect=self.client_scope)
        self.client_patch.start()

    def tearDown(self):
        self.client_patch.stop()

    def client_scope(self, *_args, **_kwargs):
        rows = list(self.playlist_rows)
        class Client:
            def listplaylistinfo(self, _name): return rows
            def sticker_find(self, *_args): return []
        @contextmanager
        def scope(): yield Client()
        return scope()

    def backend(self):
        backend = Backend.__new__(Backend)
        QObject.__init__(backend)
        backend._dj_on = False
        backend._context_shuffle_generation = 0
        backend._context_shuffle_mode = "off"
        backend._context_shuffle_cancel_event = None
        backend._defined_queue_active = True
        backend._defined_queue_kind = "defined"
        backend._defined_queue_files = (
            "Rock/B/one.flac", "Rock/C/two.flac", "Jazz/D/three.flac")
        backend._queue = [{"id": 1, "file": "Rock/A/current.flac", "artist": "A"}]
        backend._queue_pos = 0
        backend._state = "play"
        backend._song = dict(backend._queue[0])
        backend._library = type("Library", (), {"songs": [
            backend._queue[0], {"file": "Rock/B/one.flac", "artist": "B"},
            {"file": "Rock/C/two.flac", "artist": "C"},
            {"file": "Jazz/D/three.flac", "artist": "D"}]})()
        backend._search_index = [{"song": song} for song in backend._library.songs]
        backend._library_playcounts = {}; backend._library_planning_ratings = {}
        backend._library_last_played = {}; backend._library_energies = {}; backend._library_bpms = {}
        backend._library_preferences = {}; backend._library_planning_ready = True
        backend._disliked = ["Rock/C/two.flac"]; backend._liked = []
        backend._queue_sequencer = QueueSequencer(shuffle=lambda values: values.reverse())
        backend._smart_mix = SmartMixPlanner(rng=random.Random(1))
        backend._stickers = type("Stickers", (), {"values_result": lambda *_: type("R", (), {"values": {}, "available": True, "retained": False})()})()
        # The shuffle mode is a persisted preference (Iann, 2026-08-22), so a
        # mode change writes through the settings repository.
        backend._settings = type("Settings", (), {
            "try_patch": lambda _self, values: type(
                "R", (), {"success": True})()})()
        backend._settings_save_failed = False
        backend._settings_save_failure_message = ""
        backend._contextShuffleReady = _Signal(); backend.started = []
        backend._workers = object()
        backend._start_worker = lambda work, **_kwargs: backend.started.append(work) or True
        backend.restore_intents = []
        backend._request_queue_intent = lambda kind, request, **_kwargs: (
            backend.restore_intents.append((kind, dict(request))) or True)
        return backend

    def test_cycle_updates_mode_immediately_and_advances_three_states(self):
        backend = self.backend()
        modes = []
        backend.contextShuffleModeChanged.connect(
            lambda: modes.append(backend.contextShuffleMode))
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertEqual("standard", backend.contextShuffleMode)
        self.assertEqual(["standard"], modes)
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertEqual("smart", backend.contextShuffleMode)
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertEqual("off", backend.contextShuffleMode)
        self.assertEqual(["standard", "smart", "off"], modes)

    def test_manual_queue_cycles_standard_back_to_off_without_smart_plan(self):
        backend = self.backend()
        backend._defined_queue_active = False
        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "queue"}))
        self.assertEqual("standard", backend.contextShuffleMode)
        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "queue"}))
        self.assertEqual("off", backend.contextShuffleMode)
        self.assertEqual(1, len(backend.started))

    def test_album_cycles_standard_back_to_off_without_smart(self):
        backend = self.backend()
        backend._defined_queue_kind = "album"
        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "queue"}))
        self.assertEqual("standard", backend.contextShuffleMode)
        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "queue"}))
        self.assertEqual("off", backend.contextShuffleMode)
        self.assertEqual(1, len(backend.started))

    def test_smart_request_is_rejected_for_album_queue(self):
        backend = self.backend()
        backend._defined_queue_kind = "album"
        self.assertFalse(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        self.assertEqual([], backend.started)

    def test_successful_multisong_replacement_records_authored_membership(self):
        backend = self.backend()
        backend._defined_queue_active = False
        backend._defined_queue_files = ()
        Backend._record_queue_context(backend, "replace", {
            "files": ("album/01.flac", "album/02.flac"),
            "queueContext": "album",
        })
        self.assertTrue(backend._defined_queue_active)
        self.assertEqual("album", backend._defined_queue_kind)
        self.assertEqual(
            ("album/01.flac", "album/02.flac"),
            backend._defined_queue_files)

    def test_successful_manual_edit_ends_smart_and_protects_queue(self):
        backend = self.backend()
        backend._context_shuffle_mode = "smart"
        Backend._record_queue_context(backend, "insert-next", {
            "file": "chosen.flac", "manualQueueEdit": True,
        })
        self.assertFalse(backend._defined_queue_active)
        self.assertEqual((), backend._defined_queue_files)
        self.assertEqual("off", backend.contextShuffleMode)

    def test_cycle_off_cancels_pending_plan_and_restores_authored_order(self):
        backend = self.backend()
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertEqual(1, len(backend.started))
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        backend._queue_after_current = lambda *_args, **_kwargs: self.fail("cancelled plan published")
        backend.started[0]()
        self.assertEqual("off", backend.contextShuffleMode)
        self.assertEqual("replace-upcoming", backend.restore_intents[-1][0])
        self.assertEqual(
            backend._defined_queue_files,
            backend.restore_intents[-1][1]["files"])

    def test_source_order_reset_follows_current_anchor_and_drops_heard_shuffle_rows(self):
        authored = tuple(f"album/{index}.flac" for index in range(1, 7))
        queue = [
            {"file": "album/5.flac"},
            {"file": "album/2.flac"},
            {"file": "smart/recommendation.flac"},
        ]
        self.assertEqual(
            ("album/3.flac", "album/4.flac", "album/6.flac"),
            Backend._remaining_authored_in_source_order(
                authored, queue, 2))

    def test_source_order_reset_counts_duplicate_authored_occurrences(self):
        authored = ("a.flac", "repeat.flac", "b.flac", "repeat.flac",
                    "c.flac")
        queue = [{"file": "repeat.flac"}, {"file": "b.flac"},
                 {"file": "repeat.flac"}]
        self.assertEqual(
            ("c.flac",),
            Backend._remaining_authored_in_source_order(
                authored, queue, 2))

    def test_plan_and_publication_failures_return_cycle_to_off(self):
        backend = self.backend()
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "collection", "files": ["missing.flac"]}))
        backend.started[0]()
        self.assertFalse(Backend._on_context_shuffle_ready(
            backend, backend._contextShuffleReady.payloads[-1]))
        self.assertEqual("off", backend.contextShuffleMode)
        backend = self.backend()
        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "collection", "files": ["Rock/B/one.flac"]}))
        backend.started[0]()
        backend._queue_after_current = lambda _files, on_finished=None, **_kwargs: (on_finished(False), True)[1]
        self.assertTrue(Backend._on_context_shuffle_ready(
            backend, backend._contextShuffleReady.payloads[-1]))
        self.assertEqual("off", backend.contextShuffleMode)

    def test_new_mode_and_off_cancel_an_admitted_publication_token(self):
        backend = self.backend()
        backend._queue.append({
            "id": 2, "file": "Rock/B/one.flac", "artist": "B"})
        published = []
        backend._queue_after_current = (
            lambda _files, on_finished=None, cancel_event=None:
            published.append(cancel_event) or True)

        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "collection", "files": ["Rock/B/one.flac"]}))
        backend.started[0]()
        self.assertTrue(Backend._on_context_shuffle_ready(
            backend, backend._contextShuffleReady.payloads[-1]))
        standard_token = published[-1]
        self.assertFalse(standard_token.is_set())

        self.assertTrue(Backend.cycleContextShuffle(
            backend, {"kind": "collection", "files": ["Rock/B/one.flac"]}))
        self.assertTrue(standard_token.is_set())
        backend.started[1]()
        self.assertTrue(Backend._on_context_shuffle_ready(
            backend, backend._contextShuffleReady.payloads[-1]))
        smart_token = published[-1]
        self.assertFalse(smart_token.is_set())

        self.assertTrue(Backend.cycleContextShuffle(backend, {"kind": "queue"}))
        self.assertEqual("off", backend.contextShuffleMode)
        self.assertTrue(smart_token.is_set())

    def test_cancelled_publication_never_opens_an_mpd_client(self):
        backend = self.backend()
        token = threading.Event()
        token.set()
        with patch("ampere.mpdclient.temporary_mpd_client") as client:
            result = Backend._execute_queue_intent(backend, "replace", {
                "files": ("Rock/B/one.flac",), "cancelEvent": token})
        client.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("cancelled", result["messages"][-1].lower())

    def test_standard_context_is_worker_owned_and_excludes_current_disliked(self):
        backend = self.backend()
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {"kind": "collection", "files": ["Rock/A/current.flac", "Rock/B/one.flac", "Rock/C/two.flac"]}))
        self.assertEqual(1, len(backend.started))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertFalse(payload["error"])
        self.assertEqual(("Rock/B/one.flac",), payload["files"])

    def test_standard_queue_never_resurrects_the_heard_prefix(self):
        backend = self.backend()
        heard = {"id": 1, "file": "Rock/A/heard.flac", "artist": "A"}
        current = {"id": 2, "file": "Rock/B/current.flac", "artist": "B"}
        upcoming = [
            {"id": 3, "file": "Rock/C/next.flac", "artist": "C"},
            {"id": 4, "file": "Rock/D/later.flac", "artist": "D"},
        ]
        backend._queue = [heard, current, *upcoming]
        backend._queue_pos = 1
        backend._song = dict(current)
        backend._library.songs = [heard, current, *upcoming]
        backend._search_index = [
            {"song": song} for song in backend._library.songs]
        backend._disliked = []

        self.assertTrue(Backend.requestContextShuffle(
            backend, "standard", {
                "kind": "queue",
                "files": [song["file"] for song in backend._queue],
            }))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]

        self.assertFalse(payload["error"])
        self.assertEqual(
            {"Rock/C/next.flac", "Rock/D/later.flac"},
            set(payload["files"]))
        self.assertNotIn("Rock/A/heard.flac", payload["files"])
        self.assertNotIn("Rock/B/current.flac", payload["files"])

    def test_empty_explicit_collection_never_falls_through_to_library(self):
        backend = self.backend()

        self.assertTrue(Backend.requestContextShuffle(
            backend, "standard", {"kind": "collection", "files": []}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]

        self.assertTrue(payload["error"])
        self.assertEqual((), payload["files"])

    def test_failed_plan_does_not_publish_queue_mutation(self):
        backend = self.backend()
        backend._queue_after_current = lambda files: self.fail("must not mutate")
        errors = []; backend.errorOccurred.connect(errors.append)
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {"kind": "collection", "files": ["Rock/A/current.flac"]}))
        backend.started[0]()
        self.assertFalse(Backend._on_context_shuffle_ready(backend, backend._contextShuffleReady.payloads[-1]))
        self.assertTrue(errors)

    def test_smart_preserves_authored_order_and_sprinkles_recommendations(self):
        backend = self.backend()
        backend._queue.extend([
            {"id": 2, "file": "Rock/B/one.flac", "artist": "B"},
            {"id": 3, "file": "Jazz/D/three.flac", "artist": "D"},
            {"id": 4, "file": "Rock/E/four.flac", "artist": "E"},
        ])
        backend._defined_queue_files = tuple(
            song["file"] for song in backend._queue[1:])
        backend._library.songs.extend([
            backend._queue[-1],
            {"file": "Rock/F/similar.flac", "artist": "F"},
        ])
        backend._search_index = [
            {"song": song} for song in backend._library.songs]
        self.assertTrue(Backend.requestContextShuffle(backend, "smart", {"kind": "queue"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertFalse(payload["error"])
        authored = ["Rock/B/one.flac", "Jazz/D/three.flac", "Rock/E/four.flac"]
        self.assertEqual(
            authored,
            [file for file in payload["files"] if file in authored])
        self.assertLessEqual(len(payload["files"]) - len(authored), 1)

    def test_smart_request_fails_closed_for_manual_queue_without_error(self):
        backend = self.backend()
        backend._defined_queue_active = False
        errors = []
        backend.errorOccurred.connect(errors.append)
        self.assertFalse(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        self.assertEqual([], backend.started)
        self.assertEqual([], errors)

    def test_smart_does_not_read_standard_only_gapless_evidence(self):
        backend = self.backend()
        authored = {"id": 2, "file": "Rock/B/one.flac", "artist": "B"}
        backend._queue.append(authored)
        backend._defined_queue_files = (authored["file"],)
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_: self.fail(
                "Smart must not read gapless evidence")})()
        self.assertTrue(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        backend.started[0]()
        self.assertFalse(backend._contextShuffleReady.payloads[-1]["error"])

    def test_sprinkle_density_preserves_every_authored_position(self):
        authored = [f"album/{index}.flac" for index in range(1, 8)]
        picks = [f"smart/{index}.flac" for index in range(1, 5)]
        result = Backend._sprinkle_smart_recommendations(authored, picks)
        self.assertEqual(authored, [file for file in result if file in authored])
        self.assertEqual([picks[0], picks[1], picks[2]], [
            file for file in result if file in picks])

    def test_sprinkle_does_not_outweigh_a_one_song_remainder(self):
        self.assertEqual(
            ["authored.flac"],
            Backend._sprinkle_smart_recommendations(
                ["authored.flac"], ["smart.flac"]))

    def test_smart_does_not_inject_gapless_successors_after_selection(self):
        backend = self.backend()
        authored = {"id": 2, "file": "Context/01-authored.flac",
                    "artist": "Context"}
        authored_two = {"id": 3, "file": "Context/02-authored.flac",
                        "artist": "Other Context"}
        selected = {"file": "Album/01-selected.flac", "artist": "B"}
        successor = {"file": "Album/02-successor.flac", "artist": "B"}
        backend._queue.extend([authored, authored_two])
        backend._defined_queue_files = (
            authored["file"], authored_two["file"])
        backend._library.songs = [
            backend._queue[0], authored, authored_two, selected, successor]
        backend._search_index = [
            {"song": song} for song in backend._library.songs]
        backend._disliked = []
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_: type("R", (), {
                "values": {selected["file"]: "-10"},
                "available": True, "retained": False})()})()

        class Planner:
            @staticmethod
            def select(*_args, **_kwargs):
                return [selected]

            @staticmethod
            def order_window(*_args, **_kwargs):
                return QueueOrderPlan(0, 1)

        backend._smart_mix = Planner()

        self.assertTrue(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]

        self.assertFalse(payload["error"])
        self.assertEqual(
            (authored["file"], authored_two["file"], selected["file"]),
            payload["files"])
        self.assertNotIn(successor["file"], payload["files"])

    def test_smart_excludes_heard_versions_and_collapses_remaining_versions(self):
        backend = self.backend()
        heard = {"id": 1, "file": "Custom/A/song-live.flac", "artist": "A",
                 "title": "Song (Live)", "genres": ["Darkwave"]}
        current = {"id": 2, "file": "Custom/Seed/current.flac",
                   "artist": "Seed", "title": "Current",
                   "genres": ["Darkwave"]}
        heard_alternate = {"file": "Elsewhere/A/song.flac", "artist": "A",
                           "title": "Song", "genres": ["Darkwave"]}
        keep = {"file": "Elsewhere/B/keep.flac", "artist": "B",
                "title": "Keep", "genres": ["Darkwave"]}
        keep_live = {"file": "Elsewhere/B/keep-live.flac", "artist": "B",
                     "title": "Keep (Live)", "genres": ["Darkwave"]}
        other = {"file": "Elsewhere/C/other.flac", "artist": "C",
                 "title": "Other", "genres": ["Darkwave"]}
        authored_two = {"file": "Elsewhere/D/authored.flac", "artist": "D",
                        "title": "Authored", "genres": ["Darkwave"]}
        backend._queue = [heard, current, other, authored_two]
        backend._defined_queue_files = (other["file"], authored_two["file"])
        backend._queue_pos = 1
        backend._song = dict(current)
        backend._library.songs = [
            heard, current, heard_alternate, keep, keep_live, other,
            authored_two]
        backend._search_index = [
            {"song": song} for song in backend._library.songs]
        backend._disliked = []
        backend._library_preferences = {keep_live["file"]: True}

        self.assertTrue(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]

        self.assertFalse(payload["error"])
        self.assertNotIn(heard["file"], payload["files"])
        self.assertNotIn(heard_alternate["file"], payload["files"])
        self.assertNotIn(keep["file"], payload["files"])
        self.assertIn(keep_live["file"], payload["files"])
        self.assertLess(
            payload["files"].index(other["file"]),
            payload["files"].index(keep_live["file"]))

    def test_reapplying_smart_drops_prior_recommendations_from_authored_lane(self):
        backend = self.backend()
        prior = {"id": 2, "file": "Smart/prior.flac", "artist": "Prior"}
        authored = {"id": 3, "file": "Rock/B/one.flac", "artist": "B"}
        backend._queue.extend([prior, authored])
        backend._defined_queue_files = (authored["file"],)
        backend._library.songs.append(prior)
        backend._search_index = [
            {"song": song} for song in backend._library.songs]

        self.assertTrue(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]

        self.assertFalse(payload["error"])
        self.assertNotIn(prior["file"], payload["files"])
        self.assertIn(authored["file"], payload["files"])

    def test_name_only_playlist_context_reads_exact_membership_on_worker(self):
        backend = self.backend()
        self.playlist_rows = [{"file": "Rock/B/one.flac"}]
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {
            "kind": "playlist", "name": "Exact set"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertFalse(payload["error"])
        self.assertEqual(("Rock/B/one.flac",), payload["files"])

    def test_path_context_does_not_include_a_prefix_sibling(self):
        backend = self.backend()
        backend._library.songs.extend([
            {"file": "Rock/Artist A/ok.flac", "artist": "A"},
            {"file": "Rock/Artist AB/wrong.flac", "artist": "AB"}])
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {
            "kind": "artist", "path": "Rock/Artist A"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertIn("Rock/Artist A/ok.flac", payload["files"])
        self.assertNotIn("Rock/Artist AB/wrong.flac", payload["files"])

    def test_standard_filters_missing_input_and_gapless_successors_outside_context(self):
        backend = self.backend()
        backend._search_index = [
            {"song": {"file": "Rock/B/one.flac"}},
            {"song": {"file": "Rock/B/disliked-successor.flac"}},
            {"song": {"file": "Rock/B/current-successor.flac"}}]
        backend._stickers = type("Stickers", (), {"values_result": lambda *_: type("R", (), {
            "values": {"Rock/B/one.flac": "-10"}, "available": True, "retained": False})()})()
        backend._disliked.append("Rock/B/disliked-successor.flac")
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {
            "kind": "collection", "files": ["Rock/B/one.flac", "missing/nope.flac"]}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertFalse(payload["error"])
        self.assertEqual(("Rock/B/one.flac",), payload["files"])

    def test_queue_fallback_excludes_non_library_entries(self):
        backend = self.backend()
        backend._queue.append({
            "id": 2, "file": "missing/not-in-library.flac", "artist": ""})
        self.assertTrue(Backend.requestContextShuffle(
            backend, "standard", {"kind": "queue"}))
        backend.started[0]()
        payload = backend._contextShuffleReady.payloads[-1]
        self.assertTrue(payload["error"])
        self.assertEqual((), payload["files"])

    def test_unavailable_gapless_evidence_fails_closed(self):
        backend = self.backend()
        backend._stickers = type("Stickers", (), {"values_result": lambda *_: type("R", (), {
            "values": {}, "available": False, "retained": False})()})()
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {
            "kind": "collection", "files": ["Rock/B/one.flac"]}))
        backend.started[0]()
        self.assertTrue(backend._contextShuffleReady.payloads[-1]["error"])

    def test_publication_rejects_queue_or_playhead_race(self):
        backend = self.backend()
        calls, errors = [], []
        backend._queue_after_current = lambda files: calls.append(files) or True
        backend.errorOccurred.connect(errors.append)
        self.assertTrue(Backend.requestContextShuffle(backend, "standard", {
            "kind": "collection", "files": ["Rock/B/one.flac"]}))
        backend.started[0]()
        backend._queue.append({"id": 9, "file": "Rock/Z/race.flac"})
        self.assertFalse(Backend._on_context_shuffle_ready(
            backend, backend._contextShuffleReady.payloads[-1]))
        self.assertEqual([], calls)
        self.assertTrue(errors)


class ContextShuffleQmlContractTests(unittest.TestCase):
    def test_artist_context_uses_the_visible_credit_scoped_discography(self):
        main = (Path(__file__).resolve().parents[1] / "qml" / "Main.qml").read_text()

        self.assertIn("id: artistPage", main)
        artist_context = main.split(
            'if (mode === "artist")', 1)[1].split(
                'if (mode === "browse"', 1)[0]
        self.assertIn("files: artistPage.artistFiles", artist_context)

    def test_queue_context_is_backend_resolved_not_a_full_qml_snapshot(self):
        main = (Path(__file__).resolve().parents[1] / "qml" / "Main.qml").read_text()
        fallback = main.split(
            'return { kind: "queue"', 1)[1].split("}", 1)[0]

        self.assertNotIn("files:", fallback)


class SmartRefillTests(ContextShuffleTests):
    def refill_backend(self):
        backend = self.backend()
        backend._state = "play"; backend._autoplay_on = False
        backend._repeat = False; backend._dj_on = False
        backend._song_state = None
        backend.intents = []
        backend._request_queue_intent = lambda kind, request, on_finished=None: (
            backend.intents.append((kind, request)) or True)
        backend._drop_disliked = lambda files, keep="": [
            f for f in files if f not in backend._disliked]
        backend.errors = []
        backend.errorOccurred = type("S", (), {
            "emit": lambda _s, m: backend.errors.append(m)})()
        return backend

    def test_smart_plan_remembers_its_seed(self):
        backend = self.backend()
        self.assertTrue(Backend.requestContextShuffle(backend, "smart", {"kind": "queue"}))
        self.assertEqual(backend._context_shuffle_seed["file"], "Rock/A/current.flac")

    def test_smart_never_refills_past_the_authored_queue(self):
        backend = self.refill_backend()
        backend._context_shuffle_mode = "smart"
        backend._context_shuffle_seed = {
            "file": "Rock/A/current.flac", "artist": "A"}
        self.assertFalse(Backend._maybe_smart_refill(backend))
        self.assertEqual([], backend.started)
        self.assertEqual([], backend.intents)

    def test_refill_waits_while_queue_has_enough_upcoming(self):
        backend = self.refill_backend()
        backend._context_shuffle_mode = "smart"
        backend._queue = [backend._queue[0]] + [
            {"id": i, "file": f"Rock/B/{i}.flac"} for i in range(2, 6)]
        self.assertFalse(Backend._maybe_smart_refill(backend))
        self.assertEqual(backend.started, [])

    def test_refill_stays_off_even_with_autoplay_enabled(self):
        backend = self.refill_backend()
        backend._context_shuffle_mode = "smart"; backend._autoplay_on = True
        self.assertFalse(Backend._maybe_smart_refill(backend))
        self.assertEqual([], backend.started)

    def test_append_planning_is_rejected_at_admission(self):
        backend = self.refill_backend()
        backend._context_shuffle_mode = "smart"
        self.assertFalse(Backend.requestContextShuffle(
            backend, "smart", {"kind": "queue"}, append=True))
        self.assertEqual([], backend.started)


class ShufflePersistenceTests(unittest.TestCase):
    """The shuffle mode is a standing preference (Iann, 2026-08-22).

    It survives a restart and every new selection, and a single failed plan
    does not erase it.
    """

    def test_the_mode_is_a_validated_setting(self):
        from ampere.settings import DEFAULTS, _validated
        self.assertEqual("off", DEFAULTS["context_shuffle_mode"])
        self.assertEqual(
            "smart", _validated({"context_shuffle_mode": "smart"})[
                "context_shuffle_mode"])
        self.assertEqual(
            "off", _validated({"context_shuffle_mode": "sideways"})[
                "context_shuffle_mode"])

    def test_a_mode_change_is_written_through(self):
        backend = ContextShuffleTests().backend()
        written = []
        backend._settings = type("S", (), {
            "try_patch": lambda _s, values: written.append(values) or type(
                "R", (), {"success": True})()})()
        Backend._set_context_shuffle_mode(backend, "smart")
        self.assertEqual([{"context_shuffle_mode": "smart"}], written)

    def test_a_new_selection_inherits_the_standing_mode(self):
        backend = ContextShuffleTests().backend()
        backend._context_shuffle_mode = "smart"
        asked = []
        backend.requestContextShuffle = lambda mode, context, **kw: asked.append(
            (mode, context, kw)) or True
        Backend._reapply_context_shuffle(backend, True)
        self.assertEqual(1, len(asked))
        self.assertEqual("smart", asked[0][0])
        self.assertTrue(asked[0][2]["automatic"])

    def test_a_failed_selection_changes_nothing(self):
        backend = ContextShuffleTests().backend()
        backend._context_shuffle_mode = "smart"
        asked = []
        backend.requestContextShuffle = lambda *a, **k: asked.append(a) or True
        Backend._reapply_context_shuffle(backend, False)
        self.assertEqual([], asked)

    def test_shuffle_off_stays_off_for_a_new_selection(self):
        backend = ContextShuffleTests().backend()
        backend._context_shuffle_mode = "off"
        asked = []
        backend.requestContextShuffle = lambda *a, **k: asked.append(a) or True
        Backend._reapply_context_shuffle(backend, True)
        self.assertEqual([], asked)

    def test_an_automatic_plan_failure_never_erases_the_preference(self):
        # an explicit cycle still returns to OFF (SPEC row 197); the automatic
        # re-application must not, or one stale snapshot wipes a saved choice
        backend = ContextShuffleTests().backend()
        backend._context_shuffle_mode = "smart"
        backend.errorOccurred = type("S", (), {"emit": lambda *_a: None})()
        Backend._on_context_shuffle_ready(backend, {
            "generation": backend._context_shuffle_generation,
            "freshness": backend._context_shuffle_freshness(),
            "automatic": True, "error": "nothing eligible", "files": ()})
        self.assertEqual("smart", backend._context_shuffle_mode)

    def test_an_explicit_plan_failure_still_returns_to_off(self):
        backend = ContextShuffleTests().backend()
        backend._context_shuffle_mode = "smart"
        backend.errorOccurred = type("S", (), {"emit": lambda *_a: None})()
        Backend._on_context_shuffle_ready(backend, {
            "generation": backend._context_shuffle_generation,
            "freshness": backend._context_shuffle_freshness(),
            "automatic": False, "error": "nothing eligible", "files": ()})
        self.assertEqual("off", backend._context_shuffle_mode)


class SessionCoordinationTests(unittest.TestCase):
    """Test that smart shuffle and radio are mutually exclusive sessions."""

    def test_smart_shuffle_and_radio_are_mutually_exclusive(self):
        from ampere.sessions import SessionService
        sessions = SessionService(radio_enabled=True)
        # Start with radio on
        self.assertEqual(sessions.state.kind, "radio")
        self.assertFalse(sessions.state.smart_shuffle_active)
        # Enable smart shuffle, radio turns off
        changed = sessions.set_smart_shuffle({"file": "test.flac"})
        self.assertTrue(changed)
        self.assertEqual(sessions.state.kind, "smart-shuffle")
        self.assertFalse(sessions.state.radio_enabled)
        # Turn off smart shuffle, doesn't restore radio
        changed = sessions.end_smart_shuffle()
        self.assertTrue(changed)
        self.assertEqual(sessions.state.kind, "manual")

    def test_mood_session_turns_off_smart_shuffle(self):
        from ampere.sessions import SessionService
        sessions = SessionService()
        # Start with smart shuffle on
        sessions.set_smart_shuffle({"file": "test.flac"})
        self.assertEqual(sessions.state.kind, "smart-shuffle")
        # Enable mood session, smart shuffle turns off
        changed = sessions.commit_curated(mood="Dark")
        self.assertTrue(changed)
        self.assertEqual(sessions.state.kind, "mood")
        self.assertFalse(sessions.state.smart_shuffle_active)
