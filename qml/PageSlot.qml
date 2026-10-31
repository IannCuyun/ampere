import QtQuick
import "."

// One view's slot in the main content stack. When Theme.pageAnim is on, the
// incoming page fades and rises into place. The outgoing page hides at the
// ownership handoff so two semantic surfaces can never remain readable or
// focusable at once, even if an opacity animation is interrupted.
Item {
    id: slot
    // Declarative children live in a geometry-isolated host. The slot itself
    // continues to follow the window so page ownership and transition
    // transforms stay simple, but an inactive page keeps its last useful
    // dimensions instead of relaying every native resize configure through
    // its entire (often delegate-heavy) object tree.
    default property alias contentData: contentHost.data
    property bool current: false
    property real retainedWidth: 1
    property real retainedHeight: 1
    property bool _geometryAdoptionQueued: false
    readonly property real contentWidth: contentHost.width
    readonly property real contentHeight: contentHost.height

    function adoptSlotGeometry() {
        _geometryAdoptionQueued = false
        if (!current)
            return
        retainedWidth = Math.max(1, width)
        retainedHeight = Math.max(1, height)
    }

    function scheduleGeometryAdoption() {
        if (_geometryAdoptionQueued)
            return
        _geometryAdoptionQueued = true
        // Width and height arrive as separate notifications for one native
        // configure. Adopt the latest pair once before the next frame instead
        // of synchronously laying out the full page twice at a mixed aspect.
        Qt.callLater(adoptSlotGeometry)
    }

    // Responsive integrity is pre-frame: the active page adopts the latest
    // complete width/height pair before Qt renders it. Only hidden retained
    // pages are isolated from resize fan-out. Never scale an old active layout
    // into a new aspect ratio; that distorts artwork, type, and hit geometry.
    onWidthChanged: if (current) scheduleGeometryAdoption()
    onHeightChanged: if (current) scheduleGeometryAdoption()
    onCurrentChanged: if (current) adoptSlotGeometry()
    Component.onCompleted: {
        if (current)
            adoptSlotGeometry()
    }

    property Item _contentHost: Item {
        id: contentHost
        parent: slot
        x: 0
        y: 0
        width: slot.retainedWidth
        height: slot.retainedHeight
    }

    visible: current
    enabled: current
    opacity: current ? 1 : 0
    Behavior on opacity {
        enabled: Theme.pageAnim
        NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
    }
    transform: Translate {
        y: slot.current ? 0 : 16
        Behavior on y {
            enabled: Theme.pageAnim
            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }
    }
}
