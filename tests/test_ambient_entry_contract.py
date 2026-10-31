"""Regression contract for Ambient's visible four-corner entrance."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AmbientEntryContractTests(unittest.TestCase):
    def test_shared_four_corner_control_enters_ambient(self):
        rail = (ROOT / "qml" / "WhisperRail.qml").read_text()
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertIn("signal openAmbient()", rail)
        self.assertIn('Accessible.name: "Enter ambient mode"', rail)
        self.assertIn("onOpenAmbient: root.enterAmbient()", main)
        self.assertNotIn("onToggleBare:", main)

    def test_active_gallery_uses_shared_entry_at_every_width(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        rail = (ROOT / "qml" / "WhisperRail.qml").read_text()
        gallery = (ROOT / "qml" / "GalleryNowPlayingView.qml").read_text()

        self.assertIn("GalleryNowPlayingView {", main)
        self.assertIsNone(re.search(r"(?m)^\s*NowPlayingView\s*\{", main))
        self.assertIn('ambientAvailable: root.mode === "now" && !root.mini', main)
        self.assertIn("visible: rail.ambientAvailable", rail)
        self.assertNotIn('icon: "moon"', gallery)
        self.assertNotIn("signal ambient()", gallery)

    def test_ambient_restores_pre_entry_window_state(self):
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertIn("_preAmbientVis = visibility", main)
        self.assertIn("visibility = Window.FullScreen", main)
        self.assertIn("property bool ambientExitPending: false", main)
        self.assertIn("if (ambientExitPending)", main)

    def test_ambient_is_prewarmed_without_starting_unused_spectrum(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        self.assertIn("property bool _ambientPrewarmed: false", main)
        self.assertIn("active: root._ambientPrewarmed || root.ambient", main)
        self.assertIn("asynchronous: !root.ambient", main)
        self.assertNotIn("onTriggered: backend.prepareSpectrum()", main)
        self.assertIn("presentationActive: root.ambient", main)
        self.assertIn("property bool presentationActive: false", ambient)
        self.assertIn("if (ambient.presentationActive)", ambient)

    def test_fullscreen_resize_suspends_covered_rooms_and_repaints(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        gallery = (ROOT / "qml" / "GalleryNowPlayingView.qml").read_text()

        self.assertIn("property bool windowGeometryChanging: false", main)
        self.assertIn("visible: !root.mini && !root.ambient", main)
        self.assertIn("readonly property bool routeRoomActive:", main)
        self.assertIn("!mini && !ambient && !searchOpen", main)
        self.assertIn(
            'current: root.routeRoomActive && root.mode === "now"', main)
        self.assertIn("current: root.ambient", main)
        self.assertIn("windowGeometryChanging: root.windowGeometryChanging", main)
        self.assertIn("resizeActive: root.windowGeometryChanging", main)
        self.assertIn("!windowGeometryChanging ? 300 : 0", gallery)

    def test_hall_composition_is_gone(self):
        """Iann removed the Vaporwave Hall on 2026-08-05 (SPEC.md · Ambient).

        The page is a provisional bare room until its new design round.
        """
        ambient = (ROOT / "qml" / "AmbientView.qml").read_text()

        self.assertFalse((ROOT / "qml" / "AmbientHall.qml").exists())
        self.assertFalse((ROOT / "qml" / "PerspectiveSpectrum.qml").exists())
        self.assertFalse((ROOT / "qml" / "NightSpectrum.qml").exists())
        self.assertFalse(
            (ROOT / "qml" / "assets" / "ambient-vaporwave-hall.png").exists())
        for dead in ("AmbientHall", "PerspectiveSpectrum", "NightSpectrum",
                     "darkMode", "ambientQuietRoom"):
            self.assertNotIn(dead, ambient)

    def test_ambient_is_visible_before_fullscreen_resize_begins(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        enter = main.split("function enterAmbient()", 1)[1].split(
            "function leaveAmbient()", 1)[0]
        entry_frame = main.split("id: ambientEntryFrame", 1)[1].split(
            "// Construct and decode", 1)[0]

        self.assertIn("ambientEnterPending = true", enter)
        self.assertIn("ambient = true", enter)
        self.assertNotIn("visibility = Window.FullScreen", enter)
        self.assertIn("running: root.ambientEnterPending", entry_frame)
        self.assertIn("root.visibility = Window.FullScreen", entry_frame)

    def test_resize_completion_requires_stable_rendered_frames(self):
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertIn("FrameAnimation {\n        id: windowGeometrySettle", main)
        self.assertIn("root._geometryStableFrames >= 2", main)
        self.assertNotIn("interval: 72", main)

    def test_hidden_navigation_shortcuts_are_disabled_in_ambient(self):
        main = (ROOT / "qml" / "Main.qml").read_text()

        self.assertIn(
            'sequence: "Alt+Left"; enabled: !root.ambient', main)
        self.assertIn(
            'sequence: "Alt+Right"; enabled: !root.ambient', main)
        self.assertIn(
            'sequence: "Ctrl+N"; enabled: !root.ambient', main)
        self.assertIn(
            "enabled: !root.ambient", main)


if __name__ == "__main__":
    unittest.main()
