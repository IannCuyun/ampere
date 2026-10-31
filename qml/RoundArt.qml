import QtQuick
import "."

// Circular artwork. The crop happens in the art provider ("round:" prefix,
// real alpha mask) — QML Rectangle clipping is bounding-box only and CANNOT
// round-crop an Image (burned 2026-07-13: every "round" avatar was square).
Rectangle {
    id: root
    property string art: ""
    property color ring: Theme.outline

    radius: width / 2
    color: Theme.surfaceVariant
    border.color: ring
    border.width: 1

    Image {
        anchors.fill: parent
        anchors.margins: 1
        source: root.art !== "" ? "image://art/round:" + encodeURIComponent(root.art) : ""
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        mipmap: true
    }
}
