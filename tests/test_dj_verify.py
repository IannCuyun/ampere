import unittest
import threading
from unittest.mock import patch

from ampere.dj.planner import DjPlannerMixin
from ampere.queue_mutations import QueueMutationCoordinator
from ampere.dj.verify import (
    SLAM_HARD_MIN, slam_verdict_ok, validate_bridge_frontier,
    validate_cut_snapshot, validate_playhead,
)


class SlamVerdictTests(unittest.TestCase):
    def test_accepts_an_explicit_clean_verdict(self):
        self.assertTrue(slam_verdict_ok({
            "ok": True,
            "offset_ms": 7.4,
            "hardness": 8.2,
            "clip": False,
            "why": [],
        }))

    def test_rejects_off_beat_even_when_hard(self):
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": 62.0,
            "hardness": 18.0,
            "clip": False,
            "why": [],
        }))

    def test_rejects_soft_or_clipped_audio(self):
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": 0.0,
            "hardness": SLAM_HARD_MIN - 0.1,
            "clip": False,
            "why": [],
        }))
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": 0.0,
            "hardness": 9.0,
            "clip": True,
            "why": ["clipping"],
        }))

    def test_fails_closed_for_missing_or_invalid_analysis(self):
        self.assertFalse(slam_verdict_ok(None))
        self.assertFalse(slam_verdict_ok({"ok": True}))
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": None,
            "hardness": None,
            "clip": None,
            "why": ["verify-error"],
        }))
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": float("nan"),
            "hardness": float("nan"),
            "clip": False,
            "why": [],
        }))

    def test_rejects_internally_inconsistent_success(self):
        self.assertFalse(slam_verdict_ok({
            "ok": True,
            "offset_ms": 0.0,
            "hardness": 9.0,
            "clip": False,
            "why": ["analyzer-warning"],
        }))


class BridgeRejectionTests(unittest.TestCase):
    class BackendStub(DjPlannerMixin):
        def __init__(self):
            self._dj_render_meta = "aggressive slam"
            self._dj_render_key = (10, 11)
            self._dj_bridge_done = {}
            self.logs = []

        def _dj_log(self, message):
            self.logs.append(message)

    def test_verifier_rejection_becomes_a_soft_crossfade(self):
        backend = self.BackendStub()
        backend._on_bridge_ready(10, 11, "/unused.flac", 1.0, 2.0, -1.0)

        self.assertEqual(backend._dj_bridge_done[(10, 11)], "skip")
        self.assertIsNone(backend._dj_render_key)
        self.assertIn("verification rejected — soft crossfade", backend.logs[-1])

    def test_render_failure_remains_distinct(self):
        backend = self.BackendStub()
        backend._on_bridge_ready(10, 11, "/unused.flac", 1.0, 2.0, 0.0)

        self.assertEqual(backend._dj_bridge_done[(10, 11)], "skip")
        self.assertIn("render FAILED", backend.logs[-1])


