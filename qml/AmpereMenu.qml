import QtQuick
import QtQuick.Controls.Basic
import "."

// Right-click / options menu. options = [{id, label}]; emits picked(id).
Popup {
    id: menu
    property var options: []
    property int currentIndex: 0
    // A menu that pages (track actions -> playlist chooser) has to survive the
    // pick that changes its page, so the owner closes it instead.
    property bool closeOnPick: true
    signal picked(string id)

    padding: 5
    background: Rectangle {
        color: Qt.alpha(Theme.bgLow, 0.98)
        border.color: Theme.washHair
        border.width: 1
        radius: 0
    }

    function popupAt(item, px, py) {
        parent = item
        x = px
        y = py
        currentIndex = 0
        open()
        Qt.callLater(optionColumn.forceActiveFocus)
    }

    // widest label sets the width for every row — no text bleed
    property int _itemW: 190
    onOptionsChanged: _itemW = 190

    contentItem: Column {
        id: optionColumn
        focus: true
        spacing: 2
        Keys.onUpPressed: menu.currentIndex = (menu.currentIndex - 1
            + menu.options.length) % menu.options.length
        Keys.onDownPressed: menu.currentIndex = (menu.currentIndex + 1)
            % menu.options.length
        Keys.onReturnPressed: menu.choose(menu.currentIndex)
        Keys.onEnterPressed: menu.choose(menu.currentIndex)
        Keys.onSpacePressed: menu.choose(menu.currentIndex)
        Keys.onEscapePressed: menu.close()
        Repeater {
            model: menu.options
            delegate: Rectangle {
                id: optionRow
                required property var modelData
                required property int index
                width: menu._itemW
                height: 44
                radius: 0
                color: menu.currentIndex === index || mArea.containsMouse
                    ? Qt.alpha(Theme.primary, 0.12) : "transparent"
                Accessible.role: Accessible.MenuItem
                Accessible.name: modelData.label
                Accessible.focused: menu.currentIndex === index
                Accessible.onPressAction: menu.choose(optionRow.index)
                Text {
                    id: lbl
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12
                    text: modelData.label
                    color: menu.currentIndex === optionRow.index || mArea.containsMouse
                        ? Theme.washInk : Theme.washMuted
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 1.8
                    font.capitalization: Font.AllUppercase
                    Component.onCompleted: menu._itemW = Math.max(menu._itemW, Math.ceil(lbl.implicitWidth) + 26)
                }
                MouseArea {
                    id: mArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onContainsMouseChanged: if (containsMouse)
                        menu.currentIndex = optionRow.index
                    onClicked: menu.choose(optionRow.index)
                }
            }
        }
    }

    function choose(index) {
        if (index < 0 || index >= options.length) return
        picked(options[index].id)
        if (closeOnPick)
            close()
    }
}
