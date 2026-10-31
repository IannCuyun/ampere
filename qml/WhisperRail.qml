pragma ComponentBehavior: Bound

import QtQuick
import "."

// Archive Header (design/SPEC.md · Navigation). Explicit Home and browser
// history own content navigation at left. Icon-only Search and Settings close
// the band at right; Settings opens an anchored utility instrument, never a
// second navigation authority or a playback control.
FocusScope {
    id: rail

    property string currentMode: "browse"
    property bool canGoBack: false
    // The centered search field spans ~42% of the width; under 1200px it
    // would sit on top of the destination labels, so they step aside.
    property bool searchOpen: false
    property bool canGoForward: false

    signal navigate(string mode)
    signal openSearch()
    signal openAmbient()
    signal navigateBack()
    signal navigateForward()

    // Ambient's four-corner entrance only belongs to the playback room.
    property bool ambientAvailable: false

    // Compact affects room composition, but the header keeps the same explicit
    // control ownership at every supported width.
    readonly property bool compact: width < 1080

    readonly property bool menuOpen: utilityMenu.opened

    readonly property string zone: {
        var m = currentMode
        if (m === "browse" || m === "album" || m === "genres" || m === "artist"
            || m === "smart" || m === "disliked" || m === "results")
            return "library"
        if (m === "rewind" || m === "ampy")
            return "home"
        if (m === "doctor") return "settings"
        return m
    }
    readonly property var links: [
        { mode: "library", label: "Library" }
    ]
    readonly property real headerLeft: Math.max(34, width * 0.045)
    // One fixed top band keeps the complete header optically aligned and
    // clear of Gallery Monolith's sleeve even on tall desktop windows.
    readonly property real headerTop: 16

    function sectionLabel() {
        switch (zone) {
        case "home": return "Home"
        case "library": return "Library"
        case "features": return "Features"
        case "now": return "Now Playing"
        case "eq": return "Sound & EQ"
        case "settings": return "Settings"
        default: return zone
        }
    }

    // The anchored Archive Wash utility popup (ArchiveMenu language) — a
    // small explicit menu, never a full-room replacement.
    function openMenu() {
        utilityMenu.options = [
            { id: "disliked", label: "Out of Rotation" },
            { id: "doctor", label: "Library Doctor" },
            { id: "eq", label: "Sound & EQ", gap: true },
            { id: "settings", label: "Application Settings", gap: true }
        ]
        utilityMenu.selectedId = rail.zone
        utilityMenu.popupAt(settingsButton,
                             settingsButton.width - utilityMenu.width,
                             settingsButton.height + 4)
    }

    function closeMenu() {
        utilityMenu.close()
    }

    // Home is explicit. AMPERE no longer doubles as a route label.
    Item {
        id: homeButton
        objectName: "homeButton"
        z: 4
        x: rail.headerLeft
        y: rail.headerTop
        width: Math.max(44, homeLabel.implicitWidth + 24)
        height: 44
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Home"
        Accessible.description: "Open Home"
        Accessible.onPressAction: homeButton.activate()
        Keys.onReturnPressed: homeButton.activate()
        Keys.onEnterPressed: homeButton.activate()
        Keys.onSpacePressed: homeButton.activate()

        function activate() {
            rail.navigate("home")
        }

        Rectangle {
            anchors.fill: parent
            color: homeTap.pressed
                   ? Qt.alpha(Theme.primary, 0.14)
                   : homeHover.hovered ? Theme.hoverSurface : "transparent"
            border.width: homeButton.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }

        Text {
            id: homeLabel
            anchors.centerIn: parent
            text: "HOME"
            color: homeHover.hovered || homeButton.activeFocus
                   ? Theme.primary : Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: 12
            font.weight: Font.Medium
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 2.3
        }
        HoverHandler {
            id: homeHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: homeTap
            onTapped: homeButton.activate()
        }
    }

    // Library is the second stable destination even while Library is current.
    // Compact search may temporarily make it step aside to protect the field.
    Row {
        id: destinationRow
        objectName: "destinationRow"
        z: 4
        visible: !(rail.searchOpen && rail.width < 1200)
        x: homeButton.x + homeButton.width + 8
        y: homeButton.y
        spacing: 6

        Repeater {
            model: rail.links
            delegate: Item {
                id: destItem
                required property var modelData
                objectName: "dest-" + modelData.mode
                height: 44
                width: destLabel.implicitWidth + 24
                readonly property bool current: rail.zone === modelData.mode
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Accessible.onPressAction: rail.navigate(destItem.modelData.mode)
                Keys.onReturnPressed: rail.navigate(destItem.modelData.mode)
                Keys.onEnterPressed: rail.navigate(destItem.modelData.mode)
                Keys.onSpacePressed: rail.navigate(destItem.modelData.mode)

                Rectangle {
                    anchors.fill: parent
                    color: destTap.pressed
                        ? Qt.alpha(Theme.primary, 0.14)
                        : (destHover.hovered ? Theme.hoverSurface
                                             : "transparent")
                    border.width: destItem.activeFocus ? 1 : 0
                    border.color: Theme.focusRing
                    scale: destTap.pressed ? 0.965 : 1
                    Behavior on scale {
                        NumberAnimation {
                            duration: 65
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Text {
                    id: destLabel
                    anchors.centerIn: parent
                    text: destItem.modelData.label
                    color: destItem.current
                           ? Theme.washInk
                           : ((destHover.hovered || destItem.activeFocus)
                              ? Theme.washInk : Theme.washFaint)
                    font.family: Theme.displayFont
                    font.pixelSize: 12
                    font.weight: Font.Medium
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 2.3
                    Behavior on color { ColorAnimation { duration: 130 } }
                }

                Rectangle {
                    visible: destItem.current
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 8
                    height: 1
                    color: Qt.alpha(Theme.washInk, 0.55)
                }

                HoverHandler { id: destHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    id: destTap
                    onTapped: rail.navigate(destItem.modelData.mode)
                }
            }
        }
    }

    // Visible browser-style history follows both destination labels. Main owns
    // both history stacks; WhisperRail only renders availability and emits
    // navigation intent.
    Row {
        id: historyControls
        objectName: "historyControls"
        z: 4
        x: destinationRow.visible
            ? destinationRow.x + destinationRow.width + 8
            : homeButton.x + homeButton.width + 8
        y: homeButton.y
        spacing: 2

        Item {
            width: 11
            height: 44
            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 1
                height: 18
                color: Theme.washHair
            }
        }

        Repeater {
            model: [
                { back: true, label: "Back", icon: "chevron-left" },
                { back: false, label: "Forward", icon: "chevron-right" }
            ]
            delegate: Item {
                id: historyButton
                required property var modelData
                objectName: modelData.back
                    ? "historyBackButton" : "historyForwardButton"
                width: 44
                height: 44
                enabled: modelData.back ? rail.canGoBack : rail.canGoForward
                activeFocusOnTab: enabled
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Accessible.description: modelData.back
                    ? "Go to the previous page" : "Go to the next page"
                Accessible.onPressAction: historyButton.activate()

                function activate() {
                    if (!enabled) return
                    if (modelData.back) rail.navigateBack()
                    else rail.navigateForward()
                }

                Keys.onReturnPressed: historyButton.activate()
                Keys.onEnterPressed: historyButton.activate()
                Keys.onSpacePressed: historyButton.activate()

                Rectangle {
                    anchors.fill: parent
                    color: historyTap.pressed
                        ? Qt.alpha(Theme.primary, 0.14)
                        : (historyHover.hovered ? Theme.hoverSurface
                                                : "transparent")
                    border.width: historyButton.activeFocus ? 1 : 0
                    border.color: Theme.focusRing
                    scale: historyTap.pressed ? 0.965 : 1
                    Behavior on scale {
                        NumberAnimation {
                            duration: 65
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Icon {
                    anchors.centerIn: parent
                    name: historyButton.modelData.icon
                    size: 18
                    color: !historyButton.enabled ? Theme.washFaint
                         : (historyButton.activeFocus || historyHover.hovered
                            ? Theme.primary : Theme.washMuted)
                }

                HoverHandler {
                    id: historyHover
                    enabled: historyButton.enabled
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler {
                    id: historyTap
                    enabled: historyButton.enabled
                    onTapped: historyButton.activate()
                }
            }
        }
    }

    // Search stays direct. Settings is the sole utility popup.
    Row {
        id: utilityRow
        z: 4
        x: parent.width - width - 34
        y: rail.headerTop
        spacing: 4

        Item {
            width: 44
            height: 44
            visible: rail.ambientAvailable
            activeFocusOnTab: visible
            Accessible.role: Accessible.Button
            Accessible.name: "Enter ambient mode"
            Accessible.onPressAction: rail.openAmbient()
            Keys.onReturnPressed: rail.openAmbient()
            Keys.onSpacePressed: rail.openAmbient()
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: parent.activeFocus ? 1 : 0
                border.color: Theme.focusRing
            }
            Icon {
                anchors.centerIn: parent
                name: "fullscreen"
                size: 23
                color: ambientHover.hovered ? Theme.washInk : Theme.washMuted
            }
            HoverHandler { id: ambientHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: rail.openAmbient() }
        }

        Item {
            objectName: "searchButton"
            width: 44
            height: 44
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Search"
            Accessible.onPressAction: rail.openSearch()
            Keys.onReturnPressed: rail.openSearch()
            Keys.onSpacePressed: rail.openSearch()
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: parent.activeFocus ? 1 : 0
                border.color: Theme.focusRing
            }
            Icon {
                anchors.centerIn: parent
                name: "search"
                size: 23
                color: searchHover.hovered ? Theme.washInk : Theme.washMuted
            }
            HoverHandler { id: searchHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: rail.openSearch() }
        }

        Item {
            id: settingsButton
            objectName: "settingsButton"
            width: 44
            height: 44
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Settings"
            Accessible.onPressAction: rail.openMenu()
            Keys.onReturnPressed: rail.openMenu()
            Keys.onEnterPressed: rail.openMenu()
            Keys.onSpacePressed: rail.openMenu()

            Rectangle {
                anchors.fill: parent
                color: menuTap.pressed
                    ? Qt.alpha(Theme.primary, 0.14)
                    : ((menuHover.hovered || rail.menuOpen) ? Theme.hoverSurface
                                                            : "transparent")
                border.width: settingsButton.activeFocus ? 1 : 0
                border.color: Theme.focusRing
                scale: menuTap.pressed ? 0.965 : 1
                Behavior on scale {
                    NumberAnimation { duration: 65; easing.type: Easing.OutCubic }
                }
            }

            Icon {
                anchors.centerIn: parent
                name: "gear"
                size: 22
                color: (menuHover.hovered || settingsButton.activeFocus
                        || rail.menuOpen) ? Theme.washInk : Theme.washMuted
            }

            Rectangle {
                visible: rail.menuOpen
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                height: 1
                color: Theme.primary
            }

            HoverHandler { id: menuHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { id: menuTap; onTapped: rail.openMenu() }
        }
    }

    ArchiveMenu {
        id: utilityMenu
        objectName: "utilityMenu"
        onPicked: id => rail.navigate(id)
    }
}
