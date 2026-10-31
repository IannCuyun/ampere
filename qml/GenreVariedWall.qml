pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Mosaic Measure: one dominant metadata world plus two support worlds in every
// three-record measure. Geometry may mirror; membership order never does.
Item {
    id: wall

    property var genres: []
    property bool compact: false
    readonly property int measureSize: 3
    readonly property int measureCount: Math.ceil(genres.length / measureSize)
    readonly property int cols: 2
    property alias contentY: measureList.contentY
    readonly property real originY: measureList.originY

    signal openGenre(string name)

    function revealBeginning() {
        Qt.callLater(function() {
            if (measureList.visible)
                measureList.positionViewAtBeginning()
        })
    }

    ListView {
        id: measureList
        objectName: "libraryGenreMeasureList"
        anchors.fill: parent
        clip: true
        model: wall.measureCount
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        cacheBuffer: Math.max(height, 720)
        spacing: wall.compact ? 16 : 28
        ScrollBar.vertical: ArchiveScrollBar {}

        onModelChanged: wall.revealBeginning()
        Component.onCompleted: wall.revealBeginning()

        delegate: Item {
            id: measure
            required property int index
            objectName: index === 0 ? "libraryGenreMonolithStage"
                                    : "libraryGenreVariedMeasure_" + index
            width: measureList.width
            height: wall.compact ? 444 : Math.max(520, wall.height)

            readonly property int baseIndex: index * wall.measureSize
            readonly property int visibleCount: Math.min(
                wall.measureSize, Math.max(0, wall.genres.length - baseIndex))
            readonly property bool mirrored: index % 2 === 1
            readonly property real gap: wall.compact ? 10 : 18
            readonly property real heroWidth: wall.compact
                ? width : Math.floor(width * 0.59)
            readonly property real heroHeight: wall.compact
                ? 252 : height - 24
            readonly property real supportWidth: wall.compact
                ? Math.floor((width - gap) / 2)
                : width - heroWidth - gap
            readonly property real supportHeight: wall.compact
                ? 158 : Math.floor((height - 24 - 14) / 2)

            function genreAt(localIndex) {
                return wall.genres[baseIndex + localIndex] || ({})
            }

            Repeater {
                model: measure.visibleCount
                delegate: GenreMosaicCard {
                    id: card
                    required property int index
                    readonly property int globalIndex: measure.baseIndex + index
                    readonly property bool hero: index === 0
                    objectName: hero && measure.index === 0
                                ? "libraryGenreHero"
                                : index === 1 && measure.index === 0
                                  ? "libraryGenreSupport_0"
                                  : "libraryGenreCard_" + globalIndex
                    x: {
                        if (wall.compact)
                            return hero ? 0 : (index - 1)
                                   * (measure.supportWidth + measure.gap)
                        if (hero)
                            return measure.mirrored
                                ? measure.width - measure.heroWidth : 0
                        return measure.mirrored ? 0
                            : measure.heroWidth + measure.gap
                    }
                    y: wall.compact
                       ? (hero ? 0 : measure.heroHeight + measure.gap)
                       : (hero ? 0 : (index - 1)
                          * (measure.supportHeight + 14))
                    width: hero ? measure.heroWidth : measure.supportWidth
                    height: hero ? measure.heroHeight : measure.supportHeight
                    genre: measure.genreAt(index)
                    dominant: hero
                    compact: wall.compact
                    onOpenRequested: name => wall.openGenre(name)
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
