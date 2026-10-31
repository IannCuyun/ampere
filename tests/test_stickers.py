import unittest

from ampere.mpdclient import Backend
from ampere.stickers import (
    ExclusiveStickerResult, PlayRecordResult, StickerRepository,
    StickerReadResult, sticker_value,
)


class Store:
    def __init__(self):
        self.rows = {
            "playCount": [
                {"file": "a.flac", "sticker": "playCount=4"},
                {"file": "bad.flac", "sticker": "playCount=nope"},
            ]
        }
        self.scalar = {("a.flac", "playCount"): "playCount=4"}
        self.writes = []
        self.fail_names = set()

    def read(self, command, *args, default=None, **_kwargs):
        if command == "sticker_find":
            return self.rows.get(args[2], [])
        if command == "sticker_get":
            return self.scalar.get((args[1], args[2]), default)
        raise AssertionError(command)

    def write(self, command, *args, **kwargs):
        self.writes.append((command, args, kwargs))
        name = args[2]
        if name in self.fail_names:
            return False
        file = args[1]
        if command == "sticker_set":
            self.scalar[(file, name)] = f"{name}={args[3]}"
        elif command == "sticker_delete":
            self.scalar.pop((file, name), None)
        return True


class StickerRepositoryTests(unittest.TestCase):
    def repository(self, errors=None):
        store = Store()
        client = object()
        return StickerRepository(
            read=store.read, write=store.write, client=client,
            clock=lambda: 1234,
            error=(errors if errors is not None else lambda _message: None)), store, client

    def test_decodes_prefixed_and_plain_values(self):
        self.assertEqual("7", sticker_value("rating=7"))
        self.assertEqual("7", sticker_value("7"))

    def test_maps_use_reconnecting_read_and_typed_map_skips_bad_values(self):
        repository, _store, _client = self.repository()
        self.assertEqual({"a.flac": "4", "bad.flac": "nope"},
                         repository.values("playCount"))
        self.assertEqual({"a.flac": 4}, repository.integers("playCount"))

    def test_worker_map_uses_the_supplied_thread_local_client(self):
        repository, _store, _client = self.repository()
        worker = type("Worker", (), {"sticker_find": lambda *_args: [
            {"file": "worker.flac", "sticker": "rating=9"}]})()
        self.assertEqual({"worker.flac": "9"},
                         repository.values("rating", worker))

    def test_unavailable_family_retains_the_last_verified_snapshot(self):
        errors = []
        repository, store, _client = self.repository(errors.append)
        expected = repository.values("playCount")
        store.rows["playCount"] = None

        self.assertEqual(expected, repository.values("playCount"))
        self.assertEqual(1, len(errors))

    def test_malformed_family_cannot_replace_a_verified_snapshot(self):
        repository, store, _client = self.repository()
        expected = repository.values("playCount")
        store.rows["playCount"] = [{"file": "missing-sticker.flac"}]

        self.assertEqual(expected, repository.values("playCount"))

    def test_failure_warning_deduplicates_until_all_families_recover(self):
        errors = []
        repository, store, _client = self.repository(errors.append)
        store.rows["playCount"] = None
        store.rows["rating"] = None

        repository.values("playCount")
        repository.values("playCount")
        repository.values("rating")
        self.assertEqual(1, len(errors))

        store.rows["playCount"] = []
        repository.values("playCount")
        repository.values("rating")
        self.assertEqual(1, len(errors))

        store.rows["rating"] = []
        repository.values("rating")
        store.rows["playCount"] = None
        repository.values("playCount")
        self.assertEqual(2, len(errors))

    def test_worker_failure_uses_the_shared_verified_snapshot(self):
        repository, store, _client = self.repository()
        expected = repository.values("playCount")

        class Worker:
            def sticker_find(self, *_args):
                raise OSError("offline")

        self.assertEqual(expected, repository.values("playCount", Worker()))

    def test_family_result_distinguishes_no_baseline_from_retained_empty(self):
        repository, store, _client = self.repository()
        store.rows["joi_taildb"] = None

        first_failure = repository.values_result("joi_taildb")
        store.rows["joi_taildb"] = []
        verified_empty = repository.values_result("joi_taildb")
        store.rows["joi_taildb"] = None
        retained_empty = repository.values_result("joi_taildb")

        self.assertFalse(first_failure.available)
        self.assertFalse(first_failure.retained)
        self.assertTrue(verified_empty.available)
        self.assertFalse(retained_empty.available)
        self.assertTrue(retained_empty.retained)
        self.assertEqual({}, retained_empty.values)

    def test_record_play_increments_both_stickers_and_ignores_bridges(self):
        repository, store, _client = self.repository()
        self.assertEqual(
            PlayRecordResult(True, 1234, True, 5),
            repository.record_play("a.flac"))
        self.assertEqual([
            ("sticker_set", ("song", "a.flac", "playCount", "5"),
             {"quiet": True}),
            ("sticker_set", ("song", "a.flac", "lastPlayed", "1234"),
             {"quiet": True}),
        ], store.writes)
        self.assertEqual(
            PlayRecordResult(False),
            repository.record_play("/tmp/bridge.flac"))

    def test_record_play_reports_partial_sticker_persistence(self):
        repository, store, _client = self.repository()
        store.fail_names.add("playCount")

        result = repository.record_play("a.flac")

        self.assertEqual(PlayRecordResult(True, 1234, False), result)
        self.assertEqual(2, len(store.writes))

    def test_record_play_never_overwrites_an_unavailable_count_with_one(self):
        repository, store, _client = self.repository()
        repository._observe = lambda *_args, **_kwargs: StickerReadResult(
            False, None)

        result = repository.record_play("a.flac")

        self.assertEqual(PlayRecordResult(True, 1234, False), result)
        self.assertEqual([], store.writes)

    def test_exclusive_sticker_clears_only_existing_sibling_values(self):
        repository, store, _client = self.repository()
        store.scalar.update({
            ("old.flac", "joi_pref"): "joi_pref=1",
            ("other.flac", "joi_pref"): "joi_pref=legacy",
        })

        result = repository.set_exclusive(
            ["new.flac", "old.flac", "other.flac"],
            "new.flac", "joi_pref")

        self.assertEqual(ExclusiveStickerResult(True), result)
        self.assertEqual("joi_pref=1",
                         store.scalar[("new.flac", "joi_pref")])
        self.assertNotIn(("old.flac", "joi_pref"), store.scalar)
        self.assertNotIn(("other.flac", "joi_pref"), store.scalar)

    def test_exclusive_sticker_rolls_back_a_partial_commit(self):
        repository, store, _client = self.repository()
        store.scalar[("old.flac", "joi_pref")] = "joi_pref=1"
        original_write = store.write

        def fail_old_delete(command, *args, **kwargs):
            if command == "sticker_delete" and args[0:3] == (
                    "song", "old.flac", "joi_pref"):
                store.writes.append((command, args, kwargs))
                return False
            return original_write(command, *args, **kwargs)

        store.write = fail_old_delete
        repository._write = store.write

        result = repository.set_exclusive(
            ["new.flac", "old.flac"], "new.flac", "joi_pref")

        self.assertEqual(ExclusiveStickerResult(False, True), result)
        self.assertNotIn(("new.flac", "joi_pref"), store.scalar)
        self.assertEqual("joi_pref=1",
                         store.scalar[("old.flac", "joi_pref")])


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class _RecordStickers:
    def __init__(self, results):
        self.results = iter(results)

    def record_play(self, _file):
        return next(self.results)


