import QtQuick
import "."

Item {
    id: control
    implicitWidth: 44
    implicitHeight: 44
    property var shuffleContext: ({ kind: "queue", label: "CURRENT QUEUE" })
    property int glyphSize: 16
    readonly property string mode: backend.contextShuffleMode || "off"
    readonly property bool active: mode === "standard" || mode === "smart"
    readonly property string nextMode: mode === "off" ? "Standard" : mode === "standard" ? "Smart" : "Off"

    GlowButton {
        id: trigger
        objectName: "contextShuffleControl"
        anchors.fill: parent
        implicitWidth: 44
        implicitHeight: 44
        icon: control.mode === "smart" ? "smart-shuffle" : "shuffle"
        active: control.active
        glyphSize: control.glyphSize
        tip: (control.mode === "off" ? "Shuffle off" :
              control.mode === "standard" ? "Standard shuffle active" :
              "Smart shuffle active") + " · next: " + control.nextMode
        Accessible.name: tip
        onClicked: backend.cycleContextShuffle(control.shuffleContext)
    }
}
