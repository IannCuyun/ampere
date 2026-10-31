import QtQuick
import "."

// One remembered album in Home's Rewind filmstrip. The parent owns the
// Rewind action so the strip reads as a single visual memory instrument.
Item {
    id: memory
    objectName: memory.current ? "homeMemoryCurrent" : ""

    property var entry: ({})
    property bool current: false
    readonly property string artKey: entry.file || entry.cover || ""

    MediaArtwork {
        anchors.fill: parent
        source: memory.artKey
            ? "image://art/" + encodeURIComponent(memory.artKey) : ""
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: memory.current ? 1 : 0
        border.color: Theme.primary
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.bottom
        anchors.topMargin: 8
        width: memory.current ? 6 : 4
        height: width
        radius: width / 2
        color: Theme.primary
        opacity: memory.current ? 1 : 0.64
    }
}
