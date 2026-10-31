import QtQuick
import "."

// Curved crossing-arrows shuffle icon (Spotify-style S-curves) with a
// distinct variant per mode:
//   off   — plain arrows
//   queue — plain arrows (the dot alone says "on")
//   genre — arrows + bold G
//   album — arrows + bold A
//   all   — arrows + ∞ (legacy)
//   mix / smart — arrows + four-point sparkle
// Any active mode also gets the little dot underneath.
Item {
    id: root
    property color color: Theme.textDim
    property int size: 16
    property string mode: "off"
    width: size + 8
    height: size + 5
    onColorChanged: cv.requestPaint()
    onModeChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = root.color
            ctx.fillStyle = root.color
            ctx.lineWidth = 1.7
            ctx.lineCap = "round"
            var s = root.size

            // horizontal lead-in, S-curve across, horizontal lead-out + arrowhead
            function swoosh(y0, y1) {
                ctx.beginPath()
                ctx.moveTo(0.8, y0)
                ctx.lineTo(s * 0.20, y0)
                ctx.bezierCurveTo(s * 0.44, y0, s * 0.50, y1, s * 0.72, y1)
                ctx.lineTo(s * 0.80, y1)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(s * 0.80 + 4.6, y1)
                ctx.lineTo(s * 0.80 - 0.6, y1 - 3.1)
                ctx.lineTo(s * 0.80 - 0.6, y1 + 3.1)
                ctx.closePath()
                ctx.fill()
            }
            function sparkle(cx, cy, r) {
                ctx.beginPath()
                ctx.moveTo(cx, cy - r)
                ctx.quadraticCurveTo(cx + r * 0.18, cy - r * 0.18, cx + r, cy)
                ctx.quadraticCurveTo(cx + r * 0.18, cy + r * 0.18, cx, cy + r)
                ctx.quadraticCurveTo(cx - r * 0.18, cy + r * 0.18, cx - r, cy)
                ctx.quadraticCurveTo(cx - r * 0.18, cy - r * 0.18, cx, cy - r)
                ctx.closePath()
                ctx.fill()
            }

            swoosh(s * 0.74, s * 0.26)
            swoosh(s * 0.26, s * 0.74)

            ctx.font = "bold " + Math.round(s * 0.62) + "px \"" + Theme.font + "\""
            if (root.mode === "genre")
                ctx.fillText("G", s + 0.5, s * 0.62)
            else if (root.mode === "album")
                ctx.fillText("A", s + 0.5, s * 0.62)
            else if (root.mode === "all")
                ctx.fillText("∞", s + 0.5, s * 0.62)
            else if (root.mode === "smart" || root.mode === "mix") {
                sparkle(s + 3, s * 0.28, 3.6)
                sparkle(s + 6.5, s * 0.62, 1.9)
            }

            if (root.mode !== "off") {
                ctx.beginPath()
                ctx.arc(s / 2, height - 1.8, 1.8, 0, Math.PI * 2)
                ctx.fill()
            }
        }
    }
}
