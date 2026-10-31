pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Ampy — Direction A, Mixline (Iann final verdict 2026-08-15).
// Canonical source:
// design/proposals/ampy-dedicated-page-round-2026-08-15/index.html?direction=a
//
// This view owns presentation and explicit intent only. Mood and duration
// selection are inert; the backend owns asynchronous planning, generated-
// playlist publication, queue mutation, and playback.
Item {
    id: page

    property bool active: false
    readonly property bool compact: width < 820
    readonly property bool narrow: width < 640
    readonly property bool sessionBusy: backend.mixtapeBusy

    // Sound Profiles were replaced by the audited character vocabulary
    // (Iann, 2026-08-22 — SPEC UNDESIGNED #13). ANY keeps the mood arc; a
    // named character selects on measured sound instead.
    property string tab: "session"
    property var characters: [{ key: "", label: "ANY", blurb: "" }]
    property int characterAt: 0
    readonly property string selectedCharacter: characters.length
        ? String(characters[characterAt].key || "") : ""
    readonly property string selectedCharacterLabel: characters.length
        ? String(characters[characterAt].label || "ANY") : "ANY"

    property var moods: []
    property string selectedMood: ""
    property string selectedMoodLabel: ""
    property int selectedMinutes: 45
    property var previewRows: []
    property string say: "Choose the feeling and the clock. Nothing changes until Build & Play."

    readonly property var minuteChoices: [30, 45, 60, 90]
    readonly property int selectedMoodIndex: moodIndex(selectedMood)

    function moodIndex(key) {
        for (var i = 0; i < moods.length; ++i) {
            if (moods[i].key === key)
                return i;
        }
        return -1;
    }

    function minuteIndex(minutes) {
        for (var i = 0; i < minuteChoices.length; ++i) {
            if (minuteChoices[i] === minutes)
                return i;
        }
        return 0;
    }

    function reload() {
        characters = [{ key: "", label: "ANY", blurb: "" }]
            .concat(backend.soundCharacters);
        moods = backend.moodList();
        var preferred = moodIndex(selectedMood);
        if (preferred < 0)
            preferred = moodIndex("dark");
        if (preferred < 0 && moods.length)
            preferred = 0;
        if (preferred >= 0) {
            selectedMood = moods[preferred].key;
            selectedMoodLabel = moods[preferred].label;
        }
        refreshPreviewRows();
        backend.requestLibrarySummary();
    }

    function refreshPreviewRows() {
        var overview = backend.homeOverview();
        var shelves = overview.shelves || ({});
        var groups = [
            shelves.deep || [], shelves.loved || [], shelves.arrivals || [],
            shelves.history || [], shelves.unfinished || []
        ];
        var rows = [];
        var seen = {};

        function append(entry) {
            var file = String((entry || {}).file || "");
            if (!file || seen[file] || rows.length >= 8)
                return;
            seen[file] = true;
            rows.push(entry);
        }

        append(backend.currentSong || ({}));
        for (var group = 0; group < groups.length && rows.length < 8; ++group) {
            for (var index = 0; index < groups[group].length && rows.length < 8; ++index)
                append(groups[group][index]);
        }
        previewRows = rows;
    }

    function previewAt(position) {
        if (!previewRows.length)
            return ({});
        var start = Math.max(0, selectedMoodIndex);
        return previewRows[(start + position) % previewRows.length];
    }

    function cycleMood(step) {
        if (sessionBusy || !moods.length)
            return;
        var index = selectedMoodIndex;
        if (index < 0)
            index = 0;
        index = (index + step + moods.length) % moods.length;
        selectedMood = moods[index].key;
        selectedMoodLabel = moods[index].label;
        say = "Ready for a " + selectedMoodLabel.toLowerCase()
            + " arc. Nothing changes until Build & Play.";
    }

    function cycleCharacter(step) {
        if (sessionBusy || !characters.length)
            return;
        characterAt = (characterAt + step + characters.length)
            % characters.length;
        say = selectedCharacter === ""
            ? "Back to a mood arc. Nothing changes until Build & Play."
            : characters[characterAt].blurb
              + ". Nothing changes until Build & Play.";
    }

    function cycleMinutes(step) {
        if (sessionBusy)
            return;
        var index = minuteIndex(selectedMinutes);
        index = (index + step + minuteChoices.length) % minuteChoices.length;
        selectedMinutes = minuteChoices[index];
        say = "Targeting about " + selectedMinutes
            + " minutes. Nothing changes until Build & Play.";
    }

    function buildAndPlay() {
        if (sessionBusy)
            return;
        if (selectedCharacter !== "") {
            // A character is measured selection, not a clock-fitted arc: the
            // duration becomes a track count at roughly four minutes each.
            var wanted = Math.max(8, Math.round(selectedMinutes / 4));
            if (backend.buildCharacterMix(selectedCharacter, wanted) === "") {
                say = "Nothing matched " + selectedCharacterLabel.toLowerCase()
                    + ". The queue was not changed.";
                return;
            }
            say = "Playing " + selectedCharacterLabel.toLowerCase()
                + ". It is kept under MIXES.";
            return;
        }
        if (!selectedMood)
            return;
        if (!backend.startAmpySession(selectedMinutes, selectedMood)) {
            say = backend.mixtapeBusy
                ? "A listening arc is already taking shape."
                : "Ampy could not start that listening arc. The queue was not changed.";
            return;
        }
        say = "Building a ~" + selectedMinutes + " minute "
            + selectedMoodLabel.toLowerCase() + " arc away from the room…";
    }

    onActiveChanged: if (active)
        reload()

    Connections {
        target: backend

        function onConnectedChanged() {
            if (backend.connected && page.active)
                page.reload();
        }

        function onLibrarySummaryChanged() {
            if (page.active)
                page.refreshPreviewRows();
        }

        function onMixtapeFinished(name, count, started) {
            if (!name) {
                page.say = "Ampy could not build that arc. The queue was not changed.";
                return;
            }
            page.say = started
                ? "Built " + count + " tracks, saved " + name + ", and set it in motion."
                : "Saved " + name + ", but playback could not start.";
        }
    }

    component NeedleButton: Item {
        id: needleButton

        property bool forward: false
        property string accessibleName: forward ? "Next option" : "Previous option"
        signal triggered()

        width: 44
        height: 44
        activeFocusOnTab: enabled
        Accessible.role: Accessible.Button
        Accessible.name: accessibleName
        Accessible.onPressAction: needleButton.triggered()
        Keys.onReturnPressed: needleButton.triggered()
        Keys.onEnterPressed: needleButton.triggered()
        Keys.onSpacePressed: needleButton.triggered()

        Rectangle {
            anchors.fill: parent
            color: needleTap.pressed
                ? Qt.alpha(Theme.primary, 0.13)
                : (needleHover.hovered ? Theme.hoverSurface : "transparent")
            border.width: needleButton.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }

        Icon {
            anchors.centerIn: parent
            name: needleButton.forward ? "chevron-right" : "chevron-left"
            size: 14
            color: needleButton.enabled ? Theme.primary : Theme.washFaint
        }

        HoverHandler {
            id: needleHover
            cursorShape: needleButton.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        }
        TapHandler {
            id: needleTap
            enabled: needleButton.enabled
            onTapped: needleButton.triggered()
        }
    }

    component CyclePicker: Item {
        id: picker

        property string label: ""
        property string value: ""
        property string suffix: ""
        property int labelWidth: 64
        property int valueWidth: page.compact ? 60 : 72
        property string previousName: "Previous option"
        property string nextName: "Next option"
        property string previousObjectName: ""
        property string nextObjectName: ""
        signal previous()
        signal next()

        readonly property int suffixWidth: suffix ? (page.compact ? 48 : 56) : 0
        implicitWidth: labelWidth + 44 + valueWidth + 44 + suffixWidth
        implicitHeight: 44
        width: implicitWidth
        height: 44

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: picker.labelWidth
            text: picker.label
            color: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            font.weight: Font.Medium
            font.letterSpacing: page.compact ? 1.1 : 1.5
        }

        NeedleButton {
            id: previousButton
            objectName: picker.previousObjectName
            anchors.left: parent.left
            anchors.leftMargin: picker.labelWidth
            anchors.verticalCenter: parent.verticalCenter
            enabled: !page.sessionBusy
            accessibleName: picker.previousName
            onTriggered: picker.previous()
        }

        Item {
            id: valueWell
            anchors.left: previousButton.right
            anchors.verticalCenter: parent.verticalCenter
            width: picker.valueWidth
            height: 44

            Text {
                anchors.centerIn: parent
                text: picker.value
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.weight: Font.Normal
                font.letterSpacing: page.compact ? 1.0 : 1.5
            }
        }

        NeedleButton {
            id: nextButton
            objectName: picker.nextObjectName
            anchors.left: valueWell.right
            anchors.verticalCenter: parent.verticalCenter
            forward: true
            enabled: !page.sessionBusy
            accessibleName: picker.nextName
            onTriggered: picker.next()
        }

        Text {
            visible: picker.suffix !== ""
            anchors.left: nextButton.right
            anchors.leftMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            width: picker.suffixWidth - 4
            text: picker.suffix
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsMicro
            font.letterSpacing: page.compact ? 0.9 : 1.2
        }
    }

    component ArcCover: Item {
        id: cover

        property var entry: ({})
        property string eyebrow: ""
        property string caption: ""
        property real side: 240
        property bool selected: false

        width: side
        height: side

        MediaArtwork {
            anchors.fill: parent
            source: cover.entry.file
                ? "image://art/" + encodeURIComponent(cover.entry.file) : ""
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: cover.selected ? 2 : 1
            border.color: cover.selected ? Theme.primary : Theme.washHair
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: parent.height * 0.38
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.42; color: Qt.rgba(0.035, 0.032, 0.028, 0.48) }
                GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.032, 0.028, 0.94) }
            }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: page.compact ? 9 : 14
            anchors.rightMargin: page.compact ? 9 : 14
            anchors.bottomMargin: page.compact ? 9 : 13
            spacing: 4

            Text {
                width: parent.width
                text: cover.eyebrow
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: page.compact ? 1.1 : 1.7
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: cover.caption
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: page.compact ? Theme.fsSmall : Theme.fsBody
                font.weight: Font.Normal
                elide: Text.ElideRight
            }
        }
    }

    Item {
        id: composition
        objectName: "ampyStage"
        x: page.compact ? 24 : Theme.pageGutter(page.width)
        y: Theme.pageTop(page.height)
        width: page.compact
            ? Math.max(0, page.width - 48)
            : Math.min(1440, page.width - (2 * Theme.pageGutter(page.width)))
        height: Math.max(0, page.height - y - Theme.playerHeight - 18)

        Item {
            id: heading
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: page.compact ? 64 : 98

            Text {
                id: routeLabel
                anchors.left: parent.left
                anchors.top: parent.top
                text: "HOME / AMPY / SESSION"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.4
            }

            Text {
                id: titleLabel
                anchors.left: parent.left
                anchors.top: routeLabel.bottom
                anchors.topMargin: 7
                text: "Shape the next hour."
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: page.compact ? Theme.fsStat : Theme.fsHero
                font.weight: Font.Light
                font.letterSpacing: page.compact ? -0.8 : -1.4
            }

            Text {
                visible: !page.compact
                anchors.left: parent.left
                anchors.top: titleLabel.bottom
                anchors.topMargin: 8
                width: Math.min(620, parent.width * 0.52)
                text: page.say
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.weight: Font.Light
                elide: Text.ElideRight
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }

            Column {
                anchors.right: parent.right
                anchors.top: parent.top
                spacing: 5

                Text {
                    anchors.right: parent.right
                    text: page.selectedMinutes + ":00"
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: page.compact ? Theme.fsTitle : Theme.fsStat
                    font.weight: Font.Light
                }
                Text {
                    anchors.right: parent.right
                    text: "PLANNED DURATION"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2
                }
            }
        }

        Row {
            id: tabRail
            objectName: "ampyTabs"
            anchors.left: parent.left
            anchors.top: heading.bottom
            height: 44
            spacing: page.compact ? 22 : 30
            WashLine {
                objectName: "ampySessionTab"
                label: "Session"
                primaryAction: page.tab === "session"
                onActivated: page.tab = "session"
            }
            WashLine {
                objectName: "ampyMixesTab"
                label: "Mixes"
                primaryAction: page.tab === "mixes"
                onActivated: page.tab = "mixes"
            }
        }

        MixShelf {
            objectName: "ampyMixShelf"
            visible: page.tab === "mixes"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tabRail.bottom
            anchors.bottom: parent.bottom
            compact: page.compact
        }

        Item {
            id: arcStage
            visible: page.tab === "session"
            objectName: "ampyArcStage"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tabRail.bottom
            anchors.bottom: controlBar.top
            anchors.bottomMargin: page.compact ? 12 : 18

            readonly property real centerSide: page.compact
                ? Math.min(264, height * 0.72, width * 0.42)
                : Math.min(430, height * 0.82, width * 0.38)
            readonly property real supportSide: centerSide * (page.compact ? 0.66 : 0.68)

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.28; color: Qt.alpha(Theme.primary, 0.20) }
                    GradientStop { position: 0.5; color: Qt.alpha(Theme.primary, 0.52) }
                    GradientStop { position: 0.72; color: Qt.alpha(Theme.primary, 0.20) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }

            Row {
                anchors.centerIn: parent
                spacing: page.compact ? 10 : Math.max(28, arcStage.width * 0.035)

                ArcCover {
                    anchors.verticalCenter: parent.verticalCenter
                    side: arcStage.supportSide
                    entry: page.previewAt(0)
                    eyebrow: "01 · WARM-UP"
                    caption: "Open the room"
                    opacity: 0.82
                }
                ArcCover {
                    anchors.verticalCenter: parent.verticalCenter
                    side: arcStage.centerSide
                    entry: page.previewAt(1)
                    eyebrow: "02 · PEAK"
                    caption: "Take it higher"
                    selected: true
                }
                ArcCover {
                    anchors.verticalCenter: parent.verticalCenter
                    side: arcStage.supportSide
                    entry: page.previewAt(2)
                    eyebrow: "03 · LANDING"
                    caption: "Bring it home"
                    opacity: 0.82
                }
            }
        }

        Item {
            id: controlBar
            objectName: "ampyControlBar"
            visible: page.tab === "session"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            // SOUND joined MOOD and DURATION on 2026-08-22, and three
            // clauses no longer fit one line at half-screen widths. The
            // sentence wraps rather than running off the edge.
            height: Math.max(page.narrow ? 104 : 56,
                             optionGroup.implicitHeight + 12)

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.washHair
            }

            Item {
                id: optionsLane
                objectName: "ampyOptionsLane"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.right: page.narrow ? parent.right : buildAction.left
                anchors.rightMargin: page.narrow ? 0 : (page.compact ? 8 : 24)
                anchors.bottom: parent.bottom

                Flow {
                    id: optionGroup
                    objectName: "ampyOptionGroup"
                    anchors.verticalCenter: parent.verticalCenter
                    // Binding the width to its own implicitWidth is circular
                    // in a Flow and collapses it to one clause per line. Take
                    // the lane's width and centre by measured content
                    // instead, which stays honest when the sentence wraps.
                    width: optionsLane.width
                    x: wrapped ? 0
                       : Math.max(0, (optionsLane.width - childrenRect.width) / 2)
                    spacing: 0
                    // A separator between clauses only reads as one while
                    // they share a line.
                    readonly property bool wrapped: childrenRect.height > 70

                    CyclePicker {
                        label: "SOUND:"
                        value: page.selectedCharacterLabel
                        labelWidth: page.compact ? 58 : 70
                        valueWidth: page.compact ? 96 : 132
                        previousName: "Previous sound character"
                        nextName: "Next sound character"
                        previousObjectName: "ampyCharacterPrevious"
                        nextObjectName: "ampyCharacterNext"
                        onPrevious: page.cycleCharacter(-1)
                        onNext: page.cycleCharacter(1)
                    }

                    Text {
                        visible: !page.compact && !optionGroup.wrapped
                        width: 16
                        height: 44
                        verticalAlignment: Text.AlignVCenter
                        text: "\u00b7"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.washFaint
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsSmall
                    }

                    CyclePicker {
                        // A mood arc and a measured character are different
                        // instruments; MOOD is inert while SOUND names one.
                        enabled: page.selectedCharacter === ""
                        opacity: enabled ? 1 : 0.4
                        label: "MOOD:"
                        value: page.selectedMoodLabel
                        labelWidth: page.compact ? 52 : 64
                        previousName: "Previous mood"
                        nextName: "Next mood"
                        previousObjectName: "ampyMoodPrevious"
                        nextObjectName: "ampyMoodNext"
                        onPrevious: page.cycleMood(-1)
                        onNext: page.cycleMood(1)
                    }

                    Text {
                        visible: !page.compact && !optionGroup.wrapped
                        width: 16
                        height: 44
                        verticalAlignment: Text.AlignVCenter
                        text: "·"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.washFaint
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsSmall
                    }

                    CyclePicker {
                        label: "DURATION:"
                        value: "~" + page.selectedMinutes
                        suffix: "MINUTES"
                        labelWidth: page.compact ? 78 : 92
                        previousName: "Previous duration"
                        nextName: "Next duration"
                        previousObjectName: "ampyDurationPrevious"
                        nextObjectName: "ampyDurationNext"
                        onPrevious: page.cycleMinutes(-1)
                        onNext: page.cycleMinutes(1)
                    }
                }
            }

            Item {
                id: buildAction
                objectName: "ampyBuildAction"
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                width: page.compact ? 142 : 154
                height: 56
                activeFocusOnTab: enabled
                enabled: !page.sessionBusy
                         && (page.selectedCharacter !== ""
                             || page.selectedMood !== "")
                Accessible.role: Accessible.Button
                Accessible.name: backend.mixtapeBusy
                    ? "Building Ampy listening arc"
                    : page.selectedCharacter !== ""
                      ? "Build and play " + page.selectedCharacterLabel.toLowerCase()
                      : "Build and play a " + page.selectedMoodLabel.toLowerCase()
                        + " session of about " + page.selectedMinutes + " minutes"
                Accessible.onPressAction: page.buildAndPlay()
                Keys.onReturnPressed: page.buildAndPlay()
                Keys.onEnterPressed: page.buildAndPlay()
                Keys.onSpacePressed: page.buildAndPlay()

                Rectangle {
                    anchors.fill: parent
                    color: buildTap.pressed
                        ? Qt.alpha(Theme.primary, 0.13)
                        : (buildHover.hovered ? Theme.hoverSurface : "transparent")
                    border.width: buildAction.activeFocus ? 1 : 0
                    border.color: Theme.focusRing
                }

                Row {
                    anchors.centerIn: parent
                    spacing: 7

                    Text {
                        text: backend.mixtapeBusy ? "BUILDING…" : "BUILD & PLAY"
                        color: buildAction.enabled ? Theme.washInk : Theme.washFaint
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.weight: Font.Medium
                        font.letterSpacing: page.compact ? 1.3 : 1.8
                    }
                    Icon {
                        visible: !backend.mixtapeBusy
                        anchors.verticalCenter: parent.verticalCenter
                        name: "chevron-right"
                        size: 13
                        color: buildAction.enabled ? Theme.primary : Theme.washFaint
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: buildAction.enabled ? Theme.primary : Theme.washHair
                }

                HoverHandler {
                    id: buildHover
                    cursorShape: buildAction.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                }
                TapHandler {
                    id: buildTap
                    enabled: buildAction.enabled
                    onTapped: page.buildAndPlay()
                }
            }
        }
    }
}
