import QtQuick
import QtQuick.Controls.Basic
import "."

// Tag repair — the page a tag finding opens into (Iann, 2026-08-21).
// The record's art on the left, every editable tag on the right with the
// fault named beside the field it belongs to, and the finding set walked with
// the arrows at the screen edges. Ampere writes only what he types, only when
// he saves: MetadataService keeps a one-time recovery snapshot, holds a write
// lock, and verifies every field after the save before reporting success.
Item {
    id: repair
    property var findings: []
    property int index: 0
    property bool active: false
    property var metadata: ({})
    property bool loading: false
    property bool saving: false
    property bool dirty: false
    signal closed()

    readonly property var finding: (index >= 0 && index < findings.length)
                                   ? findings[index] : ({})
    readonly property string file: String(finding.file || "")
    readonly property var missing: finding.missing || []
    // Below this the record and the form cannot sit side by side and still
    // leave a usable field to type in (SPEC row 207).
    readonly property bool compact: width < 900
    readonly property bool editable: metadata.editable === true

    // Every field, its label, and the fault to state when it is empty.
    readonly property var fields: [
        { key: "title",       label: "TITLE",        issue: "NEEDS TITLE TAG" },
        { key: "artist",      label: "ARTIST",       issue: "NEEDS ARTIST TAG" },
        { key: "album",       label: "ALBUM",        issue: "NEEDS ALBUM TAG" },
        { key: "albumartist", label: "ALBUM ARTIST", issue: "NEEDS ALBUM ARTIST TAG" },
        { key: "genre",       label: "GENRE",        issue: "" },
        { key: "date",        label: "DATE",         issue: "" },
        { key: "tracknumber", label: "TRACK",        issue: "" }
    ]
    property var edited: ({})

    function open(rows, start) {
        findings = rows || []
        index = Math.max(0, Math.min(start || 0, findings.length - 1))
        active = true
        load()
    }
    function load() {
        metadata = ({}); edited = ({}); dirty = false; loading = true
        if (!file || !backend.requestTrackMetadata(file)) {
            loading = false
            metadata = ({ editable: false, error: "This file could not be read" })
        }
    }
    function step(delta) {
        if (saving || findings.length === 0) return
        index = (index + delta + findings.length) % findings.length
        load()
    }
    function valueFor(key) {
        return edited[key] !== undefined ? edited[key] : (metadata[key] || "")
    }
    function issueFor(key, spec) {
        if (!editable) return ""
        return valueFor(key) === "" ? spec : ""
    }
    function save() {
        if (!editable || saving) return
        var values = {}
        for (var i = 0; i < fields.length; ++i) {
            var key = fields[i].key
            values[key] = valueFor(key)
        }
        saving = true
        if (!backend.updateTrackMetadata(file, values)) saving = false
    }

    Connections {
        target: backend
        function onTrackMetadataReady(resultFile, result) {
            if (!repair.active || resultFile !== repair.file) return
            repair.metadata = result
            repair.loading = false
        }
        function onTrackMetadataUpdateFinished(resultFile, success) {
            if (!repair.active || resultFile !== repair.file) return
            repair.saving = false
            if (success) { repair.dirty = false; repair.load() }
        }
    }

    ArchiveWash {
        anchors.fill: parent
        // The room follows the PLAYING song, not the file being examined
        // (Iann, 2026-08-21): the persistent player sits right below this
        // page, so a room showing a different record than the mini player
        // reads as a mistake. Album View is the opposite case — there the
        // record IS the subject.
        veil: 0.74
        fitStrength: 0.0
    }

    // ---- edge navigation: one target per side, full height, unmissable ----
    component EdgeArrow: Item {
        id: edge
        property int delta: -1
        property string glyph: "‹"
        width: 72
        height: parent ? parent.height : 0
        enabled: repair.findings.length > 1 && !repair.saving
        activeFocusOnTab: enabled
        Accessible.role: Accessible.Button
        Accessible.name: delta < 0 ? "Previous file needing tags"
                                   : "Next file needing tags"
        Accessible.onPressAction: repair.step(delta)
        Keys.onReturnPressed: repair.step(delta)
        Keys.onSpacePressed: repair.step(delta)
        Rectangle {
            anchors.fill: parent
            color: edgeHover.hovered ? Qt.alpha(Theme.washInk, 0.05) : "transparent"
        }
        Text {
            anchors.centerIn: parent
            text: edge.glyph
            color: edge.enabled
                   ? (edgeHover.hovered || edge.activeFocus ? Theme.washInk : Theme.washFaint)
                   : Qt.alpha(Theme.washFaint, 0.3)
            font.family: Theme.displayFont
            font.pixelSize: 44
        }
        HoverHandler { id: edgeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: repair.step(edge.delta) }
    }

    EdgeArrow {
        anchors.left: parent.left; delta: -1; glyph: "‹"
        width: repair.compact ? 44 : 72
    }
    EdgeArrow {
        anchors.right: parent.right; delta: 1; glyph: "›"
        width: repair.compact ? 44 : 72
    }

    Keys.onLeftPressed: repair.step(-1)
    Keys.onRightPressed: repair.step(1)
    Keys.onEscapePressed: repair.closed()

    // ---- the record ----
    Item {
        id: stage
        anchors.left: parent.left
        anchors.leftMargin: repair.compact ? 56 : 92
        anchors.right: parent.right
        anchors.rightMargin: repair.compact ? 56 : 92
        anchors.top: parent.top
        anchors.topMargin: Math.max(76, repair.height * 0.045)
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 28

        readonly property real artSide: repair.compact
            ? Math.min(132, stage.width * 0.34)
            : Math.max(160, Math.min(height * 0.62, stage.width * 0.34))

        Column {
            id: artColumn
            width: stage.artSide
            spacing: 18
            MediaArtwork {
                width: stage.artSide
                height: stage.artSide
                kind: "album"
                source: repair.file
                        ? "image://art/" + encodeURIComponent(repair.file) : ""
            }
            Text {
                width: stage.artSide
                text: repair.file
                color: Theme.washFaint
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
            }
        }

        Column {
            id: form
            anchors.left: repair.compact ? parent.left : artColumn.right
            anchors.leftMargin: repair.compact ? 0 : 52
            anchors.right: parent.right
            anchors.top: repair.compact ? artColumn.bottom : parent.top
            anchors.topMargin: repair.compact ? 22 : 0
            spacing: 0

            Row {
                spacing: 16
                Text {
                    text: "TAG REPAIR"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2.8
                }
                Text {
                    objectName: "tagRepairPosition"
                    text: (repair.index + 1) + " OF " + repair.findings.length
                    color: Theme.primary
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2.8
                }
            }
            Text {
                topPadding: 10
                bottomPadding: 20
                width: form.width
                text: repair.valueFor("title") !== ""
                      ? repair.valueFor("title")
                      : repair.file.split("/").pop()
                color: Theme.washInk
                font.family: Theme.displayFont
                font.pixelSize: repair.compact ? 30 : 44
                elide: Text.ElideRight
            }

            Text {
                visible: !repair.editable && !repair.loading
                bottomPadding: 16
                width: form.width
                text: repair.metadata.error
                      || "Tag editing currently supports FLAC files."
                color: Theme.error
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }

            Repeater {
                model: repair.editable ? repair.fields : []
                delegate: TagField {
                    required property var modelData
                    width: form.width
                    label: modelData.label
                    field: modelData.key
                    value: repair.valueFor(modelData.key)
                    issue: repair.issueFor(modelData.key, modelData.issue)
                    onEdited: text => {
                        var next = repair.edited
                        next[modelData.key] = text
                        repair.edited = next
                        repair.dirty = true
                    }
                }
            }

            Row {
                topPadding: 24
                spacing: 30
                WashLine {
                    label: repair.saving ? "Saving…" : "Save tags →"
                    primaryAction: true
                    visible: repair.editable
                    onActivated: repair.save()
                }
                WashLine {
                    label: "Revert"
                    visible: repair.editable && repair.dirty
                    onActivated: { repair.edited = ({}); repair.dirty = false }
                }
                WashLine { label: "Done"; onActivated: repair.closed() }
            }

            Text {
                topPadding: 18
                width: form.width
                text: "Ampere keeps a one-time recovery copy of this file's "
                      + "original tags before its first edit, and verifies every "
                      + "field after saving."
                color: Theme.washFaint
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.Wrap
            }
        }
    }
}
