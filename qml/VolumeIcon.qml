import QtQuick
import "."

// Themed speaker icon (drawn — no more emoji in the transport).
Item {
    id: root
    property color color: Theme.textDim
    property bool muted: false
    property int size: 16
    width: size
    height: size
    onColorChanged: cv.requestPaint()
    onMutedChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.fillStyle = root.color
            ctx.strokeStyle = root.color
            ctx.lineWidth = 1.6
            ctx.lineCap = "round"
            // speaker body + cone
            ctx.beginPath()
            ctx.moveTo(1, h * 0.36)
            ctx.lineTo(w * 0.28, h * 0.36)
            ctx.lineTo(w * 0.52, h * 0.13)
            ctx.lineTo(w * 0.52, h * 0.87)
            ctx.lineTo(w * 0.28, h * 0.64)
            ctx.lineTo(1, h * 0.64)
            ctx.closePath()
            ctx.fill()
            if (root.muted) {
                ctx.beginPath()
                ctx.moveTo(w * 0.64, h * 0.32); ctx.lineTo(w * 0.94, h * 0.68); ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(w * 0.94, h * 0.32); ctx.lineTo(w * 0.64, h * 0.68); ctx.stroke()
            } else {
                ctx.beginPath()
                ctx.arc(w * 0.54, h * 0.5, w * 0.22, -0.85, 0.85)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(w * 0.54, h * 0.5, w * 0.38, -0.75, 0.75)
                ctx.stroke()
            }
        }
    }
}
