import QtQuick
import QtQuick.Layouts
import "."

// DJ studio — B (Iann's verdict 2026-07-31; round: proposals/features-round
// §B DJ). Live: a hand-off hero with the planned move and CUT NOW, then the
// set list with cue intelligence. Idle: pick a starting room, tune the set,
// drop the needle. All deck behaviors preserved.
Item {
    id: deck
    property string seed: ""
    property bool seedIsFile: false
    property string seedSongLabel: ""
    property var stats: null
    property string scanLine: ""
    property var rooms: []
    property bool tuneOpen: false

    function refreshRooms() {
        var e = backend.browse("")
        rooms = e.filter(function(x) { return x.type === "dir" })
    }
    function refreshStats() {
        stats = seed !== "" ? backend.djPoolStats(seed, seedIsFile) : null
    }
    function pickRoom(path) {
        seed = path; seedIsFile = false; seedSongLabel = ""; refreshStats()
    }
    function styleWord(s) { return (s || "cut").replace(/_/g, " ").toUpperCase() }
    function rangeWord(r) {
        return r === "room" ? "one room" : r === "progressive" ? "progressive" : "open library"
    }
    function shapeWord(s) { return s === "rise" ? "rising" : s === "arc" ? "arc" : "steady" }
    function levelWord(l) { return l === "clean" ? "clean" : l === "wild" ? "wild" : "classic" }
    function settingsLine() {
        var s = rangeWord(backend.djRange) + " · " + levelWord(backend.djLevel)
                + " · " + shapeWord(backend.djShape)
        if (backend.djMinutes > 0) s += " · " + backend.djMinutes + " min"
        if (backend.djB2b !== "") s += " · B2B"
        return s
    }
    function cueLine(row) {
        var bits = []
        if (row.bpm) bits.push(Math.round(row.bpm))
        if (row.camelot) bits.push(row.camelot)
        else if (row.keyName) bits.push(row.keyName)
        return bits.join(" · ")
    }
    Component.onCompleted: refreshRooms()
    Connections {
        target: backend
        function onDatabaseUpdated() { deck.refreshRooms() }
        function onDjProgress(done, total, scored) {
            deck.scanLine = done >= total
                ? "Cue scan done · " + scored + " songs"
                : "Scoring " + done + " / " + total
            deck.refreshStats()
        }
        function onSettingsChanged() { deck.refreshStats() }
    }

    Flickable {
        anchors.fill: parent
        clip: true
        contentHeight: body.height + 72
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: body
            width: parent.width - 2 * Theme.pageGutter(deck.width)
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 0

            // ---- head ----
            Item { width: 1; height: Theme.pageTop(deck.height) }
            Text {
                text: "FEATURES / DJ STUDIO"
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Item { width: 1; height: 8 }
            Row {
                width: parent.width
                Text {
                    id: pageTitle
                    text: "DJ studio"
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: 34
                    font.weight: Font.Light
                    font.letterSpacing: -1
                }
                Item { width: parent.width - pageTitle.width - endSet.width; height: 1 }
                Item {
                    id: endSet
                    width: endSetLabel.width + 26
                    height: 30
                    visible: backend.djOn
                    anchors.verticalCenter: pageTitle.verticalCenter
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: "End set"
                    Accessible.onPressAction: backend.endDjSession()
                    Keys.onReturnPressed: backend.endDjSession()
                    Keys.onSpacePressed: backend.endDjSession()
                    Rectangle {
                        anchors.fill: parent
                        color: endHover.hovered ? Qt.alpha(Theme.error, 0.14) : "transparent"
                        border.width: 1
                        border.color: endSet.activeFocus ? Theme.focusRing
                                    : Qt.alpha(Theme.error, endHover.hovered ? 0.9 : 0.55)
                    }
                    Text {
                        id: endSetLabel
                        anchors.centerIn: parent
                        text: "END SET"
                        color: Theme.error
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2
                    }
                    HoverHandler { id: endHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: backend.endDjSession() }
                }
            }
            Item { width: 1; height: 6 }
            Text {
                text: (backend.djOn ? (backend.djSeed || "set") + " · " : "")
                      + deck.settingsLine()
                      + (deck.scanLine !== "" ? " · " + deck.scanLine : "")
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.weight: Font.Light
            }
            Item { width: 1; height: 18 }
            Rectangle { width: parent.width; height: 1; color: Theme.washHair }

            // ================= LIVE =================
            Column {
                visible: backend.djOn
                width: parent.width
                spacing: 0

                // the hand-off hero
                Item { width: 1; height: 26 }
                Text {
                    text: "LIVE / NEXT HAND-OFF"
                    color: Theme.primary
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.8
                }
                Item { width: 1; height: 10 }
                RowLayout {
                    width: parent.width
                    spacing: 32
                    Text {
                        Layout.fillWidth: true
                        text: backend.djNextReason
                              || "Ampere is listening for the next clean bar."
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: 27
                        font.weight: Font.Light
                        lineHeight: 1.15
                    }
                    Item {
                        id: cutBtn
                        Layout.preferredWidth: cutRow.width + 34
                        Layout.preferredHeight: 44
                        Layout.alignment: Qt.AlignVCenter
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Cut now"
                        Accessible.onPressAction: backend.djCutNow()
                        Keys.onReturnPressed: backend.djCutNow()
                        Keys.onSpacePressed: backend.djCutNow()
                        Rectangle {
                            anchors.fill: parent
                            color: cutHover.hovered ? Theme.primary : Qt.alpha(Theme.primary, 0.12)
                            border.width: 1
                            border.color: cutBtn.activeFocus ? Theme.focusRing
                                        : Qt.alpha(Theme.primary, 0.7)
                        }
                        Row {
                            id: cutRow
                            anchors.centerIn: parent
                            spacing: 9
                            Text {
                                text: "CUT NOW"
                                color: cutHover.hovered ? Theme.inkOnPrimary : Theme.primary
                                font.family: Theme.displayFont
                                font.pixelSize: 11
                                font.letterSpacing: 2.4
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Icon {
                                name: "wave"
                                size: 14
                                color: cutHover.hovered ? Theme.inkOnPrimary : Theme.primary
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        HoverHandler { id: cutHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.djCutNow() }
                    }
                }
                Item { width: 1; height: 26 }

                // the set list
                Repeater {
                    model: backend.djTimeline
                    delegate: Item {
                        id: timelineRow
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: 66
                        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.washHair }
                        RowLayout {
                            anchors.fill: parent
                            spacing: 20
                            Text {
                                text: String(index + 1).padStart(2, "0")
                                color: modelData.now ? Theme.primary : Theme.washFaint
                                font.family: Theme.font
                                font.pixelSize: Theme.fsBody
                                font.weight: Font.Light
                            }
                            Column {
                                Layout.fillWidth: true
                                spacing: 3
                                Text {
                                    text: modelData.title || ""
                                    color: modelData.now ? Theme.primary : Qt.alpha(Theme.washInk, 0.92)
                                    font.family: Theme.font
                                    font.pixelSize: Theme.fsBody
                                    font.weight: Font.Light
                                }
                                Text {
                                    text: modelData.artist || ""
                                    color: Theme.washMuted
                                    font.family: Theme.font
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                            Text {
                                text: deck.cueLine(modelData)
                                color: Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 1.4
                            }
                            Text {
                                text: modelData.now ? "NOW" : deck.styleWord(modelData.style || "")
                                color: modelData.now ? Theme.primary : Theme.washMuted
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 2
                            }
                            Text {
                                id: auditionAction
                                text: "AUDITION"
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: "Audition "
                                    + (timelineRow.modelData.title || "track")
                                Accessible.onPressAction: backend.djAudition(
                                    timelineRow.modelData.file)
                                color: activeFocus || audHover.hovered
                                    ? Theme.washInk : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 2
                                HoverHandler { id: audHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: backend.djAudition(timelineRow.modelData.file) }
                                Keys.onReturnPressed: backend.djAudition(timelineRow.modelData.file)
                                Keys.onSpacePressed: backend.djAudition(timelineRow.modelData.file)
                            }
                        }
                    }
                }

                // hand-off votes
                Row {
                    spacing: 24
                    topPadding: 22
                    Text {
                        id: goodVote
                        text: "GOOD HAND-OFF"
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Rate hand-off good"
                        Accessible.onPressAction: backend.voteTransition(true)
                        color: activeFocus || goodHover.hovered ? Theme.washInk : Theme.primary
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2
                        HoverHandler { id: goodHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.voteTransition(true) }
                        Keys.onReturnPressed: backend.voteTransition(true)
                        Keys.onSpacePressed: backend.voteTransition(true)
                    }
                    Text {
                        id: missedVote
                        text: "MISSED"
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Rate hand-off missed"
                        Accessible.onPressAction: backend.voteTransition(false)
                        color: activeFocus || badHover.hovered ? Theme.washInk : Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2
                        HoverHandler { id: badHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.voteTransition(false) }
                        Keys.onReturnPressed: backend.voteTransition(false)
                        Keys.onSpacePressed: backend.voteTransition(false)
                    }
                }
            }

            // ================= IDLE: build the set =================
            Column {
                visible: !backend.djOn
                width: parent.width
                spacing: 0

                Text {
                    topPadding: 26
                    bottomPadding: 14
                    text: "STARTING ROOM"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.6
                }
                Repeater {
                    model: deck.rooms
                    delegate: Item {
                        id: roomAction
                        required property var modelData
                        width: parent.width
                        height: 56
                        readonly property bool on: deck.seed === modelData.path
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Choose starting room " + (modelData.name || "")
                        Accessible.onPressAction: deck.pickRoom(modelData.path)
                        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.washHair }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: 1
                            height: on ? 20 : 0
                            color: Theme.primary
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: on ? 14 : 0
                            Text {
                                Layout.fillWidth: true
                                text: modelData.name || ""
                                color: roomAction.activeFocus || on ? Theme.washInk
                                     : roomHover.hovered ? Theme.washMuted : Qt.alpha(Theme.washInk, 0.78)
                                font.family: Theme.font
                                font.pixelSize: Theme.fsBody
                                font.weight: Font.Light
                            }
                            Icon {
                                name: "chevron-right"
                                size: 12
                                color: roomAction.activeFocus || on || roomHover.hovered
                                    ? Theme.primary : Theme.washFaint
                            }
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: roomAction.activeFocus ? 1 : 0
                            border.color: Theme.focusRing
                        }
                        HoverHandler { id: roomHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: deck.pickRoom(modelData.path) }
                        Keys.onReturnPressed: deck.pickRoom(modelData.path)
                        Keys.onSpacePressed: deck.pickRoom(modelData.path)
                    }
                }

                Text {
                    id: startSet
                    topPadding: 26
                    text: deck.seed !== "" ? "START THE SET" : "Choose a room to begin"
                    color: deck.seed !== ""
                           ? (activeFocus || startHover.hovered
                              ? Theme.washInk : Theme.primary) : Theme.washFaint
                    font.family: deck.seed !== "" ? Theme.displayFont : Theme.font
                    font.pixelSize: deck.seed !== "" ? 15 : Theme.fsBody
                    font.letterSpacing: deck.seed !== "" ? 3 : 0
                    font.weight: Font.Light
                    enabled: deck.seed !== ""
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: "Start the DJ set"
                    Accessible.onPressAction: backend.startDjSession(
                        deck.seed, deck.seedIsFile)
                    HoverHandler { id: startHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        enabled: deck.seed !== ""
                        onTapped: backend.startDjSession(deck.seed, deck.seedIsFile)
                    }
                    Keys.onReturnPressed: backend.startDjSession(deck.seed, deck.seedIsFile)
                    Keys.onSpacePressed: backend.startDjSession(deck.seed, deck.seedIsFile)
                }
                Text {
                    topPadding: 8
                    text: deck.stats
                          ? (deck.stats.tracks || deck.stats.count || 0)
                            + " cut-ready songs · " + deck.settingsLine()
                          : ""
                    color: Theme.washMuted
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    font.weight: Font.Light
                }

                RowLayout {
                    width: parent.width
                    height: 76
                    Text {
                        Layout.fillWidth: true
                        text: "Tune the set"
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: 22
                        font.weight: Font.Light
                    }
                    Text {
                        id: tuneAction
                        text: deck.tuneOpen ? "CLOSE" : "OPEN"
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: deck.tuneOpen ? "Close set tuning" : "Open set tuning"
                        Accessible.onPressAction: deck.tuneOpen = !deck.tuneOpen
                        color: activeFocus || tuneHover.hovered ? Theme.washInk : Theme.primary
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2
                        HoverHandler { id: tuneHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: deck.tuneOpen = !deck.tuneOpen }
                        Keys.onReturnPressed: deck.tuneOpen = !deck.tuneOpen
                        Keys.onSpacePressed: deck.tuneOpen = !deck.tuneOpen
                    }
                }
                Flow {
                    visible: deck.tuneOpen
                    width: parent.width
                    spacing: 24
                    Repeater {
                        model: [{t: "ONE ROOM", v: "room"}, {t: "PROGRESSIVE", v: "progressive"},
                                {t: "OPEN LIBRARY", v: "free"}]
                        delegate: Text {
                            id: rangeAction
                            required property var modelData
                            text: modelData.t
                            color: activeFocus ? Theme.washInk
                                : backend.djRange === modelData.v ? Theme.primary : Theme.washMuted
                            font.family: Theme.displayFont
                            font.pixelSize: 11
                            font.letterSpacing: 2
                            bottomPadding: 16
                            activeFocusOnTab: visible
                            Accessible.role: Accessible.RadioButton
                            Accessible.name: modelData.t
                            Accessible.checked: backend.djRange === modelData.v
                            Accessible.onPressAction: backend.setDjRange(modelData.v)
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.setDjRange(parent.modelData.v) }
                            Keys.onReturnPressed: backend.setDjRange(modelData.v)
                            Keys.onSpacePressed: backend.setDjRange(modelData.v)
                        }
                    }
                    Repeater {
                        model: [{t: "CLEAN", v: "clean"}, {t: "CLASSIC", v: "classic"},
                                {t: "WILD", v: "wild"}]
                        delegate: Text {
                            id: levelAction
                            required property var modelData
                            text: modelData.t
                            color: activeFocus ? Theme.washInk
                                : backend.djLevel === modelData.v ? Theme.primary : Theme.washMuted
                            font.family: Theme.displayFont
                            font.pixelSize: 11
                            font.letterSpacing: 2
                            bottomPadding: 16
                            activeFocusOnTab: visible
                            Accessible.role: Accessible.RadioButton
                            Accessible.name: modelData.t
                            Accessible.checked: backend.djLevel === modelData.v
                            Accessible.onPressAction: backend.setDjLevel(modelData.v)
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.setDjLevel(parent.modelData.v) }
                            Keys.onReturnPressed: backend.setDjLevel(modelData.v)
                            Keys.onSpacePressed: backend.setDjLevel(modelData.v)
                        }
                    }
                }
            }
        }
    }
}
