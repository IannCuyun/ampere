import QtQuick
import "."

// Songs B · Selected Stage. One lead spends the full visual field on its
// album identity; supports keep substantial art and the shared track menu.
Rectangle {
    id: card

    property var trackData: ({})
    property var fileList: []
    property int rowIndex: 0
    property bool lead: false
    property bool compact: false

    readonly property bool isCurrent: backend.currentSong.file !== undefined
                                      && backend.currentSong.file
                                         === trackData.file

    function playHere() {
        backend.playFiles(fileList, rowIndex)
    }

    function openMenuAt(x, y) {
        menu.openAt(card, x, y)
    }

    objectName: "libraryStageSong_" + rowIndex
    color: isCurrent ? Qt.alpha(Theme.primary, 0.12)
                     : Qt.alpha(Theme.bgLow, 0.54)
    border.width: activeFocus ? 1 : 0
    border.color: Theme.focusRing
    clip: true
    activeFocusOnTab: true
    Accessible.role: Accessible.ButtonMenu
    Accessible.name: (trackData.title || "Unknown track")
                     + (trackData.artist ? " by " + trackData.artist : "")
    Accessible.description: "Selected-stage song; Enter or Space plays from here"
    Accessible.onPressAction: playHere()
    Keys.onReturnPressed: playHere()
    Keys.onSpacePressed: playHere()
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu
                || (event.key === Qt.Key_F10
                    && (event.modifiers & Qt.ShiftModifier))) {
            openMenuAt(width - 44, 44)
            event.accepted = true
        }
    }

    MediaArtwork {
        id: art
        objectName: "libraryStageSongArt_" + card.rowIndex
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: card.lead ? parent.width
                         : Math.max(92, Math.floor(parent.width * 0.43))
        kind: "song"
        source: card.trackData.file
                ? "image://art/" + encodeURIComponent(card.trackData.file) : ""
    }

    Rectangle {
        visible: card.lead
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.30; color: "transparent" }
            GradientStop { position: 1; color: Qt.alpha(Theme.bg, 0.96) }
        }
    }

    Column {
        id: identity
        anchors.left: card.lead ? parent.left : art.right
        anchors.leftMargin: card.lead ? (card.compact ? 16 : 22)
                                      : (card.compact ? 12 : 18)
        anchors.right: context.left
        anchors.rightMargin: 6
        anchors.bottom: parent.bottom
        anchors.bottomMargin: card.lead ? (card.compact ? 15 : 22)
                                        : (card.compact ? 12 : 16)
        spacing: card.compact ? 3 : 5

        Text {
            width: parent.width
            text: card.trackData.title || "Unknown track"
            elide: Text.ElideRight
            color: card.isCurrent ? Theme.primary : Theme.washInk
            font.family: Theme.font
            font.pixelSize: card.lead ? (card.compact ? 22 : 30)
                                      : (card.compact ? 15 : 19)
            font.weight: card.lead ? Font.Medium : Font.Normal
        }
        Text {
            width: parent.width
            text: card.trackData.artist || "Unknown artist"
            elide: Text.ElideRight
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: card.compact ? 12 : 14
        }
        Text {
            width: parent.width
            text: (card.trackData.album || "Unknown album")
                  + "  ·  " + Theme.fmtTime(card.trackData.duration || 0)
            elide: Text.ElideRight
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: card.compact ? 9 : 10
            font.letterSpacing: 1
            font.capitalization: Font.AllUppercase
        }
    }

    Item {
        id: context
        z: 2
        objectName: "libraryStageSongContext_" + card.rowIndex
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.top: parent.top
        anchors.topMargin: 4
        width: 44
        height: 44
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Actions for " + (card.trackData.title || "song")
        Accessible.onPressAction: card.openMenuAt(context.x + width,
                                                   context.y + height)
        Keys.onReturnPressed: card.openMenuAt(context.x + width,
                                              context.y + height)
        Keys.onSpacePressed: card.openMenuAt(context.x + width,
                                             context.y + height)
        Rectangle {
            anchors.fill: parent
            color: contextTap.pressed ? Qt.alpha(Theme.primary, 0.15)
                 : contextHover.hovered ? Qt.alpha(Theme.washInk, 0.10)
                                        : "transparent"
            border.width: context.activeFocus ? 1 : 0
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
                    color: Theme.washInk
                }
            }
        }
        HoverHandler { id: contextHover; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            id: contextTap
            onTapped: card.openMenuAt(context.x + context.width,
                                      context.y + context.height)
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: 40
        height: 22
        color: Qt.alpha(Theme.bgLow, 0.84)
        Text {
            anchors.centerIn: parent
            text: (card.rowIndex + 1 < 10 ? "0" : "")
                  + String(card.rowIndex + 1)
            color: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 1.2
        }
    }

    MouseArea {
        z: 1
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton)
                card.openMenuAt(mouse.x, mouse.y)
            else
                card.playHere()
        }
    }

    TrackActionMenu {
        id: menu
        trackData: card.trackData
        onPlayNow: card.playHere()
    }
}
