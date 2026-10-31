import unittest
import contextlib
from unittest.mock import patch

from mpd.base import ConnectionError as MPDConnectionError

from ampere.automix import (
    AutoMixDaemonController, TransitionOptionsResult,
    TransitionThresholdResult,
    energy_fade_factor, fade_duration,
)
from ampere.mpdclient import Backend


class AutoMixPolicyTests(unittest.TestCase):
    def test_energy_factor_uses_pair_mean_and_safety_bounds(self):
        self.assertAlmostEqual(energy_fade_factor([.2, .4]), 1.22)
        self.assertEqual(energy_fade_factor([]), 1.0)
        self.assertEqual(energy_fade_factor([-10]), 1.45)
        self.assertEqual(energy_fade_factor([10]), .55)

    def test_threshold_interpolates_mixramp_curve(self):
        self.assertEqual(fade_duration(
            base=6, factor=1, mixramp_end="-30 10; -10 2",
            mixramp_db=-20), 6)

    def test_replaygain_corrects_required_file_level(self):
        # -15 daemon threshold minus +5 dB file gain = -20 dB -> 6 sec.
        self.assertEqual(fade_duration(
            base=4, factor=1, mixramp_end="-30 10; -10 2",
            mixramp_db=-15, replaygain="+5.0 dB"), 6)

    def test_energy_scaling_happens_before_whole_bar_snap(self):
        # 5 sec * .8 = 4 sec; at 120 BPM a four-beat bar is 2 sec.
        self.assertEqual(fade_duration(
            base=6, factor=.8, mixramp_end="-20 5", mixramp_db=-20,
            bpm=120), 4)

    def test_malformed_or_missing_curve_uses_scaled_base(self):
        self.assertEqual(fade_duration(
            base=6, factor=.5, mixramp_end="broken; also bad"), 3)
        self.assertEqual(fade_duration(base=20, factor=1), 10)
        self.assertEqual(fade_duration(base=1, factor=1), 2)

    def test_curve_extremes_and_invalid_bpm_are_safe(self):
        curve = "-30 12; -10 1"
        self.assertEqual(fade_duration(
            base=6, factor=1, mixramp_end=curve, mixramp_db=-40,
            bpm="bad"), 10)
        self.assertEqual(fade_duration(
            base=6, factor=1, mixramp_end=curve, mixramp_db=0), 2)


class TransitionClient:
    def __init__(self, delay=None, crossfade=4):
        self.delay = delay
        self.crossfade_value = crossfade
        self.fail_after_delay = False
        self.mixramp_db = -17.0
        self.ignore_threshold_once = False

    def status(self):
        return {
            "mixrampdelay": "nan" if self.delay is None else str(self.delay),
            "xfade": str(self.crossfade_value),
            "mixrampdb": str(self.mixramp_db),
        }

    def mixrampdb(self, value):
        if self.ignore_threshold_once:
            self.ignore_threshold_once = False
            return
        self.mixramp_db = float(value)

    def command_list_ok_begin(self):
        pass

    def mixrampdelay(self, value):
        self.delay = None if value == "nan" else float(value)
        if self.fail_after_delay:
            self.fail_after_delay = False
            raise MPDConnectionError("partial transition reply lost")

    def crossfade(self, value):
        self.crossfade_value = int(value)

    def command_list_end(self):
        pass


class AutoMixDaemonControllerTests(unittest.TestCase):
    def controller(self, client, errors, disconnects):
        return AutoMixDaemonController(
            client, ensure_connected=lambda silent=False: True,
            mark_disconnected=lambda: disconnects.append(True),
            error=errors.append)

    def test_transition_pair_commits_only_after_fresh_status(self):
        client, errors, disconnects = TransitionClient(), [], []
        result = self.controller(client, errors, disconnects).configure(
            mixramp_delay=1.5, crossfade=7)
        self.assertTrue(result.committed)
        self.assertEqual((1.5, 7), (client.delay, client.crossfade_value))
        self.assertEqual([], errors)

    def test_partial_transition_pair_rolls_back_prior_daemon_state(self):
        client, errors, disconnects = TransitionClient(None, 4), [], []
        client.fail_after_delay = True
        result = self.controller(client, errors, disconnects).configure(
            mixramp_delay=1.5, crossfade=7)
        self.assertFalse(result.committed)
        self.assertTrue(result.rollback_complete)
        self.assertEqual((None, 4), (client.delay, client.crossfade_value))
        self.assertEqual(1, len(disconnects))
        self.assertIn("could not be changed", errors[-1])

    def test_threshold_commits_only_after_authoritative_readback(self):
        client, errors, disconnects = TransitionClient(), [], []
        result = self.controller(client, errors, disconnects).set_threshold(-30)

        self.assertTrue(result.committed)
        self.assertEqual(-30.0, result.value)
        self.assertEqual(-30.0, client.mixramp_db)
        self.assertEqual([], errors)

    def test_rejected_threshold_restores_and_publishes_baseline(self):
        client, errors, disconnects = TransitionClient(), [], []
        client.ignore_threshold_once = True
        result = self.controller(client, errors, disconnects).set_threshold(-30)

        self.assertFalse(result.committed)
        self.assertTrue(result.rollback_complete)
        self.assertEqual(-17.0, result.value)
        self.assertEqual(-17.0, client.mixramp_db)
        self.assertIn("could not be changed", errors[-1])


