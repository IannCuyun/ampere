import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ampere.dj.planner import DjPlannerMixin
from ampere.dj.votes import DjVotesRepository
from ampere.mpdclient import Backend


class SignalStub:
    def __init__(self):
        self.messages = []

    def emit(self, message=None):
        self.messages.append(message)


class DjVotesRepositoryTests(unittest.TestCase):
    def test_load_preserves_unknown_fields_and_migrates_style_timestamp(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "votes.json")
            path.write_text(json.dumps({
                "style_downs": {"mix": 3},
                "future": {"weight": 0.75},
            }))
            loaded = DjVotesRepository(path).load()

            self.assertEqual({"weight": 0.75}, loaded["future"])
            self.assertEqual(path.stat().st_mtime,
                             loaded["style_down_ts"]["mix"])
            self.assertEqual({}, loaded["cue_bans"])

    def test_malformed_document_is_backed_up_exactly_before_replacement(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "votes.json")
            original = '{"pairs": broken'
            path.write_text(original)
            repository = DjVotesRepository(path)
            votes = repository.load()
            votes["pairs"]["a|b"] = -1

            self.assertTrue(repository.save(votes))

            backups = list(Path(tmp).glob("votes.json.corrupt-*.bak"))
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_text())
            self.assertEqual(-1, json.loads(path.read_text())["pairs"]["a|b"])

    def test_wrong_field_shape_is_recoverable_corruption(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "votes.json")
            original = '{"pairs":[],"future":1}'
            path.write_text(original)
            repository = DjVotesRepository(path)

            self.assertEqual({}, repository.load()["pairs"])
            self.assertTrue(repository.save(repository.load()))
            self.assertEqual(original, next(
                Path(tmp).glob("votes.json.corrupt-*.bak")).read_text())

    def test_unreadable_document_blocks_fallback_write(self):
        repository = DjVotesRepository(Path("votes.json"))
        with patch("ampere.dj.votes.Path.read_text",
                   side_effect=PermissionError("denied")):
            votes = repository.load()
        with patch("ampere.dj.votes.atomic_write_json") as write:
            self.assertFalse(repository.save(votes))
        write.assert_not_called()


class DjVotesPlannerTests(unittest.TestCase):
    def test_save_failure_warning_deduplicates_and_rearms(self):
        manager = type("DjHarness", (DjPlannerMixin,), {})()
        manager.VOTES_PATH = Path("votes.json")
        manager._dj_votes_cache = {"pairs": {}}
        manager.errorOccurred = SignalStub()
        repository = type("Repository", (), {})()
        outcomes = iter((False, False, True, False))
        repository.save = lambda _value: next(outcomes)
        manager._dj_votes_repository = repository

        results = [manager._dj_save_votes() for _ in range(4)]

        self.assertEqual([False, False, True, False], results)
        self.assertEqual(2, len(manager.errorOccurred.messages))
        self.assertIn("DJ feedback could not be saved",
                      manager.errorOccurred.messages[-1])

    def test_explicit_cue_nudge_saves_before_reporting_success(self):
        manager = type("DjHarness", (DjPlannerMixin,), {})()
        manager._dj_votes_cache = {
            "cue_bans": {}, "pairs": {}, "style_downs": {},
            "strikes": {}, "style_fires": {}, "seam_samples": [],
            "style_down_ts": {},
        }
        manager._dj_cue_cache = {"song.flac": ({}, 1)}
        manager._dj_cues = lambda _file: {"in": [(12.5, 0.9)]}
        manager._dj_pick = lambda _cues, _side: 12.5
        manager.saved = 0
        manager._dj_save_votes = lambda: (
            setattr(manager, "saved", manager.saved + 1) or True)
        manager._dj_plan_key = ("old", "plan")
        manager._dj_bridge_done = {("a", "b"): "skip"}
        manager.refreshes = 0
        manager.refreshStatus = lambda: setattr(
            manager, "refreshes", manager.refreshes + 1)
        manager.statusChanged = SignalStub()
        manager.errorOccurred = SignalStub()

        self.assertTrue(manager._dj_nudge_cue("song.flac", "in"))

        self.assertEqual(1, manager.saved)
        self.assertEqual([12.5], manager._dj_votes_cache[
            "cue_bans"]["song.flac"]["in"])
        self.assertIsNone(manager._dj_plan_key)
        self.assertEqual({}, manager._dj_bridge_done)
        self.assertIn("next drop", manager.errorOccurred.messages[-1])

    def test_failed_cue_nudge_save_does_not_report_durable_success(self):
        manager = type("DjHarness", (DjPlannerMixin,), {})()
        manager._dj_votes_cache = {
            "cue_bans": {}, "pairs": {}, "style_downs": {},
            "strikes": {}, "style_fires": {}, "seam_samples": [],
            "style_down_ts": {},
        }
        manager._dj_cue_cache = {}
        manager._dj_cues = lambda _file: {"out": [(90.0, 0.8)]}
        manager._dj_pick = lambda _cues, _side: 90.0
        manager._dj_save_votes = lambda: False
        manager._dj_plan_key = None
        manager._dj_bridge_done = {}
        manager.refreshStatus = lambda: None
        manager.statusChanged = SignalStub()
        manager.errorOccurred = SignalStub()

        self.assertFalse(manager._dj_nudge_cue("song.flac", "out"))
        self.assertEqual([], manager.errorOccurred.messages)

    def test_set_history_worker_coalesces_to_latest_snapshot(self):
        manager = type("DjHarness", (DjPlannerMixin,), {})()
        manager._dj_set_log = {"started": 42, "songs": ["song.flac"]}
        manager.errorOccurred = SignalStub()
        manager._dj_set_save_lock = threading.Lock()
        manager._dj_set_save_busy = False
        manager._dj_set_save_pending = None
        launched = []
        results = []
        manager._start_worker = lambda work, args=(), **_kwargs: (
            launched.append((work, args)) or True)
        manager._djSetSaveReady = type("Signal", (), {
            "emit": lambda self, success: results.append(success),
        })()

        self.assertTrue(manager._dj_save_set())
        manager._dj_set_log["transitions"] = [{"style": "slam"}]
        self.assertTrue(manager._dj_save_set())
        with patch("ampere.dj.planner.save_set_snapshot",
                   side_effect=[True, True]) as save:
            work, args = launched[0]
            work(*args)

        self.assertEqual(2, save.call_count)
        self.assertNotIn("transitions", save.call_args_list[0].args[1])
        self.assertEqual([{"style": "slam"}],
                         save.call_args_list[1].args[1]["transitions"])
        self.assertEqual([True], results)
        self.assertFalse(manager._dj_set_save_busy)

    def test_set_history_failure_warns_once_and_success_rearms(self):
        manager = type("DjHarness", (DjPlannerMixin,), {})()
        manager.errorOccurred = SignalStub()

        outcomes = [Backend._on_dj_set_save_ready(manager, value)
                    for value in (False, False, True, False)]

        self.assertEqual([False, False, True, False], outcomes)
        self.assertEqual(2, len(manager.errorOccurred.messages))
        self.assertIn("Replay Last Set",
                      manager.errorOccurred.messages[-1])


if __name__ == "__main__":
    unittest.main()
