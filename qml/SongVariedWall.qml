pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Songs B · Selected Stage. The first complete Albums-sized field holds one
// explicit lead and four disciplined supports. Everything after that continues
// in one stable art-led run without reordering or another hero cadence.
Item {
    id: wall

    property var songs: []
    property var fileList: []
    property bool compact: false
    property int currentIndex: -1
    readonly property int stageCount: Math.min(5, songs.length)
    readonly property int continuationCount: Math.max(0, songs.length - 5)
    readonly property int columns: compact ? 1 : 2
    readonly property int continuationRows: Math.ceil(
        continuationCount / columns)
    readonly property int measureCount: songs.length > 0
                                        ? 1 + continuationRows : 0
    property alias contentY: rowList.contentY
    readonly property real originY: rowList.originY

    function jumpToGlobalIndex(index) {
        currentIndex = index
        var row = index < 5 ? 0
                            : 1 + Math.floor((index - 5) / columns)
        rowList.positionViewAtIndex(row, ListView.Beginning)
    }

    function revealBeginning() {
        currentIndex = -1
        Qt.callLater(function() {
            if (rowList.visible)
                rowList.positionViewAtBeginning()
        })
    }

    ListView {
        id: rowList
        objectName: "librarySongMeasureList"
        anchors.fill: parent
        clip: true
        model: wall.measureCount
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: wall.compact ? 14 : 22
        ScrollBar.vertical: ArchiveScrollBar {}

        onModelChanged: wall.revealBeginning()
        Component.onCompleted: wall.revealBeginning()

        delegate: Item {
            id: row
            required property int index
            objectName: index === 0
                        ? "librarySongSelectedStage"
                        : "librarySongContinuationRow_" + (index - 1)
            width: rowList.width
            height: index === 0
                    ? (wall.compact ? 458 : Math.max(520, wall.height))
                    : (wall.compact ? 126 : 158)

            readonly property real gap: wall.compact ? 10 : 16
            readonly property real leadWidth: wall.compact
                ? width : Math.floor(width * 0.42)
            readonly property real supportWidth: wall.compact
                ? Math.floor((width - gap) / 2)
                : Math.floor((width - leadWidth - gap * 2) / 2)
            readonly property real supportHeight: wall.compact
                ? 124 : Math.floor((height - gap) / 2)

            Repeater {
                model: row.index === 0 ? wall.stageCount : 0
                delegate: StageSongCard {
                    required property int index
                    readonly property int globalIndex: index
                    x: wall.compact
                       ? (index === 0 ? 0
                          : ((index - 1) % 2)
                            * (row.supportWidth + row.gap))
                       : (index === 0 ? 0
                          : row.leadWidth + row.gap
                            + ((index - 1) % 2)
                              * (row.supportWidth + row.gap))
                    y: wall.compact
                       ? (index === 0 ? 0
                          : (index <= 2
                             ? 180 + row.gap
                             : 180 + row.gap
                               + row.supportHeight + row.gap))
                       : (index === 0 ? 0
                          : Math.floor((index - 1) / 2)
                            * (row.supportHeight + row.gap))
                    width: wall.compact
                           ? (index === 0 ? row.width : row.supportWidth)
                           : (index === 0 ? row.leadWidth : row.supportWidth)
                    height: wall.compact
                            ? (index === 0 ? 180 : row.supportHeight)
                            : (index === 0 ? row.height : row.supportHeight)
                    lead: index === 0
                    compact: wall.compact
                    trackData: wall.songs[globalIndex] || ({})
                    fileList: wall.fileList
                    rowIndex: globalIndex
                    onActiveFocusChanged: {
                        if (activeFocus) wall.currentIndex = globalIndex
                    }
                }
            }

            Repeater {
                model: row.index === 0 ? 0 : wall.columns
                delegate: SleeveTrackRow {
                    required property int index
                    readonly property int globalIndex:
                        5 + (row.index - 1) * wall.columns + index
                    visible: globalIndex < wall.songs.length
                    x: index * (Math.floor((row.width - row.gap
                                            * (wall.columns - 1))
                                           / wall.columns) + row.gap)
                    y: 0
                    width: Math.floor((row.width - row.gap
                                       * (wall.columns - 1)) / wall.columns)
                    height: row.height
                    compact: wall.compact
                    exhibition: true
                    trackData: wall.songs[globalIndex] || ({})
                    fileList: wall.fileList
                    rowIndex: globalIndex
                    onActiveFocusChanged: {
                        if (activeFocus) wall.currentIndex = globalIndex
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
}
