"""Behavioral regressions found in the October 31 application audit."""

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ampere.mpdclient import Backend
from ampere.settings import DEFAULTS, SettingsRepository
from ampere.playhistory import PlayHistoryRepository
from ampere.remote import _MPD
from ampere.mpdgateway import track_mpd_client, tracked_mpd_clients, close_mpd_client
from ampere.stored_playlists import GeneratedPlaylistWriter
from mpd.base import CommandError


class ModuleLaunchTests(unittest.TestCase):
    def test_startup_failure_is_reported_to_the_launcher(self):
        with patch("ampere.main.main", return_value=1):
            with self.assertRaises(SystemExit) as result:
                runpy.run_module("ampere", run_name="__main__")
        self.assertEqual(1, result.exception.code)


class FolderRoomTests(unittest.TestCase):
    def test_visible_folder_order_includes_nested_tracks_once(self):
        songs = [
            {"file": f}
            for f in (
                "Rock/A/one.flac",
                "Jazz/two.flac",
                "Rock/B/three.flac",
                "Rockish/four.flac",
                "root.flac",
            )
        ]
        backend = SimpleNamespace(
            _library=SimpleNamespace(songs=songs), ROOM_FILE_LIMIT=20000
        )
        self.assertEqual(
            ["Jazz/two.flac", "Rock/A/one.flac", "Rock/B/three.flac"],
            Backend.libraryRoomFiles(backend, "folders", ["Jazz/", "Rock", "Rock/A"]),
        )

    def test_folder_limit_applies_after_order_and_deduplication(self):
        backend = SimpleNamespace(
            _library=SimpleNamespace(
                songs=[{"file": "A/nested/one.flac"}, {"file": "A/two.flac"}]
            ),
            ROOM_FILE_LIMIT=1,
        )
        self.assertEqual(
            ["A/nested/one.flac"], Backend.libraryRoomFiles(backend, "folders", ["A"])
        )


class SettingsCorruptionTests(unittest.TestCase):
    def test_bad_value_does_not_prevent_other_preferences_loading(self):
        cases = [
            ({"mix_style": []}, "mix_style", "blend"),
            ({"rating_mode": {}}, "rating_mode", "hearts"),
            ({"crossfade_base": float("inf")}, "crossfade_base", 4),
            (
                {"device_volumes": {"bad": float("inf"), "good": 70}},
                "device_volumes",
                {"good": 70},
            ),
            (
                {"sound_mixes": [{"id": "x", "character": "calm", "files": 42}]},
                "sound_mixes",
                [],
            ),
            (
                {
                    "sound_mixes": [
                        {"id": "x", "character": "calm", "files": "song.flac"}
                    ]
                },
                "sound_mixes",
                [],
            ),
            (
                {"playlist_play_counts": {"bad": float("inf"), "good": 2}},
                "playlist_play_counts",
                {"good": 2},
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            for raw, key, expected in cases:
                with self.subTest(key=key, raw=raw):
                    path.write_text(json.dumps({**raw, "remote_token": "keep-token"}))
                    values = SettingsRepository(path).load()
                    self.assertEqual(expected, values[key])
                    self.assertEqual("keep-token", values["remote_token"])

    def test_invalid_encoding_is_preserved_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            data = b'{"remote_token":"\xff"}'
            path.write_bytes(data)
            repo = SettingsRepository(path)
            self.assertEqual(DEFAULTS, repo.load())
            self.assertFalse(repo.try_patch({"rating_mode": "stars"}).success)
            self.assertEqual(data, path.read_bytes())


class HistoryCorruptionTests(unittest.TestCase):
    def test_bad_encoding_and_nonfinite_timestamp_do_not_hide_valid_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            data = (
                b'{"t":10,"f":"a.flac"}\n\xff\n'
                b'{"t":1e999,"f":"bad.flac"}\n{"t":20,"f":"b.flac"}\n'
            )
            path.write_bytes(data)
            self.assertEqual(
                ((10, "a.flac"), (20, "b.flac")),
                PlayHistoryRepository(path).snapshot().entries,
            )
            self.assertEqual(data, path.read_bytes())

    def test_append_after_partial_tail_keeps_new_record_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            path.write_bytes(b'{"t":10,"f":"a.flac"}\n{"t":')
            repo = PlayHistoryRepository(path)
            self.assertTrue(repo.append("b.flac", played_at=20))
            self.assertEqual(((10, "a.flac"), (20, "b.flac")), repo.snapshot().entries)


class RemoteConnectionTests(unittest.TestCase):
    def test_failed_handshake_releases_tracked_transport(self):
        class Client:
            closed = False

            def connect(self, *args):
                raise OSError("handshake failed")

            def disconnect(self):
                self.closed = True

        client = Client()
        baseline = tracked_mpd_clients()
        try:
            with patch(
                "ampere.remote.create_mpd_client",
                side_effect=lambda: track_mpd_client(client),
            ):
                with self.assertRaises(OSError):
                    _MPD().call(lambda c: c.status())
            self.assertTrue(client.closed)
            self.assertEqual(set(baseline), set(tracked_mpd_clients()))
        finally:
            close_mpd_client(client)


class PlaylistRecoveryTests(unittest.TestCase):
    def test_concurrently_created_destination_is_not_reported_as_saved(self):
        class Client:
            def __init__(self):
                self.playlists = {"Mix": ["someone-elses.flac"]}

            def command_list_ok_begin(self):
                pass

            def command_list_end(self):
                pass

            def playlistadd(self, name, file):
                self.playlists.setdefault(name, []).append(file)

            def rename(self, old, new):
                if new in self.playlists:
                    raise CommandError("destination exists")
                self.playlists[new] = self.playlists.pop(old)

            def rm(self, name):
                self.playlists.pop(name, None)

            def listplaylists(self):
                return [{"playlist": p} for p in self.playlists]

            def listplaylist(self, name):
                return self.playlists[name]

        client = Client()

        def write(command, *args, **kwargs):
            getattr(client, command)(*args)
            return True

        writer = GeneratedPlaylistWriter(
            client,
            ensure_connected=lambda **k: True,
            list_playlists=client.listplaylists,
            write=write,
            refresh=lambda: None,
        )
        self.assertFalse(writer.save("Mix", ["requested.flac"], existing=()))
        self.assertEqual({"Mix": ["someone-elses.flac"]}, client.playlists)
