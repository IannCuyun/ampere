pragma ComponentBehavior: Bound

import QtQuick
import "."

// Discover Inline Playback (design/SPEC.md · Discover · 2026-08-16).
// Home owns the entrance and expansion state. This presentation reads the
// bounded cached projection, lets one lane replace another without side
// effects, and crosses into playback only through the existing exact-album
// asynchronous intent boundary.
Item {
    id: page
    objectName: "discoverView"

    property bool active: false
    property string requestedKey: "loved"
    // Home owns the outer composition breakpoint. Its desktop host is short
    // and horizontal even when that host itself becomes narrower than this
    // reusable view's standalone breakpoint; letting the child independently
    // stack there makes it paint through the following Home sections.
    property bool forceDesktopLayout: false
    property bool forceCompactLayout: false
    property var overview: ({ ready: false, lanes: [] })
    property int selectedIndex: -1

    readonly property bool compact: forceCompactLayout
        || (!forceDesktopLayout && width < 820)
    readonly property var lanes: overview.lanes || []
    readonly property bool ready: overview.ready === true
    readonly property var selectedLane: selectedIndex >= 0
        && selectedIndex < lanes.length ? lanes[selectedIndex] : ({})
    readonly property var entry: selectedLane.entry || ({})
    readonly property bool hasEntry: String(entry.file || "") !== ""
    readonly property string selectedKey: String(selectedLane.key || "")
    readonly property real railHeight: 48
    readonly property real compactCopyHeight: 272
    implicitHeight: compact
        ? railHeight + 18 + width + 24 + compactCopyHeight
        : 320

    function firstAvailableLane(rows) {
        for (var i = 0; i < rows.length; ++i) {
            if (rows[i].entry && rows[i].entry.file)
                return i
        }
        return -1
    }

    function laneIndex(key, requireEntry) {
        for (var i = 0; i < lanes.length; ++i) {
            if (String(lanes[i].key || "") !== String(key || ""))
                continue
            if (!requireEntry || (lanes[i].entry && lanes[i].entry.file))
                return i
        }
        return -1
    }

    function applyPreferredLane(key) {
        var requested = laneIndex(key, true)
        selectedIndex = requested >= 0 ? requested : firstAvailableLane(lanes)
    }

    function loadCachedOverview() {
        var currentKey = selectedKey
        var next = backend.discoverOverview() || ({ ready: false, lanes: [] })
        // A refresh that has not produced verified evidence yet must not erase
        // the last usable recommendation already on screen.
        if (next.ready !== true && ready)
            return
        overview = next
        applyPreferredLane(currentKey || requestedKey)
    }

    function reload() {
        loadCachedOverview()
        backend.requestLibrarySummary()
    }

    function selectLane(index) {
        if (index >= 0 && index < lanes.length && lanes[index].entry
                && lanes[index].entry.file)
            selectedIndex = index
    }

    function playSelection() {
        var files = entry.files || []
        if (files.length)
            backend.playAlbum(files, 0)
    }

    onActiveChanged: if (active) reload()
    onRequestedKeyChanged: if (active && lanes.length)
        applyPreferredLane(requestedKey)

    Connections {
        target: backend
        function onLibrarySummaryChanged() {
            if (page.active)
                page.loadCachedOverview()
        }
    }

    Item {
        id: content
        objectName: "needleStage"
        anchors.fill: parent

        Item {
            id: laneRail
            objectName: "needleLanes"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: page.railHeight

            Repeater {
                model: page.lanes
                delegate: Item {
                    id: lane
                    required property var modelData
                    required property int index
                    objectName: "needleLane" + index
                    x: index * laneRail.width / Math.max(1, page.lanes.length)
                    width: laneRail.width / Math.max(1, page.lanes.length)
                    height: laneRail.height
                    enabled: Boolean(modelData.entry && modelData.entry.file)
                    activeFocusOnTab: enabled
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.shortTitle + ", "
                        + (enabled ? modelData.subtitle
                                   : "nothing ready in this lane")
                    Accessible.onPressAction: page.selectLane(lane.index)

                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 16
                        text: lane.modelData.shortTitle || "DISCOVER"
                        color: !lane.enabled ? Theme.washFaint
                            : (page.selectedIndex === lane.index
                               ? Theme.washInk : Theme.washMuted)
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 1.9
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: page.selectedIndex === lane.index ? 1 : 0
                        color: Theme.primary
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: laneTap.pressed
                            ? Qt.alpha(Theme.primary, 0.10)
                            : (laneHover.hovered ? Theme.hoverSurface : "transparent")
                        border.width: lane.activeFocus ? 1 : 0
                        border.color: Theme.focusRing
                    }
                    HoverHandler {
                        id: laneHover
                        cursorShape: lane.enabled ? Qt.PointingHandCursor
                                                  : Qt.ArrowCursor
                    }
                    TapHandler {
                        id: laneTap
                        enabled: lane.enabled
                        onTapped: page.selectLane(lane.index)
                    }
                    Keys.onReturnPressed: page.selectLane(lane.index)
                    Keys.onEnterPressed: page.selectLane(lane.index)
                    Keys.onSpacePressed: page.selectLane(lane.index)
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.washHair
                z: -1
            }
        }

        Loader {
            id: recommendationStage
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: laneRail.bottom
            anchors.topMargin: 18
            anchors.bottom: parent.bottom
            sourceComponent: page.compact ? compactStage : desktopStage
        }

        Text {
            objectName: "needleLoading"
            anchors.centerIn: recommendationStage
            visible: !page.ready
            text: "READING THE LAST VERIFIED DISCOVERY SIGNAL…"
            color: Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 2.1
            horizontalAlignment: Text.AlignHCenter
        }

        Text {
            objectName: "needleEmpty"
            anchors.centerIn: recommendationStage
            width: Math.min(560, recommendationStage.width * 0.82)
            visible: page.ready && !page.hasEntry
            text: "Nothing is waiting in Forgotten, New, or Unheard yet. Keep listening; Discover will fill itself from the archive."
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsBody
            font.weight: Font.Light
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Component {
        id: desktopStage

        Item {
            MediaArtwork {
                id: desktopArt
                objectName: "needleArtworkDesktop"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(parent.height, parent.width * 0.42)
                height: width
                decodeSize: 1024
                source: page.hasEntry
                    ? "image://art/full:" + encodeURIComponent(page.entry.file)
                    : ""
            }

            Loader {
                anchors.left: desktopArt.right
                anchors.leftMargin: Math.max(30, parent.width * 0.045)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: recommendationCopy
            }
        }
    }

    Component {
        id: compactStage

        Item {
            MediaArtwork {
                id: compactArt
                objectName: "needleArtworkCompact"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: width
                decodeSize: 1024
                source: page.hasEntry
                    ? "image://art/full:" + encodeURIComponent(page.entry.file)
                    : ""
            }

            Loader {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: compactArt.bottom
                anchors.topMargin: 24
                sourceComponent: recommendationCopy
            }
        }
    }

    Component {
        id: recommendationCopy

        Column {
            id: copy
            spacing: 0

            Text {
                width: parent.width
                visible: page.hasEntry
                text: page.selectedLane.eyebrow || "DISCOVER"
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 2.1
                elide: Text.ElideRight
                horizontalAlignment: page.compact ? Text.AlignHCenter
                                                  : Text.AlignLeft
            }
            Text {
                width: parent.width
                topPadding: 8
                visible: page.hasEntry
                text: page.entry.album || page.entry.title || "Untitled"
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: page.compact ? 36 : 42
                font.weight: Font.Light
                font.letterSpacing: -1.5
                maximumLineCount: 2
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                horizontalAlignment: page.compact ? Text.AlignHCenter
                                                  : Text.AlignLeft
            }
            Text {
                width: parent.width
                topPadding: 9
                visible: page.hasEntry
                text: (page.entry.albumartist || page.entry.artist || "Unknown artist")
                    + (page.entry.date ? " · " + page.entry.date : "")
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
                font.weight: Font.Light
                elide: Text.ElideRight
                horizontalAlignment: page.compact ? Text.AlignHCenter
                                                  : Text.AlignLeft
            }
            Text {
                width: parent.width
                topPadding: 15
                visible: page.hasEntry
                text: page.selectedLane.reason || ""
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.weight: Font.Light
                lineHeight: 1.35
                maximumLineCount: 3
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                horizontalAlignment: page.compact ? Text.AlignHCenter
                                                  : Text.AlignLeft
            }

            Item {
                id: playAction
                objectName: "needleAction"
                width: page.compact ? parent.width : 224
                height: 54
                visible: page.hasEntry
                enabled: visible
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Play "
                    + (page.entry.album || page.entry.title || "recommendation")
                Accessible.onPressAction: page.playSelection()

                Row {
                    anchors.centerIn: parent
                    spacing: Theme.spaceSm
                    Text {
                        text: "PLAY THIS RECORD"
                        color: playHover.hovered || playAction.activeFocus
                            ? Theme.primary : Theme.washInk
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsSmall
                        font.weight: Font.DemiBold
                        font.letterSpacing: 2.2
                    }
                    Icon {
                        name: "chevron-right"
                        size: 16
                        color: playHover.hovered || playAction.activeFocus
                            ? Theme.primary : Theme.washMuted
                    }
                }
                Rectangle {
                    anchors.left: page.compact ? undefined : parent.left
                    anchors.horizontalCenter: page.compact
                        ? parent.horizontalCenter : undefined
                    anchors.bottom: parent.bottom
                    width: 178
                    height: 1
                    color: Theme.primary
                }
                Rectangle {
                    anchors.fill: parent
                    color: playTap.pressed
                        ? Qt.alpha(Theme.primary, 0.10) : "transparent"
                    border.width: playAction.activeFocus ? 1 : 0
                    border.color: Theme.focusRing
                }
                HoverHandler {
                    id: playHover
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler { id: playTap; onTapped: page.playSelection() }
                Keys.onReturnPressed: page.playSelection()
                Keys.onEnterPressed: page.playSelection()
                Keys.onSpacePressed: page.playSelection()
            }
        }
    }
}
