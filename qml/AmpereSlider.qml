import QtQuick
import QtQuick.Controls.Basic
import "."

Slider {
    id: control
    property color accent: Theme.primary

    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: control.availableWidth
        height: 3
        radius: 1.5
        color: Qt.alpha(Theme.surfaceVariant, 0.9)
        Rectangle {
            width: control.visualPosition * parent.width
            height: parent.height
            radius: 1.5
            color: control.accent
        }
    }
    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: 12
        height: 12
        radius: 6
        color: control.pressed ? control.accent : Theme.text
        border.color: control.accent
        border.width: 1
        Rectangle {
            anchors.centerIn: parent
            width: 22; height: 22; radius: 11
            color: "transparent"
            border.color: Theme.glow(control.accent, control.hovered || control.pressed ? 0.5 : 0.0)
            border.width: 1
        }
    }
}
