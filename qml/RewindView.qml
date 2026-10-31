import QtQuick
import QtQuick.Layouts
import "."

// Rewind — Memory Arc + Contact Sheet (Iann's verdict 2026-08-15).
// The Memory page is album-led; Chapters, recap saving, Sonic DNA, and the
// full 14–60 day history remain the established behavior beneath that visual
// composition. Canonical direction: design/SPEC.md → Rewind.
Item {
    id: view
    signal openArtistPage(string name, string path)
    property bool active: false
    property string tab: "listening"

    property var r: ({totalPlays: 0, hours: 0, tracksPlayed: 0, week: 0,
                      topArtists: [], topGenres: []})
    property var h: ({days: [], rows: []})
    property var chapters: []
    property var sound: null
    property string savedRecap: ""
    property double dayT0: 0
    property double dayT1: 0
    property int selectedDayIndex: -1
    property int contactPageStart: 0
    readonly property bool compact: width < 1080
    readonly property int contactDayCount: compact ? 5 : 7
    readonly property var contactDays: {
        var days = h.days || []
        return days.slice(contactPageStart,
                          Math.min(days.length, contactPageStart + contactDayCount))
    }
    readonly property var selectedDay: {
        var days = h.days || []
        return selectedDayIndex >= 0 && selectedDayIndex < days.length
                ? days[selectedDayIndex] : ({})
    }
    readonly property var logRows: {
        var rows = h.rows || []
        if (dayT0 === 0) return rows.slice(0, 400)
        return rows.filter(function(x) { return x.ts >= dayT0 && x.ts < dayT1 })
    }
    function applyOverview() {
        var o = backend.rewindOverview()
        if (!o.ready) return
        var previousT0 = dayT0
        r = o.stats || r
        h = o.history || h
        chapters = o.chapters || chapters
        restoreDaySelection(previousT0)
    }
    // Sonic DNA is one of the three LOCKED Rewind modes (SPEC row 33,
    // SHIPPED). It reads the shape of Iann's listening and has nothing to do
    // with the retired Saved Sound Profiles; it was removed with them by
    // mistake and is restored here (2026-08-23).
    function loadSound() { sound = backend.soundProfile(); backend.requestSoundProfile() }
    function reload() {
        applyOverview()
        backend.requestLibrarySummary()
        if (tab === "sound") loadSound()
    }
    function pickTab(t) {
        tab = t; savedRecap = ""
        if (t === "listening") restoreDaySelection(dayT0)
        if (t === "chapters") applyOverview()
        if (t === "sound") loadSound()
    }
    function saveChapterRecap(key) {
        savedRecap = backend.saveRecap(key) ? "Saving recap…" : "Recap could not be saved"
    }
    function agoText(t) {
        var d = Math.max(0, Date.now() / 1000 - t)
        return d < 3600 ? Math.floor(d / 60) + "m"
             : d < 86400 ? Math.floor(d / 3600) + "h" : Math.floor(d / 86400) + "d"
    }
    function artSource(file) {
        return file ? "image://art/full:" + encodeURIComponent(file) : ""
    }
    function dayAt(offset) {
        var days = h.days || []
        var index = selectedDayIndex + offset
        return index >= 0 && index < days.length ? days[index] : ({})
    }
    function defaultDayIndex() {
        var days = h.days || []
        for (var i = days.length - 1; i >= 0; --i)
            if ((days[i].count || 0) > 0) return i
        return days.length ? days.length - 1 : -1
    }
    function positionContactPage(index) {
        var days = h.days || []
        var count = contactDayCount
        if (!days.length) { contactPageStart = 0; return }
        var start = Math.max(0, Math.min(contactPageStart,
                                         Math.max(0, days.length - count)))
        if (index < start || index >= start + count)
            start = Math.max(0, Math.min(index - count + 1,
                                         Math.max(0, days.length - count)))
        contactPageStart = start
    }
    function selectDay(index) {
        var days = h.days || []
        if (index < 0 || index >= days.length) return
        selectedDayIndex = index
        dayT0 = Number(days[index].t0 || 0)
        dayT1 = Number(days[index].t1 || 0)
        positionContactPage(index)
    }
    function restoreDaySelection(previousT0) {
        var days = h.days || []
        if (!days.length) {
            selectedDayIndex = -1; dayT0 = 0; dayT1 = 0; contactPageStart = 0
            return
        }
        var index = -1
        for (var i = 0; i < days.length; ++i) {
            if (Number(days[i].t0 || 0) === Number(previousT0 || 0)) {
                index = i; break
            }
        }
        if (index < 0) index = defaultDayIndex()
        contactPageStart = Math.max(0, days.length - contactDayCount)
        selectDay(index)
    }
    function shiftContactPage(direction) {
        var days = h.days || []
        var lastStart = Math.max(0, days.length - contactDayCount)
        contactPageStart = Math.max(0, Math.min(lastStart,
            contactPageStart + direction * contactDayCount))
    }
    function dayDate(day) {
        return day && day.t0
            ? new Date(day.t0 * 1000).toLocaleDateString(Qt.locale(), "dddd · MMM d")
            : "Listening day"
    }
    function dayStory(day) {
        if (!day || !(day.count > 0)) return "No listening recorded"
        var lead = day.album || day.artist || day.title || "Your music"
        var records = Number(day.records || 0)
        return lead + " led the day · " + records
            + (records === 1 ? " record returned" : " records returned")
    }
    onCompactChanged: Qt.callLater(function() {
        view.positionContactPage(view.selectedDayIndex)
    })
    onActiveChanged: if (active) reload()
    Connections {
        target: backend
        function onDatabaseUpdated() { if (view.active) view.reload() }
        function onLibrarySummaryChanged() { if (view.active) view.applyOverview() }
        function onSoundProfileChanged() {
            if (view.active && view.tab === "sound") view.sound = backend.soundProfile()
        }
        function onRecapSaveFinished(name, success) {
            view.savedRecap = success ? "Saved “" + name + "”" : "Recap could not be saved"
        }
    }

    Flickable {
        objectName: "rewindScroller"
        anchors.fill: parent
        clip: true
        contentHeight: body.height + 72
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: body
            width: parent.width - 2 * Theme.pageGutter(view.width)
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 0

            // ---- page head: wash voice ----
            // Opens below the protected AMPERE wordmark band.
            Item { width: 1; height: Theme.pageTop(view.height) }
            Item {
                width: parent.width
                height: view.compact ? 124 : 82

                Column {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    spacing: 6
                    Text {
                        text: "HOME / LISTENING MEMORY"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2.8
                    }
                    Text {
                        text: "Rewind"
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: view.compact ? 34 : 36
                        font.weight: Font.Light
                        font.letterSpacing: -1.1
                    }
                }

                Row {
                    anchors.left: view.compact ? parent.left : undefined
                    anchors.right: view.compact ? undefined : parent.right
                    anchors.bottom: parent.bottom
                    spacing: view.compact ? 24 : 30
                    Repeater {
                        model: [{k: "listening", t: "MEMORY"},
                                {k: "chapters", t: "CHAPTERS"},
                                {k: "sound", t: "SONIC DNA"}]
                        delegate: Text {
                            required property var modelData
                            activeFocusOnTab: true
                            Accessible.role: Accessible.PageTab
                            Accessible.name: modelData.t
                            Accessible.onPressAction: view.pickTab(modelData.k)
                            text: modelData.t
                            color: activeFocus || view.tab === modelData.k
                                ? Theme.washInk : Theme.washFaint
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2.6
                            bottomPadding: 10
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: view.tab === parent.modelData.k
                                    || parent.activeFocus ? 1 : 0
                                color: Theme.primary
                            }
                            TapHandler { onTapped: view.pickTab(parent.modelData.k) }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            Keys.onReturnPressed: view.pickTab(modelData.k)
                            Keys.onSpacePressed: view.pickTab(modelData.k)
                        }
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.washHair }

            // ================= LISTENING =================
            Item {
                id: memoryRoom
                objectName: "rewindMemoryRoom"
                visible: view.tab === "listening"
                width: parent.width
                height: Math.max(view.compact ? 650 : 610,
                                 view.height - Theme.pageTop(view.height) - 150)

                Column {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.topMargin: view.compact ? 22 : 30
                    width: view.compact ? parent.width * 0.60 : parent.width * 0.25
                    spacing: 8
                    Text {
                        text: "MEMORY ARC · 30 DAYS"
                        color: Theme.primary
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2.6
                    }
                    Text {
                        text: view.compact ? "Your listening,\nstill moving."
                                           : "Your listening,\nstill moving."
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: view.compact ? 32 : 46
                        font.weight: Font.Light
                        font.letterSpacing: -1.4
                        lineHeight: 0.96
                    }
                    Text {
                        visible: !view.compact
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Choose a day and the records that shaped it come back into focus."
                        color: Theme.washMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.Light
                        lineHeight: 1.45
                    }
                }

                Column {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: view.compact ? 26 : 28
                    spacing: 8
                    Text {
                        anchors.right: parent.right
                        text: view.r.week || 0
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: view.compact ? 48 : 74
                        font.weight: Font.ExtraLight
                        font.letterSpacing: -3
                    }
                    Text {
                        anchors.right: parent.right
                        text: "PLAYS THIS WEEK"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2.4
                    }
                }

                Item {
                    id: heroArc
                    x: view.compact ? 0 : parent.width * 0.25
                    y: view.compact ? 112 : 6
                    width: view.compact ? parent.width : parent.width * 0.62
                    height: view.compact ? 350 : 410

                    readonly property real mainSize: view.compact
                        ? Math.min(270, width * 0.58) : Math.min(330, height * 0.80)

                    MediaArtwork {
                        width: heroArc.mainSize * 0.34
                        height: width
                        x: heroArc.width * 0.03
                        y: heroArc.height * 0.16
                        source: view.artSource(view.dayAt(-4).file || "")
                        opacity: 0.38
                        rotation: -6
                    }
                    MediaArtwork {
                        width: heroArc.mainSize * 0.55
                        height: width
                        x: heroArc.width * 0.12
                        y: heroArc.height * 0.35
                        source: view.artSource(view.dayAt(-1).file || "")
                        opacity: 0.72
                        rotation: -3
                    }
                    MediaArtwork {
                        id: selectedSleeve
                        objectName: "rewindSelectedSleeve"
                        z: 3
                        width: heroArc.mainSize
                        height: width
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        source: view.artSource(view.selectedDay.file || "")
                        decodeSize: 720
                        fallbackColor: Qt.alpha(Theme.raisedSurface, 0.94)
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: 1
                            border.color: Qt.alpha(Theme.washInk, 0.20)
                        }
                    }
                    MediaArtwork {
                        width: heroArc.mainSize * 0.55
                        height: width
                        x: heroArc.width - width - heroArc.width * 0.12
                        y: heroArc.height * 0.35
                        source: view.artSource(view.dayAt(-1).file || "")
                        opacity: 0.72
                        rotation: 3
                    }
                    MediaArtwork {
                        width: heroArc.mainSize * 0.34
                        height: width
                        x: heroArc.width - width - heroArc.width * 0.03
                        y: heroArc.height * 0.16
                        source: view.artSource(view.dayAt(-3).file || "")
                        opacity: 0.38
                        rotation: 6
                    }
                }

                Column {
                    x: view.compact ? 4 : parent.width * 0.64
                    y: view.compact ? 392 : 334
                    width: view.compact ? parent.width * 0.88 : parent.width * 0.32
                    spacing: 6
                    Text {
                        text: view.dayDate(view.selectedDay).toUpperCase()
                            + " · " + Number(view.selectedDay.count || 0) + " PLAYS"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2.2
                    }
                    Text {
                        text: "The hour found its shape."
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: view.compact ? 24 : 28
                        font.weight: Font.Light
                        font.letterSpacing: -0.8
                    }
                    Text {
                        width: parent.width
                        text: view.dayStory(view.selectedDay)
                        elide: Text.ElideRight
                        color: Theme.washMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.Light
                    }
                }

                Item {
                    id: lowerBand
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 16
                    height: view.compact ? 158 : 138

                    Row {
                        id: lifetimeStats
                        anchors.left: parent.left
                        anchors.top: parent.top
                        width: view.compact ? parent.width : 280
                        height: 52
                        Repeater {
                            model: [
                                {v: view.r.totalPlays || 0, l: "ALL-TIME PLAYS"},
                                {v: Math.round(view.r.hours || 0) + "h", l: "IN THE ROOM"},
                                {v: view.r.tracksPlayed || 0, l: "TRACKS TOUCHED"}
                            ]
                            delegate: Column {
                                required property var modelData
                                width: lifetimeStats.width / 3
                                spacing: 5
                                Text {
                                    text: parent.modelData.v
                                    color: Theme.washInk
                                    font.family: Theme.font
                                    font.pixelSize: view.compact ? 20 : 24
                                    font.weight: Font.Light
                                }
                                Text {
                                    text: parent.modelData.l
                                    color: Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: view.compact ? 8 : 9
                                    font.letterSpacing: 1.5
                                }
                            }
                        }
                    }

                    Item {
                        id: contactSheet
                        objectName: "rewindContactSheet"
                        anchors.left: view.compact ? parent.left : lifetimeStats.right
                        anchors.leftMargin: view.compact ? 0 : 48
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: view.compact ? 62 : 0
                        height: view.compact ? 94 : parent.height

                        Text {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            text: view.compact ? "RECENT LISTENING DAYS" : "SEVEN LISTENING DAYS"
                            color: Theme.washFaint
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2.2
                        }
                        Row {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: -14
                            Item {
                                id: earlierDays
                                width: 44; height: 44
                                enabled: view.contactPageStart > 0
                                activeFocusOnTab: enabled
                                Accessible.role: Accessible.Button
                                Accessible.name: "Earlier listening days"
                                Accessible.onPressAction: view.shiftContactPage(-1)
                                Icon {
                                    anchors.centerIn: parent
                                    name: "chevron-left"
                                    size: 15
                                    color: earlierDays.enabled ? Theme.washMuted : Theme.washHair
                                }
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: view.shiftContactPage(-1) }
                                Keys.onReturnPressed: view.shiftContactPage(-1)
                                Keys.onSpacePressed: view.shiftContactPage(-1)
                                Rectangle { anchors.fill: parent; color: "transparent"; border.width: parent.activeFocus ? 1 : 0; border.color: Theme.focusRing }
                            }
                            Item {
                                id: laterDays
                                width: 44; height: 44
                                enabled: view.contactPageStart + view.contactDayCount
                                         < (view.h.days || []).length
                                activeFocusOnTab: enabled
                                Accessible.role: Accessible.Button
                                Accessible.name: "Later listening days"
                                Accessible.onPressAction: view.shiftContactPage(1)
                                Icon {
                                    anchors.centerIn: parent
                                    name: "chevron-right"
                                    size: 15
                                    color: laterDays.enabled ? Theme.washMuted : Theme.washHair
                                }
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: view.shiftContactPage(1) }
                                Keys.onReturnPressed: view.shiftContactPage(1)
                                Keys.onSpacePressed: view.shiftContactPage(1)
                                Rectangle { anchors.fill: parent; color: "transparent"; border.width: parent.activeFocus ? 1 : 0; border.color: Theme.focusRing }
                            }
                        }
                        Row {
                            id: contactRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: view.compact ? 74 : 104
                            spacing: view.compact ? 8 : 10
                            Repeater {
                                model: view.contactDays
                                delegate: Item {
                                    id: contactDay
                                    objectName: "rewindContactDay"
                                    required property var modelData
                                    required property int index
                                    readonly property int sourceIndex: view.contactPageStart + index
                                    readonly property bool selected: sourceIndex === view.selectedDayIndex
                                    width: (contactRow.width - contactRow.spacing
                                            * Math.max(0, view.contactDays.length - 1))
                                           / Math.max(1, view.contactDays.length)
                                    height: contactRow.height
                                    activeFocusOnTab: true
                                    Accessible.role: Accessible.Button
                                    Accessible.name: String(modelData.label || "Listening day")
                                        + ", " + Number(modelData.count || 0) + " plays"
                                    Accessible.description: selected ? "Selected listening day" : "Choose listening day"
                                    Accessible.onPressAction: view.selectDay(sourceIndex)

                                    MediaArtwork {
                                        id: contactArt
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.top: parent.top
                                        width: Math.min(view.compact ? 64 : 76, parent.width - 4)
                                        height: width
                                        source: view.artSource(contactDay.modelData.file || "")
                                        opacity: contactDay.selected || contactHover.hovered ? 1 : 0.66
                                        fallbackColor: Qt.alpha(Theme.raisedSurface, 0.90)
                                        Rectangle {
                                            anchors.fill: parent
                                            color: "transparent"
                                            border.width: contactDay.selected ? 2 : 1
                                            border.color: contactDay.selected ? Theme.primary
                                                : Qt.alpha(Theme.washInk, 0.16)
                                        }
                                    }
                                    Text {
                                        anchors.left: contactArt.left
                                        anchors.right: contactArt.right
                                        anchors.top: contactArt.bottom
                                        anchors.topMargin: 7
                                        text: String(contactDay.modelData.label || "")
                                        color: contactDay.selected ? Theme.primary : Theme.washMuted
                                        font.family: Theme.displayFont
                                        font.pixelSize: Theme.washMicro
                                        font.letterSpacing: 1.1
                                        horizontalAlignment: Text.AlignLeft
                                    }
                                    HoverHandler { id: contactHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { onTapped: view.selectDay(contactDay.sourceIndex) }
                                    Keys.onReturnPressed: view.selectDay(sourceIndex)
                                    Keys.onSpacePressed: view.selectDay(sourceIndex)
                                    Rectangle {
                                        anchors.fill: parent
                                        anchors.margins: -2
                                        color: "transparent"
                                        border.width: contactDay.activeFocus ? 1 : 0
                                        border.color: Theme.focusRing
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ================= CHAPTERS (R4 voice) =================
            Column {
                visible: view.tab === "chapters"
                width: parent.width
                spacing: 0
                Text {
                    visible: view.savedRecap !== ""
                    width: parent.width
                    topPadding: 18
                    bottomPadding: 18
                    wrapMode: Text.WordWrap
                    text: view.savedRecap
                    color: view.savedRecap.indexOf("Saved ") === 0 ? Theme.secondary : Theme.primary
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
                Repeater {
                    model: view.chapters
                    delegate: Item {
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: 116
                        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.washHair }
                        RowLayout {
                            anchors.fill: parent
                            spacing: 24
                            Text {
                                text: String(index + 1).padStart(2, "0")
                                color: Theme.washFaint
                                font.family: Theme.font
                                font.pixelSize: 30
                                font.weight: Font.Light
                            }
                            Column {
                                Layout.fillWidth: true
                                spacing: 5
                                Text {
                                    text: modelData.title || modelData.label || "Listening chapter"
                                    color: Theme.washInk
                                    font.family: Theme.font
                                    font.pixelSize: 22
                                    font.weight: Font.Light
                                }
                                Text {
                                    text: modelData.sub || modelData.summary || ""
                                    color: Theme.washMuted
                                    font.family: Theme.font
                                    font.pixelSize: Theme.fsSmall
                                }
                            }
                            Text {
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: "Save " + (modelData.title || modelData.label
                                                 || "listening chapter") + " recap"
                                Accessible.onPressAction: view.saveChapterRecap(modelData.key)
                                text: "SAVE RECAP"
                                color: activeFocus || recapHover.hovered ? Theme.washInk : Theme.primary
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.washMicro
                                font.letterSpacing: 2
                                TapHandler { onTapped: view.saveChapterRecap(modelData.key) }
                                HoverHandler { id: recapHover; cursorShape: Qt.PointingHandCursor }
                                Keys.onReturnPressed: view.saveChapterRecap(modelData.key)
                                Keys.onSpacePressed: view.saveChapterRecap(modelData.key)
                            }
                        }
                    }
                }
            }

        }
    }
}
