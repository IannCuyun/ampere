import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ampere.library_deletion import DeletionReconciliation, LibraryDeletionService
from ampere.mpdclient import Backend
from ampere.playback import QueueSnapshotResult, QueueSnapshotStore
from ampere.playlists import PlaylistRepository


class SignalStub:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class DeletionBackendStub:
    def __init__(self, *, starts=True):
        self._disliked = ["Artist/song.flac"]
        self._deleting = False
        self.starts = starts
        self.started = []
        self.deletionStateChanged = SignalStub()
        self.errorOccurred = SignalStub()

    def _start_worker(self, target, *, args=(), name=None, durable=False):
        self.started.append((target, args, name, durable))
        return self.starts

    def _delete_worker(self, _files):
        pass


class ReconciliationPlaybackStub:
    def __init__(self, backend, *, fail=False):
        self.backend = backend
        self.fail = fail
        self.ids = []

    def remove_ids(self, ids):
        self.ids = list(ids)
        if self.fail:
            raise RuntimeError("MPD unavailable")
        self.backend._queue = [song for song in self.backend._queue
                               if song.get("id") not in self.ids]
        return True


class ReconciliationBackendStub:
    def __init__(self, *, fail=False):
        self._disliked = ["gone.flac", "stay.flac"]
        self._queue = [
            {"file": "gone.flac", "id": 7},
            {"file": "stay.flac", "id": 8},
        ]
        self._deleting = True
        self._deletion_generation = 0
        self._playback = ReconciliationPlaybackStub(self, fail=fail)
        self._queue_snapshots = QueueSnapshotStore(
            normalize=lambda item: dict(item))
        self._queue_snapshots.publish(self._queue)
        self._playlist_repository = PlaylistRepository()
        self._playlist_repository.replace_snapshot(disliked=self._disliked)
        self.deletionStateChanged = SignalStub()
        self.errorOccurred = SignalStub()
        self.dislikedDeleted = SignalStub()
        self.queueChanged = SignalStub()
        self.dislikedChanged = SignalStub()
        self.requestStatusRefresh = lambda: None

    def _invalidate_queue_refresh(self):
        pass

    def _invalidate_collection_refresh(self):
        pass

    def _request_queue_intent(self, kind, request, *, on_finished=None):
        self.asserted_intent = (kind, request)
        try:
            success = self._playback.remove_ids(request["songIds"])
        except RuntimeError:
            success = False
        if on_finished is not None:
            on_finished(success)
        return True

    def _continue_delete_queue_reconciliation(self, context, removal_ok):
        return Backend._continue_delete_queue_reconciliation(
            self, context, removal_ok)

    def _start_delete_queue_reconciliation(self, context):
        payload = dict(context)
        payload["result"] = QueueSnapshotResult(
            True, tuple(dict(song) for song in self._queue))
        payload["disliked"] = tuple(context["survivors"])
        payload["dislikedVerified"] = True
        return Backend._on_delete_queue_ready(self, payload)

    def _finish_delete_reconciliation(self, *args):
        return Backend._finish_delete_reconciliation(self, *args)

class LibraryDeletionServiceTests(unittest.TestCase):
    def test_partition_rejects_absolute_traversal_and_empty_paths(self):
        safe, rejected = LibraryDeletionService.partition([
            "Artist/song.flac", "../outside.flac", "/tmp/outside.flac", ""])
        self.assertEqual(safe, ["Artist/song.flac"])
        self.assertEqual(rejected, ["../outside.flac", "/tmp/outside.flac", ""])

    def test_local_delete_handles_files_and_already_missing_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"; root.mkdir()
            track = root / "song.flac"; track.write_bytes(b"audio")
            service = LibraryDeletionService(root)
            deleted, failed = service.delete(["song.flac", "missing.flac"])
            self.assertEqual(deleted, ["song.flac", "missing.flac"])
            self.assertEqual(failed, [])
            self.assertFalse(track.exists())

    def test_local_delete_rejects_final_and_parent_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"; root.mkdir()
            outside = Path(tmp) / "outside"; outside.mkdir()
            target = outside / "safe.flac"; target.write_bytes(b"safe")
            (root / "link.flac").symlink_to(target)
            (root / "linked-dir").symlink_to(outside, target_is_directory=True)
            service = LibraryDeletionService(root)
            deleted, failed = service.delete(
                ["link.flac", "linked-dir/safe.flac"])
            self.assertEqual(deleted, [])
            self.assertEqual(failed, ["link.flac", "linked-dir/safe.flac"])
            self.assertTrue(target.exists())

    def test_remote_deletes_are_quoted_and_batched_at_fifty(self):
        calls = []
        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0)
        files = [f"Artist/track {index}.flac" for index in range(51)]
        service = LibraryDeletionService("/unused", runner=runner)
        deleted, failed = service.delete(
            files, remote_host="music-host", remote_root="/srv/Music Library/")
        self.assertEqual(deleted, files)
        self.assertEqual(failed, [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][:4],
                         ["ssh", "-o", "BatchMode=yes", "music-host"])
        self.assertIn("'/srv/Music Library/Artist/track 0.flac'",
                      calls[0][0][4])
        self.assertEqual(calls[0][1]["timeout"], 60)

    def test_remote_batch_failure_marks_only_its_chunk(self):
        returns = iter((SimpleNamespace(returncode=1),
                        SimpleNamespace(returncode=0)))
        service = LibraryDeletionService(
            "/unused", runner=lambda *args, **kwargs: next(returns))
        files = [f"{index}.flac" for index in range(51)]
        deleted, failed = service.delete(
            files, remote_host="host", remote_root="/music")
        self.assertEqual(failed, files[:50])
        self.assertEqual(deleted, files[50:])