class BridgeFrontierTests(unittest.TestCase):
    QUEUE = [
        {"id": "10", "pos": "4"},
        {"id": "11", "pos": "5"},
    ]

    def test_requires_adjacent_targets_ahead_of_authoritative_playhead(self):
        result = validate_bridge_frontier(
            self.QUEUE, {"state": "play", "song": "2"}, 10, 11)
        self.assertTrue(result.conclusive)
        self.assertTrue(result.valid)

        late = validate_bridge_frontier(
            self.QUEUE, {"state": "play", "song": "4"}, 10, 11)
        self.assertTrue(late.conclusive)
        self.assertFalse(late.valid)

    def test_unavailable_or_malformed_truth_is_inconclusive(self):
        for queue, status in (
                (None, {"state": "play", "song": "2"}),
                (self.QUEUE, None),
                ([{"id": "bad", "pos": "4"}],
                 {"state": "play", "song": "2"}),
                (self.QUEUE, {"state": "play", "song": "bad"})):
            with self.subTest(queue=queue, status=status):
                self.assertFalse(validate_bridge_frontier(
                    queue, status, 10, 11).conclusive)

    def test_inconclusive_ready_event_remains_retryable_without_mutation(self):
        class Backend(BridgeRejectionTests.BackendStub):
            _dj_on = True
            _dj_plan_key = (10, 11)
            _dj_ranged = {}
            _queue_mutations = QueueMutationCoordinator()

            def _start_worker(self, _target, *, args, **_kwargs):
                self._on_bridge_splice_ready({
                    "lease": args[0], "aId": args[1], "bId": args[2],
                    "state": "deferred", "frontier": None,
                })
                return True

        backend = Backend()
        backend._dj_bridge_done[(10, 11)] = "pending"

        backend._on_bridge_ready(
            10, 11, "/unused.flac", 1.0, 2.0, 1.0)

        self.assertNotIn((10, 11), backend._dj_bridge_done)
        self.assertIsNone(backend._dj_plan_key)
        self.assertIn("validation deferred", backend.logs[-1])

    def test_busy_queue_owner_defers_bridge_without_marking_failure(self):
        class Backend(BridgeRejectionTests.BackendStub):
            _dj_on = True
            _dj_plan_key = (10, 11)
            _dj_ranged = {}
            _queue_mutations = QueueMutationCoordinator()

            def _call(self, name, **_kwargs):
                if name == "playlistinfo":
                    return list(BridgeFrontierTests.QUEUE)
                return {"state": "play", "song": "2"}

        backend = Backend()
        entered = threading.Event()
        release = threading.Event()
        owner = threading.Thread(target=lambda: backend._queue_mutations.run(
            "playback", lambda: (entered.set(), release.wait(1))))
        owner.start()
        self.assertTrue(entered.wait(1))

        backend._on_bridge_ready(
            10, 11, "/unused.flac", 1.0, 2.0, 1.0)

        release.set()
        owner.join(1)
        self.assertNotIn((10, 11), backend._dj_bridge_done)
        self.assertIsNone(backend._dj_plan_key)
        self.assertIn("queue owned by playback", backend.logs[-1])

    def test_worker_holds_queue_lease_until_committed_publication(self):
        class Client:
            def __init__(self):
                self.rows = [
                    {"id": "10", "pos": "0", "file": "a.flac"},
                    {"id": "11", "pos": "1", "file": "b.flac"},
                ]

            def playlistinfo(self):
                return [dict(row) for row in self.rows]

            def status(self):
                return {"state": "stop"}

            def addid(self, file, position):
                self.rows.insert(position, {
                    "id": "30", "pos": str(position), "file": file,
                })
                for index, row in enumerate(self.rows):
                    row["pos"] = str(index)
                return "30"

            def rangeid(self, _song_id, _spec):
                return None

            def deleteid(self, song_id):
                self.rows = [
                    row for row in self.rows
                    if int(row["id"]) != int(song_id)
                ]

        class Scope:
            def __init__(self, client):
                self.client = client

            def __enter__(self):
                return self.client

            def __exit__(self, *_args):
                return False

        class Signal:
            def __init__(self):
                self.payload = None

            def emit(self, payload):
                self.payload = payload

        class Backend(BridgeRejectionTests.BackendStub):
            def __init__(self):
                super().__init__()
                self._queue_mutations = QueueMutationCoordinator()
                self._workers = object()
                self._bridgeSpliceReady = Signal()
                self._dj_on = True
                self._dj_plan_key = (10, 11)
                self._dj_ranged = {}
                self._dj_bridges = {}
                self._dj_reset_pending = False
                self.refreshes = 0

            def _request_queue_refresh(self):
                self.refreshes += 1

        backend = Backend()
        backend._dj_bridge_done[(10, 11)] = "pending"
        lease, rejected = backend._queue_mutations.acquire(
            "dj-bridge-splice")
        self.assertIsNone(rejected)

        with patch("ampere.dj.planner.temporary_mpd_client",
                   return_value=Scope(Client())):
            backend._bridge_splice_worker(
                lease, 10, 11, "/bridge.flac", 8.0, 2.0,
                None, None, "mix")

        payload = backend._bridgeSpliceReady.payload
        self.assertEqual(payload["state"], "committed")
        self.assertEqual(payload["result"].bridge_id, 30)
        self.assertEqual(
            backend._queue_mutations.active_owner, "dj-bridge-splice")

        backend._on_bridge_splice_ready(payload)

        self.assertEqual(backend._queue_mutations.active_owner, "")
        self.assertEqual(backend._dj_bridges[30], (10, 11, "mix"))
        self.assertEqual(backend._dj_ranged[10], (0.0, 8.0))
        self.assertEqual(backend._dj_ranged[11], (2.0, 0.0))
        self.assertEqual(backend._dj_bridge_done[(10, 11)], "mix")
        self.assertEqual(backend.refreshes, 1)


class CutSnapshotTests(unittest.TestCase):
    def test_requires_fresh_playing_identity_and_finite_elapsed(self):
        valid = validate_cut_snapshot({
            "state": "play", "songid": "42", "elapsed": "18.5",
        }, 42)
        self.assertTrue(valid.conclusive)
        self.assertTrue(valid.valid)
        self.assertEqual(18.5, valid.elapsed)

        for status in (
                None,
                {"state": "play", "songid": "42", "elapsed": "bad"},
                {"state": "play", "songid": "42", "elapsed": "nan"}):
            with self.subTest(status=status):
                self.assertFalse(validate_cut_snapshot(
                    status, 42).conclusive)

        changed = validate_cut_snapshot({
            "state": "play", "songid": "43", "elapsed": "1.0",
        }, 42)
        self.assertTrue(changed.conclusive)
        self.assertFalse(changed.valid)


class PlayheadTests(unittest.TestCase):
    def test_requires_song_identity_only_while_playing_or_paused(self):
        playing = validate_playhead({"state": "play", "songid": "42"})
        stopped = validate_playhead({"state": "stop"})

        self.assertTrue(playing.conclusive)
        self.assertEqual(42, playing.song_id)
        self.assertTrue(stopped.conclusive)
        self.assertEqual(-1, stopped.song_id)

        for status in (None, {}, {"state": "play"},
                       {"state": "pause", "songid": "bad"}):
            with self.subTest(status=status):
                self.assertFalse(validate_playhead(status).conclusive)


if __name__ == "__main__":
    unittest.main()
