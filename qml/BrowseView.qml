import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// Folder browsing inside the ratified browse-frame skeleton (design/SPEC.md ·
// Browse family). Folders and tracks share ONE ListView model — a ListView
// `header` sits above content origin and loses its scroll position to model
// swaps (proven twice 2026-07-31; kin to the search-dropdown contentY
// gotcha) — so folder rows are model rows, type-switched through a Loader.
Item {
    id: view
    property string path: ""
    signal openPath(string path)
    signal openAlbum(string path, string album)
    signal destinationRequested(string section)
    property var dirs: []
    property var tracks: []
    readonly property var fileList: tracks.map(t => t.file)
    readonly property var rows: dirs.concat(tracks)
    readonly property var albumNames: {
        var seen = ({})
        var names = []
        for (var i = 0; i < tracks.length; ++i) {
            var name = tracks[i].album || ""
            if (name && !seen[name]) {
                seen[name] = true
                names.push(name)
            }
        }
        return names
    }
    readonly property bool isAlbum: dirs.length === 0 && albumNames.length === 1
    readonly property string leafName: path.split("/").pop() || ""
    // The folder's own dominant credit; a row states only what differs.
    readonly property string folderArtist: {
        var counts = ({}), best = "", top = 0
        for (var i = 0; i < tracks.length; ++i) {
            var name = String(tracks[i].artist || "")
            if (!name) continue
            counts[name] = (counts[name] || 0) + 1
            if (counts[name] > top) { top = counts[name]; best = name }
        }
        return top > tracks.length / 2 ? best : ""
    }
    function credit(track) {
        var artist = String((track && track.artist) || "")
        if (!artist || !folderArtist || artist === folderArtist) return ""
        var lowered = artist.toLowerCase(), lead = folderArtist.toLowerCase()
        if (lowered.indexOf(lead) === 0) {
            var rest = artist.slice(folderArtist.length)
                             .replace(/^[\s,&/·]*(feat\.?|featuring|with|w\/)?[\s.]*/i, "")
            return rest || ""
        }
        return artist
    }

    function reload() {
        if (!path) { dirs = []; tracks = []; return }
        var e = backend.browse(path)
        dirs = e.filter(x => x.type === "dir")
        tracks = e.filter(x => x.type === "file")
    }
    onPathChanged: { reload(); list.contentY = 0 }
    Component.onCompleted: reload()
    Connections { target: backend; function onDatabaseUpdated() { view.reload() } }

    // this folder's art whispers under the page, wash-toned
    Image {
        anchors.fill: parent
        source: tracks.length ? "image://art/" + encodeURIComponent(tracks[0].file)
              : (dirs.length ? "image://art/" + encodeURIComponent(dirs[0].path) : "")
        fillMode: Image.PreserveAspectCrop
        opacity: 0.14
    }
    Rectangle { anchors.fill: parent; color: Qt.alpha("#0d0c0c", 0.80) }

    LibraryFrame {
        id: browseFrame
        anchors.fill: parent
        breadcrumb: "LIBRARY / " + view.path.split("/").join(" / ")
        title: view.leafName
        subtitle: (view.dirs.length ? view.dirs.length + " folders" : "")
                  + (view.dirs.length && view.tracks.length ? " · " : "")
                  + (view.tracks.length ? view.tracks.length + " tracks" : "")
        currentSection: "folders"
        actions: {
            var a = []
            if (view.isAlbum) a.push({ id: "album", label: "Album view" })
            a.push({ id: "queue", label: "Queue" })
            a.push({ id: "shuffle", label: "Shuffle" })
            a.push({ id: "play", label: "Play", accent: true })
            return a
        }
        onDestinationRequested: section => view.destinationRequested(section)
        onActionRequested: id => {
            if (id === "play") backend.playPath(view.path)
            else if (id === "shuffle") backend.shufflePathNow(view.path)
            else if (id === "queue") backend.queuePath(view.path)
            else if (id === "album") view.openAlbum(view.path, view.albumNames[0])
        }

        ArchiveLoading {
            visible: !backend.libraryReady
            anchors.left: parent.left
            anchors.top: parent.top
            count: backend.libraryTotalSongs
        }

        ListView {
            id: list
            anchors.fill: parent
            visible: backend.libraryReady
            clip: true
            spacing: 0
            model: view.rows
            cacheBuffer: 900
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ArchiveScrollBar {}
            delegate: Loader {
                required property var modelData
                required property int index
                width: list.width
                sourceComponent: modelData.type === "dir" ? folderComp : trackComp
                function sync() {
                    if (!item) return
                    if (modelData.type === "dir") {
                        item.rowData = modelData
                    } else {
                        item.trackData = modelData
                        item.fileList = view.fileList
                        item.rowIndex = index - view.dirs.length
                    }
                }
                onLoaded: sync()
                onModelDataChanged: sync()
            }

            Component {
                id: trackComp
                TrackRow {
                    width: list.width
                    playOnSingleClick: true
                    // A folder named for one artist repeated that artist on
                    // all 71 rows; only a DIFFERING credit is evidence
                    // (SPEC row 39, applied 2026-08-22).
                    showArtist: false
                    subText: view.credit(trackData)
                    onEditRequested: track => trackEditor.open(track)
                }
            }

            Component {
                id: folderComp
                Item {
                    id: folderRow
                    property var rowData: ({})
                    width: list.width
                    height: 64
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: rowData.name || "folder"
                    Accessible.onPressAction: view.openPath(rowData.path)
                    Keys.onReturnPressed: view.openPath(rowData.path)
                    Keys.onSpacePressed: view.openPath(rowData.path)
                    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.washHair }
                    MediaArtwork {
                        id: folderArt
                        anchors.verticalCenter: parent.verticalCenter
                        width: 44
                        height: 44
                        kind: "folder"
                        source: folderRow.rowData.cover
                                ? "image://art/folder:" + encodeURIComponent(folderRow.rowData.cover) : ""
                    }
                    Text {
                        anchors.left: folderArt.right
                        anchors.leftMargin: 16
                        anchors.right: openHint.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: folderRow.rowData.name || ""
                        elide: Text.ElideRight
                        color: folderHover.hovered ? Theme.washInk : Qt.alpha(Theme.washInk, 0.92)
                        font.family: Theme.font
                        font.pixelSize: 15
                        font.weight: Font.Light
                    }
                    Row {
                        id: openHint
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Text {
                            visible: folderHover.hovered
                            text: "OPEN"
                            color: Theme.primary
                            font.family: Theme.displayFont
                            font.pixelSize: 10
                            font.letterSpacing: 2.2
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Icon {
                            name: "chevron-right"
                            size: 12
                            color: folderHover.hovered ? Theme.primary : Theme.washFaint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.width: folderRow.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                    }
                    HoverHandler { id: folderHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: view.openPath(folderRow.rowData.path) }
                }
            }
        }
    }
}
