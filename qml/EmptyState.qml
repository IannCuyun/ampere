import QtQuick
import "."

// A designed empty state: dim drawn icon, one calm eyebrow, optional hint.
// Empty is a state the room owns — never a blank void. Painted with the
// Archive Wash ink set so it sits on the same surfaces as the rows around it.
Column {
    id: root
    property string icon: "note"
    property string headline: ""
    property string hint: ""
    spacing: 8

    Icon {
        anchors.horizontalCenter: parent.horizontalCenter
        name: root.icon
        size: 34
        color: Theme.washFaint
    }
    Text {
        visible: root.headline !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.headline
        color: Theme.washInk
        font.family: Theme.displayFont
        font.pixelSize: Theme.washMicro
        font.letterSpacing: 2.2
        font.capitalization: Font.AllUppercase
    }
    Text {
        visible: root.hint !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(implicitWidth, root.width - 24)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: root.hint
        color: Theme.washMuted
        font.family: Theme.font
        font.pixelSize: Theme.fsBody
    }
}
