import unittest
from unittest.mock import patch

from ampere.mpdclient import Backend
from ampere.playback import QueueSnapshotResult, QueueSnapshotStore


class Signal:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class QueueRefreshTests(unittest.TestCase):
    def backend(self, response):
        calls = []
        backend = type("QueueAdapter", (), {})()
        backend._queue = [{"file": "verified", "id": 7}]
        backend._queue_snapshots = QueueSnapshotStore(
            normalize=lambda item: dict(item))
        backend._queue_snapshots.publish(backend._queue)
        backend._call = lambda name, default=None: response
        backend._dj_sweep_stale = lambda *_args: calls.append("sweep")
        backend._dj_log = lambda message: calls.append(("log", message))
        backend.queueChanged = Signal()
        backend.requestStatusRefresh = lambda: calls.append("status")
        return backend, calls

    def test_compatibility_facade_delegates_to_owned_worker_pipeline(self):
        backend = type("Harness", (), {})()
        calls = []
        backend._request_queue_refresh = lambda: (
            calls.append("worker") or True)

        self.assertTrue(Backend.refreshQueue(backend))
        self.assertEqual(["worker"], calls)

    def test_normalized_publication_is_defensive_and_rejects_missing_files(self):
        store = QueueSnapshotStore(normalize=lambda item: dict(item))
        store.publish([{"file": "kept.flac", "id": 1}])

        source = [{"file": "new.flac", "id": 2}]
        result = store.publish_normalized(source)
        source[0]["file"] = "mutated.flac"
        rejected = store.publish_normalized([{"id": 3}])

        self.assertTrue(result.success)
        self.assertEqual("new.flac", store.songs[0]["file"])
        self.assertFalse(rejected.success)
        self.assertEqual("new.flac", store.songs[0]["file"])

    def test_worker_queue_refresh_uses_owned_client(self):
        backend = type("Harness", (), {})()
        backend._queue_refresh_busy = False
        backend._queue_refresh_pending = False
        backend._queue_refresh_generation = 0
        backend._workers = object()
        emitted = []
        backend._queueRefreshReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        calls = []
        client = type("Client", (), {
            "status": lambda self: (
                calls.append("status") or {
                    "state": "pause", "songid": "7",
                }),
            "playlistinfo": lambda self: (
                calls.append("playlistinfo") or [{
                    "file": "song.flac", "id": "7", "pos": "0",
                }]),
        })()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=Scope()):
            self.assertTrue(Backend._request_queue_refresh(backend))

        self.assertEqual(["playlistinfo", "status"], calls)
        self.assertTrue(emitted[0]["result"].success)
        self.assertEqual(7, emitted[0]["result"].songs[0]["id"])
        self.assertEqual("7", emitted[0]["playheadStatus"]["songid"])

    def test_worker_failure_retains_queue_and_warns_once_until_recovery(self):
        class MessageSignal:
            def __init__(self):
                self.messages = []

            def emit(self, *args):
                self.messages.append(args)

        backend, calls = self.backend(None)
        backend._queue_refresh_generation = 1
        backend._queue_refresh_busy = True
        backend._queue_refresh_pending = False
        backend._queue_refresh_failed = False
        backend.errorOccurred = MessageSignal()

        Backend._on_queue_refresh_ready(backend, {
            "generation": 1, "result": None,
        })
        backend._queue_refresh_busy = True
        Backend._on_queue_refresh_ready(backend, {
            "generation": 1, "result": None,
        })

        self.assertEqual([{"file": "verified", "id": 7}], backend._queue)
        self.assertEqual([], calls)
        self.assertEqual(1, len(backend.errorOccurred.messages))

        backend._queue_refresh_busy = True
        Backend._on_queue_refresh_ready(backend, {
            "generation": 1,
            "result": QueueSnapshotResult(
                True, ({"file": "fresh.flac", "id": 9},)),
        })
        self.assertEqual("fresh.flac", backend._queue[0]["file"])
        self.assertFalse(backend._queue_refresh_failed)

    def test_pending_idle_refresh_skips_intermediate_snapshot(self):
        backend = type("Harness", (), {})()
        backend._queue_refresh_generation = 3
        backend._queue_refresh_busy = True
        backend._queue_refresh_pending = True
        backend._queue = [{"file": "verified.flac"}]
        launched = []
        backend._request_queue_refresh = lambda: (
            launched.append("refresh") or True)

        Backend._on_queue_refresh_ready(backend, {
            "generation": 3,
            "result": QueueSnapshotResult(
                True, ({"file": "intermediate.flac"},)),
        })

        self.assertEqual([{"file": "verified.flac"}], backend._queue)
        self.assertEqual(["refresh"], launched)

    def test_synchronous_reconciliation_invalidates_worker_result(self):
        backend = type("Harness", (), {})()
        backend._queue_refresh_generation = 5
        backend._queue_refresh_busy = True
        backend._queue_refresh_pending = False
        backend._queue = [{"file": "committed.flac"}]
        launched = []
        backend._request_queue_refresh = lambda: (
            launched.append("refresh") or True)

        Backend._invalidate_queue_refresh(backend)
        Backend._on_queue_refresh_ready(backend, {
            "generation": 5,
            "result": QueueSnapshotResult(True, ({"file": "stale.flac"},)),
        })

        self.assertEqual([{"file": "committed.flac"}], backend._queue)
        self.assertEqual(["refresh"], launched)


if __name__ == "__main__":
    unittest.main()
