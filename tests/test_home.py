import unittest
from pathlib import Path

from ampere.home import HomeProjection
from ampere.mpdclient import Backend


class HomeProjectionTests(unittest.TestCase):
    def setUp(self):
        self.projection = HomeProjection()
        self.shelves = {
            "history": [
                {"file": "A/Album/one.flac", "album": "Album", "artist": "A"},
                {"file": "A/Album/two.flac", "album": "Album", "artist": "A"},
                {"file": "B/Other/one.flac", "album": "Other", "artist": "B"},
            ],
            "arrivals": [{"file": "C/New/one.flac", "album": "New"}],
            "loved": [{"file": "D/Loved/one.flac", "album": "Loved"}],
            "deep": [{"file": "E/Deep/one.flac", "album": "Deep"}],
            "unfinished": [{
                "file": "F/Long/one.flac", "album": "Long",
                "resumePosition": 420,
            }],
        }
        self.rewind = {
            "ready": True,
            "stats": {
                "week": 7,
                "month": 24,
                "monthArtists": 9,
                "monthTopArtists": [
                    {"name": "A", "path": "A"},
                    {"name": "B", "path": "B"},
                    {"name": "C", "path": "C"},
                    {"name": "D", "path": "D"},
                ],
            },
        }

    def test_build_is_bounded_atomic_and_album_unique(self):
        result = self.projection.build(
            smart_shelves=self.shelves, rewind=self.rewind)

        self.assertTrue(result["ready"])
        self.assertEqual(
            result["metrics"], {"week": 7, "month": 24, "artists": 9})
        self.assertEqual(["A", "B", "C"],
                         [row["name"] for row in result["artists"]])
        self.assertEqual(2, len(result["shelves"]["history"]))
        self.assertEqual("Other", result["shelves"]["history"][1]["album"])
        self.assertEqual(420, result["shelves"]["unfinished"][0][
            "resumePosition"])

        result["shelves"]["history"][0]["album"] = "Changed"
        self.assertEqual("Album", self.shelves["history"][0]["album"])

    def test_missing_family_is_not_ready_but_remains_safe(self):
        partial = dict(self.shelves)
        partial.pop("loved")
        result = self.projection.build(
            smart_shelves=partial, rewind={"ready": False, "stats": {}})

        self.assertFalse(result["ready"])
        self.assertEqual({"week": 0, "month": 0, "artists": 0},
                         result["metrics"])
        self.assertEqual([], result["shelves"]["loved"])

    def test_unfinished_uses_only_valid_resume_evidence(self):
        rows = self.projection.unfinished(
            library={
                "recent.flac": {"file": "recent.flac", "duration": 1200},
                "done.flac": {"file": "done.flac", "duration": 300},
                "short.flac": {"file": "short.flac", "duration": 100},
            },
            resume_positions={
                "recent.flac": "420", "done.flac": "260",
                "short.flac": "70", "missing.flac": "200",
            },
            last_played={"recent.flac": "200", "done.flac": "300"},
        )

        self.assertEqual(["recent.flac"], [row["file"] for row in rows])
        self.assertEqual(420, rows[0]["resumePosition"])

    def test_backend_slot_reads_only_published_caches(self):
        backend = type("BackendHarness", (), {})()
        backend._home = self.projection
        backend._smart_shelves = self.shelves
        backend._rewind_overview = self.rewind
        backend._stickers = type("Stickers", (), {
            "values_result": lambda *_args: self.fail("read stickers"),
        })()

        result = Backend.homeOverview(backend)

        self.assertTrue(result["ready"])
        self.assertEqual(24, result["metrics"]["month"])


class HomeCaptionContrastTests(unittest.TestCase):
    @staticmethod
    def _luminance(rgb):
        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.04045 else (
                (value + 0.055) / 1.055) ** 2.4
        red, green, blue = (channel(value) for value in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    @classmethod
    def _ratio(cls, first, second):
        a, b = cls._luminance(first), cls._luminance(second)
        light, dark = max(a, b), min(a, b)
        return (light + 0.05) / (dark + 0.05)

    def test_caption_ink_clears_aa_over_worst_case_bright_art(self):
        # The soft trail reaches a 70% warm near-black floor where caption
        # content begins. White artwork is the contrast worst case because it
        # produces the lightest possible composite behind the fixed inks.
        matte = (9, 8, 7)
        bright_art = (255, 255, 255)
        alpha = 0.70
        composite = tuple(round(alpha * dark + (1 - alpha) * bright)
                          for dark, bright in zip(matte, bright_art))
        caption_ink = (247, 243, 236)
        caption_muted = (216, 209, 199)

        self.assertGreaterEqual(self._ratio(caption_ink, composite), 4.5)
        self.assertGreaterEqual(self._ratio(caption_muted, composite), 4.5)

    def test_caption_contract_is_encoded_in_the_shared_cover_component(self):
        source = (Path(__file__).resolve().parents[1] / "qml" /
                  "HomeSuggestionCard.qml").read_text(encoding="utf-8")
        self.assertIn('objectName: "coverCaptionMatte"', source)
        self.assertIn('readonly property color captionInk: "#f7f3ec"', source)
        self.assertIn("captionContent.height + (card.dominant ? 152 : 112)", source)
        self.assertIn("position: 0.10", source)
        self.assertIn("position: 0.50", source)
        self.assertIn("0.70", source)

    def test_home_cover_has_no_redundant_play_overlay(self):
        qml = Path(__file__).resolve().parents[1] / "qml"
        card = (qml / "HomeSuggestionCard.qml").read_text(encoding="utf-8")
        landing = (qml / "LandingView.qml").read_text(encoding="utf-8")

        self.assertNotIn("property bool playable", card)
        self.assertNotIn('name: "play"', card)
        self.assertNotIn("playable: true", landing)
        self.assertIn("page.activate(card.modelData)", landing)


if __name__ == "__main__":
    unittest.main()
