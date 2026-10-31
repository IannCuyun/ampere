import json
import random
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ampere.dj.planner import DjPlannerMixin
from ampere.dj import verify as djverify
from ampere.dj.sets import ReplaySelection, SavedSetCatalog
from ampere.mpdclient import Backend
from ampere.queue_mutations import QueueMutationCoordinator


def _cue(conf=1.0):
    return json.dumps({
        "v": 2, "bpm": 120.0, "b0": 0.0, "conf": conf, "dur": 180.0,
        "key": 0, "lv": 1, "bcut": 120.0, "voc": 0.2,
        "in": [[8.0, 0.8, 20.0, 0.1]],
        "out": [[160.0, 0.8, 20.0, 0.1]],
    })


class JourneyHarness(DjPlannerMixin):
    DJ_GATES = Backend.DJ_GATES
    DJ_SEG = Backend.DJ_SEG
    DJ_HOPS = Backend.DJ_HOPS
    DJ_ROUTE_EXCLUDE = Backend.DJ_ROUTE_EXCLUDE

    def __init__(self, files, cues):
        self._search_index = [{"song": {
            "file": f, "duration": "180", "artist": f.split("/")[-2],
            "title": f.split("/")[-1], "album": "Album",
        }} for f in files]
        self._disliked = []
        self._dj_level = "classic"
        self._dj_shape = "flat"
        self._dj_b2b_active = False
        self._stickers = {
            "joi_cues": cues,
            "joi_energy": {f: "0.6" for f in files},
            "joi_bpm": {f: "120" for f in files},
        }

    def _sticker_map(self, name, cli=None):
        return self._stickers.get(name, {})

    def _energies(self, cli=None):
        return {f: float(v) for f, v in
                self._stickers.get("joi_energy", {}).items()}


class ProgressiveSessionTests(unittest.TestCase):
    def setUp(self):
        random.seed(1)
        self.files = [
            f"Metal & Rock/Alt Rock/Artist {i}/Track {i}.flac"
            for i in range(8)
        ] + [
            f"Metal & Rock/Metalcore/Artist {i}/Track {i}.flac"
            for i in range(8, 16)
        ]

    def test_top_level_room_resolves_to_a_real_leaf_room(self):
        h = JourneyHarness(self.files, {f: _cue() for f in self.files})

        ordered = h._dj_build_journey("Metal & Rock")

        self.assertGreaterEqual(len(ordered), 8)
        self.assertTrue(all(f.startswith("Metal & Rock/") for f in ordered))

    def test_top_level_room_starts_plain_when_no_cues_exist(self):
        h = JourneyHarness(self.files, {})

        ordered = h._dj_build_journey("Metal & Rock")

        self.assertGreater(len(ordered), 0)
        self.assertTrue(all(f.startswith("Metal & Rock/") for f in ordered))


class StickerRepository:
    def __init__(self):
        self.reads = []
        self.available = True

    def raw_observed(self, file, name, default=""):
        self.reads.append((file, name))
        return type("Result", (), {
            "available": self.available,
            "value": "0.7" if self.available else default,
        })()


class TransitionIntentHarness(DjPlannerMixin):
    def __init__(self):
        self._stickers = StickerRepository()
        self._dj_evidence_unavailable = False
        self._search_index = [{"song": {
            "file": f, "artist": "Artist", "title": f, "album": "Album",
        }} for f in ("a.flac", "b.flac")]

    def _energies(self):
        raise AssertionError("transition planning must not scan the library")

    @classmethod
    def _key_compat01(cls, _a, _b):
        return 1.0


class TransitionIntentLookupTests(unittest.TestCase):
    def test_reads_only_the_pair_energy_stickers(self):
        h = TransitionIntentHarness()
        cues = json.loads(_cue())

        h._dj_transition_intent("a.flac", cues, "b.flac", cues)

        self.assertEqual(h._stickers.reads, [
            ("a.flac", "joi_energy"),
            ("b.flac", "joi_energy"),
        ])

    def test_unavailable_energy_marks_plan_evidence_inconclusive(self):
        h = TransitionIntentHarness()
        h._stickers.available = False
        cues = json.loads(_cue())

        h._dj_transition_intent("a.flac", cues, "b.flac", cues)

        self.assertTrue(h._dj_evidence_unavailable)


