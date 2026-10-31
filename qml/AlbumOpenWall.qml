pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// B · Open Wall. A virtualized ListView owns deterministic measures, while
// each visible measure realizes only six compact or ten desktop records.
// Sorted order is never changed by the geometry.
Item {
    id: wall

    property var albums: []
    property bool compact: false
    signal openAlbum(string path, string album)

    readonly property int measureSize: compact ? 6 : 10
    readonly property int measureCount: Math.ceil(albums.length / measureSize)
    // Main already clips Library at Pocket Horizon. A desktop measure fills
    // that complete safe field; compact keeps its tighter authored rhythm.
    readonly property real measureFloor: compact ? 0 : height

    ListView {
        id: albumGrid
        objectName: "libraryAlbumGrid"
        anchors.fill: parent
        clip: true
        model: wall.measureCount
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: wall.compact ? 18 : 28
        ScrollBar.vertical: ArchiveScrollBar {}

        readonly property int measureSize: wall.measureSize
        readonly property int measureCount: wall.measureCount
        readonly property int columns: wall.compact ? 3 : 7

        function revealBeginning() {
            Qt.callLater(function() {
                if (albumGrid.visible)
                    albumGrid.positionViewAtBeginning()
            })
        }

        onModelChanged: revealBeginning()
        Component.onCompleted: revealBeginning()

        delegate: Item {
            id: measure
            required property int index
            objectName: "libraryAlbumOpenWallMeasure_" + index
            width: albumGrid.width

            readonly property int baseIndex: index * wall.measureSize
            readonly property int remaining: Math.max(
                0, wall.albums.length - baseIndex)
            readonly property int visibleCount: Math.min(
                wall.measureSize, remaining)
            readonly property bool mirrored: index % 2 === 1
            readonly property real gap: wall.compact ? 12 : 18
            readonly property real unit: Math.max(1, Math.floor(
                (width - gap * (wall.compact ? 2 : 6))
                / (wall.compact ? 3 : 7)))
            readonly property real smallCopy: wall.compact ? 42 : 52
            readonly property real heroCopy: wall.compact ? 50 : 62
            readonly property real smallHeight: unit + smallCopy
            readonly property real heroWidth: wall.compact
                ? unit * 2 + gap : unit * 3 + gap * 2
            readonly property real heroHeight: heroWidth + heroCopy
            readonly property real mediumWidth: unit * 2 + gap
            readonly property real mediumHeight: mediumWidth + smallCopy
            readonly property real compactTopHeight: Math.max(
                heroHeight, smallHeight * 2 + gap)
            readonly property real desktopSupportHeight: smallHeight + gap
                + Math.max(mediumHeight, smallHeight * 2 + gap)
            readonly property real naturalHeight: (wall.compact
                ? compactTopHeight + gap + smallHeight
                : Math.max(heroHeight, desktopSupportHeight)) + 2
            // Desktop measures use the full player-safe room as a gallery
            // score: the support row establishes the top edge, the hero sits
            // at the optical center, and the lower support band resolves at
            // the divider. Compact retains its tighter authored stack.
            readonly property real desktopLowerBandHeight: Math.max(
                mediumHeight, smallHeight * 2 + gap)
            readonly property real desktopHeroY: Math.max(
                0, Math.floor((height - heroHeight - 2) / 2))
            readonly property real desktopLowerBandY: Math.max(
                smallHeight + gap,
                height - desktopLowerBandHeight - 2)
            height: Math.max(naturalHeight, wall.measureFloor)

            function albumAt(localIndex) {
                return wall.albums[baseIndex + localIndex] || ({})
            }

            function isHero(localIndex) {
                return localIndex === 0
            }

            function isMedium(localIndex) {
                return !wall.compact && localIndex === 5
            }

            function cardWidth(localIndex) {
                if (isHero(localIndex)) return heroWidth
                if (isMedium(localIndex)) return mediumWidth
                return unit
            }

            function cardX(localIndex) {
                if (wall.compact) {
                    if (localIndex === 0)
                        return mirrored ? unit + gap : 0
                    if (localIndex <= 2)
                        return mirrored ? 0 : heroWidth + gap
                    return (localIndex - 3) * (unit + gap)
                }

                var supportX = mirrored ? 0 : heroWidth + gap
                if (localIndex === 0)
                    return mirrored ? width - heroWidth : 0
                if (localIndex <= 4)
                    return supportX + (localIndex - 1) * (unit + gap)
                if (localIndex === 5)
                    return supportX
                return supportX + (2 + ((localIndex - 6) % 2))
                    * (unit + gap)
            }

            function cardY(localIndex) {
                if (wall.compact) {
                    if (localIndex === 0) return 0
                    if (localIndex <= 2)
                        return (localIndex - 1) * (smallHeight + gap)
                    return compactTopHeight + gap
                }
                if (localIndex === 0) return desktopHeroY
                if (localIndex <= 4) return 0
                if (localIndex === 5) return desktopLowerBandY
                return desktopLowerBandY
                    + Math.floor((localIndex - 6) / 2)
                    * (smallHeight + gap)
            }

            Repeater {
                model: measure.visibleCount

                delegate: Item {
                    id: albumCard
                    required property int index
                    readonly property int globalIndex: measure.baseIndex + index
                    readonly property var album: measure.albumAt(index)
                    readonly property bool hero: measure.isHero(index)
                    readonly property bool medium: measure.isMedium(index)

                    objectName: hero && measure.index === 0
                        ? "libraryAlbumHero"
                        : index === 1 && measure.index === 0
                          ? "libraryAlbumSupport_0"
                          : "libraryAlbumCell_" + globalIndex
                    x: measure.cardX(index)
                    y: measure.cardY(index)
                    width: measure.cardWidth(index)
                    height: width + (hero ? measure.heroCopy
                                          : measure.smallCopy)
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: (album.album || "Album") + " by "
                                     + (album.artist || "Unknown artist")
                    Accessible.description: "Open album"
                    Accessible.onPressAction: albumCard.activate()
                    Keys.onReturnPressed: albumCard.activate()
                    Keys.onEnterPressed: albumCard.activate()
                    Keys.onSpacePressed: albumCard.activate()

                    function activate() {
                        wall.openAlbum(album.path || "", album.album || "")
                    }

                    Item {
                        anchors.fill: parent
                        y: cardHover.hovered ? -4 : 0
                        Behavior on y {
                            NumberAnimation { duration: Theme.motionFast }
                        }

                        MediaArtwork {
                            id: artwork
                            objectName: albumCard.hero && measure.index === 0
                                ? "libraryAlbumHeroArt"
                                : albumCard.index === 1 && measure.index === 0
                                  ? "libraryAlbumSupportArt_0"
                                  : "libraryAlbumArt_" + albumCard.globalIndex
                            anchors.left: parent.left
                            anchors.top: parent.top
                            width: parent.width
                            height: width
                            kind: "album"
                            source: albumCard.album.cover
                                ? "image://art/" + encodeURIComponent(
                                      albumCard.album.cover) : ""
                        }

                        Text {
                            id: title
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: artwork.bottom
                            anchors.topMargin: albumCard.hero ? 9 : 7
                            text: albumCard.album.album || ""
                            elide: Text.ElideRight
                            color: Theme.washInk
                            font.family: Theme.font
                            font.pixelSize: albumCard.hero
                                ? (wall.compact ? Theme.washBody : Theme.fsTitle)
                                : Theme.washBody
                            font.weight: albumCard.hero ? Font.Light : Font.Normal
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: title.bottom
                            anchors.topMargin: 3
                            text: (albumCard.album.artist || "")
                                + (albumCard.album.year
                                   ? " · " + albumCard.album.year : "")
                            elide: Text.ElideRight
                            color: Theme.washMuted
                            font.family: Theme.font
                            font.pixelSize: Theme.washSub
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: cardTap.pressed
                            ? Qt.alpha(Theme.washInk, 0.07) : "transparent"
                        border.width: albumCard.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                    }
                    HoverHandler {
                        id: cardHover
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler {
                        id: cardTap
                        onTapped: albumCard.activate()
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.washHair
            }
        }
    }
}
