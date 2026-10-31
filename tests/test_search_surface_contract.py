"""Search · Record Wall surface contracts (design/SPEC.md rows "Search
hierarchy" + "Search results"; DECISIONS 2026-08-20 verdicts 1–7; AUDIT
S-01…S-19) and the folder-art source contracts that share this file."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / "qml" / name).read_text(encoding="utf-8")


class SearchRecordWallCompositionTests(unittest.TestCase):
    def test_record_wall_owns_best_match_sleeve_row_and_song_ledger(self):
        text = source("SearchDropdown.qml")
        # artboard B: 420px best-match column, eyebrow, wrapping title, actions
        self.assertIn("width: pop.compact ? content.width : 420", text)
        self.assertIn('text: (pop.bestExact ? "Best match" : "Closest match")', text)
        self.assertIn('objectName: "searchBestTitle"', text)
        best_title = text.split('objectName: "searchBestTitle"', 1)[1].split("}", 1)[0]
        self.assertIn("wrapMode: Text.Wrap", best_title)
        self.assertNotIn("elide:", best_title)
        self.assertIn('label: pop.bestKind === "song" ? "Play →"', text)
        self.assertIn('label: "Queue"', text)
        self.assertIn('label: "Open"', text)
        # query headline + truthful counts line
        self.assertIn("font.pixelSize: pop.compact ? 44 : 56", text)
        self.assertIn('plural(allDisplayedSongs.length, "song", "songs")', text)
        # sleeve row (150px tiles) and the ledger with its in-room ALL link
        self.assertIn('text: "Albums & artists"', text)
        self.assertIn("width: 150", text)
        self.assertIn('"matching song", "matching songs"', text)
        self.assertIn('objectName: "searchAllLink"', text)
        self.assertIn('text: "All " + pop.allDisplayedSongs.length + " →"', text)
        # every file is a row; duplicates carry their format (verdict #4)
        self.assertIn('"  · " + rowData.format + " version"', text)
        self.assertIn("rowData.disambiguate && rowData.format", text)
        self.assertIn("pop.songSubLine(rowData)", text)

    def test_empty_categories_state_themselves_without_dead_view_all(self):
        text = source("SearchDropdown.qml")
        self.assertIn('objectName: "searchSleeveEmpty"', text)
        self.assertIn('objectName: "searchSongsEmpty"', text)
        self.assertIn('objectName: "searchEmptyStatement"', text)
        self.assertNotIn('"VIEW ALL"', text)
        self.assertNotIn("viewAllRequested", text)
        self.assertIn("&& pop.allDisplayedSongs.length > pop.songPreviewLimit", text)

    def test_compact_stacks_every_category_with_a_scrollbar(self):
        text = source("SearchDropdown.qml")
        self.assertIn("readonly property bool compact: width < 1000", text)
        self.assertIn("ScrollBar.vertical: ArchiveScrollBar {}", text)
        self.assertIn("flickableDirection: Flickable.HorizontalFlick", text)
        # complete album/artist access: fade while more remain, ALL N → grid
        self.assertIn('objectName: "searchSleeveFade"', text)
        self.assertIn('objectName: "searchSleevesAllLink"', text)
        self.assertIn('objectName: "searchSleeveGrid"', text)
        self.assertIn('text: "All " + pop.sleeveItems.length + " →"', text)
        self.assertIn("x: pop.compact ? 0 : 420 + 64", text)
        self.assertIn("font.pixelSize: pop.compact ? 28 : 40", text)

    def test_room_keeps_full_room_mount_without_nested_window_chrome(self):
        search = source("SearchDropdown.qml")
        header = source("SignalHeader.qml")
        main = source("Main.qml")
        self.assertNotIn("QQC.Popup", search)
        self.assertNotIn("Theme.bgLow, 0.985", search)
        self.assertNotIn('text: "AMPERE"', header)
        self.assertNotIn("canBack", header)
        self.assertIn("visible: !root.searchOpen", main)
        self.assertIn("anchors.fill: parent", main.split(
            "Search: Listening Observatory full-room index", 1)[1])

    def test_artist_images_never_fall_back_to_album_covers(self):
        text = source("SearchDropdown.qml")
        media = source("MediaArtwork.qml")
        self.assertIn("? pop.portraitSource(tile.rowData.name) : pop.artKey(tile.rowData.cover)", text)
        self.assertIn('kind: pop.bestKind === "artist" ? "artist" : pop.bestKind', text)
        self.assertIn("requestArtistBio", text)
        self.assertIn('return prefix + "round:" + key', media)
        self.assertNotIn("Image {", text.replace("MediaArtwork {", ""))


class SearchBehaviorVerdictTests(unittest.TestCase):
    def test_return_expands_the_full_list_inside_the_room(self):
        header = source("SignalHeader.qml")
        search = source("SearchDropdown.qml")
        main = source("Main.qml")
        self.assertIn("Keys.onReturnPressed: header.submit()", header)
        self.assertIn("results.expandAll();", header)
        self.assertIn("function expandAll()", search)
        self.assertNotIn("SearchResultsView", main)
        self.assertNotIn('mode === "results"', main)
        self.assertFalse((ROOT / "qml/SearchResultsView.qml").exists())

    def test_activating_a_song_queues_only_that_song(self):
        text = source("SearchDropdown.qml")
        self.assertIn("actionProvider.playFiles([track.file], 0);", text)
        self.assertNotIn("hitFiles", text)
        self.assertNotIn("suggFiles", text)

    def test_closing_search_keeps_the_query_and_results(self):
        header = source("SignalHeader.qml")
        main = source("Main.qml")
        self.assertIn("function closeSearch() {\n        dismiss();\n    }", header)
        self.assertIn("function closeSearch() {\n        searchOpen = false\n    }", main)
        self.assertNotIn("appHeader.clearSearch()", main)

    def test_field_selection_uses_the_wash_selection_recipe(self):
        header = source("SignalHeader.qml")
        self.assertIn("selectionColor: Qt.alpha(Theme.primary, 0.28)", header)
        self.assertIn("selectedTextColor: Theme.washInk", header)

    def test_history_plane_follows_the_archive_menu_recipe(self):
        header = source("SignalHeader.qml")
        self.assertIn("color: Qt.alpha(Theme.bgLow, 0.84)", header)
        self.assertIn("border.color: Theme.washHair", header)
        self.assertIn("radius: 0", header)
        self.assertIn('text: "RECENT"', header)
        self.assertIn("height: 44 + (index > 0 ? 1 : 0)", header)
        self.assertIn('text: "×"', header)
        self.assertIn('text: "CLEAR HISTORY"', header)
        # 2026-08-21 correction (Iann: "does not match the aesthetic of the
        # app"). The rows read as a generic list widget: a blue `primary`
        # hover tint against Archive Wash's warm neutral ink, and full-bleed
        # separators. Both now follow ArchiveMenu exactly — neutral washInk
        # hover, hairline inset 16px, none after the last row.
        self.assertIn("Qt.alpha(Theme.washInk, 0.065) : \"transparent\"", header)
        self.assertNotIn("Qt.alpha(Theme.primary, 0.075)", header)
        self.assertIn(
            "height: historyRow.index < header.history.length - 1 ? 1 : 0",
            header)
        self.assertIn('&& search.text === "" && history.length > 0', header)
        self.assertIn("historyProvider.rememberSearch(text)", header)
        self.assertIn("onQueryCommitted: q => header.remember(q)", header)

    def test_history_is_bounded_and_persisted_through_settings(self):
        from ampere.settings import DEFAULTS, SEARCH_HISTORY_LIMIT, _validated
        self.assertEqual([], DEFAULTS["search_history"])
        self.assertEqual(10, SEARCH_HISTORY_LIMIT)
        values = _validated({"search_history": [
            " heart ", "HEART", "bully", "", None, *[f"q{i}" for i in range(20)]]})
        self.assertEqual(10, len(values["search_history"]))
        self.assertEqual(["heart", "bully", "q0"], values["search_history"][:3])
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn('"search_history": list(self._search_history)', backend)
        self.assertIn('self._settings.try_patch({"search_history": cleaned})', backend)
        for slot in ("def rememberSearch", "def forgetSearch",
                     "def clearSearchHistory", "def searchHistory"):
            self.assertIn(slot, backend)

    def test_song_rows_share_track_rows_menu(self):
        search = source("SearchDropdown.qml")
        track = source("TrackRow.qml")
        menu = source("TrackActionMenu.qml")
        self.assertIn("TrackActionMenu {", search)
        self.assertIn("TrackActionMenu {", track)
        self.assertNotIn("AmpereMenu {", search)
        self.assertNotIn("AmpereMenu {", track)
        self.assertIn("acceptedButtons: Qt.LeftButton | Qt.RightButton", search)
        for option in ('"PLAY NOW"', '"PLAY NEXT"', '"ADD TO QUEUE"',
                       '"MORE LIKE THIS ✦"', '"EDIT TRACK INFO…"'):
            self.assertIn(option, menu)
        self.assertIn("onEditRequested: track => pop.editTrack(track)", search)
        self.assertIn("onEditTrack: track => trackEditor.open(track)", source("Main.qml"))


class SearchAuditRepairTests(unittest.TestCase):
    def test_loading_failure_and_stale_states_are_explicit(self):
        search = source("SearchDropdown.qml")
        self.assertIn('property string inFlightQuery: ""', search)
        self.assertIn("opacity: pop.stale && pop.inFlightQuery !== \"\" ? 0.45 : 1", search)
        self.assertIn('text: "Search failed — try again"', search)
        self.assertIn("function onQuickSearchFailed(searchQuery, serial, reason)", search)
        self.assertIn("if (serial < requestSerial)", search)
        self.assertIn("searchProvider.requestQuickSearch(searchQuery, requestSerial);", search)
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn('quickSearchFailed = Signal(str, int, str)', backend)
        self.assertIn("on_failed=self.quickSearchFailed.emit", backend)

    def test_keyboard_walk_and_staged_escape(self):
        search = source("SearchDropdown.qml")
        header = source("SignalHeader.qml")
        self.assertIn("function navItems()", search)
        self.assertIn("function focusRelative(item, step)", search)
        self.assertIn("Keys.onEscapePressed: pop.focusFieldRequested()", search)
        self.assertIn("results.focusFirst();", header)
        self.assertIn("Keys.onEscapePressed: header.escapeField()", header)
        self.assertIn("onFocusFieldRequested: search.forceActiveFocus()", header)
        clear_button = header.split("GlowButton {", 1)[1].split("}", 1)[0]
        self.assertIn("activeFocusOnTab: false", clear_button)
        self.assertIn("search.forceActiveFocus();\n    }\n    // Closing keeps", header)

    def test_one_character_hint_and_lyrics_states(self):
        search = source("SearchDropdown.qml")
        self.assertIn('readonly property bool hintOnly: query.trim().length === 1', search)
        self.assertIn('"Type at least 2 characters"', search)
        self.assertIn('text: "Lyrics indexing…"', search)
        self.assertIn('text: "Lyrics · " + pop.lyricHits.length', search)
        self.assertIn("function onLyricsIndexChanged()", search)


class FolderArtSourceContractTests(unittest.TestCase):
    def test_library_source_rooms_use_the_top_album_cover(self):
        media = source("MediaArtwork.qml")
        library = source("LibraryView.qml")
        browse = source("BrowseView.qml")
        self.assertIn('artwork.kind === "folder" ? "folder"', media)
        self.assertIn('kind === "folder" && sourceImage.status !== Image.Ready', media)
        source_rooms = library.split(
            "// ---- FOLDERS A: one continuous, path-first cover run ----", 1
        )[1].split("EmptyState {", 1)[0]
        self.assertIn('objectName: "libraryFolderSourceRooms"', source_rooms)
        self.assertIn("FolderRoomCard", source_rooms)
        self.assertIn("folder: modelData", source_rooms)
        self.assertIn('source: folderCard.folder.cover', library)
        self.assertIn('kind: "album"', library)
        self.assertIn('name: "folder"', library)
        self.assertIn("folderRow.rowData.cover", browse)
        self.assertIn('"image://art/folder:"', browse)
        self.assertIn('kind: "folder"', browse)


if __name__ == "__main__":
    unittest.main()


class BestMatchActivationTests(unittest.TestCase):
    """Iann, 2026-08-21: clicking the large sleeve must play immediately.

    The hero already declared itself a button — pointing-hand cursor, focus
    ring, `Accessible.onPressAction`, Return/Space — but carried no pointer
    handler, so a mouse click on the art did nothing at all."""

    def test_the_best_match_sleeve_activates_on_tap(self):
        dropdown = source("SearchDropdown.qml")
        self.assertIn("TapHandler {\n                    enabled: pop.bestItem !== null\n"
                      "                    onTapped: pop.activateBest()\n                }",
                      dropdown)

    def test_activation_still_routes_by_kind(self):
        dropdown = source("SearchDropdown.qml")
        self.assertIn("function activateBest()", dropdown)
