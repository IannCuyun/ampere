import QtQuick
import "."

// A line action in the Archive Wash voice: uppercase Rajdhani over a hairline,
// never a pill, slab or glow (design/SPEC.md · Navigation). The visible mark
// is one line of type; the interaction target stays the app-wide 44px.
Item {
    id: link
    property string label: ""
    property bool primaryAction: false
    signal activated()

    implicitWidth: linkText.implicitWidth
    implicitHeight: 44
    width: implicitWidth
    height: implicitHeight
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: link.label
    Accessible.onPressAction: link.activated()
    Keys.onReturnPressed: link.activated()
    Keys.onEnterPressed: link.activated()
    Keys.onSpacePressed: link.activated()

    Text {
        id: linkText
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: link.label
        color: link.primaryAction || linkHover.hovered || link.activeFocus
               ? Theme.washInk : Theme.washMuted
        font.family: Theme.displayFont
        font.pixelSize: Theme.fsMicro
        font.letterSpacing: 3
        font.capitalization: Font.AllUppercase
        elide: Text.ElideRight
    }
    Rectangle {
        anchors.left: linkText.left
        anchors.right: linkText.right
        anchors.top: linkText.bottom
        anchors.topMargin: 3
        height: 1
        visible: link.primaryAction || link.activeFocus
        color: link.activeFocus ? Theme.focusRing : Theme.washInk
    }
    HoverHandler { id: linkHover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: link.activated() }
}
