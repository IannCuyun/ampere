import QtQuick
import "."

// AMBIENT — Gallery Title (Direction 5, selected 2026-08-23).
//
// The title and quiet artist / album line label the complete centered sleeve;
// one synchronized lyric moment answers beneath it. There is no navigation,
// utility chrome, visualizer, clock, secondary mode, invented environment, or
// decorative motion. See design/SPEC.md · Ambient · Gallery Title revision.
//
// Any click or Esc returns to the player.
FocusScope {
    id: ambient
    signal closed()

    // The view is preconstructed while hidden. This explicit lifecycle flag
    // prevents that warm instance from owning focus or animations.
    property bool presentationActive: false
    property bool resizeActive: false
    property int currentLyric: -1

    readonly property bool compact: width < 760 || width / Math.max(1, height) < 0.9
    readonly property real albumSize: compact
        ? Math.min(width * 0.64, height * 0.38)
        : Math.min(height * 0.55, width * 0.43, 720)
    readonly property real albumTop: compact
        ? Math.max(104, height * 0.18)
        : Math.max(132, height * 0.16)
    readonly property real albumBottom: albumTop + albumSize
    readonly property real lyricTop: albumBottom
        + Math.max(24, Math.min(36, height * 0.034))

    function recomputeLyrics() {
        var lyrics = backend.lyrics
        if (!backend.lyricsSynced || lyrics.length === 0) {
            currentLyric = -1
            return
        }
        var elapsed = backend.elapsed + 0.3
        var cursor = -1
        for (var i = 0; i < lyrics.length; ++i) {
            if (lyrics[i].t <= elapsed)
                cursor = i
            else
                break
        }
        currentLyric = cursor
    }

    function lyricLine(index) {
        return index >= 0 && index < backend.lyrics.length
                ? (backend.lyrics[index].line || "· · ·") : ""
    }

    Connections {
        target: backend
        function onStatusChanged() {
            if (ambient.presentationActive)
                ambient.recomputeLyrics()
        }
        function onLyricsChanged() {
            ambient.currentLyric = -1
            if (ambient.presentationActive)
                ambient.recomputeLyrics()
        }
    }

    onPresentationActiveChanged: {
        if (presentationActive) {
            recomputeLyrics()
            Qt.callLater(ambient.forceActiveFocus)
        }
    }

    // Ambient is the same record-room treatment as normal Now Playing:
    // one shared Archive Wash, soft album fill only, with its 0.60 veil.
    // Keep this as the shared component rather than approximating the album
    // underlay with a screen-local gradient (Iann, 2026-08-23).
    ArchiveWash {
        anchors.fill: parent
        sourceFile: backend.currentSong.file || ""
        veil: 0.60
        fitStrength: 0.0
    }

    // Gallery Title: one centered exhibition label above the record.
    Column {
        id: identityColumn
        objectName: "ambientIdentity"
        anchors.horizontalCenter: parent.horizontalCenter
        y: ambient.compact
            ? Math.max(28, ambient.height * 0.055)
            : Math.max(44, ambient.height * 0.057)
        spacing: ambient.compact ? 6 : 8
        width: Math.min(740, parent.width * (ambient.compact ? 0.88 : 0.72))

        Text {
            width: parent.width
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            text: backend.currentSong.title || "—"
            color: Qt.alpha(Theme.text, 0.92)
            font.family: Theme.displayFont
            font.pixelSize: ambient.compact
                ? Math.max(22, Math.min(30, ambient.width * 0.040))
                : Math.max(30, Math.min(48, ambient.width * 0.025))
            font.weight: Font.Medium
        }
        Text {
            width: parent.width
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            text: (backend.currentSong.artist || "").toUpperCase()
                  + (backend.currentSong.album
                     ? "  ·  " + backend.currentSong.album.toUpperCase() : "")
            color: Qt.alpha(Theme.textDim, 0.64)
            font.family: Theme.font
            font.pixelSize: ambient.compact ? 10 : 12
            font.letterSpacing: 1.2
        }
    }

    Item {
        id: albumMount
        objectName: "ambientArtwork"
        width: ambient.albumSize
        height: width
        anchors.horizontalCenter: parent.horizontalCenter
        y: ambient.albumTop

        Rectangle {
            anchors.fill: parent
            anchors.margins: -Math.max(2, ambient.albumSize * 0.009)
            color: "#09090c"
            border.width: 1
            border.color: Qt.alpha(Theme.washInk, 0.30)
        }

        MediaArtwork {
            anchors.fill: parent
            kind: "album"
            decodeSize: 1536
            source: backend.currentSong.file
                    ? "image://art/full:"
                      + encodeURIComponent(backend.currentSong.file)
                    : ""
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: 1
            border.color: Qt.alpha(Theme.primary, 0.34)
        }
    }

    Column {
        id: lyricColumn
        objectName: "ambientLyricColumn"
        visible: ambient.currentLyric >= 0
        anchors.horizontalCenter: parent.horizontalCenter
        y: ambient.lyricTop
        width: Math.min(900, ambient.width * (ambient.compact ? 0.90 : 0.76))
        spacing: Math.max(5, Math.min(8, ambient.height * 0.007))

        Text {
            width: parent.width
            text: ambient.lyricLine(ambient.currentLyric - 1)
            visible: text.length > 0
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Qt.alpha(Theme.washInk, 0.55)
            font.family: Theme.font
            font.pixelSize: ambient.compact
                ? Math.max(15, Math.min(18, ambient.width * 0.026))
                : Math.max(16, Math.min(20, ambient.width * 0.014))
            font.weight: Font.Normal
            lineHeight: 1.18
        }

        Text {
            id: activeLyric
            width: parent.width
            text: ambient.lyricLine(ambient.currentLyric)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.primary
            font.family: Theme.displayFont
            font.pixelSize: ambient.compact
                ? Math.max(24, Math.min(34, ambient.width * 0.050))
                : Math.max(28, Math.min(48, ambient.width * 0.030))
            font.weight: Font.Medium
            lineHeight: 1.04
        }
    }

    MouseArea {
        anchors.fill: parent
        z: 10
        enabled: ambient.presentationActive
        onClicked: ambient.closed()
    }
    Shortcut {
        sequence: "Esc"
        enabled: ambient.presentationActive
        onActivated: ambient.closed()
    }
}
