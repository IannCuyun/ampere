pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import "."

// Approved Listening rows, SPEC Home amendment 2026-10-31.
// Selection is worker-owned; a visible page remains stable until revisited.
Item {
    id: page
    property bool active: false
    property var overview: ({ready: false, sections: [], metrics: {}})
    property string discoverLaneKey: ""
    readonly property bool compact: width < 1080
    readonly property bool discoverExpanded: discoverLaneKey !== ""
    signal openLibrary
    signal openNow
    signal openRewind
    signal openAmpy
    signal openShelf(string shelf)
    signal openArtist(string name, string path)
    signal openAlbum(string path, string album)
    property bool awaitingSummary: false
    function reload() {
        overview = backend.homeOverview()
        awaitingSummary = overview.ready !== true
        backend.requestLibrarySummary()
    }
    function openDiscoverLane(key) { discoverLaneKey = key || "deep" }
    function chooseDiscover(key) { openDiscoverLane(key) }
    function closeDiscover() { discoverLaneKey = "" }
    function activate(card) {
        if (card.kind === "song")
            backend.playAlbum([card.file], 0)
        else
            page.openAlbum(card.path, card.album)
    }
    onActiveChanged: if (active) reload()
    Connections {
        target: backend
        function onLibrarySummaryChanged() {
            if (page.active && page.awaitingSummary) {
                page.overview = backend.homeOverview()
                page.awaitingSummary = page.overview.ready !== true
            }
        }
    }
    Flickable {
        id: homeFlick
        objectName: "homeFlick"
        anchors.fill: parent
        anchors.topMargin: 66
        clip: true
        contentHeight: content.y + content.height + 48
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ArchiveScrollBar {}
        ArchiveLoading {
            visible: !backend.libraryReady
            x: content.x; y: content.y
            count: backend.libraryTotalSongs
        }
        Column {
            id: content
            x: page.compact ? 24 : Theme.pageGutter(page.width)
            y: 24
            width: parent.width - 2 * x
            spacing: 30
            visible: backend.libraryReady
            Column {
                width: parent.width
                spacing: 8
                Text { text: "YOUR COLLECTION, REDISCOVERED"; color: Theme.washMuted; font.family: Theme.displayFont; font.pixelSize: 11; font.letterSpacing: 2 }
                Text { text: "Find your next listen."; color: Theme.washInk; font.family: Theme.font; font.pixelSize: page.compact ? 32 : 38; font.weight: Font.Light }
            }
            // Existing Discover route remains accessible from Features.
            Column {
                width: parent.width
                spacing: 16
                visible: page.discoverExpanded
                WashLine { label: "Back to recommendations"; onActivated: page.closeDiscover() }
                DiscoverView {
                    width: parent.width
                    height: implicitHeight
                    active: page.active && page.discoverExpanded
                    requestedKey: page.discoverLaneKey
                }
            }
            Repeater {
                model: page.discoverExpanded ? [] : (page.overview.sections || [])
                delegate: Column {
                    id: section
                    required property var modelData
                    width: content.width
                    spacing: 24
                    Rectangle { width: parent.width; height: 1; color: Theme.washHair }
                    Text { text: section.modelData.title.toUpperCase(); color: Theme.washMuted; font.family: Theme.displayFont; font.pixelSize: 11; font.letterSpacing: 2; width: parent.width; wrapMode: Text.Wrap }
                    Grid {
                        id: rowGrid
                        width: parent.width
                        columns: page.compact ? 2 : 4
                        columnSpacing: 24
                        rowSpacing: 30
                        Repeater {
                            model: section.modelData.cards
                            delegate: Item {
                                id: card
                                required property var modelData
                                objectName: "homeRecommendationCard"
                                width: (rowGrid.width - (rowGrid.columns - 1) * rowGrid.columnSpacing) / rowGrid.columns
                                height: width + 152
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.label + ": " + modelData.title + " by " + modelData.artist + ". " + modelData.reason
                                Accessible.onPressAction: page.activate(card.modelData)
                                MediaArtwork { width: card.width; height: width; source: "image://art/" + encodeURIComponent(card.modelData.file); kind: "album" }
                                Column {
                                    y: card.width + 14; width: parent.width; spacing: 7
                                    Text { text: card.modelData.label.toUpperCase(); width: parent.width; elide: Text.ElideRight; color: Theme.washMuted; font.family: Theme.displayFont; font.pixelSize: 10; font.letterSpacing: 1.5 }
                                    Text { text: card.modelData.title; width: parent.width; height: 44; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; color: Theme.washInk; font.family: Theme.font; font.pixelSize: 18 }
                                    Text { text: card.modelData.artist; width: parent.width; elide: Text.ElideRight; color: Theme.washMuted; font.family: Theme.font; font.pixelSize: 13 }
                                    Text { text: card.modelData.reason; width: parent.width; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; color: Theme.washMuted; font.family: Theme.font; font.pixelSize: 12 }
                                }
                                Rectangle { anchors.fill: parent; color: "transparent"; border.width: card.activeFocus ? 1 : 0; border.color: Theme.focusRing }
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: page.activate(card.modelData) }
                                Keys.onReturnPressed: page.activate(card.modelData)
                                Keys.onEnterPressed: page.activate(card.modelData)
                                Keys.onSpacePressed: page.activate(card.modelData)
                                onActiveFocusChanged: if (activeFocus) {
                                    const point = card.mapToItem(content, 0, 0)
                                    homeFlick.contentY = Math.max(0, Math.min(point.y + content.y - 70, homeFlick.contentHeight - homeFlick.height))
                                }
                            }
                        }
                    }
                }
            }
            Text {
                visible: !page.discoverExpanded && !(page.overview.sections || []).length
                width: parent.width; wrapMode: Text.Wrap
                text: page.overview.ready ? "Explore your library. Recommendations will grow with your listening." : "Preparing your listening recommendations…"
                color: Theme.washMuted; font.family: Theme.font; font.pixelSize: 16
            }
            WashLine { visible: !(page.overview.sections || []).length; label: "Open Library →"; onActivated: page.openLibrary() }
            Column {
                width: parent.width; spacing: 20
                visible: !page.discoverExpanded && page.overview.ready && Number((page.overview.metrics || {}).week || 0) > 0
                Rectangle { width: parent.width; height: 1; color: Theme.washHair }
                Text { text: "YOUR LISTENING"; color: Theme.washMuted; font.family: Theme.displayFont; font.pixelSize: 11; font.letterSpacing: 2 }
                Text { text: Number((page.overview.metrics || {}).week || 0) + " plays in the last 7 days"; color: Theme.washInk; font.family: Theme.font; font.pixelSize: 30; font.weight: Font.Light }
                WashLine { label: "Explore your listening →"; onActivated: page.openRewind() }
            }
        }
    }
}
