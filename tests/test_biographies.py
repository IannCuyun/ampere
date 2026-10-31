import json
import tempfile
import unittest
from pathlib import Path

from ampere.biographies import (
    BiographyService, EMPTY_BIO, PORTRAIT_SCHEMA_VERSION,
    PORTRAIT_TARGET_WIDTH,
)


class BiographyServiceTests(unittest.TestCase):
    def test_cache_peek_returns_only_current_profiles_with_live_portraits(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = BiographyService(tmp)
            cache = service._cache_file("Example")
            cache.parent.mkdir(parents=True, exist_ok=True)
            profile = {
                "found": True, "bio": "Bio", "url": "https://example",
                "source": "Wikipedia", "portrait": "a" * 40,
                "imageRemote": "https://upload.wikimedia.org/example.jpg",
                "imageVersion": PORTRAIT_SCHEMA_VERSION,
                "imageOrigin": "Wikimedia", "portraitRetryable": False,
            }
            cache.write_text(json.dumps(profile))
            portrait = Path(tmp) / ("a" * 40 + ".img")
            portrait.write_bytes(b"portrait")

            self.assertEqual(profile, service.peek_cached("Example"))
            portrait.unlink()
            self.assertIsNone(service.peek_cached("Example"))

    def test_cache_peek_ignores_legacy_profiles_without_refetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            service = BiographyService(
                tmp, getter=lambda url: calls.append(url) or {})
            cache = service._cache_file("Example")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({
                "found": True, "bio": "Bio", "url": "https://example",
                "source": "Wikipedia", "portrait": "b" * 40,
                "imageRemote": "https://upload.wikimedia.org/example.jpg",
                "imageVersion": PORTRAIT_SCHEMA_VERSION - 1,
            }))
            (Path(tmp) / ("b" * 40 + ".img")).write_bytes(b"portrait")

            self.assertIsNone(service.peek_cached("Example"))
            self.assertEqual([], calls)

    def test_direct_musical_summary_is_accepted(self):
        def getter(url):
            return {"extract": "Example is an American singer and producer.",
                    "content_urls": {"desktop": {"page": "https://example"}}}
        result = BiographyService("/unused", getter=getter).fetch("Example")
        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "Wikipedia")

    def test_disambiguation_and_nonmusical_namesakes_are_rejected(self):
        def getter(url):
            if "w/api.php" in url:
                return {"query": {"search": []}}
            return {"extract": "Example is a town and civil parish.",
                    "type": "standard"}
        self.assertEqual(BiographyService("/unused", getter=getter).fetch("Example"),
                         EMPTY_BIO)

    def test_search_prefers_exact_named_result_and_filters_lists(self):
        seen = []
        def getter(url):
            seen.append(url)
            if "w/api.php" in url:
                return {"query": {"search": [
                    {"title": "List of Example songs"},
                    {"title": "Example discography"},
                    {"title": "The Example Ensemble"}]}}
            if "The_Example_Ensemble" in url:
                return {"extract": "The Example Ensemble is a music duo."}
            raise OSError("no direct page")
        result = BiographyService("/unused", getter=getter).fetch("Example")
        self.assertTrue(result["found"])
        self.assertTrue(any("The_Example_Ensemble" in url
                            or "The+Example+Ensemble" in url
                            for url in seen))

    def test_valid_cache_avoids_network_and_corrupt_cache_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def getter(url):
                calls.append(url)
                return {"extract": "Example is a singer."}
            service = BiographyService(tmp, getter=getter)
            cache = service._cache_file("Example")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text("broken")
            first = service.get("Example")
            self.assertTrue(first["found"])
            self.assertEqual(json.loads(cache.read_text()), first)
            count = len(calls)
            second = service.get("example")
            self.assertEqual(second, first)
            self.assertEqual(len(calls), count)
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_transient_negative_result_is_not_cached_and_can_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            online = [False]
            calls = []

            def getter(_url):
                calls.append(online[0])
                if not online[0]:
                    raise OSError("offline")
                return {"extract": "Example is a singer and producer."}

            service = BiographyService(tmp, getter=getter)
            unavailable = service.get("Example")
            self.assertFalse(unavailable["found"])
            self.assertTrue(unavailable["portraitRetryable"])
            self.assertFalse(service._cache_file("Example").exists())

            online[0] = True
            recovered = service.get("Example")
            self.assertTrue(recovered["found"])
            self.assertTrue(service._cache_file("Example").exists())
            self.assertTrue(calls)

    def test_legacy_negative_cache_is_ignored_and_replaced_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = BiographyService(
                tmp, getter=lambda _url: {
                    "extract": "Example is a musician and composer."})
            cache = service._cache_file("Example")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(EMPTY_BIO))

            result = service.get("Example")

            self.assertTrue(result["found"])
            self.assertEqual(result, json.loads(cache.read_text()))

    def test_url_loader_refuses_untrusted_hosts_before_opening(self):
        with self.assertRaises(ValueError):
            BiographyService._get_json("https://example.com/wiki/Artist")
        with self.assertRaises(ValueError):
            BiographyService._get_json("http://en.wikipedia.org/wiki/Artist")

    def test_wikimedia_portrait_is_cached_under_an_opaque_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote = "https://upload.wikimedia.org/example/artist.jpg"
            service = BiographyService(
                tmp,
                getter=lambda _url: {
                    "extract": "Example is a singer and musician.",
                    "thumbnail": {"source": remote},
                },
                image_getter=lambda url: b"portrait" if url == remote else b"",
            )

            result = service.get("Example")

            self.assertRegex(result["portrait"], r"^[0-9a-f]{40}$")
            self.assertEqual(
                b"portrait",
                (Path(tmp) / f"{result['portrait']}.img").read_bytes())

    def test_page_image_requests_a_large_bounded_wikimedia_derivative(self):
        small = "https://upload.wikimedia.org/example/330px-artist.jpg"
        large = "https://upload.wikimedia.org/example/1920px-artist.jpg"
        seen = []

        def getter(url):
            seen.append(url)
            if "prop=pageimages" in url:
                return {"query": {"pages": {"1": {
                    "title": "Example",
                    "thumbnail": {"source": large},
                }}}}
            return {
                "extract": "Example is a singer and musician.",
                "thumbnail": {"source": small},
            }

        result = BiographyService("/unused", getter=getter).fetch("Example")

        self.assertEqual(large, result["imageRemote"])
        self.assertEqual(PORTRAIT_SCHEMA_VERSION, result["imageVersion"])
        self.assertTrue(any(
            f"pithumbsize={PORTRAIT_TARGET_WIDTH}" in url for url in seen))

    def test_wikipedia_canonical_lead_image_is_used_without_gallery_scoring(self):
        lead = "https://upload.wikimedia.org/example/band.jpg"
        album = "https://upload.wikimedia.org/example/square-album.jpg"

        def getter(url):
            if "prop=pageimages" in url:
                return {"query": {"pages": {"1": {
                    "title": "Example",
                    "thumbnail": {"source": lead},
                    "unrelatedGalleryImage": {"source": album},
                }}}}
            return {"extract": "Example is a band and musical group."}

        result = BiographyService("/unused", getter=getter).fetch("Example")

        self.assertEqual(lead, result["imageRemote"])

    def test_deezer_exact_match_supplies_xl_art_when_wikipedia_has_none(self):
        remote = ("https://cdn-images.dzcdn.net/images/artist/"
                  "abc/1000x1000-000000-80-0-0.jpg")

        def getter(url):
            if "api.deezer.com" in url:
                return {"data": [
                    {"name": "Example Tribute", "picture_xl": "https://wrong"},
                    {"name": " Example  Artist ", "picture_xl": remote},
                ]}
            if "theaudiodb.com" in url:
                # a music database knows the act but carries no image, which
                # is what admits the image provider (2026-08-22)
                return {"artists": [{"strArtist": "Example Artist",
                                     "strArtistThumb": ""}]}
            if "w/api.php" in url:
                return {"query": {"search": []}}
            return {"extract": "Example Artist is a visual arts collective."}

        result = BiographyService("/unused", getter=getter).fetch(
            "Example Artist")

        self.assertFalse(result["found"])
        self.assertEqual(remote, result["imageRemote"])
        self.assertEqual("Deezer", result["imageOrigin"])
        self.assertFalse(result["portraitRetryable"])

    def test_deezer_namesake_and_placeholder_art_are_rejected(self):
        placeholder = ("https://cdn-images.dzcdn.net/images/artist//"
                       "1000x1000-000000-80-0-0.jpg")

        def getter(url):
            if "api.deezer.com" in url:
                return {"data": [
                    {"name": "Example Ensemble", "picture_xl": "https://wrong"},
                    {"name": "Example", "picture_xl": placeholder},
                ]}
            if "w/api.php" in url:
                return {"query": {"search": []}}
            return {}

        result = BiographyService("/unused", getter=getter).fetch("Example")

        self.assertFalse(result["found"])
        self.assertEqual("", result["imageRemote"])
        self.assertFalse(result["portraitRetryable"])

    def test_portrait_only_profile_is_cached_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote = ("https://cdn-images.dzcdn.net/images/artist/"
                      "abc/1000x1000-000000-80-0-0.jpg")
            calls = []

            def getter(url):
                calls.append(url)
                if "api.deezer.com" in url:
                    return {"data": [{"name": "Example", "picture_xl": remote}]}
                if "theaudiodb.com" in url:
                    return {"artists": [{"strArtist": "Example",
                                         "strArtistThumb": ""}]}
                if "w/api.php" in url:
                    return {"query": {"search": []}}
                return {}

            service = BiographyService(
                tmp, getter=getter, image_getter=lambda _url: b"portrait")
            first = service.get("Example")
            count = len(calls)
            second = service.get("Example")

            self.assertFalse(first["found"])
            self.assertRegex(first["portrait"], r"^[0-9a-f]{40}$")
            self.assertEqual(first, second)
            self.assertEqual(count, len(calls))

    def test_portrait_cache_prunes_oldest_images_to_bounded_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = BiographyService(
                tmp, image_getter=lambda _url: b"1234",
                portrait_cache_bytes=6)
            first = service._attach_portrait({
                "imageRemote": "https://upload.wikimedia.org/first.jpg"})
            second = service._attach_portrait({
                "imageRemote": "https://upload.wikimedia.org/second.jpg"})

            self.assertFalse(
                (Path(tmp) / f"{first['portrait']}.img").exists())
            self.assertTrue(
                (Path(tmp) / f"{second['portrait']}.img").exists())

    def test_portrait_cache_reclaims_only_unreferenced_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = BiographyService(
                root, image_getter=lambda _url: b"new",
                portrait_cache_bytes=1024)
            referenced = "a" * 40
            orphan = "b" * 40
            (root / f"{referenced}.img").write_bytes(b"referenced")
            (root / f"{orphan}.img").write_bytes(b"orphan")
            service._cache_file("Existing").write_text(json.dumps({
                "found": True, "bio": "", "url": "", "source": "",
                "portrait": referenced,
            }))

            attached = service._attach_portrait({
                "imageRemote": "https://upload.wikimedia.org/new.jpg",
            })
            in_flight = root / f"{attached['portrait']}.img"

            self.assertTrue((root / f"{referenced}.img").exists())
            self.assertFalse((root / f"{orphan}.img").exists())
            self.assertTrue(in_flight.exists())

    def test_pre_high_resolution_cache_is_refreshed(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {
                "found": True, "bio": "Old bio", "url": "", "source": "Wikipedia",
                "portrait": "old", "imageRemote": "https://upload.wikimedia.org/old.jpg",
            }
            calls = []

            def getter(url):
                calls.append(url)
                return {"extract": "Example is a musician and composer."}

            service = BiographyService(tmp, getter=getter)
            cache = service._cache_file("Example")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(old))

            result = service.get("Example")

            self.assertTrue(calls)
            self.assertEqual(PORTRAIT_SCHEMA_VERSION, result["imageVersion"])

    def test_image_loader_refuses_non_wikimedia_hosts(self):
        with self.assertRaises(ValueError):
            BiographyService._get_image("https://example.com/artist.jpg")
        with self.assertRaises(ValueError):
            BiographyService._get_image(
                "http://upload.wikimedia.org/artist.jpg")


if __name__ == "__main__":
    unittest.main()
