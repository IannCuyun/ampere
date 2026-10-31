import QtQuick
import "."

// Genre identity is a metadata-defined world expressed through two distinct
// album sleeves. The component never infers genre from a path or owns routing;
// it emits one activation request for its Library-local owner.
Item {
    id: card

    signal openRequested(string name)

    property var genre: ({})
    property bool dominant: false
    property bool compact: false
    property bool interactive: true
    property bool showCopy: true
    readonly property var covers: genre.covers || []
    readonly property bool hasSecondCover: covers.length > 1
    readonly property bool actionable: interactive
                                       && String(genre.name || "") !== ""
    activeFocusOnTab: actionable
    Accessible.role: Accessible.Button
    Accessible.name: genre.name || "Unknown genre"
    Accessible.description: "Open this genre's albums and songs"
    Accessible.onPressAction: card.trigger()
    Keys.onReturnPressed: card.trigger()
    Keys.onSpacePressed: card.trigger()

    function trigger() {
        if (actionable)
            openRequested(String(genre.name))
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.planeRaised
    }

    Item {
        id: mosaic
        anchors.fill: parent
        clip: true

        MediaArtwork {
            id: firstCover
            objectName: card.objectName + "Cover_0"
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: card.hasSecondCover ? Math.ceil(parent.width / 2)
                                       : parent.width
            kind: "album"
            source: card.covers.length
                    ? "image://art/" + encodeURIComponent(card.covers[0]) : ""
        }

        MediaArtwork {
            id: secondCover
            objectName: card.objectName + "Cover_1"
            visible: card.hasSecondCover
            anchors.left: firstCover.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            kind: "album"
            source: card.hasSecondCover
                    ? "image://art/" + encodeURIComponent(card.covers[1]) : ""
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.18; color: Qt.alpha(Theme.bgLow, 0.04) }
                GradientStop { position: 0.62; color: Qt.alpha(Theme.bgLow, 0.56) }
                GradientStop { position: 1.0; color: Qt.alpha(Theme.bgLow, 0.96) }
            }
        }

        Column {
            visible: card.showCopy
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: card.dominant
                             ? (card.compact ? 16 : 24)
                             : (card.compact ? 12 : 16)
            spacing: card.dominant ? 7 : 5

            Text {
                visible: card.dominant
                text: "EMBEDDED GENRE"
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.4
            }

            Text {
                width: parent.width
                text: card.genre.name || "Unknown genre"
                color: Theme.washInk
                elide: Text.ElideRight
                font.family: Theme.font
                font.pixelSize: card.dominant
                                ? (card.compact ? Theme.fsTitle : Theme.fsStat)
                                : (card.compact ? Theme.fsSmall : Theme.washBody)
                font.weight: Font.Light
            }

            Text {
                width: parent.width
                text: Number(card.genre.albums || 0) + " album"
                      + (Number(card.genre.albums || 0) === 1 ? "" : "s")
                      + " · " + Number(card.genre.artists || 0) + " artist"
                      + (Number(card.genre.artists || 0) === 1 ? "" : "s")
                color: Theme.washMuted
                elide: Text.ElideRight
                font.family: Theme.displayFont
                font.pixelSize: card.compact ? Theme.fsMicro : Theme.washSub
                font.letterSpacing: 0.6
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: cardTap.pressed ? Qt.alpha(Theme.washInk, 0.10)
                              : cardHover.hovered
                              ? Qt.alpha(Theme.washInk, 0.05) : "transparent"
        border.width: 1
        border.color: card.activeFocus ? Theme.focusRing : Theme.washHair
    }

    HoverHandler {
        id: cardHover
        enabled: card.actionable
        cursorShape: Qt.PointingHandCursor
    }
    TapHandler {
        id: cardTap
        enabled: card.actionable
        onTapped: card.trigger()
    }
}
