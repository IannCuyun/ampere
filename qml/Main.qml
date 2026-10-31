import QtQuick
import QtCore
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Shapes
import "."

ApplicationWindow {
    id: root
    width: windowPrefs.w
    height: windowPrefs.h
    minimumWidth: mini ? 560 : 720
    minimumHeight: mini ? 96 : 480
    visible: true
    title: "Ampere"
    color: "#100e0d"

    property string browsePath: ""          // browse mode: "" = the Library directory (L.01)
    property string albumPath: ""           // album mode: the folder open as a record
    property string albumName: ""           // album tag disambiguates shared artist folders
    property string mode: "home"            // Home is the stable landing room
    // Window size and the last stable room survive restarts (x/y are not
    // stored: Wayland ignores them). Transient rooms never come back.
    Settings {
        id: windowPrefs
        category: "window"
        property int w: 1380
        property int h: 880
        property string lastMode: "home"
    }
    // DJ is not restorable because it is not routable: SPEC UNDESIGNED #10
    // parks it until Iann defines the mixer workflow (ROADMAP 3.2).
    readonly property var _restorableModes: ["home", "browse", "features", "now", "radio",
        "rewind", "settings", "eq", "doctor", "disliked", "ampy"]
    function _rememberWindow() {
        if (mini || visibility !== Window.Windowed) return
        windowPrefs.w = width
        windowPrefs.h = height
    }
    property string artistName: ""
    property string artistPath: ""
    property string shelfName: ""           // smart mode: arrivals | heavy | loved | history
    property bool searchOpen: false         // the search overlay (whisper rail glyph / Ctrl+F)
    // Only one presentation tree owns native geometry at a time. Route pages
    // retain their last useful pair while Search, Ambient, or Mini covers the
    // room, then adopt the final pair when ownership returns.
    readonly property bool routeRoomActive:
        !mini && !ambient && !searchOpen
    // Gallery Monolith owns Lyrics as an in-page desktop state. Main mirrors
    // it only to give Esc one unambiguous owner while fullscreen is active.
    property bool nowLyricsOpen: false
    property bool _nowPrewarmed: false
    property string pendingNowPanel: ""

    function activeShuffleContext() {
        if (mode === "album") return { kind: "album", label: "ALBUM · " + (albumName || albumPath.split("/").pop()), path: albumPath, album: albumName }
        if (mode === "artist") return {
            kind: "artist", label: "ARTIST · " + artistName,
            path: artistPath, files: artistPage.artistFiles
        }
        if (mode === "browse" && browsePath) return { kind: "folder", label: "FOLDER · " + browsePath.split("/").pop(), path: browsePath }
        if (mode === "browse" && !browsePath
                && libraryPage.tab === "playlists"
                && libraryPage.selectedPlaylist)
            return { kind: "playlist",
                     label: "PLAYLIST · " + libraryPage.selectedPlaylist,
                     name: libraryPage.selectedPlaylist,
                     files: libraryPage.selectedPlaylistFiles }
        if (mode === "browse" && !browsePath
                && libraryPage.tab === "genres"
                && libraryPage.selectedGenre)
            return { kind: "collection",
                     label: "GENRE · " + libraryPage.selectedGenre,
                     files: libraryPage.selectedGenreFiles }
        if (mode === "smart") return { kind: "collection", label: "SMART COLLECTION", files: smartPage.fileList }
        if (mode === "browse" && libraryPage.tab === "songs") return { kind: "collection", label: "SONGS", files: libraryPage.sortedSongs.map(function(song) { return song.file }) }
        return { kind: "queue", label: "CURRENT QUEUE" }
    }

    // "Just the record" — Now Playing's bare mode owns the whole window, so
    // the shell's own chrome (the AMPERE trigger, search) leaves with it.
    property bool nowBare: false

    Binding {
        target: Theme
        property: "immersive"
        value: root.mode === "now" || root.mode === "radio" || root.ambient
    }

    function openArtist(name, path) {
        // Artist membership is CREDIT-scoped, never folder-scoped (SPEC row
        // 38), so an empty path is a legitimate destination: the page derives
        // each release's directory from its own tracks. Rejecting it here
        // silently killed every credit-only entrance — the Album page's
        // artist breadcrumb among them (found 2026-08-22).
        if (!name) return
        artistName = name
        artistPath = path || ""
        mode = "artist"
    }

    function openAlbum(path, album) {
        if (!path) return
        albumPath = path
        albumName = album || ""
        mode = "album"
    }

    // ---- browser-style history: every page change is a stop you can
    // revisit with ‹ › (Alt+←/→ or the mouse side buttons) ----
    property var backStack: []
    property var fwdStack: []
    property var _curNav: null
    property bool _navLock: false
    function _navSnapshot() {
        return {mode: mode, browsePath: browsePath, artistName: artistName,
                artistPath: artistPath, albumPath: albumPath,
                albumName: albumName,
                shelfName: shelfName,
                libraryTab: libraryPage.tab,
                playlistName: libraryPage.selectedPlaylist,
                genreName: libraryPage.selectedGenre}
    }
    function _navSame(a, b) {
        return a && b && a.mode === b.mode && a.browsePath === b.browsePath
            && a.artistName === b.artistName && a.artistPath === b.artistPath
            && a.albumPath === b.albumPath && a.albumName === b.albumName
            && a.shelfName === b.shelfName
            && a.libraryTab === b.libraryTab
            && a.playlistName === b.playlistName
            && a.genreName === b.genreName
    }
    function _navChanged() { if (!_navLock) Qt.callLater(_navSettle) }
    // callLater coalesces the compound changes of one navigation into one entry
    function _navSettle() {
        var s = _navSnapshot()
        if (_curNav && !_navSame(_curNav, s)) {
            backStack = backStack.concat([_curNav])
            fwdStack = []
        }
        _curNav = s
    }
    function _navApply(s) {
        _navLock = true
        mode = s.mode
        browsePath = s.browsePath
        artistName = s.artistName
        artistPath = s.artistPath
        albumPath = s.albumPath || ""
        albumName = s.albumName || ""
        shelfName = s.shelfName
        var targetTab = s.libraryTab || "albums"
        if (targetTab === "playlists")
            libraryPage.openPlaylist(s.playlistName || "")
        else if (targetTab === "genres" && s.genreName)
            libraryPage.openGenre(s.genreName)
        else
            libraryPage.openRoom(targetTab)
        _curNav = s
        Qt.callLater(function() { _navLock = false })
    }
    function goBack() {
        if (backStack.length === 0) return
        var target = backStack[backStack.length - 1]
        fwdStack = fwdStack.concat([_navSnapshot()])
        backStack = backStack.slice(0, backStack.length - 1)
        _navApply(target)
    }
    function goForward() {
        if (fwdStack.length === 0) return
        var target = fwdStack[fwdStack.length - 1]
        backStack = backStack.concat([_navSnapshot()])
        fwdStack = fwdStack.slice(0, fwdStack.length - 1)
        _navApply(target)
    }
    function applyPendingNowPanel() {
        if (!nowPresentation.item || pendingNowPanel === "") return
        if (pendingNowPanel === "lyrics") nowPresentation.item.setLyrics(true)
        else if (pendingNowPanel === "queue") nowPresentation.item.setQueue(true)
        pendingNowPanel = ""
    }
    function openNowPanel(panel) {
        pendingNowPanel = panel
        mode = "now"
        Qt.callLater(applyPendingNowPanel)
    }
    function retreat() {
        // The global Esc shortcut fires before the focused item's own
        // Keys.onEscapePressed, so page-local owners are honoured here: a
        // text field with content clears instead of navigating away.
        var f = root.activeFocusItem
        var editing = !!(f && f.hasOwnProperty("cursorPosition"))
        if (editing && !appHeader.fieldHasFocus && f.text !== "") { f.text = ""; return }
        if (trackEditor.visible) { trackEditor.close(); return }
        if (searchOpen) {
            // Staged Esc (S-09): from a result back to the field first,
            // from the field the room closes.
            if (!appHeader.fieldHasFocus) { appHeader.focusField(); return }
            closeSearch(); return
        }
        if (archiveHeader.menuOpen) { archiveHeader.closeMenu(); return }
        if (mode === "now" && nowPresentation.item
                && (nowPresentation.item.panelsOpen || nowBare)) {
            nowPresentation.item.closePanels(); return
        }
        // The drawer is hidden on DJ/Now even while wanted: Esc must not
        // be swallowed by a pane nobody can see.
        if (queuePane.visible) { queuePane.wanted = false; return }
        // A Discover lane is a Home state, not a history entry: close it
        // before leaving the room.
        if (mode === "home" && homePage.discoverLaneKey !== "") { homePage.closeDiscover(); return }
        goBack()
    }
    onModeChanged: {
        _navChanged()
        if (mode !== "now") nowBare = false
        else queuePane.wanted = false
        // The search room is an overlay, not a route: any route change
        // (header, menu, /api/nav, history) dismisses it.
        if (searchOpen) closeSearch()
        if (_restorableModes.indexOf(mode) >= 0) windowPrefs.lastMode = mode
    }
    onBrowsePathChanged: { _navChanged(); if (searchOpen) closeSearch() }
    onAlbumPathChanged: { _navChanged(); if (searchOpen) closeSearch() }
    onAlbumNameChanged: _navChanged()
    onArtistNameChanged: { _navChanged(); if (searchOpen) closeSearch() }
    onArtistPathChanged: _navChanged()
    onShelfNameChanged: _navChanged()
    Component.onCompleted: {
        if (_restorableModes.indexOf(windowPrefs.lastMode) >= 0)
            mode = windowPrefs.lastMode
        _curNav = _navSnapshot()
    }
    Shortcut { sequence: "Alt+Left"; enabled: !root.ambient; onActivated: root.goBack() }
    Shortcut { sequence: "Alt+Right"; enabled: !root.ambient; onActivated: root.goForward() }
    Shortcut { sequence: "Ctrl+N"; enabled: !root.ambient; onActivated: root.mode = root.mode === "now" ? "home" : "now" }

    // ---- fullscreen + mini-player ----
    // The compositor reports several intermediate sizes while a tiled window
    // enters or leaves fullscreen. Flag that short interval so retained rooms
    // can follow the compositor directly instead of launching their own
    // animations and repaint loops for every intermediate geometry.
    property bool windowGeometryChanging: false
    property int _geometryStableFrames: 0
    property real _geometryFrameWidth: width
    property real _geometryFrameHeight: height
    property double _geometryStartedAt: 0
    property int lastWindowGeometryMs: 0
    function markWindowGeometryChange() {
        if (!windowGeometryChanging)
            _geometryStartedAt = Date.now()
        windowGeometryChanging = true
        _geometryStableFrames = 0
        _geometryFrameWidth = width
        _geometryFrameHeight = height
    }
    onWidthChanged: { markWindowGeometryChange(); _rememberWindow() }
    onHeightChanged: { markWindowGeometryChange(); _rememberWindow() }
    function finishWindowGeometryChange() {
        lastWindowGeometryMs = _geometryStartedAt > 0
                ? Math.max(0, Math.round(Date.now() - _geometryStartedAt)) : 0
        console.info("Ampere window geometry settled in "
                     + lastWindowGeometryMs + " ms")
        windowGeometryChanging = false
        if (ambientExitPending) {
            ambientExitPending = false
            ambient = false
        }
    }
    FrameAnimation {
        id: windowGeometrySettle
        running: root.windowGeometryChanging
        onTriggered: {
            var unchanged = Math.abs(root.width - root._geometryFrameWidth) < 0.5
                    && Math.abs(root.height - root._geometryFrameHeight) < 0.5
            root._geometryFrameWidth = root.width
            root._geometryFrameHeight = root.height
            root._geometryStableFrames = unchanged
                    ? root._geometryStableFrames + 1 : 0
            if (root._geometryStableFrames >= 2)
                root.finishWindowGeometryChange()
        }
    }
    readonly property bool fullscreen: visibility === Window.FullScreen
    function toggleFullscreen() {
        markWindowGeometryChange()
        visibility = fullscreen ? Window.Windowed : Window.FullScreen
    }
    Shortcut { sequence: "F11"; enabled: !root.ambient; onActivated: root.toggleFullscreen() }
    // selectAll must wait a tick — focus lands async and clears the selection
    Shortcut {
        sequence: "Ctrl+F"
        enabled: !root.ambient
        onActivated: root.openSearch()
    }
    Shortcut { sequence: "Esc"; enabled: !root.ambient; onActivated: root.retreat() }

    // ---- transport + surface shortcuts ----
    // Window-context shortcuts fire before the focused item sees the key, so
    // they sleep while a text field is being edited (and Space also while a
    // keyboard-focused control would otherwise activate on it).
    readonly property bool textEditing: !!(activeFocusItem
        && activeFocusItem.hasOwnProperty("cursorPosition"))
    readonly property bool controlFocused: !!(activeFocusItem && activeFocusItem.activeFocusOnTab)
    Shortcut { sequence: "Space"; enabled: !root.ambient && !root.textEditing && !root.controlFocused; onActivated: backend.requestPlayPause() }
    Shortcut { sequence: "Ctrl+Right"; enabled: !root.ambient && !root.textEditing; onActivated: backend.requestNext() }
    Shortcut { sequence: "Ctrl+Left"; enabled: !root.ambient && !root.textEditing; onActivated: backend.requestPrevious() }
    Shortcut { sequence: "Ctrl+Up"; enabled: !root.ambient && !root.textEditing; onActivated: backend.requestVolume(Math.min(100, backend.volume + 5)) }
    Shortcut { sequence: "Ctrl+Down"; enabled: !root.ambient && !root.textEditing; onActivated: backend.requestVolume(Math.max(0, backend.volume - 5)) }
    Shortcut {
        sequence: "Ctrl+Q"
        enabled: !root.ambient && !root.textEditing
        onActivated: {
            if (root.mode === "now") root.openNowPanel("queue")
            else queuePane.wanted = !queuePane.wanted
        }
    }
    Shortcut { sequence: "Ctrl+,"; enabled: !root.ambient && !root.textEditing; onActivated: root.mode = "settings" }
    Shortcut { sequence: "Ctrl+L"; enabled: !root.ambient && !root.textEditing; onActivated: root.navigate("") }
    Shortcut { sequence: "Ctrl+M"; enabled: !root.ambient && !root.textEditing; onActivated: root.toggleMini() }

    function openSearch() {
        archiveHeader.closeMenu()
        searchOpen = true
        appHeader.focusSearch()
    }
    // Closing keeps the last query and results (DECISIONS 2026-08-20 #5);
    // openSearch() restores them with the field focused and selected.
    function closeSearch() {
        searchOpen = false
    }
    // Remote/harness entry: `search` with a query restores the room for that
    // text; an `all:` prefix also opens the full song list (verdict #1).
    function openSearchFor(text) {
        openSearch()
        var wanted = String(text || "")
        if (wanted === "history:") { appHeader.query = ""; return }
        var expand = wanted.indexOf("all:") === 0
        var menu = wanted.indexOf("menu:") === 0
        if (expand || menu) wanted = wanted.substring(wanted.indexOf(":") + 1)
        if (wanted === "") return
        appHeader.query = wanted
        if (expand) appHeader.submit()
        if (menu) appHeader.openFirstRowMenu()
    }

    // ---- ambient mode (the room screensaver) ----
    property bool ambient: false
    property bool ambientEnterPending: false
    property bool ambientExitPending: false
    property bool _ambientPrewarmed: false
    property int _preAmbientVis: Window.Windowed
    function enterAmbient() {
        _preAmbientVis = visibility
        ambientEnterPending = true
        ambientExitPending = false
        ambient = true
    }
    function leaveAmbient() {
        if (ambientEnterPending) {
            ambientEnterPending = false
            ambient = false
            return
        }
        markWindowGeometryChange()
        if (_preAmbientVis === Window.FullScreen) {
            ambient = false
            return
        }
        ambientExitPending = true
        visibility = _preAmbientVis === Window.Maximized
                ? Window.Maximized : Window.Windowed
    }
    FrameAnimation {
        id: ambientEntryFrame
        running: root.ambientEnterPending
        // FrameAnimation triggers only after a rendered frame. The Hall is
        // therefore genuinely presented at the current exact geometry before
        // the compositor receives the fullscreen request.
        onTriggered: {
            root.ambientEnterPending = false
            root.markWindowGeometryChange()
            root.visibility = Window.FullScreen
        }
    }

    // Stillpoint carries no visualizer. The retained loader is prewarmed below,
    // but Ampere no longer imports or starts the unused FFT stack at startup.
    Timer {
        interval: 1200
        running: true
        repeat: false
        onTriggered: root._ambientPrewarmed = true
    }
    Timer {
        interval: 700
        running: true
        repeat: false
        onTriggered: root._nowPrewarmed = true
    }

    property bool mini: false
    property size _restoreSize: Qt.size(1380, 880)
    property int _restoreVisibility: Window.Windowed
    function toggleMini() {
        if (!mini) {
            _restoreVisibility = visibility
            if (visibility === Window.Windowed)
                _restoreSize = Qt.size(width, height)
            mini = true
            visibility = Window.Windowed
            width = 560
            height = 96
        } else {
            mini = false
            if (_restoreVisibility === Window.Windowed) {
                visibility = Window.Windowed
                width = _restoreSize.width
                height = _restoreSize.height
            } else {
                visibility = _restoreVisibility
            }
        }
    }

    // sleep timer (set from Settings): pauses playback when it fires
    property int sleepMinutes: 0
    Timer {
        interval: Math.max(1, root.sleepMinutes) * 60000
        running: root.sleepMinutes > 0
        onTriggered: {
            if (backend.state === "play") backend.requestPlayPause()
            root.sleepMinutes = 0
        }
    }

    function navigate(p) {
        mode = "browse"
        browsePath = p
        closeSearch()
    }

    // Stable Library-directory entry point: every destination tab on a
    // Library-family page returns to the L.01 directory on that tab.
    function openLibrarySection(section) {
        mode = "browse"
        browsePath = ""
        if (section === "playlists")
            libraryPage.openPlaylist("")
        else
            libraryPage.openRoom(section || "albums")
        closeSearch()
    }

    // Compatibility entry for remote/deep links. Playlists are not a route:
    // they resolve to the embedded Open Room Index shelf.
    function openLibraryPlaylist(name) {
        mode = "browse"
        browsePath = ""
        libraryPage.openPlaylist(name || "")
        closeSearch()
    }

    // Listening Atlas owns no feature behavior. It hands each exact intent to
    // the existing route or setting owner, including the two contextual tools
    // whose usable entrance is a prepared playlist or the current record.
    function openAtlasFeature(feature) {
        closeSearch()
        if (feature === "discover") {
            mode = "home"
            homePage.openDiscoverLane("loved")
        } else if (feature === "rewind" || feature === "ampy"
                   || feature === "eq" || feature === "doctor"
                   || feature === "disliked") {
            mode = feature
        } else if (feature === "smart-shuffle") {
            openLibrarySection("playlists")
        } else if (feature === "autoplay") {
            mode = "settings"
        } else if (feature === "ambient") {
            if (backend.currentSong.file)
                enterAmbient()
            else
                mode = "now"
        }
    }

    // ---- the room: Archive Wash under everything (design/SPEC.md) ----
    PageSlot {
        anchors.fill: parent
        // The wash is a full-window shader. Freeze it while opaque Ambient
        // owns the scene instead of resizing a covered render surface.
        current: !root.ambient && !root.mini

        ArchiveWash {
            anchors.fill: parent
            // Ambient is opaque and owns the whole scene. Keeping Archive Wash
            // alive beneath it doubled the amount of fullscreen resize work.
            visible: !root.mini && !root.ambient
            // Now Playing IS the record's room (Iann, 2026-08-02): the playback
            // page thins the veil so the cover itself is the background, while
            // every utility page keeps the dialed 0.74 reading veil.
            // and it drops the sharp whole-record layer there, so the page shows
            // the cover exactly once (its sleeve) over a soft field of itself.
            readonly property bool playbackRoom: root.mode === "now" || root.mode === "radio"
            // Album View points this full-window wash at the record being
            // examined. Keeping the wash here (rather than inside the clipped
            // page room) lets that record continue behind the translucent
            // persistent player all the way to the window edge.
            readonly property bool albumRoom: root.mode === "album"
            // Rooms whose job is READING carry long-form copy directly on the
            // wash. The veil alone cannot hold it against a busy cover, so
            // these drop the sharp whole-record layer and keep only the soft
            // ambient field — the record's colour without its detail. The
            // sharp record stays wherever the record is the subject.
            readonly property bool readingRoom: root.mode === "doctor"
                                                || root.mode === "settings"
                                                || root.mode === "eq"
            // Bare mode: the sleeve itself has grown to fill the window, so the
            // room behind it only has to hold the leftover margins — it darkens
            // out of the record's way instead of competing with it.
            sourceFile: albumRoom ? albumPage.roomFile
                                  : (backend.currentSong.file || "")
            veil: root.nowBare ? 0.86
                               : ((playbackRoom || albumRoom) ? 0.60 : 0.74)
            fitStrength: (playbackRoom || albumRoom || readingRoom) ? 0.0 : 1.0
            Behavior on veil {
                NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
            }
            Behavior on fitStrength {
                NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
            }
        }
    }

    // Playback B (SPEC sprint-lock): on Now Playing the bottom bar is
    // REMOVED — the page integrates the full transport — so the room owns
    // the whole window there.
    readonly property bool barHidden: (root.mode === "now" || root.mode === "radio") && !root.mini

    Item {
        id: room
        // Retain page instances and state, but do not render the covered room
        // while Ambient is resizing above it.
        visible: !root.mini && !root.ambient
        // The persistent player is chrome, not page. At the 720x480 floor
        // several rooms laid out taller than the room they were given and
        // painted their own content across the transport — the Library
        // index's Disliked threshold and every Disliked action landed on top
        // of the playing song (found 2026-08-22, ROADMAP 5.1). A page may run
        // out of room; it may never take the player's. Menus are Popups and
        // live in the window overlay, so they still escape this.
        clip: true
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: root.barHidden ? parent.bottom : bar.top

        // ---------- offline strip ----------
        Rectangle {
            z: 25
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            width: offlineText.width + 36
            height: visible ? 30 : 0
            visible: !backend.connected
            color: Qt.alpha(Theme.error, 0.18)
            Text {
                id: offlineText
                anchors.centerIn: parent
                text: "PLAYBACK ENGINE OFFLINE — reconnecting"
                color: Theme.error
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.letterSpacing: 2
            }
        }

        // Layer 2, Archive Header: the persistent header never covers the
        // page, so pages only leave for the search room now.
        Item {
            id: pageLayer
            anchors.fill: parent
            visible: !root.searchOpen
            enabled: visible

        // ---------- full-room pages (new composition) ----------
        PageSlot {
            anchors.fill: parent
            current: root.routeRoomActive && root.mode === "home"
            LandingView {
                id: homePage
                anchors.fill: parent
                active: root.routeRoomActive && root.mode === "home"
                onOpenLibrary: root.navigate("")
                onOpenNow: root.mode = "now"
                onOpenRewind: root.mode = "rewind"
                onOpenAmpy: root.mode = "ampy"
                onOpenShelf: s => { root.shelfName = s; root.mode = "smart" }
                onOpenArtist: (n, p) => root.openArtist(n, p)
                onOpenAlbum: (p, a) => root.openAlbum(p, a)
            }
        }
        PageSlot {
            anchors.fill: parent
            current: root.routeRoomActive && root.mode === "features"
            FeaturesView {
                id: featuresPage
                anchors.fill: parent
                active: root.routeRoomActive && root.mode === "features"
                onOpenFeature: feature => root.openAtlasFeature(feature)
            }
        }
        PageSlot {
            anchors.fill: parent
            current: root.routeRoomActive
                && root.mode === "browse" && root.browsePath === ""
            LibraryView {
                id: libraryPage
                anchors.fill: parent
                active: root.routeRoomActive
                    && root.mode === "browse" && root.browsePath === ""
                onOpenAlbum: (p, a) => root.openAlbum(p, a)
                onOpenArtistPage: (n, p) => root.openArtist(n, p)
                onOpenFolder: p => root.navigate(p)
                onOpenDisliked: root.mode = "disliked"
                onTabChanged: root._navChanged()
                onSelectedPlaylistChanged: root._navChanged()
                onSelectedGenreChanged: root._navChanged()
            }
        }
        PageSlot {
            anchors.fill: parent
            // Ambient keeps this retained Gallery instance warm, but a hidden
            // Gallery must not inherit the fullscreen configure sequence.
            current: root.routeRoomActive && root.mode === "now"
            Loader {
                id: nowPresentation
                anchors.fill: parent
                // The playback rooms carry full-resolution art and several
                // viewport-sized render surfaces. Do not realize either
                // presentation while the Library (or another page) owns the
                // window; visibility alone does not prevent child resources
                // from being prepared by Qt's scene graph.
                active: root._nowPrewarmed || root.mode === "now"
                asynchronous: root.mode !== "now"
                sourceComponent: galleryNowPlaying
                onLoaded: root.applyPendingNowPanel()
            }
        }

        Component {
            id: galleryNowPlaying
            GalleryNowPlayingView {
                anchors.fill: parent
                active: root.routeRoomActive && root.mode === "now"
                suspended: root.ambient
                windowGeometryChanging: root.windowGeometryChanging
                onLyricsOpenChanged: root.nowLyricsOpen = lyricsOpen
                // Main is the single writer for bare mode: the rail's button
                // and the page's own affordances all route requests here, so
                // the two surfaces can never disagree about the state.
                bare: root.nowBare
                onBareRequested: on => root.nowBare = on
                onOpenAlbum: (p, a) => root.openAlbum(p, a)
                onOpenArtist: (n, p) => root.openArtist(n, p)
                // no onToggleQueue: the gallery page renders Up Next inline in
                // its own panel region rather than sliding the global drawer
                // over the room (Iann, 2026-08-02).
                onToggleMini: root.toggleMini()
                onOpenRadio: root.mode = "radio"
                shuffleContext: root.activeShuffleContext()
            }
        }

        // SPEC.md · Song Radio / Signal + Sequence: retain the station room
        // through history navigation; the backend owns selection and playback.
        PageSlot {
            anchors.fill: parent
            current: root.routeRoomActive && root.mode === "radio"
            Loader {
                anchors.fill: parent
                active: root.mode === "radio"
                sourceComponent: Component {
                    RadioView {
                        anchors.fill: parent
                        active: root.routeRoomActive && root.mode === "radio"
                        windowGeometryChanging: root.windowGeometryChanging
                        onOpenAlbum: (p, a) => root.openAlbum(p, a)
                        onOpenArtist: (n, p) => root.openArtist(n, p)
                        onToggleMini: root.toggleMini()
                        shuffleContext: root.activeShuffleContext()
                        onExitRadioRequested: backend.exitBeaconRadio()
                    }
                }
            }
        }

        // ---------- legacy pages: inset clear of the whisper rail ----------
        Item {
            id: legacyStage
            anchors.fill: parent
            anchors.leftMargin: 0

            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "disliked"
                DislikedView {
                    anchors.fill: parent
                    // Back returns where the visitor came from; the
                    // Library is the fallback when nothing is behind.
                    onBack: root.backStack.length > 0 ? root.goBack() : root.navigate("")
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive
                    && root.mode === "browse" && root.browsePath !== ""
                BrowseView {
                    anchors.fill: parent
                    path: root.browsePath
                    onOpenPath: p => root.navigate(p)
                    onOpenAlbum: (p, a) => root.openAlbum(p, a)
                    onDestinationRequested: section => root.openLibrarySection(section)
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "album"
                AlbumView {
                    id: albumPage
                    anchors.fill: parent
                    active: root.routeRoomActive && root.mode === "album"
                    albumPath: root.albumPath
                    albumName: root.albumName
                    onDestinationRequested: section => root.openLibrarySection(section)
                    onArtistRequested: name => root.openArtist(name, "")
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "doctor"
                DoctorView {
                    id: doctorPage
                    anchors.fill: parent
                    active: root.routeRoomActive && root.mode === "doctor"
                    // A tag finding opens the repair page over the Doctor,
                    // carrying the whole finding set so the edge arrows walk
                    // it (Iann, 2026-08-21).
                    onRepairRequested: index => tagRepair.open(
                        doctorPage.findingsFor(3), index)
                    onCompareRequested: index => versionCompare.open(
                        doctorPage.findingsFor(0), index)
                }
                VersionCompareView {
                    id: versionCompare
                    objectName: "versionComparePage"
                    anchors.fill: parent
                    visible: active
                    z: 60
                    onClosed: active = false
                    // Editing from the comparison hands the file to the same
                    // repair page, so there is one tag editor in the app.
                    onEditRequested: track => {
                        versionCompare.active = false
                        tagRepair.open([{ file: track.file, missing: [] }], 0)
                    }
                }
                TagRepairView {
                    id: tagRepair
                    objectName: "tagRepairPage"
                    anchors.fill: parent
                    visible: active
                    z: 60
                    onClosed: { active = false; backend.runDoctor() }
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "eq"
                EqView { anchors.fill: parent }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "smart"
                SmartView {
                    id: smartPage
                    anchors.fill: parent
                    active: root.routeRoomActive && root.mode === "smart"
                    shelf: root.mode === "smart" ? root.shelfName : ""
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "rewind"
                RewindView {
                    id: rewindPage
                    anchors.fill: parent
                    active: root.routeRoomActive && root.mode === "rewind"
                    onOpenArtistPage: (n, p) => root.openArtist(n, p)
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "ampy"
                AmpyView {
                    anchors.fill: parent
                    active: root.routeRoomActive && root.mode === "ampy"
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "artist"
                ArtistView {
                    id: artistPage
                    anchors.fill: parent
                    artistName: root.artistName
                    artistPath: root.artistPath
                    onOpenPath: p => root.navigate(p)
                    onOpenAlbum: (p, a) => root.openAlbum(p, a)
                    onDestinationRequested: section => root.openLibrarySection(section)
                }
            }
            PageSlot {
                anchors.fill: parent
                current: root.routeRoomActive && root.mode === "settings"
                SettingsView {
                    anchors.fill: parent
                    sleepMinutes: root.sleepMinutes
                    onSleepPicked: m => { root.sleepMinutes = 0; root.sleepMinutes = m }
                    onOpenDoctor: root.mode = "doctor"
                }
            }
        }
        }

        // ---------- Archive Header (design/SPEC.md · Navigation) ----------
        WhisperRail {
            id: archiveHeader
            anchors.fill: parent
            z: 60
            // bare mode takes the wordmark and search with it
            opacity: root.nowBare ? 0 : 1
            visible: opacity > 0
            enabled: !root.nowBare
            Behavior on opacity {
                NumberAnimation { duration: 520; easing.type: Easing.OutCubic }
            }
            currentMode: root.mode
            searchOpen: root.searchOpen
            canGoBack: root.backStack.length > 0
            canGoForward: root.fwdStack.length > 0
            ambientAvailable: root.mode === "now" && !root.mini
            onOpenAmbient: root.enterAmbient()
            onNavigateBack: root.goBack()
            onNavigateForward: root.goForward()
            onNavigate: m => {
                root.closeSearch()
                if (m === "home") root.mode = "home"
                else if (m === "library") root.navigate("")
                else root.mode = m
            }
            onOpenSearch: root.openSearch()
        }

        // Queue is a session workspace, not a permanent tax on every
        // page. It opens as a contextual drawer over the current room.
        Rectangle {
            anchors.fill: parent
            z: 39
            visible: queuePane.wanted && root.mode !== "now"
            color: Qt.alpha("#000000", 0.34)
            TapHandler { onTapped: queuePane.wanted = false }
        }

        QueuePane {
            id: queuePane
            z: 40
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            // At compact widths the queue becomes the focused session
            // workspace; on a full room it remains a restrained plane.
            width: room.width < 760
                ? room.width
                : Math.min(432, Math.max(360, room.width * 0.42))
            property bool wanted: false
            // Now Playing renders Up Next inside the page at desktop widths,
            // so the global drawer must not double it there.
            visible: wanted && root.mode !== "now"
            border.color: Theme.divider
            border.width: 1
            onCloseRequested: wanted = false

            transform: Translate { x: queuePane.visible ? 0 : queuePane.width }
        }

        // ---------- Search: Listening Observatory full-room index ----------
        Item {
            z: 45
            visible: root.searchOpen
            enabled: visible
            anchors.fill: parent

            SignalHeader {
                id: appHeader
                anchors.fill: parent
                onEditTrack: track => trackEditor.open(track)
                onOpenFolder: p => root.navigate(p)
                onOpenAlbum: (p, a) => { root.openAlbum(p, a); root.searchOpen = false }
                onOpenArtist: (n, p) => { root.openArtist(n, p); root.searchOpen = false }
                onDismiss: root.closeSearch()
            }
        }
    }

    // ---------- player bar ----------
        PlayerBar {
        id: bar
        visible: !root.barHidden
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.mini ? root.height : Theme.playerHeight
        shuffleContext: root.activeShuffleContext()
        queueOpen: queuePane.visible
        miniOn: root.mini
        onOpenFolder: p => { if (!root.mini) root.navigate(p) }
        onOpenArtist: (n, p) => { if (!root.mini) root.openArtist(n, p) }
        onOpenAlbum: (p, a) => { if (!root.mini) root.openAlbum(p, a) }
        onOpenLyrics: if (!root.mini) root.openNowPanel("lyrics")
        onOpenNow: if (!root.mini) root.mode = "now"
        onToggleQueue: if (!root.mini) {
            if (root.mode === "now") root.openNowPanel("queue")
            else queuePane.wanted = !queuePane.wanted
        }
        onToggleMini: root.toggleMini()
        onSaveMix: if (!root.mini) {
            queuePane.wanted = true
            queuePane.showSave()
        }
    }

    // metadata editor — resolved by dynamic scope from TrackRow edit actions
    // (was a dangling reference before 2026-07-31; BrowseView called it with
    // no instance anywhere)
    TrackEditor {
        id: trackEditor
        anchors.fill: parent
        z: 95
    }

    // ---------- confirmations (Archive Wash surface) ----------
    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.playerHeight + 12
        width: toastText.width + 40
        height: 38
        radius: 0
        color: Qt.alpha(Theme.bgLow, 0.92)
        border.color: Theme.washHair
        border.width: 1
        visible: false
        // A burst of messages shows one after another (max 3 waiting).
        property var pending: []
        function show(msg) {
            if (visible) {
                if (pending.length >= 3) return
                pending = pending.concat([msg])
                return
            }
            toastText.text = msg
            visible = true
            toastTimer.restart()
        }
        function next() {
            visible = false
            if (pending.length === 0) return
            var item = pending[0]
            pending = pending.slice(1)
            show(item)
        }
        Text {
            id: toastText
            anchors.centerIn: parent
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
        }
        Timer { id: toastTimer; interval: 4000; onTriggered: toast.next() }
    }
    Connections {
        target: backend
        function onErrorOccurred(msg) { console.warn("Ampere backend: " + msg) }
        function onNotice(msg) { toast.show(msg) }
        function onSpotSyncDone(msg) { toast.show(msg) }
        function onDislikedDeleted(msg) { toast.show(msg) }
        // remote /api/nav — drives the same router the UI uses
        function onNavRequested(m, arg) {
            if (root.mini) return
            // A route request always leaves the Search room, even when the
            // destination is the page Search was opened over (mode unchanged).
            if (m !== "search" && m !== "results" && root.searchOpen) root.closeSearch()
            if (m === "home") {
                root.mode = "home"
                // A Discover deep-link resolves inside Home; it is not a
                // destination in the application router or history.
                if (String(arg || "").indexOf("discover:") === 0)
                    homePage.openDiscoverLane(String(arg).substring(9) || "loved")
            }
            else if (m === "library") {
                root.navigate("")
                if (arg === "playlists") libraryPage.openPlaylist("")
                else if (arg) libraryPage.openRoom(arg)
            }
            else if (m === "playlists") root.openLibraryPlaylist(arg || "")
            // Genres is a Library destination, not a page of its own
            // (SPEC.md · Browse family: six stable destinations).
            else if (m === "genres")  {
                root.navigate("")
                libraryPage.showAllGenres()
            }
            else if (m === "ambient") root.enterAmbient()
            else if (m === "queue")   {
                if (root.mode === "now") root.openNowPanel("queue")
                else queuePane.wanted = !queuePane.wanted
            }
            else if (m === "lyrics")  root.openNowPanel("lyrics")
            // Search is a room over the page, not a route (SPEC row 23):
            // "results" stays as the legacy nav name for the same room.
            else if (m === "results" || m === "search") root.openSearchFor(arg)
            else if (m === "smart")   { root.shelfName = arg || "arrivals"; root.mode = "smart" }
            else if (m === "browse")  { root.mode = "browse"; if (arg) root.browsePath = arg }
            else if (m === "album")   {
                if (arg) { root.albumPath = arg; root.albumName = "" }
                if (root.albumPath) root.mode = "album"
            }
            else if (m === "rewind")  { root.mode = "rewind"; if (arg) rewindPage.pickTab(arg) }
            else if (m === "ampy") root.mode = "ampy"
            else if (m === "features") root.mode = "features"
            else if (m === "radio") {
                if (arg) backend.openBeaconRadio(arg)
                root.mode = "radio"
            }
            else if (m === "artist") { if (arg) root.openArtist(arg, "") }
            else if (m === "discover") {
                root.mode = "home"
                homePage.openDiscoverLane(arg || "loved")
            }
            else root.mode = m
        }
    }
    Connections {
        target: eq
        function onErrorOccurred(msg) {
            console.warn("Ampere audio: " + msg)
        }
    }

    // mouse side buttons = history, like a browser. Only Back/Forward are
    // accepted, so every other click falls through to the page beneath.
    MouseArea {
        anchors.fill: parent
        z: 90
        acceptedButtons: Qt.BackButton | Qt.ForwardButton
        onClicked: (m) => m.button === Qt.BackButton ? root.goBack() : root.goForward()
    }

    // ---------- ambient overlay: above everything, incl. the bar ----------
    PageSlot {
        anchors.fill: parent
        z: 100
        // Prewarming constructs and decodes the room while its geometry is
        // frozen. It becomes the only active full-window tree before the
        // compositor starts the fullscreen transition.
        current: root.ambient

        Loader {
            id: ambientPresentation
            anchors.fill: parent
            active: root._ambientPrewarmed || root.ambient
            asynchronous: !root.ambient
            visible: root.ambient
            sourceComponent: AmbientView {
                anchors.fill: parent
                presentationActive: root.ambient
                resizeActive: root.windowGeometryChanging
                onClosed: root.leaveAmbient()
            }
        }
    }
}
