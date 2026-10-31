import QtQuick
import QtQuick.Layouts
import "."

import QtQuick.Controls.Basic as QQC

Rectangle {
    id: btn
    property string glyph: ""
    property string label: ""
    property string tip: ""
    property bool active: false
    property int glyphSize: 16
    property string shuffleMode: "off"
    property bool volumeIcon: false
    property bool volumeMuted: false
    readonly property bool pressed: mouse.pressed
    property bool dislikeIcon: false
    property bool heartIcon: false
    // Optional state mark drawn over the glyph without creating a second
    // target or a badge slab. Loop-one uses this for its canonical "1".
    property string badgeText: ""
    // small per-glyph nudge — some unicode glyphs sit low in their em box
    property int glyphYOffset: 0
    signal clicked()
    signal rightClicked()
    Accessible.role: Accessible.Button
    Accessible.name: label || tip || icon || glyph || "Button"
    Accessible.onPressAction: btn.clicked()

    QQC.ToolTip.visible: tip !== "" && mouse.containsMouse
    QQC.ToolTip.delay: 550
    QQC.ToolTip.text: tip

    // min width keeps glyph-only buttons the same visual size as each other
    implicitWidth: Math.max(44, row.width + 20)
    implicitHeight: 44
    radius: Theme.radiusSm
    color: mouse.pressed ? Qt.alpha(Theme.primary, 0.14)
         : mouse.containsMouse ? Qt.alpha(Theme.text, 0.055) : "transparent"
    scale: mouse.pressed ? 0.965 : 1
    Behavior on scale {
        NumberAnimation { duration: 65; easing.type: Easing.OutCubic }
    }
    border.color: activeFocus ? Theme.focusRing : "transparent"
    border.width: activeFocus ? 2 : 0

    // Active state is a CENTRED wash, not a bar under the glyph. The old 2px
    // bottom rule sat off the row's shared axis and broke the centreline on
    // exactly the buttons that are ever active (loop, lyrics, queue, like) —
    // Iann's "make sure they're aligned so that they share the same center
    // point" (2026-08-02). Needle's active treatment, ported from the study.
    Rectangle {
        visible: btn.active
        anchors.centerIn: parent
        width: 29
        height: 29
        radius: width / 2
        color: Qt.alpha(Theme.primary, 0.13)
        border.width: 1
        border.color: Qt.alpha(Theme.primary, 0.22)
    }

    // keyboard-reachable: Tab lands here, Return/Space activate
    activeFocusOnTab: true
    Keys.onReturnPressed: btn.clicked()
    Keys.onSpacePressed: btn.clicked()

    property bool shuffleIcon: false

    // drawn icon from the Ampere set (Icon.qml) — preferred over glyph
    property string icon: ""

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Icon {
            visible: btn.icon !== ""
            name: btn.icon
            size: btn.glyphSize + 2
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
        }
        // Needle family (Iann, 2026-08-02): shuffle, volume and the heart were
        // bespoke Canvas components drawn in a different voice. They now come
        // from the one registry so the whole row shares a weight and a grid.
        Icon {
            visible: btn.shuffleIcon
            name: "shuffle"
            size: btn.glyphSize + 2
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon {
            visible: btn.volumeIcon
            name: btn.volumeMuted ? "volume-muted" : "volume"
            size: btn.glyphSize + 2
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon {
            visible: btn.dislikeIcon
            name: "heart-crack"
            size: btn.glyphSize + 4
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon {
            visible: btn.heartIcon
            name: btn.active ? "heart" : "heart-o"
            size: btn.glyphSize + 2
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: btn.glyph
            visible: btn.glyph !== ""
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            font.pixelSize: btn.glyphSize
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: btn.glyphYOffset
        }
        Text {
            text: btn.label
            visible: btn.label !== ""
            color: btn.active || mouse.containsMouse ? Theme.primary : Theme.textDim
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 0.3
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    Text {
        objectName: btn.objectName + "Badge"
        visible: btn.badgeText !== ""
        text: btn.badgeText
        anchors.centerIn: parent
        anchors.horizontalCenterOffset: 7
        anchors.verticalCenterOffset: -8
        color: Theme.primary
        font.family: Theme.font
        font.pixelSize: 10
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: (m) => m.button === Qt.RightButton ? btn.rightClicked() : btn.clicked()
    }
}
