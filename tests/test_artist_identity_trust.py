"""Portrait and biography must belong to the artist, or be absent.

SPEC UNDESIGNED #17 / ROADMAP 1.3. Two real failure cases drive this: the
Adam Warren screen (a same-name stranger) and Tech N9ne Collabos (where the
provider's own artist image is a record jacket).
"""
import tempfile
import unittest
from unittest.mock import patch

from ampere.artists import set_aliases
from ampere.biographies import BiographyService


class NamesakeRejectionTests(unittest.TestCase):
    """A stranger who shares the name is never presented as the artist."""

    def service(self, pages):
        def getter(url):
            for key, payload in pages.items():
                if key in url:
                    return payload
            return {}
        return BiographyService(tempfile.mkdtemp(), getter=getter)

    def test_a_disambiguation_page_is_not_a_biography(self):
        svc = self.service({"page/summary/Adam_Warren": {
            "type": "disambiguation",
            "extract": "Adam Warren may refer to: Adam Warren (comics)..."}})
        info, _ = svc._fetch_wikipedia("Adam Warren")
        self.assertIsNone(info)

    def test_a_non_musical_article_is_refused(self):
        svc = self.service({"page/summary/Adam_Warren": {
            "type": "standard",
            "extract": "Adam Warren is an American comic book writer and "
                       "artist known for his work on Empowered."}})
        info, _ = svc._fetch_wikipedia("Adam Warren")
        self.assertIsNone(info)

    def test_a_musical_article_is_accepted(self):
        svc = self.service({"page/summary/Tech_N9ne": {
            "type": "standard",
            "extract": "Aaron Dontez Yates, known as Tech N9ne, is an "
                       "American rapper and songwriter."}})
        info, _ = svc._fetch_wikipedia("Tech N9ne")
        self.assertIsNotNone(info)
        self.assertIn("rapper", info["bio"])

    def test_an_empty_extract_is_never_trusted(self):
        svc = self.service({"page/summary/Nobody": {"type": "standard",
                                                    "extract": ""}})
        self.assertIsNone(svc._fetch_wikipedia("Nobody")[0])


class DeezerPortraitTrustTests(unittest.TestCase):
    """The image provider is trusted only on an exact identity match."""

    def service(self, payload):
        return BiographyService(tempfile.mkdtemp(), getter=lambda url: payload)

    def test_a_near_match_never_supplies_a_portrait(self):
        svc = self.service({"data": [
            {"name": "Tech N9ne Collabos feat. Krizz Kaliko",
             "picture_xl": "https://cdn-images.dzcdn.net/images/artist/x/1.jpg"}]})
        self.assertEqual(("", False), svc._deezer_artist_image("Tech N9ne"))

    def test_an_exact_match_supplies_its_portrait(self):
        svc = self.service({"data": [
            {"name": "Tech N9ne",
             "picture_xl": "https://cdn-images.dzcdn.net/images/artist/x/1.jpg"}]})
        remote, retry = svc._deezer_artist_image("Tech N9ne")
        self.assertTrue(remote)
        self.assertFalse(retry)

    def test_an_untrusted_host_is_rejected(self):
        svc = self.service({"data": [
            {"name": "Tech N9ne",
             "picture_xl": "https://example.invalid/photo.jpg"}]})
        self.assertEqual(("", False), svc._deezer_artist_image("Tech N9ne"))

    def test_an_empty_provider_path_is_rejected(self):
        svc = self.service({"data": [
            {"name": "Tech N9ne",
             "picture_xl": "https://cdn-images.dzcdn.net/images/artist//1.jpg"}]})
        self.assertEqual(("", False), svc._deezer_artist_image("Tech N9ne"))


class AliasedLookupTests(unittest.TestCase):
    """Combining an alias must actually repair its portrait.

    Membership resolved through the alias table while the provider chain did
    not, so `Tech N9ne Collabos` kept querying — and caching — its own wrong
    image even after Iann combined it.
    """

    def tearDown(self):
        set_aliases({})

    def test_the_lookup_asks_for_the_canonical_identity(self):
        from ampere.mpdclient import Backend
        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        asked, emitted = [], []

        class Fake:
            def get(self, name):
                asked.append(name)
                return {"found": True}

        backend = Backend.__new__(Backend)
        backend._biographies = Fake()
        backend.artistBioReady = type(
            "S", (), {"emit": lambda _s, name, info: emitted.append(name)})()
        Backend._bio_worker(backend, "Tech N9ne Collabos")

        self.assertEqual(["Tech N9ne"], asked)
        # the reply still answers the question that was asked
        self.assertEqual(["Tech N9ne Collabos"], emitted)

    def test_an_unaliased_artist_is_unaffected(self):
        from ampere.mpdclient import Backend
        asked = []

        class Fake:
            def get(self, name):
                asked.append(name)
                return {}

        backend = Backend.__new__(Backend)
        backend._biographies = Fake()
        backend.artistBioReady = type("S", (), {"emit": lambda *_a: None})()
        Backend._bio_worker(backend, "IC3PEAK")
        self.assertEqual(["IC3PEAK"], asked)


if __name__ == "__main__":
    unittest.main()


