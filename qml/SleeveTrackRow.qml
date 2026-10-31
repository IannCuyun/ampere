import QtQuick
import "."

// Sleeve Stream — the art-first Library Songs row selected by Iann on
// 2026-08-16. The surrounding GridView owns virtualization and responsive
// column count; this component preserves TrackRow's playback/context contract.
Rectangle {
    id: row

    property var trackData: ({})
    property var fileList: []
    property int rowIndex: 0
    property bool compact: false
    property bool exhibition: false
    property bool featured: false
    signal editRequested(var track)

    readonly property bool isCurrent: backend.currentSong.file !== undefined
                                      && backend.currentSong.file === trackData.file
    readonly property bool isLiked: backend.likedFiles.indexOf(
                                        trackData.file || "") >= 0

    function playHere() {
        backend.playFiles(row.fileList, row.rowIndex)
    }

    function openMenuAt(x, y) {
        menuLoader.openAt(row, x, y)
    }

    objectName: "librarySleeveTrack_" + rowIndex
    implicitHeight: featured ? (compact ? 144 : 188)
                   : exhibition ? (compact ? 116 : 148)
                               : (compact ? 92 : 112)
    radius: 0
    color: row.isCurrent ? Qt.alpha(Theme.primary, 0.105)
         : rowHover.hovered ? Qt.alpha(Theme.washInk, 0.065)
         : Qt.alpha(Theme.washInk, 0.032)
    border.width: activeFocus ? 1 : 0
    border.color: activeFocus ? Theme.focusRing : "transparent"
    activeFocusOnTab: true
    Accessible.role: Accessible.ButtonMenu
    Accessible.name: (trackData.title || "Unknown track")
                     + (trackData.artist ? " by " + trackData.artist : "")
    Accessible.description: "Song actions; Enter or Space plays this song"
    Accessible.onPressAction: row.openMenuAt(row.width - 44, row.height)

    Keys.onReturnPressed: row.playHere()
    Keys.onSpacePressed: row.playHere()
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu
                || (event.key === Qt.Key_F10
                    && (event.modifiers & Qt.ShiftModifier))) {
            row.openMenuAt(row.width - 44, row.height)
            event.accepted = true
        }
    }

    // A restrained album-room wash gives each sleeve visual territory without
    // introducing per-row blur or expensive effects into the long collection.
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop {
                position: 0
                color: Qt.alpha(Theme.primary,
                                row.isCurrent ? 0.15
                                              : rowHover.hovered ? 0.09 : 0.055)
            }
            GradientStop { position: 0.42; color: Qt.alpha(Theme.primary, 0.018) }
            GradientStop { position: 1; color: "transparent" }
        }
    }

    Rectangle {
        visible: row.isCurrent
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 2
        color: Theme.primary
    }

    HoverHandler {
        id: rowHover
        cursorShape: Qt.PointingHandCursor
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton)
                row.openMenuAt(mouse.x, mouse.y)
            else
                row.playHere()
        }
    }

    MediaArtwork {
        id: sleeve
        objectName: "librarySleeveTrackArt_" + row.rowIndex
        z: 1
        anchors.left: parent.left
        anchors.leftMargin: row.featured ? 16
                            : row.exhibition ? 12 : (row.compact ? 8 : 10)
        anchors.verticalCenter: parent.verticalCenter
        width: row.featured ? (row.compact ? 116 : 164)
             : row.exhibition ? (row.compact ? 96 : 124)
                              : (row.compact ? 76 : 92)
        height: width
        kind: "song"
        source: row.trackData.file
                ? "image://art/" + encodeURIComponent(row.trackData.file) : ""

        Rectangle {
            visible: row.isCurrent || rowHover.hovered
            anchors.fill: parent
            color: Qt.alpha("#000000", row.isCurrent ? 0.24 : 0.13)
        }
        Rectangle {
            visible: row.isCurrent || rowHover.hovered
            anchors.centerIn: parent
            width: row.featured ? 46
                 : row.exhibition ? 40 : (row.compact ? 30 : 34)
            height: width
            radius: width / 2
            color: row.isCurrent ? Theme.primary : Qt.alpha(Theme.washInk, 0.88)
            Icon {
                anchors.centerIn: parent
                name: "play"
                size: 13
                color: row.isCurrent ? Theme.inkOnPrimary : Theme.bgLow
            }
        }
        Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            width: 34
            height: 20
            color: Qt.alpha(Theme.bgLow, 0.82)
            Text {
                anchors.centerIn: parent
                text: (row.rowIndex + 1 < 10 ? "0" : "")
                      + String(row.rowIndex + 1)
                color: Theme.washInk
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.2
            }
        }
    }

    Column {
        id: identity
        z: 1
        anchors.left: sleeve.right
        anchors.leftMargin: row.exhibition ? 20 : (row.compact ? 12 : 16)
        anchors.right: contextButton.left
        anchors.rightMargin: row.compact ? 4 : 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: row.compact ? 3 : 5

        Text {
            width: parent.width
            text: row.trackData.title || "Unknown track"
            elide: Text.ElideRight
            color: row.isCurrent ? Theme.primary : Theme.washInk
            font.family: Theme.font
            font.pixelSize: row.featured ? (row.compact ? 18 : 24)
                            : row.exhibition ? (row.compact ? 16 : 20)
                                             : (row.compact ? 15 : 18)
            font.weight: Font.Medium
        }
        Text {
            width: parent.width
            text: row.trackData.artist || "Unknown artist"
            elide: Text.ElideRight
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: row.exhibition ? (row.compact ? 13 : 14)
                                             : (row.compact ? 12 : 13)
        }
        Text {
            width: parent.width
            text: (row.trackData.album || "Unknown album")
                  + "  ·  " + Theme.fmtTime(row.trackData.duration || 0)
            elide: Text.ElideRight
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: row.compact ? 9 : 10
            font.letterSpacing: row.compact ? 0.7 : 1.0
            font.capitalization: Font.AllUppercase
        }
    }

    Item {
        id: contextButton
        objectName: "librarySleeveTrackContext_" + row.rowIndex
        z: 2
        anchors.right: parent.right
        anchors.rightMargin: row.compact ? 0 : 2
        anchors.verticalCenter: parent.verticalCenter
        width: 44
        height: 44
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Actions for " + (row.trackData.title || "song")
        Accessible.onPressAction: row.openMenuAt(
                                      contextButton.x + contextButton.width,
                                      contextButton.y + contextButton.height)
        Keys.onReturnPressed: row.openMenuAt(
                                  contextButton.x + contextButton.width,
                                  contextButton.y + contextButton.height)
        Keys.onSpacePressed: row.openMenuAt(
                                 contextButton.x + contextButton.width,
                                 contextButton.y + contextButton.height)

        Rectangle {
            anchors.fill: parent
            color: contextTap.pressed ? Qt.alpha(Theme.primary, 0.15)
                 : contextHover.hovered ? Qt.alpha(Theme.washInk, 0.07)
                 : "transparent"
            border.width: contextButton.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: 3
                delegate: Rectangle {
                    required property int index
                    width: 2.5
                    height: 2.5
                    radius: 2
                    color: contextButton.activeFocus || contextHover.hovered
                           ? Theme.washInk : Theme.washMuted
                }
            }
        }
        HoverHandler {
            id: contextHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: contextTap
            onTapped: row.openMenuAt(contextButton.x + contextButton.width,
                                     contextButton.y + contextButton.height)
        }
    }

    // The ONE track menu (SPEC · Search results, Iann verdict 2026-08-20 #7:
    // no surface grows a parallel track menu). This row carried a duplicate
    // option list, so it silently missed anything added to the shared menu —
    // "add to playlist" among them (2026-08-22).
    TrackActionMenu {
        id: menuLoader
        trackData: row.trackData
        onPlayNow: row.playHere()
        onEditRequested: track => row.editRequested(track)
    }
}
