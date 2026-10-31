import unittest
from pathlib import Path
import re

from PySide6.QtCore import QObject

from ampere.mpdclient import Backend


ROOT = Path(__file__).resolve().parents[1]


class PlaybackIntentTests(unittest.TestCase):
    @staticmethod
    def backend():
        backend = Backend.__new__(Backend)
        QObject.__init__(backend)
        backend._playback_intent_active = set()
        backend._playback_intent_pending = {}
        backend._transport_intent_target = None
        backend._state = "play"
        backend._elapsed = 0.0
        backend._duration = 240.0
        backend.launched = []
        backend._start_worker = lambda work, **_kwargs: (
            backend.launched.append(work) or True)
        return backend

    def test_previous_before_four_seconds_moves_to_previous_track(self):
        backend = self.backend()
        backend._elapsed = 3.999
        requests = []
        backend._request_playback_intent = (
            lambda key, request, **kwargs:
            requests.append((key, request, kwargs.get("on_finished"))) or True)
        backend._soft_move = lambda action: action()

        self.assertTrue(Backend.requestPrevious(backend))

        self.assertEqual([("move", {"command": "previous"}, None)], requests)

    def test_previous_at_four_seconds_restarts_current_track(self):
        backend = self.backend()
        backend._elapsed = 4.0
        requests = []
        backend._request_playback_intent = (
            lambda key, request, **kwargs:
            requests.append((key, request, kwargs.get("on_finished"))) or True)
        backend._soft_move = lambda _action: self.fail(
            "restarting the current track must not run a queue-move fade")

        self.assertTrue(Backend.requestPrevious(backend))

        self.assertEqual([("seek", {"seconds": 0.0}, None)], requests)

    def test_legacy_previous_slot_uses_the_shared_threshold_policy(self):
        backend = self.backend()
        backend._elapsed = 8.0
        requests = []
        backend._request_playback_intent = (
            lambda key, request, **kwargs:
            requests.append((key, request)) or True)

        self.assertTrue(Backend.previous(backend))

        self.assertEqual([("seek", {"seconds": 0.0})], requests)

    def test_volume_drag_starts_one_worker_and_keeps_only_latest_value(self):
        backend = self.backend()

        self.assertTrue(Backend.requestVolume(backend, 25))
        self.assertTrue(Backend.requestVolume(backend, 50))
        self.assertTrue(Backend.requestVolume(backend, 75))

        self.assertEqual(1, len(backend.launched))
        self.assertEqual({"value": 75},
                         backend._playback_intent_pending["volume"])

    def test_rapid_play_pause_tracks_latest_absolute_intent(self):
        backend = self.backend()

        Backend.requestPlayPause(backend)
        Backend.requestPlayPause(backend)

        self.assertEqual("play", backend._transport_intent_target)
        self.assertEqual({"state": "play"},
                         backend._playback_intent_pending["transport"])

    def test_loop_cycle_has_only_off_queue_and_song_states(self):
        backend = self.backend()
        backend._repeat = False
        backend._single = False
        backend._repeat_intent_target = None
        backend._autoplay_on = True
        requests = []
        backend._request_playback_intent = lambda key, request: (
            requests.append((key, request)) or True)

        Backend.requestCycleRepeat(backend)
        Backend.requestCycleRepeat(backend)
        Backend.requestCycleRepeat(backend)

        self.assertEqual([
            ("repeat", {"repeat": True, "single": False}),
            ("repeat", {"repeat": True, "single": True}),
            ("repeat", {"repeat": False, "single": False}),
        ], requests)
        self.assertTrue(backend._autoplay_on)
        self.assertTrue(all(
            "radioAfter" not in request for _, request in requests))

    def test_worker_start_failure_clears_optimistic_transport_target(self):
        backend = self.backend()
        backend._start_worker = lambda *_args, **_kwargs: False
        errors = []
        backend.errorOccurred.connect(errors.append)

        self.assertFalse(Backend.requestTransport(backend, "pause"))

        self.assertIsNone(backend._transport_intent_target)
        self.assertNotIn("transport", backend._playback_intent_active)
        self.assertNotIn("transport", backend._playback_intent_pending)
        self.assertTrue(errors)

    def test_completed_intent_starts_only_the_latest_pending_request(self):
        backend = self.backend()
        backend._playback_intent_active.add("volume")
        backend._playback_intent_pending["volume"] = {"value": 75}

        Backend._on_playback_intent_ready(backend, {
            "key": "volume", "request": {"value": 25},
            "result": None, "messages": (),
        })

        self.assertEqual(1, len(backend.launched))
        self.assertIn("volume", backend._playback_intent_active)
        self.assertNotIn("volume", backend._playback_intent_pending)

    def test_superseded_phone_completion_is_failed_before_latest_replaces_it(self):
        backend = self.backend()
        backend._playback_intent_active.add("volume")
        completions = []

        Backend._request_playback_intent(
            backend, "volume", {"value": 50},
            on_finished=lambda *result: completions.append(result))
        Backend._request_playback_intent(
            backend, "volume", {"value": 75},
            on_finished=lambda *result: completions.append(("latest", *result)))

        self.assertEqual(
            [(False, "Superseded by a newer phone command")], completions)
        self.assertEqual(
            75, backend._playback_intent_pending["volume"]["value"])

    def test_qml_interactions_use_nonblocking_request_slots(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        active_playback = (
            "PlayerBar.qml", "GalleryNowPlayingView.qml", "ShuffleControl.qml",
            "WaveSeek.qml")
        self.assertIn("GalleryNowPlayingView {", main)
        self.assertIsNone(re.search(r"(?m)^\s*NowPlayingView\s*\{", main))
        self.assertIsNone(re.search(r"(?m)^\s*LyricsView\s*\{", main))
        qml = "\n".join(
            (ROOT / "qml" / name).read_text() for name in active_playback)
        for old_call in (
                "backend.playPause()", "backend.next()", "backend.previous()",
                "backend.seek(", "backend.setVolume(",
                "backend.cycleRepeat()", "backend.reshuffleQueue()"):
            self.assertNotIn(old_call, qml)
        for request_call in (
                "backend.requestPlayPause()", "backend.requestNext()",
                "backend.requestPrevious()", "backend.requestSeek(",
                "backend.requestVolume(", "backend.requestCycleRepeat()",
                "backend.cycleContextShuffle("):
            self.assertIn(request_call, qml)

    def test_shuffle_control_is_direct_cycle_without_popup(self):
        qml = (ROOT / "qml" / "ShuffleControl.qml").read_text()
        gallery = (ROOT / "qml" / "GalleryNowPlayingView.qml").read_text()
        self.assertIn("backend.contextShuffleMode", qml)
        self.assertIn("backend.cycleContextShuffle(", qml)
        self.assertIn('"smart-shuffle"', qml)
        self.assertIn("active: control.active", qml)
        self.assertNotIn("Popup", qml)
        self.assertRegex(
            gallery,
            r"ShuffleControl\s*\{[^}]*Layout\.preferredWidth:\s*44"
            r"[^}]*Layout\.preferredHeight:\s*44")


if __name__ == "__main__":
    unittest.main()
