import QtQuick
import "."

// Drift Constellation — Iann's wave-visualization verdict (2026-07-31;
// round: proposals/waveviz-round §W.02). Fifty-six deterministic motes, two
// per spectrum band: band energy alters orbit radius and opacity, positions
// stay stable (no glitter). Paused, it settles into a sparse fixed star
// chart with only a faint frequency horizon.
Canvas {
    id: field
    property var bands: []
    property bool live: false
    property real phase: 0

    onBandsChanged: requestPaint()
    onLiveChanged: requestPaint()

    Timer {
        interval: 33
        repeat: true
        running: field.visible && field.live
        onTriggered: { field.phase += 0.16; field.requestPaint() }
    }

    onPaint: {
        var ctx = getContext("2d")
        var w = width, h = height
        ctx.clearRect(0, 0, w, h)
        var k = Math.min(w, h) / 300      // mote scale relative to the mock
        var a = Theme.primary
        var b = Theme.artVividEased

        // the frequency horizon
        ctx.strokeStyle = Qt.alpha(a, live ? 0.075 : 0.045)
        ctx.lineWidth = 0.7
        ctx.beginPath()
        ctx.moveTo(0, h * 0.67)
        ctx.lineTo(w, h * 0.67)
        ctx.stroke()

        for (var p = 0; p < 56; p++) {
            var band = p % 28
            var e = (live && bands.length > band) ? bands[band] : 0
            var seed = p * 2.399963
            var drift = live ? phase * (0.055 + (p % 5) * 0.006) : 0
            var x = w * (0.51 + 0.45 * Math.sin(seed + drift))
                    + (band - 13.5) * e * 0.65 * k
            var y = h * (0.54 + 0.34 * Math.cos(seed * 1.37 + drift * 0.73))
                    - e * h * 0.16
            var r = (live ? 0.7 + e * 2.25 + (p % 3) * 0.2 : 0.62) * k
            ctx.fillStyle = Qt.alpha(p % 3 ? a : b, live ? 0.10 + e * 0.48 : 0.12)
            ctx.beginPath()
            ctx.arc(x, y, Math.max(0.5, r), 0, Math.PI * 2)
            ctx.fill()
        }
    }
}
