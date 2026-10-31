import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Rectangle {
    id: pane
    // Playback B queue voice: wash panel (design/SPEC.md sprint-lock)
    color: Qt.alpha(Theme.navSurface, 0.92)
    property string filterText: ""
    signal closeRequested()

    readonly property string sessionLabel: backend.repeat
        ? (backend.single ? "REPEAT SONG" : "LOOP QUEUE")
        : backend.djOn ? "DJ SET"
        : backend.moodRadioOn !== "" ? "MOOD RADIO"
        : backend.smartMixOn ? "AUTO-MIX"
        : backend.autoplayOn ? "AUTOPLAY" : "MANUAL QUEUE"
    readonly property int remainingCount: backend.queueRemainingCount
    readonly property real remainingSeconds: backend.queueRemainingSeconds
    readonly property var visQueue: pane.visible ? backend.queue.filter(function(song) {
        if (song.file && song.file.charAt(0) === "/")
            return false
        var query = pane.filterText.trim().toLowerCase()
        return query === "" || ((song.title || "") + " " + (song.artist || "") + " "
            + (song.album || "")).toLowerCase().indexOf(query) >= 0
    }) : []
    readonly property int playPos: backend.visibleQueuePlayPos

    function durationLabel(seconds) {
        var minutes = Math.round(seconds / 60)
        if (minutes < 60)
            return minutes + " min"
        var hours = Math.floor(minutes / 60)
        var rest = minutes - hours * 60
        return hours + " h" + (rest ? " " + rest + " min" : "")
    }
    function visIndexOfPlaying() {
        for (var i = 0; i < visQueue.length; i++) {
            if (visQueue[i].pos === playPos)
                return i
        }
        return -1
    }
    function showSave() {
        saveRow.visible = true
        saveName.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Item {
            id: header
            Layout.fillWidth: true
            Layout.preferredHeight: compact ? 194 : 142
            // The drawer is capped near 430 px on a full room, but becomes a
            // wider session workspace when the application itself is compact.
            readonly property bool compact: width < 780

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 24
                anchors.top: parent.top
                anchors.topMargin: 20
                spacing: 5

                Text {
                    text: "Up next"
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: 27
                    font.weight: Font.Light
                    font.letterSpacing: -0.8
                }
                Text {
                    text: pane.sessionLabel + " / " + pane.remainingCount + " UP NEXT / "
                        + pane.durationLabel(pane.remainingSeconds).toUpperCase()
                    color: Theme.washMuted
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 1.8
                }
            }

            Row {
                id: queueActions
                anchors.right: header.compact ? undefined : parent.right
                anchors.rightMargin: 60
                anchors.left: header.compact ? parent.left : undefined
                anchors.leftMargin: 18
                y: header.compact ? 74 : 18
                spacing: 4

                Repeater {
                    model: [
                        { label: "NOW", name: "Jump to the playing track", go: function() {
                            var index = pane.visIndexOfPlaying()
                            if (index >= 0)
                                list.positionViewAtIndex(index, ListView.Center)
                        } },
                        { label: "TRIM", name: "Remove tracks already played", go: function() { backend.trimPlayed() } },
                        { label: "SAVE", name: "Save queue as a playlist", go: function() { pane.showSave() } },
                        { label: "CLEAR", name: "Clear the queue", go: function() { backend.clearQueue() } }
                    ]

                    delegate: Item {
                        id: action
                        required property var modelData
                        width: 66
                        height: 44
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.name
                        Accessible.onPressAction: modelData.go()

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusSm
                            color: actionHover.hovered ? Qt.alpha(Theme.primary, 0.08) : "transparent"
                            border.width: action.activeFocus ? 1 : 0
                            border.color: Theme.primary
                        }
                        Text {
                            anchors.centerIn: parent
                            text: action.modelData.label
                            color: action.activeFocus || actionHover.hovered ? Theme.washInk : Theme.washMuted
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2
                        }
                        HoverHandler { id: actionHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: action.modelData.go() }
                        Keys.onReturnPressed: action.modelData.go()
                        Keys.onSpacePressed: action.modelData.go()
                    }
                }
            }

            Item {
                id: closeAction
                anchors.top: parent.top
                anchors.topMargin: 14
                anchors.right: parent.right
                anchors.rightMargin: 12
                width: 44
                height: 44
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Close queue"
                Accessible.onPressAction: pane.closeRequested()

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSm
                    color: closeHover.hovered ? Theme.hoverSurface : "transparent"
                    border.width: closeAction.activeFocus ? 2 : 0
                    border.color: Theme.focusRing
                }
                Icon {
                    anchors.centerIn: parent
                    name: "close"
                    size: 18
                    color: closeAction.activeFocus || closeHover.hovered
                        ? Theme.primary : Theme.textMuted
                }
                HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: pane.closeRequested() }
                Keys.onReturnPressed: pane.closeRequested()
                Keys.onSpacePressed: pane.closeRequested()
            }

            RowLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 24
                anchors.rightMargin: 20
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 15
                spacing: 10

                Icon { name: "search"; color: Theme.textMuted; size: 18 }
                TextField {
                    id: queueSearch
                    Layout.fillWidth: true
                    activeFocusOnTab: true
                    Accessible.name: "Filter this queue"
                    background: Rectangle {
                        color: "transparent"
                        border.width: queueSearch.activeFocus ? 1 : 0
                        border.color: Theme.primary
                    }
                    color: Theme.text
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    placeholderText: "FILTER THIS SESSION"
                    placeholderTextColor: Theme.textSubtle
                    onTextChanged: pane.filterText = text
                }
            }
        }

        RowLayout {
            id: saveRow
            visible: false
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 20
            Layout.bottomMargin: 12
            spacing: 12

            function commit() {
                if (!saveName.text.trim())
                    return
                if (!backend.saveQueueAs(
                        saveName.text, parseInt(saveCount.text) || 0))
                    return
                saveName.text = ""
                saveCount.text = ""
                visible = false
            }

            TextField {
                id: saveName
                Layout.fillWidth: true
                activeFocusOnTab: true
                Accessible.name: "Playlist name"
                background: null
                color: Theme.text
                font.family: Theme.font
                placeholderText: "PLAYLIST NAME"
                onAccepted: saveRow.commit()
            }
            TextField {
                id: saveCount
                Layout.preferredWidth: 64
                activeFocusOnTab: true
                Accessible.name: "Maximum tracks to save"
                background: null
                color: Theme.text
                font.family: Theme.font
                placeholderText: "ALL"
                validator: IntValidator { bottom: 1; top: 99999 }
                onAccepted: saveRow.commit()
            }
            Item {
                id: saveAction
                Layout.preferredWidth: 92
                Layout.preferredHeight: 44
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Save playlist"
                Accessible.onPressAction: saveRow.commit()

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSm
                    color: saveHover.hovered ? Qt.alpha(Theme.primary, 0.08) : "transparent"
                    border.width: saveAction.activeFocus ? 1 : 0
                    border.color: Theme.primary
                }
                Text {
                    anchors.centerIn: parent
                    text: "SAVE  →"
                    color: Theme.primary
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    font.letterSpacing: 2
                }
                HoverHandler { id: saveHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: saveRow.commit() }
                Keys.onReturnPressed: saveRow.commit()
                Keys.onSpacePressed: saveRow.commit()
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.alpha(Theme.text, 0.16) }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: pane.visQueue
            readonly property int rowH: 68
            ScrollBar.vertical: ArchiveScrollBar {}

            function followPlaying() {
                var index = pane.visIndexOfPlaying()
                if (index >= 0 && !moving)
                    positionViewAtIndex(index, ListView.Visible)
            }
            Connections {
                target: backend
                function onSongChanged() { list.followPlaying() }
            }

            delegate: Item {
                id: track
                required property var modelData
                required property int index
                width: list.width
                height: list.rowH
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Play " + (modelData.title || "Unknown title") + " by "
                    + (modelData.artist || "Unknown artist")
                Accessible.onPressAction: backend.playPosition(modelData.pos)

                Rectangle {
                    anchors.fill: parent
                    color: track.activeFocus ? Qt.alpha(Theme.primary, 0.08) : "transparent"
                    border.width: track.activeFocus ? 1 : 0
                    border.color: Theme.primary
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Qt.alpha(Theme.text, 0.08)
                }
                Rectangle {
                    visible: modelData.pos === pane.playPos
                    anchors.left: parent.left
                    width: 2
                    height: parent.height
                    color: Theme.primary
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 24
                    anchors.rightMargin: 12
                    spacing: 12

                    Item {
                        Layout.preferredWidth: 26
                        Layout.preferredHeight: 24
                        Icon {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            visible: modelData.pos === pane.playPos
                            name: "play"
                            color: Theme.primary
                            size: 16
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            visible: modelData.pos !== pane.playPos
                            text: String(index + 1).padStart(2, "0")
                            color: Theme.textSubtle
                            font.family: Theme.font
                            font.pixelSize: Theme.fsMicro
                        }
                    }
                    MediaArtwork {
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        kind: "album"
                        source: modelData.file
                                ? "image://art/" + encodeURIComponent(modelData.file) : ""
                    }
                    Column {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            width: parent.width
                            text: modelData.title || "Unknown title"
                            elide: Text.ElideRight
                            color: modelData.pos === pane.playPos ? Theme.primary : Theme.text
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: (modelData.artist || "Unknown artist")
                                + (modelData.album ? "  /  " + modelData.album : "")
                            elide: Text.ElideRight
                            color: Theme.textMuted
                            font.family: Theme.font
                            font.pixelSize: Theme.fsSmall
                        }
                    }
                    Text {
                        text: Theme.fmtTime(modelData.duration || 0)
                        color: Theme.textSubtle
                        font.family: Theme.font
                        font.pixelSize: Theme.fsMicro
                    }
                    Item {
                        id: removeAction
                        Layout.preferredWidth: 44
                        Layout.preferredHeight: 44
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Remove " + (modelData.title || "track") + " from queue"
                        Accessible.onPressAction: backend.removePosition(modelData.pos)

                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusSm
                            color: removeHover.hovered ? Qt.alpha(Theme.secondary, 0.08) : "transparent"
                            border.width: removeAction.activeFocus ? 1 : 0
                            border.color: Theme.secondary
                        }
                        Icon {
                            anchors.centerIn: parent
                            name: "close"
                            color: removeAction.activeFocus || removeHover.hovered
                                ? Theme.secondary : Theme.textSubtle
                            size: 18
                        }
                        HoverHandler { id: removeHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.removePosition(modelData.pos) }
                        Keys.onReturnPressed: backend.removePosition(modelData.pos)
                        Keys.onSpacePressed: backend.removePosition(modelData.pos)
                    }
                }
                TapHandler {
                    acceptedButtons: Qt.LeftButton
                    onDoubleTapped: backend.playPosition(modelData.pos)
                }
                Keys.onReturnPressed: backend.playPosition(modelData.pos)
                Keys.onSpacePressed: backend.playPosition(modelData.pos)
            }

            Item {
                anchors.centerIn: parent
                visible: backend.queueLength === 0
                width: parent.width - 48
                height: 140
                Column {
                    anchors.centerIn: parent
                    spacing: 10
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "NO SIGNAL YET"
                        color: Theme.text
                        font.family: Theme.displayFont
                        font.pixelSize: 24
                        font.weight: Font.DemiBold
                        font.letterSpacing: 3
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Play an album, build a session, or let Ampere choose."
                        color: Theme.textMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                    }
                }
            }
        }
    }
}
