import unittest
from unittest.mock import patch

from ampere.memory import release_unused_heap


class MemoryReleaseTests(unittest.TestCase):
    def test_requests_process_allocator_trim(self):
        with patch("ampere.memory.ctypes.CDLL") as library:
            library.return_value.malloc_trim.return_value = 1

            self.assertTrue(release_unused_heap())

        library.assert_called_once_with(None)
        library.return_value.malloc_trim.assert_called_once_with(0)

    def test_degrades_when_trim_is_unavailable(self):
        with patch("ampere.memory.ctypes.CDLL", side_effect=OSError):
            self.assertFalse(release_unused_heap())


if __name__ == "__main__":
    unittest.main()