class CueEvidenceHarness(DjPlannerMixin):
    def __init__(self, available):
        self._stickers = StickerRepository()
        self._stickers.available = available
        self._dj_evidence_unavailable = False
        self._dj_cue_cache = {}
        self._dj_on = True
        self._dj_prio = []
        self.scans = 0

    def _start_dj_scan(self, **_kwargs):
        self.scans += 1


class CueEvidenceTests(unittest.TestCase):
    def test_unavailable_cue_is_not_cached_or_sent_to_scanner(self):
        h = CueEvidenceHarness(False)

        self.assertIsNone(h._dj_cues("song.flac"))

        self.assertEqual({}, h._dj_cue_cache)
        self.assertEqual([], h._dj_prio)
        self.assertEqual(0, h.scans)

    def test_verified_missing_cue_keeps_scanner_fallback(self):
        h = CueEvidenceHarness(True)

        self.assertIsNone(h._dj_cues("song.flac"))

        self.assertIn("song.flac", h._dj_cue_cache)
        self.assertEqual(["song.flac"], h._dj_prio)
        self.assertEqual(1, h.scans)


class ImmediateFader:
    def move(self, action, **_kwargs):
        action()


class DjGatewayHarness(DjPlannerMixin):
    def __init__(self):
        self._transition_fader = ImmediateFader()
        self._volume = 100
        self._state = "play"
        self._dj_on = False
        self._dj_swept = False
        self._queue = [
            {"id": 1, "file": "song.flac"},
            {"id": 2, "file": "/cache/bridge.flac"},
            {"id": 3, "file": "next.flac"},
        ]
        self.once = []
        self.writes = []
        self.logs = []
        self.fail_range = False
        self.status = {"state": "play", "songid": "1"}
        self.refresh_requests = 0

    def _call(self, name, *_args, **_kwargs):
        if name == "status":
            return self.status
        raise AssertionError(f"retrying call used for mutation: {name}")

    def _write_once(self, name, *args, **_kwargs):
        self.once.append((name, args))
        return True

    def _write(self, name, *args, **_kwargs):
        self.writes.append((name, args))
        return not self.fail_range

    def _dj_log(self, message):
        self.logs.append(message)

    def _request_queue_refresh(self):
        self.refresh_requests += 1
        return True


