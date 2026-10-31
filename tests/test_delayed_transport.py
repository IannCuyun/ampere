import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ampere.dj import verify as djverify
from ampere.dj.planner import DjPlannerMixin
from ampere.mpdclient import Backend


class DelayedBackend(DjPlannerMixin):
    _fire_trim = Backend._fire_trim
    _on_delayed_status_ready = Backend._on_delayed_status_ready

    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self._trim_gen = 4
        self._trim_on = True
        self._automix_on = False
        self._single = False
        self._tail_cut = 100.0
        self._dj_gen = 7
        self._dj_on = True
        self._state = "play"
        self._elapsed = 0.0
        self._dj_cut_at = 80.0
        self._song = {"title": "Song"}
        self._dj_level = "wild"
        self._dj_redropped = set()
        self.writes = []
        self.fades = 0
        self.seeks = []
        self.logs = []

    def _call(self, _name, default=None):
        return next(self.statuses, default)

    def _request_delayed_status(self, kind, generation, song_id,
                                context=None):
        self._on_delayed_status_ready({
            "kind": kind,
            "generation": generation,
            "snapshot": djverify.validate_cut_snapshot(
                self._call("status", default=None), song_id),
            "context": dict(context or {}),
        })
        return True

    def _write_once(self, name, *args):
        self.writes.append((name, args))
        return True

    def _dj_log_transition(self, *args, **kwargs):
        self.logs.append((args, kwargs))

    def _dj_log(self, message):
        self.logs.append(message)

    def _dj_fader_next(self, action=None):
        self.fades += 1
        if action:
            action()

    def _seek_current_once(self, seconds):
        self.seeks.append(seconds)
        return True


class DelayedTransportTests(unittest.TestCase):
    def status(self, song_id=42, elapsed=100.0, state="play"):
        return {"state": state, "songid": str(song_id),
                "elapsed": str(elapsed)}

    def test_silent_tail_trim_requires_same_song_at_tail(self):
        changed = DelayedBackend([self.status(song_id=43)])
        changed._fire_trim(4, 42)
        self.assertEqual([], changed.writes)

        valid = DelayedBackend([self.status(elapsed=99.0)])
        valid._fire_trim(4, 42)
        self.assertEqual([("next", ())], valid.writes)

    def test_timed_dj_cut_requires_same_song_at_cut_point(self):
        drifted = DelayedBackend([self.status(elapsed=20.0)])
        drifted._dj_fire(7, 42)
        self.assertEqual(0, drifted.fades)

        valid = DelayedBackend([self.status(elapsed=79.0)])
        valid._dj_fire(7, 42)
        self.assertEqual(1, valid.fades)

    def test_redrop_timer_rejects_successor_and_accepts_expected_position(self):
        cues = {"in": [(10.0, 0.9)], "out": [(70.0, 0.8)],
                "dur": 120.0}
        cur = {"id": 10}

        changed = DelayedBackend([self.status(song_id=11, elapsed=0.2)])
        scheduled = []
        with patch("ampere.dj.planner.QTimer.singleShot",
                   side_effect=lambda _delay, action: scheduled.append(action)):
            changed._dj_arm_redrop(cur, cues, 0.0, 0.0)
        scheduled[0]()
        self.assertEqual([], changed.seeks)
        self.assertEqual(0, changed.fades)

        valid = DelayedBackend([self.status(song_id=10, elapsed=69.85)])
        scheduled = []
        with patch("ampere.dj.planner.QTimer.singleShot",
                   side_effect=lambda _delay, action: scheduled.append(action)):
            valid._dj_arm_redrop(cur, cues, 0.0, 0.0)
        scheduled[0]()
        self.assertEqual([10.0], valid.seeks)
        self.assertEqual(1, valid.fades)

    def test_delayed_status_worker_uses_its_owned_client(self):
        backend = type("Harness", (), {})()
        backend._workers = object()
        emitted = []
        backend._delayedStatusReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        client = type("Client", (), {
            "status": lambda self: {
                "state": "play", "songid": "42", "elapsed": "99.5",
            },
        })()

        @contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            self.assertTrue(Backend._request_delayed_status(
                backend, "trim", 4, 42))

        self.assertTrue(emitted[0]["snapshot"].valid)
        self.assertEqual(99.5, emitted[0]["snapshot"].elapsed)


if __name__ == "__main__":
    unittest.main()
