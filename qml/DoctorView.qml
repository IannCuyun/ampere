import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// Library Doctor — Direction A, Condition Theatre.
// Canonical treatment:
// proposals/library-doctor-direction-2026-08-16/index.html?direction=a
//
// The backend remains the sole report and transaction owner. This view derives
// one selected condition and finding from that report; it never copies scan
// state, edits files, or invents a second repair path.
Item {
    id: doc

    property bool active: false
    property int selectedCondition: 0
    property int selectedFinding: 0

    signal repairRequested(int findingIndex)
    signal compareRequested(int findingIndex)
    readonly property var rep: backend.doctorReport || ({})
    readonly property bool hasReport: rep.lowBitrate !== undefined
    readonly property bool scanning: rep.total !== undefined
                                     && rep.lowBitrate === undefined
    readonly property bool compact: width < 900
    readonly property var conditionRows: [
        { key: "versionGroups", label: "DUPLICATE VERSIONS" },
        { key: "lowBitrate", label: "LOSSY / LOW BITRATE" },
        { key: "missingRg", label: "MISSING LOUDNESS" },
        { key: "untagged", label: "TAG PROBLEMS" },
        { key: "outliers", label: "LOUDNESS OUTLIERS" },
        // Not a finding: a repair Iann performs himself (SPEC UNDESIGNED #17,
        // his direction 2026-08-21). It keeps Condition Theatre's composition
        // and swaps the detail field for the alias manager.
        { key: "aliases", label: "ARTIST ALIASES", tool: true }
    ]
    readonly property int aliasCondition: conditionRows.length - 1
    readonly property bool toolSelected:
        selectedCondition === aliasCondition
    readonly property var selectedRows: findingsFor(selectedCondition)
    readonly property var selectedData: selectedRows.length > 0
                                        ? selectedRows[Math.min(selectedFinding,
                                                                selectedRows.length - 1)]
                                        : ({})
    readonly property bool reportIsClean: hasReport && totalFindings === 0
    readonly property int totalFindings:
        countFor(0) + countFor(1) + countFor(2) + countFor(3) + countFor(4)
    // A duplicate-version finding has no single file: it is a GROUP, and its
    // first member stands for it.
    function fileFor(item) {
        if (!item) return "";
        if (item.file) return item.file;
        var files = item.files || [];
        return files.length > 0 ? (files[0].file || "") : "";
    }

    readonly property string selectedFile: {
        if (selectedCondition === 0) {
            var files = selectedData.files || [];
            return files.length > 0 ? (files[0].file || "") : "";
        }
        return selectedData.file || "";
    }
    readonly property string secondaryFile: {
        if (selectedCondition !== 0)
            return "";
        var files = selectedData.files || [];
        return files.length > 1 ? (files[1].file || "") : "";
    }

    function findingsFor(condition) {
        var index = Math.max(0, Math.min(condition, conditionRows.length - 1));
        if (conditionRows[index].tool) return [];
        return rep[conditionRows[index].key] || [];
    }

    function countFor(condition) {
        return findingsFor(condition).length;
    }

    // The count column is evidence, not decoration: before a scan there is no
    // finding count to report, and the alias tool counts combinations rather
    // than findings.
    function countLabel(condition) {
        var index = Math.max(0, Math.min(condition, conditionRows.length - 1));
        if (conditionRows[index].tool)
            return aliasCount > 0 ? String(aliasCount) : "";
        return hasReport ? String(countFor(condition)) : "";
    }

    readonly property int aliasCount: Object.keys(backend.artistAliases || ({})).length

    function basename(file) {
        var bits = String(file || "").split("/");
        return bits.length ? bits[bits.length - 1] : "Unknown file";
    }

    function titleFor(item) {
        return item.title || basename(item.file || selectedFile);
    }

    function identityFor(item) {
        var artist = item.artist || "";
        var album = item.album || "";
        if (artist && album)
            return artist + "  ·  " + album;
        return artist || album || basename(item.file || selectedFile);
    }

    function conditionCopy(condition) {
        if (condition === 0)
            return "These recordings resolve to the same song identity. Choose the version Ampere should keep in generated sessions; every sibling remains in your library and can still be played directly.";
        if (condition === 1)
            return "This file is a lossy source below Ampere’s 256 kbps fidelity threshold. Replace it outside Ampere if a better master exists; the Doctor will never alter the file.";
        if (condition === 2)
            return "This recording has no ReplayGain track value, so level matching cannot hold it steady beside the rest of the queue. Rescan after tags are repaired.";
        if (condition === 3)
            return "The file is unreadable or lacks the title and artist identity Ampere needs to present it reliably. Repair the source tags, then scan again.";
        return "This master sits outside the expected ReplayGain range. It may be intentional; listen before deciding whether the source needs attention.";
    }

    function actionScope(condition) {
        return condition === 0
               ? "ONLY THIS CHANGES: FUTURE GENERATED-SESSION PREFERENCE"
               : "GUIDANCE ONLY: NO FILE OR PLAYBACK STATE IS CHANGED";
    }

    function findingBadge(condition, item) {
        if (condition === 0)
            return (item.files || []).length + " VERSIONS";
        if (condition === 1)
            return (item.kbps || 0) + " KBPS";
        if (condition === 2)
            return "NO REPLAYGAIN";
        if (condition === 3)
            return String(item.why || "TAG").toUpperCase();
        return (Number(item.gain || 0) > 0 ? "+" : "")
               + Number(item.gain || 0).toFixed(1) + " DB";
    }

    function selectCondition(index) {
        // Bound by the ROWS, never by a literal: Artist Aliases was added as
        // a sixth row while this still clamped at 4, so selecting it silently
        // landed on Loudness Outliers and the alias manager could not be
        // opened at all (found 2026-08-22).
        selectedCondition = Math.max(0, Math.min(index,
                                                 conditionRows.length - 1));
        selectedFinding = 0;
    }

    function moveFinding(delta) {
        var count = selectedRows.length;
        if (count < 2)
            return;
        selectedFinding = (selectedFinding + delta + count) % count;
    }

    function reconcileSelection() {
        if (!hasReport || totalFindings === 0) {
            selectedFinding = 0;
            return;
        }
        if (countFor(selectedCondition) === 0) {
            for (var i = 0; i < 5; ++i) {
                if (countFor(i) > 0) {
                    selectedCondition = i;
                    break;
                }
            }
        }
        selectedFinding = Math.max(0, Math.min(selectedFinding,
                                               countFor(selectedCondition) - 1));
    }

    Component.onCompleted: reconcileSelection()

    Connections {
        target: backend
        function onDoctorChanged() { doc.reconcileSelection(); }
    }

    component ConditionButton: Rectangle {
        id: conditionButton
        required property int conditionIndex
        required property string conditionLabel
        required property string conditionCount
        signal chosen()

        readonly property bool chosenState: doc.selectedCondition === conditionIndex
        objectName: "doctorCondition_" + conditionIndex
        color: conditionMouse.pressed ? Qt.alpha(Theme.primary, 0.10)
             : conditionMouse.containsMouse ? Qt.alpha(Theme.washInk, 0.04)
             : "transparent"
        border.width: activeFocus ? 2 : 0
        border.color: activeFocus ? Theme.focusRing : "transparent"
        activeFocusOnTab: enabled && visible
        Accessible.role: Accessible.Button
        Accessible.name: conditionCount === ""
            ? conditionLabel
            : conditionLabel + ", " + conditionCount
        Accessible.onPressAction: chosen()
        Keys.onReturnPressed: chosen()
        Keys.onSpacePressed: chosen()
        Keys.onLeftPressed: if (doc.compact) doc.selectCondition(conditionIndex - 1)
        Keys.onRightPressed: if (doc.compact) doc.selectCondition(conditionIndex + 1)
        Keys.onUpPressed: if (!doc.compact) doc.selectCondition(conditionIndex - 1)
        Keys.onDownPressed: if (!doc.compact) doc.selectCondition(conditionIndex + 1)

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: conditionButton.chosenState ? Theme.primary
                  : Qt.alpha(Theme.washInk, 0.08)
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: doc.compact ? Theme.spaceSm : 0
            anchors.right: countText.left
            anchors.rightMargin: Theme.spaceSm
            anchors.verticalCenter: parent.verticalCenter
            text: conditionButton.conditionLabel
            elide: Text.ElideRight
            color: conditionButton.chosenState ? Theme.washInk : Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: doc.compact ? 9 : 11
            font.weight: conditionButton.chosenState ? Font.DemiBold : Font.Medium
            font.letterSpacing: doc.compact ? 1.2 : 1.8
        }

        Text {
            id: countText
            anchors.right: parent.right
            anchors.rightMargin: doc.compact ? Theme.spaceSm : 0
            anchors.verticalCenter: parent.verticalCenter
            text: conditionButton.conditionCount
            color: conditionButton.chosenState ? Theme.primary : Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: doc.compact ? 14 : 18
            font.weight: Font.Light
        }

        MouseArea {
            id: conditionMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: conditionButton.chosen()
        }
    }

    // F2: guidance and the actions sit BESIDE the rail so the whole right
    // field stays evidence (Iann's pick, 2026-08-21). It hangs off the
    // SELECTED condition rather than the bottom of the list, where it read as
    // a description of whichever row happened to sit last (found 2026-08-22).
    component ConditionGuidance: Column {
        spacing: Theme.spaceMd
        Text {
            width: parent.width
            text: doc.conditionCopy(doc.selectedCondition)
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            font.weight: Font.Light
            wrapMode: Text.Wrap
        }
        Column {
            width: parent.width
            spacing: 2
            WashLine {
                visible: doc.selectedCondition === 3
                label: "Repair tags \u2192"
                primaryAction: true
                onActivated: doc.repairRequested(doc.selectedFinding)
            }
            WashLine {
                label: "Listen"
                primaryAction: doc.selectedCondition !== 3
                onActivated: if (doc.selectedFile)
                    backend.playFiles([doc.selectedFile], 0)
            }
        }
        Text {
            width: parent.width
            text: doc.actionScope(doc.selectedCondition)
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsMicro
            font.letterSpacing: 2.2
            wrapMode: Text.Wrap
        }
    }

    Column {
        id: head
        anchors.left: parent.left
        anchors.leftMargin: Theme.pageGutter(doc.width)
        anchors.right: parent.right
        anchors.rightMargin: Theme.pageGutter(doc.width)
        anchors.top: parent.top
        anchors.topMargin: Theme.pageTop(doc.height)
        spacing: Theme.spaceSm

        RowLayout {
            width: parent.width
            spacing: Theme.spaceLg

            Column {
                Layout.fillWidth: true
                spacing: 7
                Text {
                    text: "SETTINGS / LIBRARY DOCTOR"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.weight: Font.Medium
                    font.letterSpacing: 2.8
                }
                Text {
                    text: "Library Doctor"
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: doc.compact ? 34 : 44
                    font.weight: Font.Light
                    font.letterSpacing: -1.5
                }
                Text {
                    visible: !doc.compact
                    text: "A visual examination of versions, fidelity, tags, and playback consistency."
                    color: Theme.washMuted
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    font.weight: Font.Light
                }
            }

            GlowButton {
                Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: 44
                Layout.minimumHeight: 44
                icon: "search"
                label: doc.compact ? "" : (doc.hasReport ? "SCAN AGAIN" : "RUN THE SCAN")
                tip: doc.hasReport ? "Scan the library again" : "Run the library scan"
                enabled: !doc.scanning
                onClicked: backend.runDoctor()
            }
        }

        Rectangle {
            width: parent.width
            height: 1
            color: Theme.washHair
        }
    }

    GridLayout {
        id: stage
        anchors.left: head.left
        anchors.right: head.right
        anchors.top: head.bottom
        anchors.topMargin: doc.compact ? Theme.spaceMd : Theme.spaceLg
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.spaceMd
        columns: doc.compact ? 1 : 2
        columnSpacing: doc.compact ? 0 : 40
        rowSpacing: Theme.spaceMd

        ColumnLayout {
            id: leftField
            Layout.fillWidth: doc.compact
            Layout.fillHeight: !doc.compact
            Layout.preferredWidth: doc.compact ? stage.width : 270
            spacing: Theme.spaceLg

        // Compact WRAPS rather than scrolling sideways: a horizontal rail put
        // two of the six conditions past the right edge with no affordance, so
        // Artist Aliases simply looked absent (found 2026-08-22).
        Flow {
            id: conditionFlow
            objectName: "doctorConditionFlow"
            visible: doc.compact
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            Repeater {
                model: doc.compact ? doc.conditionRows : []
                delegate: ConditionButton {
                    required property int index
                    required property var modelData
                    width: (conditionFlow.width - Theme.spaceSm) / 2
                    height: 58
                    conditionIndex: index
                    conditionLabel: modelData.label
                    conditionCount: doc.countLabel(index)
                    onChosen: doc.selectCondition(index)
                }
            }
        }

        ListView {
            id: conditionList
            objectName: "doctorConditionIndex"
            visible: !doc.compact
            Layout.fillWidth: true
            Layout.preferredHeight: doc.compact ? 0 : stage.height
            orientation: ListView.Vertical
            spacing: 0
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: doc.compact ? [] : doc.conditionRows
            delegate: Column {
                id: conditionSlot
                required property int index
                required property var modelData
                readonly property bool chosen: doc.selectedCondition === index
                width: conditionList.width
                spacing: 0

                ConditionButton {
                    width: conditionSlot.width
                    height: 64
                    conditionIndex: conditionSlot.index
                    conditionLabel: conditionSlot.modelData.label
                    conditionCount: doc.countLabel(conditionSlot.index)
                    onChosen: doc.selectCondition(conditionSlot.index)
                }
                ConditionGuidance {
                    width: conditionSlot.width - Theme.spaceLg
                    topPadding: Theme.spaceMd
                    bottomPadding: Theme.spaceMd
                    visible: !doc.compact && conditionSlot.chosen
                             && doc.hasReport && !doc.reportIsClean
                             && !doc.toolSelected
                }
            }
            Rectangle {
                visible: !doc.compact
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 1
                color: Theme.washHair
            }
        }

            // Compact keeps the guidance beneath the wrapped rail: a Flow
            // has no single row to hang it from.
            ConditionGuidance {
                Layout.fillWidth: true
                Layout.rightMargin: Theme.spaceLg
                visible: doc.compact && doc.hasReport && !doc.reportIsClean
                         && !doc.toolSelected
            }
            Item { Layout.fillHeight: true }
        }

        Flickable {
            id: detailScroll
            objectName: "doctorDetailScroll"
            Layout.row: doc.compact ? 1 : 0
            Layout.column: doc.compact ? 0 : 1
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: detailContent.implicitHeight + Theme.spaceLg
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ArchiveScrollBar {}

            ColumnLayout {
                id: detailContent
                width: detailScroll.width - (detailScroll.ScrollBar.vertical.visible ? 12 : 0)
                spacing: Theme.spaceLg

                AliasManager {
                    objectName: "doctorAliasManager"
                    visible: doc.toolSelected
                    Layout.fillWidth: true
                }

                // F2 · contact sheet (Iann's pick 2026-08-21). One grid slot
                // for every finding; only what fills the square changes with
                // the condition. A record's fault is its sleeve; a tag fault
                // has often lost its sleeve, so the tags themselves are the
                // specimen and the missing fields are the evidence.
                Grid {
                    objectName: "doctorSpecimenSheet"
                    visible: doc.hasReport && !doc.reportIsClean && !doc.toolSelected
                    Layout.fillWidth: true
                    columns: Math.max(2, Math.floor(detailContent.width / 190))
                    columnSpacing: 18
                    rowSpacing: 22

                    Repeater {
                        model: doc.selectedRows
                        delegate: Item {
                            id: tile
                            required property var modelData
                            required property int index
                            readonly property bool chosen: doc.selectedFinding === index
                            readonly property bool tagFinding: doc.selectedCondition === 3
                            readonly property var missingFields: modelData.missing || []
                            width: (detailContent.width
                                    - (parent.columns - 1) * 18) / parent.columns
                            height: width + 46
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: doc.titleFor(modelData) + ", "
                                             + doc.findingBadge(doc.selectedCondition, modelData)
                            Accessible.onPressAction: tile.activate()
                            Keys.onReturnPressed: tile.activate()
                            Keys.onSpacePressed: tile.activate()

                            function activate() {
                                doc.selectedFinding = index
                                // Every finding type opens into its own page:
                                // a tag fault into repair, a duplicate into
                                // the version comparison (Iann, 2026-08-21).
                                if (tagFinding) doc.repairRequested(index)
                                else if (doc.selectedCondition === 0)
                                    doc.compareRequested(index)
                            }

                            Item {
                                id: square
                                width: parent.width
                                height: parent.width

                                MediaArtwork {
                                    anchors.fill: parent
                                    visible: !tile.tagFinding
                                    kind: "album"
                                    source: doc.fileFor(modelData)
                                            ? "image://art/"
                                              + encodeURIComponent(doc.fileFor(modelData))
                                            : ""
                                }

                                // the tag specimen: the fields ARE the artwork
                                Rectangle {
                                    anchors.fill: parent
                                    visible: tile.tagFinding
                                    color: Qt.alpha(Theme.washInk, 0.045)
                                    border.width: 1
                                    border.color: Theme.washHair
                                    Column {
                                        anchors.centerIn: parent
                                        width: parent.width - 24
                                        spacing: 6
                                        visible: modelData.readable !== false
                                        Repeater {
                                            model: ["title", "artist", "album",
                                                    "albumartist", "year", "track"]
                                            delegate: Row {
                                                required property string modelData
                                                readonly property bool absent:
                                                    tile.missingFields.indexOf(modelData) >= 0
                                                width: parent.width
                                                spacing: 8
                                                Text {
                                                    width: 74
                                                    text: modelData.toUpperCase()
                                                    color: parent.absent ? Theme.error : Theme.washFaint
                                                    font.family: Theme.displayFont
                                                    font.pixelSize: 9
                                                    font.letterSpacing: 1.4
                                                }
                                                Text {
                                                    width: parent.width - 82
                                                    text: parent.absent
                                                          ? "— missing"
                                                          : String(tile.modelData[modelData] || "·")
                                                    color: parent.absent ? Theme.error : Theme.washInk
                                                    font.family: Theme.font
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }
                                    }
                                    Column {
                                        anchors.centerIn: parent
                                        spacing: 8
                                        visible: modelData.readable === false
                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: "!"
                                            color: Theme.error
                                            font.family: Theme.displayFont
                                            font.pixelSize: 30
                                        }
                                        Text {
                                            text: "UNREADABLE"
                                            color: Theme.error
                                            font.family: Theme.displayFont
                                            font.pixelSize: Theme.fsMicro
                                            font.letterSpacing: 2
                                        }
                                    }
                                }

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.bottom: parent.bottom
                                    width: badge.width + 14
                                    height: 22
                                    color: Qt.rgba(0.035, 0.030, 0.026, 0.86)
                                    Text {
                                        id: badge
                                        anchors.centerIn: parent
                                        text: doc.findingBadge(doc.selectedCondition,
                                                               tile.modelData)
                                        color: Theme.primary
                                        font.family: Theme.displayFont
                                        font.pixelSize: 10
                                        font.letterSpacing: 1.4
                                    }
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    color: "transparent"
                                    border.width: tile.chosen || tile.activeFocus ? 2 : 0
                                    border.color: tile.activeFocus ? Theme.focusRing : Theme.primary
                                }
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: square.bottom
                                anchors.topMargin: 7
                                text: doc.titleFor(modelData)
                                color: Theme.washInk
                                font.family: Theme.font
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                text: doc.identityFor(modelData)
                                color: Theme.washFaint
                                font.family: Theme.font
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: tile.activate() }
                        }
                    }
                }

                Item {
                    visible: (doc.scanning || !doc.hasReport || doc.reportIsClean)
                             && !doc.toolSelected
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(420, detailScroll.height - Theme.spaceLg)

                    Column {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - Theme.spaceLg * 2, 560)
                        spacing: Theme.spaceMd

                        Item {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(330, parent.width)
                            height: 230

                            MediaArtwork {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: 168
                                height: width
                                opacity: 0.42
                                source: backend.currentSong.file
                                        ? "image://art/" + encodeURIComponent(backend.currentSong.file)
                                        : ""
                            }
                            MediaArtwork {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                width: 168
                                height: width
                                opacity: 0.56
                                source: backend.currentSong.file
                                        ? "image://art/" + encodeURIComponent(backend.currentSong.file)
                                        : ""
                            }
                            MediaArtwork {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.top: parent.top
                                width: 214
                                height: width
                                source: backend.currentSong.file
                                        ? "image://art/" + encodeURIComponent(backend.currentSong.file)
                                        : ""
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: doc.scanning ? "EXAMINING THE ARCHIVE"
                                  : doc.reportIsClean ? "LAST EXAMINATION"
                                  : "NO EXAMINATION ON RECORD"
                            color: Theme.washFaint
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.weight: Font.Medium
                            font.letterSpacing: 2.1
                        }
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: doc.scanning
                                  ? (doc.rep.scanning || 0) + " of " + (doc.rep.total || 0)
                                    + " files"
                                  : doc.reportIsClean ? "Clean bill of health."
                                  : "Let the library show its condition."
                            color: Theme.washInk
                            font.family: Theme.font
                            font.pixelSize: doc.compact ? 27 : 34
                            font.weight: Font.Light
                            font.letterSpacing: -0.8
                        }
                        Rectangle {
                            visible: doc.scanning
                            width: Math.min(360, parent.width)
                            height: 1
                            anchors.horizontalCenter: parent.horizontalCenter
                            color: Theme.washHair
                            Rectangle {
                                width: parent.width * Math.max(0, Math.min(1,
                                      Number(doc.rep.scanning || 0)
                                      / Math.max(1, Number(doc.rep.total || 1))))
                                height: 3
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.primary
                                Behavior on width { NumberAnimation { duration: 180 } }
                            }
                        }
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            text: doc.scanning
                                  ? "Ampere is reading tags, bitrate, loudness, and version identity in the background. Playback remains untouched."
                                  : doc.reportIsClean
                                    ? "Every examined file is tagged, leveled, and above the lossy threshold. Run another scan whenever the library changes."
                                    : "The scan reads tags and audio metadata without changing a file. You review every finding before any preference changes."
                            color: Theme.washMuted
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                            font.weight: Font.Light
                            lineHeight: 1.45
                        }
                        GlowButton {
                            visible: !doc.scanning
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 180
                            height: 44
                            icon: "search"
                            label: doc.reportIsClean ? "SCAN AGAIN" : "RUN THE SCAN"
                            onClicked: backend.runDoctor()
                        }
                    }
                }
            }
        }
    }
}