class DjGatewayBoundaryTests(unittest.TestCase):
    def test_stale_plan_cache_requests_worker_queue_refresh(self):
        harness = DjGatewayHarness()
        harness._queue_pos = 0
        harness._cur_songid = 99
        harness._dj_resync_ts = 0.0
        harness._dj_plan_key = (1, 2)
        harness._dj_on = True

        harness._dj_plan()

        self.assertEqual(1, harness.refresh_requests)
        self.assertIsNone(harness._dj_plan_key)
        self.assertIn("queue cache behind MPD", harness.logs[-1])

    def test_default_faded_cut_uses_at_most_once_next(self):
        harness = DjGatewayHarness()

        harness._dj_fader_next()

        self.assertEqual([("next", ())], harness.once)

    def test_stale_sweep_uses_gateway_semantics_and_retries_failure(self):
        harness = DjGatewayHarness()
        harness.fail_range = True

        harness._dj_sweep_stale(harness.status)

        self.assertEqual([("deleteid", (2,))], harness.once)
        self.assertEqual([("rangeid", (3, ":"))], harness.writes)
        self.assertFalse(harness._dj_swept)
        self.assertIn("retrying", harness.logs[-1])

    def test_stale_sweep_defers_without_mutation_when_playhead_unavailable(self):
        harness = DjGatewayHarness()

        harness._dj_sweep_stale(None)

        self.assertEqual([], harness.once)
        self.assertEqual([], harness.writes)
        self.assertFalse(harness._dj_swept)
        self.assertIn("deferred", harness.logs[-1])

    def test_stale_sweep_without_evidence_requests_owned_refresh(self):
        harness = DjGatewayHarness()
        harness._call = lambda *_args, **_kwargs: self.fail(
            "sentinel sweep must not read playhead on Qt's thread")

        harness._dj_sweep_stale()

        self.assertEqual(1, harness.refresh_requests)
        self.assertEqual([], harness.once)
        self.assertEqual([], harness.writes)
        self.assertFalse(harness._dj_swept)

    def test_stale_sweep_accepts_worker_playhead_without_gateway_read(self):
        harness = DjGatewayHarness()
        harness._call = lambda *_args, **_kwargs: self.fail(
            "worker publication must not reread playhead on Qt's thread")

        harness._dj_sweep_stale({"state": "play", "songid": "1"})

        self.assertEqual([("deleteid", (2,))], harness.once)
        self.assertEqual([("rangeid", (3, ":"))], harness.writes)
        self.assertTrue(harness._dj_swept)

    def test_reset_defers_all_cleanup_when_playhead_unavailable(self):
        harness = DjGatewayHarness()
        harness.status = None
        harness._dj_gen = 3
        harness._dj_cut_at = 12.0
        harness._dj_plan_key = (1, 2)
        harness._dj_render_key = (2, 3)
        harness._dj_active = True
        harness._dj_next_style = "slam"
        harness._dj_next_reason = "matched"
        harness._dj_bridges = {2: (1, 3, "mix")}
        harness._dj_bridge_done = {(1, 3): "ready"}
        harness._dj_ranged = {3: (4.0, 30.0)}
        harness._apply_automix = lambda: self.fail(
            "transition handback must wait for authoritative playhead")

        harness._dj_reset_generation = 1
        harness._dj_reset_busy = True
        harness._dj_reset_request_pending = False

        self.assertFalse(harness._on_dj_reset_ready({
            "generation": 1, "status": None,
        }))

        self.assertTrue(harness._dj_reset_pending)
        self.assertEqual([], harness.once)
        self.assertEqual([], harness.writes)
        self.assertEqual({2: (1, 3, "mix")}, harness._dj_bridges)
        self.assertEqual({3: (4.0, 30.0)}, harness._dj_ranged)

    def test_reset_preserves_bridge_successor_range_from_valid_playhead(self):
        harness = DjGatewayHarness()
        harness.status = {"state": "play", "songid": "2"}
        harness._dj_gen = 3
        harness._dj_cut_at = 12.0
        harness._dj_plan_key = (1, 2)
        harness._dj_render_key = (2, 3)
        harness._dj_active = True
        harness._dj_next_style = "slam"
        harness._dj_next_reason = "matched"
        harness._dj_bridges = {2: (1, 3, "mix")}
        harness._dj_bridge_done = {(1, 3): "ready"}
        harness._dj_ranged = {3: (4.0, 30.0), 4: (2.0, 20.0)}
        harness._apply_automix = lambda: True

        self.assertTrue(harness._apply_dj_reset(
            djverify.validate_playhead(harness.status)))

        self.assertEqual([("deleteid", (2,))], harness.once)
        self.assertEqual([("rangeid", (4, ":"))], harness.writes)
        self.assertFalse(harness._dj_reset_pending)

    def test_reset_worker_uses_owned_client(self):
        harness = DjGatewayHarness()
        harness._dj_reset_busy = False
        harness._dj_reset_request_pending = False
        harness._dj_reset_generation = 0
        harness._workers = object()
        emitted = []
        harness._djResetReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        harness._start_worker = lambda work, **_kwargs: (work() or True)
        client = type("Client", (), {
            "status": lambda self: {"state": "pause", "songid": "1"},
        })()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        with patch("ampere.dj.planner.temporary_mpd_client",
                   return_value=Scope()):
            self.assertTrue(harness._dj_reset())

        self.assertEqual(
            {"state": "pause", "songid": "1"}, emitted[0]["status"])

    def test_superseded_reset_result_launches_latest_only(self):
        harness = DjGatewayHarness()
        harness._dj_reset_busy = True
        harness._dj_reset_request_pending = False
        harness._dj_reset_generation = 4
        self.assertTrue(harness._dj_reset())
        launched = []
        harness._dj_reset = lambda: launched.append(True) or True
        harness._launch_pending_dj_reset = lambda: \
            DjPlannerMixin._launch_pending_dj_reset(harness)
        harness._apply_dj_reset = lambda *_args: self.fail(
            "superseded playhead must not clean up DJ state")

        harness._on_dj_reset_ready({
            "generation": 4,
            "status": {"state": "pause", "songid": "1"},
        })

        self.assertEqual([True], launched)

    def test_dj_transition_ownership_requires_verified_commit(self):
        harness = DjGatewayHarness()
        harness._dj_active = False
        harness._dj_plan_key = (1, 2)
        captured = []
        harness._configure_transitions = lambda **kwargs: (
            captured.append(kwargs) or False)

        self.assertFalse(harness._dj_configure_transition(True, 3))
        self.assertFalse(harness._dj_active)
        self.assertIsNone(harness._dj_plan_key)

        harness._dj_plan_key = (1, 2)
        harness._configure_transitions = lambda **kwargs: (
            captured.append(kwargs) or True)
        self.assertTrue(harness._dj_configure_transition(True, 3))
        self.assertFalse(harness._dj_active)
        self.assertTrue(captured[-1]["dj_active"])


