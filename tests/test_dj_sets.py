import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ampere.dj.sets import (load_saved_sets, save_set_snapshot,
                           select_replayable_set)


class SavedSetCatalogTests(unittest.TestCase):
    def test_skips_newest_damaged_entry_and_keeps_unknown_fields(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "1.json"
            newer = root / "2.json"
            older.write_text(json.dumps({
                "songs": ["valid.flac"], "future": {"room": 2}}))
            newer.write_text('{"songs":')
            os.utime(older, (10, 10))
            os.utime(newer, (20, 20))

            catalog = load_saved_sets(root)

            self.assertEqual(1, catalog.invalid)
            self.assertEqual(1, len(catalog.sets))
            self.assertEqual({"room": 2}, catalog.sets[0]["future"])

    def test_rejects_structurally_empty_or_non_object_documents(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty.json").write_text('{"songs":["",null]}')
            (root / "array.json").write_text('["song.flac"]')

            catalog = load_saved_sets(root)

            self.assertEqual(2, catalog.invalid)
            self.assertEqual((), catalog.sets)

    def test_unavailable_catalog_is_distinct_from_missing_catalog(self):
        self.assertEqual((), load_saved_sets(Path("missing-history")).sets)
        with patch("ampere.dj.sets.Path.iterdir",
                   side_effect=PermissionError("denied")):
            catalog = load_saved_sets(Path("history"))
        self.assertIn("denied", catalog.error)


class ReplaySelectionTests(unittest.TestCase):
    def test_falls_back_from_newest_unavailable_set(self):
        candidates = (
            {"songs": ["gone.flac"], "label": "new"},
            {"songs": ["here.flac", "also-gone.flac"], "label": "older"},
        )

        selected = select_replayable_set(
            candidates, {"here.flac"}, absolute_exists=lambda _file: False)

        self.assertEqual("older", selected.data["label"])
        self.assertEqual(("here.flac",), selected.songs)

    def test_keeps_existing_absolute_sting_and_relative_files_without_index(self):
        candidates = ({"songs": ["/tmp/sting.wav", "room/song.flac"]},)

        selected = select_replayable_set(
            candidates, set(), absolute_exists=lambda path: path == "/tmp/sting.wav")

        self.assertEqual(("/tmp/sting.wav", "room/song.flac"), selected.songs)


class SavedSetPersistenceTests(unittest.TestCase):
    def test_durable_snapshot_keeps_latest_retention_window(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for started in range(1, 5):
                self.assertTrue(save_set_snapshot(
                    root, {"started": started, "songs": [f"{started}.flac"]},
                    retain=2))

            self.assertEqual(["3.json", "4.json"], sorted(
                path.name for path in root.glob("*.json")))

    def test_write_failure_is_reported_without_retention(self):
        with patch("ampere.dj.sets.atomic_write_json",
                   side_effect=OSError("read-only")), \
                patch("ampere.dj.sets.Path.glob") as glob:
            self.assertFalse(save_set_snapshot(
                Path("sets"), {"started": 1, "songs": ["a.flac"]}))
        glob.assert_not_called()


if __name__ == "__main__":
    unittest.main()
