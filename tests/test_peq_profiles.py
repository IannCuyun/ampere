import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

from ampere.peq import (EqManager, _migrate_profiles, _read_genre_config,
                       _read_profile,
                       _validated_profile)


class SignalStub:
    def __init__(self):
        self.messages = []

    def emit(self, message=None):
        self.messages.append(message)


class EqProfileMigrationTests(unittest.TestCase):
    def test_migrates_valid_profiles_without_overwriting_user_copy(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / "legacy", root / "user"
            source.mkdir()
            (source / "device.json").write_text(json.dumps({"active": "Old"}))

            self.assertEqual(_migrate_profiles(source, destination), 1)
            (destination / "device.json").write_text(json.dumps({"active": "User"}))
            self.assertEqual(_migrate_profiles(source, destination), 0)
            self.assertEqual(
                json.loads((destination / "device.json").read_text())["active"],
                "User")

    def test_skips_corrupt_legacy_profile(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / "legacy", root / "user"
            source.mkdir()
            (source / "broken.json").write_text("{")
            self.assertEqual(_migrate_profiles(source, destination), 0)
            self.assertFalse((destination / "broken.json").exists())

    def test_partial_profile_falls_back_to_safe_default(self):
        profile = _validated_profile({"active": "missing", "variants": {}})
        self.assertIn("Default", profile["variants"])
        self.assertEqual(profile["active"], "Default")

    def test_invalid_variants_are_dropped_without_losing_valid_ones(self):
        profile = _validated_profile({
            "active": "broken",
            "variants": {
                "broken": {"preamp": 2},
                "valid": {"preamp": -1, "bands": []},
            },
        })
        self.assertEqual(profile["active"], "valid")
        self.assertEqual(list(profile["variants"]), ["valid"])

    def test_validation_preserves_newer_document_and_variant_fields(self):
        profile = _validated_profile({
            "active": "Default", "future_document": {"enabled": True},
            "variants": {"Default": {
                "preamp": -1, "bands": [], "future_variant": 42}},
        })
        self.assertEqual({"enabled": True}, profile["future_document"])
        self.assertEqual(42, profile["variants"]["Default"]["future_variant"])

    def test_corrupt_profile_load_retains_exact_recovery_text(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "device.json")
            original = '{"active":"HD 650", broken'
            path.write_text(original)
            loaded = _read_profile(path)
            self.assertEqual(original, loaded.corrupt_text)
            self.assertIn("Default", loaded.profile["variants"])

    def test_unreadable_profile_load_records_write_block(self):
        with patch("ampere.peq.Path.read_text",
                   side_effect=PermissionError("denied")):
            loaded = _read_profile(Path("device.json"))
        self.assertIn("denied", loaded.error)

    def test_genre_config_load_preserves_valid_fields_and_corrupt_text(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "genre-eq.json")
            path.write_text('{"enabled":true,"future":{"mode":2}}')
            loaded = _read_genre_config(path)
            self.assertTrue(loaded.value["enabled"])
            self.assertEqual({"mode": 2}, loaded.value["future"])

            original = '{"enabled":'
            path.write_text(original)
            loaded = _read_genre_config(path)
            self.assertEqual({}, loaded.value)
            self.assertEqual(original, loaded.corrupt_text)

    def test_unreadable_genre_config_records_write_block(self):
        with patch("ampere.peq.Path.read_text",
                   side_effect=PermissionError("denied")):
            loaded = _read_genre_config(Path("genre-eq.json"))
        self.assertIn("denied", loaded.error)


class EqPersistenceTests(unittest.TestCase):
    def test_failure_warning_is_deduplicated_and_success_rearms_it(self):
        manager = type("EqHarness", (), {})()
        manager._persistence_failed = False
        manager.errorOccurred = SignalStub()
        with patch("ampere.peq.atomic_write_json", side_effect=[
                OSError("read-only"), OSError("read-only"), None,
                OSError("read-only")]):
            outcomes = [EqManager._persist_json(manager, Path("eq.json"), {})
                        for _ in range(4)]

        self.assertEqual([False, False, True, False], outcomes)
        self.assertEqual(2, len(manager.errorOccurred.messages))
        self.assertIn("check storage permissions",
                      manager.errorOccurred.messages[-1])

    def test_explicit_save_clears_dirty_only_after_durable_success(self):
        manager = type("EqHarness", (), {})()
        manager._profile = {"variants": {"Default": {}}, "tone": {}}
        manager._editing = "Default"
        manager._preamp = -2.0
        manager._bands = [{"type": "LS"}, {"type": "HS"}]
        manager._tone = {"bass": 1.0, "treble": 0.0, "balance": 0.0}
        manager._dirty = True
        manager._profile_path = lambda: Path("eq.json")
        manager.changed = SignalStub()
        manager._persist_json = lambda _path, _value: False

        EqManager.saveProfile(manager)
        self.assertTrue(manager._dirty)
        self.assertEqual(1, len(manager.changed.messages))

        manager._persist_json = lambda _path, _value: True
        EqManager.saveProfile(manager)
        self.assertFalse(manager._dirty)
        self.assertEqual(2, len(manager.changed.messages))

    def test_corrupt_profile_is_backed_up_exactly_before_replacement(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "device.json")
            original = "{broken profile"
            manager = type("EqHarness", (), {})()
            manager._profile_source_path = path
            manager._profile_corrupt_text = original
            manager._profile_read_error = ""
            manager._persistence_failed = False
            manager.errorOccurred = SignalStub()

            self.assertTrue(EqManager._persist_json(
                manager, path, {"active": "Default", "variants": {}}))

            backups = list(Path(tmp).glob("device.json.corrupt-*.bak"))
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_text())

    def test_unreadable_profile_blocks_default_replacement(self):
        manager = type("EqHarness", (), {})()
        manager._profile_source_path = Path("device.json")
        manager._profile_corrupt_text = None
        manager._profile_read_error = "denied"
        manager._persistence_failed = False
        manager.errorOccurred = SignalStub()

        with patch("ampere.peq.atomic_write_json") as write:
            self.assertFalse(EqManager._persist_json(
                manager, Path("device.json"), {}))

        write.assert_not_called()

    def test_genre_config_backup_precedes_write_and_preserves_newer_fields(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "genre-eq.json")
            manager = type("EqHarness", (), {})()
            manager._profile_source_path = None
            manager._genre_config_corrupt_text = '{"enabled": broken'
            manager._genre_config_read_error = ""
            manager._persistence_failed = False
            manager.errorOccurred = SignalStub()
            value = {"enabled": True, "future": {"mode": 2}}

            with patch("ampere.peq.GENRE_CFG", path):
                self.assertTrue(EqManager._persist_json(manager, path, value))

            backups = list(Path(tmp).glob("genre-eq.json.corrupt-*.bak"))
            self.assertEqual(1, len(backups))
            self.assertEqual('{"enabled": broken', backups[0].read_text())
            self.assertEqual(value, json.loads(path.read_text()))

    def test_unreadable_genre_config_blocks_replacement(self):
        manager = type("EqHarness", (), {})()
        manager._profile_source_path = None
        manager._genre_config_corrupt_text = None
        manager._genre_config_read_error = "denied"
        manager._persistence_failed = False
        manager.errorOccurred = SignalStub()

        with patch("ampere.peq.GENRE_CFG", Path("genre-eq.json")), \
                patch("ampere.peq.atomic_write_json") as write:
            self.assertFalse(EqManager._persist_json(
                manager, Path("genre-eq.json"), {"enabled": True}))

        write.assert_not_called()


class EqDegradedModeTests(unittest.TestCase):
    def test_startup_contains_eq_failures_and_attempts_every_boundary(self):
        manager = type("EqHarness", (), {})()
        manager._runtime_failed = False
        manager._runtime_message = ""
        manager.errorOccurred = SignalStub()
        manager.ensure_chain = lambda: (_ for _ in ()).throw(
            OSError("read-only config"))
        manager.refreshes = 0
        manager._refresh_default_sink = lambda **_kwargs: setattr(
            manager, "refreshes", manager.refreshes + 1)
        manager.watcher_attempts = 0
        manager._start_watcher = lambda: setattr(
            manager, "watcher_attempts", manager.watcher_attempts + 1)
        manager._report_runtime_failure = lambda message: (
            EqManager._report_runtime_failure(manager, message))

        self.assertFalse(EqManager.start(manager))

        self.assertEqual(1, manager.refreshes)
        self.assertEqual(1, manager.watcher_attempts)
        self.assertEqual(1, len(manager.errorOccurred.messages))
        self.assertIn("playback will continue",
                      manager.errorOccurred.messages[0])
        EqManager.publishRuntimeFailure(manager)
        self.assertEqual(2, len(manager.errorOccurred.messages))

    def test_live_push_contains_tool_failure_and_rearms_after_success(self):
        manager = type("EqHarness", (), {})()
        manager._node_id = 5
        manager._preamp = 0.0
        manager._enabled = True
        manager._tone = {"bass": 0.0, "treble": 0.0, "balance": 0.0}
        manager._bands = [
            {"type": "LS", "freq": 80.0, "q": .707, "gain": 0.0},
            {"type": "HS", "freq": 10000.0, "q": .707, "gain": 0.0},
        ]
        manager._sink = "device"
        manager._runtime_failed = False
        manager._runtime_message = ""
        manager.errorOccurred = SignalStub()
        manager._find_node_id = lambda: 5
        manager._report_runtime_failure = lambda message: (
            EqManager._report_runtime_failure(manager, message))
        manager._mark_runtime_recovered = lambda: (
            EqManager._mark_runtime_recovered(manager))

        with patch("ampere.peq.subprocess.run", side_effect=[
                OSError("missing pw-cli"), OSError("missing pw-cli"),
                SimpleNamespace(returncode=0, stderr=""),
                OSError("missing pw-cli")]):
            for _ in range(4):
                EqManager._push_now(manager)

        self.assertEqual(2, len(manager.errorOccurred.messages))
        self.assertIsNone(manager._node_id)
        self.assertTrue(manager._runtime_failed)


if __name__ == "__main__":
    unittest.main()


class RouteHealingTests(unittest.TestCase):
    """The EQ chain must never be bolted to a device.

    Pinning `ampere_eq_out` with `target.object` outranks the default sink, so
    after switching outputs the chain stayed on the previous device and Ampere
    "refused" to move to the headphones (Iann, 2026-08-22). mpd.conf's own
    note is the contract: the chain FOLLOWS the default sink.
    """

    def source(self):
        return (ROOT / "ampere/peq.py").read_text(encoding="utf-8")

    def test_the_chain_output_is_never_pinned(self):
        body = self.source().split("def _heal_mpd_route", 1)[1] \
                            .split("def _release_target", 1)[0]
        # the chain output is released and moved, never targeted
        self.assertIn("self._release_target(chain_out_id)", body)
        self.assertNotIn("self._set_target(chain_out_id", body)

    def test_a_stale_pin_is_actively_cleared(self):
        source = self.source()
        self.assertIn("def _release_target(node_id)", source)
        self.assertIn('for key in ("target.object", "target.node")', source)
        self.assertIn('"-1"', source)

    def test_the_default_sink_is_read_fresh_at_heal_time(self):
        # a cached value can lag a concurrent switch and undo it
        body = self.source().split("def _heal_mpd_route", 1)[1] \
                            .split("def _release_target", 1)[0]
        self.assertIn('"pactl", "get-default-sink"', body)
        self.assertNotIn("default_name = self._sink", body)

    def test_mpd_is_still_held_on_the_chain(self):
        body = self.source().split("def _heal_mpd_route", 1)[1] \
                            .split("def _release_target", 1)[0]
        self.assertIn("self._set_target(mpd_id, chain_id)", body)

    def test_the_chain_never_feeds_itself(self):
        body = self.source().split("def _heal_mpd_route", 1)[1] \
                            .split("def _release_target", 1)[0]
        self.assertIn("if default_name == CHAIN_NAME:", body)
