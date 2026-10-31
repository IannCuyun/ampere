import QtQuick
import "."

// The room's background: a GPU shader gradient (shaders/shade.frag) computed
// per-fragment at full float precision with ~1 LSB dither baked in at the
// end. No source image exists, so nothing can quantize into bands and
// nothing is ever stretched into streaks. A pure presenter: all palette
// easing lives in Theme's HSL engine — feed it eased tokens only, or it
// would double-ease and lag the rest of the room.
// ⚠ OPAQUE COLORS ONLY: shade.frag mixes .rgb and outputs alpha 1.0 —
// passing "transparent"/alpha colors renders an opaque near-black slab
// (this painted a black wall over half the app on 2026-08-01).
Item {
    id: rg
    property color topColor: "#202020"
    property color bottomColor: "#101010"

    ShaderEffect {
        anchors.fill: parent
        property color cTop: rg.topColor
        property color cBot: rg.bottomColor
        fragmentShader: "shaders/shade.frag.qsb"
    }
}