class DjSessionPlanningLifecycleTests(unittest.TestCase):
    def harness(self):
        backend = type("Harness", (), {})()
        backend._dj_session_busy = False
        backend._dj_session_generation = 0
        backend._dj_range = "room"
        backend._dj_b2b = ""
        backend._dj_sting = False
        backend._dj_minutes = 0
        backend._dj_level = "classic"
        backend._dj_shape = "flat"
        backend._queue_mutations = QueueMutationCoordinator()
        backend._workers = object()
        backend.errors = []
        backend.errorOccurred = type("Signal", (), {
            "emit": lambda self, message: backend.errors.append(message),
        })()
        backend._dj_session_request_key = lambda seed, is_file: \
            Backend._dj_session_request_key(backend, seed, is_file)
        return backend

    def test_duplicate_start_launches_only_one_planner(self):
        backend = self.harness()
        launches = []
        backend._start_worker = lambda work, **kwargs: (
            launches.append((work, kwargs)) or True)

        first = Backend.startDjSession(backend, "Metal & Rock", False)
        duplicate = Backend.startDjSession(backend, "Metal & Rock", False)

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(1, len(launches))
        self.assertIn("already being planned", backend.errors[-1])

    def test_owned_client_plan_is_rejected_after_queue_generation_changes(self):
        backend = self.harness()
        launches, emitted, clients = [], [], []
        backend._start_worker = lambda work, **_kwargs: (
            launches.append(work) or True)
        backend._djSessionReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._dj_pool = lambda _seed, _is_file: (["a.flac", "b.flac"], "Rock")
        backend._dj_build_set = lambda pool, seed, cli: (
            clients.append(cli) or list(pool))
        backend._dj_cue_map = lambda ordered, cli: (
            clients.append(cli) or {file: {} for file in ordered})
        backend._dj_apply_time = lambda ordered, cues, cli: (
            clients.append(cli) or list(ordered))
        backend._dj_find_anthems = lambda ordered, cli: (
            clients.append(cli) or {ordered[0]})
        client = object()

        @contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend.startDjSession(
                backend, "Metal & Rock", False))
            launches[0]()

        self.assertTrue(clients)
        self.assertTrue(all(value is client for value in clients))
        backend._queue_mutations.run("playback", lambda: True)
        backend._replace_queue = lambda *_args: self.fail(
            "stale plan changed the queue")

        self.assertFalse(Backend._on_dj_session_ready(backend, emitted[0]))
        self.assertFalse(backend._dj_session_busy)
        self.assertIn("queue changed", backend.errors[-1])


