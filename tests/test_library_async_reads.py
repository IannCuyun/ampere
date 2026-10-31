"""Library reads stay off Qt's thread: cold slots answer [] and the heavy
reads resolve through ``_start_worker`` with a caller-supplied serial."""
import ast
import inspect
import textwrap
import unittest

from ampere.library import LibraryRepository
from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class ExplodingLibrary:
    @property
    def songs(self):
        raise AssertionError("cold library read recomputed the directory")


def stub(*, directory=None):
    backend = type("ReadStub", (), {})()
    backend._library_directory = {} if directory is None else directory
    backend._library = ExplodingLibrary()
    backend._directory_rows = (
        lambda key: Backend._directory_rows(backend, key))
    return backend


def start_worker_calls(name):
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(Backend, name))))
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_start_worker"]


class ColdLibraryReadTests(unittest.TestCase):
    def test_cold_directory_slots_answer_empty_without_recompute(self):
        backend = stub()
        self.assertEqual([], Backend.libraryAlbums(backend))
        self.assertEqual([], Backend.libraryArtists(backend))
        self.assertEqual([], Backend.libraryGenres(backend))
        self.assertEqual([], Backend.libraryFolders(backend, ""))
        self.assertEqual([], Backend.librarySongs(backend))

    def test_warm_directory_slots_copy_rows(self):
        rows = ({"file": "a.flac"},)
        backend = stub(directory={"songs": rows, "albums": rows})
        songs = Backend.librarySongs(backend)
        self.assertEqual([{"file": "a.flac"}], songs)
        self.assertIsNot(rows[0], songs[0])
        self.assertEqual([{"file": "a.flac"}], Backend.libraryAlbums(backend))


class AsyncLibraryReadTests(unittest.TestCase):
    def test_ready_signals_exist(self):
        self.assertTrue(hasattr(Backend, "librarySongsReady"))
        self.assertTrue(hasattr(Backend, "artistDiscographyReady"))

    def test_request_slots_use_one_worker_each(self):
        for name in ("requestLibrarySongs", "requestArtistDiscography"):
            with self.subTest(slot=name):
                self.assertEqual(1, len(start_worker_calls(name)))

    def test_sync_search_slot_is_gone(self):
        self.assertFalse(hasattr(Backend, "search"))
        self.assertTrue(hasattr(Backend, "requestQuickSearch"))

    def run_inline(self, backend):
        backend._start_worker = lambda target, **kw: target()

    def test_request_library_songs_echoes_serial(self):
        backend = stub(directory={"songs": ({"file": "a.flac"},)})
        backend.librarySongsReady = Signal()
        self.run_inline(backend)
        Backend.requestLibrarySongs(backend, 7)
        self.assertEqual([(7, [{"file": "a.flac"}])],
                         backend.librarySongsReady.values)

        cold = stub()
        cold.librarySongsReady = Signal()
        self.run_inline(cold)
        Backend.requestLibrarySongs(cold, 8)
        self.assertEqual([(8, [])], cold.librarySongsReady.values)

    def test_request_artist_discography_echoes_artist_and_serial(self):
        backend = stub()
        backend._library = LibraryRepository()
        backend._library.replace([
            {"file": "Rap/Artist/Album/01.flac", "title": "Signal",
             "artist": "Artist", "album": "Album"},
        ])
        backend._library_playcounts = {}
        backend.artistDiscographyReady = Signal()
        self.run_inline(backend)
        Backend.requestArtistDiscography(backend, "Artist", 3)
        (artist, serial, rows), = backend.artistDiscographyReady.values
        self.assertEqual(("Artist", 3), (artist, serial))
        self.assertEqual(["Album"], [entry["album"] for entry in rows])


if __name__ == "__main__":
    unittest.main()
