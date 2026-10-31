import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ampere.playlists import PlaylistRepository
from ampere.mpdclient import Backend
from ampere.taste import TasteService, TasteUpdate


class MpdStore:
    def __init__(self):
        self.playlists = {"Liked": [], "Disliked": []}
        self.stickers = {}
        self.readable = True
        self.writable = True

    def read(self, command, *args, default=None, **_kwargs):
        if not self.readable:
            return default
        if command == "listplaylist":
            return list(self.playlists.get(args[0], []))
        if command == "sticker_get":
            return self.stickers.get((args[1], args[2]), default)
        raise AssertionError(command)

    def write(self, command, *args, **_kwargs):
        if not self.writable:
            return False
        if command == "playlistadd":
            self.playlists.setdefault(args[0], []).append(args[1])
        elif command == "playlistdelete":
            self.playlists[args[0]].pop(args[1])
        elif command == "sticker_set":
            self.stickers[(args[1], args[2])] = args[3]
        elif command == "sticker_delete":
            self.stickers.pop((args[1], args[2]), None)
        else:
            raise AssertionError(command)
        return True


class TasteServiceTests(unittest.TestCase):
    def service(self):
        store = MpdStore()
        def replace(name, files):
            store.playlists[name] = list(files)
            return True
        service = TasteService(
            PlaylistRepository(), read=store.read, write=store.write,
            replace_files=replace)
        service.refresh_liked()
        service.refresh_disliked()
        return service, store

    def test_failed_refresh_retains_last_durable_snapshot(self):
        service, store = self.service()
        store.playlists["Liked"] = ["one.flac"]
        self.assertTrue(service.refresh_liked())
        store.readable = False

        self.assertFalse(service.refresh_liked())
        self.assertEqual(("one.flac",), service.liked)

    def test_explicit_refresh_distinguishes_unchanged_success_from_failure(self):
        service, store = self.service()

        unchanged = service.refresh_disliked_result()
        store.readable = False
        unavailable = service.refresh_disliked_result()

        self.assertTrue(unchanged.success)
        self.assertFalse(unchanged.changed)
        self.assertFalse(unavailable.success)
        self.assertEqual(unchanged.files, unavailable.files)

    def test_dislike_is_add_first_and_removes_mutually_exclusive_like(self):
        service, store = self.service()
        store.playlists["Liked"] = ["one.flac"]
        service.refresh_liked()

        update = service.toggle_dislike(
            "one.flac", current_file="one.flac")

        self.assertEqual((), service.liked)
        self.assertEqual(("one.flac",), service.disliked)
        self.assertTrue(update.liked_changed)
        self.assertTrue(update.disliked_changed)
        self.assertTrue(update.skip_current)

    def test_like_is_add_first_and_removes_mutually_exclusive_dislike(self):
        service, store = self.service()
        store.playlists["Disliked"] = ["one.flac"]
        service.refresh_disliked()

        update = service.toggle_like("one.flac")

        self.assertEqual(("one.flac",), service.liked)
        self.assertEqual((), service.disliked)
        self.assertTrue(update.liked_changed)
        self.assertTrue(update.disliked_changed)

    def test_failed_rating_write_does_not_publish_a_new_value(self):
        service, store = self.service()
        store.writable = False
        self.assertEqual((False, 4.5), service.set_rating("one.flac", 4.6))
        self.assertEqual({}, store.stickers)

    def test_rating_round_trip_uses_half_star_sticker_units(self):
        service, _store = self.service()
        self.assertEqual((True, 3.5), service.set_rating("one.flac", 3.7))
        self.assertEqual(3.5, service.rating("one.flac"))

    def test_transactional_toggle_replaces_collections_without_position_writes(self):
        service, store = self.service()
        store.playlists["Liked"] = ["one.flac", "two.flac"]
        service.refresh_liked()

        service.toggle_dislike("one.flac", current_file="one.flac")

        self.assertEqual(["two.flac"], store.playlists["Liked"])
        self.assertEqual(["one.flac"], store.playlists["Disliked"])
        self.assertEqual({}, store.stickers)

    def test_restoring_current_dislike_does_not_skip_playback(self):
        service, store = self.service()
        store.playlists["Disliked"] = ["one.flac"]
        service.refresh_disliked()

        update = service.toggle_dislike(
            "one.flac", current_file="one.flac")

        self.assertFalse(update.skip_current)
        self.assertEqual([], store.playlists["Disliked"])

    def test_failed_like_removal_rolls_back_new_dislike(self):
        store = MpdStore()
        store.playlists["Liked"] = ["one.flac"]

        def replace(name, files):
            if name == "Liked":
                return False
            store.playlists[name] = list(files)
            return True

        service = TasteService(
            PlaylistRepository(), read=store.read, write=store.write,
            replace_files=replace)
        service.refresh_liked()
        service.refresh_disliked()

        update = service.toggle_dislike("one.flac")

        self.assertFalse(update.disliked_changed)
        self.assertEqual(["one.flac"], store.playlists["Liked"])
        self.assertEqual([], store.playlists["Disliked"])

    def test_failed_dislike_removal_rolls_back_new_like(self):
        store = MpdStore()
        store.playlists["Disliked"] = ["one.flac"]

        def replace(name, files):
            if name == "Disliked":
                return False
            store.playlists[name] = list(files)
            return True

        service = TasteService(
            PlaylistRepository(), read=store.read, write=store.write,
            replace_files=replace)
        service.refresh_liked()
        service.refresh_disliked()

        update = service.toggle_like("one.flac")

        self.assertFalse(update.success)
        self.assertTrue(update.rollback_complete)
        self.assertEqual([], store.playlists["Liked"])
        self.assertEqual(["one.flac"], store.playlists["Disliked"])

    def test_mutation_outcomes_distinguish_invalid_failure_and_success(self):
        service, store = self.service()
        self.assertFalse(service.toggle_like("").attempted)

        store.readable = False
        failed = service.toggle_like("one.flac")
        self.assertTrue(failed.attempted)
        self.assertFalse(failed.success)

        store.readable = True
        recovered = service.toggle_like("one.flac")
        self.assertTrue(recovered.attempted)
        self.assertTrue(recovered.success)

    def test_dislike_reports_incomplete_mutual_exclusion_rollback(self):
        store = MpdStore()
        store.playlists["Liked"] = ["one.flac"]
        disliked_writes = 0

        def replace(name, files):
            nonlocal disliked_writes
            if name == "Liked":
                return False
            disliked_writes += 1
            if disliked_writes > 1:
                return False
            store.playlists[name] = list(files)
            return True

        service = TasteService(
            PlaylistRepository(), read=store.read, write=store.write,
            replace_files=replace)
        service.refresh_liked()
        service.refresh_disliked()

        update = service.toggle_dislike("one.flac")

        self.assertTrue(update.attempted)
        self.assertFalse(update.success)
        self.assertFalse(update.rollback_complete)
        self.assertEqual(["one.flac"], store.playlists["Disliked"])

    def test_like_reports_incomplete_mutual_exclusion_rollback(self):
        store = MpdStore()
        store.playlists["Disliked"] = ["one.flac"]
        liked_writes = 0

        def replace(name, files):
            nonlocal liked_writes
            if name == "Disliked":
                return False
            liked_writes += 1
            if liked_writes > 1:
                return False
            store.playlists[name] = list(files)
            return True

        service = TasteService(
            PlaylistRepository(), read=store.read, write=store.write,
            replace_files=replace)
        service.refresh_liked()
        service.refresh_disliked()

        update = service.toggle_like("one.flac")

        self.assertTrue(update.attempted)
        self.assertFalse(update.success)
        self.assertFalse(update.rollback_complete)
        self.assertEqual(["one.flac"], store.playlists["Liked"])


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, *args):
        self.messages.append(args)


