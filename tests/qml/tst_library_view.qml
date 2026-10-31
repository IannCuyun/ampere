import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "LibraryDislikedEntryBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property bool connected: true
        // Without this the shelf binds !genreDetailOpen && undefined, which
        // Qt refuses to assign — so the first genre detail latched the shelf
        // invisible for every later test (found 2026-08-23).
        property bool libraryReady: true
        property var playlists: ["Dark Passage", "Night Drive"]
        property var playlistPlayCounts: ({})
        property var dislikedFiles: ["one.flac", "two.flac"]
        property var likedFiles: []
        property var currentSong: ({})
        property var artColors: ["#d18a55", "#614634"]
        readonly property var defaultAlbumRows: [
            { path: "Alpha", cover: "Alpha/01.flac", album: "Alpha",
              artist: "Artist One", year: 2026, added: 8 },
            { path: "Beta", cover: "Beta/01.flac", album: "Beta",
              artist: "Artist Two", year: 2025, added: 7 },
            { path: "Gamma", cover: "Gamma/01.flac", album: "Gamma",
              artist: "Artist Three", year: 2024, added: 6 },
            { path: "Delta", cover: "Delta/01.flac", album: "Delta",
              artist: "Artist Four", year: 2023, added: 5 },
            { path: "Epsilon", cover: "Epsilon/01.flac", album: "Epsilon",
              artist: "Artist Five", year: 2022, added: 4 },
            { path: "Zeta", cover: "Zeta/01.flac", album: "Zeta",
              artist: "Artist Six", year: 2021, added: 3 },
            { path: "Eta", cover: "Eta/01.flac", album: "Eta",
              artist: "Artist Seven", year: 2020, added: 2 },
            { path: "Theta", cover: "Theta/01.flac", album: "Theta",
              artist: "Artist Eight", year: 2019, added: 1 }
        ]
        property var albumRows: defaultAlbumRows
        readonly property var defaultArtistRows: [
            { name: "Alpha Artist", path: "Artists/Alpha", albums: 8,
              songs: 72, portrait: "Alpha/album.flac" },
            { name: "Beta Band", path: "Artists/Beta", albums: 7,
              songs: 63, portrait: "Beta/album.flac" },
            { name: "Gamma Group", path: "Artists/Gamma", albums: 6,
              songs: 54, portrait: "Gamma/album.flac" },
            { name: "Delta Duo", path: "Artists/Delta", albums: 5,
              songs: 45, portrait: "Delta/album.flac" },
            { name: "Epsilon Ensemble", path: "Artists/Epsilon", albums: 4,
              songs: 36, portrait: "Epsilon/album.flac" },
            { name: "Zeta Singer", path: "Artists/Zeta", albums: 3,
              songs: 27, portrait: "Zeta/album.flac" },
            { name: "Eta Musician", path: "Artists/Eta", albums: 2,
              songs: 18, portrait: "Eta/album.flac" },
            { name: "Theta Composer", path: "Artists/Theta", albums: 1,
              songs: 9, portrait: "Theta/album.flac" }
        ]
        property var artistRows: defaultArtistRows
        readonly property var defaultGenreRows: [
            { name: "Ambient", covers: ["A/one.flac", "A/two.flac"],
              albums: 12, artists: 8, songs: 64 },
            { name: "Dark Folk", covers: ["B/one.flac", "B/two.flac"],
              albums: 10, artists: 7, songs: 52 },
            { name: "Deathcore", covers: ["C/one.flac", "C/two.flac"],
              albums: 9, artists: 6, songs: 48 },
            { name: "Electronic", covers: ["D/one.flac", "D/two.flac"],
              albums: 8, artists: 5, songs: 40 },
            { name: "Hyperpop", covers: ["E/one.flac", "E/two.flac"],
              albums: 7, artists: 4, songs: 32 },
            { name: "Post-Punk", covers: ["F/one.flac", "F/two.flac"],
              albums: 6, artists: 3, songs: 24 },
            { name: "Sacred", covers: ["G/one.flac", "G/two.flac"],
              albums: 5, artists: 2, songs: 16 }
        ]
        property var genreRows: defaultGenreRows
        property var artistBioRequests: []
        property var artistPortraitPrimeCalls: []
        property var artistPortraitPriorityCalls: []
        property var artistPortraitActiveCalls: []
        readonly property var defaultSongRows: [
            { file: "a.flac", title: "Aerials", artist: "System of a Down",
              album: "Toxicity", duration: 235 },
            { file: "b.flac", title: "Blue Monday", artist: "New Order",
              album: "Power, Corruption & Lies", duration: 449 },
            { file: "c.flac", title: "Ceremony", artist: "New Order",
              album: "Substance", duration: 286 },
            { file: "d.flac", title: "Digital Bath", artist: "Deftones",
              album: "White Pony", duration: 255 }
        ]
        property var songRows: defaultSongRows
        property var folderRows: [
            { name: "Metal & Rock", path: "Music/Metal & Rock",
              cover: "metal/top-album.flac", items: 759,
              modified: 1785628800 },
            { name: "Incoming", path: "Music/Incoming",
              cover: "incoming/top-album.flac", items: 1054,
              modified: 1788307200 },
            { name: "Folk", path: "Music/Folk",
              cover: "folk/top-album.flac", items: 32,
              modified: 1785628800 }
        ]
        property var playFilesCalls: []
        property var playlistRequests: []
        property var playlistActions: []
        signal databaseUpdated()
        signal libraryStatsChanged()
        signal dislikedChanged()
        signal artistBioReady(string artistName, var info)
        signal artistPortraitsReady(var portraitKeys)
        signal librarySongsReady(int serial, var rows)
        signal playlistCoversChanged()
        signal playlistTracksReady(string name, var rows, bool success)

        function stats() {
            return {albums: 4, artists: 3, songs: 12,
                    genres: genreRows.length}
        }
        function requestLibrarySummary() {}
        function libraryAlbums() { return albumRows }
        function libraryArtists() { return artistRows }
        function librarySongs() { return songRows }
        function requestLibrarySongs(serial) {
            librarySongsReady(serial, songRows)
        }
        function libraryGenres() { return genreRows }
        function libraryGenreDetail(name) {
            const wanted = String(name || "").toLowerCase()
            if (wanted !== "ambient")
                return ({})
            const tracks = [
                { file: "A/one.flac", title: "Still Air",
                  artist: "Alpha Artist", album: "Alpha", duration: 241,
                  genres: ["Ambient"] },
                { file: "A/two.flac", title: "Low Horizon",
                  artist: "Beta Artist", album: "Beta", duration: 308,
                  genres: ["Ambient"] }
            ]
            return {
                name: "Ambient",
                cover: "A/one.flac",
                covers: ["A/one.flac", "A/two.flac"],
                artists: 2,
                songs: 2,
                albums: [
                    { path: "Alpha", cover: "A/one.flac", album: "Alpha",
                      artist: "Alpha Artist", songs: 1 },
                    { path: "Beta", cover: "A/two.flac", album: "Beta",
                      artist: "Beta Artist", songs: 1 }
                ],
                tracks: tracks
            }
        }
        function libraryFolders(path) { return folderRows }
        function songInfo(file) {
            return {file: file, title: file, artist: "", album: ""}
        }
        function playFiles(files, index) {
            playFilesCalls = playFilesCalls.concat([
                { files: Array.from(files), index: index }
            ])
        }
        function playPlaylistFiles(name, files, index) {
            playlistActions = playlistActions.concat([{
                name: name, files: Array.from(files), index: index
            }])
        }
        function playNext(file) {}
        function queuePath(file) {}
        function toggleLike(file) {}
        function moreLikeThis(file) {}
        function requestArtistBio(artistName) {
            artistBioRequests = artistBioRequests.concat([artistName])
        }
        function primeArtistPortraits(artistNames) {
            artistPortraitPrimeCalls = artistPortraitPrimeCalls.concat([
                Array.from(artistNames)
            ])
        }
        function prioritizeArtistPortraits(visibleNames, nearbyNames) {
            artistPortraitPriorityCalls = artistPortraitPriorityCalls.concat([{
                visible: Array.from(visibleNames),
                nearby: Array.from(nearbyNames)
            }])
        }
        function setArtistPortraitPrefetchActive(active) {
            artistPortraitActiveCalls = artistPortraitActiveCalls.concat([
                Boolean(active)
            ])
        }
        function playlistCovers() {
            return {
                "Dark Passage": ["a.flac", "b.flac", "c.flac", "d.flac"],
                "Night Drive": ["b.flac", "c.flac", "d.flac", "a.flac"]
            }
        }
        function requestPlaylistCovers() {}
        function playlistTracks(name) {
            playlistRequests = playlistRequests.concat([name])
            return [{file: name + "/01.flac", title: "Opening",
                     artist: "Artist", album: name, duration: 180}]
        }
        function loadPlaylist(name, replace) {
            playlistActions = playlistActions.concat([
                {name: name, replace: replace}
            ])
        }
        function shufflePlaylistNow(name) {
            playlistActions = playlistActions.concat([
                {name: name, shuffle: true}
            ])
        }
    }

    LibraryView {
        id: library
        parent: testCase
        width: testCase.width
        height: testCase.height
        tab: "albums"
        active: true
    }

    SignalSpy {
        id: openSpy
        target: library
        signalName: "openDisliked"
    }

    SignalSpy {
        id: albumSpy
        target: library
        signalName: "openAlbum"
    }

    SignalSpy {
        id: artistSpy
        target: library
        signalName: "openArtistPage"
    }

    SignalSpy {
        id: folderSpy
        target: library
        signalName: "openFolder"
    }

    function init() {
        // A test that fails before restoring the width used to leave every
        // later test at the compact size; settling here contains the damage
        // to the one test that actually broke (2026-08-23).
        testCase.width = 1280
        wait(0)
        provider.dislikedFiles = ["one.flac", "two.flac"]
        provider.dislikedChanged()
        provider.albumRows = provider.defaultAlbumRows
        provider.artistRows = provider.defaultArtistRows
        provider.genreRows = provider.defaultGenreRows
        provider.playlists = ["Dark Passage", "Night Drive"]
        provider.artistBioRequests = []
        provider.artistPortraitPrimeCalls = []
        provider.artistPortraitPriorityCalls = []
        provider.artistPortraitActiveCalls = []
        provider.songRows = provider.defaultSongRows
        provider.playFilesCalls = []
        provider.playlistRequests = []
        provider.playlistActions = []
        library.openRoom("albums")
        library.filterQuery = ""
        library.sortAlbums = "added"
        library.sortAlbumsDescending = true
        library.sortArtists = "name"
        library.sortArtistsDescending = false
        library.sortGenres = "name"
        library.sortGenresDescending = false
        library.artistPortraitKeys = ({})
        openSpy.clear()
        albumSpy.clear()
        artistSpy.clear()
        folderSpy.clear()
        wait(0)
    }

    function test_count_is_reactive_and_separate_from_six_destinations() {
        const action = findChild(library, "libraryDislikedAction")
        const label = findChild(library, "libraryDislikedLabel")
        verify(action !== null && label !== null)
        compare(library.tabRow.length, 6)
        compare(label.text, "DISLIKED · 2")

        provider.dislikedFiles = ["one.flac", "two.flac", "three.flac"]
        provider.dislikedChanged()
        wait(0)
        compare(label.text, "DISLIKED · 3")
    }

    function test_keyboard_invokes_the_route_once_with_a_44px_target() {
        const action = findChild(library, "libraryDislikedAction")
        tryCompare(action, "height", 84)
        action.forceActiveFocus()
        verify(action.activeFocus)
        keyClick(Qt.Key_Return)
        compare(openSpy.count, 1)
    }

    function test_open_room_index_preserves_six_rooms_and_extension_lane() {
        const index = findChild(library, "libraryRoomIndex")
        const extension = findChild(library, "libraryExtensionLane")
        verify(index !== null && extension !== null)
        compare(library.tabRow.length, 6)
        verify(extension.height >= 84)
        for (const room of library.tabRow) {
            const choice = findChild(library, "libraryRoomChoice_" + room.key)
            verify(choice !== null)
            verify(choice.height >= 44)
        }
    }

    function test_room_choice_keyboard_updates_the_active_shelf() {
        const artists = findChild(library, "libraryRoomChoice_artists")
        artists.forceActiveFocus()
        verify(artists.activeFocus)
        keyClick(Qt.Key_Return)
        compare(library.tab, "artists")
    }

    function test_playlists_room_opens_the_single_sequence_shelves_owner() {
        library.tab = "albums"
        const playlists = findChild(library, "libraryRoomChoice_playlists")
        playlists.forceActiveFocus()
        verify(playlists.activeFocus)
        keyClick(Qt.Key_Return)
        compare(library.tab, "playlists")
        compare(findChild(library, "playlistList"), null)
        const surface = findChild(library, "libraryPlaylistSurface")
        const wall = findChild(library, "playlistWall")
        verify(surface !== null && surface.visible)
        verify(wall !== null && wall.visible)

        const second = findChild(library, "playlistSequence_1")
        verify(second !== null)
        second.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(library.selectedPlaylist, "Night Drive")
        compare(provider.playlistRequests.length, 1)
        compare(provider.playlistRequests[0], "Night Drive")

        const workspace = findChild(library, "libraryWorkspace")
        const index = findChild(library, "libraryRoomIndex")
        const shelfHeader = findChild(library, "libraryShelfHeader")
        compare(surface.parent, workspace)
        compare(surface.x, 0)
        compare(surface.y, 0)
        compare(surface.width, workspace.width)
        compare(surface.height, workspace.height)
        compare(index.visible, false)
        compare(shelfHeader.visible, false)
        verify(findChild(library, "playlistSelectedMosaic") !== null)
        verify(findChild(library, "librarySleeveTrackArt_0") !== null)

        const retreat = findChild(library, "playlistAllSequences")
        retreat.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(library.selectedPlaylist, "")
        compare(index.visible, true)
        compare(shelfHeader.visible, true)
    }

    function test_filtered_playlist_empty_state_is_exclusive_at_both_widths() {
        library.openRoom("playlists")
        library.filterQuery = "does not exist"
        wait(0)
        const permanentEmpty = findChild(library, "playlistEmptyState")
        const filteredEmpty = findChild(library, "libraryFilteredEmptyState")
        verify(permanentEmpty !== null && filteredEmpty !== null)

        const widths = [1280, 680]
        for (let i = 0; i < widths.length; ++i) {
            testCase.width = widths[i]
            wait(0)
            verify(!permanentEmpty.visible)
            verify(filteredEmpty.visible)
        }
    }

    function test_compact_index_and_shelf_stay_contained() {
        testCase.width = 680
        wait(0)
        const action = findChild(library, "libraryDislikedAction")
        const index = findChild(library, "libraryRoomIndex")
        const grid = findChild(library, "libraryRoomGrid")
        const shelfHeader = findChild(library, "libraryShelfHeader")
        const shelves = findChild(library, "libraryShelves")
        compare(action.visible, false)
        verify(index.x >= 0)
        verify(index.x + index.width <= index.parent.width + 0.5)
        compare(grid.height, 142)
        verify(shelfHeader.y >= index.y + index.height)
        verify(shelves.y >= shelfHeader.y + shelfHeader.height)
        verify(shelves.height > 0)
        library.openPlaylist("")
        wait(0)
        const playlistSurface = findChild(library, "libraryPlaylistSurface")
        const playlistWall = findChild(library, "playlistWall")
        verify(playlistSurface.visible)
        compare(playlistWall.cols, 2)
        verify(playlistSurface.x >= 0)
        verify(playlistSurface.x + playlistSurface.width
               <= playlistSurface.parent.width + 0.5)
        testCase.width = 1280
    }

    function test_open_wall_shell_is_shared_by_all_collection_rooms() {
        testCase.width = 1280
        library.showAllGenres()
        library.openPlaylist("")
        const rooms = ["albums", "artists", "songs", "genres", "folders",
                       "playlists"]
        for (let i = 0; i < rooms.length; ++i) {
            library.openRoom(rooms[i])
            wait(0)
            const title = findChild(library, "libraryPageTitle")
            const index = findChild(library, "libraryRoomIndex")
            const workspace = findChild(library, "libraryWorkspace")
            const header = findChild(library, "libraryShelfHeader")
            const shelves = findChild(library, "libraryShelves")
            const disliked = findChild(library, "libraryDislikedAction")
            verify(library.collectionOpenWall)
            compare(title.width, index.width)
            compare(header.x, 0)
            compare(header.width, index.width - 18)
            fuzzyCompare(header.y,
                         workspace.height - header.height - 8, 0.5)
            fuzzyCompare(shelves.x, index.width + 18, 0.5)
            fuzzyCompare(shelves.y, -workspace.y, 0.5)
            compare(disliked.visible, false)
        }
    }

    function test_halfScreenWidthUsesTheCompactRoomIndex() {
        testCase.width = 948
        wait(0)
        verify(library.compact)
        const grid = findChild(library, "libraryRoomGrid")
        compare(grid.columns, 2)
        testCase.width = 1280
    }

    function openSongs() {
        library._loadedSongs = false
        library.tab = "songs"
        library.loadTab()
        tryCompare(library, "_loadedSongs", true)
        wait(0)
    }

    function openAlbums() {
        library._loadedAlbums = false
        library.tab = "albums"
        library.loadTab()
        tryCompare(library, "_loadedAlbums", true)
        wait(0)
    }

    function openArtists() {
        if (library.tab === "artists") {
            library.tab = "albums"
            wait(0)
        }
        library._loadedArtists = false
        library.tab = "artists"
        library.loadTab()
        tryCompare(library, "_loadedArtists", true)
        wait(0)
    }

    function openGenres() {
        // Land on the genres INDEX. A previous test that opened a genre
        // detail left it open, and an invisible parent makes every child
        // read invisible in Qt Quick — which is what broke the three tests
        // after it (2026-08-23).
        library.showAllGenres()
        if (library.tab === "genres") {
            library.tab = "albums"
            wait(0)
        }
        library._loadedGenres = false
        library.tab = "genres"
        library.loadTab()
        tryCompare(library, "_loadedGenres", true)
        wait(0)
    }

    function test_album_open_wall_establishes_repeating_scale_hierarchy() {
        openAlbums()
        const stage = findChild(library, "libraryAlbumOpenWallMeasure_0")
        const hero = findChild(library, "libraryAlbumHero")
        const heroArt = findChild(library, "libraryAlbumHeroArt")
        const supportArt = findChild(library, "libraryAlbumSupportArt_0")
        const medium = findChild(library, "libraryAlbumCell_5")
        const lowerSupport = findChild(library, "libraryAlbumCell_7")
        const grid = findChild(library, "libraryAlbumGrid")
        const wall = findChild(library, "libraryAlbumOpenWall")
        verify(stage !== null && hero !== null && heroArt !== null)
        verify(supportArt !== null && medium !== null && lowerSupport !== null)
        verify(grid !== null && wall !== null)
        compare(grid.measureSize, 10)
        compare(grid.measureCount, 1)
        verify(heroArt.width >= supportArt.width * 1.7)
        compare(grid.columns, 7)
        compare(wall.measureFloor, wall.height)
        verify(stage.height >= grid.height - 0.5)
        tryCompare(grid, "contentY", 0)
        const stageInGrid = stage.mapToItem(grid, 0, 0)
        verify(stageInGrid.y >= -0.5)
        verify(stageInGrid.y < grid.height)
        const heroInStage = hero.mapToItem(stage, 0, 0)
        const mediumInStage = medium.mapToItem(stage, 0, 0)
        const lowerInStage = lowerSupport.mapToItem(stage, 0, 0)
        verify(heroInStage.y > 0)
        fuzzyCompare(heroInStage.y,
                     Math.floor((stage.height - hero.height - 2) / 2), 0.5)
        verify(mediumInStage.y > supportArt.height)
        fuzzyCompare(mediumInStage.y, stage.desktopLowerBandY, 0.5)
        verify(lowerInStage.y >= mediumInStage.y)
        verify(lowerInStage.y + lowerSupport.height <= stage.height + 0.5)
        verify(stage.height
               - (stage.desktopLowerBandY + stage.desktopLowerBandHeight)
               <= 2.5)
    }

    function test_album_open_wall_compact_recomposes_inside_the_shelf() {
        openAlbums()
        testCase.width = 680
        wait(0)
        const stage = findChild(library, "libraryAlbumOpenWallMeasure_0")
        const hero = findChild(library, "libraryAlbumHero")
        const support = findChild(library, "libraryAlbumSupport_0")
        const grid = findChild(library, "libraryAlbumGrid")
        const wall = findChild(library, "libraryAlbumOpenWall")
        compare(grid.columns, 3)
        compare(grid.measureSize, 6)
        compare(wall.measureFloor, 0)
        const heroInStage = hero.mapToItem(stage, 0, 0)
        const supportInStage = support.mapToItem(stage, 0, 0)
        verify(heroInStage.x >= 0)
        verify(heroInStage.x + hero.width <= stage.width + 0.5)
        verify(supportInStage.x >= 0)
        verify(supportInStage.x + support.width <= stage.width + 0.5)
        verify(supportInStage.y + support.height <= stage.height + 0.5)
        testCase.width = 1280
    }

    function test_album_monolith_keyboard_opens_exact_featured_album() {
        openAlbums()
        const hero = findChild(library, "libraryAlbumHero")
        hero.forceActiveFocus()
        verify(hero.activeFocus)
        keyClick(Qt.Key_Return)
        compare(albumSpy.count, 1)
        compare(albumSpy.signalArguments[0][0], "Alpha")
        compare(albumSpy.signalArguments[0][1], "Alpha")
    }

    function test_artist_monolith_establishes_dedicated_image_hierarchy() {
        openArtists()
        const stage = findChild(library, "libraryArtistMonolithStage")
        const hero = findChild(library, "libraryArtistHero")
        const heroPortrait = findChild(library,
                                       "libraryArtistHeroPortrait")
        const heroFallback = findChild(library,
                                       "libraryArtistHeroFallback")
        const shelfLabel = findChild(library, "libraryShelfLabel")
        const support = findChild(library, "libraryArtistSupport_0")
        const grid = findChild(library, "libraryArtistGrid")
        verify(stage !== null && hero !== null && heroPortrait !== null)
        verify(heroFallback !== null && shelfLabel !== null)
        verify(support !== null && grid !== null)
        compare(library.artistSupports.length, 4)
        compare(library.artistRemainder.length, 3)
        verify(hero.width >= support.width * 1.7)
        verify(grid.cols >= 3)
        fuzzyCompare(stage.height, grid.height, 0.5)
        tryCompare(grid, "contentY", grid.originY)

        // The local representative album file is deliberately ignored.
        compare(heroPortrait.source.toString(), "")
        compare(heroFallback.text, "AA")
        verify(heroFallback.visible)
        verify(!shelfLabel.visible)
        tryVerify(() => provider.artistPortraitPrimeCalls.length > 0)
        compare(provider.artistPortraitPrimeCalls[0].length,
                provider.defaultArtistRows.length)
        tryVerify(() => provider.artistPortraitPriorityCalls.length > 0)
        const priority = provider.artistPortraitPriorityCalls[
            provider.artistPortraitPriorityCalls.length - 1]
        verify(priority.visible.indexOf("Alpha Artist") !== -1)
        // QML reports intent only; the backend owns every network request.
        compare(provider.artistBioRequests.length, 0)
        const key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        provider.artistPortraitsReady({"Alpha Artist": key})
        tryCompare(heroPortrait, "source",
                   "image://art/portrait-full:" + key)
    }

    function test_artist_portrait_work_pauses_outside_artist_room() {
        openArtists()
        tryVerify(() => provider.artistPortraitActiveCalls.indexOf(true) !== -1)
        library.openRoom("albums")
        tryVerify(() => provider.artistPortraitActiveCalls.length > 0
                  && provider.artistPortraitActiveCalls[
                      provider.artistPortraitActiveCalls.length - 1] === false)
    }

    function test_artist_far_jump_promotes_target_before_positioning() {
        var rows = []
        for (var index = 0; index < 30; ++index) {
            rows.push({name: "Artist " + String(index).padStart(2, "0"),
                       path: "Artists/" + index, albums: 1, songs: 1})
        }
        provider.artistRows = rows
        openArtists()
        const grid = findChild(library, "libraryArtistGrid")
        provider.artistPortraitPriorityCalls = []

        grid.jumpToGlobalIndex(25)

        tryVerify(() => provider.artistPortraitPriorityCalls.length > 0)
        const first = provider.artistPortraitPriorityCalls[0]
        verify(first.visible.indexOf("Artist 25") !== -1)
    }

    function test_artist_scroll_reprioritizes_the_new_viewport() {
        var rows = []
        for (var index = 0; index < 30; ++index) {
            rows.push({name: "Artist " + String(index).padStart(2, "0"),
                       path: "Artists/" + index, albums: 1, songs: 1})
        }
        provider.artistRows = rows
        openArtists()
        const grid = findChild(library, "libraryArtistGrid")
        provider.artistPortraitPriorityCalls = []

        grid.contentY = grid.originY + grid.height + 28

        tryVerify(() => provider.artistPortraitPriorityCalls.length > 0)
        const latest = provider.artistPortraitPriorityCalls[
            provider.artistPortraitPriorityCalls.length - 1]
        verify(latest.visible.indexOf("Artist 05") !== -1)
    }

    function test_artist_monolith_compact_recomposes_inside_the_shelf() {
        openArtists()
        testCase.width = 680
        wait(0)
        const stage = findChild(library, "libraryArtistMonolithStage")
        const hero = findChild(library, "libraryArtistHero")
        const support = findChild(library, "libraryArtistSupport_0")
        const grid = findChild(library, "libraryArtistGrid")
        const shelfLabel = findChild(library, "libraryShelfLabel")
        compare(grid.cols, 2)
        compare(stage.height, 250)
        verify(shelfLabel.visible)
        const heroInStage = hero.mapToItem(stage, 0, 0)
        const supportInStage = support.mapToItem(stage, 0, 0)
        verify(heroInStage.x >= 0)
        verify(heroInStage.x + hero.width <= stage.width + 0.5)
        verify(supportInStage.x >= 0)
        verify(supportInStage.x + support.width <= stage.width + 0.5)
        verify(support.height <= stage.height)
        testCase.width = 1280
    }

    function test_artist_monolith_keyboard_opens_exact_featured_artist() {
        openArtists()
        const hero = findChild(library, "libraryArtistHero")
        hero.forceActiveFocus()
        verify(hero.activeFocus)
        keyClick(Qt.Key_Return)
        compare(artistSpy.count, 1)
        compare(artistSpy.signalArguments[0][0], "Alpha Artist")
        compare(artistSpy.signalArguments[0][1], "Artists/Alpha")
    }

    function test_artist_alphabet_rail_reaches_virtualized_remainder() {
        openArtists()
        library.jumpToLetter("Z")
        const grid = findChild(library, "libraryArtistGrid")
        compare(grid.currentIndex, 7)
    }

    function test_artist_varied_measure_repeats_beyond_the_entrance() {
        openArtists()
        const grid = findChild(library, "libraryArtistGrid")
        grid.jumpToGlobalIndex(5)
        wait(0)
        const secondMeasure = findChild(library,
                                        "libraryArtistVariedMeasure_1")
        const secondHero = findChild(library, "libraryArtistCard_5")
        const secondSupport = findChild(library, "libraryArtistCard_6")
        verify(secondMeasure !== null)
        verify(secondHero !== null && secondSupport !== null)
        verify(secondHero.width >= secondSupport.width * 1.7)
    }

    function test_artist_alphabet_rail_stays_above_the_player_boundary() {
        const rows = []
        for (let code = 65; code <= 90; ++code) {
            const letter = String.fromCharCode(code)
            rows.push({ name: letter + " Artist", path: "Artists/" + letter,
                        albums: 1, songs: 1, portrait: letter + "/01.flac" })
        }
        provider.artistRows = rows
        openArtists()
        const rail = findChild(library, "libraryArtistAlphaRail")
        const last = findChild(library, "libraryArtistAlpha_Z")
        const shelves = findChild(library, "libraryShelves")
        verify(rail !== null && last !== null && shelves !== null)
        const railInLibrary = rail.mapToItem(library, 0, 0)
        const lastInRail = last.mapToItem(rail, 0, 0)
        const lastInLibrary = last.mapToItem(library, 0, 0)
        const shelvesInLibrary = shelves.mapToItem(library, 0, 0)
        verify(lastInRail.y >= 0)
        verify(lastInRail.y + last.height <= rail.height + 0.5)
        verify(lastInLibrary.y + last.height
               <= shelvesInLibrary.y + shelves.height - 3.5)
        verify(lastInLibrary.y + last.height
               >= shelvesInLibrary.y + shelves.height - 4.5)
        verify(railInLibrary.y + rail.height
               <= library.height + 0.5)
    }

    function test_genre_monolith_establishes_metadata_mosaic_hierarchy() {
        openGenres()
        const stage = findChild(library, "libraryGenreMonolithStage")
        const hero = findChild(library, "libraryGenreHero")
        const firstCover = findChild(library, "libraryGenreHeroCover_0")
        const secondCover = findChild(library, "libraryGenreHeroCover_1")
        const support = findChild(library, "libraryGenreSupport_0")
        const grid = findChild(library, "libraryGenreGrid")
        verify(stage !== null && hero !== null && support !== null)
        verify(firstCover !== null && secondCover !== null && grid !== null)
        compare(library.genreLead.name, "Ambient")
        compare(library.genreSupports.length, 2)
        compare(library.genreRemainder.length, 4)
        verify(hero.width > support.width)
        fuzzyCompare(stage.height, grid.height, 0.5)
        verify(decodeURIComponent(firstCover.source.toString())
               .indexOf("A/one.flac") !== -1)
        verify(decodeURIComponent(secondCover.source.toString())
               .indexOf("A/two.flac") !== -1)
        tryCompare(grid, "contentY", grid.originY)
    }

    function test_genre_monolith_compact_recomposes_inside_the_shelf() {
        openGenres()
        testCase.width = 680
        wait(0)
        const stage = findChild(library, "libraryGenreMonolithStage")
        const hero = findChild(library, "libraryGenreHero")
        const support = findChild(library, "libraryGenreSupport_0")
        const grid = findChild(library, "libraryGenreGrid")
        compare(stage.height, 444)
        compare(grid.cols, 2)
        compare(hero.width, stage.width)
        verify(support.y >= hero.y + hero.height)
        verify(support.x >= 0)
        verify(support.x + support.width <= stage.width + 0.5)
        testCase.width = 1280
    }

    function test_genre_varied_measure_repeats_beyond_the_entrance() {
        openGenres()
        const grid = findChild(library, "libraryGenreGrid")
        grid.contentY = grid.height
        wait(0)
        const secondMeasure = findChild(library,
                                        "libraryGenreVariedMeasure_1")
        const secondHero = findChild(library, "libraryGenreCard_3")
        const secondSupport = findChild(library, "libraryGenreCard_4")
        verify(secondMeasure !== null)
        verify(secondHero !== null && secondSupport !== null)
        verify(secondHero.width > secondSupport.width)
    }

    function test_genre_mosaic_opens_exact_art_led_detail_and_returns() {
        openGenres()
        const hero = findChild(library, "libraryGenreHero")
        verify(hero !== null)
        mouseClick(hero, hero.width / 2, hero.height / 2)
        compare(library.selectedGenre, "Ambient")
        compare(library.selectedGenreFiles,
                ["A/one.flac", "A/two.flac"])

        const detail = findChild(library, "libraryGenreDetailGrid")
        const index = findChild(library, "libraryRoomIndex")
        const header = findChild(library, "libraryShelfHeader")
        const firstTrack = findChild(library, "libraryGenreTrack_0")
        const firstAlbum = findChild(library, "libraryGenreAlbum_0")
        verify(detail !== null && detail.visible)
        verify(firstTrack !== null && firstAlbum !== null)
        compare(index.visible, false)
        compare(header.visible, false)

        firstAlbum.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(albumSpy.count, 1)
        compare(albumSpy.signalArguments[0][0], "Alpha")
        compare(albumSpy.signalArguments[0][1], "Alpha")

        const retreat = findChild(library, "libraryAllGenres")
        retreat.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(library.selectedGenre, "")
        verify(!detail.visible)
        compare(index.visible, true)
        compare(header.visible, true)
    }

    function test_genre_detail_keyboard_and_compact_recomposition() {
        openGenres()
        const hero = findChild(library, "libraryGenreHero")
        hero.forceActiveFocus()
        verify(hero.activeFocus)
        keyClick(Qt.Key_Return)
        compare(library.selectedGenre, "Ambient")

        testCase.width = 680
        wait(0)
        const detail = findChild(library, "libraryGenreDetailGrid")
        const detailHeader = findChild(library, "libraryGenreDetailHeader")
        const mosaic = findChild(library, "librarySelectedGenreMosaic")
        const identity = findChild(library, "libraryGenreDetailIdentity")
        compare(detail.columns, 1)
        // The genre detail gained Play / Shuffle / Queue line actions
        // (ROADMAP 2.2, 2026-08-22) and its compact header grew to hold them.
        compare(detailHeader.height, 556)
        compare(mosaic.width, detailHeader.width)
        verify(identity.y >= mosaic.y + mosaic.height)
        verify(identity.x >= 0)
        verify(identity.x + identity.width <= detailHeader.width + 0.5)
        testCase.width = 1280
    }

    function test_genre_empty_state_is_explicit() {
        provider.genreRows = []
        openGenres()
        const emptyState = findChild(library, "libraryGenreEmptyState")
        verify(emptyState !== null)
        verify(emptyState.visible)
    }

    function test_song_selected_stage_reflows_without_losing_the_lead() {
        openSongs()
        const grid = findChild(library, "librarySongGrid")
        const first = findChild(library, "libraryStageSong_0")
        const second = findChild(library, "libraryStageSong_1")
        const art = findChild(library, "libraryStageSongArt_0")
        verify(grid !== null && first !== null && second !== null && art !== null)
        compare(grid.columns, 2)
        compare(first.lead, true)
        verify(first.height > second.height)
        verify(first.width > second.width)
        compare(art.width, first.width)

        testCase.width = 680
        wait(0)
        compare(grid.columns, 1)
        compare(first.height, 180)
        verify(first.x >= 0)
        verify(first.x + first.width <= grid.width + 0.5)
        verify(second.width < first.width)
        testCase.width = 1280
    }

    function test_song_selected_stage_continues_without_another_hero() {
        const rows = []
        for (let i = 0; i < 10; ++i) {
            rows.push({ file: "song-" + i + ".flac",
                        title: String.fromCharCode(65 + i) + " song",
                        artist: "Artist", album: "Album", duration: 180 })
        }
        provider.songRows = rows
        openSongs()
        const grid = findChild(library, "librarySongGrid")
        compare(grid.measureCount, 4)
        grid.jumpToGlobalIndex(5)
        wait(0)
        const continuation = findChild(library,
                                       "librarySongContinuationRow_0")
        const firstContinuation = findChild(library, "librarySleeveTrack_5")
        const secondContinuation = findChild(library, "librarySleeveTrack_6")
        verify(continuation !== null)
        verify(firstContinuation !== null && secondContinuation !== null)
        compare(firstContinuation.width, secondContinuation.width)
        compare(firstContinuation.trackData.file, "song-5.flac")
        compare(secondContinuation.trackData.file, "song-6.flac")
    }

    function test_folder_source_rooms_reflow_and_keep_exact_open_action() {
        library.folders = provider.folderRows
        library._loadedFolders = true
        library.openRoom("folders")
        wait(0)
        const grid = findChild(library, "libraryFolderSourceRooms")
        const first = findChild(library, "libraryFolderRoom_0")
        const second = findChild(library, "libraryFolderRoom_1")
        verify(grid !== null && first !== null && second !== null)
        compare(grid.columns, 2)
        compare(first.width, second.width)
        verify(first.width > 280)
        const cover = findChild(library, "libraryFolderCover_0")
        verify(cover !== null)
        verify(String(cover.source).indexOf("top-album.flac") !== -1)
        first.forceActiveFocus()
        verify(first.activeFocus)
        keyClick(Qt.Key_Return)
        compare(folderSpy.count, 1)

        testCase.width = 680
        wait(0)
        compare(grid.columns, 1)
        compare(grid.cellWidth, grid.width)
        compare(first.width, grid.width)
        compare(second.width, first.width)
        verify(first.width <= grid.width + 0.5)
        testCase.width = 1280
    }

    function test_folder_continuous_run_keeps_one_uniform_measure() {
        library.folders = provider.folderRows.concat([
            { name: "Classical", path: "Music/Classical",
              cover: "classical/top.flac", items: 42,
              modified: 1785628800 },
            { name: "Electronic", path: "Music/Electronic",
              cover: "electronic/top.flac", items: 84,
              modified: 1785628800 },
            { name: "Jazz", path: "Music/Jazz", cover: "jazz/top.flac",
              items: 21,
              modified: 1785628800 }
        ])
        library._loadedFolders = true
        library.openRoom("folders")
        wait(0)
        const grid = findChild(library, "libraryFolderSourceRooms")
        compare(grid.columns, 2)
        compare(grid.measureCount, 3)
        const first = findChild(library, "libraryFolderRoom_0")
        const sixth = findChild(library, "libraryFolderRoom_5")
        verify(first !== null && sixth !== null)
        compare(first.width, sixth.width)
    }

    function test_playlist_sequence_stage_leads_then_continues_uniformly() {
        provider.playlists = ["One", "Two", "Three", "Four", "Five", "Six"]
        library.openRoom("playlists")
        wait(0)
        const wall = findChild(library, "playlistWall")
        compare(wall.measureCount, 3)
        wall.positionViewAtIndex(1, ListView.Beginning)
        wait(0)
        const first = findChild(library, "playlistSequence_0")
        const second = findChild(library, "playlistSequence_1")
        const secondMeasure = findChild(library, "playlistContinuationRow_1")
        verify(first !== null && second !== null && secondMeasure !== null)
        verify(first.width > second.width)
    }

    function test_sleeve_stream_keyboard_plays_from_exact_row() {
        openSongs()
        const second = findChild(library, "libraryStageSong_1")
        verify(second !== null)
        second.forceActiveFocus()
        verify(second.activeFocus)
        keyClick(Qt.Key_Return)
        compare(provider.playFilesCalls.length, 1)
        compare(provider.playFilesCalls[0].index, 1)
        compare(provider.playFilesCalls[0].files.length, 4)
        compare(provider.playFilesCalls[0].files[1], "b.flac")
    }

    function test_song_alphabet_rail_is_sort_aware_and_actionable() {
        openSongs()
        const rail = findChild(library, "librarySongAlphaRail")
        const b = findChild(library, "librarySongAlpha_B")
        const context = findChild(library, "libraryStageSongContext_0")
        verify(rail !== null && rail.visible)
        verify(b !== null)
        verify(context !== null)
        compare(context.width, 44)
        compare(context.height, 44)
        library.jumpToSongLetter("B")
        const grid = findChild(library, "librarySongGrid")
        compare(grid.currentIndex, 1)

        library.sortSongs = "added"
        wait(0)
        compare(library.songAlphaLetters.length, 0)
        verify(!rail.visible)
        library.sortSongs = "title"
    }

    function test_song_alphabet_uses_the_artist_left_shelf_lane() {
        openArtists()
        const artistRail = findChild(library, "libraryArtistAlphaRail")
        const artistGrid = findChild(library, "libraryArtistGrid")
        const shelves = findChild(library, "libraryShelves")
        verify(artistRail !== null && artistGrid !== null && shelves !== null)
        const artistRailX = artistRail.mapToItem(shelves, 0, 0).x
        const artistGridX = artistGrid.mapToItem(shelves, 0, 0).x

        openSongs()
        const songRail = findChild(library, "librarySongAlphaRail")
        const songGrid = findChild(library, "librarySongGrid")
        verify(songRail !== null && songGrid !== null)
        compare(songRail.mapToItem(shelves, 0, 0).x, artistRailX)
        compare(songGrid.mapToItem(shelves, 0, 0).x, artistGridX)
        compare(songRail.width, artistRail.width)
    }

    function test_compact_full_alphabet_stays_above_the_player_boundary() {
        const rows = []
        for (let code = 65; code <= 90; ++code) {
            const letter = String.fromCharCode(code)
            rows.push({ file: letter + ".flac", title: letter + " song",
                        artist: "Artist " + letter, album: "Album " + letter,
                        duration: 180 })
        }
        provider.songRows = rows
        testCase.width = 680
        openSongs()
        const scroller = findChild(library, "libraryStageScroller")
        const rail = findChild(library, "librarySongAlphaRail")
        const grid = findChild(library, "librarySongGrid")
        const last = findChild(library, "librarySongAlpha_Z")
        verify(scroller !== null && rail !== null && grid !== null
               && last !== null)
        // The compact Open Room Index now scrolls away for every collection.
        // Judge the rail at the collection's player-safe resting position.
        scroller.contentY = scroller.contentHeight - scroller.height
        wait(0)
        const lastInRail = last.mapToItem(rail, 0, 0)
        const railInLibrary = rail.mapToItem(library, 0, 0)
        const gridInLibrary = grid.mapToItem(library, 0, 0)
        verify(railInLibrary.x < gridInLibrary.x)
        verify(lastInRail.y >= 0)
        verify(lastInRail.y + last.height <= rail.height + 0.5)
        verify(railInLibrary.y + rail.height
               <= library.height - Theme.playerHeight + 0.5)
        scroller.contentY = 0
        testCase.width = 1280
    }

    function test_low_height_keeps_current_index_and_scrolls_to_active_shelf() {
        testCase.width = 720
        testCase.height = 384
        wait(0)

        const scroller = findChild(library, "libraryStageScroller")
        const index = findChild(library, "libraryRoomIndex")
        const shelf = findChild(library, "libraryAlbumGrid")
        verify(scroller !== null && index !== null && shelf !== null)
        verify(library.compact)
        verify(library.lowHeight)
        verify(index.height >= 3 * 46)
        verify(index.height < 260)
        verify(scroller.contentHeight > scroller.height)

        scroller.contentY = scroller.contentHeight - scroller.height
        wait(0)
        const shelfInLibrary = shelf.mapToItem(library, 0, 0)
        verify(shelfInLibrary.y < library.height)
        verify(shelfInLibrary.y + shelf.height > 0)

        testCase.height = 820
        testCase.width = 1280
    }

    function test_compact_collections_can_scroll_the_index_away_for_the_full_wall() {
        testCase.width = 948
        testCase.height = 920
        const rooms = ["albums", "artists", "songs", "genres", "folders",
                       "playlists"]
        for (let i = 0; i < rooms.length; ++i) {
            library.showAllGenres()
            library.openPlaylist("")
            library.openRoom(rooms[i])
            wait(0)

            const scroller = findChild(library, "libraryStageScroller")
            const title = findChild(library, "libraryPageTitle")
            const shelves = findChild(library, "libraryShelves")
            verify(scroller !== null && title !== null && shelves !== null)
            verify(library.compact)
            verify(!library.lowHeight)
            verify(scroller.contentHeight > scroller.height)

            scroller.contentY = scroller.contentHeight - scroller.height
            wait(0)
            const titleInLibrary = title.mapToItem(library, 0, 0)
            const shelfInLibrary = shelves.mapToItem(library, 0, 0)
            verify(titleInLibrary.y + title.height < 0)
            verify(shelfInLibrary.y >= 0)
            verify(shelfInLibrary.y < 150)
            scroller.contentY = 0
        }

        testCase.height = 820
        testCase.width = 1280
    }
}
