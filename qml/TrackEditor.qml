import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Item {
    id: editor
    property string file: ""
    property var metadata: ({})
    property bool loading: false
    property bool saving: false
    visible: false
    z: 80

    function open(track) {
        file = track.file || ""
        metadata = ({})
        loading = true
        saving = false
        visible = true
        if (!backend.requestTrackMetadata(file)) {
            loading = false
            metadata = ({ editable: false,
                          error: "Track information could not be read while Ampere is closing" })
        }
    }
    function close() {
        if (saving) return
        visible = false
        loading = false
        file = ""
        metadata = ({})
    }

    Connections {
        target: backend
        function onTrackMetadataReady(resultFile, result) {
            if (!editor.visible || resultFile !== editor.file) return
            editor.metadata = result
            editor.loading = false
            titleField.text = result.title || ""
            artistField.text = result.artist || ""
            albumField.text = result.album || ""
            albumArtistField.text = result.albumartist || ""
            genreField.text = result.genre || ""
            dateField.text = result.date || ""
            trackField.text = result.tracknumber || ""
        }
        function onTrackMetadataUpdateFinished(resultFile, success) {
            if (!editor.visible || resultFile !== editor.file) return
            editor.saving = false
            if (success) editor.close()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.alpha("#000000", 0.62)
        TapHandler { enabled: !editor.saving; onTapped: editor.close() }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(720, editor.width - 48)
        height: form.height + 40
        radius: Theme.radiusLg
        color: Theme.raisedSurface
        border.width: 0

        ColumnLayout {
            id: form
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Column {
                    Layout.fillWidth: true
                    Text {
                        text: "Edit track information"
                        color: Theme.text
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width
                        text: editor.file
                        elide: Text.ElideMiddle
                        color: Theme.textSubtle
                        font.family: Theme.font
                        font.pixelSize: Theme.fsMicro
                    }
                }
                GlowButton {
                    icon: "close"; tip: editor.saving ? "Saving track information" : "Close"
                    enabled: !editor.saving
                    onClicked: editor.close()
                }
            }

            Text {
                Layout.fillWidth: true
                visible: editor.loading
                text: "Reading track information…"
                color: Theme.textSubtle
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }

            Text {
                Layout.fillWidth: true
                visible: !editor.loading && editor.metadata.editable === false
                text: editor.metadata.error || "This file cannot be edited"
                wrapMode: Text.WordWrap
                color: Theme.error
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }

            GridLayout {
                visible: !editor.loading && editor.metadata.editable === true
                Layout.fillWidth: true
                columns: editor.width < 680 ? 1 : 2
                columnSpacing: 12
                rowSpacing: 10

                EditorField { id: titleField; Layout.fillWidth: true; label: "TITLE" }
                EditorField { id: artistField; Layout.fillWidth: true; label: "ARTIST" }
                EditorField { id: albumField; Layout.fillWidth: true; label: "ALBUM" }
                EditorField { id: albumArtistField; Layout.fillWidth: true; label: "ALBUM ARTIST" }
                EditorField { id: genreField; Layout.fillWidth: true; label: "GENRE" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    EditorField { id: dateField; Layout.fillWidth: true; label: "DATE" }
                    EditorField { id: trackField; Layout.preferredWidth: 90; label: "TRACK" }
                }
            }

            Text {
                visible: !editor.loading && editor.metadata.editable === true
                Layout.fillWidth: true
                text: "The original tags are backed up before the first edit. Audio data is never rewritten."
                color: Theme.textSubtle
                font.family: Theme.font
                font.pixelSize: Theme.fsMicro
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                visible: !editor.loading && editor.metadata.editable === true
                Item { Layout.fillWidth: true }
                GlowButton { label: "Cancel"; enabled: !editor.saving; onClicked: editor.close() }
                GlowButton {
                    icon: "save"; label: editor.saving ? "Saving…" : "Save changes"
                    active: true; enabled: !editor.saving
                    onClicked: {
                        editor.saving = backend.updateTrackMetadata(editor.file, {
                            title: titleField.text,
                            artist: artistField.text,
                            album: albumField.text,
                            albumartist: albumArtistField.text,
                            genre: genreField.text,
                            date: dateField.text,
                            tracknumber: trackField.text
                        })
                    }
                }
            }
        }
    }

    component EditorField: ColumnLayout {
        property alias text: input.text
        property string label: ""
        spacing: 4
        Text {
            text: parent.label
            color: Theme.textSubtle
            font.family: Theme.font
            font.pixelSize: Theme.fsMicro
            font.letterSpacing: 1.5
        }
        TextField {
            id: input
            Layout.fillWidth: true
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            selectByMouse: true
            Accessible.name: parent.label
            background: Rectangle {
                implicitHeight: 38
                radius: Theme.radius
                color: Theme.raisedSurface
                border.color: input.activeFocus ? Theme.primary : Theme.divider
            }
        }
    }
}
