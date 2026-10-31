import unittest
from unittest.mock import patch

from ampere.mpdclient import Backend, _read_optional_playlist
from mpd.base import CommandError
from ampere.playlists import PlaylistRepository


class Signal:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class PlaylistRefreshTests(unittest.TestCase):
    def test_uncreated_taste_playlist_is_empty(self):
        client = unittest.mock.Mock()
        client.listplaylist.side_effect = CommandError(
            "[50@0] {listplaylist} No such playlist")
        self.assertEqual([], _read_optional_playlist(client, "Liked"))

    def test_taste_playlist_permission_failure_is_not_empty(self):
        client = unittest.mock.Mock()
        client.listplaylist.side_effect = CommandError(
            "[4@0] {listplaylist} permission denied")
        with self.assertRaises(CommandError):
            _read_optional_playlist(client, "Liked")

    def test_worker_refresh_owns_all_three_collection_reads(self):
        backend = type("Harness", (), {})()
        backend._collection_refresh_busy = False
        backend._collection_refresh_pending = False
        backend._collection_refresh_generation = 0
        backend._workers = object()
        emitted = []
        backend._collectionRefreshReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        calls = []
        client = type("Client", (), {
            "listplaylists": lambda self: (
                calls.append("catalog") or [{"playlist": "Focus"}]),
            "listplaylist": lambda self, name: (
                calls.append(name) or [f"{name}.flac"]),
        })()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=Scope()):
            self.assertTrue(Backend._request_collection_refresh(backend))

        self.assertEqual(["catalog", "Liked", "Disliked"], calls)
        self.assertEqual(("Focus",), emitted[0]["result"]["playlists"])
        self.assertEqual(("Liked.flac",), emitted[0]["result"]["liked"])
        self.assertEqual(("Disliked.flac",), emitted[0]["result"]["disliked"])

    def test_collection_publication_is_atomic_and_failure_retains_all(self):
        class MultiSignal:
            def __init__(self):
                self.messages = []

            def emit(self, *args):
                self.messages.append(args)

        backend = type("Harness", (), {})()
        backend._playlist_repository = PlaylistRepository()
        backend._playlist_repository.replace_snapshot(
            playlists=("Old",), liked=("liked.flac",),
            disliked=("disliked.flac",))
        backend._playlists = ["Old"]
        backend._liked = ["liked.flac"]
        backend._disliked = ["disliked.flac"]
        backend._collection_refresh_generation = 1
        backend._collection_refresh_busy = True
        backend._collection_refresh_pending = False
        backend._collection_refresh_failed = False
        backend.errorOccurred = MultiSignal()
        backend.playlistsChanged = MultiSignal()
        backend.likedChanged = MultiSignal()
        backend.dislikedChanged = MultiSignal()

        Backend._on_collection_refresh_ready(backend, {
            "generation": 1,
            "result": {"playlists": ("New",), "liked": None,
                       "disliked": ()},
        })

        self.assertEqual(("Old",),
                         backend._playlist_repository.snapshot.playlists)
        self.assertEqual(("liked.flac",),
                         backend._playlist_repository.snapshot.liked)
        self.assertEqual(("disliked.flac",),
                         backend._playlist_repository.snapshot.disliked)
        self.assertEqual(1, len(backend.errorOccurred.messages))

        backend._collection_refresh_busy = True
        Backend._on_collection_refresh_ready(backend, {
            "generation": 1,
            "result": {"playlists": ("New",), "liked": ("new-like",),
                       "disliked": ()},
        })
        self.assertEqual(("New",),
                         backend._playlist_repository.snapshot.playlists)
        self.assertEqual(("new-like",),
                         backend._playlist_repository.snapshot.liked)
        self.assertEqual(1, len(backend.playlistsChanged.messages))
        self.assertEqual(1, len(backend.likedChanged.messages))
        self.assertEqual(1, len(backend.dislikedChanged.messages))

    def test_mutation_invalidation_defers_one_fresh_followup(self):
        backend = type("Harness", (), {})()
        backend._collection_refresh_generation = 4
        backend._collection_refresh_busy = True
        backend._collection_refresh_pending = False
        backend._collection_refresh_failed = False
        launched = []
        backend._request_collection_refresh = lambda: (
            launched.append("refresh") or True)

        Backend._invalidate_collection_refresh(backend)
        Backend._on_collection_refresh_ready(backend, {
            "generation": 4, "result": None,
        })

        self.assertEqual(5, backend._collection_refresh_generation)
        self.assertEqual(["refresh"], launched)


if __name__ == "__main__":
    unittest.main()
