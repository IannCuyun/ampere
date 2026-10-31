import unittest
import tempfile
from pathlib import Path

from ampere.mpdclient import Backend
from ampere.settings import SettingsRepository, SettingsSaveResult


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class Repository:
    def __init__(self, results):
        self.results = iter(results)
        self.values = []

    def try_save(self, values):
        self.values.append(dict(values))
        return next(self.results)


class SettingsPersistenceTests(unittest.TestCase):
    def backend(self, results):
        backend = type("SettingsAdapter", (), {})()
        backend._settings = Repository(results)
        backend._settings_values = lambda: {"rating_mode": "stars"}
        backend.errorOccurred = Signal()
        return backend

    def test_failure_episode_emits_only_one_actionable_error(self):
        failure = SettingsSaveResult(False, {}, "disk full")
        backend = self.backend([failure, failure])

        self.assertFalse(Backend._save_conf(backend))
        self.assertFalse(Backend._save_conf(backend))

        self.assertEqual(1, len(backend.errorOccurred.messages))
        self.assertIn("only until Ampere closes",
                      backend.errorOccurred.messages[0])

    def test_success_resets_latch_so_a_later_failure_is_visible(self):
        failure = SettingsSaveResult(False, {}, "read only")
        success = SettingsSaveResult(True, {"rating_mode": "stars"})
        backend = self.backend([failure, success, failure])

        self.assertFalse(Backend._save_conf(backend))
        self.assertTrue(Backend._save_conf(backend))
        self.assertFalse(Backend._save_conf(backend))

        self.assertEqual(2, len(backend.errorOccurred.messages))

    def test_distinct_failure_kind_is_visible_during_same_outage(self):
        failure = SettingsSaveResult(False, {}, "read only")
        backend = self.backend([failure, failure, failure])
        rolled_back = (
            "Sound Profile could not be saved — the previous profile "
            "state was kept")

        self.assertFalse(Backend._save_conf(backend))
        self.assertFalse(Backend._save_conf(
            backend, failure_message=rolled_back))
        self.assertFalse(Backend._save_conf(
            backend, failure_message=rolled_back))

        self.assertEqual([
            "Settings could not be saved — changes apply only until "
            "Ampere closes",
            rolled_back,
        ], backend.errorOccurred.messages)

    def test_narrow_patch_preserves_newer_unrelated_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SettingsRepository(Path(directory) / "config.json")
            repository.load()
            self.assertTrue(repository.try_save({
                "rating_mode": "hearts",
                "search_history": [],
            }).success)
            self.assertTrue(repository.try_save({
                "rating_mode": "stars",
                "search_history": ["before"],
            }).success)

            result = repository.try_patch({"search_history": ["after"]})

            self.assertTrue(result.success)
            reloaded = SettingsRepository(repository.path).load()
            self.assertEqual("stars", reloaded["rating_mode"])
            self.assertEqual(["after"], reloaded["search_history"])

    def test_full_snapshot_keeps_incrementally_written_user_state(self):
        backend = type("SettingsSnapshot", (), {
            "_automix_on": True, "_mix_style": "fade", "_xfade_base": 4,
            "_autoplay_on": True, "_radio_mood": "match",
            "_remote_on": True, "_remote_token": "token",
            "_delete_remote_host": "host", "_delete_remote_root": "/music",
            "_mix_on": False, "_mix_arc": False, "_trim_on": True,
            "_dj_level": "classic", "_dj_range": "progressive",
            "_dj_mix_len": "auto", "_dj_slam_only": False,
            "_dj_seed_label": "", "_dj_shape": "arc", "_dj_minutes": 0,
            "_dj_b2b": "", "_dj_sting": True, "_replay_gain": "track",
            "_rg_on_mode": "track", "_rating_mode": "hearts",
            "_context_shuffle_mode": "smart", "_device_vols": {},
            "_search_history": ["query"],
            "_playlist_play_counts": {"Focus": 3},
            "_artist_aliases": {"Ye": "Kanye West"},
            "_sound_mixes": [{"id": "mix", "character": "dark",
                               "label": "DARK", "created": 1,
                               "files": ["track.flac"]}],
        })()

        values = Backend._settings_values(backend)

        self.assertEqual("smart", values["context_shuffle_mode"])
        self.assertEqual({"Ye": "Kanye West"}, values["artist_aliases"])
        self.assertEqual({"Focus": 3}, values["playlist_play_counts"])
        self.assertEqual("mix", values["sound_mixes"][0]["id"])


if __name__ == "__main__":
    unittest.main()
