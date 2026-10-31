import QtQuick
import QtQuick.Controls.Basic
import "."

// Shared Archive Wash popup. It keeps Ampere's whisper-caps, hard edges,
// hairlines, and sparse adaptive accent rather than borrowing a rounded
// generic application menu.
Popup {
    id: menu

    property var options: []
    property string selectedId: ""
    property int currentIndex: 0
    signal picked(string id)

    width: 208
    implicitHeight: optionColumn.implicitHeight + topPadding + bottomPadding
    padding: 0
    topPadding: 6
    bottomPadding: 6
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    background: Rectangle {
        color: Qt.alpha(Theme.bgLow, 0.98)
        border.color: Theme.washHair
        border.width: 1
        radius: 0
    }

    function selectedIndex() {
        for (var i = 0; i < options.length; ++i)
            if (options[i].id === selectedId) return i
        return 0
    }

    function choose(index) {
        if (index < 0 || index >= options.length) return
        picked(options[index].id)
        close()
    }

    function popupAt(item, px, py) {
        parent = item
        x = px
        y = py
        currentIndex = selectedIndex()
        open()
        Qt.callLater(optionColumn.forceActiveFocus)
    }

    contentItem: Column {
        id: optionColumn
        focus: true

        Keys.onUpPressed: {
            menu.currentIndex = (menu.currentIndex - 1 + menu.options.length)
                                % menu.options.length
        }
        Keys.onDownPressed: {
            menu.currentIndex = (menu.currentIndex + 1) % menu.options.length
        }
        Keys.onReturnPressed: menu.choose(menu.currentIndex)
        Keys.onEnterPressed: menu.choose(menu.currentIndex)
        Keys.onSpacePressed: menu.choose(menu.currentIndex)
        Keys.onEscapePressed: menu.close()

        Repeater {
            model: menu.options
            delegate: Item {
                id: optionRow
                required property var modelData
                required property int index
                width: menu.width
                // A gap option reads as "quiet divider then row": +9px of
                // air above the row for the hairline. Every row retains the
                // app-wide 44px minimum interaction target.
                readonly property bool gap: !!modelData.gap
                height: gap ? 53 : 44
                Accessible.role: Accessible.MenuItem
                Accessible.name: modelData.label
                Accessible.selected: menu.selectedId === modelData.id
                Accessible.focused: menu.currentIndex === index
                Accessible.onPressAction: menu.choose(optionRow.index)

                readonly property bool current: menu.currentIndex === index
                readonly property bool selected: menu.selectedId === modelData.id

                Rectangle {
                    visible: optionRow.gap
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 4
                    height: 1
                    color: Theme.washHair
                }

                Item {
                    id: rowContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 44

                    Rectangle {
                        anchors.fill: parent
                        color: optionRow.current
                               ? Qt.alpha(Theme.washInk, 0.065) : "transparent"
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1
                        height: optionRow.selected ? 20 : 0
                        color: Theme.primary
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        text: optionRow.modelData.label
                        color: optionRow.current || optionRow.selected
                               ? Theme.washInk : Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 1.8
                        font.capitalization: Font.AllUppercase
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        height: optionRow.index < menu.options.length - 1 ? 1 : 0
                        color: Theme.washHair
                    }
                }
                HoverHandler {
                    cursorShape: Qt.PointingHandCursor
                    onHoveredChanged: if (hovered) menu.currentIndex = optionRow.index
                }
                TapHandler { onTapped: menu.choose(optionRow.index) }
            }
        }
    }
}
