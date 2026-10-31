import QtQuick
import "."

// Themed broken-heart icon (drawn — no more emoji in the transport).
// Filled heart with a lightning crack cut out of the middle.
Item {
    id: root
    property color color: Theme.textDim
    property int size: 16
    width: size
    height: size
    onColorChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.fillStyle = root.color
            // the heart: two lobes + point
            ctx.beginPath()
            ctx.moveTo(w * 0.5, h * 0.30)
            ctx.bezierCurveTo(w * 0.42, h * 0.06, w * 0.04, h * 0.10, w * 0.06, h * 0.38)
            ctx.bezierCurveTo(w * 0.08, h * 0.60, w * 0.32, h * 0.76, w * 0.5, h * 0.94)
            ctx.bezierCurveTo(w * 0.68, h * 0.76, w * 0.92, h * 0.60, w * 0.94, h * 0.38)
            ctx.bezierCurveTo(w * 0.96, h * 0.10, w * 0.58, h * 0.06, w * 0.5, h * 0.30)
            ctx.closePath()
            ctx.fill()
            // the crack: zigzag cut straight out of the fill
            ctx.globalCompositeOperation = "destination-out"
            ctx.strokeStyle = "#000"
            ctx.lineWidth = Math.max(1.4, w * 0.11)
            ctx.lineCap = "butt"
            ctx.lineJoin = "miter"
            ctx.beginPath()
            ctx.moveTo(w * 0.50, h * 0.16)
            ctx.lineTo(w * 0.40, h * 0.38)
            ctx.lineTo(w * 0.56, h * 0.52)
            ctx.lineTo(w * 0.44, h * 0.72)
            ctx.lineTo(w * 0.52, h * 0.96)
            ctx.stroke()
            ctx.globalCompositeOperation = "source-over"
        }
    }
}
