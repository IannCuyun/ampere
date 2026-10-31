import QtQuick
import QtQuick.Controls.Basic
import "."

// Version comparison — the page a duplicate finding opens into (Iann,
// 2026-08-21). Two recordings that resolve to one identity are laid out side
// by side with every fact that decides whether they really are the same
// performance: container, bitrate, sample rate, depth, size, duration, plays,
// and the tags. A value that DIFFERS between versions is marked, because a
// difference is the whole reason to look.
//
// Ampere never merges or deletes here. Choosing a version sets which one
// generated sessions prefer; every sibling stays in the library.
Item {
    id: compare
    property var groups: []
    property int index: 0
    property bool active: false
    property var rows: []
    property bool loading: false
    signal closed()

    readonly property var group: (index >= 0 && index < groups.length)
                                 ? groups[index] : ({})
    readonly property var members: group.files || []
    readonly property string groupTitle: String(group.title || "")
    readonly property string groupArtist: String(group.artist || "")
    // Two versions side by side IS the page, so compact tightens the columns
    // rather than stacking them — stacked, nothing can be compared at a
    // glance (SPEC row 207).
    readonly property bool compact: width < 900

    readonly property var facts: [
        { key: "format",     label: "FORMAT" },
        { key: "kbps",       label: "BITRATE",     unit: " kbps" },
        { key: "sampleRate", label: "SAMPLE RATE", unit: " Hz" },
        { key: "bitDepth",   label: "BIT DEPTH",   unit: "-bit" },
        { key: "channels",   label: "CHANNELS" },
        { key: "bytes",      label: "SIZE" },
        { key: "duration",   label: "LENGTH" },
        { key: "plays",      label: "PLAYS" },
        { key: "album",      label: "ALBUM" },
        { key: "albumartist",label: "ALBUM ARTIST" },
        { key: "genre",      label: "GENRE" },
        { key: "year",       label: "YEAR" }
    ]

    function open(rowsIn, start) {
        groups = rowsIn || []
        index = Math.max(0, Math.min(start || 0, groups.length - 1))
        active = true
        load()
    }
    function load() {
        rows = []
        loading = true
        var files = []
        for (var i = 0; i < members.length; ++i) files.push(members[i].file)
        if (!backend.requestVersionDetails(files)) loading = false
    }
    function step(delta) {
        if (groups.length === 0) return
        index = (index + delta + groups.length) % groups.length
        load()
    }
    function display(row, key) {
        var value = row[key]
        if (key === "duration") return Theme.fmtTime(Number(value || 0))
        if (key === "bytes") {
            var mb = Number(value || 0) / 1048576
            return mb >= 1 ? mb.toFixed(1) + " MB"
                           : Math.round(Number(value || 0) / 1024) + " KB"
        }
        if (value === "" || value === 0 || value === undefined) return "—"
        for (var i = 0; i < facts.length; ++i)
            if (facts[i].key === key && facts[i].unit)
                return String(value) + facts[i].unit
        return String(value)
    }
    // A fact only matters here when the versions disagree about it.
    function differs(key) {
        if (rows.length < 2) return false
        var first = display(rows[0], key)
        for (var i = 1; i < rows.length; ++i)
            if (display(rows[i], key) !== first) return true
        return false
    }

    Connections {
        target: backend
        function onVersionDetailsReady(result) {
            if (!compare.active) return
            compare.rows = result.rows || []
            compare.loading = false
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

    component EdgeArrow: Item {
        id: edge
        property int delta: -1
        property string glyph: "‹"
        width: 72
        height: parent ? parent.height : 0
        enabled: compare.groups.length > 1
        activeFocusOnTab: enabled
        Accessible.role: Accessible.Button
        Accessible.name: delta < 0 ? "Previous duplicate group" : "Next duplicate group"
        Accessible.onPressAction: compare.step(delta)
        Keys.onReturnPressed: compare.step(delta)
        Keys.onSpacePressed: compare.step(delta)
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
        TapHandler { onTapped: compare.step(edge.delta) }
    }
    EdgeArrow {
        anchors.left: parent.left; delta: -1; glyph: "‹"
        width: compare.compact ? 40 : 72
    }
    EdgeArrow {
        anchors.right: parent.right; delta: 1; glyph: "›"
        width: compare.compact ? 40 : 72
    }

    Keys.onLeftPressed: compare.step(-1)
    Keys.onRightPressed: compare.step(1)
    Keys.onEscapePressed: compare.closed()

    Column {
        id: headBlock
        anchors.left: parent.left
        anchors.leftMargin: compare.compact ? 52 : 92
        anchors.right: parent.right
        anchors.rightMargin: compare.compact ? 52 : 92
        anchors.top: parent.top
        anchors.topMargin: Math.max(76, compare.height * 0.045)
        spacing: 0

        Row {
            spacing: 16
            Text {
                text: "SAME SONG, " + compare.members.length + " VERSIONS"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.8
            }
            Text {
                objectName: "versionComparePosition"
                text: (compare.index + 1) + " OF " + compare.groups.length
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.8
            }
        }
        Text {
            topPadding: 10
            width: headBlock.width
            text: compare.groupTitle
            color: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: compare.compact ? 30 : 44
            elide: Text.ElideRight
        }
        Text {
            topPadding: 6
            bottomPadding: 22
            text: compare.groupArtist
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsEmph
        }
    }

    // ---- the versions, side by side ----
    Flickable {
        anchors.left: headBlock.left
        anchors.right: headBlock.right
        anchors.top: headBlock.bottom
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 34
        clip: true
        contentHeight: columns.height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ArchiveScrollBar {}

        Row {
            id: columns
            width: parent.width
            spacing: compare.compact ? 20 : 40

            Repeater {
                model: compare.rows
                delegate: Column {
                    id: card
                    required property var modelData
                    required property int index
                    readonly property bool preferred:
                        (compare.members[index] || ({})).pref === true
                    width: (columns.width - (compare.rows.length - 1)
                            * (compare.compact ? 20 : 40))
                           / Math.max(1, compare.rows.length)
                    spacing: 0

                    // The sleeve identifies the version; the FACTS decide it,
                    // so the art is capped and the table owns the page.
                    MediaArtwork {
                        width: Math.min(card.width, compare.compact ? 104 : 176)
                        height: width
                        kind: "album"
                        source: "image://art/" + encodeURIComponent(card.modelData.file)
                    }
                    Text {
                        topPadding: 10
                        width: card.width
                        text: card.modelData.file
                        color: Theme.washFaint
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        topPadding: 12
                        visible: card.preferred
                        text: "PREFERRED IN GENERATED SESSIONS"
                        color: Theme.primary
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 2.2
                    }

                    Column {
                        topPadding: 12
                        width: card.width
                        spacing: 0
                        Repeater {
                            model: compare.facts
                            delegate: Item {
                                required property var modelData
                                width: card.width
                                height: 28
                                readonly property bool marked: compare.differs(modelData.key)
                                Text {
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: compare.compact ? 84 : 118
                                    text: modelData.label
                                    color: parent.marked ? Theme.primary : Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: 10
                                    font.letterSpacing: 1.6
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: compare.compact ? 90 : 126
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: compare.display(card.modelData, modelData.key)
                                    color: parent.marked ? Theme.washInk : Theme.washMuted
                                    font.family: Theme.font
                                    font.pixelSize: Theme.fsSmall
                                    font.weight: parent.marked ? Font.Medium : Font.Light
                                    elide: Text.ElideRight
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 1
                                    color: Theme.washHair
                                }
                            }
                        }
                    }

                    Row {
                        topPadding: 16
                        bottomPadding: 6
                        spacing: 26
                        WashLine {
                            label: "Listen →"
                            primaryAction: true
                            onActivated: backend.playFiles([card.modelData.file], 0)
                        }
                        WashLine {
                            label: card.preferred ? "Preferred" : "Prefer this"
                            onActivated: backend.preferVersion(card.modelData.file)
                        }
                        WashLine {
                            label: "Edit tags"
                            onActivated: compare.editRequested(card.modelData)
                        }
                    }
                }
            }
        }
    }

    signal editRequested(var track)

    Text {
        anchors.left: headBlock.left
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        text: "Nothing is merged or deleted here. Preferring a version only "
              + "changes which one generated sessions reach for."
        color: Theme.washFaint
        font.family: Theme.font
        font.pixelSize: Theme.fsSmall
    }
}
