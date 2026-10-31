import QtQuick
import "."

// Lyrics — "Continuous Ledger" (Iann's verdict 2026-07-31; round:
// proposals/utility-round §Lyrics), WITHOUT the redundant current-line
// marker element. The recording's identity sits in a quiet aside; the lines
// flow as one left-aligned ledger. Karaoke-follow and click-to-seek behavior
// preserved — the sung line lifts by ink alone.
Item {
    id: view
    property int cur: -1
    property bool autoFollow: true
    readonly property bool compact: width < 860

    RoomGradient {
        anchors.fill: parent
        topColor: Theme.mix(Theme.bgHigh, Theme.artVividEased, 0.16)
        bottomColor: Theme.bgLow
    }

    // page head — wash voice
    Column {
        id: head
        anchors.left: parent.left
        anchors.leftMargin: 44
        anchors.top: parent.top
        anchors.topMargin: 30
        spacing: 8
        z: 2
        Text {
            text: "NOW PLAYING / LYRICS"
            color: Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.8
        }
        Text {
            text: "Lyrics"
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: 30
            font.weight: Font.Light
            font.letterSpacing: -0.9
        }
        Text {
            text: backend.lyricsSynced
                  ? "Following the recording / select a timed line to seek"
                  : "Embedded lyrics"
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            font.weight: Font.Light
        }
    }

    // the recording's identity — quiet aside beside the ledger
    Column {
        visible: !view.compact
        anchors.left: parent.left
        anchors.leftMargin: 44
        anchors.top: head.bottom
        anchors.topMargin: 34
        width: 190
        spacing: 10
        MediaArtwork {
            width: 160
            height: 160
            kind: "album"
            source: backend.currentSong.file
                    ? "image://art/" + encodeURIComponent(backend.currentSong.file) : ""
        }
        Text {
            width: parent.width
            text: backend.currentSong.title || ""
            elide: Text.ElideRight
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
            font.weight: Font.Light
        }
        Text {
            width: parent.width
            text: (backend.currentSong.artist || "")
                  + (backend.currentSong.album ? " / " + backend.currentSong.album : "")
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
        }
        Text {
            text: backend.lyricsSynced ? "Synced embedded lyrics" : "Plain embedded lyrics"
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 1.8
        }
    }

    function recompute() {
        var ls = backend.lyrics
        if (!backend.lyricsSynced || ls.length === 0) { cur = -1; return }
        var e = backend.elapsed + 0.3   // slight lead so lines light as they're sung
        var c = -1
        for (var i = 0; i < ls.length; i++) {
            if (ls[i].t <= e) c = i
            else break
        }
        if (c !== cur) {
            cur = c
            if (autoFollow && c >= 0)
                lv.currentIndex = c   // highlight range slides the list up through it
        }
    }

    Connections {
        target: backend
        function onStatusChanged() { if (view.visible) view.recompute() }
        function onLyricsChanged() {
            view.cur = -1
            view.autoFollow = true
            if (backend.lyrics.length > 0) lv.positionViewAtIndex(0, ListView.Beginning)
            view.recompute()
        }
    }
    onVisibleChanged: if (visible) { autoFollow = true; recompute() }

    Timer {
        id: resumeFollow
        interval: 4000
        onTriggered: {
            view.autoFollow = true
            if (view.cur >= 0) lv.currentIndex = view.cur
        }
    }
    WheelHandler {
        target: null
        onWheel: (ev) => {
            view.autoFollow = false
            resumeFollow.restart()
            lv.flick(0, ev.angleDelta.y > 0 ? 500 : -500)
        }
    }

    ListView {
        id: lv
        anchors.fill: parent
        anchors.leftMargin: view.compact ? 58 : 300
        anchors.rightMargin: Math.max(48, width * 0.14)
        anchors.topMargin: 132
        anchors.bottomMargin: 24
        clip: true
        model: backend.lyrics
        spacing: 16
        // the active line lives in the upper quarter; everything slides up to it
        highlightRangeMode: ListView.ApplyRange
        preferredHighlightBegin: height * 0.20
        preferredHighlightEnd: height * 0.30
        highlightMoveDuration: 550
        highlightMoveVelocity: -1
        highlightFollowsCurrentItem: true
        header: Item { width: 1; height: lv.height * 0.20 }
        // small footer: near the song's end the view runs out of scroll room,
        // so the last lines rest around 3/4 down instead of climbing to the band
        footer: Item { width: 1; height: lv.height * 0.25 }
        onDragStarted: { view.autoFollow = false; resumeFollow.restart() }
        onFlickStarted: { view.autoFollow = false; resumeFollow.restart() }

        delegate: Text {
            required property var modelData
            required property int index
            width: lv.width
            horizontalAlignment: Text.AlignLeft
            wrapMode: Text.Wrap
            text: modelData.line === "" ? "· · ·" : modelData.line
            color: index === view.cur ? Theme.washInk
                 : Qt.alpha(Theme.washInk, backend.lyricsSynced ? 0.26 : 0.68)
            font.family: Theme.font
            font.pixelSize: index === view.cur ? 26 : 19
            font.weight: Font.Light
            Behavior on color { ColorAnimation { duration: 160 } }
            MouseArea {
                anchors.fill: parent
                enabled: modelData.t >= 0
                cursorShape: Qt.PointingHandCursor
                onClicked: backend.requestSeek(modelData.t)
            }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 8
        visible: backend.lyrics.length === 0
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: "note"
            size: 40
            color: Qt.alpha(Theme.outline, 0.9)
        }
        Text {
            text: "No lyrics embedded in this file"
            color: Qt.alpha(Theme.textDim, 0.6)
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
        }
    }
}
