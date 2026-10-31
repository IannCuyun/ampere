"""Regression contract for Gallery Title's intentionally chrome-free room.

The Dark Ambient / Quiet Room toggle was removed with the Vaporwave Hall on
Iann's 2026-08-05 verdict. Gallery Title removes the remaining in-room
fullscreen control while preserving Main's automatic fullscreen transaction.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AmbientCornerControlsContractTests(unittest.TestCase):
    def test_gallery_title_room_has_no_utility_control_or_signal(self):
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertNotIn('objectName: "ambientCornerControls"', ambient)
        self.assertNotIn('objectName: "ambientFullscreenButton"', ambient)
        self.assertNotIn("signal toggleFullscreenRequested", ambient)
        self.assertNotIn("onToggleFullscreenRequested", main)
        self.assertIn("Qt.callLater(ambient.forceActiveFocus)", ambient)

    def test_automatic_fullscreen_transaction_remains_owned_by_main(self):
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertIn("root.visibility = Window.FullScreen", main)
        self.assertIn('sequence: "F11"; enabled: !root.ambient', main)

    def test_dark_ambient_toggle_is_retired(self):
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        self.assertNotIn('icon: "moon"', ambient)
        self.assertNotIn("darkButton", ambient)
        self.assertNotIn("darkMode", ambient)

    def test_gallery_title_retains_record_lyric_and_identity(self):
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        self.assertIn("backend.currentSong.title", ambient)
        self.assertIn("ambient.lyricLine(ambient.currentLyric)", ambient)
        self.assertIn("color: Theme.primary", ambient)
        self.assertIn('kind: "album"', ambient)
        self.assertIn('objectName: "ambientArtwork"', ambient)
        self.assertIn('objectName: "ambientLyricColumn"', ambient)
        self.assertIn('objectName: "ambientIdentity"', ambient)

    def test_gallery_title_reuses_now_playing_album_underlay(self):
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        self.assertIn("ArchiveWash {", ambient)
        self.assertIn('sourceFile: backend.currentSong.file || ""', ambient)
        self.assertIn("veil: 0.60", ambient)
        self.assertIn("fitStrength: 0.0", ambient)
        self.assertNotIn("RoomGradient {", ambient)

    def test_stillpoint_has_no_visualizer_or_secondary_mode(self):
        """Characterization supplement; geometry is covered in QML tests."""
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        for retired in ("Visualizer", "prepareSpectrum", "id: clock",
                        "darkMode", "ambientQuietRoom"):
            self.assertNotIn(retired, ambient)


if __name__ == "__main__":
    unittest.main()
