pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Playlist Sequence Stage. One truthful most-played lead opens the Albums
// field; every other visible sequence continues in one stable run.
Item {
    id: stage

    property var playlistNames: []
    property var covers: ({})
    property var playCounts: ({})
    property bool compact: false
    signal openPlaylist(string name)

    readonly property string leadPlaylist: {
        if (!playlistNames.length)
            return ""
        var winner = String(playlistNames[0])
        var best = Number(playCounts[winner] || 0)
        for (var i = 1; i < playlistNames.length; ++i) {
            var name = String(playlistNames[i])
            var count = Number(playCounts[name] || 0)
            if (count > best) {
                winner = name
                best = count
            }
        }
        return winner
    }
    readonly property var continuationNames: playlistNames.filter(
        function(name) { return String(name) !== leadPlaylist })
    readonly property int cols: compact ? 2 : 3
    readonly property int continuationRows: Math.ceil(
        continuationNames.length / cols)
    readonly property int measureCount: playlistNames.length
                                        ? 1 + continuationRows : 0

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
                        ? "image://art/"
                          + encodeURIComponent(mosaic.files[index]) : ""
            }
        }
    }

    component SequenceCard: Item {
        id: card
        property string sequenceName: ""
        property var art: []
        property bool lead: false
        property int displayIndex: 0

        objectName: "playlistSequence_" + displayIndex
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: sequenceName
        Accessible.description: lead
            ? "Open most-played playlist in this Library shelf"
            : "Open playlist in this Library shelf"
        Accessible.onPressAction: stage.openPlaylist(sequenceName)
        Keys.onReturnPressed: stage.openPlaylist(sequenceName)
        Keys.onSpacePressed: stage.openPlaylist(sequenceName)

        Rectangle {
            anchors.fill: parent
            color: cardTap.pressed ? Qt.alpha(Theme.primary, 0.11)
                 : cardHover.hovered ? Qt.alpha(Theme.washInk, 0.075)
                                     : Qt.alpha(Theme.bgLow, 0.48)
            border.width: card.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }

        Mosaic {
            id: cardMosaic
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            side: card.lead ? Math.min(parent.height, parent.width * 0.38)
                            : Math.min(parent.height, parent.width * 0.43)
            files: card.art
        }

        Column {
            anchors.left: cardMosaic.right
            anchors.leftMargin: card.lead ? (stage.compact ? 16 : 26)
                                          : (stage.compact ? 10 : 14)
            anchors.right: parent.right
            anchors.rightMargin: stage.compact ? 10 : 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: card.lead ? 8 : 5
            Text {
                width: parent.width
                text: card.lead ? "MOST PLAYED" : "SEQUENCE"
                color: card.lead ? Theme.primary : Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.1
                font.capitalization: Font.AllUppercase
            }
            Text {
                width: parent.width
                text: card.sequenceName
                elide: Text.ElideRight
                color: cardHover.hovered || card.activeFocus
                       ? Theme.washInk : Qt.alpha(Theme.washInk, 0.94)
                font.family: Theme.font
                font.pixelSize: card.lead
                    ? (stage.compact ? 23 : 31)
                    : (stage.compact ? 14 : 17)
                font.weight: card.lead ? Font.Medium : Font.Normal
            }
            Text {
                width: parent.width
                text: card.lead
                    ? "Your most-played stored playlist"
                    : "Open sequence"
                elide: Text.ElideRight
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: stage.compact ? 11 : 13
            }
        }

        HoverHandler { id: cardHover; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            id: cardTap
            onTapped: stage.openPlaylist(card.sequenceName)
        }
    }

    ListView {
        id: rows
        objectName: "playlistWall"
        anchors.fill: parent
        clip: true
        model: stage.measureCount
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: stage.compact ? 12 : 16
        ScrollBar.vertical: ArchiveScrollBar {}
        readonly property int cols: stage.cols
        readonly property int measureCount: stage.measureCount

        onModelChanged: Qt.callLater(function() {
            if (rows.visible)
                rows.positionViewAtBeginning()
        })

        delegate: Item {
            id: row
            required property int index
            objectName: index === 0 ? "playlistSequenceStage"
                                    : "playlistContinuationRow_" + (index - 1)
            width: rows.width
            height: index === 0
                    ? (stage.compact ? 222
                       : Math.max(280, Math.floor(rows.height * 0.56)))
                    : (stage.compact ? 152 : 178)
            readonly property real gap: stage.compact ? 10 : 14
            readonly property real cardWidth: Math.floor(
                (width - gap * (stage.cols - 1)) / stage.cols)

            SequenceCard {
                visible: row.index === 0 && stage.leadPlaylist !== ""
                anchors.fill: parent
                sequenceName: stage.leadPlaylist
                art: stage.covers[stage.leadPlaylist] || []
                lead: true
                displayIndex: 0
            }

            Repeater {
                model: row.index === 0 ? 0 : stage.cols
                delegate: SequenceCard {
                    required property int index
                    readonly property int continuationIndex:
                        (row.index - 1) * stage.cols + index
                    visible: continuationIndex < stage.continuationNames.length
                    x: index * (row.cardWidth + row.gap)
                    y: 0
                    width: row.cardWidth
                    height: row.height
                    sequenceName: visible
                        ? String(stage.continuationNames[continuationIndex]) : ""
                    art: stage.covers[sequenceName] || []
                    lead: false
                    displayIndex: continuationIndex + 1
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
