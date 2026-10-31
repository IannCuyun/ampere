import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ampere.spotbridge import materialize, sync


class SpotifyMaterializeTests(unittest.TestCase):
    def test_remote_playlist_name_cannot_escape_output_directory(self):
        with TemporaryDirectory() as tmp:
            result = Path(materialize("../../Road/Trip", ["Artist/Song.flac"], tmp))
            self.assertEqual(result.parent, Path(tmp))
            self.assertEqual(result.read_text(), "Artist/Song.flac\n")
            self.assertFalse((Path(tmp).parent / "Road").exists())

    def test_unusable_remote_playlist_name_is_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                materialize("///", [], tmp)

    def test_empty_materialization_preserves_existing_playlist(self):
        with TemporaryDirectory() as tmp:
            existing = Path(tmp) / "Road Trip (Spotify).m3u"
            existing.write_text("Artist/Old.flac\n")

            with self.assertRaisesRegex(ValueError, "no matched tracks"):
                materialize("Road Trip", [], tmp)

            self.assertEqual("Artist/Old.flac\n", existing.read_text())

    def test_zero_match_sync_preserves_existing_playlist(self):
        with TemporaryDirectory() as tmp:
            existing = Path(tmp) / "Road Trip (Spotify).m3u"
            existing.write_text("Artist/Old.flac\n")
            remote = [{"title": "Unavailable", "artist": "Elsewhere",
                       "album": "Remote"}]
            with patch("ampere.spotbridge.token", return_value="token"), \
                    patch("ampere.spotbridge.list_playlists", return_value=[
                        {"id": "one", "name": "Road Trip", "count": 1}]), \
                    patch("ampere.spotbridge.fetch_tracks", return_value=remote):
                with self.assertRaisesRegex(ValueError, "none of the 1"):
                    sync("Road Trip", [], tmp)

            self.assertEqual("Artist/Old.flac\n", existing.read_text())


if __name__ == "__main__":
    unittest.main()
