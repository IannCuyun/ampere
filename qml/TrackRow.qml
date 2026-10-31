import QtQuick
import QtQuick.Layouts
import "."

// One track line. Owner provides trackData {file,title,artist,duration} plus
// the surrounding fileList/rowIndex so "play from here" replaces sensibly.
Rectangle {
    id: row
    property var trackData: ({})
    property var fileList: []
    property int rowIndex: 0
    property bool playOnSingleClick: false
    property bool showArtist: true
    // Presentation hint retained for album/artist owners. Direct track
    // activation is never the parent-album action, so it must use the normal
    // filtered boundary even when the row is displayed inside a record.
    property bool albumMode: false
    function playHere() {
        backend.playFiles(row.fileList, row.rowIndex)
    }
    function openMenuAt(x, y) {
        menuLoader.openAt(row, x, y)
    }
    property string whenText: ""   // optional "2 h ago" column (smart shelves)
    // Optional second line under the title. Album View uses it for the
    // FEATURED credit only — SPEC row 39 rejects repeating the already-known
    // artist on every row. Empty everywhere else, so the row keeps its 44px.
    property string subText: ""
    signal editRequested(var track)
    readonly property bool isCurrent: backend.currentSong.file !== undefined
                                      && backend.currentSong.file === trackData.file

    width: parent ? parent.width : 0
    height: row.subText !== "" ? 54 : 44
    activeFocusOnTab: true
    Accessible.role: Accessible.ButtonMenu
    Accessible.name: (trackData.title || "Unknown track")
                     + (trackData.artist ? " by " + trackData.artist : "")
    Accessible.description: "Track actions menu; Enter or Space plays this track"
    Accessible.onPressAction: row.openMenuAt(24, row.height)
    Keys.onReturnPressed: row.playHere()
    Keys.onSpacePressed: row.playHere()
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Menu
                || (event.key === Qt.Key_F10
                    && (event.modifiers & Qt.ShiftModifier))) {
            row.openMenuAt(24, row.height)
            event.accepted = true
        }
    }
    radius: 0
    color: rowHover.hovered ? Qt.alpha(Theme.washInk, 0.045)
         : isCurrent ? Qt.alpha(Theme.primary, 0.075) : "transparent"
    border.width: activeFocus ? 2 : 0
    border.color: activeFocus ? Theme.focusRing : "transparent"

    HoverHandler { id: rowHover }

    Rectangle {
        visible: row.isCurrent
        width: 2; height: parent.height
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.primary
        radius: 0
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 8
        spacing: 12

        Item {
            Layout.preferredWidth: 28
            Layout.fillHeight: true
            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                // Only the playing row trades its ordinal for the play mark.
                // Blanking it on hover too left the column simply empty —
                // the hover play control lives in the right action group.
                text: row.isCurrent ? "" : (row.rowIndex + 1)
                color: Qt.alpha(Theme.washFaint, 0.6)
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
            }
            Icon {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                // Paused still marks the row — otherwise the ordinal column
                // goes blank on the one row that matters most.
                visible: row.isCurrent
                name: "play"
                size: 12
                color: Theme.primary
            }
        }
        Column {
            Layout.fillWidth: true
            spacing: 1
            Text {
                width: parent.width
                text: row.trackData.title || ""
                elide: Text.ElideRight
                color: row.isCurrent ? Theme.primary : Theme.washInk
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
                font.weight: Font.Medium
            }
            Text {
                width: parent.width
                visible: row.subText !== ""
                text: row.subText
                elide: Text.ElideRight
                color: Theme.washFaint
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }
        }
        Text {
            // shrinkable: caps at 240 but yields under pressure so the
            // trailing when/duration columns never clip
            Layout.fillWidth: true
            Layout.maximumWidth: 240
            text: row.trackData.artist || ""
            elide: Text.ElideRight
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
            visible: row.showArtist && parent.width > 560
        }
        Row {
            spacing: 4
            visible: rowHover.hovered || rowLiked
            readonly property bool rowLiked:
                backend.likedFiles.indexOf(row.trackData.file || "") >= 0
            GlowButton { activeFocusOnTab: false; icon: "play"; glyphSize: 13; tip: "Play from here"; visible: rowHover.hovered; onClicked: row.playHere() }
            GlowButton { activeFocusOnTab: false; icon: "plus"; glyphSize: 13; tip: "Append to queue"; visible: rowHover.hovered; onClicked: backend.queuePath(row.trackData.file) }
            GlowButton {
                activeFocusOnTab: false
                icon: parent.rowLiked ? "heart" : "heart-o"
                glyphSize: 13
                active: parent.rowLiked
                visible: Theme.heartsOn && (rowHover.hovered || parent.rowLiked)
                tip: parent.rowLiked ? "Remove from Liked" : "Add to Liked"
                onClicked: backend.toggleLike(row.trackData.file)
            }
        }
        Text {
            visible: row.whenText !== ""
            text: row.whenText
            color: Qt.alpha(Theme.washFaint, 0.55)
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 1
        }
        Text {
            text: Theme.fmtTime(row.trackData.duration || 0)
            color: Qt.alpha(Theme.washFaint, 0.7)
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
        }
    }

    TrackActionMenu {
        id: menuLoader
        trackData: row.trackData
        onPlayNow: row.playHere()
        onEditRequested: track => row.editRequested(track)
    }

    MouseArea {
        id: rowMouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        z: -1
        onDoubleClicked: { if (!row.playOnSingleClick) row.playHere() }
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) {
                row.openMenuAt(mouse.x, mouse.y)
            } else if (row.playOnSingleClick) {
                row.playHere()
            }
        }
    }
}
