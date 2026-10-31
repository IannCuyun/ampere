import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ampere.playhistory import PlayHistoryRepository


class PlayHistoryRepositoryTests(unittest.TestCase):
    def test_missing_log_is_an_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = PlayHistoryRepository(Path(directory) / "missing.jsonl")
            snapshot = repository.snapshot()
            self.assertEqual(snapshot.entries, ())
            self.assertEqual(dict(snapshot.first_played), {})

    def test_append_preserves_the_existing_jsonl_schema_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "playlog.jsonl"
            repository = PlayHistoryRepository(path, clock=lambda: 1234)
            self.assertTrue(repository.append("Música/Señal.flac"))
            record = json.loads(path.read_text())
            self.assertEqual(record, {"f": "Música/Señal.flac", "t": 1234})
            self.assertEqual(repository.snapshot().entries,
                             ((1234, "Música/Señal.flac"),))

    def test_reader_skips_corruption_and_indexes_the_earliest_play(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playlog.jsonl"
            path.write_text(
                '{"f":"a.flac","t":300}\n'
                'not json\n'
                '{"f":"a.flac","t":100}\n'
                '{"f":"","t":200}\n'
                '[]\n'
                '{"f":"b.flac","t":"250","future":true}\n')
            snapshot = PlayHistoryRepository(path).snapshot()
            self.assertEqual(snapshot.entries, (
                (300, "a.flac"), (100, "a.flac"), (250, "b.flac")))
            self.assertEqual(dict(snapshot.first_played),
                             {"a.flac": 100, "b.flac": 250})

    def test_snapshot_refreshes_after_internal_and_external_appends(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playlog.jsonl"
            repository = PlayHistoryRepository(path)
            repository.append("a.flac", played_at=10)
            first = repository.snapshot()
            self.assertIs(first, repository.snapshot())
            with path.open("a") as stream:
                stream.write('{"f":"b.flac","t":20}\n')
            second = repository.snapshot()
            self.assertIsNot(first, second)
            self.assertEqual(second.entries,
                             ((10, "a.flac"), (20, "b.flac")))

    def test_failed_append_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_file = Path(directory) / "not-a-directory"
            parent_file.write_text("occupied")
            repository = PlayHistoryRepository(parent_file / "playlog.jsonl")
            self.assertFalse(repository.append("a.flac", played_at=10))

    def test_successful_append_syncs_the_record_before_returning(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = PlayHistoryRepository(
                Path(directory) / "playlog.jsonl")
            with patch("ampere.playhistory.os.fsync") as sync:
                self.assertTrue(repository.append("a.flac", played_at=10))
            self.assertEqual(2, sync.call_count)

    def test_transient_signature_failure_preserves_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playlog.jsonl"
            repository = PlayHistoryRepository(path)
            repository.append("a.flac", played_at=10)
            verified = repository.snapshot()

            with patch("ampere.playhistory.Path.stat",
                       side_effect=PermissionError("temporarily unavailable")):
                unavailable = repository.snapshot()

            self.assertIs(unavailable, verified)
            self.assertEqual(unavailable.entries, ((10, "a.flac"),))


if __name__ == "__main__":
    unittest.main()