class DjSetReplayLifecycleTests(unittest.TestCase):
    def harness(self):
        backend = type("Harness", (), {})()
        backend._dj_replay_busy = False
        backend._dj_replay_generation = 0
        backend._queue_mutations = QueueMutationCoordinator()
        backend._library = type("Library", (), {
            "by_file": {"a.flac": {}, "b.flac": {}},
        })()
        backend.errors = []
        backend.errorOccurred = type("Signal", (), {
            "emit": lambda self, message: backend.errors.append(message),
        })()
        return backend

    def test_duplicate_replay_launches_only_one_worker(self):
        backend = self.harness()
        launches = []
        backend._start_worker = lambda work, **kwargs: (
            launches.append((work, kwargs)) or True)

        self.assertTrue(Backend.replayLastSet(backend))
        self.assertFalse(Backend.replayLastSet(backend))
        self.assertEqual(1, len(launches))
        self.assertIn("already being prepared", backend.errors[-1])

    def test_queue_change_rejects_worker_selection_before_commit(self):
        backend = self.harness()
        launches, emitted = [], []
        backend._start_worker = lambda work, **_kwargs: (
            launches.append(work) or True)
        backend._djReplayReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        with patch("ampere.mpdclient.load_saved_sets", return_value=(
                SavedSetCatalog(({"songs": ["a.flac"]},), 0, ""))), \
                patch("ampere.mpdclient.select_replayable_set", return_value=(
                    ReplaySelection({"songs": ["a.flac"]}, ("a.flac",)))):
            self.assertTrue(Backend.replayLastSet(backend))
            launches[0]()
        backend._queue_mutations.run("playback", lambda: True)
        backend._replace_queue = lambda *_args: self.fail(
            "stale saved set changed the queue")

        self.assertFalse(Backend._on_dj_replay_ready(backend, emitted[0]))
        self.assertFalse(backend._dj_replay_busy)
        self.assertIn("queue changed", backend.errors[-1])

    def test_current_selection_commits_and_publishes_session(self):
        backend = self.harness()
        backend._dj_replay_generation = 2
        backend._dj_replay_busy = True
        backend._mix_on = False
        backend._dj_prio = []
        backend._dj_plan_key = "old"
        backend._dj_on = False
        backend._dj_anthems = {"old"}
        backend._dj_redropped = {1}
        backend.replaced = []
        backend._finish_dj_replay_start = lambda data, available, success: (
            Backend._finish_dj_replay_start(
                backend, data, available, success))
        backend._request_queue_intent = lambda kind, request, \
                on_finished=None: (
                    backend.replaced.append((kind, request))
                    or on_finished(True) or True)
        backend._save_conf = lambda: True
        backend._start_dj_scan = lambda: None
        backend.settingsChanged = type("Signal", (), {"emit": lambda self: None})()
        backend.refreshStatus = lambda: None

        result = Backend._on_dj_replay_ready(backend, {
            "generation": 2,
            "queueGeneration": backend._queue_mutations.generation,
            "catalog": SavedSetCatalog(({"songs": ["a.flac"]},), 0, ""),
            "selection": ReplaySelection(
                {"songs": ["a.flac"], "label": "Encore"}, ("a.flac",)),
        })

        self.assertTrue(result)
        self.assertEqual("replace", backend.replaced[0][0])
        self.assertEqual(("a.flac",), backend.replaced[0][1]["files"])
        self.assertTrue(backend._dj_on)
        self.assertEqual("Encore", backend._dj_seed_label)
        self.assertEqual(["a.flac"], backend._dj_prio)


if __name__ == "__main__":
    unittest.main()
