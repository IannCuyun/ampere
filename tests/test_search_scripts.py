"""Non-Latin titles must be findable — in their own script and by romanization.

Before this, `normalize` stripped every character outside [a-z0-9], so a
Japanese, Chinese, Cyrillic or Greek title normalized to the empty string and
could not be found even by typing it exactly (Iann, 2026-08-21).
"""
import unittest

from ampere.search import build_index, normalize, romanizations, search, searchable

SONGS = [
    {"file": "JP/ningen.flac", "title": "無情のスキャット",
     "artist": "人間椅子", "album": "苦悶の宴"},
    {"file": "RU/vitas.flac", "title": "Опера №2",
     "artist": "Витас", "album": "Философия чуда"},
    {"file": "CN/jay.flac", "title": "稻香", "artist": "周杰倫", "album": "魔杰座"},
    {"file": "US/hyaena.flac", "title": "HYAENA",
     "artist": "Travis Scott", "album": "UTOPIA"},
]


class NonLatinNormalizeTests(unittest.TestCase):
    def test_non_latin_survives_normalization(self):
        for text in ("人間椅子", "Витас", "무한", "Ωμέγα"):
            self.assertTrue(normalize(text), f"{text} normalized away")

    def test_latin_normalization_is_unchanged(self):
        self.assertEqual(normalize("Can't Hold Us"), "cant hold us")
        self.assertEqual(normalize("B.Y.O.B.", fused=True), "byob")
        self.assertEqual(normalize("FE!N"), "fein")
        self.assertEqual(normalize("Beyoncé"), "beyonce")
        self.assertEqual(normalize("six foot seven"), "6 foot 7")

    def test_han_gets_both_japanese_and_mandarin_readings(self):
        forms = romanizations("人間椅子")
        self.assertTrue(any("ningen" in f for f in forms), forms)
        self.assertTrue(any("ren" in f and "jian" in f for f in forms), forms)

    def test_ascii_text_needs_no_romanization(self):
        self.assertEqual(romanizations("Travis Scott"), ())

    def test_searchable_keeps_original_and_adds_romanization(self):
        hay = searchable("人間椅子")
        self.assertIn("人間椅子", hay)
        self.assertIn("ningen isu", hay)


class NonLatinSearchTests(unittest.TestCase):
    def setUp(self):
        self.index = build_index(SONGS)

    def hits(self, query):
        return [song["title"] for song in search(self.index, query)[0]]

    def test_japanese_found_by_romanized_artist(self):
        self.assertEqual(self.hits("ningen isu"), ["無情のスキャット"])

    def test_japanese_found_by_romanized_title(self):
        self.assertEqual(self.hits("mujou no sukyatto"), ["無情のスキャット"])

    def test_found_by_typing_the_original_script(self):
        self.assertEqual(self.hits("人間椅子"), ["無情のスキャット"])
        self.assertEqual(self.hits("Витас"), ["Опера №2"])

    def test_cyrillic_found_by_transliteration(self):
        self.assertEqual(self.hits("vitas"), ["Опера №2"])
        self.assertEqual(self.hits("opera"), ["Опера №2"])

    def test_chinese_found_by_pinyin(self):
        self.assertEqual(self.hits("zhou jie lun"), ["稻香"])

    def test_latin_search_is_unaffected(self):
        self.assertEqual(self.hits("hyaena"), ["HYAENA"])
        self.assertEqual(self.hits("travis scott"), ["HYAENA"])

    def test_a_romanized_query_never_drags_in_unrelated_records(self):
        self.assertNotIn("HYAENA", self.hits("ningen isu"))


if __name__ == "__main__":
    unittest.main()
