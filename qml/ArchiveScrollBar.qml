import QtQuick
import QtQuick.Controls.Basic
import "."

ScrollBar {
    id: bar
    policy: ScrollBar.AsNeeded
    width: 8
    padding: 2
    interactive: true

    contentItem: Rectangle {
        implicitWidth: 3
        radius: width / 2
        color: bar.pressed || bar.hovered
               ? Qt.alpha(Theme.primary, 0.74)
               : Qt.alpha(Theme.washInk, 0.26)
        opacity: bar.size < 1 ? 1 : 0
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }
    background: Rectangle {
        color: "transparent"
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 1
            height: parent.height
            color: Qt.alpha(Theme.washInk, bar.hovered ? 0.10 : 0.04)
        }
    }
}