class LibraryDeletionLifecycleTests(unittest.TestCase):
    def test_delete_request_publishes_busy_state_and_rejects_duplicates(self):
        backend = DeletionBackendStub()

        Backend.deleteDislikedSongs(backend, ["Artist/song.flac"])
        Backend.deleteDislikedSongs(backend, ["Artist/song.flac"])

        self.assertTrue(backend._deleting)
        self.assertEqual(1, len(backend.started))
        self.assertEqual([()], backend.deletionStateChanged.values)

    def test_rejected_worker_start_restores_idle_state(self):
        backend = DeletionBackendStub(starts=False)

        Backend.deleteDislikedSongs(backend, ["Artist/song.flac"])

        self.assertFalse(backend._deleting)
        self.assertEqual([(), ()], backend.deletionStateChanged.values)
        self.assertIn("closing", backend.errorOccurred.values[0][0])


class DeletionReconciliationTests(unittest.TestCase):
    def test_complete_cleanup_reports_only_the_deleted_count(self):
        result = DeletionReconciliation(
            deleted=2, failed=0, disliked_verified=True,
            queue_verified=True)
        self.assertEqual("2 files deleted from the library", result.message())

    def test_partial_outcome_names_every_unverified_surface(self):
        result = DeletionReconciliation(
            deleted=1, failed=2, disliked_verified=False,
            queue_verified=False)
        self.assertEqual(
            "1 file deleted from the library · "
            "2 files could not be deleted and remain Disliked · "
            "Disliked cleanup could not be verified · "
            "queue cleanup could not be verified",
            result.message())

    def test_backend_reconciles_queue_by_stable_id_and_verifies_surfaces(self):
        backend = ReconciliationBackendStub()

        Backend._on_delete_done(backend, ["gone.flac"], [])

        self.assertEqual([7], backend._playback.ids)
        self.assertEqual(["stay.flac"], backend._disliked)
        self.assertEqual([{"file": "stay.flac", "id": 8}], backend._queue)
        self.assertFalse(backend._deleting)
        self.assertEqual(
            [("1 file deleted from the library",)],
            backend.dislikedDeleted.values)

    def test_backend_releases_busy_state_when_async_queue_removal_fails(self):
        backend = ReconciliationBackendStub(fail=True)

        Backend._on_delete_done(backend, ["gone.flac"], [])

        self.assertFalse(backend._deleting)
        self.assertIn("queue cleanup could not be verified",
                      backend.dislikedDeleted.values[0][0])

    def test_queue_verification_worker_uses_an_owned_client(self):
        emitted = []
        backend = type("Harness", (), {})()
        backend._workers = object()
        backend._deleteQueueReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        class Client:
            def __init__(self):
                # MPD may omit an empty built-in playlist entirely; fresh
                # catalog truth must choose create, not a backup rename.
                self.playlists = {}
                self.updates = 0

            def status(self):
                return {}

            def update(self):
                self.updates += 1

            def ping(self):
                pass

            def playlistinfo(self):
                return [{"file": "stay.flac", "id": "8", "pos": "0"}]

            def listplaylist(self, name):
                return list(self.playlists[name])

            def listplaylists(self):
                return [{"playlist": name} for name in self.playlists]

            def command_list_ok_begin(self):
                pass

            def command_list_end(self):
                pass

            def playlistadd(self, name, file):
                self.playlists.setdefault(name, []).append(file)

            def rename(self, old, new):
                self.playlists[new] = self.playlists.pop(old)

            def rm(self, name):
                self.playlists.pop(name, None)

            def playlistclear(self, name):
                self.playlists[name] = []

        client = Client()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        context = {
            "generation": 1, "deleted": ("gone.flac",), "failed": (),
            "survivors": ("stay.flac",), "removalOk": True,
            "gone": ("gone.flac",),
        }
        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=Scope()):
            self.assertTrue(Backend._start_delete_queue_reconciliation(
                backend, context))

        self.assertTrue(emitted[0]["result"].success)
        self.assertEqual("stay.flac", emitted[0]["result"].songs[0]["file"])
        self.assertTrue(emitted[0]["dislikedVerified"])
        self.assertEqual(("stay.flac",), emitted[0]["disliked"])
        self.assertTrue(emitted[0]["libraryUpdate"].started)
        self.assertEqual(1, client.updates)


if __name__ == "__main__":
    unittest.main()
