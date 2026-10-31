pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Portrait Measure: exact sorted order, grouped into repeating one-dominant /
// four-support tableaux. Odd measures mirror without reordering records.
Item {
    id: wall

    property var artists: []
    property bool compact: false
    property var portraitFor: function(_name) { return "" }
    property int currentIndex: -1
    readonly property int measureSize: 5
    readonly property int measureCount: Math.ceil(artists.length / measureSize)
    readonly property int cols: compact ? 2 : 3
    property alias contentY: measureList.contentY
    readonly property real originY: measureList.originY
    property real previousContentY: 0
    property int scrollDirection: 0

    signal openArtist(string name, string path)
    signal portraitPriority(var visibleNames, var nearbyNames)

    function namesForMeasure(measureIndex) {
        var names = []
        if (measureIndex < 0 || measureIndex >= measureCount)
            return names
        var first = measureIndex * measureSize
        var last = Math.min(artists.length, first + measureSize)
        for (var index = first; index < last; ++index) {
            var name = String((artists[index] || {}).name || "").trim()
            if (name)
                names.push(name)
        }
        return names
    }

    function appendMeasure(target, seen, measureIndex) {
        var names = namesForMeasure(measureIndex)
        for (var index = 0; index < names.length; ++index) {
            if (!seen[names[index]]) {
                seen[names[index]] = true
                target.push(names[index])
            }
        }
    }

    function reportPortraitPriority(anchorIndex) {
        if (!visible || measureCount <= 0)
            return
        var pitch = (compact ? 250 : Math.max(520, height))
                    + (compact ? 16 : 28)
        var firstMeasure
        var lastMeasure
        if (anchorIndex !== undefined && anchorIndex >= 0) {
            firstMeasure = Math.floor(anchorIndex / measureSize)
            lastMeasure = firstMeasure
        } else {
            var offset = Math.max(0, measureList.contentY - measureList.originY)
            firstMeasure = Math.max(0, Math.floor(offset / pitch))
            lastMeasure = Math.min(
                measureCount - 1,
                Math.floor((offset + Math.max(1, measureList.height) - 1)
                           / pitch))
        }
        var visibleNames = []
        var nearbyNames = []
        var seen = ({})
        for (var measure = firstMeasure; measure <= lastMeasure; ++measure)
            appendMeasure(visibleNames, seen, measure)

        var nearbyMeasures
        if (scrollDirection < 0)
            nearbyMeasures = [firstMeasure - 1, firstMeasure - 2,
                              lastMeasure + 1]
        else
            nearbyMeasures = [lastMeasure + 1, lastMeasure + 2,
                              firstMeasure - 1]
        for (var nearby = 0; nearby < nearbyMeasures.length; ++nearby)
            appendMeasure(nearbyNames, seen, nearbyMeasures[nearby])
        portraitPriority(visibleNames, nearbyNames)
    }

    onArtistsChanged: Qt.callLater(reportPortraitPriority)
    onVisibleChanged: if (visible) Qt.callLater(reportPortraitPriority)
    onHeightChanged: portraitPriorityTimer.restart()
    onWidthChanged: portraitPriorityTimer.restart()
    Component.onCompleted: {
        previousContentY = measureList.contentY
        Qt.callLater(reportPortraitPriority)
    }

    function jumpToGlobalIndex(index) {
        currentIndex = index
        scrollDirection = 0
        reportPortraitPriority(index)
        measureList.positionViewAtIndex(
            Math.floor(Math.max(0, index) / measureSize), ListView.Beginning)
    }

    Timer {
        id: portraitPriorityTimer
        interval: 50
        repeat: false
        onTriggered: wall.reportPortraitPriority()
    }

    function revealBeginning() {
        currentIndex = -1
        Qt.callLater(function() {
            if (measureList.visible)
                measureList.positionViewAtBeginning()
        })
    }

    ListView {
        id: measureList
        objectName: "libraryArtistMeasureList"
        anchors.fill: parent
        clip: true
        model: wall.measureCount
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: wall.compact ? 16 : 28
        ScrollBar.vertical: ArchiveScrollBar {}

        onModelChanged: wall.revealBeginning()
        onContentYChanged: {
            var delta = contentY - wall.previousContentY
            if (Math.abs(delta) > 0.5)
                wall.scrollDirection = delta > 0 ? 1 : -1
            wall.previousContentY = contentY
            portraitPriorityTimer.restart()
        }
        onMovementEnded: {
            portraitPriorityTimer.stop()
            wall.scrollDirection = 0
            wall.reportPortraitPriority()
        }
        Component.onCompleted: wall.revealBeginning()

        delegate: Item {
            id: measure
            required property int index
            objectName: index === 0 ? "libraryArtistMonolithStage"
                                    : "libraryArtistVariedMeasure_" + index
            width: measureList.width
            height: wall.compact ? 250 : Math.max(520, wall.height)

            readonly property int baseIndex: index * wall.measureSize
            readonly property int visibleCount: Math.min(
                wall.measureSize, Math.max(0, wall.artists.length - baseIndex))
            readonly property bool mirrored: index % 2 === 1
            readonly property real gap: wall.compact ? 10 : 18
            readonly property real heroWidth: Math.floor(
                width * (wall.compact ? 0.53 : 0.52))
            readonly property real supportWidth: Math.max(
                0, width - heroWidth - gap)
            readonly property real contentHeight: height - 24
            readonly property real supportGap: wall.compact ? 8 : 14
            readonly property real supportCellWidth: Math.floor(
                (supportWidth - supportGap) / 2)
            readonly property real supportCellHeight: Math.floor(
                (contentHeight - supportGap) / 2)

            function artistAt(localIndex) {
                return wall.artists[baseIndex + localIndex] || ({})
            }

            Repeater {
                model: measure.visibleCount
                delegate: ArtistPortraitCard {
                    id: card
                    required property int index
                    readonly property int globalIndex: measure.baseIndex + index
                    readonly property var entry: measure.artistAt(index)
                    readonly property bool hero: index === 0
                    objectName: hero && measure.index === 0
                                ? "libraryArtistHero"
                                : index === 1 && measure.index === 0
                                  ? "libraryArtistSupport_0"
                                  : "libraryArtistCard_" + globalIndex
                    x: hero
                       ? (measure.mirrored
                          ? measure.width - measure.heroWidth : 0)
                       : (measure.mirrored ? 0
                          : measure.heroWidth + measure.gap)
                         + ((index - 1) % 2)
                           * (measure.supportCellWidth + measure.supportGap)
                    y: hero ? 0
                       : Math.floor((index - 1) / 2)
                         * (measure.supportCellHeight + measure.supportGap)
                    width: hero ? measure.heroWidth : measure.supportCellWidth
                    height: hero ? measure.contentHeight
                                 : measure.supportCellHeight
                    artist: entry
                    portraitSource: wall.portraitFor(entry.name || "")
                    dominant: hero
                    compact: wall.compact
                    showCounts: hero || !wall.compact
                    onOpenRequested: (name, path) => wall.openArtist(name, path)
                    onActiveFocusChanged: {
                        if (activeFocus) wall.currentIndex = globalIndex
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
