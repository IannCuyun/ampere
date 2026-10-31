pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// The kept mixes. Every one is something Iann actually built, so the shelf
// states what it is, replays it exactly, or ports it into a real playlist
// unchanged (Iann, 2026-08-22).
Item {
    id: shelf
    property bool compact: false
    property var mixes: backend.soundMixes

    function when(seconds) {
        if (!seconds) return ""
        var age = (Date.now() / 1000) - seconds
        if (age < 3600) return Math.max(1, Math.round(age / 60)) + " MIN AGO"
        if (age < 86400) return Math.round(age / 3600) + " HR AGO"
        return Math.round(age / 86400) + " DAYS AGO"
    }

    Text {
        id: emptyLine
        objectName: "mixShelfEmpty"
        visible: shelf.mixes.length === 0
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.topMargin: 24
        text: "Nothing built yet. A mix is kept here the moment you build one."
        color: Theme.washMuted
        font.family: Theme.font
        font.pixelSize: Theme.fsBody
        font.weight: Font.Light
    }

    ListView {
        id: list
        objectName: "mixShelfList"
        visible: shelf.mixes.length > 0
        anchors.fill: parent
        anchors.topMargin: 12
        clip: true
        spacing: 0
        model: shelf.mixes
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ArchiveScrollBar {}

        delegate: Item {
            id: row
            required property var modelData
            required property int index
            objectName: "mixRow_" + index
            width: list.width
            height: naming ? 132 : 88
            property bool naming: false

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.washHair
            }

            Text {
                id: mixLabel
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.topMargin: 12
                text: row.modelData.label || row.modelData.character
                color: Theme.washInk
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsEmph
                font.letterSpacing: 1.6
            }
            Text {
                id: mixFacts
                anchors.left: parent.left
                anchors.top: mixLabel.bottom
                anchors.topMargin: 4
                text: (row.modelData.files || []).length + " TRACKS"
                      + (shelf.when(row.modelData.created)
                         ? "  ·  " + shelf.when(row.modelData.created) : "")
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.2
            }

            Row {
                id: mixActions
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 6
                spacing: shelf.compact ? 18 : 26

                WashLine {
                    objectName: "mixPlay_" + row.index
                    label: "Play →"
                    primaryAction: true
                    onActivated: backend.playSoundMix(row.modelData.id)
                }
                WashLine {
                    objectName: "mixSave_" + row.index
                    label: "Save as playlist"
                    onActivated: {
                        row.naming = !row.naming
                        if (row.naming) nameField.forceActiveFocus()
                    }
                }
                WashLine {
                    objectName: "mixForget_" + row.index
                    label: "Forget"
                    onActivated: backend.forgetSoundMix(row.modelData.id)
                }
            }

            // Naming is the one thing that needs a field, so it appears only
            // when asked for and takes the row's own width.
            Item {
                id: namingLane
                visible: row.naming
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: mixFacts.bottom
                anchors.topMargin: 10
                height: 44

                TextField {
                    id: nameField
                    objectName: "mixNameField_" + row.index
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(360, parent.width - saveLine.width - 24)
                    height: 40
                    placeholderText: "Playlist name"
                    color: Theme.washInk
                    placeholderTextColor: Theme.washFaint
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                    background: Rectangle {
                        color: "transparent"
                        border.width: nameField.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.washHair
                        }
                    }
                    onAccepted: saveLine.activated()
                }
                WashLine {
                    id: saveLine
                    objectName: "mixNameConfirm_" + row.index
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: "Keep it"
                    primaryAction: true
                    onActivated: {
                        if (nameField.text.trim() === "")
                            return
                        backend.saveSoundMixAs(row.modelData.id, nameField.text)
                        nameField.text = ""
                        row.naming = false
                    }
                }
            }
        }
    }
}
