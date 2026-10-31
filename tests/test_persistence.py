import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ampere.persistence import atomic_write_json, atomic_write_text


class AtomicPersistenceTests(unittest.TestCase):
    def test_replaces_complete_text_and_leaves_no_temporary_file(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "config.json")
            target.write_text("old")
            atomic_write_text(target, "new")
            self.assertEqual(target.read_text(), "new")
            self.assertEqual(list(Path(tmp).glob(".*.tmp")), [])

    def test_failed_replace_preserves_original_file(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "config.json")
            target.write_text("valid")
            with patch("ampere.persistence.os.replace", side_effect=OSError("full")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "partial")
            self.assertEqual(target.read_text(), "valid")

    def test_json_output_is_valid_and_unicode_safe(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "state.json")
            atomic_write_json(target, {"artist": "Beyoncé"})
            self.assertEqual(json.loads(target.read_text())["artist"], "Beyoncé")

    def test_replacement_tightens_legacy_group_and_other_permissions(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "config.json")
            target.write_text("old")
            target.chmod(0o664)

            atomic_write_text(target, "new")

            self.assertEqual(0o600, target.stat().st_mode & 0o777)
            self.assertEqual("new", target.read_text())

    def test_success_syncs_file_contents_and_replaced_directory_entry(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "state.json")
            with patch("ampere.persistence.os.fsync") as sync:
                atomic_write_text(target, "durable")

            self.assertEqual(2, sync.call_count)
            self.assertEqual("durable", target.read_text())

    def test_new_nested_directories_are_synced_before_file_publication(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "one", "two", "state.json")
            with patch("ampere.persistence.os.fsync") as sync:
                atomic_write_text(target, "durable")

            # two new directory entries + temporary file + final rename
            self.assertEqual(4, sync.call_count)
            self.assertEqual("durable", target.read_text())


if __name__ == "__main__":
    unittest.main()
