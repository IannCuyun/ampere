import shutil
import tempfile
import threading
import time
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider
from mutagen.id3 import ID3, TXXX

from ampere import artprovider
from ampere.artprovider import ArtProvider


class ArtProviderAsyncTests(unittest.TestCase):
    @staticmethod
    def _image_bytes(width, height, color="#884422"):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(encoded)

    def test_provider_forces_image_loading_off_the_gui_thread(self):
        provider = ArtProvider()

        self.assertTrue(
            provider.flags()
            & QQuickImageProvider.Flag.ForceAsynchronousImageLoading
        )

    def test_distinct_art_requests_are_not_globally_serialized(self):
        provider = ArtProvider.__new__(ArtProvider)
        provider._request_image_locked = lambda *_args: time.sleep(0.06)
        image_ids = []
        locks = set()
        candidate = 0
        while len(image_ids) < 4:
            image_id = f"album-{candidate}"
            lock = artprovider._art_lock_for(image_id)
            if id(lock) not in locks:
                locks.add(id(lock))
                image_ids.append(image_id)
            candidate += 1

        started = time.perf_counter()
        threads = [threading.Thread(
            target=provider.requestImage,
            args=(image_id, None, QSize())) for image_id in image_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertLess(time.perf_counter() - started, 0.18)

    def test_first_miss_after_cache_clear_recreates_cache_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_cache, old_music = artprovider.CACHE_DIR, artprovider.MUSIC_ROOT
            artprovider.CACHE_DIR = root / "art"
            artprovider.MUSIC_ROOT = root / "music"
            artprovider.MUSIC_ROOT.mkdir()
            try:
                provider = ArtProvider()
                shutil.rmtree(artprovider.CACHE_DIR)
                fallback = QImage(2, 2, QImage.Format.Format_ARGB32)
                fallback.fill(0)
                with patch("ampere.artprovider._noart_image",
                           return_value=fallback):
                    provider._square("missing.flac")
                self.assertTrue(artprovider.CACHE_DIR.is_dir())
                self.assertTrue(any(artprovider.CACHE_DIR.iterdir()))
            finally:
                artprovider.CACHE_DIR = old_cache
                artprovider.MUSIC_ROOT = old_music

    def test_artless_folder_request_returns_null_for_drawn_qml_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            cache = root / "cache"
            track = music / "Artless" / "track.flac"
            track.parent.mkdir(parents=True)
            track.touch()
            old_cache, old_music = artprovider.CACHE_DIR, artprovider.MUSIC_ROOT
            artprovider.CACHE_DIR = cache
            artprovider.MUSIC_ROOT = music
            try:
                provider = ArtProvider()
                folder = provider.requestImage(
                    "folder:Artless/track.flac", None, QSize())
            finally:
                artprovider.CACHE_DIR = old_cache
                artprovider.MUSIC_ROOT = old_music

            self.assertTrue(folder.isNull())

    def test_unprefixed_album_request_uses_native_source_path_by_default(self):
        provider = ArtProvider.__new__(ArtProvider)
        native = QImage(900, 900, QImage.Format.Format_RGB32)
        calls = []
        provider._full = lambda rel, requested, **kwargs: (
            calls.append((rel, requested, kwargs)) or (native, native.size()))

        result = provider._request_image_locked(
            "Albums/example.flac", None, QSize(720, 720))

        self.assertEqual(QSize(900, 900), result.size())
        self.assertEqual("Albums/example.flac", calls[0][0])
        self.assertEqual(QSize(720, 720), calls[0][1])

    def test_ambient_and_round_art_also_bypass_lossy_thumbnail_cache(self):
        provider = ArtProvider.__new__(ArtProvider)
        native = QImage(900, 900, QImage.Format.Format_ARGB32)
        native.fill(QColor("#884422"))
        calls = []
        provider._full = lambda rel, requested, **kwargs: (
            calls.append((rel, kwargs)) or (native, native.size()))

        ambient = provider._request_image_locked(
            "ambient:Albums/example.flac", None, QSize(800, 800))
        rounded = provider._request_image_locked(
            "round:Albums/example.flac", None, QSize(256, 256))

        self.assertFalse(ambient.isNull())
        self.assertFalse(rounded.isNull())
        self.assertEqual(2, len(calls))

    def test_full_artist_portrait_preserves_cached_rectangular_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_bio_cache = artprovider.BIO_CACHE_DIR
            artprovider.BIO_CACHE_DIR = Path(tmp)
            try:
                key = "a" * 40
                (Path(tmp) / f"{key}.img").write_bytes(
                    self._image_bytes(1200, 800))
                provider = ArtProvider()

                full = provider._request_image_locked(
                    f"portrait-full:{key}", None, QSize(900, 600))
                rounded = provider._request_image_locked(
                    f"portrait:{key}", None, QSize(600, 600))
            finally:
                artprovider.BIO_CACHE_DIR = old_bio_cache

        self.assertFalse(full.isNull())
        self.assertEqual(QSize(900, 600), full.size())
        self.assertEqual(255, full.pixelColor(0, 0).alpha())
        self.assertEqual(0, rounded.pixelColor(0, 0).alpha())

    def test_missing_full_artist_portrait_stays_null_for_semantic_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_bio_cache = artprovider.BIO_CACHE_DIR
            artprovider.BIO_CACHE_DIR = Path(tmp)
            try:
                result = ArtProvider()._request_image_locked(
                    "portrait-full:" + "b" * 40, None, QSize(512, 512))
            finally:
                artprovider.BIO_CACHE_DIR = old_bio_cache

        self.assertTrue(result.isNull())

    def test_folder_native_miss_remains_null_for_semantic_fallback(self):
        provider = ArtProvider.__new__(ArtProvider)
        calls = []

        def full(rel, requested, **kwargs):
            calls.append((rel, kwargs))
            return QImage(), QSize()

        provider._full = full
        result = provider._request_image_locked(
            "folder:Artless/track.flac", None, QSize(128, 128))

        self.assertTrue(result.isNull())
        self.assertFalse(calls[0][1]["fallback_on_miss"])

    def test_best_art_data_chooses_resolution_not_tag_order(self):
        small = self._image_bytes(96, 96)
        large = self._image_bytes(900, 900)

        self.assertEqual(large, artprovider._best_art_data((small, large)))

    def test_corrupt_larger_candidate_falls_through_to_valid_art(self):
        valid = self._image_bytes(300, 300)
        corrupt_large_header = self._image_bytes(1200, 1200)[:200]

        self.assertEqual(
            valid,
            artprovider._best_art_data((valid, corrupt_large_header)),
        )

    def test_decode_verification_scales_large_sources_to_bounded_raster(self):
        reader = MagicMock()
        reader.size.return_value = QSize(5000, 5000)
        verified = QImage(64, 64, QImage.Format.Format_RGB32)
        verified.fill(QColor("#884422"))
        reader.read.return_value = verified

        with patch("ampere.artprovider.QImageReader", return_value=reader):
            self.assertTrue(artprovider._art_decodes(b"encoded-image"))

        reader.setScaledSize.assert_called_once_with(QSize(64, 64))

    def test_embedded_art_chooses_largest_front_cover_not_first_picture(self):
        small_front = self._image_bytes(96, 96)
        large_front = self._image_bytes(900, 900)
        larger_back = self._image_bytes(1200, 1200)
        tagged_file = SimpleNamespace(pictures=[
            SimpleNamespace(type=3, data=small_front),
            SimpleNamespace(type=4, data=larger_back),
            SimpleNamespace(type=3, data=large_front),
        ])

        with patch("ampere.artprovider.FLAC", return_value=tagged_file):
            selected = artprovider._embedded_art(Path("album.flac"))

        self.assertEqual(large_front, selected)

    def test_safe_larger_folder_cover_replaces_low_resolution_embed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = root / "track.flac"
            cover = root / "cover.png"
            track.touch()
            cover.write_bytes(self._image_bytes(1000, 1000))
            low_embed = self._image_bytes(300, 300)

            with patch("ampere.artprovider._album_tag",
                       return_value="One Album"), patch(
                           "ampere.artprovider._embedded_art",
                           return_value=low_embed):
                selected = artprovider._art_bytes_for(track)

            self.assertEqual(1000 * 1000, artprovider._image_area(selected))

    def test_folder_cover_cannot_override_flat_multi_album_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.flac"
            second = root / "second.flac"
            first.touch()
            second.touch()
            (root / "cover.png").write_bytes(
                self._image_bytes(1000, 1000))
            low_embed = self._image_bytes(300, 300)

            def album_tag(path):
                return "First" if path == first else "Second"

            with patch("ampere.artprovider._album_tag",
                       side_effect=album_tag), patch(
                           "ampere.artprovider._embedded_art",
                           return_value=low_embed):
                selected = artprovider._art_bytes_for(first)

            self.assertEqual(low_embed, selected)

    def test_unverified_parent_cover_is_not_a_last_chance_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.flac"
            other = root / "other.flac"
            target.touch()
            other.touch()
            (root / "cover.png").write_bytes(
                self._image_bytes(1200, 1200))

            albums = {target: "Target", other: "Other"}
            with patch("ampere.artprovider._album_tag",
                       side_effect=lambda path: albums[path]), patch(
                           "ampere.artprovider._embedded_art",
                           return_value=None), patch(
                               "ampere.artprovider._deezer_exact_art",
                               return_value=None), patch(
                                   "ampere.artprovider._spotify_exact_art",
                                   return_value=None):
                selected = artprovider._art_bytes_for(target)

            self.assertIsNone(selected)

    def test_higher_resolution_same_album_sibling_is_used_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            low_track = root / "low.flac"
            other_album = root / "other.flac"
            high_track = root / "high.flac"
            for track in (low_track, other_album, high_track):
                track.touch()
            low_embed = self._image_bytes(300, 300)
            high_embed = self._image_bytes(1000, 1000)

            albums = {
                low_track: "Wanted Album",
                high_track: "Wanted Album",
                other_album: "Other Album",
            }
            embeds = {low_track: low_embed, high_track: high_embed}

            def media(path, easy=True):
                return {"album": [albums[path]]}

            with patch("ampere.artprovider.MutagenFile",
                       side_effect=media), patch(
                           "ampere.artprovider._embedded_art",
                           side_effect=lambda path: embeds.get(path)):
                selected = artprovider._art_bytes_for(low_track)

            self.assertEqual(high_embed, selected)

    def test_adequate_wrong_embed_does_not_hide_better_same_album_art(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.flac"
            same_album = root / "same-album.flac"
            other_album = root / "other-album.flac"
            for track in (target, same_album, other_album):
                track.touch()
            wrong_but_large_enough = self._image_bytes(600, 600, "#cc2266")
            correct_album_art = self._image_bytes(1000, 1000, "#335522")
            unrelated_art = self._image_bytes(1400, 1400, "#2233aa")

            albums = {
                target: "Wanted Album",
                same_album: "Wanted Album",
                other_album: "Other Album",
            }
            embeds = {
                target: wrong_but_large_enough,
                same_album: correct_album_art,
                other_album: unrelated_art,
            }

            def media(path, easy=True):
                return {"album": [albums[path]]}

            with patch("ampere.artprovider.MutagenFile",
                       side_effect=media), patch(
                           "ampere.artprovider._embedded_art",
                           side_effect=lambda path: embeds[path]):
                selected = artprovider._art_bytes_for(target)

            self.assertEqual(correct_album_art, selected)

    def test_exact_spotify_id_can_raise_a_low_resolution_local_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "track.flac"
            track.touch()
            low_embed = self._image_bytes(300, 300, "#332211")
            exact_remote = self._image_bytes(640, 640, "#664422")

            with patch("ampere.artprovider._embedded_art",
                       return_value=low_embed), patch(
                           "ampere.artprovider._safe_folder_art",
                           return_value=None), patch(
                           "ampere.artprovider._same_album_sibling_art",
                           return_value=None), patch(
                           "ampere.artprovider._spotify_exact_art",
                           return_value=exact_remote):
                selected = artprovider._art_bytes_for(track, 1536)

            self.assertEqual((640, 640), artprovider._image_dimensions(selected))

    def test_exact_deezer_id_can_raise_a_low_resolution_local_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "track.flac"
            track.touch()
            low_embed = self._image_bytes(150, 150, "#332211")
            exact_remote = self._image_bytes(1000, 1000, "#664422")

            with patch("ampere.artprovider._embedded_art",
                       return_value=low_embed), patch(
                           "ampere.artprovider._safe_folder_art",
                           return_value=None), patch(
                               "ampere.artprovider._same_album_sibling_art",
                               return_value=None), patch(
                                   "ampere.artprovider._deezer_exact_art",
                                   return_value=exact_remote), patch(
                                       "ampere.artprovider._spotify_exact_art") as spotify:
                selected = artprovider._art_bytes_for(track, 1536)

            self.assertEqual((1000, 1000),
                             artprovider._image_dimensions(selected))
            spotify.assert_not_called()

    def test_larger_local_art_avoids_remote_provider_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "track.flac"
            track.touch()
            local = self._image_bytes(1400, 1400)

            with patch("ampere.artprovider._embedded_art",
                       return_value=local), patch(
                           "ampere.artprovider._safe_folder_art",
                           return_value=None), patch(
                               "ampere.artprovider._same_album_sibling_art",
                               return_value=None), patch(
                                   "ampere.artprovider._deezer_exact_art") as deezer, patch(
                                       "ampere.artprovider._spotify_exact_art") as spotify:
                selected = artprovider._art_bytes_for(track, 1536)

            self.assertEqual(local, selected)
            deezer.assert_not_called()
            spotify.assert_not_called()

    def test_spotify_remains_fallback_when_deezer_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "track.flac"
            track.touch()
            local = self._image_bytes(300, 300)
            spotify = self._image_bytes(640, 640)

            with patch("ampere.artprovider._embedded_art",
                       return_value=local), patch(
                           "ampere.artprovider._safe_folder_art",
                           return_value=None), patch(
                               "ampere.artprovider._same_album_sibling_art",
                               return_value=None), patch(
                                   "ampere.artprovider._deezer_exact_art",
                                   return_value=None), patch(
                                       "ampere.artprovider._spotify_exact_art",
                                       return_value=spotify):
                selected = artprovider._art_bytes_for(track, 1536)

            self.assertEqual((640, 640),
                             artprovider._image_dimensions(selected))

    def test_deezer_exact_art_validates_ids_and_caches_xl_raster(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache = artprovider.CACHE_DIR
            artprovider.CACHE_DIR = Path(tmp) / "cache"
            track = Path(tmp) / "track.flac"
            track.touch()
            exact_remote = self._image_bytes(1000, 1000, "#886633")
            track_id = "350171311"
            album_id = "39949511"
            calls = []

            def read(url, allowed_hosts, max_bytes):
                calls.append((url, allowed_hosts, max_bytes))
                if "api.deezer.com" in url:
                    return json.dumps({
                        "id": int(album_id),
                        "cover_xl": (
                            "https://cdn-images.dzcdn.net/images/cover/"
                            "exact/1000x1000.jpg"
                        ),
                    }).encode()
                return exact_remote

            try:
                with patch("ampere.artprovider._deezer_track_id",
                           return_value=track_id), patch(
                               "ampere.artprovider._deezer_album_id",
                               return_value=album_id), patch(
                                   "ampere.artprovider._read_trusted_https",
                                   side_effect=read):
                    first = artprovider._deezer_exact_art(track)
                    second = artprovider._deezer_exact_art(track)
            finally:
                artprovider.CACHE_DIR = old_cache

            self.assertEqual(exact_remote, first)
            self.assertEqual(exact_remote, second)
            self.assertEqual(2, len(calls))

    def test_deezer_returned_id_mismatch_fails_closed(self):
        track_id = "350171311"
        album_id = "39949511"
        failure_key = f"deezer-album:{album_id}"
        artprovider._REMOTE_ART_FAILURES.discard(failure_key)
        with tempfile.TemporaryDirectory() as tmp:
            old_cache = artprovider.CACHE_DIR
            artprovider.CACHE_DIR = Path(tmp) / "cache"
            try:
                with patch("ampere.artprovider._deezer_track_id",
                           return_value=track_id), patch(
                               "ampere.artprovider._deezer_album_id",
                               return_value=album_id), patch(
                                   "ampere.artprovider._read_trusted_https",
                                   return_value=json.dumps({
                                       "id": 1,
                                       "cover_xl": "https://example.com/x.jpg",
                                   }).encode()):
                    self.assertIsNone(
                        artprovider._deezer_exact_art(Path("track.flac")))
            finally:
                artprovider.CACHE_DIR = old_cache
                artprovider._REMOTE_ART_FAILURES.discard(failure_key)

    def test_remote_reader_rejects_untrusted_redirects_and_oversized_data(self):
        class Response:
            def __init__(self, final_url, payload):
                self.final_url = final_url
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return self.final_url

            def read(self, _limit):
                return self.payload

        with patch("ampere.artprovider.urlopen", return_value=Response(
                "https://example.com/wrong.jpg", b"image")):
            with self.assertRaisesRegex(ValueError, "redirect"):
                artprovider._read_trusted_https(
                    "https://cdn-images.dzcdn.net/right.jpg",
                    artprovider._DEEZER_IMAGE_HOSTS,
                    8,
                )

        with patch("ampere.artprovider.urlopen", return_value=Response(
                "https://cdn-images.dzcdn.net/right.jpg", b"123456789")):
            with self.assertRaisesRegex(ValueError, "too large"):
                artprovider._read_trusted_https(
                    "https://cdn-images.dzcdn.net/right.jpg",
                    artprovider._DEEZER_IMAGE_HOSTS,
                    8,
                )

    def test_exact_provider_ids_are_read_from_id3_txxx_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "track.mp3"
            tags = ID3()
            tags.add(TXXX(
                encoding=3, desc="DEEZER_TRACK_ID", text=["350171311"]))
            tags.add(TXXX(
                encoding=3, desc="SPOTIFY_TRACK_ID",
                text=["3v275M3Us9etGzH6fmvGmz"]))
            tags.save(track)

            self.assertEqual("350171311",
                             artprovider._deezer_track_id(track))
            self.assertEqual("3v275M3Us9etGzH6fmvGmz",
                             artprovider._spotify_track_id(track))

    def test_gallery_uses_full_resolution_provider_route(self):
        source = (Path(__file__).parents[1] / "qml" /
                  "GalleryNowPlayingView.qml").read_text(encoding="utf-8")

        self.assertIn("decodeSize: 1536", source)
        self.assertIn('"image://art/full:"', source)

    def test_spotify_exact_art_validates_host_and_caches_largest_raster(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache = artprovider.CACHE_DIR
            artprovider.CACHE_DIR = Path(tmp) / "cache"
            track = Path(tmp) / "track.flac"
            track.touch()
            exact_remote = self._image_bytes(640, 640, "#886633")
            track_id = "3v275M3Us9etGzH6fmvGmz"
            calls = []

            def read(url, allowed_hosts, max_bytes):
                calls.append((url, allowed_hosts, max_bytes))
                if "open.spotify.com/oembed" in url:
                    return json.dumps({
                        "provider_name": "Spotify",
                        "thumbnail_url": (
                            "https://image-cdn-fa.spotifycdn.com/image/"
                            "ab67616d00001e0297ad7eb2a1b4ef7c71f23d0e"
                        ),
                    }).encode()
                self.assertIn("ab67616d0000b273", url)
                return exact_remote

            try:
                with patch("ampere.artprovider._spotify_track_id",
                           return_value=track_id), patch(
                               "ampere.artprovider._read_trusted_https",
                               side_effect=read):
                    first = artprovider._spotify_exact_art(track)
                    second = artprovider._spotify_exact_art(track)
            finally:
                artprovider.CACHE_DIR = old_cache

            self.assertEqual(exact_remote, first)
            self.assertEqual(exact_remote, second)
            self.assertEqual(2, len(calls))

    def test_spotify_external_fallback_rejects_untrusted_image_hosts(self):
        self.assertEqual(
            "",
            artprovider._largest_spotify_thumbnail(
                "https://example.com/image/"
                "ab67616d00001e0297ad7eb2a1b4ef7c71f23d0e"
            ),
        )

    def test_failed_spotify_id_is_attempted_once_per_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cache = artprovider.CACHE_DIR
            artprovider.CACHE_DIR = Path(tmp) / "cache"
            track = Path(tmp) / "track.flac"
            track.touch()
            track_id = "3v275M3Us9etGzH6fmvGmz"
            artprovider._REMOTE_ART_FAILURES.discard(track_id)
            try:
                with patch("ampere.artprovider._spotify_track_id",
                           return_value=track_id), patch(
                               "ampere.artprovider._read_trusted_https",
                               side_effect=OSError("offline")) as reader:
                    self.assertIsNone(artprovider._spotify_exact_art(track))
                    self.assertIsNone(artprovider._spotify_exact_art(track))
                    self.assertEqual(1, reader.call_count)
            finally:
                artprovider._REMOTE_ART_FAILURES.discard(track_id)
                artprovider.CACHE_DIR = old_cache

    def test_cache_key_includes_source_selection_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            music = Path(tmp)
            track = music / "track.flac"
            track.touch()
            old_music = artprovider.MUSIC_ROOT
            artprovider.MUSIC_ROOT = music
            try:
                with patch.object(artprovider, "ART_CACHE_VERSION", "v1"):
                    first_key = artprovider._cache_key("track.flac")
                with patch.object(artprovider, "ART_CACHE_VERSION", "v2"):
                    second_key = artprovider._cache_key("track.flac")
            finally:
                artprovider.MUSIC_ROOT = old_music

            self.assertNotEqual(first_key, second_key)

    def test_cache_key_changes_when_folder_cover_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            music.mkdir()
            track = music / "track.flac"
            cover = music / "cover.jpg"
            track.touch()
            cover.write_bytes(b"first")
            old_music = artprovider.MUSIC_ROOT
            artprovider.MUSIC_ROOT = music
            try:
                first_key = artprovider._cache_key("track.flac")
                cover.write_bytes(b"replacement-is-larger")
                second_key = artprovider._cache_key("track.flac")
            finally:
                artprovider.MUSIC_ROOT = old_music

            self.assertNotEqual(first_key, second_key)

    def test_cache_key_changes_when_same_album_sibling_is_retagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            music.mkdir()
            track = music / "track.flac"
            sibling = music / "sibling.flac"
            track.write_bytes(b"track")
            sibling.write_bytes(b"small-art-tag")
            old_music = artprovider.MUSIC_ROOT
            artprovider.MUSIC_ROOT = music
            try:
                first_key = artprovider._cache_key("track.flac")
                sibling.write_bytes(b"replacement-high-resolution-art-tag")
                second_key = artprovider._cache_key("track.flac")
            finally:
                artprovider.MUSIC_ROOT = old_music

            self.assertNotEqual(first_key, second_key)


if __name__ == "__main__":
    unittest.main()
