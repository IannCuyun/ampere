import QtQuick
import "."

// An organic spectrum field: layered currents and drifting sparks rather than
// another equalizer-bar wall. It is intentionally decorative and never owns
// input. The 28-band tap shapes the ribbons; animation stops when the page is
// hidden or motion is disabled.
Item {
    id: field
    property var bands: []
    property bool active: false
    property real intensity: 1.0
    property real phase: 0

    readonly property bool animationRunning: paintClock.running
    readonly property int canvasRenderTarget: canvas.renderTarget

    readonly property real bass: average(0, 7)
    readonly property real mids: average(7, 18)
    readonly property real air: average(18, 28)

    function average(a, b) {
        if (!bands || bands.length === 0) return 0
        var sum = 0
        var end = Math.min(b, bands.length)
        for (var i = a; i < end; i++) sum += Number(bands[i] || 0)
        return end > a ? sum / (end - a) : 0
    }

    Timer {
        id: paintClock
        // One paint clock owns the canvas.  Audio frames only update `bands`;
        // repainting both here and in onBandsChanged previously doubled the
        // render pressure and could starve Qt's input/event processing.
        interval: 67
        repeat: true
        running: field.active && Theme.pageAnim
        onTriggered: {
            field.phase += 0.018 + field.bass * 0.018
            canvas.requestPaint()
        }
    }
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        // Keep raster work off the GUI thread so an expensive frame cannot
        // delay navigation, playback controls, or window repaint events.
        renderStrategy: Canvas.Threaded
        renderTarget: Canvas.Image
        opacity: 0.78 * field.intensity

        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ctx.reset()
            ctx.clearRect(0, 0, w, h)
            if (w <= 0 || h <= 0) return

            var energy = Math.min(1, field.bass * 0.50 + field.mids * 0.35 + field.air * 0.15)
            var baseY = h * 0.62
            var palette = [Theme.primary, Theme.secondary, Theme.tertiary]

            // Four translucent currents cross and separate as frequency
            // regions rise. Filled envelopes read as light in fog, not bars.
            for (var layer = 0; layer < 4; layer++) {
                var amp = h * (0.035 + energy * 0.09 + layer * 0.012)
                var y0 = baseY + (layer - 1.5) * h * 0.055
                var col = palette[layer % palette.length]
                var grad = ctx.createLinearGradient(0, y0 - amp, w, y0 + amp)
                grad.addColorStop(0, Qt.rgba(col.r, col.g, col.b, 0.02))
                grad.addColorStop(0.5, Qt.rgba(col.r, col.g, col.b, 0.18 + energy * 0.18))
                grad.addColorStop(1, Qt.rgba(col.r, col.g, col.b, 0.015))
                ctx.fillStyle = grad
                ctx.beginPath()
                ctx.moveTo(0, y0)
                var steps = 34
                for (var i = 0; i <= steps; i++) {
                    var x = w * i / steps
                    var bi = Math.min(27, Math.floor(i / steps * 28))
                    var band = field.bands.length > bi ? Number(field.bands[bi] || 0) : 0
                    var wave = Math.sin(i * 0.38 + field.phase * (1.1 + layer * 0.13) + layer)
                    var fine = Math.sin(i * 0.83 - field.phase * 0.7 + layer * 2.1) * 0.35
                    var y = y0 + (wave + fine) * amp * (0.35 + band * 1.25)
                    ctx.lineTo(x, y)
                }
                for (var j = steps; j >= 0; j--) {
                    var x2 = w * j / steps
                    var bi2 = Math.min(27, Math.floor(j / steps * 28))
                    var band2 = field.bands.length > bi2 ? Number(field.bands[bi2] || 0) : 0
                    var wave2 = Math.sin(j * 0.38 + field.phase * (1.1 + layer * 0.13) + layer)
                    var y2 = y0 + wave2 * amp * 0.18 - amp * (0.22 + band2 * 0.32)
                    ctx.lineTo(x2, y2)
                }
                ctx.closePath()
                ctx.fill()
            }

            // Slow deterministic sparks give high-frequency detail without
            // allocating particle objects or introducing random jitter.
            for (var p = 0; p < 30; p++) {
                var seed = p * 2.399963
                var speed = 0.25 + (p % 7) * 0.035
                var px = w * (0.5 + 0.46 * Math.sin(seed + field.phase * speed))
                var py = h * (0.50 + 0.38 * Math.cos(seed * 1.37 + field.phase * speed * 0.8))
                var lift = field.air * 18 + field.mids * 8
                py -= lift * Math.sin(seed + field.phase)
                var radius = 0.7 + (p % 4) * 0.45 + field.air * 1.8
                var pc = palette[p % palette.length]
                ctx.fillStyle = Qt.rgba(pc.r, pc.g, pc.b, 0.10 + field.air * 0.28)
                ctx.beginPath()
                ctx.arc(px, py, radius, 0, Math.PI * 2)
                ctx.fill()
            }
        }
    }
}
