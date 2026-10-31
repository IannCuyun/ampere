import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ampere.settings import (DEFAULTS, SettingsRepository,
                            clean_playlist_play_counts)


class SettingsRepositoryTests(unittest.TestCase):
    def test_missing_or_corrupt_document_uses_complete_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            repository = SettingsRepository(path)
            self.assertEqual(DEFAULTS, repository.load())
            path.write_text("not json")
            self.assertEqual(DEFAULTS, repository.load())

    def test_load_validates_ranges_choices_and_nested_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps({
                "mix_style": "broken",
                "crossfade_base": 99,
                "dj_minutes": 17,
                "rating_mode": "stars",
                "device_volumes": {"speakers": "82", "bad": "loud"},
            }))
            settings = SettingsRepository(path).load()
            self.assertEqual("blend", settings["mix_style"])
            self.assertEqual(15, settings["crossfade_base"])
            self.assertEqual(0, settings["dj_minutes"])
            self.assertEqual("stars", settings["rating_mode"])
            self.assertEqual({"speakers": 82}, settings["device_volumes"])

    def test_save_persists_rating_mode_and_preserves_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps({"future_option": {"enabled": True}}))
            repository = SettingsRepository(path)
            values = repository.load()
            values["rating_mode"] = "stars"
            repository.save(values)
            saved = json.loads(path.read_text())
            self.assertEqual("stars", saved["rating_mode"])
            self.assertEqual({"enabled": True}, saved["future_option"])

    def test_zero_crossfade_survives_a_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            repository = SettingsRepository(path)
            values = repository.load()
            values["crossfade_base"] = 0
            repository.save(values)
            self.assertEqual(0, SettingsRepository(path).load()["crossfade_base"])

    def test_remote_pairing_token_survives_a_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            repository = SettingsRepository(path)
            values = repository.load()
            values["remote_token"] = "persistent-pairing-token"
            repository.save(values)
            self.assertEqual("persistent-pairing-token",
                             SettingsRepository(path).load()["remote_token"])

    def test_legacy_radio_preference_migrates_to_autoplay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps({"radio_on": True}))

            settings = SettingsRepository(path).load()

            self.assertTrue(settings["autoplay_on"])

    def test_explicit_autoplay_preference_outranks_legacy_radio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps({
                "autoplay_on": False,
                "radio_on": True,
            }))

            settings = SettingsRepository(path).load()

            self.assertFalse(settings["autoplay_on"])

    def test_failed_save_preserves_document_for_a_successful_retry(self):
        attempts = []

        def write(_path, document):
            attempts.append(dict(document))
            if len(attempts) == 1:
                raise OSError("disk full")

        repository = SettingsRepository("/unused/config.json", write_json=write)
        repository._document = {"future_option": True, "rating_mode": "hearts"}

        failed = repository.try_save({"rating_mode": "stars"})
        succeeded = repository.try_save({"rating_mode": "stars"})

        self.assertFalse(failed.success)
        self.assertEqual("disk full", failed.error)
        self.assertTrue(succeeded.success)
        self.assertTrue(attempts[1]["future_option"])
        self.assertEqual("stars", attempts[1]["rating_mode"])

    def test_corrupt_document_is_snapshotted_exactly_before_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            original = '{"remote_token":"keep-me", broken'
            path.write_text(original)
            repository = SettingsRepository(path)
            values = repository.load()
            values["rating_mode"] = "stars"

            result = repository.try_save(values)

            self.assertTrue(result.success)
            backups = list(Path(tmp).glob("config.json.corrupt-*.bak"))
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_text())
            self.assertEqual("stars", json.loads(path.read_text())["rating_mode"])

    def test_unreadable_existing_document_blocks_destructive_default_save(self):
        repository = SettingsRepository("/unused/config.json")
        with patch("ampere.settings.Path.read_text",
                   side_effect=PermissionError("denied")):
            values = repository.load()

        result = repository.try_save(values)

        self.assertFalse(result.success)
        self.assertIn("refusing to overwrite", result.error)

    def test_playlist_play_counts_are_exact_bounded_positive_launches(self):
        values = clean_playlist_play_counts({
            " Night Drive ": "4",
            "Never launched": 0,
            "Negative": -3,
            "Broken": "many",
            "": 8,
        })

        self.assertEqual({"Night Drive": 4}, values)

    def test_playlist_play_counts_survive_a_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            repository = SettingsRepository(path)
            values = repository.load()
            values["playlist_play_counts"] = {"Always Rising": 7}

            repository.save(values)

            self.assertEqual(
                {"Always Rising": 7},
                SettingsRepository(path).load()["playlist_play_counts"])


if __name__ == "__main__":
    unittest.main()
