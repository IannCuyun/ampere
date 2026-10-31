import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as QQC
import "."

// Signal Deck — purpose-built three-zone playback instrument.
Rectangle {
    id: deck
    objectName: "playerDeck"
    color: "transparent"
    signal openFolder(string path)
    signal openArtist(string name, string path)
    signal openAlbum(string path, string album)
    signal openLyrics()
    signal openNow()
    signal toggleQueue()
    signal toggleMini()
    signal saveMix()
    property bool queueOpen: false
    property bool miniOn: false
    property int lastVol: 60
    property var shuffleContext: ({ kind: "queue", label: "CURRENT QUEUE" })
    // Keep the deck's compact control vocabulary aligned with the Now Playing
    // hero breakpoint so medium windows never leave a half-collapsed toolbar.
    readonly property bool compact: width < 900
    readonly property bool generous: width >= 1180
    readonly property string currentFile: backend.currentSong.file || ""
    readonly property string currentAlbumPath: currentFile.indexOf("/") >= 0
        ? currentFile.substring(0, currentFile.lastIndexOf("/")) : currentFile

    function toggleMute() {
        if (backend.volume > 0) { lastVol = backend.volume; backend.requestVolume(0) }
        else backend.requestVolume(lastVol > 0 ? lastVol : 50)
    }

    Rectangle {
        id: progress
        objectName: "playerSeekRail"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 15
        color: "transparent"
        readonly property real fraction: backend.duration > 0 ? Math.max(0, Math.min(1, backend.elapsed / backend.duration)) : 0
        property real previewFraction: fraction
        readonly property real shownFraction: seekArea.pressed ? previewFraction : fraction
        readonly property real targetFraction: seekArea.pressed
            ? previewFraction
            : seekArea.containsMouse
                ? Math.max(0, Math.min(1,
                    seekArea.mouseX / Math.max(1, seekArea.width)))
                : shownFraction
        activeFocusOnTab: backend.duration > 0
        Accessible.role: Accessible.Slider
        Accessible.name: "Playback position"
        Accessible.description: Theme.fmtTime(backend.elapsed) + " of "
            + Theme.fmtTime(backend.duration)
        function seekBy(seconds) {
            backend.requestSeek(Math.max(0, Math.min(
                backend.duration, backend.elapsed + seconds)))
        }
        Accessible.onDecreaseAction: seekBy(-5)
        Accessible.onIncreaseAction: seekBy(5)
        Keys.onLeftPressed: seekBy(-5)
        Keys.onRightPressed: seekBy(5)
        Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: seekArea.containsMouse ? 3 : 2; color: Qt.alpha(Theme.washInk, 0.22) }
        Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; width: parent.width * progress.shownFraction; height: seekArea.containsMouse ? 4 : 3; color: Theme.primary }
        Rectangle {
            objectName: "playerSeekHandle"
            x: Math.max(0, Math.min(parent.width - width, parent.width * progress.shownFraction - width / 2))
            anchors.verticalCenter: parent.verticalCenter
            width: seekArea.containsMouse || seekArea.pressed ? 12 : 9
            height: width
            radius: width / 2
            color: Theme.primary
            border.width: 1
            border.color: Qt.alpha(Theme.washInk, 0.72)
            Behavior on width { NumberAnimation { duration: 90 } }
        }
        Rectangle {
            objectName: "playerSeekTarget"
            z: 3
            visible: seekArea.containsMouse || seekArea.pressed
                || progress.activeFocus
            x: Math.max(0, Math.min(parent.width - width,
                parent.width * progress.targetFraction - width / 2))
            y: -4
            width: 1.5
            height: parent.height + 8
            color: Theme.washInk

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                width: 7
                height: 7
                rotation: 45
                color: Theme.washInk
            }
        }
        Rectangle {
            objectName: "playerSeekPreview"
            z: 4
            visible: seekArea.containsMouse || seekArea.pressed
                || progress.activeFocus
            x: Math.max(0, Math.min(parent.width - width,
                parent.width * progress.targetFraction - width / 2))
            y: -30
            width: seekPreviewText.implicitWidth + 18
            height: 24
            color: Qt.alpha(Theme.navSurface, 0.98)
            border.width: 1
            border.color: Theme.divider

            Text {
                id: seekPreviewText
                anchors.centerIn: parent
                text: "SEEK · " + Theme.fmtTime(
                    progress.targetFraction * backend.duration)
                color: Theme.washInk
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.weight: Font.DemiBold
                font.letterSpacing: 1
            }
        }
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: progress.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        MouseArea {
            id: seekArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function capture(x) { progress.previewFraction=Math.max(0,Math.min(1,x/width)) }
            onPressed: m => capture(m.x)
            onPositionChanged: m => { if (pressed) capture(m.x) }
            onReleased: backend.requestSeek(progress.previewFraction * backend.duration)
        }
    }

    MouseArea {
        anchors.fill: parent
        anchors.topMargin: 15
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: deck.openNow()
    }

    Item {
        id: playerFrame
        anchors.fill: parent
        anchors.topMargin: 15
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        readonly property real clusterHalfWidth: deck.compact ? 125 : 176
        readonly property real sideGap: deck.compact ? 8 : 18
        readonly property real safeSideWidth: Math.max(
            0, width / 2 - clusterHalfWidth - sideGap)

        // ZONE 1 / identity
        RowLayout {
            objectName: "playerIdentityZone"
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(
                deck.generous ? 360 : 280, playerFrame.safeSideWidth)
            height: deck.compact ? 46 : 58
            spacing: 12
            Item {
                Layout.preferredWidth: deck.compact ? 46 : 58
                Layout.preferredHeight: Layout.preferredWidth
                MediaArtwork {
                    anchors.fill: parent
                    kind: "album"
                    source: backend.currentSong.file ? "image://art/" + encodeURIComponent(backend.currentSong.file) : ""
                }
                Rectangle { anchors.left: parent.left; anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.primary }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Item {
                    id: albumLink
                    Layout.fillWidth: true; Layout.preferredHeight: 21
                    enabled: deck.currentAlbumPath !== ""
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open album " + (backend.currentSong.album || "")
                    Accessible.onPressAction: deck.openAlbum(
                        deck.currentAlbumPath, backend.currentSong.album || "")
                    Marquee { anchors.fill: parent; text: backend.currentSong.title || "Nothing playing"; color: albumLink.activeFocus || titleHover.hovered ? Theme.primary : Theme.text; pixelSize: Theme.fsBody; weight: Font.DemiBold }
                    HoverHandler { id: titleHover; enabled: deck.currentAlbumPath !== ""; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: deck.currentAlbumPath !== ""; onTapped: deck.openAlbum(deck.currentAlbumPath, backend.currentSong.album || "") }
                    Keys.onReturnPressed: deck.openAlbum(deck.currentAlbumPath, backend.currentSong.album || "")
                    Keys.onSpacePressed: deck.openAlbum(deck.currentAlbumPath, backend.currentSong.album || "")
                }
                Item {
                    id: artistLink
                    Layout.fillWidth: true; Layout.preferredHeight: 18
                    enabled: deck.currentFile !== ""
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open artist " + (backend.currentSong.artist || "")
                    function activate() {
                        var name = backend.currentSong.artist || ""
                        var path = backend.artistPath(deck.currentFile, name)
                        if (name && path !== "") deck.openArtist(name, path)
                    }
                    Accessible.onPressAction: activate()
                    Marquee { anchors.fill: parent; text: backend.currentSong.artist || "Choose something from your archive"; color: artistLink.activeFocus || artistHover.hovered ? Theme.primary : Theme.textMuted; pixelSize: Theme.fsSmall }
                    HoverHandler { id: artistHover; enabled: deck.currentFile !== ""; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        enabled: deck.currentFile !== ""
                        onTapped: {
                            artistLink.activate()
                        }
                    }
                    Keys.onReturnPressed: activate()
                    Keys.onSpacePressed: activate()
                }
            }
        }

        // ZONE 2 / transport — play/pause owns the application's exact
        // horizontal center. The surrounding controls anchor to it instead of
        // inheriting drift from unequal metadata and utility lanes.
        ColumnLayout {
            objectName: "playerTransportZone"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            width: deck.compact ? 250 : 360
            height: deck.compact ? 46 : 62
            spacing: 2

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 46

                Item {
                    id: playerPlayControl
                    objectName: "playerPlayControl"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.verticalCenter: parent.verticalCenter
                    width: 46
                    height: 46
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: backend.state === "play" ? "Pause" : "Play"
                    Accessible.onPressAction: backend.requestPlayPause()
                    scale: playTap.pressed ? 0.955 : 1
                    Behavior on scale { NumberAnimation { duration: 65; easing.type: Easing.OutCubic } }
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: playHover.hovered ? Theme.text : Theme.primary
                        border.width: parent.activeFocus ? 2 : 0
                        border.color: Theme.focusRing
                    }
                    Icon { anchors.centerIn: parent; name: backend.state === "play" ? "pause" : "play"; size: 19; color: Theme.inkOnPrimary }
                    HoverHandler { id: playHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { id: playTap; onTapped: backend.requestPlayPause() }
                    Keys.onReturnPressed: backend.requestPlayPause()
                    Keys.onSpacePressed: backend.requestPlayPause()
                }

                GlowButton {
                    id: playerPreviousControl
                    objectName: "playerPreviousControl"
                    anchors.right: playerPlayControl.left
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    icon: "prev"
                    glyphSize: 18
                    tip: "Previous"
                    onClicked: backend.requestPrevious()
                }
                ShuffleControl {
                    id: playerShuffleControl
                    anchors.right: playerPreviousControl.left
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    shuffleContext: deck.shuffleContext
                }
                GlowButton {
                    objectName: "playerLikeControl"
                    visible: Theme.heartsOn && !deck.compact
                    anchors.right: playerShuffleControl.left
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    glyphSize: 20
                    heartIcon: true
                    active: backend.likedFiles.indexOf(deck.currentFile) >= 0
                    tip: active
                         ? "Remove Like"
                         : "Like — add this track to Liked"
                    onClicked: backend.toggleLike(deck.currentFile)
                }

                GlowButton {
                    id: playerNextControl
                    objectName: "playerNextControl"
                    anchors.left: playerPlayControl.right
                    anchors.leftMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    icon: "next"
                    glyphSize: 18
                    tip: "Next"
                    onClicked: backend.requestNext()
                }
                GlowButton {
                    id: playerLoopControl
                    objectName: "playerLoopControl"
                    visible: !deck.compact
                    anchors.left: playerNextControl.right
                    anchors.leftMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    icon: "loop"
                    active: backend.repeat
                    badgeText: backend.repeat && backend.single ? "1" : ""
                    tip: !backend.repeat ? "Loop off"
                         : backend.single ? "Repeat current song"
                         : "Loop current queue"
                    onClicked: backend.requestCycleRepeat()
                }
                GlowButton {
                    objectName: "playerDislikeControl"
                    visible: Theme.heartsOn && !deck.compact
                    anchors.left: playerLoopControl.right
                    anchors.leftMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    height: 44
                    glyphSize: 18
                    dislikeIcon: true
                    active: backend.dislikedFiles.indexOf(deck.currentFile) >= 0
                    tip: active
                         ? "Restore — remove this track from Disliked"
                         : "Dislike — bench this from shuffles, radio and mixes"
                    onClicked: backend.toggleDislike(deck.currentFile)
                }
            }
            Text {
                visible: !deck.compact
                Layout.alignment: Qt.AlignHCenter
                text: Theme.fmtTime(backend.elapsed) + "   /   " + Theme.fmtTime(backend.duration)
                color: Theme.textSubtle
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 1
            }
        }

        // ZONE 3 / output + queue
        RowLayout {
            objectName: "playerUtilityZone"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(
                deck.generous ? 340 : 230, playerFrame.safeSideWidth)
            height: deck.compact ? 46 : 58
            spacing: 6
            Item { Layout.fillWidth: true }
            GlowButton { visible: deck.generous && !deck.miniOn; icon: "note"; tip: "Lyrics"; onClicked: deck.openLyrics() }
            GlowButton { icon: "list"; active: deck.queueOpen; tip: "Up next"; onClicked: deck.toggleQueue() }
            GlowButton { visible: deck.generous || deck.miniOn; icon: "mini"; active: deck.miniOn; tip: deck.miniOn ? "Restore window" : "Mini player"; onClicked: deck.toggleMini() }
            GlowButton { volumeIcon: true; volumeMuted: backend.volume <= 0; tip: "Volume " + backend.volume; onClicked: deck.toggleMute() }
            AmpereSlider {
                visible: !deck.compact
                Layout.preferredWidth: deck.generous ? 100 : 72
                from: 0; to: 100
                value: backend.volume
                accent: Theme.primary
                Accessible.name: "Volume"
                onMoved: backend.requestVolume(value)
            }
        }
    }
}
