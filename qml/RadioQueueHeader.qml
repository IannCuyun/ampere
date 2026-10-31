import QtQuick
import "."

// Radio identity occupies Gallery's existing panel-header region.
Item {
    id: header
    property bool lyrics: false
    property int count: 0
    readonly property bool stacked: width < 480
    signal exitRequested()
    signal saveRequested()
    height: stacked ? 100 : 52

    Text {
        text: backend.beaconRestoring ? "RESTORING QUEUE…" : backend.beaconBusy ? "BUILDING RADIO…" : "UP NEXT / " + header.count
        color: Theme.primary
        font.family: Theme.displayFont
        font.pixelSize: 10
        font.letterSpacing: 2.2
    }
    Text {
        objectName: "radioPanelHeading"
        y: 20
        width: header.stacked ? parent.width : Math.max(0, actions.x - 16)
        text: header.lyrics ? "RADIO · LYRICS" : "RADIO QUEUE"
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: 22
        font.weight: Font.Light
        font.letterSpacing: 2.2
        elide: Text.ElideRight
    }
    Row {
        id: actions
        x: header.stacked ? 0 : header.width - width
        y: header.stacked ? 52 : 4
        spacing: 8
        GlowButton {
            objectName: "radioSaveControl"
            icon: "save"
            tip: "Save Radio as Playlist"
            enabled: ((backend.beaconSession || {}).tracks || []).length > 0
            opacity: enabled ? 1 : 0.35
            onClicked: if (enabled) header.saveRequested()
        }
        GlowButton {
            objectName: "radioExitControl"
            label: backend.beaconRestoring ? "Restoring queue…" : "Exit Radio Queue"
            enabled: !backend.beaconRestoring
            icon: "close"
            onClicked: header.exitRequested()
        }
    }
}