class _TasteStub:
    def __init__(self, updates):
        self._updates = iter(updates)
        self.liked = ()

    def toggle_like(self, _file):
        return next(self._updates)


class TastePublicationTests(unittest.TestCase):
    def test_mutation_worker_uses_fresh_owned_collections(self):
        class Client:
            def __init__(self, *, playlists=None, library=None):
                self.playlists = {"Liked": ["old.flac"], "Disliked": []}
                if playlists is not None:
                    self.playlists = {
                        name: list(files) for name, files in playlists.items()
                    }
                self.library = set(
                    library if library is not None
                    else ("old.flac", "new.flac", "playing.flac"))

            def listplaylist(self, name):
                return list(self.playlists[name])

            def listplaylists(self):
                return [{"playlist": name} for name in self.playlists]

            def listall(self):
                return [{"file": file} for file in sorted(self.library)]

            def ping(self):
                return None

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
        emitted = []
        backend = type("Harness", (), {})()
        backend._taste_mutation_busy = False
        backend._song = {"file": "playing.flac"}
        backend._workers = object()
        backend.invalidations = 0
        backend._invalidate_collection_refresh = lambda: setattr(
            backend, "invalidations", backend.invalidations + 1)
        backend._tasteMutationReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        @contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._request_taste_mutation(
                backend, "like", "new.flac"))

        self.assertTrue(backend._taste_mutation_busy)
        self.assertEqual(1, backend.invalidations)
        self.assertTrue(emitted[0]["update"].success)
        self.assertEqual(("old.flac", "new.flac"), emitted[0]["liked"])
        self.assertEqual(["old.flac", "new.flac"],
                         client.playlists["Liked"])

    def test_mutation_retires_orphans_from_collection_being_rebuilt(self):
        target = "Pop/Indie & Alt-Pop/Yot Club/Yot Club - YKWIM.flac"
        orphan = "Incoming/removed.sync-conflict.flac"

        class Client:
            def __init__(self):
                self.playlists = {
                    "Liked": ["unrelated-missing.flac"],
                    "Disliked": [orphan],
                }

            def listplaylist(self, name):
                return list(self.playlists[name])

            def listplaylists(self):
                return [{"playlist": name} for name in self.playlists]

            def listall(self):
                return [{"file": target}]

            def ping(self):
                return None

            def command_list_ok_begin(self):
                pass

            def command_list_end(self):
                pass

            def playlistadd(self, name, file):
                if file != target:
                    raise AssertionError(f"orphan restaged: {file}")
                self.playlists.setdefault(name, []).append(file)

            def rename(self, old, new):
                self.playlists[new] = self.playlists.pop(old)

            def rm(self, name):
                self.playlists.pop(name, None)

            def playlistclear(self, name):
                self.playlists[name] = []

        client = Client()
        emitted = []
        backend = type("Harness", (), {})()
        backend._taste_mutation_busy = False
        backend._song = {"file": target}
        backend._workers = object()
        backend._invalidate_collection_refresh = lambda: None
        backend._tasteMutationReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        @contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._request_taste_mutation(
                backend, "dislike", target))

        self.assertTrue(emitted[0]["update"].success)
        self.assertEqual((orphan,), emitted[0]["retired"])
        self.assertEqual([target], client.playlists["Disliked"])
        self.assertEqual(
            ["unrelated-missing.flac"], client.playlists["Liked"])
        self.assertEqual(
            ("unrelated-missing.flac",), emitted[0]["liked"])

    def test_restore_can_remove_clicked_orphan_without_restaging_it(self):
        orphan = "Incoming/removed.sync-conflict.flac"

        class Client:
            def __init__(self):
                self.playlists = {"Liked": [], "Disliked": [orphan]}

            def listplaylist(self, name):
                return list(self.playlists[name])

            def listplaylists(self):
                return [{"playlist": name} for name in self.playlists]

            def listall(self):
                return []

            def ping(self):
                return None

            def playlistclear(self, name):
                self.playlists[name] = []

        client = Client()
        emitted = []
        backend = type("Harness", (), {})()
        backend._taste_mutation_busy = False
        backend._song = {}
        backend._workers = object()
        backend._invalidate_collection_refresh = lambda: None
        backend._tasteMutationReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        @contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._request_taste_mutation(
                backend, "dislike", orphan))

        self.assertTrue(emitted[0]["update"].success)
        self.assertEqual([], client.playlists["Disliked"])
        self.assertEqual((), emitted[0]["disliked"])

    def test_failed_episode_warns_once_and_success_rearms(self):
        backend = type("BackendHarness", (), {})()
        updates = [
            TasteUpdate(attempted=True),
            TasteUpdate(attempted=True),
            TasteUpdate(attempted=True, success=True),
            TasteUpdate(attempted=True),
        ]
        backend._taste_mutation_failed = False
        backend._taste_mutation_busy = True
        backend._liked = []
        backend._disliked = []
        backend._playlist_repository = PlaylistRepository()
        backend.errorOccurred = _Signal()
        backend.likedChanged = _Signal()
        backend.dislikedChanged = _Signal()
        backend._write_once = lambda *_args: True
        backend._request_collection_refresh = lambda: True
        backend.cleaned = []
        backend._request_disliked_queue_cleanup = backend.cleaned.append
        backend._report_taste_mutation = lambda success, message: \
            Backend._report_taste_mutation(backend, success, message)

        for update in updates:
            Backend._on_taste_mutation_ready(backend, {
                "kind": "like", "file": "one.flac", "update": update,
                "liked": ("one.flac",) if update.success else (),
                "disliked": (),
            })

        self.assertEqual(2, len(backend.errorOccurred.messages))
        self.assertTrue(backend._taste_mutation_failed)

    def test_successful_new_dislike_triggers_verified_queue_cleanup(self):
        backend = type("BackendHarness", (), {})()
        backend._taste_mutation_failed = False
        backend._taste_mutation_busy = True
        backend._liked = []
        backend._disliked = []
        backend._playlist_repository = PlaylistRepository()
        backend.errorOccurred = _Signal()
        backend.likedChanged = _Signal()
        backend.dislikedChanged = _Signal()
        backend._request_collection_refresh = lambda: True
        cleaned = []
        backend._request_disliked_queue_cleanup = cleaned.append
        backend._report_taste_mutation = lambda success, message: \
            Backend._report_taste_mutation(backend, success, message)

        Backend._on_taste_mutation_ready(backend, {
            "kind": "dislike", "file": "bad.flac",
            "update": TasteUpdate(
                attempted=True, success=True,
                disliked_changed=True, skip_current=True),
            "liked": (), "disliked": ("bad.flac",),
        })

        self.assertEqual(["bad.flac"], cleaned)
        self.assertEqual(["bad.flac"], backend._disliked)

    def test_restoring_dislike_does_not_touch_queue(self):
        backend = type("BackendHarness", (), {})()
        backend._taste_mutation_failed = False
        backend._taste_mutation_busy = True
        backend._liked = []
        backend._disliked = ["bad.flac"]
        backend._playlist_repository = PlaylistRepository()
        backend._playlist_repository.replace_snapshot(
            playlists=(), liked=(), disliked=("bad.flac",))
        backend.errorOccurred = _Signal()
        backend.likedChanged = _Signal()
        backend.dislikedChanged = _Signal()
        backend._request_collection_refresh = lambda: True
        cleaned = []
        backend._request_disliked_queue_cleanup = cleaned.append
        backend._report_taste_mutation = lambda success, message: \
            Backend._report_taste_mutation(backend, success, message)

        Backend._on_taste_mutation_ready(backend, {
            "kind": "dislike", "file": "bad.flac",
            "update": TasteUpdate(
                attempted=True, success=True, disliked_changed=True),
            "liked": (), "disliked": (),
        })

        self.assertEqual([], cleaned)


if __name__ == "__main__":
    unittest.main()
