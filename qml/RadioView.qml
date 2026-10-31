import QtQuick
import QtQuick.Controls.Basic
import "."

// SPEC.md: October 2 reference is Gallery itself, not a parallel layout.
GalleryNowPlayingView {
    id: view
    radioRoom: true
    queueOpen: true
    onActiveChanged: if (active) setQueue(true)
    onSaveRadioRequested: {
        var session = backend.beaconSession || ({})
        playlistName.text = "Radio—" + ((session.seed || {}).artist || "Song")
        saveDialog.open()
    }

    Dialog {
        id: saveDialog
        objectName: "radioSaveDialog"
        anchors.centerIn: parent
        width: Math.min(440, view.width - 64)
        title: "Save as Playlist"
        header: Text {
            text: saveDialog.title
            padding: 20
            color: Theme.text
            font.family: Theme.displayFont
            font.pixelSize: 28
        }
        footer: DialogButtonBox {
            standardButtons: saveDialog.standardButtons
            delegate: Button {
                implicitHeight: 44
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
                contentItem: Text { text: parent.text; color: Theme.text; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: parent.down || parent.hovered ? Theme.hoverSurface : "transparent"; border.width: parent.activeFocus ? 2 : 0; border.color: Theme.focusRing }
            }
        }
        modal: true
        standardButtons: Dialog.Save | Dialog.Cancel
        onOpened: { playlistName.forceActiveFocus(); playlistName.selectAll() }
        onAccepted: if (playlistName.text.trim()) backend.saveBeaconPlaylist(playlistName.text.trim())
        background: Rectangle { color: Theme.planeRaised; border.color: Theme.washHair }
        contentItem: TextField {
            id: playlistName
            objectName: "radioPlaylistName"
            implicitHeight: 48
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
            Accessible.name: "Playlist name"
            selectByMouse: true
            background: Rectangle { color: "transparent"; border.width: playlistName.activeFocus ? 2 : 1; border.color: playlistName.activeFocus ? Theme.focusRing : Theme.washHair }
            onTextChanged: { var save = saveDialog.standardButton(Dialog.Save); if (save) save.enabled = text.trim() !== "" }
        }
    }
}