class AutoMixPublicationTests(unittest.TestCase):
    def backend(self):
        backend = type("Harness", (), {})()
        backend._automix_on = False
        backend._mixrampdb = -17.0
        backend._xfade_base = 4
        backend._mix_style = "blend"
        backend._dj_active = False
        backend._xfade = 4
        backend._queue_pos = -1
        backend._queue = []
        backend._song = {}
        backend._transition_settings_generation = 1
        backend._transition_settings_busy = True
        backend._transition_settings_active = None
        backend._transition_settings_pending = None
        backend._transition_internal_pending = None
        backend._transition_internal_failed = False
        backend.saved = backend.changed = backend.statuses = 0
        backend.scans = backend.refreshes = 0
        backend._save_conf = lambda: setattr(
            backend, "saved", backend.saved + 1)
        backend.settingsChanged = type("Signal", (), {
            "emit": lambda _self: setattr(
                backend, "changed", backend.changed + 1),
        })()
        backend.statusChanged = type("Signal", (), {
            "emit": lambda _self: setattr(
                backend, "statuses", backend.statuses + 1),
        })()
        backend.errorOccurred = type("Signal", (), {"emit": lambda *_args: None})()
        backend._start_mixramp_scan = lambda: setattr(
            backend, "scans", backend.scans + 1)
        backend.requestStatusRefresh = lambda: setattr(
            backend, "refreshes", backend.refreshes + 1)
        backend._transition_settings_desired = lambda: (
            Backend._transition_settings_desired(backend))
        backend._transition_target = lambda **kwargs: (
            Backend._transition_target(backend, **kwargs))
        return backend

    def test_enable_is_published_only_after_daemon_pair_commits(self):
        failed = self.backend()
        Backend._on_transition_settings_ready(failed, {
            "generation": 1, "publish": {"automix_on": True},
            "scan": True,
            "optionsResult": TransitionOptionsResult(False),
        })
        self.assertFalse(failed._automix_on)
        self.assertEqual((0, 0), (failed.saved, failed.scans))

        committed = self.backend()
        Backend._on_transition_settings_ready(committed, {
            "generation": 1, "publish": {"automix_on": True},
            "scan": True,
            "optionsResult": TransitionOptionsResult(True),
        })
        self.assertTrue(committed._automix_on)
        self.assertEqual((1, 1), (committed.saved, committed.scans))

    def test_first_enable_requires_verified_safety_threshold(self):
        backend = self.backend()
        backend._mixrampdb = 0.0
        captured = []
        backend._request_transition_settings = lambda request: (
            captured.append(request) or True)
        backend._transition_target = lambda **kwargs: (
            Backend._transition_target(backend, **kwargs))

        self.assertTrue(Backend.setMixRampOn(backend, True))

        self.assertEqual(-30.0, captured[0]["threshold"])
        self.assertEqual(-30.0, captured[0]["publish"]["mixrampdb"])
        self.assertEqual(1.5, captured[0]["delay"])
        self.assertTrue(captured[0]["scan"])

    def test_threshold_slot_defers_publication_to_worker_result(self):
        backend = self.backend()
        captured = []
        backend._request_transition_settings = lambda request: (
            captured.append(request) or True)

        self.assertTrue(Backend.setMixRampDb(backend, -30.0))
        self.assertEqual(-17.0, backend._mixrampdb)
        self.assertEqual(-30.0, captured[0]["threshold"])

    def test_latest_pending_request_inherits_complete_desired_state(self):
        backend = self.backend()
        backend._transition_settings_busy = False
        backend._transition_settings_generation = 0
        launched = []

        def launch(request):
            backend._transition_settings_busy = True
            backend._transition_settings_active = request
            launched.append(request)
            return True

        backend._start_transition_settings_request = launch
        backend._request_transition_settings = lambda request: (
            Backend._request_transition_settings(backend, request))
        backend._transition_settings_desired = lambda: (
            Backend._transition_settings_desired(backend))
        backend._transition_target = lambda **kwargs: (
            Backend._transition_target(backend, **kwargs))
        backend._fade_duration = lambda *_args, **_kwargs: 7

        self.assertTrue(Backend.setMixRampOn(backend, True))
        self.assertTrue(Backend.setMixStyle(backend, "fade"))

        pending = backend._transition_settings_pending
        self.assertEqual(1, len(launched))
        self.assertTrue(pending["publish"]["automix_on"])
        self.assertEqual("fade", pending["publish"]["mix_style"])
        self.assertEqual(7, pending["crossfade"])

    def test_settings_worker_uses_one_owned_client(self):
        backend = self.backend()
        backend._workers = object()
        emitted = []
        backend._transitionSettingsReady = type("Signal", (), {
            "emit": lambda _self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        client = TransitionClient()
        client.ping = lambda: None

        @contextlib.contextmanager
        def scope(*_args, **_kwargs):
            yield client

        request = {
            "generation": 1, "delay": 1.5, "crossfade": 6,
            "threshold": -30.0, "publish": {},
        }
        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._start_transition_settings_request(
                backend, request))

        self.assertEqual((-30.0, 1.5, 6), (
            client.mixramp_db, client.delay, client.crossfade_value))
        self.assertTrue(emitted[0]["thresholdResult"].committed)
        self.assertTrue(emitted[0]["optionsResult"].committed)

    def test_user_transaction_has_priority_over_internal_retune(self):
        backend = self.backend()
        backend._transition_settings_busy = True
        backend._transition_settings_active = {"internal": False}

        self.assertFalse(Backend._request_internal_transition(
            backend, mixramp_delay=None, crossfade=7))
        self.assertIsNone(backend._transition_internal_pending)

    def test_internal_retunes_coalesce_and_dj_publishes_after_commit(self):
        backend = self.backend()
        backend._transition_settings_busy = False
        backend._transition_settings_generation = 0
        backend._dj_active = False
        backend._dj_plan_key = (1, 2)
        launched = []

        def launch(request):
            backend._transition_settings_busy = True
            backend._transition_settings_active = request
            launched.append(request)
            return True

        backend._start_transition_settings_request = launch
        self.assertTrue(Backend._request_internal_transition(
            backend, mixramp_delay=None, crossfade=2, dj_active=True))
        self.assertTrue(Backend._request_internal_transition(
            backend, mixramp_delay=None, crossfade=4, dj_active=True))
        self.assertEqual(4, backend._transition_internal_pending["crossfade"])
        self.assertFalse(backend._dj_active)

        Backend._on_transition_settings_ready(backend, {
            **launched[0], "optionsResult": TransitionOptionsResult(True),
        })

        self.assertFalse(backend._dj_active)
        self.assertEqual(2, len(launched))

        Backend._on_transition_settings_ready(backend, {
            **launched[1], "optionsResult": TransitionOptionsResult(True),
        })
        self.assertTrue(backend._dj_active)

    def test_fade_retune_uses_verified_transition_pair(self):
        backend = type("Harness", (), {})()
        backend._dj_active = False
        backend._xfade = 4
        backend._queue_pos = 0
        backend._queue = [{"file": "a.flac"}, {"file": "b.flac"}]
        backend._song = {"file": "a.flac"}
        backend._fade_active = lambda: True
        backend._fade_duration = lambda *_args, **_kwargs: 7
        backend.calls = []
        backend._configure_transitions = lambda **kwargs: (
            backend.calls.append(kwargs) or True)

        Backend._apply_fade_xfade(backend)

        self.assertEqual(backend.calls, [{
            "mixramp_delay": None, "crossfade": 7,
        }])

    def test_fade_timing_uses_cached_energy_and_bpm_without_sticker_io(self):
        backend = type("Harness", (), {})()
        backend._library_energies = {"a.flac": .2, "b.flac": .4}
        backend._library_bpms = {"a.flac": 120.0}
        backend._energy_fade_factor = lambda *args: \
            Backend._energy_fade_factor(backend, *args)
        backend._stickers = type("Stickers", (), {
            "number": lambda *_args, **_kwargs: self.fail("read sticker"),
        })()
        backend._xfade_base = 6
        backend._mixrampdb = -30.0

        cached = Backend._fade_duration(backend, "a.flac", "b.flac")
        unknown = Backend._fade_duration(backend, "missing.flac")

        self.assertGreater(cached, unknown)
        self.assertEqual(6, unknown)


if __name__ == "__main__":
    unittest.main()