class PortraitChainTests(unittest.TestCase):
    """Portrait order, after reading Lollypop's chain (Iann, 2026-08-22).

    Wikipedia is authoritative for the BIOGRAPHY but not for the face: its
    lead image for Travis Scott is his signature, and for many acts it is a
    logo or a record sleeve. A music database's artist image is a portrait by
    definition, so it goes first.
    """

    THUMB = "https://r2.theaudiodb.com/images/media/artist/thumb/x.jpg"
    FANART = "https://r2.theaudiodb.com/images/media/artist/fanart/x.jpg"

    def service(self, pages):
        def getter(url):
            for key, payload in pages.items():
                if key in url:
                    return payload
            return {}
        return BiographyService(tempfile.mkdtemp(), getter=getter)

    def wiki(self, extract="An American rapper and songwriter.", image=True):
        page = {"type": "standard", "extract": extract}
        if image:
            page["originalimage"] = {
                "source": "https://upload.wikimedia.org/signature.svg"}
        return page

    def test_a_music_database_portrait_outranks_the_encyclopaedia_image(self):
        svc = self.service({
            "page/summary": self.wiki(),
            "theaudiodb.com": {"artists": [
                {"strArtist": "Travis Scott", "strArtistThumb": self.THUMB}]},
        })
        result = svc.fetch("Travis Scott")
        self.assertEqual("TheAudioDB", result["imageOrigin"])
        self.assertEqual(self.THUMB, result["imageRemote"])
        # the biography still comes from the encyclopaedia
        self.assertTrue(result["found"])

    def test_a_portrait_is_preferred_over_a_wide_promotional_shot(self):
        svc = self.service({"theaudiodb.com": {"artists": [
            {"strArtist": "Tech N9ne", "strArtistThumb": self.THUMB,
             "strArtistFanart": self.FANART}]}})
        self.assertEqual(self.THUMB, svc.fetch("Tech N9ne")["imageRemote"])

    def test_fanart_is_used_when_there_is_no_portrait(self):
        svc = self.service({"theaudiodb.com": {"artists": [
            {"strArtist": "Tech N9ne", "strArtistThumb": "",
             "strArtistFanart": self.FANART}]}})
        self.assertEqual(self.FANART, svc.fetch("Tech N9ne")["imageRemote"])

    def test_a_namesake_at_the_provider_supplies_nothing(self):
        svc = self.service({"theaudiodb.com": {"artists": [
            {"strArtist": "Travis Scott Jr", "strArtistThumb": self.THUMB}]}})
        self.assertEqual("", svc.fetch("Travis Scott")["imageRemote"])

    def test_an_untrusted_image_host_is_refused(self):
        svc = self.service({"theaudiodb.com": {"artists": [
            {"strArtist": "Tech N9ne",
             "strArtistThumb": "https://example.invalid/x.jpg"}]}})
        self.assertEqual("", svc.fetch("Tech N9ne")["imageRemote"])

    def test_an_artist_with_no_article_still_gets_a_portrait(self):
        # Молчат Дома has no English article; Lollypop-style fallback stands
        svc = self.service({"theaudiodb.com": {"artists": [
            {"strArtist": "Molchat Doma", "strArtistThumb": self.THUMB}]}})
        result = svc.fetch("Molchat Doma")
        self.assertFalse(result["found"])
        self.assertEqual(self.THUMB, result["imageRemote"])


class UncorroboratedPortraitTests(unittest.TestCase):
    """A face is never shown for a name nothing can vouch for.

    Deezer returns a picture for any string typed at it, which is how
    "Adam Warren" — a comics writer, a pitcher and a cricketer, with no
    musical article anywhere — acquired a portrait.
    """

    DEEZER = "https://cdn-images.dzcdn.net/images/artist/abc/1000x1000.jpg"

    def service(self, pages):
        def getter(url):
            for key, payload in pages.items():
                if key in url:
                    return payload
            return {}
        return BiographyService(tempfile.mkdtemp(), getter=getter)

    def test_an_unverified_name_gets_no_portrait(self):
        svc = self.service({
            "page/summary/Adam_Warren": {"type": "disambiguation",
                                         "extract": "may refer to"},
            "theaudiodb.com": {"artists": None},
            "api.deezer.com": {"data": [
                {"name": "Adam Warren", "picture_xl": self.DEEZER}]},
        })
        result = svc.fetch("Adam Warren")
        self.assertEqual("", result["imageRemote"])
        self.assertEqual("", result["imageOrigin"])

    def test_a_verified_biography_admits_the_image_provider(self):
        svc = self.service({
            "page/summary": {"type": "standard",
                             "extract": "A British rock band."},
            "theaudiodb.com": {"artists": None},
            "api.deezer.com": {"data": [
                {"name": "Wet Leg", "picture_xl": self.DEEZER}]},
        })
        self.assertEqual("Deezer", svc.fetch("Wet Leg")["imageOrigin"])

    def test_a_music_database_match_admits_it_too(self):
        svc = self.service({
            "theaudiodb.com": {"artists": [
                {"strArtist": "Some Act", "strArtistThumb": ""}]},
            "api.deezer.com": {"data": [
                {"name": "Some Act", "picture_xl": self.DEEZER}]},
        })
        self.assertEqual("Deezer", svc.fetch("Some Act")["imageOrigin"])
