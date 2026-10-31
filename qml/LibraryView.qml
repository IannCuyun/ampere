import QtQuick
import QtCore
import QtQuick.Controls.Basic
import "."

// Open Room Index — Iann's selected Library local order (design/SPEC.md ·
// Library; canonical direction:
// design/proposals/library-local-order-2026-08-15/index.html?direction=c).
// The six destinations form one page-local room index beside the still-ratified
// L.01 open shelves. Utility access, including Out of Rotation, belongs to S1
// Settings; the unoccupied lower index lane remains available for future areas.
Item {
    id: lib
    signal openAlbum(string path, string album)
    signal openArtistPage(string name, string path)
    signal openFolder(string path)
    signal openDisliked()

    property bool active: false
    // The desktop index + monolith needs a genuinely wide shelf. At common
    // half-screen widths, recompose the six rooms above the collection rather
    // than reducing the art field to a narrow database column.
    readonly property bool compact: width < 1080
    readonly property bool lowHeight: height < 600
    // Main's persistent player overlays the bottom of every retained page.
    // The shelf already leaves a responsive outer margin, so reserve only
    // the part of the player that still intersects the shelf.  Navigation
    // rails use this value to remain wholly actionable above the player.
    readonly property real shelfPlayerOverlap: Math.max(
        0, Theme.playerHeight - (compact ? 16 : height * 0.06))
    readonly property int dislikedCount: backend.dislikedFiles.length
    readonly property var dislikedPreviewRows: {
        var rows = []
        var files = Array.from(backend.dislikedFiles)
        for (var i = 0; i < Math.min(3, files.length); ++i)
            rows.push(backend.songInfo(files[i]))
        return rows
    }

    // ---- the six destinations (ratified directory contract) ----
    property string tab: "albums"
    readonly property string selectedPlaylist: playlistSurface.selected
    readonly property var selectedPlaylistFiles: playlistSurface.fileList
    readonly property bool playlistDetailOpen: tab === "playlists"
                                               && selectedPlaylist !== ""
    property string selectedGenre: ""
    property var selectedGenreDetail: ({})
    readonly property bool genreDetailOpen: tab === "genres"
                                            && selectedGenre !== ""
    readonly property bool libraryDetailOpen: playlistDetailOpen
                                              || genreDetailOpen
    // Every collection shares Albums' approved Open Wall architecture. A
    // selected playlist or genre detail deliberately leaves that architecture
    // and owns the complete, conventionally inset Library workspace.
    readonly property bool collectionOpenWall: !libraryDetailOpen
    readonly property var selectedGenreTracks:
        selectedGenreDetail.tracks || []
    readonly property var selectedGenreAlbums:
        selectedGenreDetail.albums || []
    readonly property var selectedGenreFiles: selectedGenreTracks.map(
        function(track) { return track.file })
    readonly property var tabRow: [
        { key: "albums", label: "Albums" },
        { key: "artists", label: "Artists" },
        { key: "songs", label: "Songs" },
        { key: "genres", label: "Genres" },
        { key: "folders", label: "Folders" },
        { key: "playlists", label: "Playlists" }
    ]

    // ---- per-destination remembered sorts (ratified sort contract) ----
    property string sortAlbums: "added"
    property string sortArtists: "name"
    property string sortSongs: "title"
    property string sortGenres: "name"
    property string sortFolders: "name"
    property string sortPlaylists: "name"
    property bool sortAlbumsDescending: true
    property bool sortArtistsDescending: false
    property bool sortSongsDescending: false
    property bool sortGenresDescending: false
    property bool sortFoldersDescending: false
    property bool sortPlaylistsDescending: false
    property string filterQuery: ""
    Settings {
        category: "libraryDirectory"
        property alias tab: lib.tab
        property alias sortAlbums: lib.sortAlbums
        property alias sortArtists: lib.sortArtists
        property alias sortSongs: lib.sortSongs
        property alias sortGenres: lib.sortGenres
        property alias sortFolders: lib.sortFolders
        property alias sortPlaylists: lib.sortPlaylists
        property alias sortAlbumsDescending: lib.sortAlbumsDescending
        property alias sortArtistsDescending: lib.sortArtistsDescending
        property alias sortSongsDescending: lib.sortSongsDescending
        property alias sortGenresDescending: lib.sortGenresDescending
        property alias sortFoldersDescending: lib.sortFoldersDescending
        property alias sortPlaylistsDescending: lib.sortPlaylistsDescending
    }
    readonly property var sortMenus: ({
        albums: [["added", "Recently added"], ["title", "Title"],
                 ["artist", "Artist"], ["year", "Year"]],
        artists: [["name", "A – Z"], ["albums", "Album count"],
                  ["songs", "Song count"]],
        songs: [["title", "Title"], ["artist", "Artist"],
                ["album", "Album"], ["added", "Recently added"]],
        genres: [["name", "Name"], ["albums", "Album count"],
                 ["artists", "Artist count"]],
        folders: [["name", "Name"], ["items", "Item count"],
                  ["modified", "Modified"]],
        playlists: [["name", "Name"]]
    })
    function currentSort() {
        return tab === "albums" ? sortAlbums
             : tab === "artists" ? sortArtists
             : tab === "songs" ? sortSongs
             : tab === "genres" ? sortGenres
             : tab === "folders" ? sortFolders
             : tab === "playlists" ? sortPlaylists : ""
    }
    function sortLabel() {
        var menu = sortMenus[tab] || []
        var key = currentSort()
        for (var i = 0; i < menu.length; i++)
            if (menu[i][0] === key) return menu[i][1]
        return ""
    }
    function pickSort(key) {
        if (tab === "albums") sortAlbums = key
        else if (tab === "artists") sortArtists = key
        else if (tab === "songs") sortSongs = key
        else if (tab === "genres") sortGenres = key
        else if (tab === "folders") sortFolders = key
        else if (tab === "playlists") sortPlaylists = key
    }
    function currentDescending() {
        return tab === "albums" ? sortAlbumsDescending
             : tab === "artists" ? sortArtistsDescending
             : tab === "songs" ? sortSongsDescending
             : tab === "genres" ? sortGenresDescending
             : tab === "folders" ? sortFoldersDescending
             : sortPlaylistsDescending
    }
    function toggleSortDirection() {
        if (tab === "albums") sortAlbumsDescending = !sortAlbumsDescending
        else if (tab === "artists") sortArtistsDescending = !sortArtistsDescending
        else if (tab === "songs") sortSongsDescending = !sortSongsDescending
        else if (tab === "genres") sortGenresDescending = !sortGenresDescending
        else if (tab === "folders") sortFoldersDescending = !sortFoldersDescending
        else sortPlaylistsDescending = !sortPlaylistsDescending
    }
    function directionName() {
        return currentDescending() ? "reverse" : "forward"
    }
    function tabLabel() {
        for (var i = 0; i < tabRow.length; ++i)
            if (tabRow[i].key === tab) return tabRow[i].label
        return "Library"
    }
    function tabCount(key) {
        var value = key === "albums" ? libStats.albums
                  : key === "artists" ? libStats.artists
                  : key === "songs" ? libStats.songs
                  : key === "genres" ? libStats.genres
                  : key === "folders" ? libStats.folders
                  : key === "playlists" ? backend.playlists.length : 0
        return Number(value || 0) > 0 ? fmtCount(value) : ""
    }
    function openRoom(key) {
        // Entering Playlists from another room begins at its wall. Once inside,
        // wall/detail state stays local and the already-active room is inert.
        if (key === "playlists" && tab !== "playlists")
            playlistSurface.showAll()
        selectedGenre = ""
        selectedGenreDetail = ({})
        tab = key
    }

    function openGenre(name) {
        name = String(name || "").trim()
        if (!name) {
            showAllGenres()
            return false
        }
        var detail = backend.libraryGenreDetail(name)
        if (!detail || !(detail.tracks || []).length)
            return false
        tab = "genres"
        selectedGenreDetail = detail
        selectedGenre = String(detail.name || name)
        return true
    }

    function showAllGenres() {
        selectedGenre = ""
        selectedGenreDetail = ({})
        tab = "genres"
    }

    function openPlaylist(name) {
        selectedGenre = ""
        selectedGenreDetail = ({})
        tab = "playlists"
        if (name)
            playlistSurface.openPlaylist(name)
        else
            playlistSurface.showAll()
    }

    // ---- data: verified in-memory generation, loaded lazily per tab ----
    property var libStats: ({})
    property var albums: []
    property var artists: []
    property var artistPortraitKeys: ({})
    property var songs: []
    property var genres: []
    property var folders: []
    property bool _loadedAlbums: false
    property bool _loadedArtists: false
    property bool _loadedSongs: false
    property bool _loadedGenres: false
    property bool _loadedFolders: false
    // Songs arrive asynchronously (perf): the previous list stays on screen
    // until the newest request's rows land; older responses are dropped.
    property int songsRequestSerial: 0

    function requestSongs() {
        songsRequestSerial += 1
        backend.requestLibrarySongs(songsRequestSerial)
    }
    function applySongs(serial, rows) {
        if (Number(serial) < songsRequestSerial)
            return
        songs = rows || []
    }

    function loadTab() {
        if (!active) return
        if (tab === "albums" && !_loadedAlbums) {
            albums = backend.libraryAlbums(); _loadedAlbums = true
        } else if (tab === "artists" && !_loadedArtists) {
            artists = backend.libraryArtists(); _loadedArtists = true
            var artistNames = []
            for (var index = 0; index < artists.length; ++index) {
                var artistName = String((artists[index] || {}).name || "").trim()
                if (artistName)
                    artistNames.push(artistName)
            }
            if (typeof backend.primeArtistPortraits === "function")
                backend.primeArtistPortraits(artistNames)
        } else if (tab === "songs" && !_loadedSongs) {
            requestSongs(); _loadedSongs = true
        } else if (tab === "genres" && !_loadedGenres) {
            genres = backend.libraryGenres(); _loadedGenres = true
        } else if (tab === "folders" && !_loadedFolders) {
            folders = backend.libraryFolders(""); _loadedFolders = true
        }
        updateArtistPortraitPrefetchState()
        if (tab === "artists")
            Qt.callLater(artistVariedWall.reportPortraitPriority)
    }
    function invalidate() {
        _loadedAlbums = _loadedArtists = _loadedSongs = false
        _loadedGenres = _loadedFolders = false
        libStats = backend.stats()
        backend.requestLibrarySummary()
        loadTab()
        if (genreDetailOpen)
            openGenre(selectedGenre)
    }
    // Selection must paint before a large QVariant model is materialized and
    // sorted. Deferring one event-loop turn keeps the tap acknowledgement in
    // the frame where it happened; directory contents follow immediately.
    function updateArtistPortraitPrefetchState() {
        if (typeof backend.setArtistPortraitPrefetchActive === "function")
            backend.setArtistPortraitPrefetchActive(
                active && tab === "artists")
    }
    onActiveChanged: {
        updateArtistPortraitPrefetchState()
        if (active) Qt.callLater(invalidate)
    }
    onTabChanged: {
        updateArtistPortraitPrefetchState()
        Qt.callLater(loadTab)
    }
    Component.onDestruction: {
        if (typeof backend.setArtistPortraitPrefetchActive === "function")
            backend.setArtistPortraitPrefetchActive(false)
    }
    Connections {
        target: backend
        function onDatabaseUpdated() { if (lib.active) lib.invalidate() }
        function onConnectedChanged() {
            if (backend.connected && lib.active) lib.invalidate()
        }
        function onLibraryStatsChanged() { lib.libStats = backend.stats() }
    }
    Connections {
        target: backend
        ignoreUnknownSignals: true
        function onLibrarySongsReady(serial, rows) {
            lib.applySongs(serial, rows)
        }
    }
    Connections {
        target: backend
        ignoreUnknownSignals: true
        function onArtistPortraitsReady(portraitKeys) {
            var portraits = lib.copiedMap(lib.artistPortraitKeys)
            for (var artistName in portraitKeys)
                portraits[artistName] = portraitKeys[artistName] || ""
            lib.artistPortraitKeys = portraits
        }
        function onArtistBioReady(artistName, info) {
            var portraits = lib.copiedMap(lib.artistPortraitKeys)
            portraits[artistName] = info && info.portrait
                                    ? info.portrait : ""
            lib.artistPortraitKeys = portraits
        }
    }

    function copiedMap(source) {
        var copy = {}
        for (var key in source)
            copy[key] = source[key]
        return copy
    }
    function artistPortraitSource(artistName) {
        var key = artistPortraitKeys[artistName] || ""
        return key ? "image://art/portrait-full:" + key : ""
    }
    // ---- sorted projections ----
    function by(field, dir) {
        return function(a, b) {
            var x = a[field], y = b[field]
            if (typeof x === "string") {
                x = x.toLowerCase(); y = (y || "").toLowerCase()
                return dir * (x < y ? -1 : x > y ? 1 : 0)
            }
            return dir * ((x || 0) - (y || 0))
        }
    }
    function containsQuery(row, fields) {
        var query = filterQuery.trim().toLowerCase()
        if (!query) return true
        for (var i = 0; i < fields.length; ++i) {
            var value = row && row[fields[i]] !== undefined ? row[fields[i]] : ""
            if (String(value).toLowerCase().indexOf(query) !== -1) return true
        }
        return false
    }
    function filtered(rows, fields) {
        if (!filterQuery.trim()) return rows.slice()
        return rows.filter(function(row) { return lib.containsQuery(row, fields) })
    }
    readonly property var sortedAlbums: {
        var rows = filtered(albums, ["album", "artist", "year"])
        var dir = sortAlbumsDescending ? -1 : 1
        if (sortAlbums === "title") rows.sort(by("album", dir))
        else if (sortAlbums === "artist") rows.sort(by("artist", dir))
        else if (sortAlbums === "year") rows.sort(by("year", dir))
        else rows.sort(by("added", dir))
        return rows
    }
    readonly property var albumLead: sortedAlbums.length > 0
                                     ? sortedAlbums[0] : ({})
    readonly property var albumSupports: sortedAlbums.slice(1, 5)
    readonly property var albumRemainder: sortedAlbums.slice(5)
    readonly property var sortedArtists: {
        var rows = filtered(artists, ["name"])
        var dir = sortArtistsDescending ? -1 : 1
        if (sortArtists === "albums") rows.sort(by("albums", dir))
        else if (sortArtists === "songs") rows.sort(by("songs", dir))
        else rows.sort(by("name", dir))
        return rows
    }
    readonly property var artistLead: sortedArtists.length > 0
                                       ? sortedArtists[0] : ({})
    readonly property var artistSupports: sortedArtists.slice(1, 5)
    readonly property var artistRemainder: sortedArtists.slice(5)
    readonly property var sortedSongs: {
        var rows = filtered(songs, ["title", "artist", "album"])
        var dir = sortSongsDescending ? -1 : 1
        if (sortSongs === "artist") rows.sort(by("artist", dir))
        else if (sortSongs === "album") rows.sort(by("album", dir))
        else if (sortSongs === "added") rows.sort(by("added", dir))
        else rows.sort(by("title", dir))
        return rows
    }
    readonly property var songFiles: sortedSongs.map(function(s) { return s.file })
    readonly property var sortedGenres: {
        var rows = filtered(genres, ["name"])
        var dir = sortGenresDescending ? -1 : 1
        if (sortGenres === "albums") rows.sort(by("albums", dir))
        else if (sortGenres === "artists") rows.sort(by("artists", dir))
        else rows.sort(by("name", dir))
        return rows
    }
    readonly property var genreLead: sortedGenres.length > 0
                                      ? sortedGenres[0] : ({})
    readonly property var genreSupports: sortedGenres.slice(1, 3)
    readonly property var genreRemainder: sortedGenres.slice(3)
    readonly property var sortedFolders: {
        var rows = filtered(folders, ["name", "path"])
        var dir = sortFoldersDescending ? -1 : 1
        if (sortFolders === "items") rows.sort(by("items", dir))
        else if (sortFolders === "modified") rows.sort(by("modified", dir))
        else rows.sort(by("name", dir))
        return rows
    }
    readonly property var sortedPlaylists: {
        var query = filterQuery.trim().toLowerCase()
        var rows = backend.playlists.filter(function(name) {
            return !query || String(name).toLowerCase().indexOf(query) !== -1
        })
        rows.sort(function(a, b) {
            var x = String(a).toLowerCase(), y = String(b).toLowerCase()
            var result = x < y ? -1 : x > y ? 1 : 0
            return sortPlaylistsDescending ? -result : result
        })
        return rows
    }
    // Every room can be played as it is currently filtered and sorted (Iann,
    // 2026-08-22). The files are taken from the VISIBLE projection, so a
    // search or a sort is honoured rather than quietly ignored.
    function visibleFiles() {
        var i, j
        if (tab === "songs") return songFiles.slice()
        if (tab === "albums") {
            var files = []
            for (i = 0; i < sortedAlbums.length; ++i) {
                var tracks = sortedAlbums[i].tracks || []
                for (j = 0; j < tracks.length; ++j)
                    if (tracks[j].file) files.push(tracks[j].file)
            }
            return files
        }
        // One request per ROOM, never one per row: asking row by row walked
        // the whole library for each of 1,346 artists and froze the app
        // (2026-08-22).
        var keys = []
        if (tab === "artists") {
            for (i = 0; i < sortedArtists.length; ++i)
                keys.push(sortedArtists[i].name || "")
            return backend.libraryRoomFiles("artists", keys)
        }
        if (tab === "genres") {
            for (i = 0; i < sortedGenres.length; ++i)
                keys.push(sortedGenres[i].name || "")
            return backend.libraryRoomFiles("genres", keys)
        }
        if (tab === "folders") {
            for (i = 0; i < sortedFolders.length; ++i)
                keys.push(sortedFolders[i].path || "")
            return backend.libraryRoomFiles("folders", keys)
        }
        return []
    }

    readonly property bool roomIsPlayable:
        tab !== "playlists" && currentResultCount() > 0

    function currentResultCount() {
        return tab === "albums" ? sortedAlbums.length
             : tab === "artists" ? sortedArtists.length
             : tab === "songs" ? sortedSongs.length
             : tab === "genres" ? sortedGenres.length
             : tab === "folders" ? sortedFolders.length
             : sortedPlaylists.length
    }
    readonly property var alphaLetters: {
        var seen = {}, letters = []
        for (var i = 0; i < sortedArtists.length; i++) {
            var c = Theme.alphaBucket(sortedArtists[i].name)
            if (!seen[c]) { seen[c] = true; letters.push(c) }
        }
        return letters
    }
    function jumpToLetter(letter) {
        for (var i = 0; i < sortedArtists.length; i++) {
            var c = Theme.alphaBucket(sortedArtists[i].name)
            if (c === letter) {
                artistVariedWall.jumpToGlobalIndex(i)
                return
            }
        }
    }
    function songAlphaValue(row) {
        if (sortSongs === "artist") return row.artist || ""
        if (sortSongs === "album") return row.album || ""
        if (sortSongs === "title") return row.title || ""
        return ""
    }
    readonly property var songAlphaLetters: {
        if (sortSongs === "added") return []
        var seen = {}, letters = []
        for (var i = 0; i < sortedSongs.length; ++i) {
            var c = Theme.alphaBucket(songAlphaValue(sortedSongs[i]))
            if (!seen[c]) { seen[c] = true; letters.push(c) }
        }
        return letters
    }
    function jumpToSongLetter(letter) {
        for (var i = 0; i < sortedSongs.length; ++i) {
            var c = Theme.alphaBucket(songAlphaValue(sortedSongs[i]))
            if (c === letter) {
                songVariedWall.jumpToGlobalIndex(i)
                return
            }
        }
    }
    function fmtCount(n) { return Number(n || 0).toLocaleString(Qt.locale(), "f", 0) }
    function counted(n, word) { return n + " " + word + (n === 1 ? "" : "s") }

    component FolderRoomCard: Item {
        id: folderCard
        property var folder: ({})
        property int ordinal: 0
        property bool compactCard: false
        signal opened()

        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: folder.name || "Music folder"
        Accessible.description: "Open folder " + (folder.path || folder.name || "")
        Accessible.onPressAction: folderCard.opened()
        Keys.onReturnPressed: folderCard.opened()
        Keys.onEnterPressed: folderCard.opened()
        Keys.onSpacePressed: folderCard.opened()

        Rectangle {
            anchors.fill: parent
            color: folderTap.pressed
                ? Qt.alpha(Theme.primary, 0.11)
                : folderHover.hovered
                  ? Qt.alpha(Theme.washInk, 0.075)
                  : Qt.alpha(Theme.bgLow, 0.46)
            border.width: folderCard.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: folderCard.activeFocus || folderHover.hovered ? 2 : 1
            color: folderCard.activeFocus || folderHover.hovered
                ? Theme.primary : Theme.washHair
        }

        MediaArtwork {
            id: folderCover
            objectName: "libraryFolderCover_" + folderCard.ordinal
            anchors.left: parent.left
            anchors.leftMargin: folderCard.compactCard ? 12 : 16
            anchors.verticalCenter: parent.verticalCenter
            width: folderCard.compactCard ? 84 : 104
            height: width
            kind: "album"
            source: folderCard.folder.cover
                    ? "image://art/" + encodeURIComponent(
                        folderCard.folder.cover) : ""
        }
        Icon {
            visible: !folderCard.folder.cover
            anchors.centerIn: folderCover
            name: "folder"
            size: folderCard.compactCard ? 34 : 42
            color: Theme.washMuted
        }
        Text {
            id: folderEyebrow
            anchors.left: folderCover.right
            anchors.leftMargin: folderCard.compactCard ? 14 : 18
            anchors.top: folderCover.top
            text: "SOURCE " + (folderCard.ordinal < 9 ? "0" : "")
                  + (folderCard.ordinal + 1)
            color: Theme.primary
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.4
            font.capitalization: Font.AllUppercase
        }
        Text {
            id: folderName
            anchors.left: folderEyebrow.left
            anchors.right: parent.right
            anchors.rightMargin: folderCard.compactCard ? 18 : 22
            anchors.top: folderEyebrow.bottom
            anchors.topMargin: folderCard.compactCard ? 6 : 9
            text: folderCard.folder.name || "Untitled source"
            elide: Text.ElideRight
            color: folderHover.hovered || folderCard.activeFocus
                ? Theme.washInk : Qt.alpha(Theme.washInk, 0.94)
            font.family: Theme.font
            font.pixelSize: folderCard.compactCard ? 19 : 24
            font.weight: Font.Light
        }
        Text {
            anchors.left: folderName.left
            anchors.right: parent.right
            anchors.rightMargin: folderCard.compactCard ? 18 : 22
            anchors.top: folderName.bottom
            anchors.topMargin: 4
            text: folderCard.folder.path || folderCard.folder.name || ""
            elide: Text.ElideMiddle
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.washSub
            font.weight: Font.Light
        }
        Row {
            anchors.left: folderName.left
            anchors.bottom: folderCover.bottom
            spacing: 10
            Text {
                text: lib.counted(folderCard.folder.items || 0, "item")
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.5
                font.capitalization: Font.AllUppercase
            }
            Rectangle {
                visible: folderCard.folder.modified > 0
                anchors.verticalCenter: parent.verticalCenter
                width: 2
                height: 2
                radius: 1
                color: Theme.primary
            }
            Text {
                visible: folderCard.folder.modified > 0
                text: new Date(folderCard.folder.modified * 1000)
                    .toLocaleDateString(Qt.locale(), "MMM yyyy")
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.5
                font.capitalization: Font.AllUppercase
            }
        }

        HoverHandler {
            id: folderHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: folderTap
            onTapped: folderCard.opened()
        }
    }

    // ---- the stage (Open Room Index + L.01 shelves) ----
    Flickable {
        id: stage
        objectName: "libraryStageScroller"
        anchors.fill: parent
        anchors.leftMargin: lib.compact ? 66 : Math.max(78, lib.width * 0.066)
        anchors.rightMargin: lib.compact ? 24
                            : lib.collectionOpenWall ? 24 : lib.width * 0.08
        anchors.topMargin: lib.compact ? 66
                           : lib.collectionOpenWall ? 70 : lib.height * 0.11
        anchors.bottomMargin: lib.compact ? 16
                              : lib.collectionOpenWall ? 0 : lib.height * 0.06
        contentWidth: width
        // Preserve Open Room Index exactly. At the 720x480 floor the page
        // receives only 384px above Pocket Horizon, so its existing compact
        // composition needs a taller scroll canvas instead of a new layout.
        contentHeight: lib.compact && lib.collectionOpenWall
                       ? height + roomIndex.height + (lib.lowHeight ? 160 : 300)
                       : lib.lowHeight && !lib.libraryDetailOpen ? 760 : height
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Text {
            id: pageTitle
            objectName: "libraryPageTitle"
            visible: !lib.libraryDetailOpen
            anchors.left: parent.left
            width: !lib.compact && lib.collectionOpenWall
                   ? Math.min(320, parent.width * 0.19) : parent.width
            text: "Your Library"
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: lib.compact ? 38 : 54
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: 30
            font.weight: Font.Light
            font.letterSpacing: -((lib.compact ? 38 : 54) * 0.045)
            elide: Text.ElideRight
        }
        Text {
            id: pageHint
            visible: !lib.libraryDetailOpen
            anchors.left: parent.left
            width: pageTitle.width
            anchors.top: pageTitle.bottom
            anchors.topMargin: 9
            text: lib.fmtCount(libStats.albums) + " albums · "
                  + lib.fmtCount(libStats.artists) + " artists · "
                  + lib.fmtCount(libStats.songs) + " songs"
            color: Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: !lib.compact && lib.collectionOpenWall ? 2.1 : 2.8
            font.capitalization: Font.AllUppercase
            elide: Text.ElideRight
        }

        Rectangle {
            id: pageRule
            visible: !lib.libraryDetailOpen
            anchors.top: pageHint.bottom
            anchors.topMargin: 24
            width: pageTitle.width
            height: 1
            color: Theme.washHair
        }

        // C keeps all Library-local structure in one room: the six stable
        // destinations at left (2x3 on compact), an extensible lower lane, and
        // the active open shelf beside or beneath them.
        Item {
            id: workspace
            objectName: "libraryWorkspace"
            anchors.top: lib.libraryDetailOpen ? parent.top : pageRule.bottom
            anchors.topMargin: lib.libraryDetailOpen ? 0 : 24
            anchors.bottom: parent.bottom
            width: parent.width

            Item {
                id: roomIndex
                objectName: "libraryRoomIndex"
                visible: !lib.libraryDetailOpen
                anchors.left: parent.left
                anchors.top: parent.top
                width: lib.compact ? parent.width
                                   : lib.collectionOpenWall
                                     ? Math.min(320, parent.width * 0.19)
                                     : Math.min(370, parent.width * 0.25)
                height: lib.compact ? roomGrid.y + roomGrid.height + 12 : parent.height
                readonly property real roomGridHeight: lib.compact
                    ? (3 * 46 + 2 * 2) : (lib.tabRow.length * 48)

                Text {
                    id: roomIndexLabel
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: "CHOOSE A LIBRARY ROOM"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.8
                    font.capitalization: Font.AllUppercase
                }

                Grid {
                    id: roomGrid
                    objectName: "libraryRoomGrid"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: roomIndexLabel.bottom
                    anchors.topMargin: lib.compact ? 12 : 14
                    columns: lib.compact ? 2 : 1
                    columnSpacing: lib.compact ? 24 : 0
                    rowSpacing: lib.compact ? 2 : 0
                    // Grid.childrenRect briefly reported only two rows while
                    // Repeater delegates settled, letting the extension lane
                    // overlap Folders / Playlists at compact width. The room
                    // count is a ratified invariant, so size from that contract.
                    height: roomIndex.roomGridHeight

                    function focusRelative(index, delta) {
                        var next = (index + delta + roomRepeater.count)
                                   % roomRepeater.count
                        var item = roomRepeater.itemAt(next)
                        if (item) item.forceActiveFocus()
                    }

                    Repeater {
                        id: roomRepeater
                        model: lib.tabRow
                        delegate: Item {
                            id: roomChoice
                            objectName: "libraryRoomChoice_" + modelData.key
                            required property var modelData
                            required property int index
                            readonly property bool on: lib.tab === modelData.key
                            width: lib.compact
                                   ? Math.floor((roomGrid.width - roomGrid.columnSpacing) / 2)
                                   : roomGrid.width
                            height: lib.compact ? 46 : 48
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.label
                            Accessible.description: "Open the " + modelData.label + " Library room"
                            Accessible.onPressAction: lib.openRoom(modelData.key)
                            Keys.onReturnPressed: lib.openRoom(modelData.key)
                            Keys.onSpacePressed: lib.openRoom(modelData.key)
                            Keys.onUpPressed: roomGrid.focusRelative(index, lib.compact ? -2 : -1)
                            Keys.onDownPressed: roomGrid.focusRelative(index, lib.compact ? 2 : 1)
                            Keys.onLeftPressed: if (lib.compact) roomGrid.focusRelative(index, -1)
                            Keys.onRightPressed: if (lib.compact) roomGrid.focusRelative(index, 1)

                            Text {
                                id: roomName
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                text: roomChoice.modelData.label
                                color: roomChoice.on ? Theme.washInk
                                     : roomHover.hovered || roomChoice.activeFocus
                                     ? Theme.washMuted : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: lib.compact ? 17 : 24
                                font.weight: Font.Medium
                                font.letterSpacing: lib.compact ? 3.1 : 4.2
                                font.capitalization: Font.AllUppercase
                            }
                            Text {
                                anchors.left: roomName.right
                                anchors.leftMargin: 10
                                anchors.baseline: roomName.baseline
                                text: lib.tabCount(roomChoice.modelData.key)
                                visible: text !== ""
                                color: roomChoice.on ? Theme.primary : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 1.2
                            }
                            Rectangle {
                                anchors.fill: parent
                                color: roomTap.pressed
                                       ? Qt.alpha(Theme.washInk, 0.08) : "transparent"
                                border.width: roomChoice.activeFocus ? 1 : 0
                                border.color: Theme.focusRing
                            }
                            HoverHandler {
                                id: roomHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                id: roomTap
                                onTapped: lib.openRoom(roomChoice.modelData.key)
                            }
                        }
                    }
                }

                // Future Library-local areas may use this lane only after a
                // design verdict; blank air is the correct current state.
                Item {
                    id: extensionLane
                    objectName: "libraryExtensionLane"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    y: roomGrid.y + roomIndex.roomGridHeight
                       + (lib.compact ? 10 : 18)
                    height: parent.height - y

                    Item {
                        id: dislikedAction
                        objectName: "libraryDislikedAction"
                        visible: false
                        anchors.left: parent.left
                        anchors.right: parent.right
                        height: lib.compact ? 74 : 84
                        y: lib.compact ? 0 : Math.max(0, parent.height - height)
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Open disliked tracks, " + lib.dislikedCount
                        Accessible.description: "Open the Library contact sheet for tracks out of rotation"
                        Accessible.onPressAction: dislikedAction.trigger()

                        function trigger() { lib.openDisliked() }

                        Rectangle {
                            anchors.fill: parent
                            color: dislikedTap.pressed
                                   ? Qt.alpha(Theme.washInk, 0.12)
                                   : dislikedHover.hovered
                                   ? Qt.alpha(Theme.washInk, 0.07) : "transparent"
                            border.width: dislikedAction.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 1
                            color: Theme.washHair
                        }
                        Item {
                            id: previewStack
                            anchors.left: parent.left
                            anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: lib.compact ? 112 : 100
                            height: lib.compact ? 54 : 52

                            Repeater {
                                model: lib.dislikedPreviewRows
                                delegate: MediaArtwork {
                                    required property var modelData
                                    required property int index
                                    x: index * (lib.compact ? 20 : 18)
                                    width: parent.height
                                    height: parent.height
                                    kind: "album"
                                    source: "image://art/" + encodeURIComponent(modelData.file || "")
                                    opacity: index === 0 ? 0.52 : index === 1 ? 0.72 : 1
                                    z: index
                                }
                            }
                            Icon {
                                visible: lib.dislikedPreviewRows.length === 0
                                anchors.centerIn: parent
                                name: "heart-crack"
                                size: 18
                                color: Theme.washFaint
                            }
                        }
                        Column {
                            id: dislikedCopy
                            anchors.left: previewStack.right
                            anchors.leftMargin: 12
                            anchors.right: parent.right
                            anchors.rightMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 5
                            Text {
                                text: "OUT OF ROTATION"
                                color: Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 2.4
                                font.capitalization: Font.AllUppercase
                            }
                            Row {
                                spacing: 8
                                Icon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    name: "heart-crack"
                                    size: 14
                                    color: dislikedAction.activeFocus || dislikedHover.hovered
                                           ? Theme.washInk : Theme.washMuted
                                }
                                Text {
                                    id: dislikedActionLabel
                                    objectName: "libraryDislikedLabel"
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "DISLIKED · " + lib.fmtCount(lib.dislikedCount)
                                    color: dislikedAction.activeFocus || dislikedHover.hovered
                                           ? Theme.washInk : Theme.washMuted
                                    font.family: Theme.displayFont
                                    font.pixelSize: 11
                                    font.letterSpacing: 2.0
                                    font.capitalization: Font.AllUppercase
                                }
                                Icon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    name: "chevron-right"
                                    size: 11
                                    color: Theme.primary
                                }
                            }
                            Text {
                                id: dislikedReviewCopy
                                objectName: "libraryDislikedReviewCopy"
                                visible: !lib.compact
                                width: parent.width
                                text: "Review and restore what left rotation"
                                color: Theme.washMuted
                                font.family: Theme.font
                                font.pixelSize: Theme.washSub
                                elide: Text.ElideRight
                            }
                        }
                        HoverHandler {
                            id: dislikedHover
                            cursorShape: Qt.PointingHandCursor
                        }
                        TapHandler {
                            id: dislikedTap
                            onTapped: dislikedAction.trigger()
                        }
                        Keys.onReturnPressed: dislikedAction.trigger()
                        Keys.onSpacePressed: dislikedAction.trigger()
                    }
                }

                Rectangle {
                    visible: !lib.compact
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.right: parent.right
                    width: 1
                    color: Theme.washHair
                }
            }

            Item {
                id: shelfHeader
                objectName: "libraryShelfHeader"
                visible: !lib.libraryDetailOpen
                z: 8
                x: lib.compact ? 0
                   : lib.collectionOpenWall ? 0 : roomIndex.width + 42
                y: lib.compact ? roomIndex.height + 24
                   : lib.collectionOpenWall
                     ? parent.height - height - 8 : 0
                width: lib.compact ? parent.width
                       : lib.collectionOpenWall
                         ? Math.max(0, roomIndex.width - 18)
                         : Math.max(0, parent.width - x)
                height: (lib.compact ? 72 : 30)
                        + (lib.roomIsPlayable ? 52 : 0)

                Text {
                    id: shelfLabel
                    objectName: "libraryShelfLabel"
                    visible: lib.compact
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: lib.tabLabel() + " · open shelf"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.4
                    font.capitalization: Font.AllUppercase
                }

                // Play the room as it stands. The actions sit beside the
                // filter and sort they obey, so what plays is exactly what is
                // on screen (Iann, 2026-08-22).
                Row {
                    id: roomActions
                    objectName: "libraryRoomActions"
                    visible: lib.roomIsPlayable
                    anchors.left: parent.left
                    anchors.top: utilityRow.bottom
                    anchors.topMargin: lib.compact ? 16 : 12
                    spacing: lib.compact ? 20 : 26
                    WashLine {
                        label: "Play →"
                        primaryAction: true
                        onActivated: {
                            var files = lib.visibleFiles()
                            if (files.length) backend.playFiles(files, 0)
                        }
                    }
                    WashLine {
                        label: "Shuffle"
                        onActivated: {
                            var files = lib.visibleFiles()
                            if (files.length) backend.playFilesShuffled(files)
                        }
                    }
                    WashLine {
                        label: "Queue"
                        onActivated: {
                            var files = lib.visibleFiles()
                            if (files.length) backend.queueFiles(files)
                        }
                    }
                }

                Item {
                    id: utilityRow
                    anchors.left: lib.compact ? parent.left : undefined
                    anchors.right: parent.right
                    anchors.top: lib.compact ? shelfLabel.bottom : parent.top
                    anchors.topMargin: lib.compact ? 14 : 0
                    width: lib.compact ? parent.width : Math.min(430, parent.width * 0.58)
                    height: 24

                    Item {
                        id: filterLine
                        anchors.left: parent.left
                        anchors.right: sortWhisper.left
                        anchors.rightMargin: 24
                        height: parent.height

                        TextField {
                            id: filterInput
                            anchors.fill: parent
                            anchors.bottomMargin: 1
                            leftPadding: 0
                            rightPadding: 0
                            topPadding: 0
                            bottomPadding: 2
                            background: null
                            color: Theme.washInk
                            placeholderText: "SEARCH " + lib.tabLabel().toUpperCase()
                            placeholderTextColor: Theme.washFaint
                            selectionColor: Qt.alpha(Theme.primary, 0.28)
                            selectedTextColor: Theme.washInk
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 1.8
                            selectByMouse: true
                            inputMethodHints: Qt.ImhNoPredictiveText
                            Accessible.name: "Filter " + lib.tabLabel()
                            onTextChanged: lib.filterQuery = text
                            Keys.onEscapePressed: {
                                text = ""
                                focus = false
                            }
                        }
                    }

                    Item {
                        id: sortWhisper
                        visible: lib.sortLabel() !== ""
                        anchors.right: sortDirection.left
                        anchors.rightMargin: 12
                        anchors.top: parent.top
                        width: sortRow.width + 6
                        height: 24
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Sort by " + lib.sortLabel()
                        Accessible.onPressAction: sortWhisper.openSortMenu()
                        Keys.onReturnPressed: openSortMenu()
                        Keys.onSpacePressed: openSortMenu()

                        function openSortMenu() {
                            sortMenu.popupAt(sortWhisper,
                                             sortWhisper.width - sortMenu.width,
                                             sortWhisper.height + 8)
                        }

                        Row {
                            id: sortRow
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 7
                            Text {
                                text: lib.sortLabel()
                                color: sortHover.hovered ? Theme.washInk : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 2.2
                                font.capitalization: Font.AllUppercase
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Icon {
                                name: "chevron-down"
                                size: 10
                                color: sortHover.hovered ? Theme.washInk : Theme.washFaint
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -2
                            color: "transparent"
                            border.width: sortWhisper.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        HoverHandler { id: sortHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: sortWhisper.openSortMenu() }
                        ArchiveMenu {
                            id: sortMenu
                            selectedId: lib.currentSort()
                            options: (lib.sortMenus[lib.tab] || []).map(function(o) {
                                return { id: o[0], label: o[1] }
                            })
                            onPicked: id => lib.pickSort(id)
                        }
                    }

                    Item {
                        id: sortDirection
                        anchors.right: parent.right
                        anchors.top: parent.top
                        width: 24
                        height: 24
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Sort " + lib.directionName()
                        Accessible.description: "Reverse the current sort order"
                        Accessible.onPressAction: lib.toggleSortDirection()
                        Keys.onReturnPressed: lib.toggleSortDirection()
                        Keys.onSpacePressed: lib.toggleSortDirection()
                        Icon {
                            anchors.centerIn: parent
                            name: "arrow-up"
                            size: 13
                            rotation: lib.currentDescending() ? 180 : 0
                            color: directionHover.hovered || sortDirection.activeFocus
                                   ? Theme.washInk : Theme.washFaint
                            Behavior on rotation {
                                NumberAnimation { duration: Theme.motionFast }
                            }
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: sortDirection.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        HoverHandler {
                            id: directionHover
                            cursorShape: Qt.PointingHandCursor
                        }
                        TapHandler { onTapped: lib.toggleSortDirection() }
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Theme.washHair
                }
            }

            // First-index state: the shelf column stays put (LOCKED composition)
            // but its empty grids hide behind one honest statement.
            ArchiveLoading {
                objectName: "libraryArchiveLoading"
                visible: !backend.libraryReady
                anchors.left: shelves.left
                anchors.top: shelves.top
                count: backend.libraryTotalSongs
            }

            Item {
                id: shelves
                objectName: "libraryShelves"
                visible: !lib.genreDetailOpen && backend.libraryReady
                x: lib.compact ? 0
                   : roomIndex.width + (lib.collectionOpenWall ? 18 : 42)
                y: !lib.compact && lib.collectionOpenWall
                   ? -workspace.y
                   : shelfHeader.y + shelfHeader.height
                     + (lib.compact ? 18 : 20)
                width: Math.max(0, workspace.width - x)
                height: Math.max(0, workspace.height - y)

            // ---- ALBUMS: B Open Wall (Iann-selected 2026-08-27) ----
            AlbumOpenWall {
                id: albumOpenWall
                objectName: "libraryAlbumOpenWall"
                visible: lib.tab === "albums"
                anchors.fill: parent
                albums: lib.sortedAlbums
                compact: lib.compact
                onOpenAlbum: (path, album) => lib.openAlbum(path, album)
            }

            // Retained inertly for one migration pass so the old object graph
            // cannot compete with Open Wall while its source is removed.
            GridView {
                id: albumGrid
                objectName: "libraryAlbumMonolithRetired"
                visible: false
                anchors.fill: parent
                clip: true
                model: []
                readonly property int cols: lib.compact ? 2
                                            : Math.max(3, Math.floor(width / 260))
                cellWidth: Math.floor(width / cols)
                cellHeight: cellWidth - 26 + 82
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                cacheBuffer: cellHeight * 2
                ScrollBar.vertical: ArchiveScrollBar {}

                // GridView's origin sits above zero when it owns a header. Keep
                // the selected Monolith stage—not the remainder grid—as the
                // entrance whenever this room or its projection changes.
                function revealMonolith() {
                    Qt.callLater(function() {
                        if (albumGrid.visible)
                            albumGrid.positionViewAtBeginning()
                    })
                }
                onVisibleChanged: {
                    if (visible)
                        revealMonolith()
                }
                onModelChanged: {
                    if (visible)
                        revealMonolith()
                }
                Component.onCompleted: revealMonolith()
                Connections {
                    target: lib
                    function onCompactChanged() {
                        if (albumGrid.visible)
                            albumGrid.revealMonolith()
                    }
                }

                header: Item {
                    id: albumMonolithHeader
                    objectName: "libraryAlbumMonolithStage"
                    width: albumGrid.width
                    height: visible ? (lib.compact ? 262
                                                   : Math.min(590,
                                                              Math.max(460,
                                                                       width * 0.52)))
                                    : 0
                    visible: false

                    Item {
                        id: albumHero
                        objectName: "libraryAlbumHero"
                        readonly property real artSize: Math.floor(Math.min(
                            lib.compact ? albumMonolithHeader.width * 0.54
                                        : albumMonolithHeader.width * 0.52,
                            albumMonolithHeader.height - (lib.compact ? 58 : 66)))
                        width: artSize
                        height: albumMonolithHeader.height - 24
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: (lib.albumLead.album || "Album")
                                         + " by "
                                         + (lib.albumLead.artist || "Unknown artist")
                        Accessible.description: "Open the featured album"
                        Accessible.onPressAction: lib.openAlbum(
                            lib.albumLead.path, lib.albumLead.album)
                        Keys.onReturnPressed: lib.openAlbum(
                            lib.albumLead.path, lib.albumLead.album)
                        Keys.onSpacePressed: lib.openAlbum(
                            lib.albumLead.path, lib.albumLead.album)

                        Item {
                            anchors.fill: parent
                            y: albumHeroHover.hovered ? -4 : 0
                            Behavior on y {
                                NumberAnimation { duration: Theme.motionFast }
                            }
                            MediaArtwork {
                                id: albumHeroArt
                                objectName: "libraryAlbumHeroArt"
                                width: albumHero.artSize
                                height: width
                                kind: "album"
                                source: ""
                            }
                            Text {
                                id: albumHeroTitle
                                anchors.top: albumHeroArt.bottom
                                anchors.topMargin: lib.compact ? 7 : 10
                                width: albumHeroArt.width
                                text: lib.albumLead.album || ""
                                elide: Text.ElideRight
                                color: Theme.washInk
                                font.family: Theme.font
                                font.pixelSize: lib.compact ? Theme.washBody
                                                            : Theme.fsTitle
                                font.weight: Font.Normal
                            }
                            Text {
                                anchors.top: albumHeroTitle.bottom
                                anchors.topMargin: 4
                                width: albumHeroArt.width
                                text: (lib.albumLead.artist || "")
                                      + (lib.albumLead.year
                                         ? " · " + lib.albumLead.year : "")
                                elide: Text.ElideRight
                                color: Theme.washMuted
                                font.family: Theme.font
                                font.pixelSize: Theme.washSub
                            }
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: albumHero.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        HoverHandler {
                            id: albumHeroHover
                            cursorShape: Qt.PointingHandCursor
                        }
                        TapHandler {
                            onTapped: lib.openAlbum(lib.albumLead.path,
                                                    lib.albumLead.album)
                        }
                    }

                    Item {
                        id: albumSupportStage
                        objectName: "libraryAlbumSupportStage"
                        anchors.left: albumHero.right
                        anchors.leftMargin: lib.compact ? 14 : 24
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: parent.height - 24
                        readonly property real gap: lib.compact ? 10 : 18
                        readonly property real cellWidth:
                            Math.floor((width - gap) / 2)
                        readonly property real cellHeight:
                            Math.floor((height - gap) / 2)

                        Repeater {
                            model: []
                            delegate: Item {
                                id: supportAlbum
                                required property var modelData
                                required property int index
                                objectName: "libraryAlbumSupport_" + index
                                readonly property real artSize: Math.floor(Math.min(
                                    albumSupportStage.cellWidth,
                                    albumSupportStage.cellHeight
                                    - (lib.compact ? 23 : 44)))
                                x: (index % 2)
                                   * (albumSupportStage.cellWidth
                                      + albumSupportStage.gap)
                                y: Math.floor(index / 2)
                                   * (albumSupportStage.cellHeight
                                      + albumSupportStage.gap)
                                width: albumSupportStage.cellWidth
                                height: albumSupportStage.cellHeight
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.album + " by "
                                                 + modelData.artist
                                Accessible.onPressAction: lib.openAlbum(
                                    modelData.path, modelData.album)
                                Keys.onReturnPressed: lib.openAlbum(
                                    modelData.path, modelData.album)
                                Keys.onSpacePressed: lib.openAlbum(
                                    modelData.path, modelData.album)

                                Item {
                                    anchors.fill: parent
                                    y: supportHover.hovered ? -3 : 0
                                    Behavior on y {
                                        NumberAnimation {
                                            duration: Theme.motionFast
                                        }
                                    }
                                    MediaArtwork {
                                        id: supportArt
                                        objectName: "libraryAlbumSupportArt_"
                                                    + supportAlbum.index
                                        width: supportAlbum.artSize
                                        height: width
                                        kind: "album"
                                        source: supportAlbum.modelData.cover
                                                ? "image://art/"
                                                  + encodeURIComponent(
                                                      supportAlbum.modelData.cover)
                                                : ""
                                    }
                                    Text {
                                        id: supportTitle
                                        anchors.top: supportArt.bottom
                                        anchors.topMargin: lib.compact ? 3 : 7
                                        width: supportArt.width
                                        text: supportAlbum.modelData.album
                                        elide: Text.ElideRight
                                        color: Theme.washInk
                                        font.family: Theme.font
                                        font.pixelSize: lib.compact
                                                        ? Theme.fsSmall
                                                        : Theme.washBody
                                        font.weight: Font.Normal
                                    }
                                    Text {
                                        visible: !lib.compact
                                        anchors.top: supportTitle.bottom
                                        anchors.topMargin: 3
                                        width: supportArt.width
                                        text: supportAlbum.modelData.artist
                                              + (supportAlbum.modelData.year
                                                 ? " · "
                                                   + supportAlbum.modelData.year
                                                 : "")
                                        elide: Text.ElideRight
                                        color: Theme.washMuted
                                        font.family: Theme.font
                                        font.pixelSize: Theme.washSub
                                    }
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    color: "transparent"
                                    border.width: supportAlbum.activeFocus ? 1 : 0
                                    border.color: Theme.focusRing
                                }
                                HoverHandler {
                                    id: supportHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    onTapped: lib.openAlbum(
                                        supportAlbum.modelData.path,
                                        supportAlbum.modelData.album)
                                }
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.washHair
                    }
                }

                delegate: Item {
                    id: albumCell
                    required property var modelData
                    required property int index
                    objectName: "libraryAlbumCell_" + index
                    width: albumGrid.cellWidth
                    height: albumGrid.cellHeight
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.album + " by " + modelData.artist
                    Accessible.onPressAction: lib.openAlbum(
                        modelData.path, modelData.album)
                    Keys.onReturnPressed: lib.openAlbum(modelData.path, modelData.album)
                    Keys.onSpacePressed: lib.openAlbum(modelData.path, modelData.album)
                    Item {
                        anchors.fill: parent
                        anchors.rightMargin: 26
                        y: albumHover.hovered ? -4 : 0
                        Behavior on y { NumberAnimation { duration: Theme.motionFast } }
                        MediaArtwork {
                            id: albumArt
                            width: parent.width
                            height: parent.width
                            kind: "album"
                            source: albumCell.modelData.cover
                                    ? "image://art/" + encodeURIComponent(albumCell.modelData.cover) : ""
                        }
                        Text {
                            id: albumTitle
                            anchors.top: albumArt.bottom
                            anchors.topMargin: 9
                            width: parent.width
                            text: albumCell.modelData.album
                            elide: Text.ElideRight
                            color: Theme.washInk
                            font.family: Theme.font
                            font.pixelSize: Theme.washBody
                            font.weight: Font.Normal
                        }
                        Text {
                            anchors.top: albumTitle.bottom
                            anchors.topMargin: 4
                            width: parent.width
                            text: albumCell.modelData.artist
                                  + (albumCell.modelData.year ? " · " + albumCell.modelData.year : "")
                            elide: Text.ElideRight
                            color: Theme.washMuted
                            font.family: Theme.font
                            font.pixelSize: Theme.washSub
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        anchors.rightMargin: 22
                        color: "transparent"
                        border.width: albumCell.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                    }
                    HoverHandler { id: albumHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        onTapped: lib.openAlbum(albumCell.modelData.path,
                                                albumCell.modelData.album)
                    }
                }
            }

            // ---- ARTISTS: B Monolith (Iann-selected 2026-08-15) ----
            Item {
                visible: lib.tab === "artists"
                anchors.fill: parent
                Item {
                    id: alphaRail
                    objectName: "libraryArtistAlphaRail"
                    readonly property real opticalOffsetY: 4
                    visible: !lib.compact
                    clip: true
                    anchors.top: parent.top
                    anchors.topMargin: opticalOffsetY
                    anchors.bottom: parent.bottom
                    // The shelf itself now ends on Pocket Horizon. Keep the
                    // alphabet optically inside that player-safe field.
                    anchors.bottomMargin: opticalOffsetY
                    width: 34
                    Repeater {
                        model: lib.tab === "artists" ? lib.alphaLetters : []
                        delegate: Item {
                            id: alphaItem
                            required property string modelData
                            required property int index
                            objectName: "libraryArtistAlpha_" + modelData
                            y: index * height
                            width: alphaRail.width
                            height: Math.max(
                                1, alphaRail.height
                                   / Math.max(1, lib.alphaLetters.length))
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Jump to artists beginning with " + modelData
                            Accessible.onPressAction: lib.jumpToLetter(modelData)
                            Text {
                                anchors.centerIn: parent
                                text: alphaItem.modelData
                                color: alphaItem.activeFocus || alphaHover.hovered
                                    ? Theme.washInk : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Math.max(8, Math.min(
                                    11, alphaItem.height - 2))
                                font.letterSpacing: 2
                            }
                            Rectangle {
                                anchors.fill: parent
                                color: "transparent"
                                border.width: alphaItem.activeFocus ? 1 : 0
                                border.color: Theme.focusRing
                            }
                            HoverHandler { id: alphaHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: lib.jumpToLetter(alphaItem.modelData) }
                            Keys.onReturnPressed: lib.jumpToLetter(modelData)
                            Keys.onSpacePressed: lib.jumpToLetter(modelData)
                        }
                    }
                }
                ArtistVariedWall {
                    id: artistVariedWall
                    objectName: "libraryArtistGrid"
                    anchors.fill: parent
                    anchors.leftMargin: lib.compact ? 0 : 76
                    artists: lib.sortedArtists
                    compact: lib.compact
                    portraitFor: function(name) {
                        return lib.artistPortraitSource(name)
                    }
                    onPortraitPriority: (visibleNames, nearbyNames) => {
                        if (lib.active && lib.tab === "artists"
                                && typeof backend.prioritizeArtistPortraits
                                   === "function") {
                            backend.prioritizeArtistPortraits(
                                visibleNames, nearbyNames)
                        }
                    }
                    onOpenArtist: (name, path) =>
                        lib.openArtistPage(name, path)
                }
                // Retained inertly for one correction migration pass. The
                // repeating Portrait Measure above is the sole live owner.
                GridView {
                    id: artistGrid
                    objectName: "libraryArtistMonolithRetired"
                    visible: false
                    anchors.fill: parent
                    anchors.leftMargin: lib.compact ? 0 : 76
                    clip: true
                    model: []
                    readonly property int cols: lib.compact ? 2
                                                : Math.max(3,
                                                    Math.floor(width / 260))
                    cellWidth: Math.floor(width / cols)
                    cellHeight: Math.floor(cellWidth * (lib.compact ? 0.72
                                                                   : 0.68))
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    cacheBuffer: cellHeight * 2
                    ScrollBar.vertical: ArchiveScrollBar {}

                    function revealMonolith() {
                        Qt.callLater(function() {
                            if (artistGrid.visible)
                                artistGrid.positionViewAtBeginning()
                        })
                    }
                    onVisibleChanged: {
                        if (visible)
                            revealMonolith()
                    }
                    onModelChanged: {
                        if (visible)
                            revealMonolith()
                    }
                    Component.onCompleted: revealMonolith()
                    Connections {
                        target: lib
                        function onCompactChanged() {
                            if (artistGrid.visible)
                                artistGrid.revealMonolith()
                        }
                    }

                    header: Item {
                        id: artistMonolithHeader
                        objectName: "libraryArtistMonolithStage"
                        width: artistGrid.width
                        height: visible ? (lib.compact ? 250
                                                       : artistGrid.height)
                                        : 0
                        visible: lib.sortedArtists.length > 0

                        ArtistPortraitCard {
                            id: artistHero
                            objectName: "libraryArtistHero"
                            width: Math.floor(parent.width
                                              * (lib.compact ? 0.53 : 0.52))
                            height: parent.height - 24
                            artist: lib.artistLead
                            portraitSource: lib.artistPortraitSource(
                                lib.artistLead.name || "")
                            dominant: true
                            compact: lib.compact
                            showCounts: true
                            onOpenRequested: (name, path) =>
                                lib.openArtistPage(name, path)
                        }

                        Item {
                            id: artistSupportStage
                            objectName: "libraryArtistSupportStage"
                            anchors.left: artistHero.right
                            anchors.leftMargin: lib.compact ? 10 : 18
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: parent.height - 24
                            readonly property real gap: lib.compact ? 8 : 14
                            readonly property real cellWidth:
                                Math.floor((width - gap) / 2)
                            readonly property real cellHeight:
                                Math.floor((height - gap) / 2)

                            Repeater {
                                model: lib.artistSupports
                                delegate: ArtistPortraitCard {
                                    id: supportArtist
                                    required property var modelData
                                    required property int index
                                    objectName: "libraryArtistSupport_" + index
                                    x: (index % 2)
                                       * (artistSupportStage.cellWidth
                                          + artistSupportStage.gap)
                                    y: Math.floor(index / 2)
                                       * (artistSupportStage.cellHeight
                                          + artistSupportStage.gap)
                                    width: artistSupportStage.cellWidth
                                    height: artistSupportStage.cellHeight
                                    artist: modelData
                                    portraitSource: lib.artistPortraitSource(
                                        modelData.name || "")
                                    compact: lib.compact
                                    showCounts: !lib.compact
                                    onOpenRequested: (name, path) =>
                                        lib.openArtistPage(name, path)
                                }
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.washHair
                        }
                    }

                    delegate: ArtistPortraitCard {
                        id: artistCard
                        required property var modelData
                        required property int index
                        objectName: "libraryArtistCard_" + index
                        width: artistGrid.cellWidth - (lib.compact ? 12 : 18)
                        height: artistGrid.cellHeight - (lib.compact ? 12 : 18)
                        artist: modelData
                        portraitSource: lib.artistPortraitSource(
                            modelData.name || "")
                        compact: lib.compact
                        showCounts: true
                        onOpenRequested: (name, path) =>
                            lib.openArtistPage(name, path)
                    }
                }
            }

            // ---- SONGS: A Sleeve Stream (Iann-selected 2026-08-16) ----
            Item {
                visible: lib.tab === "songs"
                anchors.fill: parent

                SongVariedWall {
                    id: songVariedWall
                    objectName: "librarySongGrid"
                    anchors.fill: parent
                    // The sort-aware alphabet is the same retrieval instrument
                    // Artists uses. Reserve its established left shelf lane
                    // instead of pinning Songs to the opposite edge.
                    anchors.leftMargin: songAlphaRail.visible
                                        ? (lib.compact ? 34 : 76) : 0
                    songs: lib.sortedSongs
                    fileList: lib.songFiles
                    compact: lib.compact
                }

                // Retained inertly for one correction migration pass. Sleeve
                // Score is the sole live collection owner.
                GridView {
                    id: songGrid
                    objectName: "librarySongGridRetired"
                    visible: false
                    anchors.fill: parent
                    anchors.leftMargin: songAlphaRail.visible
                                        ? (lib.compact ? 34 : 76) : 0
                    clip: true
                    model: []
                    readonly property int columns: lib.compact ? 1 : 2
                    cellWidth: Math.floor(width / columns)
                    cellHeight: lib.compact ? 126 : 158
                    boundsBehavior: Flickable.StopAtBounds
                    keyNavigationWraps: false
                    reuseItems: true
                    cacheBuffer: cellHeight * 2
                    ScrollBar.vertical: ArchiveScrollBar {}

                    delegate: SleeveTrackRow {
                        required property var modelData
                        required property int index
                        width: songGrid.cellWidth - (lib.compact ? 0 : 12)
                        height: songGrid.cellHeight - 10
                        compact: lib.compact
                        exhibition: true
                        trackData: modelData
                        fileList: lib.songFiles
                        rowIndex: index
                        onActiveFocusChanged: {
                            if (activeFocus) songGrid.currentIndex = index
                        }
                    }
                }

                Item {
                    id: songAlphaRail
                    objectName: "librarySongAlphaRail"
                    readonly property real opticalOffsetY: 4
                    visible: lib.songAlphaLetters.length > 0
                    clip: true
                    anchors.top: parent.top
                    anchors.topMargin: lib.compact ? 0 : opticalOffsetY
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: lib.compact
                                          ? lib.shelfPlayerOverlap
                                          : opticalOffsetY
                    anchors.left: parent.left
                    width: lib.compact ? 26 : 34

                    Column {
                        anchors.fill: parent
                        spacing: 1
                        Repeater {
                            model: lib.tab === "songs"
                                   ? lib.songAlphaLetters : []
                            delegate: Item {
                                id: songAlphaItem
                                required property string modelData
                                required property int index
                                objectName: "librarySongAlpha_" + modelData
                                width: songAlphaRail.width
                                height: Math.max(1, Math.floor(
                                    (songAlphaRail.height
                                     - Math.max(0,
                                         lib.songAlphaLetters.length - 1))
                                    / Math.max(1,
                                               lib.songAlphaLetters.length)))
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: "Jump to songs beginning with "
                                                 + modelData
                                Accessible.onPressAction:
                                    lib.jumpToSongLetter(modelData)
                                Keys.onReturnPressed:
                                    lib.jumpToSongLetter(modelData)
                                Keys.onSpacePressed:
                                    lib.jumpToSongLetter(modelData)

                                Text {
                                    anchors.centerIn: parent
                                    text: songAlphaItem.modelData
                                    color: songAlphaItem.activeFocus
                                           || songAlphaHover.hovered
                                           ? Theme.primary : Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: lib.compact
                                                    ? Math.max(7, Math.min(
                                                        9, songAlphaItem.height - 1))
                                                    : 10
                                    font.weight: Font.Medium
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    color: "transparent"
                                    border.width: songAlphaItem.activeFocus ? 1 : 0
                                    border.color: Theme.focusRing
                                }
                                HoverHandler {
                                    id: songAlphaHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    onTapped: lib.jumpToSongLetter(
                                                  songAlphaItem.modelData)
                                }
                            }
                        }
                    }
                }
            }

            // ---- GENRES: B Monolith (Iann-selected 2026-08-15) ----
            Item {
                visible: lib.tab === "genres" && !lib.genreDetailOpen
                anchors.fill: parent

                GenreVariedWall {
                    id: genreVariedWall
                    objectName: "libraryGenreGrid"
                    anchors.fill: parent
                    genres: lib.sortedGenres
                    compact: lib.compact
                    onOpenGenre: name => lib.openGenre(name)
                }

                // Retained inertly for one correction migration pass. Mosaic
                // Measure is the sole live collection owner.
                GridView {
                    id: genreGrid
                    objectName: "libraryGenreMonolithRetired"
                    visible: false
                    anchors.fill: parent
                    clip: true
                    model: []
                    readonly property int cols: 2
                    cellWidth: Math.floor(width / cols)
                    cellHeight: lib.compact ? 204 : 250
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    cacheBuffer: cellHeight * 2
                    ScrollBar.vertical: ArchiveScrollBar {}

                    function revealMonolith() {
                        Qt.callLater(function() {
                            if (genreGrid.visible)
                                genreGrid.positionViewAtBeginning()
                        })
                    }
                    onVisibleChanged: if (visible) revealMonolith()
                    onModelChanged: if (visible) revealMonolith()
                    Component.onCompleted: revealMonolith()
                    Connections {
                        target: lib
                        function onCompactChanged() {
                            if (genreGrid.visible)
                                genreGrid.revealMonolith()
                        }
                    }

                    header: Item {
                        id: genreMonolithHeader
                        objectName: "libraryGenreMonolithStage"
                        width: genreGrid.width
                        height: visible ? (lib.compact ? 444
                                                       : genreGrid.height)
                                        : 0
                        visible: lib.sortedGenres.length > 0

                        GenreMosaicCard {
                            id: genreHero
                            objectName: "libraryGenreHero"
                            width: lib.compact ? parent.width
                                               : Math.floor(parent.width * 0.59)
                            height: lib.compact ? 252 : parent.height - 24
                            genre: lib.genreLead
                            dominant: true
                            compact: lib.compact
                            onOpenRequested: name => lib.openGenre(name)
                        }

                        Item {
                            id: genreSupportStage
                            objectName: "libraryGenreSupportStage"
                            anchors.left: lib.compact ? parent.left
                                                      : genreHero.right
                            anchors.leftMargin: lib.compact ? 0 : 18
                            anchors.right: parent.right
                            anchors.top: lib.compact ? genreHero.bottom
                                                     : parent.top
                            anchors.topMargin: lib.compact ? 10 : 0
                            height: lib.compact ? 158 : parent.height - 24
                            readonly property real gap: lib.compact ? 10 : 14
                            readonly property real cellWidth: lib.compact
                                ? Math.floor((width - gap) / 2) : width
                            readonly property real cellHeight: lib.compact
                                ? height : Math.floor((height - gap) / 2)

                            Repeater {
                                model: lib.genreSupports
                                delegate: GenreMosaicCard {
                                    required property var modelData
                                    required property int index
                                    objectName: "libraryGenreSupport_" + index
                                    x: lib.compact
                                       ? index * (genreSupportStage.cellWidth
                                                  + genreSupportStage.gap) : 0
                                    y: lib.compact
                                       ? 0 : index * (genreSupportStage.cellHeight
                                                      + genreSupportStage.gap)
                                    width: genreSupportStage.cellWidth
                                    height: genreSupportStage.cellHeight
                                    genre: modelData
                                    compact: lib.compact
                                    onOpenRequested: name => lib.openGenre(name)
                                }
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.washHair
                        }
                    }

                    delegate: GenreMosaicCard {
                        required property var modelData
                        required property int index
                        objectName: "libraryGenreCard_" + index
                        width: genreGrid.cellWidth - (lib.compact ? 10 : 18)
                        height: genreGrid.cellHeight - (lib.compact ? 10 : 18)
                        genre: modelData
                        compact: lib.compact
                        onOpenRequested: name => lib.openGenre(name)
                    }
                }

                Column {
                    objectName: "libraryGenreEmptyState"
                    visible: lib.sortedGenres.length === 0
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 48, 420)
                    spacing: 9
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "No embedded genre tags found"
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.Light
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Genres appear here from each track's GENRE metadata."
                        color: Theme.washMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.washSub
                    }
                }
            }

            // ---- FOLDERS A: one continuous, path-first cover run ----
            GridView {
                id: folderVariedWall
                objectName: "libraryFolderSourceRooms"
                visible: lib.tab === "folders"
                anchors.fill: parent
                clip: true
                model: lib.sortedFolders
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                readonly property int columns: lib.compact ? 1 : 2
                readonly property int measureCount: Math.ceil(
                    count / Math.max(1, columns))
                cellWidth: Math.floor(width / columns)
                cellHeight: lib.compact ? 122 : 152
                cacheBuffer: cellHeight * 3
                ScrollBar.vertical: ArchiveScrollBar {}

                onModelChanged: Qt.callLater(function() {
                    if (folderVariedWall.visible)
                        folderVariedWall.positionViewAtBeginning()
                })

                delegate: FolderRoomCard {
                    required property var modelData
                    required property int index
                    objectName: "libraryFolderRoom_" + index
                    width: folderVariedWall.cellWidth
                           - (lib.compact ? 0 : 12)
                    height: folderVariedWall.cellHeight
                            - (lib.compact ? 10 : 12)
                    folder: modelData
                    ordinal: index
                    compactCard: lib.compact
                    onOpened: lib.openFolder(folder.path)
                }
            }

            // Retained inertly for one correction migration pass.
            GridView {
                id: folderGrid
                objectName: "libraryFolderSourceRoomsRetired"
                visible: false
                anchors.fill: parent
                clip: true
                model: []
                cellWidth: lib.compact ? width : width / 2
                cellHeight: lib.compact ? 150 : 210
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ArchiveScrollBar {}
                delegate: FolderRoomCard {
                    required property var modelData
                    required property int index
                    objectName: "libraryFolderRoom_" + index
                    width: folderGrid.cellWidth - (lib.compact ? 0 : 14)
                    height: folderGrid.cellHeight - 12
                    folder: modelData
                    ordinal: index
                    compactCard: lib.compact
                    onOpened: lib.openFolder(modelData.path)
                }
            }

            EmptyState {
                visible: !lib.filterQuery.trim() && lib.tab === "albums"
                         && lib._loadedAlbums && lib.albums.length === 0
                anchors.centerIn: parent
                icon: "disc"
                headline: "The shelves are empty"
                hint: "Add music to the library and it will appear here."
            }
            EmptyState {
                objectName: "libraryFilteredEmptyState"
                visible: lib.filterQuery.trim() !== "" && lib.currentResultCount() === 0
                anchors.centerIn: parent
                icon: "search"
                headline: "No " + lib.tabLabel().toLowerCase() + " found"
                hint: "Try another search term."
            }
            }

            // Selected genre: one Library-local detail, never a global route.
            // The header spends the workspace on exact album identity; the
            // complete metadata membership continues as Sleeve Stream rows.
            GridView {
                id: genreDetailGrid
                objectName: "libraryGenreDetailGrid"
                visible: lib.genreDetailOpen
                anchors.fill: parent
                z: 20
                clip: true
                model: visible ? lib.selectedGenreTracks : []
                readonly property int columns: lib.compact ? 1 : 2
                cellWidth: Math.floor(width / columns)
                cellHeight: lib.compact ? 102 : 122
                boundsBehavior: Flickable.StopAtBounds
                keyNavigationWraps: false
                reuseItems: true
                cacheBuffer: cellHeight * 2
                ScrollBar.vertical: ArchiveScrollBar {}

                function revealDetail() {
                    Qt.callLater(function() {
                        if (genreDetailGrid.visible)
                            genreDetailGrid.positionViewAtBeginning()
                    })
                }
                onVisibleChanged: if (visible) revealDetail()
                onModelChanged: if (visible) revealDetail()

                header: Item {
                    id: genreDetailHeader
                    objectName: "libraryGenreDetailHeader"
                    width: genreDetailGrid.width
                    height: lib.compact ? 556 : 406

                    WashLine {
                        id: allGenresAction
                        objectName: "libraryAllGenres"
                        anchors.left: parent.left
                        anchors.top: parent.top
                        label: "← All genres"
                        Accessible.description: "Return to the Genres Monolith"
                        onActivated: lib.showAllGenres()
                    }

                    GenreMosaicCard {
                        id: selectedGenreMosaic
                        objectName: "librarySelectedGenreMosaic"
                        x: 0
                        y: 50
                        width: lib.compact ? parent.width
                                           : Math.floor(parent.width * 0.40)
                        height: lib.compact ? 228 : 276
                        genre: lib.selectedGenreDetail
                        dominant: true
                        compact: lib.compact
                        interactive: false
                        showCopy: false
                    }

                    Item {
                        id: genreDetailIdentity
                        objectName: "libraryGenreDetailIdentity"
                        x: lib.compact ? 0 : selectedGenreMosaic.width + 28
                        y: lib.compact ? selectedGenreMosaic.y
                                         + selectedGenreMosaic.height + 18
                                       : selectedGenreMosaic.y
                        width: lib.compact ? parent.width
                                           : parent.width - x
                        height: lib.compact ? 246
                                           : selectedGenreMosaic.height + 56

                        Text {
                            id: genreDetailEyebrow
                            anchors.left: parent.left
                            anchors.top: parent.top
                            text: "EMBEDDED GENRE"
                            color: Theme.primary
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2.5
                        }
                        Text {
                            id: genreDetailTitle
                            objectName: "libraryGenreDetailTitle"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: genreDetailEyebrow.bottom
                            anchors.topMargin: 8
                            text: lib.selectedGenre
                            color: Theme.washInk
                            elide: Text.ElideRight
                            font.family: Theme.font
                            font.pixelSize: lib.compact ? Theme.fsTitle
                                                        : Theme.fsStat
                            font.weight: Font.Light
                        }
                        Text {
                            id: genreDetailCounts
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: genreDetailTitle.bottom
                            anchors.topMargin: 6
                            text: lib.counted(lib.selectedGenreAlbums.length,
                                              "album") + " · "
                                  + lib.counted(lib.selectedGenreTracks.length,
                                                "song")
                            color: Theme.washMuted
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washSub
                            font.letterSpacing: 0.8
                        }
                        // A genre is a room, and a room plays. Same line
                        // actions, same order as every other detail page
                        // (Album View grammar, 2026-08-22).
                        Row {
                            id: genreDetailActions
                            objectName: "libraryGenreDetailActions"
                            anchors.left: parent.left
                            anchors.top: genreDetailCounts.bottom
                            anchors.topMargin: lib.compact ? 6 : 10
                            height: 44
                            spacing: lib.compact ? 20 : 26
                            WashLine {
                                objectName: "libraryGenrePlay"
                                label: "Play →"
                                primaryAction: true
                                onActivated: {
                                    var files = lib.selectedGenreFiles
                                    if (files.length) backend.playFiles(files, 0)
                                }
                            }
                            WashLine {
                                objectName: "libraryGenreShuffle"
                                label: "Shuffle"
                                onActivated: {
                                    var files = lib.selectedGenreFiles
                                    if (files.length) backend.playFilesShuffled(files)
                                }
                            }
                            WashLine {
                                objectName: "libraryGenreQueue"
                                label: "Queue"
                                onActivated: {
                                    var files = lib.selectedGenreFiles
                                    if (files.length) backend.queueFiles(files)
                                }
                            }
                        }
                        Text {
                            id: genreAlbumsLabel
                            anchors.left: parent.left
                            anchors.top: genreDetailActions.bottom
                            anchors.topMargin: lib.compact ? 8 : 16
                            text: "ALBUMS IN THIS GENRE"
                            color: Theme.washFaint
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2.2
                        }
                        ListView {
                            id: genreAlbumRail
                            objectName: "libraryGenreAlbumRail"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: genreAlbumsLabel.bottom
                            anchors.topMargin: 8
                            anchors.bottom: parent.bottom
                            orientation: ListView.Horizontal
                            spacing: lib.compact ? 10 : 14
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            model: lib.selectedGenreAlbums

                            delegate: Item {
                                id: genreAlbumCard
                                required property var modelData
                                required property int index
                                objectName: "libraryGenreAlbum_" + index
                                readonly property real artSize: lib.compact
                                    ? Math.min(78, genreAlbumRail.height - 22)
                                    : Math.min(112, genreAlbumRail.height - 24)
                                width: artSize
                                height: genreAlbumRail.height
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.album + " by "
                                                 + modelData.artist
                                Accessible.description: "Open this album"
                                Accessible.onPressAction: lib.openAlbum(
                                    modelData.path, modelData.album)
                                Keys.onReturnPressed: lib.openAlbum(
                                    modelData.path, modelData.album)
                                Keys.onSpacePressed: lib.openAlbum(
                                    modelData.path, modelData.album)

                                MediaArtwork {
                                    id: genreAlbumArt
                                    objectName: genreAlbumCard.objectName + "Art"
                                    anchors.top: parent.top
                                    width: genreAlbumCard.artSize
                                    height: width
                                    kind: "album"
                                    source: genreAlbumCard.modelData.cover
                                            ? "image://art/" + encodeURIComponent(
                                                  genreAlbumCard.modelData.cover)
                                            : ""
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: genreAlbumArt.bottom
                                    anchors.topMargin: 4
                                    text: genreAlbumCard.modelData.album
                                    elide: Text.ElideRight
                                    color: Theme.washInk
                                    font.family: Theme.font
                                    font.pixelSize: Theme.washSub
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    color: genreAlbumTap.pressed
                                           ? Qt.alpha(Theme.washInk, 0.08)
                                           : "transparent"
                                    border.width: genreAlbumCard.activeFocus ? 1 : 0
                                    border.color: Theme.focusRing
                                }
                                HoverHandler {
                                    id: genreAlbumHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    id: genreAlbumTap
                                    onTapped: lib.openAlbum(
                                        genreAlbumCard.modelData.path,
                                        genreAlbumCard.modelData.album)
                                }
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.washHair
                    }
                }

                delegate: SleeveTrackRow {
                    required property var modelData
                    required property int index
                    objectName: "libraryGenreTrack_" + index
                    width: genreDetailGrid.cellWidth - (lib.compact ? 0 : 12)
                    height: genreDetailGrid.cellHeight - 10
                    compact: lib.compact
                    trackData: modelData
                    fileList: lib.selectedGenreFiles
                    rowIndex: index
                    onActiveFocusChanged: {
                        if (activeFocus)
                            genreDetailGrid.currentIndex = index
                    }
                }
            }

            // PLAYLISTS: the collection wall uses the indexed shelf. Selecting
            // one sequence expands this same component across the Library
            // workspace, yielding the index only while exact art-led membership
            // is being examined. There is still one local navigation owner.
            PlaylistsView {
                id: playlistSurface
                objectName: "libraryPlaylistSurface"
                visible: lib.tab === "playlists"
                x: selected !== "" ? 0 : shelves.x
                y: selected !== "" ? 0 : shelves.y
                width: selected !== "" ? workspace.width : shelves.width
                height: selected !== "" ? workspace.height : shelves.height
                z: selected !== "" ? 20 : 0
                compact: lib.compact
                playlistNames: lib.sortedPlaylists
                filterActive: lib.filterQuery.trim() !== ""
            }
        }
    }
}
