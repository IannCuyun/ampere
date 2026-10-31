import QtQuick
import "."

// Text that scrolls horizontally when it overflows its box.
Item {
    id: root
    property string text: ""
    property color color: Theme.text
    property int pixelSize: 16
    property int weight: Font.Normal
    clip: true
    implicitHeight: t.implicitHeight
    // actual rendered text width (capped at the box) — lets owners size
    // click areas to the words, not the whole layout column
    readonly property real textWidth: Math.min(t.implicitWidth, width)

    Text {
        id: t
        text: root.text
        color: root.color
        font.family: Theme.font
        font.pixelSize: root.pixelSize
        font.weight: root.weight

        SequentialAnimation on x {
            running: t.implicitWidth > root.width && root.visible
            loops: Animation.Infinite
            PauseAnimation { duration: 2000 }
            NumberAnimation {
                to: root.width - t.implicitWidth
                duration: Math.max(1500, (t.implicitWidth - root.width) * 35)
            }
            PauseAnimation { duration: 1400 }
            NumberAnimation { to: 0; duration: 700; easing.type: Easing.InOutQuad }
        }
    }
    onTextChanged: t.x = 0
}
