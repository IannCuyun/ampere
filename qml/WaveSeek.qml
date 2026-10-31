import QtQuick
import "."

// Waveform seek bar: the track's peak envelope IS the progress bar.
// Falls back to a plain line while the envelope is being computed.
Item {
    id: ws
    implicitHeight: 42
    implicitWidth: 220
    // Native window resizing must not allocate and repaint two GPU canvases
    // for every intermediate compositor configure. The item still follows
    // exact geometry; it presents a lightweight seek rail during the short
    // resize interval and rebuilds the real waveform once at the final width.
    property bool resizeActive: false
    property bool _rebuildQueued: false
    property int rasterWidth: 1
    property int rasterHeight: 1
    readonly property real progress: backend.duration > 0
        ? Math.min(1, (seekArea.scrubbing ? seekArea.scrubX / width : backend.elapsed / backend.duration))
        : 0
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
    Rectangle {
        z: 20
        anchors.fill: parent
        color: "transparent"
        border.width: ws.activeFocus ? 1 : 0
        border.color: Theme.focusRing
    }
    // section markers for long files (mixes, full-album rips) — times in s
    property var chapters: []
    onChaptersChanged: cv.requestPaint()

    // bars are computed ONCE per (waveform, width) and cached — progress
    // repaints must never re-bucket, or the silhouette shimmers every second
    property var bars: []
    function rebuildBars() {
        _rebuildQueued = false
        if (resizeActive)
            return
        var wave = backend.waveform
        var w = Math.round(width)
        rasterWidth = Math.max(1, w)
        rasterHeight = Math.max(1, Math.round(height))
        if (w <= 0 || wave.length < 8) { bars = []; cv.requestPaint(); cvLit.requestPaint(); return }
        // clip the full-file envelope to the played slice (#18): a DJ-ranged
        // song's elapsed/duration are slice-relative, so the silhouette must
        // show only what plays or the progress marker rides the wrong bars
        var trim = backend.waveTrim
        var lo0 = Math.floor((trim[0] || 0) * wave.length)
        var hi0 = Math.ceil((trim[1] || 1) * wave.length)
        if (hi0 - lo0 >= 8) wave = wave.slice(lo0, hi0)
        var n = wave.length
        var m = Math.max(24, Math.min(n, Math.floor(w / 3)))
        var out = []
        for (var i = 0; i < m; i++) {
            var lo = Math.floor(i * n / m)
            var hi = Math.max(lo + 1, Math.floor((i + 1) * n / m))
            var peak = 0
            for (var j = lo; j < hi; j++) peak = Math.max(peak, wave[j])
            out.push(peak)
        }
        bars = out
        cv.requestPaint()
        cvLit.requestPaint()
    }
    function scheduleRebuild() {
        if (resizeActive || _rebuildQueued)
            return
        _rebuildQueued = true
        Qt.callLater(rebuildBars)
    }
    onWidthChanged: scheduleRebuild()
    onHeightChanged: scheduleRebuild()
    onResizeActiveChanged: if (!resizeActive) scheduleRebuild()
    Component.onCompleted: rebuildBars()
    Connections {
        target: backend
        function onWaveformChanged() { ws.rebuildBars() }
    }

    // The progress cursor advances every second. It used to force a FULL
    // canvas repaint (all bars + ticks + markers) just to move a 1px line and
    // recolor the crossed bar. Now the silhouette is static (repaints only on
    // data change) and the "played" state is a primary-colored COPY revealed by
    // a clip whose width is BOUND to progress — so each tick is a cheap layout
    // change, no canvas work. Repaint on palette ease since we no longer do it
    // every second.
    property color litColor: Theme.primary
    property color dimColor: Theme.textDim
    onLitColorChanged: { cv.requestPaint(); cvLit.requestPaint() }
    onDimColorChanged: cv.requestPaint()

    function paintBars(ctx, w, h, lit) {
        ctx.clearRect(0, 0, w, h)
        var m = ws.bars.length
        if (m === 0) {   // no envelope yet: slim fallback line
            ctx.fillStyle = lit ? Theme.primary : Qt.alpha(Theme.surfaceVariant, 0.9)
            ctx.fillRect(0, h / 2 - 1.5, w, 3)
            return
        }
        var bw = w / m
        var barW = Math.max(1.5, bw - 1)
        ctx.fillStyle = lit ? Theme.primary : Qt.alpha(Theme.textDim, 0.3)
        for (var i = 0; i < m; i++) {
            var bh = Math.max(2, ws.bars[i] * (h - 4))
            ctx.fillRect(i * bw, (h - bh) / 2, barW, bh)
        }
    }

    // static silhouette (dim) + chapter ticks + DJ cut marker
    Canvas {
        id: cv
        anchors.fill: parent
        visible: !ws.resizeActive
        canvasSize: Qt.size(ws.rasterWidth, ws.rasterHeight)
        // Qt 6 supports Canvas.Image only. Threaded gives its raster pass a
        // private painting thread; FramebufferObject is ignored in Qt 6 and
        // Cooperative does not guarantee separation from the GUI thread.
        renderTarget: Canvas.Image
        renderStrategy: Canvas.Threaded
        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ws.paintBars(ctx, w, h, false)
            // chapter ticks: section starts of a long file, as seek targets
            if (ws.chapters.length > 0 && backend.duration > 1) {
                ctx.fillStyle = Qt.alpha(Theme.text, 0.5)
                for (var c = 0; c < ws.chapters.length; c++) {
                    var chx = (ws.chapters[c] / backend.duration) * w
                    ctx.fillRect(chx - 0.5, 0, 1, 5)
                    ctx.fillRect(chx - 0.5, h - 5, 1, 5)
                }
            }
            // DJ cut marker: where this song will hand off to the next.
            // (A song already sliced by rangeid reports the slice as its
            // whole timeline, so the guard hides the marker there — the
            // bar's end IS the cut.)
            var cut = backend.djCutAt
            if (cut > 0 && backend.duration > 1 && cut < backend.duration - 1) {
                var cx = (cut / backend.duration) * w
                ctx.fillStyle = Theme.tertiary
                ctx.fillRect(cx - 0.75, 0, 1.5, h)
                ctx.beginPath()
                ctx.moveTo(cx - 4, 0)
                ctx.lineTo(cx + 4, 0)
                ctx.lineTo(cx, 6)
                ctx.closePath()
                ctx.fill()
            }
        }
    }

    // played overlay: the SAME bars in primary, revealed only up to progress by
    // a clip bound to progress (no repaint as it advances)
    Item {
        width: Math.max(0, ws.progress * ws.width)
        height: ws.height
        clip: true
        visible: !ws.resizeActive
        Canvas {
            id: cvLit
            width: ws.width
            height: ws.height
            canvasSize: Qt.size(ws.rasterWidth, ws.rasterHeight)
            renderTarget: Canvas.Image
            renderStrategy: Canvas.Threaded
            onPaint: ws.paintBars(getContext("2d"), width, height, true)
        }
    }

    // Exact-size transition fallback. It deliberately changes vocabulary
    // rather than stretching a stale waveform texture into a new aspect.
    Item {
        anchors.fill: parent
        visible: ws.resizeActive
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: 2
            color: Qt.alpha(Theme.textDim, 0.30)
        }
        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, ws.progress * parent.width)
            height: 2
            color: Theme.primary
        }
    }

    // progress cursor: a bound overlay Rectangle, never a canvas repaint
    Rectangle {
        x: ws.progress * ws.width - 0.75
        y: 1
        width: 1.5
        height: ws.height - 2
        color: Theme.text
    }

    // hover ghost: target line + the time a click would seek to
    Rectangle {
        visible: seekArea.containsMouse && !seekArea.scrubbing
        x: seekArea.mouseX - 0.75
        width: 1.5; height: parent.height
        color: Qt.alpha(Theme.text, 0.55)
    }
    Rectangle {
        visible: seekArea.containsMouse && !seekArea.scrubbing
        x: Math.max(0, Math.min(ws.width - width, seekArea.mouseX - width / 2))
        y: -26
        width: wsHoverTime.implicitWidth + 14
        height: 22
        radius: Theme.radiusSm
        color: Qt.alpha(Theme.surface, 0.95)
        border.color: Theme.outline
        Text {
            id: wsHoverTime
            anchors.centerIn: parent
            text: Theme.fmtTime((Math.max(0, Math.min(ws.width, seekArea.mouseX)) / Math.max(1, ws.width)) * backend.duration)
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.fsMicro
        }
    }

    MouseArea {
        id: seekArea
        anchors.fill: parent
        enabled: backend.duration > 0
        preventStealing: true
        hoverEnabled: true
        property bool scrubbing: false
        property real scrubX: 0
        cursorShape: Qt.PointingHandCursor

        // don't spam MPD while scrubbing — trailing seek at ~8 Hz
        Timer {
            id: seekThrottle
            interval: 120
            onTriggered: backend.requestSeek((seekArea.scrubX / ws.width) * backend.duration)
        }
        function scrubTo(x) {
            scrubX = Math.max(0, Math.min(ws.width, x))
            seekThrottle.restart()
        }
        onPressed: (mouse) => { scrubbing = true; scrubTo(mouse.x) }
        onPositionChanged: (mouse) => { if (scrubbing) scrubTo(mouse.x) }
        onReleased: (mouse) => {
            seekThrottle.stop()
            backend.requestSeek((scrubX / ws.width) * backend.duration)
            scrubbing = false
        }
        onCanceled: { seekThrottle.stop(); scrubbing = false }
    }
}