class _History:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def append(self, file, *, played_at):
        self.calls.append((file, played_at))
        return next(self.results)


class PlayRecordPublicationTests(unittest.TestCase):
    def test_verified_count_write_advances_cached_consumers_and_refreshes(self):
        backend = type("BackendHarness", (), {})()
        backend._stickers = _RecordStickers([
            PlayRecordResult(True, 10, True, 6),
        ])
        backend._play_history = _History([True])
        backend._play_record_failed = False
        backend._library_playcounts = {"song.flac": 5}
        backend._search_catalog = type("Catalog", (), {
            "replace_playcounts": lambda self, values: setattr(
                self, "counts", dict(values)),
        })()
        backend.refreshes = 0
        backend.requestLibrarySummary = lambda: setattr(
            backend, "refreshes", backend.refreshes + 1)

        Backend._publish_play_record(
            backend, "song.flac", backend._stickers.record_play("song.flac"))

        self.assertEqual(6, backend._library_playcounts["song.flac"])
        self.assertEqual(6, backend._search_catalog.counts["song.flac"])
        self.assertEqual(1, backend.refreshes)

    def test_partial_episodes_warn_once_and_success_rearms_warning(self):
        backend = type("BackendHarness", (), {})()
        backend._stickers = _RecordStickers([
            PlayRecordResult(True, 10, False),
            PlayRecordResult(True, 20, False),
            PlayRecordResult(True, 30, True),
            PlayRecordResult(True, 40, True),
        ])
        backend._play_record_failed = False
        backend.errorOccurred = _Signal()
        backend._start_next_listening_progress_job = lambda: None
        backend._publish_play_record = lambda file, result: (
            Backend._publish_play_record(backend, file, result))
        backend._report_listening_progress_failure = lambda: (
            Backend._report_listening_progress_failure(backend))

        results = [
            (PlayRecordResult(True, 10, False), True, True),
            (PlayRecordResult(True, 20, False), False, True),
            (PlayRecordResult(True, 30, True), True, True),
            (PlayRecordResult(True, 40, True), False, True),
        ]
        for record, history_saved, resume_saved in results:
            Backend._on_listening_progress_ready(backend, {
                "update": type("Update", (), {"resume_file": "song.flac"})(),
                "play_record": record,
                "history_saved": history_saved,
                "resume_saved": resume_saved,
                "resume_position": None,
            })

        self.assertEqual(2, len(backend.errorOccurred.messages))
        self.assertTrue(backend._play_record_failed)


if __name__ == "__main__":
    unittest.main()
