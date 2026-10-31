import QtQuick
import "."

// Themed filled heart (drawn — matches HeartCrackIcon's geometry exactly).
// liked: true adds a little four-point sparkle at the shoulder.
Item {
    id: root
    property color color: Theme.textDim
    property bool liked: false
    property int size: 16
    width: size
    height: size
    onColorChanged: cv.requestPaint()
    onLikedChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.fillStyle = root.color
            // the heart: two lobes + point (same path as the broken one)
            ctx.beginPath()
            ctx.moveTo(w * 0.5, h * 0.30)
            ctx.bezierCurveTo(w * 0.42, h * 0.06, w * 0.04, h * 0.10, w * 0.06, h * 0.38)
            ctx.bezierCurveTo(w * 0.08, h * 0.60, w * 0.32, h * 0.76, w * 0.5, h * 0.94)
            ctx.bezierCurveTo(w * 0.68, h * 0.76, w * 0.92, h * 0.60, w * 0.94, h * 0.38)
            ctx.bezierCurveTo(w * 0.96, h * 0.10, w * 0.58, h * 0.06, w * 0.5, h * 0.30)
            ctx.closePath()
            ctx.fill()
            if (root.liked) {
                // the sparkle: four-point star off the right shoulder, with
                // a halo punched out of the lobe so it reads as separate
                var cx = w * 0.82, cy = h * 0.16, r = w * 0.20
                ctx.globalCompositeOperation = "destination-out"
                ctx.beginPath()
                ctx.arc(cx, cy, r * 1.55, 0, Math.PI * 2)
                ctx.fill()
                ctx.globalCompositeOperation = "source-over"
                ctx.beginPath()
                ctx.moveTo(cx, cy - r)
                ctx.quadraticCurveTo(cx + r * 0.18, cy - r * 0.18, cx + r, cy)
                ctx.quadraticCurveTo(cx + r * 0.18, cy + r * 0.18, cx, cy + r)
                ctx.quadraticCurveTo(cx - r * 0.18, cy + r * 0.18, cx - r, cy)
                ctx.quadraticCurveTo(cx - r * 0.18, cy - r * 0.18, cx, cy - r)
                ctx.closePath()
                ctx.fill()
            }
        }
    }
}
