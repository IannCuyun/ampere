import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"


class NavigationFlowContractTests(unittest.TestCase):
    def test_visible_history_controls_use_main_as_the_only_history_owner(self):
        rail = (QML / "WhisperRail.qml").read_text(encoding="utf-8")
        main = (QML / "Main.qml").read_text(encoding="utf-8")

        self.assertIn("property bool canGoBack: false", rail)
        self.assertIn("property bool canGoForward: false", rail)
        self.assertIn("signal navigateBack()", rail)
        self.assertIn("signal navigateForward()", rail)
        self.assertIn('icon: "chevron-left"', rail)
        self.assertIn('icon: "chevron-right"', rail)
        self.assertNotIn("property var backStack", rail)
        self.assertNotIn("property var fwdStack", rail)

        self.assertIn("canGoBack: root.backStack.length > 0", main)
        self.assertIn("canGoForward: root.fwdStack.length > 0", main)
        self.assertIn("onNavigateBack: root.goBack()", main)
        self.assertIn("onNavigateForward: root.goForward()", main)
        self.assertIn("backStack = backStack.concat([_curNav])", main)
        self.assertIn("backStack = backStack.slice(0, backStack.length - 1)", main)
        self.assertIn("fwdStack = fwdStack.concat([_navSnapshot()])", main)
        self.assertIn("libraryTab: libraryPage.tab", main)
        self.assertIn("playlistName: libraryPage.selectedPlaylist", main)
        self.assertIn("genreName: libraryPage.selectedGenre", main)
        self.assertIn("onTabChanged: root._navChanged()", main)
        self.assertIn("onSelectedPlaylistChanged: root._navChanged()", main)
        self.assertIn("onSelectedGenreChanged: root._navChanged()", main)
        self.assertIn('targetTab === "genres" && s.genreName', main)
        self.assertIn("libraryPage.openGenre(s.genreName)", main)

    def test_search_room_closes_on_any_route_change(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        on_mode = main.split("onModeChanged: {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("if (searchOpen) closeSearch()", on_mode)
        for handler in ("onBrowsePathChanged", "onAlbumPathChanged",
                        "onArtistNameChanged"):
            self.assertIn(
                handler + ": { _navChanged(); if (searchOpen) closeSearch() }",
                main)

    def test_window_size_and_last_stable_room_persist(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("import QtCore", main)
        prefs = main.split("id: windowPrefs", 1)[1].split("}", 1)[0]
        self.assertIn('category: "window"', prefs)
        self.assertNotIn("property int x", prefs)
        self.assertIn("width: windowPrefs.w", main)
        self.assertIn("height: windowPrefs.h", main)
        self.assertIn("if (mini || visibility !== Window.Windowed) return", main)
        modes = main.split("_restorableModes: [", 1)[1].split("]", 1)[0]
        for never in ("ambient", "results", "search", "album", "artist"):
            self.assertNotIn('"' + never + '"', modes)
        self.assertIn('"home"', modes)
        self.assertIn('"features"', modes)
        self.assertIn("mode = windowPrefs.lastMode", main)

    def test_explicit_home_and_contextual_library_own_content_navigation(self):
        rail = (QML / "WhisperRail.qml").read_text(encoding="utf-8")
        primary = rail.split("readonly property var links:", 1)[1].split(
            "readonly property var utilities:", 1)[0]
        self.assertIn('{ mode: "library", label: "Library" }', primary)
        self.assertIn('{ mode: "features", label: "Features" }', primary)
        self.assertNotIn('{ mode: "home", label: "Home" }', primary)
        self.assertNotIn('{ mode: "now", label: "Now playing" }', primary)
        self.assertLess(primary.index('mode: "library"'),
                        primary.index('mode: "features"'))
        self.assertNotIn("Up next", primary)
        self.assertIn('objectName: "homeButton"', rail)
        self.assertIn('Accessible.name: "Home"', rail)
        self.assertIn('text: "HOME"', rail)
        self.assertNotIn('text: "AMPERE"', rail)
        self.assertIn('rail.navigate("home")', rail)
        self.assertIn('visible: !(rail.searchOpen && rail.width < 1200)', rail)
        self.assertIn('x: homeButton.x + homeButton.width + 8', rail)
        self.assertIn('? destinationRow.x + destinationRow.width + 8', rail)
        self.assertLess(rail.index('id: homeButton'), rail.index('id: destinationRow'))
        self.assertLess(rail.index('id: destinationRow'), rail.index('id: historyControls'))
        utility = rail.split("utilityMenu.options = [", 1)[1].split("]", 1)[0]
        ids = [line.split('id: "', 1)[1].split('"', 1)[0]
               for line in utility.splitlines() if 'id: "' in line]
        self.assertEqual(ids, ["disliked", "doctor", "eq", "settings"])
        self.assertIn('{ id: "disliked", label: "Out of Rotation" }', utility)
        self.assertNotIn('id: "library"', utility)
        self.assertNotIn('id: "rewind"', utility)
        self.assertNotIn('id: "ampy"', utility)
        self.assertNotIn("overlayOpen", rail)
        self.assertNotIn("toggleOverlay", rail)
        self.assertIn('"Sound & EQ"', rail)
        self.assertIn('"Application Settings"', rail)

    def test_lyrics_and_queue_route_into_retained_gallery(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn('onOpenLyrics: if (!root.mini) root.openNowPanel("lyrics")', main)
        self.assertIn('root.openNowPanel("queue")', main)
        self.assertIn("active: root._nowPrewarmed || root.mode === \"now\"", main)
        self.assertIn("sourceComponent: galleryNowPlaying", main)
        self.assertNotIn('current: root.mode === "lyrics"', main)
        self.assertNotIn('root.mode = root.mode === "lyrics"', main)

    def test_discover_rewind_and_ampy_are_home_workflows(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        home = (QML / "LandingView.qml").read_text(encoding="utf-8")
        rail = (QML / "WhisperRail.qml").read_text(encoding="utf-8")
        remote = (ROOT / "ampere" / "remote.py").read_text(encoding="utf-8")

        self.assertIn("AmpyView {", main)
        self.assertIn("DiscoverView {", home)
        self.assertNotIn("DiscoverView {", main)
        self.assertNotIn("signal openDiscover", home)
        self.assertIn("signal openRewind", home)
        self.assertIn("signal openAmpy", home)
        self.assertIn('property string discoverLaneKey: ""', home)
        self.assertIn("function openDiscoverLane(key)", home)
        self.assertIn('current: root.routeRoomActive && root.mode === "home"', main)
        self.assertNotIn('current: root.mode === "discover"', main)
        self.assertIn("onOpenRewind: root.mode = \"rewind\"", main)
        self.assertIn("onOpenAmpy: root.mode = \"ampy\"", main)
        self.assertIn("FeaturesView {", main)
        self.assertIn('{ mode: "features", label: "Features" }', rail)
        self.assertIn('current: root.routeRoomActive && root.mode === "features"', main)
        self.assertIn("onOpenFeature: feature => root.openAtlasFeature(feature)", main)
        self.assertIn('current: root.routeRoomActive && root.mode === "ampy"', main)
        self.assertIn('active: root.routeRoomActive && root.mode === "ampy"', main)
        self.assertNotIn('if (mode === "ampy")', main)
        self.assertIn('else if (m === "ampy") root.mode = "ampy"', main)
        self.assertIn('else if (m === "discover") {', main)
        self.assertIn('homePage.openDiscoverLane(arg || "loved")', main)
        self.assertIn('String(arg || "").indexOf("discover:") === 0', main)
        nav_modes = remote.split('elif path == "/api/nav":', 1)[1].split(
            'if cb is None or mode not in ok:', 1)[0]
        # Ampy and Discover are remote-reachable; they resolve inside Home
        # (Discover) or the Ampy room via the same router branches above.
        for reachable in ('"ampy"', '"discover"', '"features"', '"artist"'):
            self.assertIn(reachable, nav_modes)
        self.assertTrue((QML / "AmpyView.qml").is_file())
        self.assertTrue((QML / "DiscoverView.qml").is_file())

    def test_escape_closes_transients_before_page_history(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        retreat = main.split("function retreat()", 1)[1].split(
            "onModeChanged", 1)[0]
        owners = [
            "trackEditor.visible",
            "searchOpen",
            "archiveHeader.menuOpen",
            "nowPresentation.item.panelsOpen",
            "queuePane.wanted",
            "goBack()",
        ]
        positions = [retreat.index(owner) for owner in owners]
        self.assertEqual(sorted(positions), positions)
        self.assertNotIn('mode = "home"', retreat)
        self.assertNotIn("Window.Windowed", retreat)

    def test_escape_defers_to_text_fields_and_stages_search_close(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        header = (QML / "SignalHeader.qml").read_text(encoding="utf-8")
        retreat = main.split("function retreat()", 1)[1].split(
            "onModeChanged", 1)[0]
        self.assertIn('f.hasOwnProperty("cursorPosition")', retreat)
        self.assertIn('f.text !== ""', retreat)
        self.assertLess(retreat.index('f.text = ""'), retreat.index("trackEditor.visible"))
        self.assertIn("if (!appHeader.fieldHasFocus) { appHeader.focusField(); return }", retreat)
        self.assertIn("readonly property bool fieldHasFocus: search.activeFocus", header)
        self.assertIn("function focusField() { search.forceActiveFocus(); }", header)

    def test_transport_and_surface_shortcuts_sleep_while_editing_text(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("readonly property bool textEditing:", main)
        for sequence in ("Space", "Ctrl+Right", "Ctrl+Left", "Ctrl+Up",
                         "Ctrl+Down", "Ctrl+Q", "Ctrl+,", "Ctrl+L", "Ctrl+M"):
            block = main.split('sequence: "%s"' % sequence, 1)[1].split("onActivated", 1)[0]
            self.assertIn("!root.ambient && !root.textEditing", block, sequence)
        self.assertIn("backend.requestPlayPause()", main)
        self.assertIn("backend.requestVolume(Math.min(100, backend.volume + 5))", main)
        self.assertIn("backend.requestVolume(Math.max(0, backend.volume - 5))", main)
        sequences = [line.split('sequence: "', 1)[1].split('"', 1)[0]
                     for line in main.splitlines() if 'sequence: "' in line]
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_player_identity_and_queue_rows_expose_expected_context(self):
        player = (QML / "PlayerBar.qml").read_text(encoding="utf-8")
        queue = (QML / "QueuePane.qml").read_text(encoding="utf-8")
        self.assertIn("signal openAlbum(string path, string album)", player)
        self.assertIn("backend.artistPath(deck.currentFile, name)", player)
        self.assertIn("onReleased: backend.requestSeek", player)
        self.assertIn("MediaArtwork {", queue)
        self.assertIn("encodeURIComponent(modelData.file)", queue)

    def test_library_surfaces_use_the_shared_scrollbar(self):
        expected = {
            "LibraryView.qml": 5,
            "BrowseView.qml": 1,
            # Album View is one composition at every width (Iann 2026-08-21,
            # artboard `E1 · Split`): desktop and compact share a single
            # sequence Flickable instead of two per-layout ListViews.
            "AlbumView.qml": 1,
            "ArtistView.qml": 1,
            "PlaylistsView.qml": 2,
        }
        for filename, minimum in expected.items():
            text = (QML / filename).read_text(encoding="utf-8")
            self.assertGreaterEqual(
                text.count("ScrollBar.vertical: ArchiveScrollBar"), minimum,
                filename)

    def test_disliked_is_a_library_utility_not_a_seventh_destination(self):
        library = (QML / "LibraryView.qml").read_text(encoding="utf-8")
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        destination_model = library.split(
            "readonly property var tabRow:", 1
        )[1].split("]", 1)[0]

        self.assertIn("signal openDisliked()", library)
        self.assertIn('objectName: "libraryDislikedAction"', library)
        self.assertIn('name: "heart-crack"', library)
        self.assertIn('text: "DISLIKED · "', library)
        self.assertNotIn("disliked", destination_model.lower())
        self.assertIn('onOpenDisliked: root.mode = "disliked"', main)

    def test_home_summary_completion_does_not_request_another_refresh(self):
        home = (QML / "LandingView.qml").read_text(encoding="utf-8")
        completion = home.split("function onLibrarySummaryChanged()", 1)[1]
        completion = completion.split("}", 1)[0]
        self.assertIn("backend.homeOverview()", completion)
        self.assertNotIn("page.reload()", completion)
        self.assertNotIn("requestLibrarySummary", completion)

    def test_home_uses_one_small_cached_music_projection(self):
        home = (QML / "LandingView.qml").read_text(encoding="utf-8")
        self.assertIn("backend.homeOverview()", home)
        self.assertIn("backend.requestLibrarySummary()", home)
        self.assertNotIn("backend.stats()", home)
        self.assertNotIn("backend.rewindOverview()", home)
        self.assertNotIn("backend.cachedSmartShelf", home)
        self.assertNotIn("backend.librarySummary()", home)
        self.assertIn("page.overview.sections", home)
        self.assertIn("page.awaitingSummary", home)
        self.assertNotIn("CONTINUE THE RECORD", home)

    def test_archive_header_replaces_the_hidden_navigation_room(self):
        rail = (QML / "WhisperRail.qml").read_text(encoding="utf-8")
        main = (QML / "Main.qml").read_text(encoding="utf-8")

        self.assertIn('text: "HOME"', rail)
        self.assertNotIn('text: "AMPERE"', rail)
        self.assertNotIn("Open navigation", rail)
        self.assertIn('objectName: "destinationRow"', rail)
        self.assertIn('objectName: "searchButton"', rail)
        self.assertIn('objectName: "settingsButton"', rail)
        self.assertNotIn('text: "MENU"', rail)
        self.assertIn("readonly property bool compact", rail)
        self.assertNotIn("overlayOpen", main)
        self.assertNotIn("signal toggleQueue()", rail)
        self.assertIn('m === "rewind" || m === "ampy"', rail)
        self.assertNotIn('m === "rewind" || m === "discover"', rail)
        self.assertIn("onNavigate: m => {\n                root.closeSearch()", main)

    def test_medium_now_playing_stacks_identity_above_waveform(self):
        gallery = (QML / "GalleryNowPlayingView.qml").read_text(
            encoding="utf-8")
        self.assertIn("readonly property bool mediumDeck: width < 1460", gallery)
        self.assertIn("readonly property int restDeckHeight: mediumDeck ? 228 : 170", gallery)
        self.assertIn("readonly property int restIdentityHeight: mediumDeck ? 94 : 98", gallery)
        self.assertIn("readonly property real restWaveY: mediumDeck ? 106 : 8", gallery)
        self.assertIn("y: view.mix(view.restWaveY, 87)", gallery)
        self.assertIn("view.mediumDeck ? deck.width : view.artSide", gallery)
        self.assertIn("view.mediumDeck\n                            ? deck.width * 0.62", gallery)

    def test_covered_routes_relinquish_geometry_and_utility_copy_clears_header(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("readonly property bool routeRoomActive:", main)
        self.assertIn("!mini && !ambient && !searchOpen", main)
        self.assertGreaterEqual(main.count("current: root.routeRoomActive"), 12)

        for filename in ("EqView.qml", "SettingsView.qml"):
            text = (QML / filename).read_text(encoding="utf-8")
            self.assertIn("Theme.pageTop(view.height)", text, filename)

    def test_supported_floor_preserves_rooms_and_uses_scroll_reachability(self):
        library = (QML / "LibraryView.qml").read_text(encoding="utf-8")
        rewind = (QML / "RewindView.qml").read_text(encoding="utf-8")
        eq = (QML / "EqView.qml").read_text(encoding="utf-8")

        self.assertIn('objectName: "libraryStageScroller"', library)
        self.assertIn("? height + roomIndex.height + (lib.lowHeight ? 160 : 300)", library)
        self.assertIn('objectName: "rewindScroller"', rewind)
        self.assertIn("contentHeight: body.height + 72", rewind)
        self.assertIn('objectName: "eqScroller"', eq)
        self.assertIn('objectName: "eqCurvePlot"', eq)
        self.assertIn("contentHeight: col.height + 30", eq)

    def test_now_playing_title_owns_a_bounded_slot_above_metadata(self):
        gallery = (QML / "GalleryNowPlayingView.qml").read_text(
            encoding="utf-8")
        self.assertIn("id: titleSlot", gallery)
        self.assertIn("anchors.bottom: metadata.top", gallery)
        self.assertIn("anchors.bottomMargin: view.titleMetadataGap", gallery)
        self.assertIn("view.titleSize, titleSlot.height / 1.16", gallery)
        self.assertIn("font.pixelSize: fittedPixelSize", gallery)
        self.assertIn("font.letterSpacing: -(fittedPixelSize * 0.045)", gallery)
        self.assertNotIn("height: view.mix(view.mediumDeck ? 82 : 98, 76)", gallery)

    def test_playlists_have_one_library_local_collection_owner(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        library = (QML / "LibraryView.qml").read_text(encoding="utf-8")
        playlists = (QML / "PlaylistsView.qml").read_text(encoding="utf-8")
        playlist_stage = (QML / "PlaylistSequenceStage.qml").read_text(
            encoding="utf-8")

        self.assertIn('function openLibraryPlaylist(name)', main)
        self.assertNotIn('current: root.mode === "playlists"', main)
        self.assertNotIn('id: playlistsPage', main)
        self.assertIn('libraryPage.openPlaylist(name || "")', main)
        self.assertIn('lib.openRoom(roomChoice.modelData.key)', library)
        self.assertIn('id: playlistSurface', library)
        self.assertIn('objectName: "libraryPlaylistSurface"', library)
        self.assertIn('playlistNames: lib.sortedPlaylists', library)
        self.assertNotIn('id: playlistList', library)
        self.assertNotIn('LibraryFrame {', playlists)
        self.assertNotIn('signal destinationRequested', playlists)
        self.assertIn('PlaylistSequenceStage {', playlists)
        self.assertIn('objectName: "playlistWall"', playlist_stage)
        self.assertIn('text: card.lead ? "MOST PLAYED"', playlist_stage)
        self.assertIn('objectName: "playlistDetail"', playlists)
        self.assertIn('SleeveTrackRow {', playlists)
        self.assertIn('objectName: "playlistSelectedMosaic"', playlists)
        self.assertIn('property string sortKey: "playlist"', playlists)
        self.assertIn('property bool sortDescending: false', playlists)
        self.assertIn('{ id: "playlist", label: "Playlist order" }', playlists)
        self.assertIn('{ id: "title", label: "Title" }', playlists)
        self.assertIn('{ id: "artist", label: "Artist" }', playlists)
        self.assertIn('{ id: "added", label: "Date added" }', playlists)
        self.assertIn('objectName: "playlistSortPicker"', playlists)
        self.assertIn('objectName: "playlistSortDirection"', playlists)
        self.assertIn('selectedId: view.sortKey', playlists)
        self.assertNotIn('visible: action.primary', playlists)
        self.assertNotIn('objectName: "playlistLeadTrack"', playlists)
        self.assertIn('model: view.displayTracks', playlists)
        self.assertIn('exhibition: true', playlists)
        self.assertIn('width: selected !== "" ? workspace.width : shelves.width', library)
        self.assertIn('readonly property bool playlistDetailOpen:', library)
        self.assertIn('readonly property bool genreDetailOpen:', library)
        self.assertIn('readonly property bool libraryDetailOpen:', library)
        self.assertIn('visible: !lib.libraryDetailOpen', library)

    def test_genres_have_one_actionable_library_local_detail_owner(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        library = (QML / "LibraryView.qml").read_text(encoding="utf-8")
        card = (QML / "GenreMosaicCard.qml").read_text(encoding="utf-8")

        self.assertIn("signal openRequested(string name)", card)
        self.assertIn("TapHandler {", card)
        self.assertIn("onTapped: card.trigger()", card)
        self.assertIn("Accessible.onPressAction: card.trigger()", card)
        self.assertIn("Keys.onReturnPressed: card.trigger()", card)
        self.assertIn("onOpenRequested: name => lib.openGenre(name)", library)
        self.assertIn('objectName: "libraryGenreDetailGrid"', library)
        self.assertIn('objectName: "libraryAllGenres"', library)
        self.assertIn("backend.libraryGenreDetail(name)", library)
        self.assertIn("fileList: lib.selectedGenreFiles", library)
        self.assertIn("genreName: libraryPage.selectedGenre", main)
        self.assertIn("libraryPage.openGenre(s.genreName)", main)
        self.assertIn("libraryPage.showAllGenres()", main)


    def test_route_requests_always_leave_the_search_room(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        handler = main.split("function onNavRequested(m, arg) {", 1)[1]
        self.assertIn('if (m !== "search" && m !== "results" && root.searchOpen) root.closeSearch()',
                      handler.split("\n            if (m === \"home\")", 1)[0])
        rail = (QML / "WhisperRail.qml").read_text(encoding="utf-8")
        self.assertIn('visible: !(rail.searchOpen && rail.width < 1200)', rail)
        self.assertNotIn('objectName: "currentSectionLabel"', rail)
        self.assertIn("searchOpen: root.searchOpen", main)


if __name__ == "__main__":
    unittest.main()


class AlbumViewCompositionTests(unittest.TestCase):
    """Album View · E1 Split (Iann verdict 2026-08-21).

    SPEC.md had this surface under UNDESIGNED #18; the direction round settled
    it. These pin the parts that were the point of the redesign, and the
    behaviour SPEC #18 required be preserved through it.
    """

    def album(self):
        return (QML / "AlbumView.qml").read_text(encoding="utf-8")

    def test_the_room_is_the_record_on_gallery_monoliths_contract(self):
        album = self.album()
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("id: albumPage", main)
        self.assertIn('readonly property bool albumRoom: root.mode === "album"', main)
        self.assertIn("sourceFile: albumRoom ? albumPage.roomFile", main)
        self.assertIn("(playbackRoom || albumRoom) ? 0.60 : 0.74", main)
        self.assertIn(
            "(playbackRoom || albumRoom || readingRoom) ? 0.0 : 1.0", main)
        # One full-window wash owns the album room. A page-local wash would be
        # clipped above the persistent player and expose the playing record.
        self.assertNotIn("ArchiveWash {", album)

    def test_the_wash_can_be_pointed_at_a_chosen_record(self):
        wash = (QML / "ArchiveWash.qml").read_text(encoding="utf-8")
        # default preserves every existing caller
        self.assertIn(
            "property string sourceFile: backend.currentSong.file", wash)
        self.assertIn("encodeURIComponent(wash.sourceFile)", wash)
        self.assertNotIn("encodeURIComponent(backend.currentSong.file)", wash)

    def test_geometry_mirrors_the_now_playing_lyric_room(self):
        album = self.album()
        self.assertIn("width * 0.435", album)
        self.assertIn("readonly property real artX: width * 0.05", album)
        self.assertIn("Math.max(76, height * 0.045)", album)

    def test_nothing_is_painted_on_the_artwork(self):
        album = self.album()
        # no local matte, scrim or gradient over the sleeve
        for banned in ("LinearGradient", "GradientStop", "opacity: 0.16",
                       'Qt.alpha("#0d0c0c'):
            self.assertNotIn(banned, album)

    def test_the_library_tab_rail_is_gone_from_this_detail_page(self):
        self.assertNotIn("LibraryFrame", self.album())

    def test_actions_are_lines_not_slabs(self):
        album = self.album()
        self.assertEqual(3, album.count("WashLine {"))
        line = (QML / "WashLine.qml").read_text(encoding="utf-8")
        self.assertIn("implicitHeight: 44", line)          # real target
        self.assertIn("Accessible.role: Accessible.Button", line)
        self.assertNotIn("radius:", line)                   # never a pill

    def test_protected_playback_behaviour_survives_the_redesign(self):
        album = self.album()
        # the parent-album exception plays the record whole, dislikes included
        self.assertIn("backend.playAlbum(view.files, 0)", album)
        # shuffle is rotation and stays filtered
        self.assertIn("backend.playFilesShuffled(view.files)", album)
        self.assertIn("backend.queueAlbum(view.files)", album)
        # exact (folder, album tag) membership is still the source of truth
        self.assertIn("backend.albumInfo(albumPath, albumName)", album)
        # every track keeps the shared row, its menu and its play-from-here
        self.assertIn("albumMode: true", album)
        self.assertIn("fileList: view.files", album)

    def test_rows_never_repeat_the_already_known_artist(self):
        album = self.album()
        self.assertIn("showArtist: false", album)
        self.assertIn("subText: view.credit(modelData)", album)
        # a credit equal to the album artist is not a credit
        self.assertIn("if (!artist || !primary || artist === primary)", album)

    def test_the_optional_credit_line_leaves_other_rows_at_44px(self):
        row = (QML / "TrackRow.qml").read_text(encoding="utf-8")
        self.assertIn('property string subText: ""', row)
        self.assertIn('height: row.subText !== "" ? 54 : 44', row)


class AliasManagerSurfaceTests(unittest.TestCase):
    """The alias pane in Library Doctor (Iann's direction 2026-08-21).

    Doctor is a LOCKED surface, so the pane joins it as a sixth condition and
    swaps only the detail field — Condition Theatre's composition is untouched.
    """

    def mgr(self):
        return (QML / "AliasManager.qml").read_text(encoding="utf-8")

    def doctor(self):
        return (QML / "DoctorView.qml").read_text(encoding="utf-8")

    def test_it_joins_doctor_without_disturbing_the_composition(self):
        doctor = self.doctor()
        self.assertIn('{ key: "aliases", label: "ARTIST ALIASES", tool: true }',
                      doctor)
        self.assertIn("AliasManager {", doctor)
        # every other detail state yields to the tool
        self.assertIn("&& !doc.toolSelected", doctor)

    def test_a_tool_condition_reports_no_findings(self):
        self.assertIn("if (conditionRows[index].tool) return [];", self.doctor())

    def test_the_three_parts_iann_asked_for_are_present(self):
        mgr = self.mgr()
        self.assertIn('objectName: "aliasSearchField"', mgr)   # searchable
        self.assertIn('text: "SUGGESTIONS"', mgr)              # suggestions line
        self.assertIn('text: "COMBINED INTO THIS ARTIST"', mgr)  # and the undo

    def test_a_suggestion_is_a_proposal_and_states_its_reason(self):
        mgr = self.mgr()
        self.assertIn("backend.aliasSuggestions(chosen)", mgr)
        self.assertIn("text: modelData.reason", mgr)
        # nothing attaches without an explicit activation
        self.assertIn("onActivated: mgr.attach(modelData.name)", mgr)

    def test_every_combination_is_reversible(self):
        mgr = self.mgr()
        self.assertIn("backend.removeArtistAlias(name)", mgr)
        self.assertIn('label: "Separate"', mgr)
        self.assertIn("never changes your tags", mgr)

    def test_rows_keep_the_app_wide_target(self):
        mgr = self.mgr()
        self.assertIn("height: 44", mgr)
        self.assertIn("Accessible.role: Accessible.Button", mgr)


class ReadingRoomWashTests(unittest.TestCase):
    """Rooms that carry long-form copy drop the sharp whole-record layer.

    Caught on Library Doctor against IC3PEAK's cover (2026-08-21): the veil
    alone could not hold reading copy against a busy record. These rooms keep
    the soft ambient field — the record's colour without its detail — which is
    the same mechanism Now Playing and Album View already rely on. The sharp
    record remains wherever the record is the subject.
    """

    def test_reading_rooms_are_named_and_drop_the_sharp_layer(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn('readonly property bool readingRoom: root.mode === "doctor"',
                      main)
        self.assertIn('|| root.mode === "settings"', main)
        self.assertIn('|| root.mode === "eq"', main)
        self.assertIn(
            "fitStrength: (playbackRoom || albumRoom || readingRoom) ? 0.0 : 1.0",
            main)

    def test_browse_rooms_keep_the_sharp_record(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertNotIn('root.mode === "browse"\n', main.split(
            "readonly property bool readingRoom:", 1)[1].split("\n\n", 1)[0])

    def test_the_doctor_count_column_reports_only_real_evidence(self):
        doctor = (QML / "DoctorView.qml").read_text(encoding="utf-8")
        self.assertIn("function countLabel(condition)", doctor)
        self.assertIn('return hasReport ? String(countFor(condition)) : "";',
                      doctor)
        self.assertIn('return aliasCount > 0 ? String(aliasCount) : "";', doctor)


class DoctorContactSheetTests(unittest.TestCase):
    """F2 · contact sheet + tag repair (Iann's verdict and direction 2026-08-21).

    The page was a slideshow: 33 outliers walked one at a time through a 20px
    pager, with no way to scan or compare the set. Findings now fill a grid,
    and only what fills the square changes with the condition.
    """

    def doctor(self):
        return (QML / "DoctorView.qml").read_text(encoding="utf-8")

    def test_findings_are_a_sheet_not_a_slideshow(self):
        doctor = self.doctor()
        self.assertIn('objectName: "doctorSpecimenSheet"', doctor)
        self.assertIn("model: doc.selectedRows", doctor)

    def test_a_group_finding_resolves_its_own_artwork(self):
        # a duplicate-version finding has no single `file`; its first member
        # stands for it
        self.assertIn("function fileFor(item)", self.doctor())
        self.assertIn("source: doc.fileFor(modelData)", self.doctor())

    def test_a_tag_finding_shows_its_missing_fields_as_the_specimen(self):
        doctor = self.doctor()
        self.assertIn("tile.missingFields.indexOf(modelData) >= 0", doctor)
        self.assertIn('"— missing"', doctor)
        self.assertIn('text: "UNREADABLE"', doctor)

    def test_guidance_and_actions_sit_beside_the_rail(self):
        doctor = self.doctor()
        self.assertIn("id: leftField", doctor)
        self.assertIn("doc.conditionCopy(doc.selectedCondition)", doctor)

    def test_a_tag_tile_opens_the_repair_page_with_the_whole_set(self):
        doctor = self.doctor()
        self.assertIn("signal repairRequested(int findingIndex)", doctor)
        self.assertIn("if (tagFinding) doc.repairRequested(index)", doctor)
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("tagRepair.open(", main)
        self.assertIn("doctorPage.findingsFor(3)", main)


class TagRepairTests(unittest.TestCase):
    """The repair page Iann specified: art, faults named per field, edge
    arrows through the set, direct editing, library-backed completion."""

    def repair(self):
        return (QML / "TagRepairView.qml").read_text(encoding="utf-8")

    def test_each_fault_is_stated_beside_its_own_field(self):
        repair = self.repair()
        self.assertIn('issue: "NEEDS ARTIST TAG"', repair)
        self.assertIn('issue: "NEEDS TITLE TAG"', repair)
        self.assertIn('issue: "NEEDS ALBUM TAG"', repair)
        field = (QML / "TagField.qml").read_text(encoding="utf-8")
        self.assertIn('objectName: "tagFieldIssue"', field)

    def test_the_set_is_walked_from_the_screen_edges(self):
        repair = self.repair()
        self.assertIn("component EdgeArrow", repair)
        self.assertIn("anchors.left: parent.left; delta: -1", repair)
        self.assertIn("anchors.right: parent.right; delta: 1", repair)
        self.assertIn("Keys.onLeftPressed: repair.step(-1)", repair)

    def test_completion_can_only_offer_names_the_library_already_uses(self):
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn("def tagSuggestions(self, field, prefix)", backend)
        self.assertIn('self._directory_rows("artists")', backend)
        field = (QML / "TagField.qml").read_text(encoding="utf-8")
        self.assertIn("backend.tagSuggestions(field, text)", field)

    def test_a_write_happens_only_on_an_explicit_save(self):
        repair = self.repair()
        self.assertIn("backend.updateTrackMetadata(file, values)", repair)
        self.assertIn('label: repair.saving ? "Saving…" : "Save tags →"', repair)
        # and the existing service keeps the safety guarantees
        meta = (ROOT / "ampere/metadata.py").read_text(encoding="utf-8")
        self.assertIn("if not backup_path.exists():", meta)
        self.assertIn("Metadata save could not be verified", meta)

    def test_the_scan_reports_per_field_state_without_writing(self):
        doctor = (ROOT / "ampere/doctor.py").read_text(encoding="utf-8")
        self.assertIn("def _tag_state(file: str, idx: dict, readable: bool)", doctor)
        self.assertIn('"missingCount": len(missing)', doctor)
        self.assertNotIn(".save()", doctor)


class VersionCompareTests(unittest.TestCase):
    """Every finding opens into its own page (Iann, 2026-08-21).

    A duplicate finding says two recordings share an identity; deciding
    whether they are the same performance needs the facts side by side.
    """

    def compare(self):
        return (QML / "VersionCompareView.qml").read_text(encoding="utf-8")

    def test_a_duplicate_tile_opens_the_comparison(self):
        doctor = (QML / "DoctorView.qml").read_text(encoding="utf-8")
        self.assertIn("signal compareRequested(int findingIndex)", doctor)
        self.assertIn("else if (doc.selectedCondition === 0)", doctor)
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("versionCompare.open(", main)
        self.assertIn("doctorPage.findingsFor(0)", main)

    def test_the_deciding_facts_are_shown_per_version(self):
        compare = self.compare()
        for key in ("format", "kbps", "sampleRate", "bitDepth", "bytes",
                    "duration", "plays", "album"):
            self.assertIn('key: "%s"' % key, compare)

    def test_a_disagreement_between_versions_is_marked(self):
        compare = self.compare()
        self.assertIn("function differs(key)", compare)
        self.assertIn("compare.differs(modelData.key)", compare)

    def test_the_set_is_walked_from_the_screen_edges(self):
        compare = self.compare()
        self.assertIn("component EdgeArrow", compare)
        self.assertIn("Keys.onLeftPressed: compare.step(-1)", compare)

    def test_nothing_is_merged_or_deleted(self):
        compare = self.compare()
        self.assertIn("backend.preferVersion(", compare)
        self.assertIn("Nothing is merged or deleted here", compare)
        for banned in ("deleteFile", "removeFile", "backend.delete"):
            self.assertNotIn(banned, compare)

    def test_editing_reuses_the_one_tag_editor(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("onEditRequested: track => {", main)
        self.assertIn("tagRepair.open([{ file: track.file", main)

    def test_the_reader_crosses_the_bridge_as_plain_variants(self):
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn('versionDetailsReady = Signal("QVariantMap")', backend)
        # a tuple nested in the payload arrives in QML as an empty array
        self.assertIn('"rows": [dict(row) for row in rows]', backend)
        self.assertNotIn('"rows": tuple(rows)', backend)


class DoctorDetailRoomTests(unittest.TestCase):
    """Doctor's detail pages keep the PLAYING record as their room.

    Iann, 2026-08-21: the persistent player sits directly below these pages,
    so a room showing a different record than the mini player reads as a
    mistake. Album View is deliberately the opposite — there the record on the
    page IS the subject.
    """

    def test_the_examination_pages_follow_the_player(self):
        for name in ("VersionCompareView.qml", "TagRepairView.qml"):
            text = (QML / name).read_text(encoding="utf-8")
            self.assertIn("ArchiveWash {", text)
            self.assertNotIn("sourceFile:", text)

    def test_album_view_still_owns_its_own_record(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        album = (QML / "AlbumView.qml").read_text(encoding="utf-8")
        self.assertIn("readonly property string roomFile:", album)
        self.assertIn("albumRoom ? albumPage.roomFile", main)


class CreditScopedArtistNavigationTests(unittest.TestCase):
    """An artist is reachable without knowing a folder.

    SPEC row 38 makes artist membership credit-scoped, never folder-scoped, so
    a caller that has only a NAME must be able to open the page. `openArtist`
    rejected an empty path, which silently killed the Album page's artist
    breadcrumb and the remote artist route (found 2026-08-22).
    """

    def test_a_name_alone_opens_the_artist_page(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        body = main.split("function openArtist(name, path) {", 1)[1].split("}", 1)[0]
        self.assertIn("if (!name) return", body)
        self.assertNotIn('path === ""', body)

    def test_the_credit_only_callers_still_pass_an_empty_path(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertIn('root.openArtist(name, "")', main)   # album breadcrumb
        self.assertIn('root.openArtist(arg, "")', main)    # remote route


class ArtistPageGrammarTests(unittest.TestCase):
    """Artist page conformed to the Album View grammar (ROADMAP 2.1).

    The page carried two `bgLow` slabs with borders and a decorative cover
    strip at 0.105 opacity behind the artist's name — the exact vocabulary
    Album View removed — and it sat in whatever record happened to be PLAYING.
    """

    def artist(self):
        return (QML / "ArtistView.qml").read_text(encoding="utf-8")

    def test_the_fields_are_not_slabs(self):
        artist = self.artist()
        self.assertNotIn("Qt.alpha(Theme.bgLow, 0.72)", artist)
        self.assertNotIn("Qt.alpha(Theme.bgLow, 0.54)", artist)

    def test_the_decorative_cover_strip_is_gone(self):
        self.assertNotIn("opacity: 0.105", self.artist())

    def test_the_subject_owns_the_room(self):
        artist = self.artist()
        self.assertIn("ArchiveWash {", artist)
        self.assertIn("sourceFile: view.roomFile", artist)
        self.assertIn("veil: 0.60", artist)
        self.assertIn("readonly property string roomFile:", artist)

    def test_a_release_row_names_a_guest_not_the_page_artist(self):
        artist = self.artist()
        self.assertIn("showArtist: false", artist)
        self.assertIn("subText: view.credit(modelData)", artist)
        self.assertIn("if (!artist || !primary || artist === primary) return \"\"",
                      artist)

    def test_the_biography_cannot_run_through_the_actions(self):
        # the banner is a fixed height with the actions pinned beneath it
        self.assertIn("maximumLineCount: view.compact ? 2 : 3", self.artist())


class UserFacingCopyTests(unittest.TestCase):
    """One spelling across everything a listener reads.

    The UI settled on American forms ("Album colors", "Current behavior"), so
    a stray British form reads as a typo rather than a house style.
    """

    BRITISH = ("neighbour", "colour", "behaviour", "analyse", "organis",
               "recognise", "centre ")

    def test_visible_copy_keeps_one_spelling(self):
        import re
        for path in sorted(QML.glob("*.qml")):
            text = path.read_text(encoding="utf-8")
            for value in re.findall(r'(?:text|tip|label|placeholderText): "([^"]+)"',
                                    text):
                lowered = value.casefold()
                for word in self.BRITISH:
                    self.assertNotIn(word, lowered,
                                     f"{path.name}: {value!r}")


class CompactRoomTests(unittest.TestCase):
    """Every room has to work narrow (SPEC row 207; Iann, 2026-08-22).

    Two defects drove these: Doctor's compact rail scrolled sideways so two of
    six conditions — Artist Aliases among them — sat past the edge with no
    affordance, and the pages added this session had no compact handling at
    all.
    """

    def test_the_compact_condition_rail_wraps_instead_of_scrolling(self):
        doctor = (QML / "DoctorView.qml").read_text(encoding="utf-8")
        self.assertIn("id: conditionFlow", doctor)
        self.assertIn("visible: doc.compact", doctor)
        # the vertical rail is the desktop form only
        self.assertIn("orientation: ListView.Vertical", doctor)
        self.assertNotIn("ListView.Horizontal", doctor)

    def test_compact_keeps_the_guidance_and_actions(self):
        doctor = (QML / "DoctorView.qml").read_text(encoding="utf-8")
        self.assertNotIn("visible: !doc.compact && doc.hasReport", doctor)

    def test_the_examination_pages_recompose(self):
        for name in ("TagRepairView.qml", "VersionCompareView.qml"):
            text = (QML / name).read_text(encoding="utf-8")
            self.assertIn("readonly property bool compact: width < 900", text)
            self.assertIn("compact ? 44 : 72", text.replace("40 : 72", "44 : 72"))

    def test_tag_repair_stacks_the_record_above_the_form(self):
        repair = (QML / "TagRepairView.qml").read_text(encoding="utf-8")
        self.assertIn("anchors.left: repair.compact ? parent.left : artColumn.right",
                      repair)
        self.assertIn("anchors.top: repair.compact ? artColumn.bottom : parent.top",
                      repair)

    def test_the_comparison_stays_side_by_side(self):
        # stacked versions cannot be compared at a glance, which is the page
        compare = (QML / "VersionCompareView.qml").read_text(encoding="utf-8")
        self.assertIn("compare.compact ? 20 : 40", compare)
        self.assertIn("compare.compact ? 84 : 118", compare)
        self.assertNotIn("compact ? 1 : compare.rows.length", compare)


class RoomActionsAndPlaylistTests(unittest.TestCase):
    """Play the room you are looking at, and file a song anywhere from the
    one track menu (Iann, 2026-08-22)."""

    def library(self):
        return (QML / "LibraryView.qml").read_text(encoding="utf-8")

    def test_a_room_can_be_played_shuffled_or_queued(self):
        library = self.library()
        self.assertIn('objectName: "libraryRoomActions"', library)
        self.assertIn("backend.playFiles(files, 0)", library)
        self.assertIn("backend.playFilesShuffled(files)", library)
        self.assertIn("backend.queueFiles(files)", library)

    def test_the_actions_obey_the_filter_and_sort(self):
        library = self.library()
        self.assertIn("function visibleFiles()", library)
        self.assertIn("return songFiles.slice()", library)
        self.assertIn("lib.visibleFiles()", library)

    def test_add_to_playlist_is_in_the_one_shared_menu(self):
        menu = (QML / "TrackActionMenu.qml").read_text(encoding="utf-8")
        self.assertIn('{id: "playlist", label: "ADD TO PLAYLIST  ›"}', menu)
        self.assertIn("backend.addToPlaylist(", menu)

    def test_the_menu_survives_the_pick_that_changes_its_page(self):
        ampere_menu = (QML / "AmpereMenu.qml").read_text(encoding="utf-8")
        self.assertIn("property bool closeOnPick: true", ampere_menu)
        self.assertIn("if (closeOnPick)", ampere_menu)
        self.assertIn("closeOnPick: false",
                      (QML / "TrackActionMenu.qml").read_text(encoding="utf-8"))

    def test_no_surface_keeps_a_parallel_track_menu(self):
        # SPEC · Search results, Iann verdict 2026-08-20 #7
        sleeve = (QML / "SleeveTrackRow.qml").read_text(encoding="utf-8")
        self.assertIn("TrackActionMenu {", sleeve)
        self.assertNotIn("AmpereMenu {", sleeve)

    def test_appending_never_rewrites_the_listeners_ordering(self):
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn("def addToPlaylist(self, name, files)", backend)
        self.assertIn("fresh = tuple(f for f in wanted if f not in have)", backend)
        self.assertIn("writer.save(playlist, current + fresh", backend)


class ArtistPortraitFallbackTests(unittest.TestCase):
    """With no verified portrait, show the artist's own record (Iann,
    2026-08-22) — never a stranger, never a bare initial."""

    def artist(self):
        return (QML / "ArtistView.qml").read_text(encoding="utf-8")

    def test_a_record_sleeve_stands_in_for_a_missing_portrait(self):
        artist = self.artist()
        self.assertIn("id: sleeveFallback", artist)
        self.assertIn("visible: portrait.status !== Image.Ready && view.roomFile", artist)

    def test_the_caption_never_claims_a_portrait_it_is_not_showing(self):
        self.assertIn('"FROM THIS ARTIST\'S RECORDS"', self.artist())

    def test_the_initial_remains_the_last_resort(self):
        artist = self.artist()
        self.assertIn("&& sleeveFallback.status !== Image.Ready", artist)


class RoomFilesPerformanceTests(unittest.TestCase):
    """Playing a room must not walk the library once per visible row.

    The first version asked the backend for each row's files, so playing the
    Artists room made 1,346 requests that each scanned 3,929 songs and
    recomputed every credit. It froze Ampere hard enough that it could not be
    closed (Iann, 2026-08-22).
    """

    def library(self):
        return (QML / "LibraryView.qml").read_text(encoding="utf-8")

    def test_a_room_is_resolved_in_one_request(self):
        library = self.library()
        self.assertIn('backend.libraryRoomFiles("artists", keys)', library)
        self.assertIn('backend.libraryRoomFiles("genres", keys)', library)
        self.assertIn('backend.libraryRoomFiles("folders", keys)', library)

    def test_no_per_row_membership_call_inside_a_loop(self):
        body = self.library().split("function visibleFiles()", 1)[1] \
                             .split("readonly property bool roomIsPlayable", 1)[0]
        for banned in ("backend.artistFiles(", "backend.genreFiles(",
                       "backend.folderFiles("):
            self.assertNotIn(banned, body)

    def test_the_backend_builds_one_index_and_bounds_the_result(self):
        backend = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertIn("def libraryRoomFiles(self, kind, keys)", backend)
        self.assertIn("ROOM_FILE_LIMIT", backend)
        body = backend.split("def libraryRoomFiles(self, kind, keys)", 1)[1] \
                      .split("@Slot", 1)[0]
        # exactly one pass over the library per room, not one per key
        self.assertEqual(3, body.count("for song in songs:"))


class FolderPageGrammarTests(unittest.TestCase):
    """Folders conformed to the Album View grammar (ROADMAP 2.2)."""

    def frame(self):
        return (QML / "LibraryFrame.qml").read_text(encoding="utf-8")

    def test_the_detail_frame_uses_line_actions(self):
        frame = self.frame()
        self.assertIn("delegate: WashLine {", frame)
        self.assertNotIn("component WashAction", frame)

    def test_a_detail_page_does_not_wear_the_index_rail(self):
        frame = self.frame()
        self.assertNotIn("readonly property var destinations:", frame)
        self.assertNotIn("Accessible.PageTab", frame)

    def test_a_folder_row_names_only_a_differing_credit(self):
        browse = (QML / "BrowseView.qml").read_text(encoding="utf-8")
        self.assertIn("showArtist: false", browse)
        self.assertIn("subText: view.credit(trackData)", browse)
        self.assertIn("readonly property string folderArtist:", browse)


class GenreAndPlaylistGrammarTests(unittest.TestCase):
    """Genres and Playlist detail conformed to the Album View grammar
    (ROADMAP 2.2, 2026-08-22)."""

    def library(self):
        return (QML / "LibraryView.qml").read_text(encoding="utf-8")

    def playlists(self):
        return (QML / "PlaylistsView.qml").read_text(encoding="utf-8")

    def test_a_genre_is_a_room_and_a_room_plays(self):
        library = self.library()
        self.assertIn('objectName: "libraryGenreDetailActions"', library)
        for name in ("libraryGenrePlay", "libraryGenreShuffle",
                     "libraryGenreQueue"):
            self.assertIn(f'objectName: "{name}"', library)
        # The room plays exactly the membership the page is showing.
        self.assertIn("var files = lib.selectedGenreFiles", library)

    def test_playlist_detail_states_its_actions_as_lines(self):
        playlists = self.playlists()
        self.assertNotIn("component HeaderAction", playlists)
        self.assertNotIn("HeaderAction {", playlists)
        for name in ("playlistPlayAction", "playlistShuffleAction",
                     "playlistQueueAction"):
            self.assertIn(f'objectName: "{name}"', playlists)

    def test_both_retreats_are_line_actions(self):
        self.assertRegex(
            self.library(),
            r"WashLine \{\s*\n\s*id: allGenresAction",
        )
        self.assertRegex(
            self.playlists(),
            r"WashLine \{\s*\n\s*id: allSequences",
        )

    def test_the_actions_read_in_one_order_everywhere(self):
        # Play → Shuffle → Queue, the order Album View set.
        for text in (self.library(), self.playlists(), (
                QML / "AlbumView.qml").read_text(encoding="utf-8")):
            order = [m for m in re.findall(
                r'label: "(Play →|Play album →|Shuffle|Queue)"', text)]
            self.assertTrue(order, "no line actions found")
            for i in range(0, len(order) - 2, 3):
                self.assertTrue(order[i].startswith("Play"), order)
                self.assertEqual(order[i + 1], "Shuffle", order)
                self.assertEqual(order[i + 2], "Queue", order)


class DoctorIndexGrammarTests(unittest.TestCase):
    """The Doctor reads consistently with its own detail pages
    (ROADMAP 2.3, 2026-08-22)."""

    def doctor(self):
        return (QML / "DoctorView.qml").read_text(encoding="utf-8")

    def test_every_condition_row_can_actually_be_selected(self):
        # Artist Aliases was added as a sixth row while selectCondition still
        # clamped at 4, so choosing it landed on Loudness Outliers and the
        # alias manager could not be opened at all.
        doctor = self.doctor()
        self.assertNotIn("Math.min(index, 4)", doctor)
        self.assertIn("conditionRows.length - 1", doctor)
        rows = doctor.count('{ key: "')
        self.assertGreaterEqual(rows, 6, "condition rows shrank unexpectedly")

    def test_the_guidance_belongs_to_the_selected_condition(self):
        # At the bottom of the list it read as a description of whichever row
        # happened to sit last (Artist Aliases), not of the chosen one.
        doctor = self.doctor()
        self.assertIn("component ConditionGuidance:", doctor)
        self.assertIn("conditionSlot.chosen", doctor)
        self.assertIn("visible: doc.compact", doctor)


class ParkedDjIsNotInNavigationTests(unittest.TestCase):
    """SPEC UNDESIGNED #10 parks DJ: it may not be designed, implemented, or
    placed in navigation until Iann defines the mixer workflow. It was still
    a menu entry, a Features room, a restorable mode and a live page
    (ROADMAP 3.2, 2026-08-22)."""

    def test_no_navigation_surface_offers_dj(self):
        for name in ("WhisperRail.qml", "FeaturesView.qml", "Main.qml"):
            text = (QML / name).read_text(encoding="utf-8")
            self.assertNotIn('"dj"', text, name)
            self.assertNotIn("DJ Studio", text, name)
            self.assertNotIn("DJ studio", text, name)

    def test_the_router_cannot_restore_or_reach_it(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        self.assertNotIn("DjView {", main)
        modes = main.split("_restorableModes: [", 1)[1].split("]", 1)[0]
        self.assertNotIn("dj", modes)

    def test_the_parked_page_and_its_backend_are_kept_as_evidence(self):
        # Parked is not deleted: the page stays on disk and the planner keeps
        # its tests, so resuming DJ starts from evidence rather than nothing.
        self.assertTrue((QML / "DjView.qml").exists())
        self.assertTrue((QML / ".." / "ampere" / "dj").resolve().is_dir())


class FloorContainmentTests(unittest.TestCase):
    """SPEC row 208 gives the window a 720x480 floor and requires room content
    to stay above the persistent player. Several rooms did not (ROADMAP 5.1,
    2026-08-22)."""

    def test_the_room_never_paints_over_the_player(self):
        main = (QML / "Main.qml").read_text(encoding="utf-8")
        room = main.split("id: room", 1)[1].split("// ---------- offline strip", 1)[0]
        self.assertIn("clip: true", room)
        self.assertIn("anchors.bottom: root.barHidden ? parent.bottom : bar.top",
                      room)

    def test_the_page_origin_follows_the_spec_formula(self):
        # The old `h < 620 ? 66` clamp spent MORE than height x 0.11 on short
        # windows, which is where pages ran out of height.
        theme = (QML / "Theme.qml").read_text(encoding="utf-8")
        self.assertIn("function pageTop(h) { return Math.max(28, h * 0.11) }",
                      theme)

    def test_disliked_actions_outrank_its_contact_sheet(self):
        disliked = (QML / "DislikedView.qml").read_text(encoding="utf-8")
        self.assertIn("heightBudget", disliked)
        self.assertIn("compactActions.implicitHeight", disliked)
        # The sheet gives way; the only controls on the page do not — and
        # the budget only ever REDUCES the width-derived size.
        self.assertIn("readonly property real widthSize:", disliked)
        self.assertIn("Math.min(widthSize, heightBudget)", disliked)


class SoundCharacterSurfaceTests(unittest.TestCase):
    """Ampy gained the audited SOUND axis and a MIXES tab; Sound Profiles are
    replaced rather than redesigned (Iann, 2026-08-22, SPEC UNDESIGNED #13)."""

    def ampy(self):
        return (QML / "AmpyView.qml").read_text(encoding="utf-8")

    def test_the_page_has_both_tabs(self):
        ampy = self.ampy()
        self.assertIn('objectName: "ampyTabs"', ampy)
        self.assertIn('objectName: "ampySessionTab"', ampy)
        self.assertIn('objectName: "ampyMixesTab"', ampy)
        self.assertIn('objectName: "ampyMixShelf"', ampy)

    def test_sound_joins_the_sentence_and_mutes_mood_when_named(self):
        ampy = self.ampy()
        self.assertIn('label: "SOUND:"', ampy)
        self.assertIn('nextObjectName: "ampyCharacterNext"', ampy)
        # A mood arc and a measured character are different instruments.
        self.assertIn("enabled: page.selectedCharacter === \"\"", ampy)

    def test_a_named_character_builds_plays_and_is_kept(self):
        ampy = self.ampy()
        self.assertIn("backend.buildCharacterMix(", ampy)
        self.assertIn("It is kept under MIXES", ampy)

    def test_the_sentence_wraps_instead_of_running_off_the_edge(self):
        ampy = self.ampy()
        self.assertIn("Flow {", ampy)
        self.assertIn("width: optionsLane.width", ampy)
        # Binding a Flow's width to its own implicitWidth is circular.
        self.assertNotIn("Math.min(implicitWidth, optionsLane.width)", ampy)

    def test_a_kept_mix_can_play_port_or_be_forgotten(self):
        shelf = (QML / "MixShelf.qml").read_text(encoding="utf-8")
        for call in ("backend.playSoundMix(", "backend.saveSoundMixAs(",
                     "backend.forgetSoundMix("):
            self.assertIn(call, shelf)
        self.assertIn('objectName: "mixShelfEmpty"', shelf)


class RewindLockedModesTests(unittest.TestCase):
    """SPEC row 33 ships Rewind with its upper composition LOCKED to three
    modes. Sonic DNA reads listening shape and is unrelated to the retired
    Saved Sound Profiles; it was removed with them by mistake (2026-08-23)."""

    def test_all_three_locked_modes_are_present(self):
        rewind = (QML / "RewindView.qml").read_text(encoding="utf-8")
        for mode in ('{k: "listening", t: "MEMORY"}',
                     '{k: "chapters", t: "CHAPTERS"}',
                     '{k: "sound", t: "SONIC DNA"}'):
            self.assertIn(mode, rewind)

    def test_the_sonic_dna_mode_still_loads_its_evidence(self):
        rewind = (QML / "RewindView.qml").read_text(encoding="utf-8")
        self.assertIn("backend.requestSoundProfile()", rewind)
        self.assertIn('if (t === "sound") loadSound()', rewind)
