"""Structural characterization for Milestone 5's active QML control graph.

The QML behavior suite is the behavioral gate. These assertions deliberately
remain source-level guards so a future refactor cannot silently drop a required
focus/keyboard/assistive bridge from the currently reachable components.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"


def source(name: str) -> str:
    return (QML / name).read_text(encoding="utf-8")


class ActiveControlAccessibilityCharacterizationTests(unittest.TestCase):
    def assert_action_counts(self, expected_counts: dict[str, int]) -> None:
        for name, minimum in expected_counts.items():
            self.assertGreaterEqual(
                source(name).count("Accessible.onPressAction"), minimum, name
            )

    def test_active_navigation_and_menu_controls_bridge_assistive_press(self) -> None:
        self.assert_action_counts({
            "WhisperRail.qml": 5,
            "ArchiveMenu.qml": 1,
            "AmpereMenu.qml": 1,
            "SignalHeader.qml": 3,  # history rows, forget, clear history
        })
        self.assertIn(
            "Accessible.onPressAction: btn.clicked()", source("GlowButton.qml")
        )

    def test_active_library_home_and_search_actions_bridge_assistive_press(self) -> None:
        self.assert_action_counts({
            "HomeSuggestionCard.qml": 1,
            # LandingView owns the one Rewind action; HomeThread is visual.
            "HomeThread.qml": 0,
            "LandingView.qml": 1,
            "FeaturesView.qml": 1,
            "LibraryFrame.qml": 0,
            "LibraryView.qml": 9,
            "BrowseView.qml": 1,
            "PlaylistsView.qml": 1,
            "ArtistView.qml": 3,
            "SearchDropdown.qml": 2,
        })

    def test_active_playback_and_feature_custom_controls_have_equivalent_input(self) -> None:
        self.assert_action_counts({
            "PlayerBar.qml": 3,
            "GalleryNowPlayingView.qml": 6,
            "QueuePane.qml": 5,
            "WaveSeek.qml": 0,
            "RewindView.qml": 2,
            "SettingsView.qml": 2,
            "DislikedView.qml": 1,
            "DjView.qml": 10,
            "EqView.qml": 1,
        })

        for name in ("PlayerBar.qml", "WaveSeek.qml"):
            text = source(name)
            self.assertIn("Accessible.onDecreaseAction", text, name)
            self.assertIn("Accessible.onIncreaseAction", text, name)
            self.assertIn("Keys.onLeftPressed", text, name)
            self.assertIn("Keys.onRightPressed", text, name)

    def test_inactive_legacy_pages_are_not_used_as_accessibility_authority(self) -> None:
        main = source("Main.qml")
        for component in ("NowPlayingView", "AppSidebar", "LyricsView"):
            self.assertIsNone(
                re.search(rf"(?m)^\s*{component}\s*\{{", main), component
            )

    def test_reachable_custom_controls_expose_visible_focus(self) -> None:
        dj = source("DjView.qml")
        self.assertIn("border.width: roomAction.activeFocus ? 1 : 0", dj)
        self.assertIn("activeFocus || startHover.hovered", dj)
        self.assertRegex(dj, r"id: rangeAction[\s\S]{0,180}color: activeFocus \? Theme\.washInk")
        self.assertRegex(dj, r"id: levelAction[\s\S]{0,180}color: activeFocus \? Theme\.washInk")

        library = source("LibraryView.qml")
        self.assertIn("color: alphaItem.activeFocus || alphaHover.hovered", library)

        # The six-destination rail moved out of the detail frame (2026-08-22);
        # its actions are the reachable controls that remain, and WashLine
        # carries their focus ring.
        wash_line = source("WashLine.qml")
        self.assertIn("activeFocusOnTab: true", wash_line)
        self.assertIn("|| link.activeFocus", wash_line)
        self.assertIn("visible: link.primaryAction || link.activeFocus", wash_line)

        eq = source("EqView.qml")
        self.assertRegex(
            eq,
            r"id: variantAction[\s\S]{0,120}color: activeFocus \? Theme\.primary",
        )

        settings = source("SettingsView.qml")
        self.assertIn(
            "border.width: scroller.activeFocus && scroller.keyboardFocus ? 1 : 0",
            settings,
        )

    def test_ampy_mixline_controls_keep_accessibility_ownership(self) -> None:
        text = source("AmpyView.qml")
        self.assertIn('objectName: "ampyBuildAction"', text)
        self.assertIn('Accessible.name: backend.mixtapeBusy', text)
        self.assertIn('Accessible.role: Accessible.Button', text)
        self.assertIn('previousObjectName: "ampyMoodPrevious"', text)
        self.assertIn('nextObjectName: "ampyMoodNext"', text)
        self.assertIn('previousObjectName: "ampyDurationPrevious"', text)
        self.assertIn('nextObjectName: "ampyDurationNext"', text)
        self.assertIn("activeFocusOnTab: enabled", text)
        self.assertIn("border.color: Theme.focusRing", text)
        self.assertIn("Accessible.onPressAction: needleButton.triggered()", text)
        self.assertIn("Keys.onReturnPressed: needleButton.triggered()", text)
        self.assertIn("Keys.onSpacePressed: needleButton.triggered()", text)
        self.assertIn("backend.startAmpySession(selectedMinutes, selectedMood)", text)
        self.assertNotIn("soundProfile", text)
        self.assertNotIn("soundprint", text.lower())

    def test_lyrics_track_menu_and_search_clear_have_equivalent_access(self) -> None:
        lyrics = source("GalleryNowPlayingView.qml")
        self.assertIn("enabled: modelData.t >= 0", lyrics)
        self.assertIn("Accessible.ignored: !enabled", lyrics)
        self.assertIn("Accessible.onPressAction: if (lyricLine.enabled)", lyrics)
        self.assertNotIn("LYRICS / CONTINUOUS LEDGER", lyrics)
        self.assertNotIn("SYNCHRONIZED · ACTIVE LINE FOLLOWS PLAYBACK", lyrics)
        self.assertNotIn('text: "CONTINUOUS LEDGER"', lyrics)

        track = source("TrackRow.qml")
        self.assertIn("Accessible.role: Accessible.ButtonMenu", track)
        self.assertIn("Accessible.onPressAction: row.openMenuAt", track)
        self.assertGreaterEqual(track.count("activeFocusOnTab: false"), 3)
        menu = source("TrackActionMenu.qml")
        self.assertIn('{id: "toggle-like", label:', menu)
        self.assertIn('id === "toggle-like") backend.toggleLike', menu)

        self.assertIn('tip: "Clear search"', source("SignalHeader.qml"))


class PointerOnlyRoutesTests(unittest.TestCase):
    """A route a pointer can take, a keyboard must be able to take
    (ROADMAP 5.2, 2026-08-22)."""

    def test_album_location_labels_are_static(self):
        album = source("AlbumView.qml")
        crumb = album.split('objectName: "albumBreadcrumb"', 1)[1].split("}", 1)[0]
        for token in ("MouseArea", "TapHandler", "activeFocusOnTab", "onPressAction"):
            self.assertNotIn(token, crumb)

    def test_the_folder_page_artist_breadcrumb_is_a_real_link(self):
        frame = source("LibraryFrame.qml")
        crumb = frame.split("id: crumb\n", 1)[1]
        for token in ("activeFocusOnTab: link", "Accessible.onPressAction",
                      "Keys.onReturnPressed", "crumb.activeFocus"):
            self.assertIn(token, crumb, token)

    def test_no_role_is_announced_without_a_name(self):
        # An assistive user hears the role and nothing else when a control
        # carries Accessible.role but no Accessible.name.
        import pathlib
        qml = pathlib.Path(__file__).resolve().parent.parent / "qml"
        retired = {"NowPlayingView.qml", "AppSidebar.qml", "LyricsView.qml",
                   "DjView.qml"}
        offenders = []
        for path in sorted(qml.glob("*.qml")):
            if path.name in retired:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if "Accessible.role" not in line:
                    continue
                window = "\n".join(lines[max(0, i - 12):i + 12])
                if "Accessible.name" not in window:
                    offenders.append(f"{path.name}:{i + 1}")
        self.assertEqual([], offenders)
