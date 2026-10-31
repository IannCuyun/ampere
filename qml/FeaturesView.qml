pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "."

// Listening Atlas (design/SPEC.md, Iann verdict A, 2026-09-01).
// This page renders cached presentation evidence and emits navigation intent.
// Main remains the sole route and feature-state owner.
Item {
    id: view

    property bool active: false
    signal openFeature(string mode)

    readonly property bool compact: width < 1080
    property var overview: ({
        ready: false,
        metrics: ({ week: 0, artists: 0 }),
        shelves: ({ history: [], arrivals: [], loved: [], deep: [], unfinished: [] })
    })

    readonly property var shelves: overview.shelves || ({})
    readonly property var recent: shelves.history || []
    readonly property var arrivals: shelves.arrivals || []
    readonly property var loved: shelves.loved || []
    readonly property var deep: shelves.deep || []
    readonly property var unfinished: shelves.unfinished || []
    readonly property var metrics: overview.metrics || ({})
    readonly property var discoverEntry: first(loved.length ? loved
        : (arrivals.length ? arrivals : (deep.length ? deep : recent)))
    readonly property var ampyEntry: first(deep.length ? deep
        : (loved.length ? loved : (arrivals.length ? arrivals : recent)))
    readonly property var currentEntry: backend.currentSong || ({})
    readonly property var memoryEntries: collectMemory()
    readonly property var featureModes: [
        "discover", "rewind", "ampy", "ambient", "eq", "doctor",
        "smart-shuffle", "autoplay", "disliked"
    ]

    function first(rows) {
        return rows && rows.length ? rows[0] : ({});
    }

    function collectMemory() {
        var rows = [];
        var seen = {};
        var groups = [recent, loved, unfinished, arrivals, deep];
        for (var group = 0; group < groups.length && rows.length < 3; ++group) {
            for (var index = 0; index < groups[group].length && rows.length < 3; ++index) {
                var file = String(groups[group][index].file || "");
                if (file && !seen[file]) {
                    seen[file] = true;
                    rows.push(groups[group][index]);
                }
            }
        }
        return rows;
    }

    function loadCachedSummary() {
        if (backend && typeof backend.homeOverview === "function")
            overview = backend.homeOverview();
    }

    function reload() {
        loadCachedSummary();
        if (backend && typeof backend.requestLibrarySummary === "function")
            backend.requestLibrarySummary();
    }

    function activate(mode) {
        if (featureModes.indexOf(mode) >= 0)
            openFeature(mode);
    }

    onActiveChanged: if (active) reload()

    Connections {
        target: backend
        function onLibrarySummaryChanged() {
            if (view.active)
                view.loadCachedSummary();
        }
    }

    component AtlasTile: Item {
        id: tile

        property string tileKey: ""
        property string mode: ""
        property string category: ""
        property string title: ""
        property string description: ""
        property string action: "OPEN"
        property string visual: "icon"
        property string iconName: "note"
        property var entry: ({})
        property var entries: []
        property bool dominant: false
        property string statOne: ""
        property string statOneLabel: ""
        property string statTwo: ""
        property string statTwoLabel: ""

        objectName: "featureTile-" + tileKey
        clip: true
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: title
        Accessible.description: description + ". " + action
        Accessible.onPressAction: view.activate(mode)
        Keys.onReturnPressed: view.activate(mode)
        Keys.onEnterPressed: view.activate(mode)
        Keys.onSpacePressed: view.activate(mode)

        Rectangle {
            anchors.fill: parent
            color: tileTap.pressed
                ? Qt.alpha(Theme.primary, 0.11)
                : (tileHover.hovered ? Theme.hoverSurface
                                     : Qt.alpha(Theme.raisedSurface, 0.18))
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 1
            color: Theme.washHair
        }

        MediaArtwork {
            id: singleArt
            visible: (tile.visual === "art" || tile.visual === "ambient")
                && Boolean(tile.entry.file)
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: tile.dominant ? parent.width * 0.56 : parent.width
            source: visible
                ? "image://art/full:" + encodeURIComponent(tile.entry.file) : ""
            kind: "album"
            decodeSize: tile.dominant ? 768 : 512
            fallbackColor: Qt.alpha(Theme.raisedSurface, 0.38)
        }

        Row {
            id: mosaic
            visible: tile.visual === "mosaic" && tile.entries.length > 0
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: parent.width * 0.53
            spacing: 3

            Repeater {
                model: Math.min(3, tile.entries.length)
                delegate: MediaArtwork {
                    required property int index
                    width: Math.max(0, (mosaic.width - 6) / 3)
                    height: mosaic.height
                    source: tile.entries[index].file
                        ? "image://art/full:"
                          + encodeURIComponent(tile.entries[index].file) : ""
                    kind: "album"
                    decodeSize: 384
                    fallbackColor: Qt.alpha(Theme.raisedSurface, 0.38)
                }
            }
        }

        Rectangle {
            visible: singleArt.visible || mosaic.visible
            anchors.fill: parent
            color: Qt.alpha("#0c0b0a", tile.dominant ? 0.24 : 0.43)
        }

        Rectangle {
            visible: tile.dominant && singleArt.visible
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * 0.53
            color: Qt.alpha("#0c0b0a", 0.78)
        }

        Canvas {
            id: responseCurve
            visible: tile.visual === "curve"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            y: parent.height * 0.43
            height: Math.max(44, parent.height * 0.32)
            renderTarget: Canvas.Image
            renderStrategy: Canvas.Threaded
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                ctx.lineWidth = 1;
                ctx.strokeStyle = Qt.alpha(Theme.washInk, 0.10);
                for (var gx = 0; gx <= 6; ++gx) {
                    ctx.beginPath();
                    ctx.moveTo(width * gx / 6, 0);
                    ctx.lineTo(width * gx / 6, height);
                    ctx.stroke();
                }
                for (var gy = 0; gy <= 3; ++gy) {
                    ctx.beginPath();
                    ctx.moveTo(0, height * gy / 3);
                    ctx.lineTo(width, height * gy / 3);
                    ctx.stroke();
                }
                ctx.lineWidth = 2;
                ctx.strokeStyle = Theme.primary;
                ctx.beginPath();
                ctx.moveTo(0, height * 0.58);
                ctx.bezierCurveTo(width * 0.16, height * 0.58,
                                  width * 0.15, height * 0.25,
                                  width * 0.28, height * 0.34);
                ctx.bezierCurveTo(width * 0.42, height * 0.46,
                                  width * 0.43, height * 0.80,
                                  width * 0.56, height * 0.55);
                ctx.bezierCurveTo(width * 0.68, height * 0.27,
                                  width * 0.75, height * 0.32,
                                  width * 0.82, height * 0.48);
                ctx.bezierCurveTo(width * 0.90, height * 0.68,
                                  width * 0.94, height * 0.52,
                                  width, height * 0.49);
                ctx.stroke();
            }
        }

        Row {
            visible: tile.visual === "meter"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            y: parent.height * 0.52
            height: Math.max(34, parent.height * 0.22)
            spacing: 4

            Repeater {
                model: 5
                delegate: Rectangle {
                    required property int index
                    width: Math.max(1, (parent.width - 16) / 5)
                    height: parent.height
                    color: Qt.alpha(Theme.washInk, 0.07)
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 2
                        color: Qt.alpha(Theme.primary, 0.62)
                    }
                }
            }
        }

        Icon {
            visible: tile.visual === "icon"
            anchors.right: parent.right
            anchors.rightMargin: tile.dominant ? 24 : 16
            anchors.verticalCenter: parent.verticalCenter
            name: tile.iconName
            size: tile.dominant ? 50 : 38
            color: Qt.alpha(Theme.primary, 0.86)
        }

        Item {
            id: copy
            x: 16
            y: tile.dominant ? 24 : 15
            width: tile.dominant ? parent.width * 0.45 : parent.width - 32
            height: Math.max(0, actionLabel.y - y - 6)

            Text {
                id: categoryLabel
                anchors.left: parent.left
                anchors.right: parent.right
                text: tile.category.toUpperCase()
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.weight: Font.Medium
                font.letterSpacing: 1.45
                elide: Text.ElideRight
            }

            Text {
                id: featureName
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: categoryLabel.bottom
                anchors.topMargin: tile.dominant ? 8 : 5
                text: tile.title
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: tile.dominant
                    ? (view.compact ? Theme.fsStat : Theme.fsHero)
                    : (tile.width < 210 ? Theme.fsEmph : Theme.fsTitle)
                font.weight: Font.Light
                font.letterSpacing: tile.dominant ? -1.1 : -0.35
                elide: Text.ElideRight
            }

            Text {
                visible: tile.description !== ""
                    && (tile.dominant || tile.tileKey === "smart-shuffle"
                        || tile.tileKey === "autoplay"
                        || tile.tileKey === "disliked")
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: featureName.bottom
                anchors.topMargin: 7
                text: tile.description
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: view.compact ? Theme.fsSmall : Theme.fsBody
                font.weight: Font.Light
                lineHeight: 1.3
                wrapMode: Text.Wrap
                maximumLineCount: tile.dominant ? 4 : 2
                elide: Text.ElideRight
            }

            Row {
                visible: tile.visual === "mosaic"
                anchors.left: parent.left
                anchors.top: featureName.bottom
                anchors.topMargin: 12
                spacing: 18

                Column {
                    Text {
                        text: tile.statOne
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.Light
                    }
                    Text {
                        text: tile.statOneLabel
                        color: Theme.washFaint
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 1.2
                    }
                }
                Column {
                    Text {
                        text: tile.statTwo
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsTitle
                        font.weight: Font.Light
                    }
                    Text {
                        text: tile.statTwoLabel
                        color: Theme.washFaint
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 1.2
                    }
                }
            }
        }

        Text {
            id: actionLabel
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.right: parent.right
            anchors.rightMargin: 16
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            text: tile.action.toUpperCase()
            color: tile.activeFocus || tileHover.hovered
                ? Theme.primary : Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsMicro
            font.weight: Font.DemiBold
            font.letterSpacing: 1.35
            elide: Text.ElideRight
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: tile.activeFocus ? 1 : (tileHover.hovered ? 1 : 0)
            border.color: tile.activeFocus ? Theme.focusRing
                                           : Qt.alpha(Theme.primary, 0.50)
        }

        HoverHandler {
            id: tileHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: tileTap
            onTapped: view.activate(tile.mode)
        }
    }

    Flickable {
        id: atlasFlick
        objectName: "featuresAtlasFlick"
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: atlasLoader.y + atlasLoader.height + (view.compact ? 20 : 32)
        ScrollBar.vertical: ArchiveScrollBar {}

        Loader {
            id: atlasLoader
            x: view.compact ? 20 : Theme.pageGutter(view.width)
            y: view.compact ? 72 : Math.max(88, Theme.pageTop(view.height))
            width: parent.width - x - (view.compact ? 20 : Math.max(48, view.width * 0.055))
            height: item ? item.height : 0
            sourceComponent: view.compact ? compactAtlas : desktopAtlas
        }
    }

    Component {
        id: desktopAtlas

        Item {
            id: desktop
            width: parent.width
            readonly property real introWidth: Math.min(245, width * 0.18)
            readonly property real atlasGap: 34
            readonly property real gridX: introWidth + atlasGap
            readonly property real gridWidth: width - gridX
            readonly property real firstFoldHeight: Math.max(620,
                view.height - atlasLoader.y - 24)
            readonly property real gap: 12
            readonly property real column: (gridWidth - gap * 11) / 12
            readonly property real row: (firstFoldHeight - gap * 5) / 6
            readonly property real continuationHeight: 152
            height: firstFoldHeight + gap + continuationHeight

            function gx(columnIndex) { return gridX + columnIndex * (column + gap); }
            function gy(rowIndex) { return rowIndex * (row + gap); }
            function gw(columns) { return columns * column + (columns - 1) * gap; }
            function gh(rows) { return rows * row + (rows - 1) * gap; }

            Item {
                id: atlasIntro
                objectName: "featuresAtlasIntro"
                x: 0
                y: 0
                width: desktop.introWidth
                height: desktop.firstFoldHeight

                Text {
                    id: atlasEyebrow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    text: "FEATURE ATLAS"
                    color: Theme.primary
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.weight: Font.DemiBold
                    font.letterSpacing: 2
                }
                Text {
                    id: atlasTitle
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: atlasEyebrow.bottom
                    anchors.topMargin: 10
                    text: "What Ampere can do with your music"
                    color: Theme.washInk
                    font.family: Theme.font
                    font.pixelSize: Theme.fsStat
                    font.weight: Font.Light
                    lineHeight: 1.02
                    wrapMode: Text.Wrap
                }
                Text {
                    id: atlasDeck
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: atlasTitle.bottom
                    anchors.topMargin: 14
                    text: "Sessions, playback intelligence, sound tools, and care for the library itself."
                    color: Theme.washMuted
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    font.weight: Font.Light
                    lineHeight: 1.4
                    wrapMode: Text.Wrap
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: atlasDeck.bottom
                    anchors.topMargin: 32

                    Repeater {
                        model: [
                            { label: "All features", count: "09", current: true },
                            { label: "Sessions", count: "03", current: false },
                            { label: "Playback", count: "03", current: false },
                            { label: "Sound + care", count: "03", current: false }
                        ]
                        delegate: Item {
                            required property var modelData
                            width: parent.width
                            height: 46
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: 1
                                color: Theme.washHair
                            }
                            Rectangle {
                                visible: parent.modelData.current
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: 14
                                height: 1
                                color: Theme.primary
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: parent.modelData.current ? 22 : 0
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.modelData.label.toUpperCase()
                                color: parent.modelData.current ? Theme.washInk : Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.fsMicro
                                font.letterSpacing: 1.35
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.modelData.count
                                color: Theme.washFaint
                                font.family: Theme.displayFont
                                font.pixelSize: Theme.fsMicro
                                font.letterSpacing: 1.1
                            }
                        }
                    }
                }
            }

            AtlasTile {
                tileKey: "discover"
                mode: "discover"
                category: "Sessions · 01"
                title: "Discover"
                description: "Loved records gone quiet. New arrivals. Deep cuts that never received their turn."
                action: "Open Discover  ›"
                visual: "art"
                entry: view.discoverEntry
                dominant: true
                x: desktop.gx(0); y: desktop.gy(0)
                width: desktop.gw(7); height: desktop.gh(4)
            }
            AtlasTile {
                tileKey: "rewind"
                mode: "rewind"
                category: "Sessions · 02"
                title: "Rewind"
                description: "Listening history, chapters, and sonic patterns."
                action: "Open history  ›"
                visual: "mosaic"
                entries: view.memoryEntries
                statOne: view.overview.ready ? String(view.metrics.week || 0) : "—"
                statOneLabel: "THIS WEEK"
                statTwo: view.overview.ready ? String(view.metrics.artists || 0) : "—"
                statTwoLabel: "ARTISTS"
                x: desktop.gx(7); y: desktop.gy(0)
                width: desktop.gw(5); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "ampy"
                mode: "ampy"
                category: "Sessions · 03"
                title: "Ampy"
                description: "Build a deliberate listening arc around the time you have."
                action: "Build a mix  ›"
                visual: "art"
                entry: view.ampyEntry
                x: desktop.gx(7); y: desktop.gy(2)
                width: desktop.gw(3); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "ambient"
                mode: "ambient"
                category: "Playback · 01"
                title: "Ambient"
                description: "The playing record becomes a full-screen room."
                action: "Enter room  ›"
                visual: "ambient"
                entry: view.currentEntry
                x: desktop.gx(10); y: desktop.gy(2)
                width: desktop.gw(2); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "eq"
                mode: "eq"
                category: "Sound + care · 01"
                title: "Parametric EQ"
                description: "Per-device correction with direct value editing."
                action: "Shape sound  ›"
                visual: "curve"
                x: desktop.gx(0); y: desktop.gy(4)
                width: desktop.gw(6); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "doctor"
                mode: "doctor"
                category: "Sound + care · 02"
                title: "Library Doctor"
                description: "Examine identity, tags, artwork, and versions."
                action: "Examine library  ›"
                visual: "meter"
                x: desktop.gx(6); y: desktop.gy(4)
                width: desktop.gw(3); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "smart-shuffle"
                mode: "smart-shuffle"
                category: "Playback · 02"
                title: "Smart Shuffle"
                description: "A similar song after every two authored tracks."
                action: "Choose a sequence  ›"
                visual: "icon"
                iconName: "smart-shuffle"
                x: desktop.gx(9); y: desktop.gy(4)
                width: desktop.gw(3); height: desktop.gh(2)
            }
            AtlasTile {
                tileKey: "autoplay"
                mode: "autoplay"
                category: "Playback · 03"
                title: "Autoplay"
                description: "Continue from the chosen queue when it reaches the end."
                action: "Open playback setting  ›"
                visual: "icon"
                iconName: "infinity"
                x: desktop.gridX
                y: desktop.firstFoldHeight + desktop.gap
                width: (desktop.gridWidth - desktop.gap) * 0.46
                height: desktop.continuationHeight
            }
            AtlasTile {
                tileKey: "disliked"
                mode: "disliked"
                category: "Sound + care · 03"
                title: "Out of Rotation"
                description: "Review music removed from normal selection."
                action: "Review collection  ›"
                visual: "icon"
                iconName: "heart-crack"
                x: desktop.gridX + (desktop.gridWidth - desktop.gap) * 0.46 + desktop.gap
                y: desktop.firstFoldHeight + desktop.gap
                width: desktop.gridWidth - (desktop.gridWidth - desktop.gap) * 0.46 - desktop.gap
                height: desktop.continuationHeight
            }
        }
    }

    Component {
        id: compactAtlas

        Item {
            id: compactRoom
            width: parent.width
            readonly property real gap: 8
            readonly property real columnWidth: (width - gap) / 2
            readonly property real discoverHeight: 164
            readonly property real rowHeight: 144
            readonly property real gridY: 76
            height: gridY + discoverHeight + gap + (rowHeight + gap) * 4

            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                text: "Feature Atlas"
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: Theme.fsStat
                font.weight: Font.Light
                font.letterSpacing: -0.7
            }
            Text {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 12
                text: "SESSIONS  ·  PLAYBACK  ·  SOUND + CARE"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.weight: Font.Medium
                font.letterSpacing: 1.05
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                y: 58
                height: 1
                color: Theme.washHair
            }

            AtlasTile {
                tileKey: "discover"; mode: "discover"
                category: "Sessions · 01"; title: "Discover"
                description: "Loved records gone quiet. New arrivals. Deep cuts that never received their turn."
                action: "Open Discover  ›"; visual: "art"
                entry: view.discoverEntry; dominant: true
                x: 0; y: compactRoom.gridY
                width: parent.width; height: compactRoom.discoverHeight
            }
            AtlasTile {
                tileKey: "rewind"; mode: "rewind"
                category: "Sessions · 02"; title: "Rewind"
                description: "Your listening history in motion."
                action: "Open history  ›"; visual: "mosaic"
                entries: view.memoryEntries
                statOne: view.overview.ready ? String(view.metrics.week || 0) : "—"
                statOneLabel: "WEEK"; statTwo: ""; statTwoLabel: ""
                x: 0; y: compactRoom.gridY + compactRoom.discoverHeight + compactRoom.gap
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "ampy"; mode: "ampy"
                category: "Sessions · 03"; title: "Ampy"
                description: "Mood-led sessions and saved mixes."
                action: "Build a mix  ›"; visual: "art"; entry: view.ampyEntry
                x: compactRoom.columnWidth + compactRoom.gap
                y: compactRoom.gridY + compactRoom.discoverHeight + compactRoom.gap
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "ambient"; mode: "ambient"
                category: "Playback · 01"; title: "Ambient"
                description: "Full-screen art and synchronized lyric."
                action: "Enter room  ›"; visual: "ambient"; entry: view.currentEntry
                x: 0; y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + compactRoom.rowHeight + compactRoom.gap
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "eq"; mode: "eq"
                category: "Sound + care · 01"; title: "Parametric EQ"
                description: "Per-device correction and direct editing."
                action: "Shape sound  ›"; visual: "curve"
                x: compactRoom.columnWidth + compactRoom.gap
                y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + compactRoom.rowHeight + compactRoom.gap
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "doctor"; mode: "doctor"
                category: "Sound + care · 02"; title: "Library Doctor"
                description: "Repair identity, tags, and versions."
                action: "Examine library  ›"; visual: "meter"
                x: 0; y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + (compactRoom.rowHeight + compactRoom.gap) * 2
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "smart-shuffle"; mode: "smart-shuffle"
                category: "Playback · 02"; title: "Smart Shuffle"
                description: "A similar song after every two authored tracks."
                action: "Choose a sequence  ›"; visual: "icon"; iconName: "smart-shuffle"
                x: compactRoom.columnWidth + compactRoom.gap
                y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + (compactRoom.rowHeight + compactRoom.gap) * 2
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "autoplay"; mode: "autoplay"
                category: "Playback · 03"; title: "Autoplay"
                description: "Continue when the chosen queue ends."
                action: "Open setting  ›"; visual: "icon"; iconName: "infinity"
                x: 0; y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + (compactRoom.rowHeight + compactRoom.gap) * 3
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
            AtlasTile {
                tileKey: "disliked"; mode: "disliked"
                category: "Sound + care · 03"; title: "Out of Rotation"
                description: "Review music removed from normal selection."
                action: "Review collection  ›"; visual: "icon"; iconName: "heart-crack"
                x: compactRoom.columnWidth + compactRoom.gap
                y: compactRoom.gridY + compactRoom.discoverHeight
                    + compactRoom.gap + (compactRoom.rowHeight + compactRoom.gap) * 3
                width: compactRoom.columnWidth; height: compactRoom.rowHeight
            }
        }
    }
}
