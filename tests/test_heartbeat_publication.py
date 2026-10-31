import unittest

from ampere.mpdclient import Backend


class HeartbeatPublicationTests(unittest.TestCase):
    def backend(self, responses):
        backend = type("HeartbeatAdapter", (), {})()
        backend._state = "pause"
        backend._song = {"file": "verified.flac"}
        backend._elapsed = 42.0
        backend._duration = 180.0
        backend._volume = 73
        backend._mixrampdb = -17.0
        calls = []

        class Client:
            def status(_self):
                calls.append("status")
                return responses.get("status")

            def currentsong(_self):
                calls.append("currentsong")
                return responses.get("currentsong")

        def call(name, default=None):
            calls.append(name)
            return responses.get(name, default)

        backend._call = call
        backend.client = Client()
        backend._read_heartbeat = lambda cli: Backend._read_heartbeat(
            backend, cli)
        backend._publish_heartbeat = lambda heartbeat: bool(heartbeat)
        return backend, calls

    def assert_preserved(self, backend):
        self.assertEqual("pause", backend._state)
        self.assertEqual({"file": "verified.flac"}, backend._song)
        self.assertEqual((42.0, 180.0, 73), (
            backend._elapsed, backend._duration, backend._volume))

    def test_unavailable_status_exits_before_current_song_read(self):
        backend, calls = self.backend({})
        self.assertIsNone(Backend._read_heartbeat(backend, backend.client))
        self.assertEqual(["status"], calls)
        self.assert_preserved(backend)

    def test_unavailable_current_song_prevents_partial_status_commit(self):
        backend, calls = self.backend({
            "status": {"state": "play", "elapsed": "99", "volume": "12"}
        })
        self.assertIsNone(Backend._read_heartbeat(backend, backend.client))
        self.assertEqual(["status", "currentsong"], calls)
        self.assert_preserved(backend)

    def test_malformed_current_song_prevents_partial_status_commit(self):
        backend, _calls = self.backend({
            "status": {"state": "play"}, "currentsong": []
        })
        self.assertIsNone(Backend._read_heartbeat(backend, backend.client))
        self.assert_preserved(backend)

    def test_refresh_status_invalidates_then_routes_to_owned_worker(self):
        backend = type("HeartbeatAdapter", (), {})()
        backend._status_refresh_generation = 4
        backend._status_refresh_busy = False
        backend.requested = 0
        backend.requestStatusRefresh = lambda: setattr(
            backend, "requested", backend.requested + 1) or True

        self.assertTrue(Backend.refreshStatus(backend))

        self.assertEqual(5, backend._status_refresh_generation)
        self.assertEqual(1, backend.requested)

    def test_busy_refresh_coalesces_without_starting_another_worker(self):
        backend = type("HeartbeatAdapter", (), {})()
        backend._status_refresh_busy = True
        backend._status_refresh_pending = False
        self.assertFalse(Backend.requestStatusRefresh(backend))
        self.assertTrue(backend._status_refresh_pending)

    def test_stale_worker_result_is_not_published(self):
        backend = type("HeartbeatAdapter", (), {})()
        backend._status_refresh_generation = 4
        backend._status_refresh_busy = True
        backend._status_refresh_pending = False
        backend.published = []
        backend._publish_heartbeat = backend.published.append
        Backend._on_status_refresh_ready(backend, {
            "generation": 3, "heartbeat": object(),
        })
        self.assertEqual([], backend.published)
        self.assertFalse(backend._status_refresh_busy)

    def test_tick_runs_only_while_playing(self):
        class Tick:
            def __init__(self):
                self.active = False

            def isActive(self):
                return self.active

            def start(self):
                self.active = True

            def stop(self):
                self.active = False

        backend = type("HeartbeatAdapter", (), {})()
        backend._status_tick = Tick()
        backend._state = "play"
        Backend._sync_status_tick(backend)
        self.assertTrue(backend._status_tick.active)
        backend._state = "pause"
        Backend._sync_status_tick(backend)
        self.assertFalse(backend._status_tick.active)


if __name__ == "__main__":
    unittest.main()
