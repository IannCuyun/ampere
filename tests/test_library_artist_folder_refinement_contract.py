"""Source-level guards for the 2026-08-17 Library refinement.

The QML behavior tests exercise projection and activation when Qt Quick Test is
available. These guards keep the visual contract explicit even on headless
machines where qmltestrunner cannot create its test window.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"


def source(name: str) -> str:
    return (QML / name).read_text(encoding="utf-8")


class LibraryArtistFolderRefinementContractTests(unittest.TestCase):
    def test_artist_catalog_has_search_dropdown_and_direction_control(self) -> None:
        artist = source("ArtistView.qml")
        self.assertIn('objectName: "artistCatalogSearch"', artist)
        self.assertIn('objectName: "artistSortPicker"', artist)
        self.assertIn('objectName: "artistSortDirection"', artist)
        self.assertIn('{ id: "plays", label: "Listening" }', artist)
        self.assertIn('{ id: "title", label: "Release title" }', artist)
        self.assertIn('{ id: "year", label: "Release year" }', artist)
        self.assertIn('{ id: "tracks", label: "Track count" }', artist)
        self.assertIn("model: view.visibleDisco", artist)
        self.assertIn("readonly property var artistFiles: visibleDisco.reduce", artist)
        self.assertIn("rotation: view.sortDescending ? 180 : 0", artist)

    def test_artist_release_rows_suppress_redundant_artist_column(self) -> None:
        artist = source("ArtistView.qml")
        track = source("TrackRow.qml")
        self.assertIn("showArtist: false", artist)
        self.assertIn("property bool showArtist: true", track)
        self.assertIn("visible: row.showArtist && parent.width > 560", track)
        self.assertRegex(artist, r"artSize:[\s\S]{0,160}Math\.min\(258")

    def test_library_filter_has_one_structural_rule_and_folders_are_rooms(self) -> None:
        library = source("LibraryView.qml")
        filter_block = library.split("id: filterLine", 1)[1].split(
            "id: sortWhisper", 1
        )[0]
        self.assertNotIn("height: 1", filter_block)
        self.assertIn('objectName: "libraryFolderSourceRooms"', library)
        self.assertIn('objectName: "libraryFolderRoom_" + index', library)
        self.assertIn("component FolderRoomCard: Item", library)
        self.assertNotIn('kind: "folder"', library)
        self.assertIn("onOpened: lib.openFolder(modelData.path)", library)


if __name__ == "__main__":
    unittest.main()
