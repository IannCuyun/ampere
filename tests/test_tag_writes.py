import tempfile
import threading
import unittest
from pathlib import Path

from ampere.tag_writes import tag_write_lock


class TagWriteLockTests(unittest.TestCase):
    def test_same_canonical_file_serializes_writers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "track.flac"
            path.write_bytes(b"fixture")
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()

            def first():
                with tag_write_lock(path):
                    first_entered.set()
                    release_first.wait(timeout=2)

            def second():
                first_entered.wait(timeout=2)
                with tag_write_lock(path.parent / "." / path.name):
                    second_entered.set()

            one = threading.Thread(target=first)
            two = threading.Thread(target=second)
            one.start()
            two.start()
            self.assertTrue(first_entered.wait(timeout=2))
            self.assertFalse(second_entered.wait(timeout=0.05))
            release_first.set()
            self.assertTrue(second_entered.wait(timeout=2))
            one.join(timeout=2)
            two.join(timeout=2)
            self.assertFalse(one.is_alive())
            self.assertFalse(two.is_alive())

    def test_different_files_do_not_block_each_other(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "one.flac"
            second = Path(temp) / "two.flac"
            with tag_write_lock(first):
                entered = threading.Event()

                def writer():
                    with tag_write_lock(second):
                        entered.set()

                thread = threading.Thread(target=writer)
                thread.start()
                self.assertTrue(entered.wait(timeout=2))
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
