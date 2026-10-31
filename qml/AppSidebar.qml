import QtQuick
import QtQuick.Layouts
import "."

// Signal Rail: one quiet navigation instrument. No grouped cards, badges in
// bubbles, or selected pills; position, type weight, and a single luminous
// rule do the work.
Rectangle {
    id: rail
    property string currentMode: "browse"
    property bool queueOpen: false
    signal navigate(string mode, string arg)
    signal toggleQueue()
    color: Qt.alpha(Theme.navSurface, 0.96)

    property var primaryRows: [
        {mode: "home", label: "Home", icon: "sparkle"},
        {mode: "library", label: "Library", icon: "grid"},
        {mode: "now", label: "Now playing", icon: "wave"},
        {mode: "features", label: "Features", icon: "sparkle"}
    ]

    function pick(mode) {
        navigate(mode, "")
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 20
        anchors.rightMargin: 16
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 30
            spacing: 12
            Icon {
                name: "wave"; size: 25; color: Theme.primary
            }
            Column {
                spacing: -2
                Text { text: "AMPERE"; color: Theme.text; font.family: Theme.displayFont; font.pixelSize: Theme.fsEmph; font.weight: Font.DemiBold; font.letterSpacing: 3 }
                Text { text: "LOCAL / ALIVE"; color: Theme.textSubtle; font.family: Theme.font; font.pixelSize: Theme.fsMicro; font.letterSpacing: 1.4 }
            }
        }

        Repeater {
            model: rail.primaryRows
            delegate: Item {
                id: link
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                readonly property bool selected: rail.currentMode === modelData.mode
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Keys.onReturnPressed: rail.pick(modelData.mode)
                Keys.onSpacePressed: rail.pick(modelData.mode)

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSm
                    color: "transparent"
                    border.width: link.activeFocus ? 2 : 0
                    border.color: link.activeFocus ? Theme.focusRing : "transparent"
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: link.selected ? 18 : hover.hovered ? 10 : 0
                    height: 1
                    color: Theme.primary
                    Behavior on width { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutCubic } }
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: link.selected || hover.hovered ? 28 : 10
                    anchors.rightMargin: 4
                    spacing: 11
                    Behavior on anchors.leftMargin { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutCubic } }
                    Icon {
                        name: link.modelData.icon
                        size: 16
                        color: link.selected ? Theme.primary : Theme.textSubtle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: link.modelData.label
                        color: link.selected ? Theme.text : hover.hovered ? Theme.textDim : Theme.textMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                        font.weight: link.selected ? Font.DemiBold : Font.Normal
                    }
                }
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: rail.pick(link.modelData.mode) }
            }
        }

        Item { Layout.fillHeight: true }
        Repeater {
            model: [{mode: "eq", label: "Sound & EQ", icon: "eq"}, {mode: "settings", label: "Settings", icon: "gear"}]
            delegate: Item {
                id: utility
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Keys.onReturnPressed: rail.navigate(modelData.mode, "")
                Keys.onSpacePressed: rail.navigate(modelData.mode, "")
                readonly property bool selected: rail.currentMode === modelData.mode
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSm
                    color: "transparent"
                    border.width: utility.activeFocus ? 2 : 0
                    border.color: utility.activeFocus ? Theme.focusRing : "transparent"
                }
                RowLayout {
                    anchors.fill: parent
                    spacing: 11
                    Icon {
                        name: utility.modelData.icon
                        size: 16
                        color: utility.selected ? Theme.primary : Theme.textSubtle
                    }
                    Text {
                        text: utility.modelData.label
                        color: utility.selected ? Theme.text : Theme.textMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        font.weight: utility.selected ? Font.DemiBold : Font.Normal
                    }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: rail.navigate(utility.modelData.mode, "") }
            }
        }
    }
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Qt.alpha(Theme.primary, 0.12) }
}
