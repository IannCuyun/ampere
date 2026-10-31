import QtQuick
import QtQuick.Window
import "."

// Image-led artist entrance used by Library Monolith. Artist identity comes
// only from Ampere's trust-bounded Wikipedia/Wikimedia portrait cache; a miss
// stays an honest semantic fallback and never becomes an album-cover surrogate.
Item {
    id: card

    property var artist: ({})
    property url portraitSource: ""
    property bool dominant: false
    property bool compact: false
    property bool showCounts: true

    signal openRequested(string name, string path)

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: (artist.name || "Artist") + ", "
                     + Number(artist.albums || 0) + " albums, "
                     + Number(artist.songs || 0) + " songs"
    Accessible.description: "Open artist"
    Accessible.onPressAction: card.openRequested(
        artist.name || "", artist.path || "")
    Keys.onReturnPressed: card.openRequested(
        artist.name || "", artist.path || "")
    Keys.onSpacePressed: card.openRequested(
        artist.name || "", artist.path || "")

    function artistInitials() {
        var words = String(card.artist.name || "").trim().split(/\s+/)
        if (!words.length || !words[0])
            return "A"
        if (words.length === 1)
            return words[0].slice(0, 2).toUpperCase()
        return (words[0].slice(0, 1) + words[words.length - 1].slice(0, 1))
            .toUpperCase()
    }

    Item {
        id: lifted
        anchors.fill: parent
        y: hover.hovered ? -4 : 0
        Behavior on y {
            NumberAnimation { duration: Theme.motionFast }
        }

        Rectangle {
            anchors.fill: parent
            color: Theme.planeRaised
        }

        Image {
            id: portrait
            objectName: card.objectName + "Portrait"
            anchors.fill: parent
            source: card.portraitSource
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            sourceSize: {
                var required = Math.ceil(Math.max(width, height)
                                         * Math.max(1, Screen.devicePixelRatio))
                var side = required <= 512 ? 512
                         : required <= 1024 ? 1024 : 1536
                return Qt.size(side, side)
            }
            visible: status === Image.Ready
        }

        Text {
            id: portraitFallback
            objectName: card.objectName + "Fallback"
            anchors.centerIn: parent
            visible: portrait.status !== Image.Ready
            text: card.artistInitials()
            color: Qt.alpha(Theme.washInk, 0.16)
            font.family: Theme.font
            font.pixelSize: Math.max(44, Math.min(152,
                                                  Math.min(parent.width,
                                                           parent.height)
                                                  * 0.42))
            font.weight: Font.ExtraLight
            font.letterSpacing: 4
        }

        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: portraitFallback.bottom
            anchors.topMargin: 8
            visible: portrait.status !== Image.Ready
            name: "artist"
            size: card.compact ? 18 : 22
            color: Qt.alpha(Theme.washInk, 0.34)
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop {
                    position: 0.28
                    color: Qt.alpha(Theme.bgLow, 0.0)
                }
                GradientStop {
                    position: 0.68
                    color: Qt.alpha(Theme.bgLow, 0.68)
                }
                GradientStop {
                    position: 1.0
                    color: Qt.alpha(Theme.bgLow, 0.96)
                }
            }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: card.dominant
                             ? (card.compact ? 14 : 22)
                             : (card.compact ? 9 : 14)
            spacing: card.showCounts ? 5 : 0

            Text {
                width: parent.width
                text: card.artist.name || ""
                elide: Text.ElideRight
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: card.dominant
                                ? (card.compact ? Theme.fsTitle : Theme.fsStat)
                                : (card.compact ? Theme.fsSmall : Theme.washBody)
                font.weight: Font.Light
            }
            Text {
                visible: card.showCounts
                width: parent.width
                text: Number(card.artist.albums || 0) + " album"
                      + (Number(card.artist.albums || 0) === 1 ? "" : "s")
                      + " · " + Number(card.artist.songs || 0) + " song"
                      + (Number(card.artist.songs || 0) === 1 ? "" : "s")
                elide: Text.ElideRight
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: card.compact ? Theme.fsMicro : Theme.washSub
                font.letterSpacing: 0.7
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: card.activeFocus ? 1 : 0
        border.color: Theme.focusRing
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        onTapped: card.openRequested(card.artist.name || "",
                                     card.artist.path || "")
    }
}
