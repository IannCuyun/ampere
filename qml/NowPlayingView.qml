import QtQuick
import QtQuick.Layouts
import "."

// Now Playing — Playback B "Album Room" (Iann's verdict 2026-07-31 + two
// tweaks, design/SPEC.md sprint-locks; round: proposals/playback-round §B).
// The bottom player bar does NOT exist on this page: the full transport is
// integrated here. Large square artwork is the room's architectural center;
// beside it the track identity, a restrained glass ledger (tech + story),
// the waveform with chapters, and the complete control deck share one view.
Item {
    id: view
    signal ambient()
    signal openLyrics()
    signal toggleQueue()
    signal toggleMini()
    property var spectrumBands: []
    property bool suspended: false
    readonly property bool compact: width < 900

    readonly property var upNext: backend.upcomingQueue

    RoomGradient {
        anchors.fill: parent
        topColor: Theme.mix(Theme.bg, Theme.artVividEased, 0.32)
        bottomColor: Theme.bgLow
    }

    Loader {
        anchors.fill: parent
        active: view.active
        sourceComponent: VisualizerField {
            active: view.active && !view.suspended
            bands: view.spectrumBands
            intensity: 0.9
        }
    }

    // bound to the page mode in Main.qml — PageSlot's opacity-visibility is
    // not a reliable open/close signal for children
    property bool active: false

    property var story: null
    property var chaps: []
    function refreshStory() {
        var f = backend.currentSong.file || ""
        story = f !== "" ? backend.songStory(f) : null
        chaps = f !== "" ? backend.trackChapters(f) : []
    }
    Connections {
        target: backend
        function onSongChanged() { if (view.active) view.refreshStory() }
        function onSpectrumFrame(b) { if (view.active) view.spectrumBands = b }
        function onWaveformChanged() {
            if (view.active && view.chaps.length === 0)
                view.chaps = backend.trackChapters(backend.currentSong.file || "")
        }
    }
    onActiveChanged: syncSpectrum()
    onSuspendedChanged: syncSpectrum()
    function syncSpectrum() {
        if (active && !suspended) {
            refreshStory()
            backend.startSpectrum("now")
        } else {
            backend.stopSpectrum("now")
            spectrumBands = []
        }
    }

    property int lastVol: 60
    function toggleMute() {
        if (backend.volume > 0) { lastVol = backend.volume; backend.requestVolume(0) }
        else backend.requestVolume(lastVol > 0 ? lastVol : 50)
    }

    // Quiet page controls, top right. The four-corner control is Ambient's
    // entrance at every width; raw window fullscreen remains available on F11.
    Row {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 16
        z: 5
        spacing: 4
        GlowButton {
            icon: "mini"; glyphSize: 15
            tip: "Mini player"
            onClicked: view.toggleMini()
        }
        GlowButton {
            icon: "fullscreen"; glyphSize: 15
            tip: "Ambient mode — art, spectrum, lyrics. Click or Esc leaves."
            onClicked: view.ambient()
        }
    }

    NumberAnimation {
        id: scrollAnim
        target: flick
        property: "contentY"
        duration: 450
        easing.type: Easing.InOutQuad
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: hero.height + nextList.height + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        // ---- page 1: the album room, exactly one viewport tall ----
        Item {
            id: hero
            width: flick.width
            height: flick.height

            GridLayout {
                id: heroGrid
                // clear the whisper rail's zone at the left — the room's
                // content never sits under the navigation
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: view.compact ? 58 : 78
                anchors.rightMargin: view.compact ? 24 : 48
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -10
                columns: view.compact ? 1 : 2
                columnSpacing: view.compact ? 0 : 48
                rowSpacing: view.compact ? 16 : 0
                // the info column needs ~540px of instruments; the record
                // takes what remains, capped by the room's height
                readonly property int artSide: view.compact
                    ? Math.min(300, hero.height * 0.34, width - 48)
                    : Math.max(280, Math.min(560, hero.height * 0.80, width - 588))

                // the record — architectural center of the room
                MediaArtwork {
                    Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
                    Layout.preferredWidth: heroGrid.artSide
                    Layout.preferredHeight: Layout.preferredWidth
                    kind: "album"
                    source: backend.currentSong.file
                            ? "image://art/" + encodeURIComponent(backend.currentSong.file) : ""
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: view.compact ? 10 : 14

                    Text {
                        text: "NOW PLAYING"
                              + (backend.queuePos >= 0 ? " / TRACK " + (backend.queuePos + 1) : "")
                        color: Theme.primary
                        font.family: Theme.displayFont
                        font.pixelSize: 10
                        font.letterSpacing: 2.8
                    }
                    Text {
                        Layout.fillWidth: true
                        text: backend.currentSong.title || "—"
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        color: Theme.text
                        font.family: Theme.font
                        font.pixelSize: view.compact ? 30 : 44
                        font.weight: Font.Light
                        font.letterSpacing: -((view.compact ? 30 : 44) * 0.03)
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text {
                            text: backend.currentSong.artist || ""
                            elide: Text.ElideRight
                            color: Theme.textDim
                            font.family: Theme.font
                            font.pixelSize: Theme.fsEmph
                            font.weight: Font.Light
                        }
                        Text {
                            Layout.fillWidth: true
                            text: backend.currentSong.album
                                  ? "/  " + backend.currentSong.album
                                    + (backend.currentSong.year ? " · " + backend.currentSong.year : "")
                                  : ""
                            elide: Text.ElideRight
                            color: Theme.textMuted
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                        }
                    }

                    // the glass ledger: tech truth + his story with the song
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: ledgerCol.height + 20
                        color: Qt.alpha("#0d0c0c", 0.52)
                        border.width: 1
                        border.color: Theme.washHair
                        Column {
                            id: ledgerCol
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 4
                            Text {
                                width: parent.width
                                text: backend.audioInfo
                                      + (backend.liveKbps > 0 && backend.state === "play"
                                         ? "  ·  " + backend.liveKbps + " kbps live" : "")
                                elide: Text.ElideRight
                                color: Theme.textMuted
                                font.family: Theme.font
                                font.pixelSize: Theme.fsSmall
                            }
                            Text {
                                width: parent.width
                                visible: text !== ""
                                text: {
                                    var s = view.story
                                    if (!s || (s.plays === 0 && s.firstHeard === 0)) return ""
                                    var bits = []
                                    if (s.firstHeard > 0)
                                        bits.push("first heard " + new Date(s.firstHeard * 1000)
                                                  .toLocaleDateString(Qt.locale(), "MMM d"))
                                    if (s.plays > 0)
                                        bits.push(s.plays + (s.plays === 1 ? " play" : " plays"))
                                    if (s.rankMonth > 0 && s.rankMonth <= 20)
                                        bits.push("#" + s.rankMonth + " this month")
                                    if (s.hourWord !== "")
                                        bits.push("usually " + s.hourWord + " song")
                                    return bits.join("  ·  ")
                                }
                                elide: Text.ElideRight
                                color: Theme.secondary
                                font.family: Theme.font
                                font.pixelSize: Theme.fsSmall
                            }
                        }
                    }

                    // waveform + chapters, time-labelled
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Text {
                            Layout.preferredWidth: 42
                            horizontalAlignment: Text.AlignRight
                            text: Theme.fmtTime(backend.elapsed)
                            color: Theme.textDim
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                        }
                        WaveSeek {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 52
                            chapters: view.chaps
                        }
                        Text {
                            Layout.preferredWidth: 42
                            text: Theme.fmtTime(backend.duration)
                            color: Theme.textDim
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                        }
                    }

                    // ---- the integrated transport deck (replaces the bar) ----
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        spacing: 7
                        GlowButton {
                            visible: Theme.heartsOn
                            heartIcon: true
                            active: backend.likedFiles.indexOf(backend.currentSong.file || "") >= 0
                            tip: active ? "Remove from Liked" : "Add to Liked"
                            onClicked: backend.toggleLike(backend.currentSong.file || "")
                        }
                        Item { Layout.fillWidth: true }
                        GlowButton { shuffleIcon: true; tip: "Reshuffle queue"; onClicked: backend.requestReshuffleQueue() }
                        GlowButton { icon: "prev"; glyphSize: 18; tip: "Previous"; onClicked: backend.requestPrevious() }
                        Item {
                            Layout.preferredWidth: 50
                            Layout.preferredHeight: 50
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: backend.state === "play" ? "Pause" : "Play"
                            scale: playTap.pressed ? 0.955 : 1
                            Behavior on scale { NumberAnimation { duration: 65; easing.type: Easing.OutCubic } }
                            Rectangle {
                                anchors.fill: parent
                                radius: width / 2
                                color: playHover.hovered ? Theme.text : Theme.primary
                            }
                            Icon { anchors.centerIn: parent; name: backend.state === "play" ? "pause" : "play"; size: 20; color: Theme.inkOnPrimary }
                            HoverHandler { id: playHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { id: playTap; onTapped: backend.requestPlayPause() }
                            Keys.onReturnPressed: backend.requestPlayPause()
                            Keys.onSpacePressed: backend.requestPlayPause()
                        }
                        GlowButton { icon: "next"; glyphSize: 18; tip: "Next"; onClicked: backend.requestNext() }
                        GlowButton {
                            icon: "loop"
                            active: backend.repeat
                            badgeText: backend.repeat && backend.single ? "1" : ""
                            tip: !backend.repeat ? "Loop off"
                                 : backend.single ? "Repeat current song"
                                 : "Loop current queue"
                            onClicked: backend.requestCycleRepeat()
                        }
                        Item { Layout.fillWidth: true }
                        GlowButton { icon: "note"; tip: "Lyrics"; onClicked: view.openLyrics() }
                        GlowButton { icon: "list"; tip: "Up next"; onClicked: view.toggleQueue() }
                        GlowButton { volumeIcon: true; volumeMuted: backend.volume <= 0; tip: "Volume " + backend.volume; onClicked: view.toggleMute() }
                        AmpereSlider {
                            visible: !view.compact
                            Layout.preferredWidth: 84
                            from: 0; to: 100
                            value: backend.volume
                            accent: Theme.primary
                            onMoved: backend.requestVolume(value)
                        }
                    }
                }
            }

            // UP NEXT — pinned near the bottom of the room
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 26
                spacing: 12
                visible: view.upNext.length > 0

                Icon { name: "chevron-down"; size: 13; color: upNextHover.hovered ? Theme.primary : Theme.textDim; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: "Up next"
                    color: upNextHover.hovered ? Theme.primary : Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
                Icon { name: "chevron-down"; size: 13; color: upNextHover.hovered ? Theme.primary : Theme.textDim; anchors.verticalCenter: parent.verticalCenter }

                HoverHandler { id: upNextHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        scrollAnim.to = hero.height * 0.92
                        scrollAnim.restart()
                    }
                }
            }
        }

        // ---- page 2: the list, below the fold ----
        ColumnLayout {
            id: nextList
            y: hero.height
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(640, flick.width - 80)
            spacing: 4

            Repeater {
                model: view.upNext
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    height: 52
                    radius: 0
                    color: nextHover.hovered ? Theme.hoverSurface : "transparent"
                    border.width: 0
                    HoverHandler { id: nextHover }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 16
                        spacing: 12
                        MediaArtwork {
                            Layout.preferredWidth: 38
                            Layout.preferredHeight: 38
                            kind: "album"
                            source: "image://art/" + encodeURIComponent(modelData.file)
                        }
                        Column {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                width: parent.width
                                text: modelData.title
                                elide: Text.ElideRight
                                color: nextHover.hovered ? Theme.primary : Theme.text
                                font.family: Theme.font
                                font.pixelSize: Theme.fsBody
                            }
                            Text {
                                width: parent.width
                                text: modelData.artist
                                elide: Text.ElideRight
                                color: Qt.alpha(Theme.textDim, 0.85)
                                font.family: Theme.font
                                font.pixelSize: Theme.fsSmall
                            }
                        }
                        Text {
                            text: Theme.fmtTime(modelData.duration)
                            color: Qt.alpha(Theme.textDim, 0.65)
                            font.family: Theme.font
                            font.pixelSize: Theme.fsSmall
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        z: -1
                        cursorShape: Qt.PointingHandCursor
                        onDoubleClicked: backend.playPosition(backend.queuePos + 1 + index)
                    }
                }
            }
        }
    }
}
