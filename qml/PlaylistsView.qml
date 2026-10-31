import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// Sequence Shelves — LibraryView owns the Open Room Index and active
// destination. The wall occupies that room's right-hand shelf; selecting a
// sequence promotes this same local owner into the complete Library workspace.
// It never creates another route, frame, or navigation rail.
Item {
    id: view

    property var playlistNames: backend.playlists
    property bool filterActive: false
    property bool compact: width < 720
    property string selected: ""       // "" = all Sequence Shelves
    property var tracks: []
    property bool loading: false
    property string loadError: ""
    property var covers: ({})
    property var playCounts: backend.playlistPlayCounts
    property string sortKey: "playlist"
    property bool sortDescending: false
    readonly property var sortOptions: [
        { id: "playlist", label: "Playlist order" },
        { id: "title", label: "Title" },
        { id: "artist", label: "Artist" },
        { id: "added", label: "Date added" }
    ]
    readonly property var displayTracks: {
        var rows = tracks.slice()
        if (sortKey === "playlist") {
            if (sortDescending)
                rows.reverse()
            return rows
        }
        var direction = sortDescending ? -1 : 1
        rows.sort(function(a, b) {
            var result = 0
            if (sortKey === "added") {
                result = Number(a.added || 0) - Number(b.added || 0)
            } else {
                var x = String(a[sortKey] || "").toLocaleLowerCase()
                var y = String(b[sortKey] || "").toLocaleLowerCase()
                result = x.localeCompare(y)
            }
            if (result === 0)
                result = Number(a.playlistPos || 0)
                       - Number(b.playlistPos || 0)
            return direction * result
        })
        return rows
    }
    readonly property var fileList: displayTracks.map(function(track) {
        return track.file
    })
    readonly property real totalSeconds: tracks.reduce(function(total, track) {
        return total + (track.duration || 0)
    }, 0)
    readonly property var selectedCovers: {
        var known = covers[selected] || []
        if (known.length)
            return known
        return tracks.slice(0, 4).map(function(track) { return track.file })
    }

    function durationLabel() {
        var minutes = Math.round(totalSeconds / 60)
        return tracks.length + " track" + (tracks.length === 1 ? "" : "s")
             + (minutes > 0 ? " · " + minutes + " minutes" : "")
    }

    function sortLabel() {
        for (var i = 0; i < sortOptions.length; ++i)
            if (sortOptions[i].id === sortKey)
                return sortOptions[i].label
        return "Playlist order"
    }

    function chooseSort(key) {
        sortKey = key
    }

    function toggleSortDirection() {
        sortDescending = !sortDescending
    }

    function sortDirectionName() {
        return sortDescending ? "reverse" : "forward"
    }

    function openPlaylist(name) {
        name = String(name || "")
        if (!name)
            return
        selected = name
        tracks = backend.playlistTracks(name)
        loading = true
        loadError = ""
    }

    function showAll() {
        selected = ""
        tracks = []
        loading = false
        loadError = ""
    }

    function reloadSelected() {
        if (!selected)
            return
        tracks = backend.playlistTracks(selected)
        loading = true
        loadError = ""
    }

    function refreshCovers() {
        covers = backend.playlistCovers()
        backend.requestPlaylistCovers()
    }

    onVisibleChanged: if (visible) refreshCovers()

    Connections {
        target: backend

        function onPlaylistsChanged() {
            if (view.selected && backend.playlists.indexOf(view.selected) < 0)
                view.showAll()
            else
                view.reloadSelected()
            if (view.visible)
                backend.requestPlaylistCovers()
        }

        function onPlaylistCoversChanged() {
            view.covers = backend.playlistCovers()
        }

        function onPlaylistTracksReady(name, rows, success) {
            if (name !== view.selected)
                return
            view.tracks = rows
            view.loading = false
            view.loadError = success ? ""
                                     : "This sequence could not be opened. Your library is unchanged."
        }
    }

    component Mosaic: Grid {
        id: mosaic
        property var files: []
        property real side: 120
        readonly property int cell: Math.floor((side - spacing) / 2)
        columns: 2
        spacing: 2
        width: side
        height: side

        Repeater {
            model: 4
            delegate: MediaArtwork {
                required property int index
                width: mosaic.cell
                height: mosaic.cell
                kind: "album"
                source: index < mosaic.files.length
                        ? "image://art/" + encodeURIComponent(mosaic.files[index])
                        : ""
            }
        }
    }

    PlaylistSequenceStage {
        id: sequenceStage
        visible: view.selected === ""
        anchors.fill: parent
        playlistNames: view.playlistNames
        covers: view.covers
        playCounts: view.playCounts
        compact: view.compact
        onOpenPlaylist: name => view.openPlaylist(name)
    }

    // Sequence Measure: every five records repeat one large four-sleeve shelf,
    // two stacked small shelves, and two medium shelves. Odd measures mirror
    // without changing saved/sorted sequence order.
    ListView {
        id: variedWall
        objectName: "playlistWallRetiredVaried"
        visible: false
        anchors.fill: parent
        clip: true
        model: 0
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: view.compact ? 14 : 28
        ScrollBar.vertical: ArchiveScrollBar {}
        readonly property int measureSize: 5
        readonly property int measureCount: model
        readonly property int cols: view.compact ? 2 : 3

        onModelChanged: Qt.callLater(function() {
            if (variedWall.visible)
                variedWall.positionViewAtBeginning()
        })

        delegate: Item {
            id: measure
            required property int index
            objectName: "playlistVariedMeasure_" + index
            width: variedWall.width
            height: view.compact ? 464 : Math.max(520, variedWall.height)
            readonly property int baseIndex: index * 5
            readonly property int visibleCount: Math.min(
                5, Math.max(0, view.playlistNames.length - baseIndex))
            readonly property bool mirrored: index % 2 === 1
            readonly property real gap: view.compact ? 12 : 16
            readonly property real heroWidth: view.compact
                ? width : Math.floor(width * 0.58)
            readonly property real heroHeight: view.compact ? 180 : 280
            readonly property real smallWidth: view.compact
                ? Math.floor((width - gap) / 2)
                : width - heroWidth - gap
            readonly property real smallHeight: view.compact ? 130
                : Math.floor((heroHeight - gap) / 2)
            readonly property real mediumHeight: view.compact ? 130 : 178
            readonly property real heroY: view.compact ? 0
                : Math.max(0, Math.floor((height - heroHeight) / 2))
            readonly property real lowerY: view.compact
                ? heroHeight + gap + smallHeight + gap
                : height - mediumHeight - 2

            function nameAt(localIndex) {
                return view.playlistNames[baseIndex + localIndex] || ""
            }
            function cardX(localIndex) {
                if (view.compact) {
                    if (localIndex === 0) return 0
                    return ((localIndex - 1) % 2) * (smallWidth + gap)
                }
                if (localIndex === 0)
                    return mirrored ? width - heroWidth : 0
                if (localIndex <= 2)
                    return mirrored ? 0 : heroWidth + gap
                return (localIndex - 3)
                    * (Math.floor((width - gap) / 2) + gap)
            }
            function cardY(localIndex) {
                if (view.compact) {
                    if (localIndex === 0) return 0
                    if (localIndex <= 2) return heroHeight + gap
                    return lowerY
                }
                if (localIndex === 0) return heroY
                if (localIndex <= 2)
                    return (localIndex - 1) * (smallHeight + gap)
                return lowerY
            }
            function cardWidth(localIndex) {
                if (view.compact)
                    return localIndex === 0 ? width : smallWidth
                if (localIndex === 0) return heroWidth
                if (localIndex <= 2) return smallWidth
                return Math.floor((width - gap) / 2)
            }
            function cardHeight(localIndex) {
                if (localIndex === 0) return heroHeight
                if (localIndex <= 2) return smallHeight
                return mediumHeight
            }

            Repeater {
                model: measure.visibleCount
                delegate: Item {
                    id: variedCard
                    required property int index
                    readonly property int globalIndex: measure.baseIndex + index
                    readonly property string sequenceName: measure.nameAt(index)
                    readonly property var art: view.covers[sequenceName] || []
                    readonly property real artSide: Math.max(72, Math.min(
                        width - (view.compact ? 8 : 16), height - 34))
                    objectName: "playlistSequence_" + globalIndex
                    x: measure.cardX(index)
                    y: measure.cardY(index)
                    width: measure.cardWidth(index)
                    height: measure.cardHeight(index)
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: sequenceName
                    Accessible.description: "Open playlist in this Library shelf"
                    Accessible.onPressAction: view.openPlaylist(sequenceName)
                    Keys.onReturnPressed: view.openPlaylist(sequenceName)
                    Keys.onSpacePressed: view.openPlaylist(sequenceName)

                    Item {
                        anchors.fill: parent
                        y: variedCardHover.hovered ? -4 : 0
                        Behavior on y {
                            NumberAnimation { duration: Theme.motionFast }
                        }

                        Mosaic {
                            id: variedCardMosaic
                            files: variedCard.art
                            side: variedCard.artSide
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: variedCardMosaic.bottom
                            anchors.topMargin: 8
                            text: variedCard.sequenceName
                            elide: Text.ElideRight
                            color: variedCardHover.hovered
                                   || variedCard.activeFocus
                                   ? Theme.washInk
                                   : Qt.alpha(Theme.washInk, 0.92)
                            font.family: Theme.font
                            font.pixelSize: variedCard.index === 0
                                ? Theme.fsTitle : Theme.washBody
                            font.weight: Font.Light
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: variedCardTap.pressed
                               ? Qt.alpha(Theme.washInk, 0.08) : "transparent"
                        border.width: variedCard.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                    }
                    HoverHandler {
                        id: variedCardHover
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler {
                        id: variedCardTap
                        onTapped: view.openPlaylist(variedCard.sequenceName)
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
    }

    // Retained inertly for one correction migration pass. Sequence Measure is
    // the sole live collection owner.
    GridView {
        id: wall
        objectName: "playlistWallRetired"
        visible: false
        anchors.fill: parent
        clip: true
        model: []
        readonly property int cols: view.compact
                                    ? 2 : Math.max(2, Math.floor(width / 230))
        cellWidth: Math.floor(width / cols)
        cellHeight: Math.max(174, cellWidth - 24 + 46)
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: cellHeight * 2
        ScrollBar.vertical: ArchiveScrollBar {}

        delegate: Item {
            id: card
            objectName: "playlistSequence_" + index
            required property string modelData
            required property int index
            width: wall.cellWidth
            height: wall.cellHeight
            readonly property var art: view.covers[modelData] || []
            readonly property real artSide: Math.max(112, Math.min(
                width - (view.compact ? 12 : 22), height - 50))
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: modelData
            Accessible.description: "Open playlist in this Library shelf"
            Accessible.onPressAction: view.openPlaylist(modelData)
            Keys.onReturnPressed: view.openPlaylist(modelData)
            Keys.onSpacePressed: view.openPlaylist(modelData)

            Item {
                anchors.fill: parent
                anchors.rightMargin: view.compact ? 10 : 20
                y: cardHover.hovered ? -4 : 0
                Behavior on y {
                    NumberAnimation { duration: Theme.motionFast }
                }

                Mosaic {
                    id: cardMosaic
                    files: card.art
                    side: card.artSide
                }

                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: cardMosaic.bottom
                    anchors.topMargin: 10
                    text: card.modelData
                    elide: Text.ElideRight
                    color: cardHover.hovered || card.activeFocus
                           ? Theme.washInk : Qt.alpha(Theme.washInk, 0.92)
                    font.family: Theme.font
                    font.pixelSize: Theme.washBody
                    font.weight: Font.Light
                }
            }

            Rectangle {
                anchors.fill: parent
                anchors.rightMargin: view.compact ? 8 : 18
                color: cardTap.pressed
                       ? Qt.alpha(Theme.washInk, 0.08) : "transparent"
                border.width: card.activeFocus ? 1 : 0
                border.color: Theme.focusRing
            }
            HoverHandler {
                id: cardHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                id: cardTap
                onTapped: view.openPlaylist(card.modelData)
            }
        }
    }

    Column {
        objectName: "playlistEmptyState"
        visible: view.selected === "" && view.playlistNames.length === 0
                 && !view.filterActive
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: 10

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: "No saved sequences yet"
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: Theme.fsTitle
            font.weight: Font.Light
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Saved playlists will appear here as four-sleeve shelves."
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.washSub
        }
    }

    // Selected sequence: this same local owner expands to the complete Library
    // workspace. Sleeve Stream rows make exact record identity the primary
    // retrieval instrument instead of reducing the playlist to a ledger.
    Item {
        id: detail
        objectName: "playlistDetail"
        visible: view.selected !== ""
        anchors.fill: parent

        Item {
            id: detailHeader
            objectName: "playlistDetailHeader"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: view.compact ? 266 : 264

            WashLine {
                id: allSequences
                objectName: "playlistAllSequences"
                anchors.left: parent.left
                anchors.top: parent.top
                label: "← All sequences"
                Accessible.description: "Return to every playlist in this Library room"
                onActivated: view.showAll()
            }

            Mosaic {
                id: selectedMosaic
                objectName: "playlistSelectedMosaic"
                anchors.left: parent.left
                anchors.top: allSequences.bottom
                anchors.topMargin: 4
                files: view.selectedCovers
                side: view.compact ? 132 : 212
            }

            Column {
                id: sequenceIdentity
                objectName: "playlistSequenceIdentity"
                anchors.left: selectedMosaic.right
                anchors.leftMargin: view.compact ? 16 : 24
                anchors.top: selectedMosaic.top
                width: Math.max(0, parent.width - x)
                spacing: view.compact ? 5 : 7

                Text {
                    width: parent.width
                    text: "SELECTED SEQUENCE"
                    color: Theme.primary
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.2
                    font.capitalization: Font.AllUppercase
                }

                Text {
                    width: parent.width
                    text: view.selected
                    elide: Text.ElideRight
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: view.compact ? 24 : 38
                    font.weight: Font.Light
                }
                Text {
                    width: parent.width
                    text: view.loading && view.tracks.length === 0
                          ? "Loading…"
                          : view.durationLabel()
                    elide: Text.ElideRight
                    color: Theme.washMuted
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 1.8
                    font.capitalization: Font.AllUppercase
                }
            }

            Item {
                id: controlSuite
                objectName: "playlistControlSuite"
                anchors.left: view.compact ? parent.left : sequenceIdentity.left
                anchors.top: view.compact ? selectedMosaic.bottom
                                          : sequenceIdentity.bottom
                anchors.topMargin: view.compact ? 14 : 16
                width: view.compact ? parent.width
                                    : Math.min(448, parent.width - x)
                height: 64

                Column {
                    id: sortGroup
                    anchors.left: parent.left
                    anchors.top: parent.top
                    width: view.compact ? 216 : 220
                    spacing: 5

                    Text {
                        text: "SORT"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 1.8
                        font.capitalization: Font.AllUppercase
                    }
                    Row {
                        width: parent.width
                        height: 44
                        spacing: 4

                        Item {
                            id: sortPicker
                            objectName: "playlistSortPicker"
                            width: parent.width - sortDirection.width - parent.spacing
                            height: 44
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Sort by " + view.sortLabel()
                            Accessible.description: "Choose the playlist sort field"
                            Accessible.onPressAction: sortPicker.openMenu()
                            Keys.onReturnPressed: openMenu()
                            Keys.onEnterPressed: openMenu()
                            Keys.onSpacePressed: openMenu()

                            function openMenu() {
                                sortMenu.popupAt(sortPicker, 0,
                                                 sortPicker.height + 6)
                            }

                            Rectangle {
                                anchors.fill: parent
                                color: sortTap.pressed
                                       ? Qt.alpha(Theme.primary, 0.14)
                                       : sortHover.hovered
                                         ? Theme.hoverSurface : "transparent"
                                border.width: sortPicker.activeFocus ? 1 : 0
                                border.color: Theme.focusRing
                            }
                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 8
                                Text {
                                    width: parent.width - 18
                                    text: view.sortLabel()
                                    elide: Text.ElideRight
                                    color: sortPicker.activeFocus || sortHover.hovered
                                           ? Theme.washInk : Theme.primary
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.washMicro
                                    font.letterSpacing: 1.2
                                    font.capitalization: Font.AllUppercase
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Icon {
                                    name: "chevron-down"
                                    size: 10
                                    color: sortPicker.activeFocus || sortHover.hovered
                                           ? Theme.washInk : Theme.washMuted
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 1
                                color: Theme.primary
                            }
                            HoverHandler {
                                id: sortHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                id: sortTap
                                onTapped: sortPicker.openMenu()
                            }
                            ArchiveMenu {
                                id: sortMenu
                                selectedId: view.sortKey
                                options: view.sortOptions
                                onPicked: id => view.chooseSort(id)
                            }
                        }

                        Item {
                            id: sortDirection
                            objectName: "playlistSortDirection"
                            width: 44
                            height: 44
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Sort " + view.sortDirectionName()
                            Accessible.description: "Reverse the current playlist sort order"
                            Accessible.onPressAction: view.toggleSortDirection()
                            Keys.onReturnPressed: view.toggleSortDirection()
                            Keys.onEnterPressed: view.toggleSortDirection()
                            Keys.onSpacePressed: view.toggleSortDirection()

                            Rectangle {
                                anchors.fill: parent
                                color: directionTap.pressed
                                       ? Qt.alpha(Theme.primary, 0.14)
                                       : directionHover.hovered
                                         ? Theme.hoverSurface : "transparent"
                                border.width: sortDirection.activeFocus ? 1 : 0
                                border.color: Theme.focusRing
                            }
                            Icon {
                                anchors.centerIn: parent
                                name: "arrow-up"
                                size: 13
                                rotation: view.sortDescending ? 180 : 0
                                color: sortDirection.activeFocus
                                       || directionHover.hovered
                                       ? Theme.washInk : Theme.washMuted
                                Behavior on rotation {
                                    NumberAnimation { duration: Theme.motionFast }
                                }
                            }
                            HoverHandler {
                                id: directionHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                id: directionTap
                                onTapped: view.toggleSortDirection()
                            }
                        }
                    }
                }

                Column {
                    anchors.left: sortGroup.right
                    anchors.leftMargin: view.compact ? 6 : 16
                    anchors.right: parent.right
                    anchors.top: parent.top
                    spacing: 5

                    Text {
                        text: "PLAYBACK"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 1.8
                        font.capitalization: Font.AllUppercase
                    }
                    // Line actions, never boxed buttons, and in the same
                    // Play → Shuffle → Queue order every other detail page
                    // states them (Album View grammar, 2026-08-22).
                    Row {
                        anchors.left: parent.left
                        height: 44
                        spacing: view.compact ? 20 : 26
                        WashLine {
                            objectName: "playlistPlayAction"
                            label: "Play →"
                            primaryAction: true
                            // The arrangement instrument is part of playback:
                            // Play starts the exact projection on screen, not a
                            // second backend read of the saved insertion order.
                            onActivated: backend.playPlaylistFiles(
                                             view.selected, view.fileList, 0)
                        }
                        WashLine {
                            objectName: "playlistShuffleAction"
                            label: "Shuffle"
                            onActivated: backend.shufflePlaylistNow(view.selected)
                        }
                        WashLine {
                            objectName: "playlistQueueAction"
                            label: "Queue"
                            onActivated: backend.loadPlaylist(view.selected, false)
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

        Text {
            id: errorMessage
            visible: view.loadError !== ""
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: detailHeader.bottom
            anchors.topMargin: 12
            text: view.loadError
            wrapMode: Text.WordWrap
            color: Theme.error
            font.family: Theme.font
            font.pixelSize: Theme.washSub
        }

        GridView {
            id: trackList
            objectName: "playlistTrackList"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: errorMessage.visible ? errorMessage.bottom
                                              : detailHeader.bottom
            anchors.topMargin: errorMessage.visible ? 10 : 8
            anchors.bottom: parent.bottom
            clip: true
            model: view.displayTracks
            readonly property int cols: view.compact || width < 1040 ? 1 : 2
            cellWidth: Math.floor(width / cols)
            cellHeight: view.compact ? 124 : 156
            cacheBuffer: cellHeight * 4
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            ScrollBar.vertical: ArchiveScrollBar {}

            delegate: Item {
                required property var modelData
                required property int index
                width: trackList.cellWidth
                height: trackList.cellHeight

                SleeveTrackRow {
                    anchors.fill: parent
                    anchors.rightMargin: trackList.cols > 1 ? 12 : 0
                    anchors.bottomMargin: 8
                    trackData: parent.modelData
                    fileList: view.fileList
                    rowIndex: parent.index
                    compact: view.compact
                    exhibition: true
                    onEditRequested: track => trackEditor.open(track)
                }
            }
        }
    }
}
