import unittest
from unittest.mock import patch

from ampere.dj import verify as djverify
from ampere.dj.planner import DjPlannerMixin
from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class CutBackend:
    djCutNow = Backend.djCutNow
    _dj_apply_delayed_status = DjPlannerMixin._dj_apply_delayed_status

    def __init__(self, statuses):
        self._state = "play"
        self._song = {"file": "song.flac", "title": "Song",
                      "rangeStart": 0.0}
        self._cur_songid = 42
        self._dj_gen = 7
        self._dj_cutnow_armed = False
        self.statuses = iter(statuses)
        self.fades = 0
        self.logs = []
        self.errorOccurred = Signal()

    def _call(self, name, default=None):
        self.assert_command = name
        return next(self.statuses, default)

    def _dj_cues(self, _file):
        return {"bpm": 120.0, "b0": 0.0}

    def _dj_log_transition(self, *args, **kwargs):
        self.logs.append((args, kwargs))

    def _dj_fader_next(self):
        self.fades += 1

    def _request_delayed_status(self, kind, generation, song_id,
                                context=None):
        self._dj_apply_delayed_status(
            kind, generation,
            djverify.validate_cut_snapshot(
                self._call("status", default=None), song_id),
            dict(context or {}))
        return True


class DjCutNowTests(unittest.TestCase):
    PLAYING = {"state": "play", "songid": "42", "elapsed": "10.0"}

    def test_unavailable_arm_never_schedules_or_skips(self):
        backend = CutBackend([None])
        scheduled = []

        with patch("ampere.mpdclient.QTimer.singleShot",
                   side_effect=lambda delay, action: scheduled.append(
                       (delay, action))):
            backend.djCutNow()

        self.assertEqual([], scheduled)
        self.assertEqual(0, backend.fades)
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_click_routes_initial_authority_to_delayed_worker(self):
        backend = CutBackend([])
        requests = []
        backend._call = lambda *_args, **_kwargs: self.fail(
            "Cut Now must not read MPD on Qt's thread")
        backend._request_delayed_status = lambda *args: \
            requests.append(args) or True

        self.assertTrue(backend.djCutNow())

        self.assertTrue(backend._dj_cutnow_armed)
        self.assertEqual("dj-cut-now-arm", requests[0][0])
        self.assertEqual(42, requests[0][2])

    def test_timer_rejects_a_different_song_before_skip(self):
        backend = CutBackend([
            self.PLAYING,
            {"state": "play", "songid": "43", "elapsed": "0.2"},
        ])
        scheduled = []
        with patch("ampere.mpdclient.QTimer.singleShot",
                   side_effect=lambda _delay, action: scheduled.append(action)):
            backend.djCutNow()
        scheduled[0]()

        self.assertEqual(0, backend.fades)
        self.assertFalse(backend._dj_cutnow_armed)

    def test_timer_skips_only_the_same_song_near_expected_beat(self):
        backend = CutBackend([
            self.PLAYING,
            {"state": "play", "songid": "42", "elapsed": "11.85"},
        ])
        scheduled = []
        with patch("ampere.mpdclient.QTimer.singleShot",
                   side_effect=lambda _delay, action: scheduled.append(action)):
            backend.djCutNow()
        scheduled[0]()

        self.assertEqual(1, backend.fades)
        self.assertEqual(1, len(backend.logs))


if __name__ == "__main__":
    unittest.main()
