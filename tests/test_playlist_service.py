import unittest
from unittest.mock import patch

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from ampere.mpdclient import Backend
from ampere.playlist_service import PlaylistResult, PlaylistService
from ampere.playlists import PlaylistRepository


class Store:
    def __init__(self):
        self.playlists = {
            "Focus": ["a.flac", "bad.flac"],
            "Empty": [],
        }
        self.writes = []
        self.refreshes = 0
        self.saved = []

    def read(self, command, name, default=None):
        if command != "listplaylistinfo" or name not in self.playlists:
            return default
        return [{"file": file, "title": file} for file in self.playlists[name]]

    def write(self, command, *args, **_kwargs):
        self.writes.append((command, args))
        return True

    def save(self, name, files):
        self.saved.append((name, list(files)))
        return True

    def refresh(self):
        self.refreshes += 1


class PlaylistServiceTests(unittest.TestCase):
    def service(self):
        store = Store()
        repository = PlaylistRepository()
        repository.replace_playlists([{"playlist": "Focus"}])
        service = PlaylistService(
            repository, read=store.read, write=store.write,
            refresh=store.refresh, save_files=store.save,
            filter_allowed=lambda files: [f for f in files if f != "bad.flac"],
            normalize_song=lambda row: dict(row))
        return service, store

    def test_tracks_are_normalized_and_keep_stored_positions(self):
        service, _store = self.service()
        rows = service.tracks("Focus")
        self.assertEqual([0, 1], [row["playlistPos"] for row in rows])

    def test_worker_client_tracks_are_normalized_and_positioned(self):
        client = type("Client", (), {
            "listplaylistinfo": lambda self, _name: [
                {"file": "a.flac", "title": "A"},
                {"file": "b.flac", "title": "B"},
            ],
        })()

        result = PlaylistService.client_tracks_result(
            client, "Focus", lambda row: dict(row))

        self.assertTrue(result.success)
        self.assertEqual((0, 1), tuple(
            row["playlistPos"] for row in result.tracks))

    def test_worker_client_rejects_transport_and_malformed_rows(self):
        failed = type("Client", (), {
            "listplaylistinfo": lambda *_args: (_ for _ in ()).throw(
                MPDConnectionError("lost")),
        })()
        malformed = type("Client", (), {
            "listplaylistinfo": lambda *_args: [{"title": "missing file"}],
        })()

        self.assertFalse(PlaylistService.client_tracks_result(
            failed, "Focus", dict).success)
        self.assertFalse(PlaylistService.client_tracks_result(
            malformed, "Focus", dict).success)

    def test_rename_and_delete_validate_then_refresh(self):
        service, store = self.service()
        self.assertFalse(service.rename("Focus", "Focus").ok)
        self.assertTrue(service.rename("Focus", "Driving").ok)
        self.assertTrue(service.delete("Focus").ok)
        self.assertEqual(2, store.refreshes)

    def test_missing_source_never_enters_mutation_or_reconciliation(self):
        service, store = self.service()

        rename = service.rename("Missing", "Driving")
        delete = service.delete("Missing")

        self.assertFalse(rename.ok)
        self.assertFalse(delete.ok)
        self.assertEqual([], store.writes)
        self.assertEqual(0, store.refreshes)

    def test_lost_rename_reply_reconciles_without_replaying(self):
        service, store = self.service()
        calls = []

        def ambiguous_write(command, *args, **_kwargs):
            calls.append((command, args))
            return False

        def committed_refresh():
            service._repository.replace_playlists([
                {"playlist": "Driving"}])
            return True

        service._write = ambiguous_write
        service._refresh = committed_refresh

        result = service.rename("Focus", "Driving")

        self.assertTrue(result.ok)
        self.assertEqual([("rename", ("Focus", "Driving"))], calls)

    def test_lost_delete_reply_reconciles_without_replaying(self):
        service, _store = self.service()
        calls = []
        service._write = lambda command, *args, **_kwargs: (
            calls.append((command, args)) or False)
        service._refresh = lambda: (
            service._repository.replace_playlists([]) or True)

        result = service.delete("Focus")

        self.assertTrue(result.ok)
        self.assertEqual([("rm", ("Focus",))], calls)

    def test_ambiguous_mutation_with_unavailable_catalog_is_unconfirmed(self):
        service, _store = self.service()
        service._write = lambda *_args, **_kwargs: False
        service._refresh = lambda: False

        rename = service.rename("Focus", "Driving")
        delete = service.delete("Focus")

        self.assertFalse(rename.ok)
        self.assertFalse(rename.available)
        self.assertIn("could not be confirmed", rename.message)
        self.assertFalse(delete.ok)
        self.assertFalse(delete.available)
        self.assertIn("could not be confirmed", delete.message)

    def test_load_filters_disliked_tracks_without_mutating_store(self):
        service, store = self.service()
        result = service.load("Focus")
        self.assertEqual(("a.flac",), result.files)
        self.assertEqual(["a.flac", "bad.flac"], store.playlists["Focus"])

    def test_save_excludes_bridges_and_protects_builtin_collections(self):
        service, store = self.service()
        queue = [{"file": "a.flac"}, {"file": "/tmp/bridge.flac"},
                 {"file": "b.flac"}]
        self.assertFalse(service.save_queue("Liked", queue).ok)
        result = service.save_queue("Focus", queue, count=1)
        self.assertTrue(result.ok)
        self.assertEqual([("Focus", ["a.flac"])], store.saved)
        self.assertIn("Replaced", result.message)

    def test_backend_returns_authoritative_queue_save_result(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, message):
                self.messages.append(message)

        backend = type("PlaylistBackend", (), {})()
        backend._queue = [{"file": "a.flac"}]
        backend.errorOccurred = Signal()
        outcomes = iter((
            PlaylistResult(False, "save failed"),
            PlaylistResult(True, "saved", ("a.flac",)),
        ))
        requested = []
        backend._request_generated_playlist_save = \
            lambda purpose, name, files, **context: (
                requested.append((purpose, name, files, context)) or True)

        backend._playlist_repository = PlaylistRepository()
        with patch("ampere.mpdclient.plan_queue_save",
                   side_effect=lambda *_args, **_kwargs: next(outcomes)):
            self.assertFalse(Backend.saveQueueAs(backend, "Focus", 0))
            self.assertTrue(Backend.saveQueueAs(backend, "Focus", 0))
        self.assertEqual(["save failed"], backend.errorOccurred.messages)
        self.assertEqual([("queue-save", "Focus", ("a.flac",),
                           {"message": "saved"})], requested)

    def test_queue_save_feedback_waits_for_worker_commit(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, message):
                self.messages.append(message)

        backend = type("Harness", (), {})()
        backend._generated_playlist_busy = True
        backend.errorOccurred = Signal()
        backend._request_collection_refresh = lambda: True

        Backend._on_generated_playlist_ready(backend, {
            "purpose": "queue-save", "name": "Focus",
            "files": ("a.flac",), "context": {"message": "Saved Focus"},
            "success": True,
        })
        Backend._on_generated_playlist_ready(backend, {
            "purpose": "queue-save", "name": "Focus",
            "files": ("a.flac",), "context": {}, "success": False,
        })

        self.assertEqual([
            "Saved Focus",
            "Playlist could not be saved — the previous copy is intact",
        ], backend.errorOccurred.messages)

    def test_empty_and_unavailable_playlists_have_distinct_outcomes(self):
        service, store = self.service()
        empty = service.load("Empty")
        unavailable = service.load("Missing")

        self.assertFalse(empty.ok)
        self.assertTrue(empty.available)
        self.assertIn("empty", empty.message)
        self.assertFalse(unavailable.ok)
        self.assertFalse(unavailable.available)
        self.assertIn("unavailable", unavailable.message)
        self.assertEqual([], store.writes)

    def test_unavailable_read_blocks_position_edits_without_saving(self):
        service, store = self.service()

        remove = service.remove_position_result("Missing", 0)
        move = service.move_position_result("Missing", 0, 1)

        self.assertFalse(remove.ok)
        self.assertFalse(remove.available)
        self.assertFalse(move.ok)
        self.assertFalse(move.available)
        self.assertEqual([], store.saved)

    def test_malformed_row_rejects_the_complete_snapshot(self):
        service, store = self.service()
        store.playlists["Broken"] = ["a.flac"]
        original_read = store.read
        store.read = lambda command, name, default=None: (
            [{"file": "a.flac"}, 7]
            if name == "Broken" else original_read(command, name, default))
        service._read = store.read

        self.assertFalse(service.files_result("Broken").success)
        self.assertFalse(service.tracks_result("Broken").success)

    def test_worker_playlist_read_distinguishes_missing_from_outage(self):
        class Client:
            outcome = [{"file": "a.flac"}]

            def listplaylistinfo(self, _name):
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                return self.outcome

        client = Client()
        found = PlaylistService.client_files_result(client, "Hype")
        client.outcome = CommandError("No such playlist")
        missing = PlaylistService.client_files_result(client, "Hype")
        client.outcome = MPDConnectionError("lost")
        unavailable = PlaylistService.client_files_result(client, "Hype")
        client.outcome = [{"file": "a.flac"}, 7]
        malformed = PlaylistService.client_files_result(client, "Hype")

        self.assertEqual(("a.flac",), found.files)
        self.assertTrue(missing.success)
        self.assertEqual((), missing.files)
        self.assertFalse(unavailable.success)
        self.assertFalse(malformed.success)

    def test_remove_and_move_replace_the_complete_verified_playlist(self):
        service, store = self.service()

        self.assertTrue(service.remove_position("Focus", 0))
        self.assertTrue(service.move_position("Focus", 0, 1))

        self.assertEqual([
            ("Focus", ["bad.flac"]),
            ("Focus", ["bad.flac", "a.flac"]),
        ], store.saved)
        self.assertEqual([], store.writes)


if __name__ == "__main__":
    unittest.main()
