pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Search · Record Wall (design/SPEC.md rows "Search hierarchy" + "Search
// results"; canonical artboard `B · Record Wall`, DECISIONS 2026-08-20).
// One full-room Archive Wash instrument: a 420px best-match sleeve with its
// actions at left, the query headline + truthful counts, a sleeve row of
// matching albums and artists, and the song ledger beneath. The full list
// expands inside this room; async execution and result ownership stay intact.
Item {
    id: pop

    property string query: ""
    property int debounceInterval: 180
    property int songPreviewLimit: 4
    property var searchProvider: backend
    property var readinessProvider: backend
    // The test harness swaps in providers without the property; treat that as ready.
    readonly property bool libraryReady: readinessProvider
        && readinessProvider.libraryReady !== undefined ? readinessProvider.libraryReady : true
    property var actionProvider: backend
    property var bioProvider: backend
    property var allHits: []
    property var allSuggestions: []
    property var allAlbums: []
    property var allArtists: []
    property var lyricHits: []
    property bool lyricsPending: false
    property var best: null
    property var portraitKeys: ({})
    property var portraitRequests: ({})
    property bool artistFirst: false
    property string scheduledQuery: ""
    // The query the visible results belong to. Differs from `query` while
    // a newer request is in flight (S-07: stale content dims, never ghosts).
    property string resultsQuery: ""
    property string inFlightQuery: ""
    property int requestSerial: 0
    property int appliedSerial: 0
    property string failure: ""
    property bool expanded: false
    property bool sleevesExpanded: false
    property bool expandOnArrival: false
    property bool menuOnArrival: false
    property bool opened: false

    readonly property bool compact: width < 1000
    readonly property bool searchPending: searchDelay.running || inFlightQuery !== ""
    readonly property bool stale: resultsQuery !== "" && resultsQuery !== query.trim()
    readonly property bool hintOnly: query.trim().length === 1
    readonly property bool closestOnly: allHits.length === 0 && allSuggestions.length > 0
    readonly property var allDisplayedSongs: allHits.length ? allHits : allSuggestions
    readonly property var displayedSongs: expanded
        ? allDisplayedSongs : allDisplayedSongs.slice(0, songPreviewLimit)
    readonly property var sleeveItems: allAlbums.map(a => ({kind: "album", data: a}))
        .concat(allArtists.map(a => ({kind: "artist", data: a})))
    readonly property string bestKind: best && best.kind ? best.kind : ""
    readonly property var bestItem: best && best.item ? best.item : null
    readonly property bool bestExact: !best || best.exact !== false
    readonly property bool empty: resultsQuery !== "" && allDisplayedSongs.length === 0
        && allAlbums.length === 0 && allArtists.length === 0
    readonly property int sleeveSide: compact ? Math.min(260, width - 2 * gutter) : 420
    readonly property int gutter: compact ? 24 : Theme.pageGutter(width)

    signal openFolder(string path)
    signal openAlbum(string path, string album)
    signal openArtistPage(string name, string path)
    signal editTrack(var track)
    signal focusFieldRequested()
    signal queryCommitted(string query)
    signal closeRequested()

    visible: opened
    focus: false

    function open() { opened = true; }
    function close() { opened = false; }
    function copiedMap(source) {
        var copy = {};
        for (var key in source)
            copy[key] = source[key];
        return copy;
    }
    function plural(count, one, many) {
        return count === 0 ? "no " + many : count + " " + (count === 1 ? one : many);
    }
    function countsLine() {
        return plural(allDisplayedSongs.length, "song", "songs") + " · "
            + plural(allAlbums.length, "album", "albums") + " · "
            + plural(allArtists.length, "artist", "artists");
    }
    function artKey(file) {
        return file ? "image://art/" + encodeURIComponent(file) : "";
    }
    function portraitSource(artistName) {
        var key = portraitKeys[artistName] || "";
        return key ? "image://art/portrait:" + key : "";
    }
    function ensurePortrait(artistName) {
        artistName = String(artistName || "").trim();
        if (!artistName || portraitRequests[artistName])
            return;
        var requests = copiedMap(portraitRequests);
        requests[artistName] = true;
        portraitRequests = requests;
        if (bioProvider && typeof bioProvider.requestArtistBio === "function")
            bioProvider.requestArtistBio(artistName);
    }
    function requestVisiblePortraits() {
        for (var index = 0; index < allArtists.length; ++index)
            ensurePortrait(allArtists[index].name);
    }
    function fileDir(file) {
        var path = String(file || "");
        var cut = path.lastIndexOf("/");
        return cut > 0 ? path.substring(0, cut) : "";
    }
    function albumFiles(album) {
        if (!album || !actionProvider || typeof actionProvider.albumInfo !== "function")
            return [];
        var info = actionProvider.albumInfo(album.dir || "", album.album || "");
        var tracks = info && info.tracks ? info.tracks : [];
        return tracks.map(t => t.file);
    }
    function commit() {
        var trimmed = query.trim();
        if (trimmed.length >= 2)
            queryCommitted(trimmed);
    }
    // Iann verdict #2: a song activated from Search queues only that song.
    function activateSong(track) {
        if (!track || !track.file)
            return;
        actionProvider.playFiles([track.file], 0);
        commit();
        close();
        closeRequested();
    }
    function queueSong(track) {
        if (track && track.file && actionProvider.queuePath)
            actionProvider.queuePath(track.file);
    }
    function openSongAlbum(track) {
        if (!track || !track.file)
            return;
        commit();
        openAlbum(fileDir(track.file), track.album || "");
        close();
    }
    function activateAlbum(album) {
        if (!album)
            return;
        commit();
        openAlbum(album.dir || "", album.album || "");
        close();
    }
    function playAlbum(album) {
        var files = albumFiles(album);
        if (!files.length)
            return;
        actionProvider.playAlbum(files, 0);
        commit();
        close();
        closeRequested();
    }
    function queueAlbum(album) {
        var files = albumFiles(album);
        if (files.length)
            actionProvider.queueAlbum(files);
    }
    function activateArtist(artist) {
        if (!artist)
            return;
        commit();
        openArtistPage(artist.name || "", artist.path || "");
        close();
    }
    function activateBest() {
        if (bestKind === "song")
            activateSong(bestItem);
        else if (bestKind === "album")
            playAlbum(bestItem);
        else if (bestKind === "artist")
            activateArtist(bestItem);
    }
    function playFirst() { activateBest(); }
    // Iann verdict #1: Return in the field opens the full list, in the room.
    function expandAll() {
        if (resultsQuery === query.trim() && resultsQuery !== "") {
            expanded = true;
            commit();
        } else {
            expandOnArrival = true;
        }
    }
    function openFirstRowMenu() {
        var row = songRepeater.count > 0 ? songRepeater.itemAt(0) : null;
        if (row && resultsQuery === query.trim()) {
            menuOnArrival = false;
            row.openMenuAt(24, 64);
        } else {
            menuOnArrival = true;
        }
    }
    function clearResults() {
        allHits = [];
        allSuggestions = [];
        allAlbums = [];
        allArtists = [];
        lyricHits = [];
        lyricsPending = false;
        best = null;
        artistFirst = false;
        resultsQuery = "";
        inFlightQuery = "";
        failure = "";
        expanded = false;
        sleevesExpanded = false;
        expandOnArrival = false;
    }
    function scheduleRefresh() {
        var trimmed = query.trim();
        failure = "";
        if (trimmed !== resultsQuery) {
            expanded = false;
            sleevesExpanded = false;
            expandOnArrival = false;
        }
        if (trimmed.length < 2) {
            searchDelay.stop();
            scheduledQuery = "";
            inFlightQuery = "";
            // One character is a hint state, not blankness (S-15); the
            // room stays open to say so. Empty text keeps the last results
            // restored behind the history plane (verdict #5).
            if (trimmed.length === 0 && resultsQuery === "")
                close();
            else if (trimmed.length === 1)
                open();
            return;
        }
        scheduledQuery = trimmed;
        searchDelay.restart();
    }
    function requestRefresh(searchQuery) {
        if (searchQuery !== query.trim() || searchQuery.length < 2)
            return;
        requestSerial += 1;
        inFlightQuery = searchQuery;
        searchProvider.requestQuickSearch(searchQuery, requestSerial);
    }
    function retry() {
        var trimmed = query.trim();
        if (trimmed.length >= 2)
            requestRefresh(trimmed);
    }
    function applyResults(searchQuery, result) {
        if (searchQuery !== query.trim())
            return;
        // S-08: anything older than the newest issued request is stale,
        // even when its query text matches.
        var serial = Number(result && result.serial !== undefined ? result.serial : requestSerial);
        if (serial < requestSerial)
            return;
        appliedSerial = serial;
        allHits = result.hits || [];
        allSuggestions = result.suggestions || [];
        allAlbums = result.albums || [];
        allArtists = result.artists || [];
        lyricHits = result.lyrics || [];
        lyricsPending = result.lyricsPending === true;
        best = result.best || null;
        artistFirst = result.artistFirst === true;
        resultsQuery = searchQuery;
        inFlightQuery = "";
        failure = "";
        if (expandOnArrival) {
            expanded = true;
            expandOnArrival = false;
            commit();
        }
        requestVisiblePortraits();
        open();
        if (menuOnArrival)
            Qt.callLater(openFirstRowMenu);
    }
    function applyFailure(searchQuery, serial, reason) {
        if (searchQuery !== query.trim() || Number(serial) < appliedSerial)
            return;
        inFlightQuery = "";
        failure = reason || "search failed";
        open();
    }
    function bestTitle() {
        if (!bestItem)
            return "";
        if (bestKind === "song")
            return bestItem.title || "Untitled";
        if (bestKind === "album")
            return bestItem.album || "Untitled album";
        return bestItem.name || "Unknown artist";
    }
    function bestMeta() {
        if (!bestItem)
            return "";
        if (bestKind === "song") {
            var parts = [bestItem.artist || "", bestItem.album || "",
                         Theme.fmtTime(Number(bestItem.duration || 0)),
                         bestItem.format || ""];
            return parts.filter(p => p !== "").join(" · ");
        }
        if (bestKind === "album") {
            var count = Number(bestItem.trackCount || 0);
            var meta = [bestItem.artist || "", bestItem.year || "",
                        count ? count + (count === 1 ? " track" : " tracks") : ""];
            return meta.filter(p => p !== "").join(" · ");
        }
        return "Artist";
    }
    function bestArtwork() {
        if (!bestItem)
            return "";
        if (bestKind === "artist")
            return portraitSource(bestItem.name);
        if (bestKind === "album")
            return artKey(bestItem.cover);
        return artKey(bestItem.file);
    }
    function songSubLine(track) {
        var parts = [track.artist || "", track.album || ""];
        return parts.filter(p => p !== "").join(" · ");
    }

    // ---- flat keyboard walk (S-11): hero → sleeves → songs → ALL → lyrics
    function navItems() {
        var items = [];
        if (bestItem)
            items.push(hero);
        var sleeves = pop.sleevesExpanded ? sleeveGridRepeater : sleeveRepeater;
        for (var s = 0; s < sleeves.count; ++s)
            items.push(sleeves.itemAt(s));
        if (sleevesAllLink.visible)
            items.push(sleevesAllLink);
        for (var r = 0; r < songRepeater.count; ++r)
            items.push(songRepeater.itemAt(r));
        if (allLink.visible)
            items.push(allLink);
        for (var l = 0; l < lyricRepeater.count; ++l)
            items.push(lyricRepeater.itemAt(l));
        return items.filter(item => item !== null && item !== undefined);
    }
    function focusFirst() {
        var items = navItems();
        if (items.length)
            items[0].forceActiveFocus();
        else
            focusFieldRequested();
    }
    function focusRelative(item, step) {
        var items = navItems();
        var index = items.indexOf(item);
        if (index < 0)
            return;
        var next = index + step;
        if (next < 0) {
            focusFieldRequested();
            return;
        }
        if (next >= items.length)
            return;
        items[next].forceActiveFocus();
    }
    function ensureVisible(item) {
        if (!item)
            return;
        var top = item.mapToItem(content, 0, 0).y + content.y;
        var bottom = top + item.height;
        if (top < roomFlick.contentY)
            roomFlick.contentY = Math.max(0, top - 24);
        else if (bottom > roomFlick.contentY + roomFlick.height)
            roomFlick.contentY = Math.min(
                Math.max(0, roomFlick.contentHeight - roomFlick.height),
                bottom - roomFlick.height + 24);
    }

    onQueryChanged: scheduleRefresh()

    Timer {
        id: searchDelay
        interval: pop.debounceInterval
        repeat: false
        onTriggered: pop.requestRefresh(pop.scheduledQuery)
    }
    Connections {
        target: pop.searchProvider
        ignoreUnknownSignals: true
        function onQuickSearchReady(searchQuery, result) {
            pop.applyResults(searchQuery, result);
        }
        function onQuickSearchFailed(searchQuery, serial, reason) {
            pop.applyFailure(searchQuery, serial, reason);
        }
        // The optional lyric index finishing changes what this query can
        // show (S-19): re-ask once, quietly, without a loading flip.
        function onLyricsIndexChanged() {
            if (pop.lyricsPending && pop.resultsQuery !== "")
                pop.retry();
        }
    }
    Connections {
        target: pop.bioProvider
        ignoreUnknownSignals: true
        function onArtistBioReady(artistName, info) {
            if (!pop.portraitRequests[artistName])
                return;
            var portraits = pop.copiedMap(pop.portraitKeys);
            portraits[artistName] = info && info.portrait ? info.portrait : "";
            pop.portraitKeys = portraits;
        }
    }

    // ---- shared pieces -----------------------------------------------------

    component LedCaps: Text {
        color: Theme.washFaint
        font.family: Theme.displayFont
        font.pixelSize: Theme.fsMicro
        font.letterSpacing: 3
        font.capitalization: Font.AllUppercase
        elide: Text.ElideRight
    }

    component ActionLink: Item {
        id: link
        property string label: ""
        property bool primaryAction: false
        signal activated()
        width: linkText.implicitWidth
        height: 20
        LedCaps {
            id: linkText
            text: link.label
            color: link.primaryAction || linkHover.hovered ? Theme.washInk : Theme.washMuted
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: linkText.bottom
            anchors.topMargin: 3
            height: 1
            visible: link.primaryAction
            color: Theme.washInk
        }
        HoverHandler { id: linkHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: link.activated() }
    }

    component Statement: Text {
        width: parent ? parent.width : implicitWidth
        color: Theme.washFaint
        font.family: Theme.font
        font.pixelSize: Theme.fsSmall
        wrapMode: Text.Wrap
    }

    // One album / artist sleeve tile (150px, artboard B sleeve row).
    component SleeveTile: Item {
        id: tile
        required property var modelData
        required property int index
        readonly property string kind: modelData.kind
        readonly property var rowData: modelData.data
        readonly property string titleText: kind === "album"
            ? rowData.album || "Untitled album" : rowData.name || "Unknown artist"
        readonly property string subText: kind === "artist" ? "Artist"
            : (rowData.artist || "") + " · " + (rowData.nameMatch
                ? "Album"
                : pop.plural(Number(rowData.matchingSongs || 0),
                             "matching song", "matching songs"))

        function activate() {
            if (kind === "album")
                pop.activateAlbum(rowData);
            else
                pop.activateArtist(rowData);
        }

        width: 150
        height: 150 + 8 + tileTitle.height + tileSub.height
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Open " + kind + " " + titleText
        Accessible.onPressAction: activate()
        Keys.onReturnPressed: activate()
        Keys.onSpacePressed: activate()
        Keys.onDownPressed: pop.focusRelative(tile, 1)
        Keys.onUpPressed: pop.focusRelative(tile, -1)
        Keys.onEscapePressed: pop.focusFieldRequested()
        onActiveFocusChanged: if (activeFocus) pop.ensureVisible(tile)

        MediaArtwork {
            id: tileArt
            width: 150
            height: 150
            kind: tile.kind
            source: tile.kind === "artist"
                ? pop.portraitSource(tile.rowData.name) : pop.artKey(tile.rowData.cover)
        }
        Rectangle {
            anchors.fill: tileArt
            color: "transparent"
            border.width: tile.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        Text {
            id: tileTitle
            anchors.top: tileArt.bottom
            anchors.topMargin: 8
            width: parent.width
            text: tile.titleText
            color: tile.activeFocus ? Theme.primary : Theme.washInk
            font.family: Theme.font
            font.pixelSize: 14
            elide: Text.ElideRight
        }
        Text {
            id: tileSub
            anchors.top: tileTitle.bottom
            width: parent.width
            text: tile.subText
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.washSub
            elide: Text.ElideRight
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: tile.activate() }
    }

    // One song row (artboard B ledger: 44px sleeve · title / artist · album ·
    // duration). Right-click opens the shared track menu (verdict #7).
    component SongRow: Item {
        id: songRow
        required property var modelData
        required property int index
        property bool lyric: false
        readonly property var rowData: modelData
        readonly property string titleText: rowData.title || "Untitled"
        readonly property string versionText: rowData.disambiguate && rowData.format
            ? "  · " + rowData.format + " version" : ""
        readonly property string subText: lyric && rowData.snippet
            ? rowData.snippet : pop.songSubLine(rowData)

        function activate() { pop.activateSong(rowData); }
        function openMenuAt(x, y) { rowMenu.openAt(songRow, x, y); }

        width: parent ? parent.width : 0
        height: 64
        activeFocusOnTab: true
        Accessible.role: Accessible.ButtonMenu
        Accessible.name: "Play " + titleText + (rowData.artist ? " by " + rowData.artist : "")
        Accessible.description: "Track actions menu; Enter or Space plays this song"
        Accessible.onPressAction: openMenuAt(24, songRow.height)
        Keys.onReturnPressed: activate()
        Keys.onSpacePressed: activate()
        Keys.onDownPressed: pop.focusRelative(songRow, 1)
        Keys.onUpPressed: pop.focusRelative(songRow, -1)
        Keys.onEscapePressed: pop.focusFieldRequested()
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Menu
                    || (event.key === Qt.Key_F10
                        && (event.modifiers & Qt.ShiftModifier))) {
                openMenuAt(24, songRow.height);
                event.accepted = true;
            }
        }
        onActiveFocusChanged: if (activeFocus) pop.ensureVisible(songRow)

        Rectangle {
            anchors.fill: parent
            color: rowHover.hovered ? Qt.alpha(Theme.washInk, 0.045) : "transparent"
            border.width: songRow.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        MediaArtwork {
            id: rowArt
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 44
            height: 44
            kind: "song"
            source: pop.artKey(songRow.rowData.file)
        }
        Column {
            anchors.left: rowArt.right
            anchors.leftMargin: 18
            anchors.right: rowDuration.left
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                width: parent.width
                textFormat: Text.StyledText
                text: songRow.titleText.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                    + (songRow.versionText
                       ? "<font color=\"" + Theme.washFaint + "\">"
                         + songRow.versionText + "</font>" : "")
                color: songRow.activeFocus ? Theme.primary : Theme.washInk
                font.family: Theme.font
                font.pixelSize: Theme.washBody
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: songRow.subText
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.washSub
                elide: Text.ElideRight
            }
        }
        Text {
            id: rowDuration
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 60
            text: Theme.fmtTime(Number(songRow.rowData.duration || 0))
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: 12
            font.letterSpacing: 1
            horizontalAlignment: Text.AlignRight
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.washHair
        }
        TrackActionMenu {
            id: rowMenu
            trackData: songRow.rowData
            onPlayNow: songRow.activate()
            onEditRequested: track => pop.editTrack(track)
        }
        HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: mouse => {
                if (mouse.button === Qt.RightButton)
                    songRow.openMenuAt(mouse.x, mouse.y);
                else
                    songRow.activate();
            }
        }
    }

    // ---- the room -----------------------------------------------------------

    Flickable {
        id: roomFlick
        anchors.fill: parent
        clip: true
        contentHeight: content.height + content.y + 36
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ArchiveScrollBar {}

        Item {
            id: content
            x: pop.gutter
            y: pop.compact ? 20 : 36
            width: roomFlick.width - x * 2
            height: pop.compact
                ? (hero.visible ? bestColumn.height + 28 : 0) + resultsColumn.height
                : Math.max(bestColumn.height, resultsColumn.height)
            opacity: pop.stale && pop.inFlightQuery !== "" ? 0.45 : 1
            Behavior on opacity { NumberAnimation { duration: 140 } }

            // ---- best match (left column desktop · top compact) ----
            Item {
                id: hero
                objectName: "searchBestMatch"
                visible: pop.bestItem !== null && !pop.hintOnly
                width: pop.compact ? content.width : 420
                height: bestColumn.height
                activeFocusOnTab: pop.bestItem !== null
                Accessible.role: Accessible.Button
                Accessible.name: (pop.bestKind === "song" ? "Play best match "
                    : pop.bestKind === "album" ? "Play best match album "
                    : "Open best match artist ") + pop.bestTitle()
                Accessible.onPressAction: pop.activateBest()
                Keys.onReturnPressed: pop.activateBest()
                Keys.onSpacePressed: pop.activateBest()
                Keys.onDownPressed: pop.focusRelative(hero, 1)
                Keys.onUpPressed: pop.focusRelative(hero, -1)
                Keys.onEscapePressed: pop.focusFieldRequested()
                onActiveFocusChanged: if (activeFocus) pop.ensureVisible(hero)

                Column {
                    id: bestColumn
                    width: parent.width
                    spacing: 0
                    LedCaps {
                        objectName: "searchBestEyebrow"
                        width: parent.width
                        bottomPadding: 18
                        text: (pop.bestExact ? "Best match" : "Closest match")
                            + " · " + pop.bestKind
                        color: Theme.primary
                    }
                    Item {
                        width: pop.sleeveSide
                        height: pop.sleeveSide
                        MediaArtwork {
                            anchors.fill: parent
                            kind: pop.bestKind === "artist" ? "artist" : pop.bestKind
                            source: pop.bestArtwork()
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: hero.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: pop.activateBest() }
                    }
                    Text {
                        objectName: "searchBestTitle"
                        width: parent.width
                        topPadding: 18
                        text: pop.bestTitle()
                        color: hero.activeFocus ? Theme.primary : Theme.washInk
                        font.family: Theme.displayFont
                        font.pixelSize: pop.compact ? 28 : 40
                        font.weight: Font.Normal
                        lineHeight: 1.05
                        wrapMode: Text.Wrap
                    }
                    Text {
                        width: parent.width
                        topPadding: 10
                        text: pop.bestMeta()
                        color: Theme.washMuted
                        font.family: Theme.font
                        font.pixelSize: 14
                        wrapMode: Text.Wrap
                    }
                    Row {
                        spacing: 28
                        topPadding: 24
                        ActionLink {
                            visible: pop.bestKind !== ""
                            primaryAction: true
                            label: pop.bestKind === "song" ? "Play →"
                                : pop.bestKind === "album" ? "Play album →" : "Open artist →"
                            onActivated: pop.activateBest()
                        }
                        ActionLink {
                            visible: pop.bestKind === "song" || pop.bestKind === "album"
                            label: "Queue"
                            onActivated: pop.bestKind === "song"
                                ? pop.queueSong(pop.bestItem) : pop.queueAlbum(pop.bestItem)
                        }
                        ActionLink {
                            visible: pop.bestKind === "song" || pop.bestKind === "album"
                            label: "Open"
                            onActivated: pop.bestKind === "song"
                                ? pop.openSongAlbum(pop.bestItem) : pop.activateAlbum(pop.bestItem)
                        }
                    }
                }
                HoverHandler {
                    enabled: pop.bestItem !== null
                    cursorShape: Qt.PointingHandCursor
                }
                // The whole sleeve is the entrance, exactly as the eyebrow,
                // the cursor and Accessible.onPressAction already promised:
                // a song plays, an album plays, an artist opens. Before this
                // the art showed a pointing hand and did nothing on click.
                TapHandler {
                    enabled: pop.bestItem !== null
                    onTapped: pop.activateBest()
                }
            }

            // ---- headline · counts · sleeve row · ledger ----
            Column {
                id: resultsColumn
                x: pop.compact ? 0 : 420 + 64
                y: pop.compact && hero.visible ? bestColumn.height + 28 : 0
                width: pop.compact ? content.width : content.width - x
                spacing: 0

                Item {
                    width: parent.width
                    height: headline.height
                    Text {
                        id: headline
                        objectName: "searchHeadline"
                        width: Math.min(implicitWidth, parent.width)
                        text: pop.query.trim()
                        color: Theme.washInk
                        font.family: Theme.displayFont
                        font.pixelSize: pop.compact ? 44 : 56
                        font.weight: Font.Light
                        lineHeight: 1
                        elide: Text.ElideRight
                    }
                    LedCaps {
                        objectName: "searchCountsLine"
                        anchors.left: headline.right
                        anchors.leftMargin: 22
                        anchors.right: parent.right
                        anchors.baseline: headline.baseline
                        text: pop.hintOnly ? "Type at least 2 characters"
                            : pop.failure !== "" ? "Search failed"
                            : pop.inFlightQuery !== "" ? "Searching the archive…"
                            : pop.resultsQuery !== "" ? pop.countsLine() : ""
                    }
                }
                Item { width: 1; height: 22 }
                Rectangle { width: parent.width; height: 1; color: Theme.washHair }

                // failure (S-06) · hint (S-15) · empty
                Item {
                    id: failureRow
                    width: parent.width
                    // Both rows bind to the CONDITION, never to each other:
                    // a parent whose visibility read its child's deadlocked
                    // at false, because a child's effective visibility
                    // already includes its parent's. The failure line could
                    // never appear (found 2026-08-23).
                    height: pop.failure !== "" ? 64 : 0
                    visible: pop.failure !== ""
                    Text {
                        id: failureLine
                        objectName: "searchFailureLine"
                        visible: pop.failure !== ""
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Search failed — try again"
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                    }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: pop.retry() }
                }
                Statement {
                    visible: pop.hintOnly
                    topPadding: 24
                    text: "Type at least 2 characters to search the archive."
                }
                ArchiveLoading {
                    objectName: "searchArchiveLoading"
                    visible: pop.empty && !pop.hintOnly && pop.failure === "" && !pop.libraryReady
                    topPadding: 24
                }
                Statement {
                    objectName: "searchEmptyStatement"
                    visible: pop.empty && !pop.hintOnly && pop.failure === "" && pop.libraryReady
                    topPadding: 24
                    text: "Nothing in the archive matches “" + pop.resultsQuery + "”."
                }

                // ---- ALBUMS & ARTISTS sleeve row ----
                Item {
                    width: parent.width
                    height: 24 + 14 + 14
                    visible: pop.resultsQuery !== "" && !pop.empty && !pop.hintOnly
                    LedCaps {
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 14
                        text: "Albums & artists"
                    }
                    Item {
                        id: sleevesAllLink
                        objectName: "searchSleevesAllLink"
                        visible: !pop.sleevesExpanded && sleeveRow.contentWidth > sleeveRow.width + 1
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 14
                        width: sleevesAllText.implicitWidth
                        height: sleevesAllText.height
                        activeFocusOnTab: visible
                        Accessible.role: Accessible.Button
                        Accessible.name: "Show all " + pop.sleeveItems.length + " albums and artists"
                        Accessible.onPressAction: pop.sleevesExpanded = true
                        Keys.onReturnPressed: pop.sleevesExpanded = true
                        Keys.onSpacePressed: pop.sleevesExpanded = true
                        Keys.onDownPressed: pop.focusRelative(sleevesAllLink, 1)
                        Keys.onUpPressed: pop.focusRelative(sleevesAllLink, -1)
                        Keys.onEscapePressed: pop.focusFieldRequested()
                        LedCaps {
                            id: sleevesAllText
                            text: "All " + pop.sleeveItems.length + " →"
                            color: sleevesAllLink.activeFocus || sleevesAllHover.hovered
                                ? Theme.washInk : Theme.primary
                        }
                        HoverHandler { id: sleevesAllHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: pop.sleevesExpanded = true }
                    }
                }
                Statement {
                    objectName: "searchSleeveEmpty"
                    visible: pop.resultsQuery !== "" && !pop.empty && !pop.hintOnly
                        && pop.sleeveItems.length === 0
                    text: "No albums or artists match “" + pop.resultsQuery + "”."
                }
                Item {
                    width: parent.width
                    visible: pop.sleeveItems.length > 0 && !pop.hintOnly
                    height: visible ? (pop.sleevesExpanded ? sleeveGrid.height : sleeveRowContent.height) : 0

                    // collapsed: one horizontal lane that flicks, with a fade
                    // at the right edge while more tiles remain
                    Flickable {
                        id: sleeveRow
                        objectName: "searchSleeveRow"
                        visible: !pop.sleevesExpanded
                        width: parent.width
                        height: sleeveRowContent.height
                        contentWidth: sleeveRowContent.width
                        clip: true
                        flickableDirection: Flickable.HorizontalFlick
                        boundsBehavior: Flickable.StopAtBounds
                        Row {
                            id: sleeveRowContent
                            spacing: 22
                            Repeater {
                                id: sleeveRepeater
                                model: pop.sleevesExpanded ? [] : pop.sleeveItems
                                delegate: SleeveTile {}
                            }
                        }
                    }
                    Rectangle {
                        objectName: "searchSleeveFade"
                        visible: !pop.sleevesExpanded
                            && sleeveRow.contentX + sleeveRow.width < sleeveRow.contentWidth - 1
                        anchors.right: parent.right
                        anchors.top: parent.top
                        width: 72
                        height: 150
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: Qt.alpha(Theme.bg, 0.0) }
                            GradientStop { position: 1.0; color: Theme.bg }
                        }
                    }

                    // expanded: every album and artist tile, wrapping in place
                    Flow {
                        id: sleeveGrid
                        objectName: "searchSleeveGrid"
                        visible: pop.sleevesExpanded
                        width: parent.width
                        spacing: 22
                        Repeater {
                            id: sleeveGridRepeater
                            model: pop.sleevesExpanded ? pop.sleeveItems : []
                            delegate: SleeveTile {}
                        }
                    }
                }

                // ---- SONGS ledger ----
                Item {
                    width: parent.width
                    height: 34 + 20
                    visible: pop.resultsQuery !== "" && !pop.empty && !pop.hintOnly
                    LedCaps {
                        objectName: "searchSongsHeader"
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        text: (pop.closestOnly ? "Closest songs" : "Songs")
                            + " · " + pop.allDisplayedSongs.length
                    }
                    Item {
                        id: allLink
                        objectName: "searchAllLink"
                        visible: !pop.expanded
                            && pop.allDisplayedSongs.length > pop.songPreviewLimit
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        width: allText.implicitWidth
                        height: allText.height
                        activeFocusOnTab: visible
                        Accessible.role: Accessible.Button
                        Accessible.name: "Show all " + pop.allDisplayedSongs.length + " songs"
                        Accessible.onPressAction: pop.expandAll()
                        Keys.onReturnPressed: pop.expandAll()
                        Keys.onSpacePressed: pop.expandAll()
                        Keys.onDownPressed: pop.focusRelative(allLink, 1)
                        Keys.onUpPressed: pop.focusRelative(allLink, -1)
                        Keys.onEscapePressed: pop.focusFieldRequested()
                        LedCaps {
                            id: allText
                            text: "All " + pop.allDisplayedSongs.length + " →"
                            color: allLink.activeFocus || allHover.hovered
                                ? Theme.washInk : Theme.primary
                        }
                        HoverHandler { id: allHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: pop.expandAll() }
                    }
                }
                Column {
                    id: songLedger
                    objectName: "songsLedger"
                    width: parent.width
                    Repeater {
                        id: songRepeater
                        model: pop.displayedSongs
                        delegate: SongRow {}
                    }
                }
                Statement {
                    objectName: "searchSongsEmpty"
                    visible: pop.resultsQuery !== "" && !pop.empty && !pop.hintOnly
                        && pop.allDisplayedSongs.length === 0
                    topPadding: 8
                    text: "No songs match “" + pop.resultsQuery + "”."
                }

                // ---- LYRICS (S-19): quiet while indexing, a ledger when ready ----
                LedCaps {
                    visible: pop.lyricsPending && pop.resultsQuery.length >= 3
                        && !pop.hintOnly && pop.failure === ""
                    topPadding: 28
                    text: "Lyrics indexing…"
                }
                LedCaps {
                    visible: pop.lyricHits.length > 0 && !pop.hintOnly
                    topPadding: 34
                    bottomPadding: 6
                    text: "Lyrics · " + pop.lyricHits.length
                }
                Column {
                    objectName: "lyricsLedger"
                    width: parent.width
                    Repeater {
                        id: lyricRepeater
                        model: pop.lyricHits
                        delegate: SongRow { lyric: true }
                    }
                }
            }
        }
    }
}
