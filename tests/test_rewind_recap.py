import unittest

from ampere.mpdclient import Backend


class RewindStub:
    def __init__(self, result):
        self.result = result

    def recap_files(self, entries, key):
        return self.result


class RewindRecapTests(unittest.TestCase):
    def backend(self, recap, save_result=True):
        backend = type("RewindAdapter", (), {})()
        backend._rewind = RewindStub(recap)
        backend._playlog_entries = lambda: [(1, "song.flac")]
        backend.saved = []
        backend._request_generated_playlist_save = lambda purpose, name, files, **context: (
            backend.saved.append((purpose, name, list(files), context))
            or save_result)
        return backend

    def test_success_starts_the_generated_playlist_worker(self):
        backend = self.backend(("Jul 2026", ["song.flac"]))

        result = Backend.saveRecap(backend, "2026-07")

        self.assertTrue(result)
        self.assertEqual(
            [("recap", "Rewind — Jul 2026", ["song.flac"],
              {"key": "2026-07"})], backend.saved)

    def test_failed_transaction_returns_no_success_name(self):
        backend = self.backend(("Jul 2026", ["song.flac"]), False)

        result = Backend.saveRecap(backend, "2026-07")

        self.assertFalse(result)

    def test_empty_chapter_never_attempts_a_playlist_write(self):
        backend = self.backend(("Jul 2026", []))

        result = Backend.saveRecap(backend, "2026-07")

        self.assertFalse(result)
        self.assertEqual([], backend.saved)


if __name__ == "__main__":
    unittest.main()
