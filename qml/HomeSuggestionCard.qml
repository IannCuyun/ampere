import QtQuick
import "."

// A cover is the control. Home uses this primitive for both the dominant
// current record and Discover's visual choices; labels stay inside the art
// instead of rebuilding the former document-card grammar around it.
Item {
    id: card

    property var entry: ({})
    property string kind: "album"
    property string eyebrow: ""
    property string title: kind === "artist"
        ? (entry.name || "Your artists")
        : (entry.album || entry.title || "Your archive")
    property string subtitle: entry.albumartist || entry.artist || ""
    property string actionLabel: "OPEN"
    property bool dominant: false
    property bool fullResolution: false
    property bool showSubtitle: true
    property bool showAction: true
    signal chosen(var entry)

    readonly property string artKey: kind === "artist"
        ? (entry.cover || entry.path || "") : (entry.file || entry.cover || "")
    // Caption contrast is intentionally independent from both the pictured
    // cover and Theme's current (different-record) album palette.
    readonly property color captionInk: "#f7f3ec"
    readonly property color captionMuted: "#d8d1c7"

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: actionLabel + " " + title
    Accessible.onPressAction: card.activate()

    function activate() {
        card.chosen(card.entry)
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.planeRaised
        clip: true

        MediaArtwork {
            anchors.fill: parent
            kind: card.kind
            decodeSize: card.fullResolution ? 1024 : 0
            source: card.artKey
                ? "image://art/" + (card.fullResolution ? "full:" : "")
                    + encodeURIComponent(card.artKey)
                : ""
        }

        Rectangle {
            id: captionMatte
            objectName: "coverCaptionMatte"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            // The long, near-transparent upper trail keeps this from reading
            // as a horizontal band. Opacity only becomes assertive where the
            // caption begins, so the art stays open while text stays stable.
            height: Math.min(parent.height * 0.88,
                captionContent.height + (card.dominant ? 152 : 112))
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.10; color: Qt.rgba(0.035, 0.031, 0.027, 0.015) }
                GradientStop { position: 0.20; color: Qt.rgba(0.035, 0.031, 0.027, 0.05) }
                GradientStop { position: 0.30; color: Qt.rgba(0.035, 0.031, 0.027, 0.12) }
                GradientStop { position: 0.38; color: Qt.rgba(0.035, 0.031, 0.027, 0.24) }
                GradientStop { position: 0.44; color: Qt.rgba(0.035, 0.031, 0.027, 0.42) }
                GradientStop { position: 0.50; color: Qt.rgba(0.035, 0.031, 0.027, 0.70) }
                GradientStop { position: 0.60; color: Qt.rgba(0.035, 0.031, 0.027, 0.84) }
                GradientStop { position: 0.72; color: Qt.rgba(0.035, 0.031, 0.027, 0.90) }
                GradientStop { position: 0.86; color: Qt.rgba(0.035, 0.031, 0.027, 0.94) }
                GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.031, 0.027, 0.96) }
            }
        }

        Column {
            id: captionContent
            objectName: "coverCaptionContent"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: card.dominant ? 22 : 16
            spacing: card.dominant ? 5 : 3

            Text {
                width: parent.width
                text: card.eyebrow
                color: card.captionMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.2
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: card.title
                color: card.captionInk
                font.family: Theme.font
                font.pixelSize: card.dominant ? 33 : 24
                font.weight: Font.Light
                lineHeight: 0.94
                maximumLineCount: 2
                wrapMode: Text.Wrap
                elide: Text.ElideRight
            }
            Text {
                visible: card.showSubtitle && text !== ""
                width: parent.width
                text: card.subtitle
                color: card.captionMuted
                font.family: Theme.font
                font.pixelSize: card.dominant ? 13 : 11
                elide: Text.ElideRight
            }
            Text {
                visible: card.showAction
                topPadding: card.dominant ? 5 : 3
                text: card.actionLabel + "  →"
                color: card.captionInk
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 1.8
            }
        }

        Rectangle {
            anchors.fill: parent
            color: cardTap.pressed ? Qt.alpha(Theme.primary, 0.10) : "transparent"
            border.width: card.activeFocus ? 2 : 0
            border.color: Theme.focusRing
        }
    }

    HoverHandler { id: cardHover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: cardTap; onTapped: card.activate() }
    Keys.onReturnPressed: card.activate()
    Keys.onEnterPressed: card.activate()
    Keys.onSpacePressed: card.activate()
}
