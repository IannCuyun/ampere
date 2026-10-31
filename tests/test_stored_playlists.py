import unittest
from contextlib import contextmanager
from unittest.mock import patch

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from ampere.stored_playlists import GeneratedPlaylistWriter
from ampere.mpdclient import Backend


class Client:
    def __init__(self, playlists=None, fail_on=None):
        self.playlists = dict(playlists or {})
        self.fail_on = fail_on
        self.disconnected = False
        self.fail_after_rename = None

    def command_list_ok_begin(self):
        pass

    def command_list_end(self):
        pass

    def playlistadd(self, name, file):
        if self.fail_on == ("add", file):
            raise CommandError("missing")
        self.playlists.setdefault(name, []).append(file)

    def rename(self, old, new):
        if self.fail_on == ("rename", old):
            raise CommandError("rename failed")
        self.playlists[new] = self.playlists.pop(old)
        if self.fail_after_rename == old:
            self.fail_after_rename = None
            raise MPDConnectionError("rename reply lost")

    def rm(self, name):
        self.playlists.pop(name, None)

    def disconnect(self):
        self.disconnected = True

    def ping(self):
        return None

    def connect(self, *_args):
        self.disconnected = False

    def listplaylists(self):
        return [{"playlist": name} for name in self.playlists]


class GeneratedPlaylistWriterTests(unittest.TestCase):
    def writer(self, client, *, connected=True):
        refreshed, failed = [], []
        def write(command, *args, **kwargs):
            getattr(client, command)(*args)
            return True
        writer = GeneratedPlaylistWriter(
            client, ensure_connected=lambda silent=False: connected,
            list_playlists=lambda: [{"playlist": name}
                                    for name in client.playlists],
            write=write, refresh=lambda: refreshed.append(True),
            connection_failed=lambda: failed.append(True),
            token=iter(("stage", "backup")).__next__)
        return writer, refreshed, failed

    def test_success_swaps_then_removes_backup(self):
        client = Client({"Mix": ["old.flac"]})
        writer, refreshed, _ = self.writer(client)
        self.assertTrue(writer.save("Mix", ["new.flac"], existing=["Mix"]))
        self.assertEqual(client.playlists, {"Mix": ["new.flac"]})
        self.assertTrue(refreshed)

    def test_invalid_input_never_opens_a_transaction(self):
        client = Client()
        writer, refreshed, _ = self.writer(client)
        self.assertFalse(writer.save("", ["a.flac"]))
        self.assertFalse(writer.save("Mix", []))
        self.assertEqual(client.playlists, {})
        self.assertFalse(refreshed)

    def test_staging_failure_preserves_original_and_cleans_stage(self):
        client = Client({"Mix": ["old.flac"]}, fail_on=("add", "bad.flac"))
        writer, _, _ = self.writer(client)
        self.assertFalse(writer.save(
            "Mix", ["new.flac", "bad.flac"], existing=["Mix"]))
        self.assertEqual(client.playlists, {"Mix": ["old.flac"]})

    def test_failed_install_restores_backup_name(self):
        client = Client({"Mix": ["old.flac"]},
                        fail_on=("rename", ".ampere-stage-stage"))
        writer, _, _ = self.writer(client)
        self.assertFalse(writer.save("Mix", ["new.flac"], existing=["Mix"]))
        self.assertEqual(client.playlists, {"Mix": ["old.flac"]})

    def test_connection_failure_marks_and_disconnects_before_recovery(self):
        class DroppingClient(Client):
            def playlistadd(self, name, file):
                raise MPDConnectionError("gone")
        client = DroppingClient({"Mix": ["old.flac"]})
        writer, _, failed = self.writer(client)
        self.assertFalse(writer.save("Mix", ["new.flac"], existing=["Mix"]))
        self.assertTrue(client.disconnected)
        self.assertTrue(failed)

    def test_lost_install_reply_is_recognized_as_committed(self):
        client = Client({"Mix": ["old.flac"]})
        client.fail_after_rename = ".ampere-stage-stage"
        writer, refreshed, failed = self.writer(client)

        self.assertTrue(writer.save("Mix", ["new.flac"], existing=["Mix"]))

        self.assertEqual({"Mix": ["new.flac"]}, client.playlists)
        self.assertTrue(writer.last_recovery.committed)
        self.assertTrue(refreshed)
        self.assertTrue(failed)

    def test_unavailable_recovery_catalog_uses_best_effort_restore(self):
        client = Client({"Mix": ["old.flac"]},
                        fail_on=("rename", ".ampere-stage-stage"))
        writes = []

        def write(command, *args, **_kwargs):
            writes.append((command, args))
            try:
                getattr(client, command)(*args)
                return True
            except (CommandError, KeyError):
                return False

        writer = GeneratedPlaylistWriter(
            client, ensure_connected=lambda silent=False: True,
            list_playlists=lambda: None, write=write,
            refresh=lambda: None,
            token=iter(("stage", "backup")).__next__)

        self.assertFalse(writer.save("Mix", ["new.flac"], existing=["Mix"]))
        self.assertFalse(writer.last_recovery.catalog_available)
        self.assertTrue(writer.last_recovery.restored)
        self.assertEqual({"Mix": ["old.flac"]}, client.playlists)
        self.assertIn(("rm", (".ampere-stage-stage",)), writes)

    def test_backend_generated_save_uses_owned_client_and_defers_publication(self):
        client = Client({"Mix": ["old.flac"]})
        emitted = []
        backend = type("Harness", (), {})()
        backend._generated_playlist_busy = False
        # The Qt snapshot is intentionally stale: worker-owned catalog truth
        # must still protect the externally-created target before replacement.
        backend._playlists = []
        backend._workers = object()
        backend._generatedPlaylistReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        @contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._request_generated_playlist_save(
                backend, "recap", "Mix", ["new.flac"], key="month"))

        self.assertTrue(backend._generated_playlist_busy)
        self.assertEqual({"Mix": ["new.flac"]}, client.playlists)
        self.assertTrue(emitted[0]["success"])
        self.assertEqual("recap", emitted[0]["purpose"])


if __name__ == "__main__":
    unittest.main()
