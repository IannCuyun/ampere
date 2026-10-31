import QtQuick
import QtQuick.Controls.Basic
import "."

// Album View — design/SPEC.md · Album view (Iann verdict 2026-08-21, artboard
// `E1 · Split` on https://claude.ai/code/artifact/ea3fb478-adf1-452a-bf18-3e41893e78c5).
//
// The room is Gallery Monolith's, not a new invention: this page publishes its
// roomFile to Main's full-window ArchiveWash, which paints the record itself —
// ambient crop blown up and softened, tone-ceilinged, under ONE flat veil at
// 0.60 with the sharp whole-record layer at 0.0. The full-window owner keeps
// that wash behind the persistent player instead of exposing the playing
// record at the bottom edge. The cover appears exactly twice, once huge and
// soft behind and once sharp as this page's own sleeve. The only difference
// from Now Playing is WHICH record: this page is about the album being looked
// at, not the one playing.
//
// Geometry mirrors GalleryNowPlayingView's lyric-room composition: the sleeve
// sits at width * 0.05 and takes width * 0.435, and the track sequence owns
// the right field exactly where the lyric ledger lives.
//
// Nothing is painted on the artwork. The wash's tone ceiling keeps the room
// below ~0.28 luminance whatever the cover does, so readability never depends
// on the artwork (SPEC's Home caption rule) and no local matte is needed.
Item {
    id: view
    property string albumPath: ""
    property string albumName: ""
    property bool active: false
    property var info: null
    signal destinationRequested(string section)
    signal artistRequested(string name)

    function reload() {
        if (albumPath) info = backend.albumInfo(albumPath, albumName)
    }
    onActiveChanged: if (active) reload()
    onAlbumPathChanged: if (active) reload()
    onAlbumNameChanged: if (active) reload()

    readonly property var tracks: info && info.tracks ? info.tracks : []
    readonly property var files: tracks.map(t => t.file)
    readonly property string albumTitle: (info && info.album) || albumName
                                                || albumPath.split("/").pop()
    readonly property string albumArtist: (info && info.artist) || ""
    readonly property real totalSeconds:
        tracks.reduce((sum, track) => sum + (track.duration || 0), 0)
    readonly property string roomFile: tracks.length ? tracks[0].file : ""

    // Featured credit only: the album already names its artist, so a row
    // repeats nothing (SPEC row 39). An exact prefix match is stripped; a
    // genuinely different credit is shown whole. No fuzzy matching.
    function credit(track) {
        var artist = String((track && track.artist) || "")
        var primary = String(view.albumArtist || "")
        if (!artist || !primary || artist === primary)
            return ""
        var lowered = artist.toLowerCase(), lead = primary.toLowerCase()
        if (lowered.indexOf(lead) === 0) {
            var rest = artist.slice(primary.length)
                             .replace(/^[\s,&/·]*(feat\.?|featuring|with|w\/)?[\s.]*/i, "")
            return rest || ""
        }
        return artist
    }

    // --- Gallery Monolith's own measurements -------------------------------
    readonly property bool compact: width < 900
    readonly property real artTopY: Math.max(76, height * 0.045)
    readonly property real artRoom: Math.max(0, height - artTopY - 32)
    readonly property real artSide: Math.max(
        112, Math.min(artRoom, width * 0.435))
    readonly property real artX: width * 0.05
    readonly property real fieldX: artX + artSide + width * 0.05
    readonly property real fieldWidth: Math.max(0, width - fieldX - 32)
    // Two columns need real measure; below that the sequence is one column.
    readonly property bool twoColumn: !compact && fieldWidth >= 540
                                      && tracks.length > 8
    readonly property int splitAt: Math.ceil(tracks.length / 2)

    ArchiveLoading {
        visible: !backend.libraryReady
        x: view.artX
        y: view.artTopY
        count: backend.libraryTotalSongs
    }

    // ---- the sleeve: one sharp, square, hard-cornered record (SPEC row 42)
    MediaArtwork {
        id: sleeve
        visible: backend.libraryReady && !view.compact
        x: view.artX
        y: view.artTopY + Math.max(0, (view.artRoom - view.artSide) / 2)
        width: view.artSide
        height: view.artSide
        kind: "album"
        source: view.roomFile ? "image://art/" + encodeURIComponent(view.roomFile) : ""
    }

    // ---- identity + sequence own the right field --------------------------
    Item {
        id: field
        visible: backend.libraryReady
        x: view.compact ? 24 : view.fieldX
        y: view.compact ? view.artTopY : view.artTopY - 26
        width: view.compact ? view.width - 48 : view.fieldWidth
        height: view.height - y - 24

        Column {
            id: identity
            x: view.compact ? 112 : 0
            width: parent.width - x
            spacing: 0

            Row {
                spacing: 0
                Text {
                    text: "LIBRARY / "
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2.4
                }
                // The route to the artist was reachable by pointer only
                // (ROADMAP 5.2, 2026-08-22). It is a real navigation link and
                // now announces, focuses and activates like one.
                Text {
                    id: crumbArtist
                    visible: view.albumArtist !== ""
                    text: view.albumArtist.toUpperCase()
                    color: crumbHover.hovered || crumbArtist.activeFocus
                           ? Theme.washInk : Theme.washMuted
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2.4
                    activeFocusOnTab: visible
                    Accessible.role: Accessible.Link
                    Accessible.name: "Open " + view.albumArtist
                    Accessible.onPressAction: view.artistRequested(view.albumArtist)
                    Keys.onReturnPressed: view.artistRequested(view.albumArtist)
                    Keys.onEnterPressed: view.artistRequested(view.albumArtist)
                    Keys.onSpacePressed: view.artistRequested(view.albumArtist)
                    HoverHandler { id: crumbHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: view.artistRequested(view.albumArtist) }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.bottom
                        anchors.topMargin: 2
                        height: 1
                        visible: crumbArtist.activeFocus
                        color: Theme.focusRing
                    }
                }
                Text {
                    text: (view.albumArtist ? " / " : "") + "ALBUM"
                    color: Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 2.4
                }
            }

            Text {
                topPadding: 14
                width: identity.width
                text: view.albumTitle
                color: Theme.washInk
                font.family: Theme.displayFont
                font.pixelSize: view.compact ? 38 : 60
                font.weight: Font.Normal
                lineHeight: 0.98
                elide: Text.ElideRight
                maximumLineCount: 2
                wrapMode: Text.Wrap
            }
            Text {
                topPadding: 9
                width: identity.width
                visible: view.albumArtist !== ""
                text: view.albumArtist
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsEmph
                elide: Text.ElideRight
            }
            Text {
                topPadding: 12
                text: ((view.info && view.info.year) ? view.info.year + "  ·  " : "")
                      + view.tracks.length + (view.tracks.length === 1 ? " TRACK" : " TRACKS")
                      + "  ·  " + Math.round(view.totalSeconds / 60) + " MINUTES"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.4
            }

            // Line actions, not slabs (SPEC row 20: never a pill, slab or glow)
            Row {
                topPadding: 22
                spacing: 28
                WashLine {
                    label: "Play album →"
                    primaryAction: true
                    // A deliberate parent-album action plays the record whole,
                    // dislikes included (SPEC · Player taste controls).
                    onActivated: backend.playAlbum(view.files, 0)
                }
                WashLine {
                    label: "Shuffle"
                    // Shuffle is rotation and therefore always benches dislikes.
                    onActivated: backend.playFilesShuffled(view.files)
                }
                WashLine {
                    label: "Queue"
                    onActivated: backend.queueAlbum(view.files)
                }
            }
        }

        // ---- the complete sequence ---------------------------------------
        Flickable {
            id: sequence
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: identity.bottom
            anchors.topMargin: 26
            anchors.bottom: parent.bottom
            clip: true
            contentHeight: view.twoColumn ? Math.max(columnA.height, columnB.height)
                                          : columnA.height
            contentWidth: width
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ArchiveScrollBar {}

            Column {
                id: columnA
                x: 0
                width: view.twoColumn ? (parent.width - 30) / 2 : parent.width
                Repeater {
                    model: view.twoColumn
                           ? view.tracks.slice(0, view.splitAt) : view.tracks
                    delegate: TrackRow {
                        required property var modelData
                        required property int index
                        width: columnA.width
                        trackData: modelData
                        fileList: view.files
                        rowIndex: index
                        albumMode: true
                        showArtist: false
                        subText: view.credit(modelData)
                    }
                }
            }
            Column {
                id: columnB
                visible: view.twoColumn
                x: (parent.width + 30) / 2
                width: (parent.width - 30) / 2
                Repeater {
                    model: view.twoColumn ? view.tracks.slice(view.splitAt) : []
                    delegate: TrackRow {
                        required property var modelData
                        required property int index
                        width: columnB.width
                        trackData: modelData
                        fileList: view.files
                        rowIndex: view.splitAt + index
                        albumMode: true
                        showArtist: false
                        subText: view.credit(modelData)
                    }
                }
            }
        }
    }

    // Compact keeps the record, then identity, then one sequence — the same
    // recomposition rule every other Ampere room follows.
    MediaArtwork {
        visible: backend.libraryReady && view.compact
        x: 24
        y: view.artTopY
        width: 96
        height: 96
        kind: "album"
        source: view.roomFile ? "image://art/" + encodeURIComponent(view.roomFile) : ""
    }
}
