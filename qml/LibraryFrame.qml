import QtQuick
import QtQuick.Layouts
import "."

// The ratified browse-frame skeleton (design/SPEC.md · Browse family;
// mockup: design/mockups/ampere-browse-family/unified-shots/): breadcrumb →
// title/context → line actions → hairline → page content. This frame now
// dresses DETAIL pages only (the folder page); the six-destination rail
// belongs to the Library index, which owns its own (2026-08-22).
Item {
    id: frame
    default property alias bodyData: body.data

    property string breadcrumb: "LIBRARY"
    // Optional artist segment: rendered as a link between breadcrumb and tail.
    property string breadcrumbArtist: ""
    property string breadcrumbTail: ""
    property string title: "Library"
    property string subtitle: ""
    property string currentSection: "albums"
    // actions: [{id, label, accent?}] — accent marks THE one primary action
    property var actions: []
    readonly property bool compact: width < 700

    signal destinationRequested(string section)
    signal artistRequested(string name)
    signal actionRequested(string id)

    ColumnLayout {
        anchors.fill: parent
        // One origin with the shipped Open Shelves page (LibraryView): the
        // browse-frame skeleton is shared, so its gutters must be too, and
        // the breadcrumb must clear the protected AMPERE wordmark band
        // instead of printing across it.
        anchors.leftMargin: frame.compact ? 66 : Theme.pageGutter(frame.width)
        anchors.rightMargin: frame.compact ? 24 : frame.width * 0.08
        anchors.topMargin: frame.compact ? 66 : Theme.pageTop(frame.height)
        anchors.bottomMargin: 16
        spacing: 0

        Row {
            Repeater {
                model: [
                    { text: frame.breadcrumb, link: false },
                    { text: frame.breadcrumbArtist, link: true },
                    { text: frame.breadcrumbTail, link: false }
                ]
                // Only the artist segment is a link, and it was reachable by
                // pointer only (ROADMAP 5.2, 2026-08-22).
                Text {
                    id: crumb
                    required property var modelData
                    readonly property bool link: modelData.link && text !== ""
                    text: modelData.text
                    color: link && (crumbHover.hovered || crumb.activeFocus)
                           ? Theme.washInk : Theme.washMuted
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 2.8
                    font.capitalization: Font.AllUppercase
                    activeFocusOnTab: link
                    Accessible.role: link ? Accessible.Link : Accessible.StaticText
                    Accessible.name: link ? "Open " + text : text
                    Accessible.onPressAction: if (crumb.link)
                        frame.artistRequested(crumb.modelData.text)
                    Keys.onReturnPressed: if (crumb.link)
                        frame.artistRequested(crumb.modelData.text)
                    Keys.onEnterPressed: if (crumb.link)
                        frame.artistRequested(crumb.modelData.text)
                    Keys.onSpacePressed: if (crumb.link)
                        frame.artistRequested(crumb.modelData.text)
                    HoverHandler { id: crumbHover; enabled: crumb.link; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: crumb.link; onTapped: frame.artistRequested(crumb.modelData.text) }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.bottom
                        anchors.topMargin: 2
                        height: 1
                        visible: crumb.activeFocus
                        color: Theme.focusRing
                    }
                }
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: frame.compact
                ? titleColumn.height + actionRow.height + 14
                : Math.max(titleColumn.height, actionRow.height)
            Layout.topMargin: 10
            Column {
                id: titleColumn
                anchors.left: parent.left
                anchors.right: frame.compact ? parent.right : actionRow.left
                anchors.rightMargin: frame.compact ? 0 : 24
                anchors.top: parent.top
                spacing: 7
                Text {
                    width: parent.width
                    text: frame.title
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: frame.compact ? 30 : 40
                    font.weight: Font.Light
                font.letterSpacing: -((frame.compact ? 30 : 40) * 0.03)
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: frame.subtitle !== ""
                    text: frame.subtitle
                    color: Theme.washMuted
                    font.family: Theme.font
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
            }
            Row {
                id: actionRow
                spacing: 26
                anchors.left: frame.compact ? parent.left : undefined
                anchors.right: frame.compact ? undefined : parent.right
                anchors.bottom: parent.bottom
                Repeater {
                    model: frame.actions
                    delegate: WashLine {
                        required property var modelData
                        label: modelData.label
                        primaryAction: modelData.accent === true
                        onActivated: frame.actionRequested(modelData.id)
                    }
                }
            }
        }
        // The six-destination rail belongs to the Library INDEX, not to a
        // page reached from it: a detail surface wearing the index's chrome
        // was the first defect the Album View pass removed, and the Artist
        // page has never had one (2026-08-22).
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 18
            height: 1
            color: Theme.washHair
        }
        Item {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 14
            clip: true
        }
    }
}
