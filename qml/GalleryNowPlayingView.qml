import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// NP.01 "Gallery Monolith" — locked Now Playing winner (Iann, 2026-08-01).
// The sleeve and its instruments travel as one composition; the lyric room
// has no backing panel, decorative divider, header rule, or current-line mark.
FocusScope {
    id: view

    signal toggleQueue()
    signal toggleMini()
    signal openRadio()
    signal exitRadioRequested()
    signal saveRadioRequested()
    property bool radioRoom: false
    signal openAlbum(string path, string album)
    signal openArtist(string name, string path)

    property bool active: false
    property bool suspended: false
    property bool windowGeometryChanging: false
    property bool lyricsOpen: false

    // BARE — "just the record" (Iann, 2026-08-02). Every instrument leaves and
    // the sleeve expands to fill the window. Main owns this state; the page
    // only ever REQUESTS a change so the rail button and the in-page
    // affordances cannot drift apart.
    property bool bare: false
    signal bareRequested(bool on)

    // The right half is a panel region shared by the lyric ledger and the
    // queue. Either alone takes the whole region; together they split it.
    property bool queueOpen: false
    readonly property int panelCount: (lyricsOpen ? 1 : 0) + (queueOpen ? 1 : 0)
    readonly property bool panelsOpen: panelCount > 0

    property var story: null
    property var chaps: []
    property int lyricCursor: -1
    property bool lyricAutoFollow: true
    property int lastVol: 60
    property var shuffleContext: ({ kind: "queue", label: "CURRENT QUEUE" })

    // Travel time for the composition. 700ms read as sluggish once the page
    // became something you toggle constantly (Iann, 2026-08-02).
    // Panel travel remains expressive; native window resizing must not inherit
    // the same 300ms chase after the compositor has already moved the window.
    readonly property int motionDuration:
        Theme.pageAnim && !windowGeometryChanging ? 300 : 0

    // The panels are MUTUALLY EXCLUSIVE — selecting one replaces the other, so
    // there is no split state and no third layout (Iann, 2026-08-02). That is
    // what settles the controls: toggling lyrics <-> queue moves nothing,
    // because both use the same panel composition.
    readonly property bool split: false
    // Rest keeps its own composition — centred sleeve over a full-width deck
    // (Iann's correction, same day: "The resting screen should be the one we
    // already had. I only wanted you to apply the new changes to the
    // lyrics/queue screen"). The narrow left-column deck belongs to the panel
    // screens alone.
    readonly property bool narrowDeck: panelsOpen

    // ONE CLOCK FOR THE DECK (Iann, 2026-08-02: "a fluid single animation …
    // not start → position → endpoint"). Previously the deck animated its own
    // width while its children animated toward fractions OF that width — each
    // child chased a target that was itself still moving, so every element
    // settled twice. Now a single scalar travels 0 → 1 and every deck
    // measurement is a straight interpolation of it: one curve, one arrival.
    // One clock for the whole deck: a single scalar travels 0 -> 1 and every
    // deck measurement interpolates off it, so the composition arrives once
    // instead of each element chasing a target that is itself still moving.
    property real narrowT: narrowDeck ? 1 : 0
    Behavior on narrowT {
        NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic }
    }
    function mix(rest, narrow) { return rest + (narrow - rest) * narrowT }

    // Same idea for controls that LEAVE the transport row: a button popping
    // out of a RowLayout reflows every sibling in one frame, which reads as a
    // second phase. They collapse their width on this clock instead.
    property real panelT: panelsOpen ? 1 : 0
    Behavior on panelT {
        NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic }
    }

    // Targets, never the in-flight values — anything OUTSIDE the deck (the
    // sleeve, the panel columns) must aim at where the deck is going, or it
    // inherits the same chase.
    // At medium window widths the wide caption geometry no longer has enough
    // side-room beside the centred sleeve for both identity and waveform. Give
    // the resting deck a second row instead of compressing the song title into
    // the waveform's lane. Panel geometry remains the approved narrow deck.
    readonly property bool mediumDeck: width < 1460
    readonly property int restDeckHeight: mediumDeck ? 228 : 170
    readonly property int deckHeight: narrowDeck ? 190 : restDeckHeight
    readonly property real deckTopY: height - deckHeight
                                     - (narrowDeck ? height * 0.025
                                                   : height * 0.04)

    readonly property real artTopY: Math.max(76, height * 0.045)
    readonly property real artRoom: Math.max(0, deckTopY - artTopY - 32)
    readonly property real panelArtRoom:
        Math.max(0, height - 190 - height * 0.025 - artTopY - 32)
    // Shallow supported windows must preserve the sleeve/deck gap before they
    // preserve a preferred exhibition size. 112px remains a useful visual
    // identity at the 720×480 floor without crossing the transport deck.
    readonly property real minimumContainedArtSide: 112
    readonly property real panelArtSide:
        Math.max(minimumContainedArtSide,
                 Math.min(panelArtRoom, width * 0.435))
    readonly property real artSide: bare
                                    ? Math.min(width, height)
                                    : narrowDeck ? panelArtSide
                                    : Math.max(minimumContainedArtSide, Math.min(
                                                artRoom,
                                                split ? width * 0.33
                                                      : width * 0.66))

    // The panel region. One panel takes the right half; two share a wider
    // region as equal columns.
    readonly property real regionX: (split ? 0.415 : 0.55) * width
    readonly property real regionW: (split ? 0.550 : 0.415) * width
    readonly property real colGap: 24
    readonly property real colW: split ? (regionW - colGap) / 2 : regionW
    readonly property real regionY: Math.max(76, height * 0.07)
    // side by side, the columns stop clear of the full-width deck below them
    readonly property real regionH: Math.max(0, (split ? deckTopY - 18
                                                       : height - height * 0.06)
                                                - regionY)
    readonly property real queueX: split ? regionX + colW + colGap : regionX

    // REST TRANSPORT (Iann, 2026-08-02): the primary controls sit centred under
    // the artwork, the utility cluster stays right, and the buttons grow. The
    // panel state keeps the composition he approved, so every number below is
    // a mix(rest, panel) pair whose panel side is unchanged.
    readonly property real btnW: mix(46, 38)
    readonly property real playW: mix(58, 50)
    // A compact panel leaves 0.435w for transport. Keep the core five controls
    // at their real hit-target sizes instead of letting RowLayout compress Play
    // underneath its neighbours; Like/Dislike remain in the resting player and
    // return as soon as the panel column has enough room.
    readonly property bool compactPanelTransport:
        panelsOpen ? width < 780 : width < 900
    // Preserve the generous keyboard/pointer target and the play-centred row
    // geometry, but keep the visible disc closer to its neighbouring glyphs.
    // The previous disc filled the whole 58/50px target and protruded from the
    // otherwise quiet Needle row (Iann correction, 2026-08-02).
    readonly property real playDiscW: mix(50, 46)
    readonly property real btnGlyph: mix(20, 16)
    // Iann wants PLAY itself on the record's axis, not the cluster centred.
    // Rest and panel use different deck/art widths, so each endpoint gets an
    // explicit lead and narrowT carries the player between them on one clock.
    // In panel mode the deck and sleeve share x = 0.035w; transport begins
    // 18px inside the deck.
    readonly property real restBeforePlay:
        Theme.heartsOn && !compactPanelTransport ? 46 * 3 + 8 : 46 * 2 + 6
    readonly property real panelBeforePlay:
        compactPanelTransport ? 44 + 38 + 4
                              : Theme.heartsOn ? 38 * 2 + 44 + 8
                                               : 44 + 38 + 6
    readonly property real restTransportLead:
        Math.max(0, width * 0.45 - restBeforePlay - 58 / 2)
    readonly property real panelTransportLead:
        Math.max(0, panelArtSide / 2 - 18 - panelBeforePlay - 50 / 2)
    readonly property real transportLead:
        mix(restTransportLead, panelTransportLead)

    // One vertical axis for every transport control. The panel deck sits 10px
    // lower at the reference height than the resting deck; keeping utilities
    // on the resting line left Lyrics / Queue / Volume visibly above Play.
    // The horizontal utility anchor remains window-owned, while this center
    // follows the deck's one animation clock so the full control family lands
    // together in both compositions (Iann, 2026-08-02).
    readonly property real transportCenterY:
        height - mix(height * 0.04, height * 0.025) - mix(2, 7) - 25
    readonly property real queueBottomInset:
        Math.max(0, regionY + regionH
                    - (transportCenterY - 25 - 8))

    // Title scale and vertical ownership are part of one responsive contract.
    // Medium rooms previously kept the desktop 48px title inside an 82px
    // identity box; its line box then occupied the metadata lane beneath it.
    // Cap that state one step lower and reserve enough identity height for a
    // full title line, metadata, and breathing room before the waveform.
    readonly property real restTitleSize:
        mediumDeck ? Math.max(34, Math.min(42, width * 0.034))
                   : Math.max(34, Math.min(48, width * 0.040))
    readonly property real titleSize: mix(restTitleSize, 34)
    readonly property int restIdentityHeight: mediumDeck ? 94 : 98
    readonly property real identityHeight: mix(restIdentityHeight, 76)
    readonly property real titleMetadataGap:
        mix(mediumDeck ? 4 : 2, 0)
    readonly property real restWaveY: mediumDeck ? 106 : 8
    readonly property int nextCount: backend.queueRemainingCount
    readonly property string currentFile: backend.currentSong.file || ""
    readonly property string currentAlbumPath: currentFile.indexOf("/") >= 0
        ? currentFile.substring(0, currentFile.lastIndexOf("/")) : currentFile
    readonly property string currentArtistPath: currentFile
        ? backend.artistPath(currentFile, backend.currentSong.artist || "") : ""

    function refreshStory() {
        var file = backend.currentSong.file || ""
        story = file !== "" ? backend.songStory(file) : null
        chaps = file !== "" ? backend.trackChapters(file) : []
    }

    function toggleMute() {
        if (backend.volume > 0) {
            lastVol = backend.volume
            backend.requestVolume(0)
        } else {
            backend.requestVolume(lastVol > 0 ? lastVol : 50)
        }
    }

    function playQueueRow(row) {
        if (radioRoom) backend.playBeaconPosition(row.pos)
        else backend.playPosition(row.pos)
    }

    function setLyrics(open) {
        if (radioRoom && !open) { setQueue(true); return }
        lyricsOpen = open
        if (open) {
            queueOpen = false          // one panel at a time — they replace
            lyricAutoFollow = true
            recomputeLyrics()
            if (radioRoom) Qt.callLater(function() {
                if (view.lyricCursor >= 0) lyricList.positionViewAtIndex(view.lyricCursor, ListView.Center)
            })
            forceActiveFocus()
        }
    }

    function setQueue(open) {
        if (radioRoom && !open) return
        queueOpen = open
        if (open) lyricsOpen = false   // one panel at a time — they replace
    }

    function closePanels() {
        if (radioRoom) { setQueue(true); return }
        if (queueOpen) queueOpen = false
        else if (lyricsOpen) setLyrics(false)
        else if (bare) bareRequested(false)
    }

    function recomputeLyrics() {
        var lines = backend.lyrics
        if (!backend.lyricsSynced || lines.length === 0) {
            lyricCursor = -1
            return
        }
        var elapsed = backend.elapsed + 0.3
        var cursor = -1
        for (var i = 0; i < lines.length; ++i) {
            if (lines[i].t <= elapsed) cursor = i
            else break
        }
        if (cursor !== lyricCursor) {
            lyricCursor = cursor
            if (lyricAutoFollow && cursor >= 0)
                lyricList.currentIndex = cursor
        }
    }

    onActiveChanged: {
        if (!active) {
            lyricsOpen = false
            queueOpen = false
            bareRequested(false)
        } else {
            refreshStory()
            // Lyrics can already be open when the page becomes active (state
            // restoration and verification both exercise this path). Do not
            // wait for a later MPD status tick to establish the active line.
            if (lyricsOpen) recomputeLyrics()
        }
    }

    Connections {
        target: backend
        function onSongChanged() {
            view.lyricCursor = -1
            view.lyricAutoFollow = true
            if (view.active) view.refreshStory()
        }
        function onStatusChanged() {
            if (view.active && view.lyricsOpen) view.recomputeLyrics()
        }
        function onLyricsChanged() {
            view.lyricCursor = -1
            view.lyricAutoFollow = true
            if (backend.lyrics.length > 0)
                lyricList.positionViewAtIndex(0, ListView.Beginning)
            view.recomputeLyrics()
        }
        function onWaveformChanged() {
            if (view.active && view.chaps.length === 0)
                view.chaps = backend.trackChapters(backend.currentSong.file || "")
        }
    }

    // No gradient and no spectrum field here (Iann, 2026-08-02): the page
    // paints nothing of its own so the app-wide Archive Wash — the playing
    // record itself, thinned to veil 0.60 by Main — IS this room. The old
    // ribbon-and-spark VisualizerField was removed as visual noise; the
    // waveform seek line remains the only moving instrument.

    // Protected top band: the moving sleeve never crosses AMPERE.
    Item {
        id: sleeve
        z: 2
        width: view.artSide
        height: width
        // Placement is derived from artSide — the TARGET size — never from the
        // sleeve's own animating width, which would make x chase width and
        // land in two stages.
        x: view.bare ? (view.width - view.artSide) / 2
           : view.narrowDeck ? view.width * 0.035
           : view.split ? view.width * 0.05
                        : (view.width - view.artSide) / 2
        y: view.bare
           ? (view.height - view.artSide) / 2
           : view.artTopY + Math.max(0, (view.artRoom - view.artSide) / 2)

        Behavior on x {
            NumberAnimation {
                duration: view.motionDuration
                easing.type: Easing.OutCubic
            }
        }
        Behavior on y {
            NumberAnimation {
                duration: view.motionDuration
                easing.type: Easing.OutCubic
            }
        }
        Behavior on width {
            NumberAnimation {
                duration: view.motionDuration
                easing.type: Easing.OutCubic
            }
        }

        // The exhibition object decodes from the native embedded picture, not
        // the 512px thumbnail path — at this size the thumb was visibly
        // softer than the room behind it (Iann, 2026-08-02).
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
            // the framing hairline belongs to the exhibition object, not to a
            // record that has become the whole window
            border.color: Qt.alpha(Theme.washInk, view.bare ? 0 : 0.10)
            Behavior on border.color { ColorAnimation { duration: view.motionDuration } }
        }
    }

    // The floating top-right cluster is gone (Iann, 2026-08-02): nothing
    // hovers over the record any more. Ambient and mini moved into the deck's
    // right-hand utility group; fullscreen was dropped outright because F11
    // toggles it and Esc leaves it, everywhere in the app.

    // The way OUT of bare mode. Entering it is the rail's visible button next
    // to search; leaving it needs an affordance that survives after every
    // other surface has gone, so this strip stays hover-revealed.
    Item {
        id: bareZone
        z: 40
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: 300
        height: 62
        visible: view.bare

        HoverHandler { id: bareHover }

        GlowButton {
            anchors.centerIn: parent
            icon: "close"
            glyphSize: 15
            tip: "Show the player again (Esc)"
            opacity: bareHover.hovered ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            onClicked: view.bareRequested(false)
        }
    }

    Item {
        id: deck
        z: 7
        opacity: view.bare ? 0 : 1
        visible: opacity > 0
        enabled: !view.bare
        Behavior on opacity {
            NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic }
        }
        // no Behaviors below this line — narrowT is the only thing animating
        x: view.mix(view.width * 0.05, view.width * 0.035)
        y: view.height - height
           - view.mix(view.height * 0.04, view.height * 0.025)
        width: view.mix(view.width * 0.90, view.width * 0.435)
        height: view.mix(view.restDeckHeight, 190)

        Item {
            id: identity
            x: view.mix(0, 18)
            y: view.mix(view.mediumDeck ? 4 : 8, 14)
            // Wide rooms keep the original side-by-side caption. Medium rooms
            // give identity a useful measure and place the waveform on the
            // next row, so neither element is forced through the other.
            width: view.mix(view.mediumDeck
                            ? deck.width * 0.62
                            : Math.max(180,
                                       (deck.width - view.artSide) / 2 - 24),
                            deck.width * 0.56)
            height: view.identityHeight

            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                text: "NOW PLAYING"
                      + (backend.queuePos >= 0
                         ? " / TRACK " + (backend.queuePos + 1) : "")
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: 10
                font.letterSpacing: 2.8
                elide: Text.ElideRight
            }
            Item {
                id: titleSlot
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 18
                anchors.bottom: metadata.top
                anchors.bottomMargin: view.titleMetadataGap
                clip: true
                enabled: view.currentAlbumPath !== ""
                activeFocusOnTab: enabled
                Accessible.role: Accessible.Button
                Accessible.name: "Open album " + (backend.currentSong.album || "")
                Accessible.onPressAction: view.openAlbum(
                    view.currentAlbumPath, backend.currentSong.album || "")
                Text {
                    readonly property real fittedPixelSize:
                        Math.max(1, Math.floor(Math.min(
                            view.titleSize, titleSlot.height / 1.16)))
                    anchors.fill: parent
                    verticalAlignment: Text.AlignVCenter
                    text: backend.currentSong.title || "—"
                    color: titleSlot.activeFocus || titleHover.hovered ? Theme.primary : Theme.text
                    font.family: Theme.font
                    // The slot, not the title string, owns the final bound.
                    // This keeps the same one-line hierarchy while making it
                    // mathematically impossible for glyphs to enter metadata.
                    font.pixelSize: fittedPixelSize
                    font.weight: Font.Light
                    font.letterSpacing: -(fittedPixelSize * 0.045)
                    elide: Text.ElideRight
                }
                HoverHandler { id: titleHover; enabled: view.currentAlbumPath !== ""; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: view.currentAlbumPath !== ""; onTapped: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "") }
                Keys.onReturnPressed: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "")
                Keys.onSpacePressed: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "")
            }
            Row {
                id: metadata
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 22
                spacing: 8
                Text {
                    id: artistLink
                    width: Math.min(implicitWidth, identity.width * 0.42)
                    text: backend.currentSong.artist || ""
                    color: artistLink.activeFocus || artistHover.hovered ? Theme.primary : Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                    font.weight: Font.Light
                    elide: Text.ElideRight
                    enabled: view.currentArtistPath !== ""
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open artist " + (backend.currentSong.artist || "")
                    Accessible.onPressAction: view.openArtist(
                        backend.currentSong.artist || "", view.currentArtistPath)
                    HoverHandler { id: artistHover; enabled: view.currentArtistPath !== ""; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: view.currentArtistPath !== ""; onTapped: view.openArtist(backend.currentSong.artist || "", view.currentArtistPath) }
                    Keys.onReturnPressed: view.openArtist(backend.currentSong.artist || "", view.currentArtistPath)
                    Keys.onSpacePressed: view.openArtist(backend.currentSong.artist || "", view.currentArtistPath)
                }
                Text { visible: !!backend.currentSong.album; text: "/"; color: Theme.washFaint; font.family: Theme.font; font.pixelSize: Theme.fsBody }
                Text {
                    id: albumLink
                    width: Math.min(implicitWidth, identity.width * 0.42)
                    text: backend.currentSong.album || ""
                    color: albumLink.activeFocus || albumHover.hovered ? Theme.primary : Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                    font.weight: Font.Light
                    elide: Text.ElideRight
                    enabled: view.currentAlbumPath !== ""
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open album " + (backend.currentSong.album || "")
                    Accessible.onPressAction: view.openAlbum(
                        view.currentAlbumPath, backend.currentSong.album || "")
                    HoverHandler { id: albumHover; enabled: view.currentAlbumPath !== ""; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: view.currentAlbumPath !== ""; onTapped: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "") }
                    Keys.onReturnPressed: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "")
                    Keys.onSpacePressed: view.openAlbum(view.currentAlbumPath, backend.currentSong.album || "")
                }
                Text { visible: !!backend.currentSong.year; text: "· " + (backend.currentSong.year || ""); color: Theme.textDim; font.family: Theme.font; font.pixelSize: Theme.fsBody }
            }
        }

        Column {
            id: ledger
            x: view.mix(view.mediumDeck ? deck.width * 0.66 : 0,
                        deck.width * 0.62)
            y: view.mix(view.mediumDeck ? 26
                                        : deck.height - height - 8,
                        22)
            width: deck.width * view.mix(view.mediumDeck ? 0.34 : 0.31,
                                         0.35)
            spacing: 2

            Text {
                width: parent.width
                horizontalAlignment: view.mediumDeck || view.narrowT > 0.5
                                     ? Text.AlignRight : Text.AlignLeft
                text: backend.audioInfo
                      + (backend.liveKbps > 0 && backend.state === "play"
                         ? " · " + backend.liveKbps + " kbps live" : "")
                color: Theme.textDim
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                horizontalAlignment: view.mediumDeck || view.narrowT > 0.5
                                     ? Text.AlignRight : Text.AlignLeft
                text: {
                    var value = view.story
                    if (!value || (value.plays === 0 && value.firstHeard === 0))
                        return ""
                    var parts = []
                    if (value.firstHeard > 0)
                        parts.push("first heard "
                                   + new Date(value.firstHeard * 1000)
                                     .toLocaleDateString(Qt.locale(), "MMM d"))
                    if (value.plays > 0)
                        parts.push(value.plays
                                   + (value.plays === 1 ? " play" : " plays"))
                    if (value.rankMonth > 0 && value.rankMonth <= 20)
                        parts.push("#" + value.rankMonth + " this month")
                    if (value.hourWord !== "")
                        parts.push("usually " + value.hourWord + " song")
                    return parts.join(" · ")
                }
                color: Theme.textMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
            }
        }

        RowLayout {
            id: waveLine
            x: view.mix(view.mediumDeck
                        ? 0 : (deck.width - view.artSide) / 2,
                        18)
            y: view.mix(view.restWaveY, 87)
            width: view.mix(view.mediumDeck ? deck.width : view.artSide,
                            deck.width - 36)
            height: 52
            spacing: 10

            Text {
                Layout.preferredWidth: 38
                horizontalAlignment: Text.AlignRight
                text: Theme.fmtTime(backend.elapsed)
                color: Theme.textMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }
            WaveSeek {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                chapters: view.chaps
                resizeActive: view.windowGeometryChanging
            }
            Text {
                Layout.preferredWidth: 38
                text: Theme.fmtTime(backend.duration)
                color: Theme.textMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }
        }

        RowLayout {
            id: transport
            objectName: "galleryTransport"
            x: view.mix(0, 18)
            y: deck.height - height - view.mix(2, 7)
            width: view.mix(deck.width, deck.width - 36)
            height: 50
            spacing: 2

            // Leading gap that puts PLAY itself on the sleeve's centerline in
            // both compositions; it travels on narrowT with the rest of deck.
            Item {
                Layout.preferredWidth: view.transportLead
                Layout.preferredHeight: 1
                // a zero-width item still contributes the row's spacing, which
                // would shift the panel composition by 2px — hide it instead
                visible: Layout.preferredWidth > 0.5
            }
            GlowButton {
                objectName: "galleryLikeControl"
                visible: Theme.heartsOn && !view.compactPanelTransport
                Layout.preferredWidth: view.btnW
                Layout.preferredHeight: view.btnW
                // the outlined heart carries less visual mass than its
                // neighbours at the same nominal size — Iann, 2026-08-02
                glyphSize: view.btnGlyph + 4
                heartIcon: true
                active: backend.likedFiles.indexOf(backend.currentSong.file || "") >= 0
                tip: active ? "Remove from Liked" : "Add to Liked"
                onClicked: backend.toggleLike(backend.currentSong.file || "")
            }
            ShuffleControl {
                Layout.preferredWidth: 44
                Layout.preferredHeight: 44
                glyphSize: view.btnGlyph
                shuffleContext: view.shuffleContext
            }
            GlowButton {
                objectName: "galleryPreviousControl"
                Layout.preferredWidth: view.btnW
                Layout.preferredHeight: view.btnW
                glyphSize: view.btnGlyph + 2
                icon: "prev"; tip: "Previous"; onClicked: backend.requestPrevious()
            }
            Item {
                objectName: "galleryPlayControl"
                Layout.preferredWidth: view.playW
                Layout.preferredHeight: view.playW
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: backend.state === "play" ? "Pause" : "Play"
                Accessible.onPressAction: backend.requestPlayPause()
                scale: playTap.pressed ? 0.955 : 1
                Behavior on scale { NumberAnimation { duration: 65; easing.type: Easing.OutCubic } }
                Rectangle {
                    anchors.centerIn: parent
                    width: view.playDiscW
                    height: view.playDiscW
                    radius: width / 2
                    color: playHover.hovered ? Theme.text : Theme.primary
                    border.width: parent.activeFocus ? 2 : 0
                    border.color: Theme.focusRing
                }
                Icon {
                    anchors.centerIn: parent
                    name: backend.state === "play" ? "pause" : "play"
                    size: view.btnGlyph + 4
                    color: Theme.inkOnPrimary
                }
                HoverHandler { id: playHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { id: playTap; onTapped: backend.requestPlayPause() }
                Keys.onReturnPressed: backend.requestPlayPause()
                Keys.onSpacePressed: backend.requestPlayPause()
            }
            GlowButton {
                objectName: "galleryNextControl"
                Layout.preferredWidth: view.btnW
                Layout.preferredHeight: view.btnW
                glyphSize: view.btnGlyph + 2
                icon: "next"; tip: "Next"; onClicked: backend.requestNext()
            }
            GlowButton {
                objectName: "galleryLoopControl"
                Layout.preferredWidth: view.btnW
                Layout.preferredHeight: view.btnW
                glyphSize: view.btnGlyph
                icon: "loop"
                active: backend.repeat
                badgeText: backend.repeat && backend.single ? "1" : ""
                tip: !backend.repeat ? "Loop off"
                     : backend.single ? "Repeat current song"
                     : "Loop current queue"
                onClicked: backend.requestCycleRepeat()
            }
            // Dislike closes the cluster opposite the heart (Iann, 2026-08-02),
            // so the six controls sit three either side of play.
            GlowButton {
                objectName: "galleryDislikeControl"
                visible: Theme.heartsOn && !view.compactPanelTransport
                Layout.preferredWidth: view.btnW
                Layout.preferredHeight: view.btnW
                glyphSize: view.btnGlyph + 2
                dislikeIcon: true
                active: backend.dislikedFiles.indexOf(backend.currentSong.file || "") >= 0
                tip: active
                     ? "Disliked — benched from shuffles, radio and mixes"
                     : "Dislike — bench this from shuffles, radio and mixes"
                onClicked: backend.toggleDislike(backend.currentSong.file || "")
            }
            // Lyrics, queue and volume are NOT in this row — they live in the
            // `utilities` group below, anchored to the window rather than the
            // deck, so opening a panel cannot drag them sideways.
            //
            // This trailing spacer is load-bearing: without something that can
            // grow, RowLayout hands the leftover width to the BUTTONS and the
            // cluster smears across the deck. It must absorb the slack so the
            // cluster keeps its measured width and stays centred on play.
            Item { Layout.fillWidth: true; Layout.preferredHeight: 1 }
        }
    }

    // These three used to ride the deck, so narrowing it for a panel pulled
    // them across the screen. Iann, 2026-08-02: "the lyrics, queue & volume
    // button should stay where they are and not move." They are now anchored
    // to the window's right edge, while their vertical center follows the
    // transport's shared axis. Opening a panel never shifts them sideways.
    Row {
        id: utilities
        z: 8
        spacing: 2
        height: 50
        x: view.width - width - view.width * 0.05
        y: view.transportCenterY - height / 2
        opacity: view.bare ? 0 : 1
        visible: opacity > 0
        enabled: !view.bare
        Behavior on opacity {
            NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic }
        }

        GlowButton {
            objectName: "galleryRadioControl"
            width: 46
            height: 46
            anchors.verticalCenter: parent.verticalCenter
            glyphSize: 20
            icon: "beacon"
            tip: "Start Song Radio"
            enabled: view.currentFile !== ""
            opacity: enabled ? 1 : 0.35
            onClicked: if (enabled) {
                backend.startBeaconRadio()
                view.openRadio()
            }
        }
        GlowButton {
            width: 46
            height: 46
            anchors.verticalCenter: parent.verticalCenter
            objectName: "galleryLyricsControl"
            glyphSize: 20
            icon: "note"
            active: view.lyricsOpen
            tip: view.lyricsOpen ? "Close lyrics" : "Lyrics"
            onClicked: view.setLyrics(!view.lyricsOpen)
        }
        GlowButton {
            width: 46
            height: 46
            anchors.verticalCenter: parent.verticalCenter
            objectName: "galleryQueueControl"
            glyphSize: 20
            icon: "list"
            active: view.queueOpen
            tip: view.queueOpen ? "Close up next" : "Up next"
            onClicked: view.setQueue(!view.queueOpen)
        }
        GlowButton {
            width: 46
            height: 46
            anchors.verticalCenter: parent.verticalCenter
            glyphSize: 20
            volumeIcon: true
            volumeMuted: backend.volume <= 0
            tip: "Volume " + backend.volume
            onClicked: view.toggleMute()
        }
        AmpereSlider {
            visible: view.width >= 1080
            width: 68
            anchors.verticalCenter: parent.verticalCenter
            from: 0
            to: 100
            value: backend.volume
            accent: Theme.primary
            Accessible.name: "Volume"
            onMoved: backend.requestVolume(value)
        }
    }

    Item {
        id: lyricRoom
        z: 10
        x: view.regionX + (view.lyricsOpen ? 0 : 56)
        y: view.regionY
        width: view.colW
        height: view.regionH
        opacity: view.lyricsOpen && !view.bare ? 1 : 0
        visible: opacity > 0
        enabled: view.lyricsOpen && !view.bare

        Behavior on x { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on height { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on opacity {
            NumberAnimation { duration: Theme.pageAnim ? 220 : 0; easing.type: Easing.OutCubic }
        }

        Item {
            id: lyricHead
            anchors.left: parent.left
            anchors.right: parent.right
            height: view.radioRoom ? lyricRadioHeader.height : 76

            RadioQueueHeader {
                id: lyricRadioHeader
                objectName: "lyricRadioHeader"
                width: parent.width
                visible: view.radioRoom
                lyrics: true
                count: view.nextCount
                onExitRequested: view.exitRadioRequested()
                onSaveRequested: view.saveRadioRequested()
            }

            Text {
                visible: !view.radioRoom
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.topMargin: 4
                width: lyricRoom.width * 0.78
                text: (backend.currentSong.title || "LYRICS").toUpperCase()
                color: Theme.text
                font.family: Theme.font
                font.pixelSize: 28
                font.weight: Font.Light
                font.letterSpacing: 2.2
                elide: Text.ElideRight
            }
            // The artist / "Synced embedded lyrics" caption was cut here
            // (Iann, 2026-08-02): the artist is already in the deck below and
            // the lyric source is plumbing, not something the room should say.
            GlowButton {
                id: closeLyrics
                visible: !view.radioRoom
                anchors.top: parent.top
                anchors.right: parent.right
                icon: "close"
                tip: "Close lyrics"
                onClicked: view.setLyrics(false)
            }
        }

        Timer {
            id: resumeLyricFollow
            objectName: "galleryResumeLyricFollow"
            interval: 4000
            onTriggered: {
                view.lyricAutoFollow = true
                if (view.lyricCursor >= 0) {
                    lyricList.currentIndex = view.lyricCursor
                    if (view.radioRoom) lyricList.positionViewAtIndex(view.lyricCursor, ListView.Center)
                }
            }
        }

        ListView {
            id: lyricList
            objectName: "galleryLyricList"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: lyricHead.bottom
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 24
            clip: true
            model: backend.lyrics
            spacing: 0
            highlightRangeMode: ListView.ApplyRange
            preferredHighlightBegin: height * 0.20
            preferredHighlightEnd: height * 0.30
            highlightMoveDuration: view.motionDuration
            highlightMoveVelocity: -1
            highlightFollowsCurrentItem: true
            footer: Item { width: 1; height: lyricList.height * 0.30 }
            onDragStarted: {
                view.lyricAutoFollow = false
                resumeLyricFollow.restart()
            }
            onFlickStarted: {
                view.lyricAutoFollow = false
                resumeLyricFollow.restart()
            }

            delegate: Text {
                id: lyricLine
                required property var modelData
                required property int index
                onActiveFocusChanged: if (activeFocus && view.radioRoom) {
                    view.lyricAutoFollow = false
                    resumeLyricFollow.restart()
                    lyricList.positionViewAtIndex(index, ListView.Contain)
                }
                readonly property bool activeLine:
                    backend.lyricsSynced && index === view.lyricCursor
                width: lyricList.width
                height: modelData.line === ""
                        ? 24 : Math.max(activeLine ? 58 : 43, implicitHeight)
                text: modelData.line === "" ? " " : modelData.line
                enabled: modelData.t >= 0
                activeFocusOnTab: enabled
                Accessible.ignored: !enabled
                Accessible.role: Accessible.Button
                Accessible.name: "Seek to lyric " + (modelData.line || "line")
                Accessible.onPressAction: if (lyricLine.enabled)
                    backend.requestSeek(modelData.t)
                // Theme.primary is the album's vivid extracted color lifted
                // into a readable band against the current Archive Wash room.
                color: activeFocus || activeLine ? Theme.primary : Theme.textDim
                font.family: Theme.font
                font.pixelSize: activeLine ? 31 : 25
                font.weight: activeLine ? Font.Normal : Font.Light
                font.letterSpacing: -0.3
                wrapMode: Text.Wrap
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.42
                Behavior on color {
                    ColorAnimation { duration: Theme.pageAnim ? 180 : 0 }
                }
                Behavior on font.pixelSize {
                    NumberAnimation {
                        duration: Theme.pageAnim ? 180 : 0
                        easing.type: Easing.OutCubic
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: modelData.t >= 0
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: backend.requestSeek(modelData.t)
                }
                Keys.onReturnPressed: if (enabled) backend.requestSeek(modelData.t)
                Keys.onSpacePressed: if (enabled) backend.requestSeek(modelData.t)
            }
        }

        Column {
            anchors.centerIn: lyricList
            spacing: 8
            visible: backend.lyrics.length === 0
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "note"
                size: 36
                color: Qt.alpha(Theme.outline, 0.9)
            }
            Text {
                text: "No lyrics embedded in this file"
                color: Theme.textDim
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
            }
        }

    }

    // ---- Up next, rendered in the page (Iann, 2026-08-02) ----
    // The queue shares the right region with the ledger instead of sliding a
    // drawer over the room. Same voice as the lyric side: no backing panel,
    // no divider — spacing carries the structure.
    Item {
        id: queueRoom
        z: 10
        x: view.queueX + (view.queueOpen ? 0 : 56)
        y: view.regionY
        width: view.colW
        height: view.regionH
        opacity: view.queueOpen && !view.bare ? 1 : 0
        visible: opacity > 0
        enabled: view.queueOpen && !view.bare

        Behavior on x { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on height { NumberAnimation { duration: view.motionDuration; easing.type: Easing.OutCubic } }
        Behavior on opacity {
            NumberAnimation { duration: Theme.pageAnim ? 220 : 0; easing.type: Easing.OutCubic }
        }

        // DJ bridges are invisible by law (rendered mixes "just happen"), and
        // every row keeps its REAL queue position — never the visual index.
        readonly property var rows: view.queueOpen ? backend.queue.filter(function (song) {
            return !(song.file && song.file.charAt(0) === "/")
        }) : []
        readonly property int playPos: backend.visibleQueuePlayPos

        // A queue of hundreds is useless opened at row 1 — land on what is
        // playing, both when the panel opens and when the song moves on.
        function showPlaying() {
            for (var i = 0; i < rows.length; ++i) {
                if (rows[i].pos === queueRoom.playPos) {
                    queueList.positionViewAtIndex(i, ListView.Beginning)
                    return
                }
            }
        }
        onVisibleChanged: if (visible) Qt.callLater(showPlaying)
        Connections {
            target: backend
            function onSongChanged() {
                if (queueRoom.visible) Qt.callLater(queueRoom.showPlaying)
            }
        }

        Item {
            id: queueHead
            anchors.left: parent.left
            anchors.right: parent.right
            height: view.radioRoom ? queueRadioHeader.height : 52

            RadioQueueHeader {
                id: queueRadioHeader
                objectName: "queueRadioHeader"
                width: parent.width
                visible: view.radioRoom
                count: view.nextCount
                onExitRequested: view.exitRadioRequested()
                onSaveRequested: view.saveRadioRequested()
            }

            Text {
                visible: !view.radioRoom
                anchors.left: parent.left
                anchors.top: parent.top
                text: "UP NEXT / " + view.nextCount
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: 10
                font.letterSpacing: 2.2
            }
            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.topMargin: 20
                width: parent.width - closeQueue.width - 20
                visible: !view.radioRoom
                text: backend.djOn ? "DJ SET"
                      : backend.smartMixOn ? "AUTO-MIX" : "QUEUE"
                color: Theme.text
                font.family: Theme.font
                font.pixelSize: 22
                font.weight: Font.Light
                font.letterSpacing: 2.2
                elide: Text.ElideRight
            }
            GlowButton {
                id: closeQueue
                visible: !view.radioRoom
                anchors.top: parent.top
                anchors.right: parent.right
                icon: "close"
                tip: "Close up next"
                onClicked: view.setQueue(false)
            }
        }

        ListView {
            id: queueList
            objectName: "galleryQueueList"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: queueHead.bottom
            anchors.topMargin: 6
            anchors.bottom: parent.bottom
            anchors.bottomMargin: view.queueBottomInset
            clip: true
            model: queueRoom.rows
            spacing: 0
            currentIndex: -1
            ScrollBar.vertical: ArchiveScrollBar {}

            delegate: Item {
                id: queueTrack
                required property var modelData
                required property int index
                readonly property bool playing: modelData.pos === queueRoom.playPos
                width: queueList.width
                height: 58
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Play " + (modelData.title || "Unknown title")
                    + " by " + (modelData.artist || "Unknown artist")
                Accessible.onPressAction: view.playQueueRow(modelData)
                onActiveFocusChanged: if (activeFocus && view.radioRoom)
                    queueList.positionViewAtIndex(index, ListView.Contain)

                Rectangle {
                    anchors.fill: parent
                    anchors.rightMargin: 4
                    color: queueTrack.activeFocus
                        ? Qt.alpha(Theme.primary, 0.08)
                        : rowHover.hovered ? Qt.alpha(Theme.text, 0.055)
                                           : "transparent"
                    radius: Theme.radiusSm
                    border.width: queueTrack.activeFocus ? 1 : 0
                    border.color: Theme.primary
                }

                // The playing row is marked by an edge stroke rather than a
                // glyph, so nothing sits on top of the artwork.
                Rectangle {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 3
                    height: parent.height - 14
                    radius: 1.5
                    color: playing ? Theme.primary : "transparent"
                }
                MediaArtwork {
                    id: rowArt
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 40
                    height: 40
                    kind: "album"
                    source: modelData.file
                            ? "image://art/" + encodeURIComponent(modelData.file)
                            : ""
                    opacity: playing ? 1 : 0.88
                }
                Column {
                    anchors.left: rowArt.right
                    anchors.leftMargin: 12
                    anchors.right: rowTime.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        width: parent.width
                        text: modelData.title || "—"
                        color: playing ? Theme.primary : Theme.text
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                        font.weight: Font.Light
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: (modelData.artist || "")
                              + (modelData.album ? "  /  " + modelData.album : "")
                        color: Theme.textMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        elide: Text.ElideRight
                    }
                }
                Text {
                    id: rowTime
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: Theme.fmtTime(Number(modelData.duration || 0))
                    color: Theme.textSubtle
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }

                HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.playQueueRow(modelData) }
                Keys.onReturnPressed: view.playQueueRow(modelData)
                Keys.onSpacePressed: view.playQueueRow(modelData)
            }
        }

        Column {
            anchors.centerIn: queueList
            spacing: 8
            visible: queueRoom.rows.length === 0
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: "list"
                size: 36
                color: Qt.alpha(Theme.outline, 0.9)
            }
            Text {
                text: "Nothing queued"
                color: Theme.textDim
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
            }
        }
    }
}
