import unittest

from ampere.playback_status import (PlaybackHeartbeat, PlaybackStatus,
                                  reconcile_mixramp)


class PlaybackStatusTests(unittest.TestCase):
    def test_normalizes_complete_mpd_status(self):
        result = PlaybackStatus.from_mpd({
            "state": "play", "elapsed": "12.75", "duration": "240.5",
            "volume": "83", "random": "1", "repeat": "1",
            "single": "oneshot", "song": "0", "songid": "42",
            "xfade": "7", "bitrate": "921.8", "mixrampdb": "-17.5",
            "mixrampdelay": "0.6",
        })
        self.assertEqual(result.state, "play")
        self.assertEqual(result.queue_pos, 0)
        self.assertEqual(result.song_id, 42)
        self.assertEqual(result.bitrate_kbps, 921)
        self.assertTrue(result.random and result.repeat and result.single)
        self.assertTrue(result.mixramp_delay_on)
        self.assertTrue(result.queue_position_changed(-1))
        self.assertFalse(result.queue_position_changed(0))

    def test_missing_values_preserve_only_explicit_fallbacks(self):
        result = PlaybackStatus.from_mpd(
            {}, current_volume=73, current_mixramp_db=-18.0)
        self.assertEqual(result.state, "stop")
        self.assertEqual(result.volume, 73)
        self.assertEqual(result.mixramp_db, -18.0)
        self.assertEqual(result.queue_pos, -1)
        self.assertEqual(result.song_id, -1)
        self.assertFalse(result.mixramp_delay_on)

    def test_malformed_daemon_values_do_not_escape(self):
        result = PlaybackStatus.from_mpd({
            "elapsed": "bad", "duration": object(), "volume": "loud",
            "song": [], "songid": "none", "xfade": None,
            "bitrate": float("inf"), "mixrampdb": "bad",
            "mixrampdelay": "nan",
        }, current_volume=61, current_mixramp_db=-12.5)
        self.assertEqual(result.elapsed, 0.0)
        self.assertEqual(result.duration, 0.0)
        self.assertEqual(result.volume, 61)
        self.assertEqual(result.queue_pos, -1)
        self.assertEqual(result.bitrate_kbps, 0)
        self.assertEqual(result.mixramp_db, -12.5)
        self.assertFalse(result.mixramp_delay_on)

    def test_fade_mode_retains_local_state_and_disables_daemon_mixramp(self):
        result = reconcile_mixramp(
            delay_on=True, mix_style="fade", dj_active=False,
            automix_on=False)
        self.assertEqual((False, False, True), (
            result.mixramp_on, result.automix_on,
            result.disable_daemon_delay))

    def test_dj_transition_retains_local_state_without_daemon_mutation(self):
        result = reconcile_mixramp(
            delay_on=False, mix_style="blend", dj_active=True,
            automix_on=True)
        self.assertEqual((True, True, False), (
            result.mixramp_on, result.automix_on,
            result.disable_daemon_delay))

    def test_idle_blend_mode_adopts_daemon_switch(self):
        for delay_on in (False, True):
            with self.subTest(delay_on=delay_on):
                result = reconcile_mixramp(
                    delay_on=delay_on, mix_style="blend", dj_active=False,
                    automix_on=not delay_on)
                self.assertEqual((delay_on, delay_on, False), (
                    result.mixramp_on, result.automix_on,
                    result.disable_daemon_delay))

    def test_heartbeat_requires_both_mpd_mappings(self):
        normalize = lambda song: {"file": song["file"]}
        self.assertIsNone(PlaybackHeartbeat.from_mpd(
            None, {}, normalize_song=normalize))
        self.assertIsNone(PlaybackHeartbeat.from_mpd(
            {}, None, normalize_song=normalize))
        self.assertIsNone(PlaybackHeartbeat.from_mpd(
            {}, {"broken": True}, normalize_song=normalize))

    def test_stopped_heartbeat_accepts_a_verified_empty_current_song(self):
        result = PlaybackHeartbeat.from_mpd(
            {"state": "stop", "song": "-1"}, {},
            normalize_song=lambda song: dict(song))
        self.assertIsNotNone(result)
        self.assertEqual("stop", result.status.state)
        self.assertEqual({}, result.song)


if __name__ == "__main__":
    unittest.main()
