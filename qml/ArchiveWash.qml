import QtQuick
import "."

// Archive Wash — the locked visual system (design/SPEC.md · Visual system,
// mockup: design/mockups/ampere-archive-wash-results/). The playing record's
// art fills the room, softened, under ONE flat semi-transparent dark veil
// (Iann's spec 2026-08-01: shapes and colors visible everywhere, text
// readable, no brightness bands). Composition per his art-scale pick A
// (2026-08-01): the whole record full-bleed and SHARP — the fit layer
// samples the native embedded art (capped 1536px, never magnified on his
// displays) while the ambient crop fill stays deliberately low-res (128px
// decode) to keep JPEG noise dissolved.
//
// Everything happens in ONE shader pass (shaders/archivewash.frag): ambient
// crop + the whole record centered (fit math in the shader — exact by
// construction), soften, tone ceiling (0.72u − 0.02, washpick option 2),
// veil, ~1 LSB dither LAST. Never split this back into MultiEffect/
// Rectangle layers: (a) MultiEffect's source proxy applies a fitted
// Image's centering offset TWICE — the off-center-by-window-orientation
// bug; (b) each extra 8-bit pass re-quantizes shallow dark ramps into
// contour blotches; a veil Rectangle on top would erase the dither.
// Triage records: design/triage/2026-08-01-wash-rendering.md +
// 2026-08-01-wash-art-scale.md.
Item {
    id: wash

    // ONE dial: how much the dark glass covers the record.
    property real veil: 0.74

    // Which record IS the room. The app-wide wash follows the playing song;
    // a detail page that is ABOUT one record (Album View) points this at the
    // record being looked at instead. Default keeps every existing caller
    // behaving exactly as before.
    property string sourceFile: backend.currentSong.file || ""

    // Second dial (2026-08-02): how much of the SHARP whole-record layer the
    // room carries. 1.0 is the locked wash. Now Playing drives it to 0 so the
    // page shows one sharp record — its own sleeve — over a soft field of
    // itself, instead of the same cover twice at two sizes.
    property real fitStrength: 1.0

    // If shader creation fails, fail dark and readable instead of transparent.
    Rectangle { anchors.fill: parent; color: "#0c0a0a" }

    Image {
        id: ambientArt
        source: wash.sourceFile
                ? "image://art/ambient:"
                  + encodeURIComponent(wash.sourceFile)
                : ""
        sourceSize: Qt.size(128, 128)
        smooth: true
        asynchronous: true
        cache: true
        visible: false
    }

    Image {
        id: fitArt
        source: wash.sourceFile
                ? "image://art/full:"
                  + encodeURIComponent(wash.sourceFile)
                : ""
        // Static bound: no resize-triggered provider churn. Raster sources
        // smaller than this remain at native size and are never upscaled.
        sourceSize: Qt.size(1536, 1536)
        smooth: true
        asynchronous: true
        cache: false
        visible: false
    }

    ShaderEffect {
        anchors.fill: parent
        property var ambientSource: ambientArt
        property var fitSource: fitArt
        property real artOpacity: ambientArt.status === Image.Ready
                                  && fitArt.status === Image.Ready ? 1.0 : 0.0
        property real veilOpacity: wash.veil
        property real fitStrength: wash.fitStrength
        property size itemSize: Qt.size(width, height)
        property size ambientPixels: Qt.size(
            Math.max(1, ambientArt.implicitWidth),
            Math.max(1, ambientArt.implicitHeight))
        property size fitPixels: Qt.size(
            Math.max(1, fitArt.implicitWidth),
            Math.max(1, fitArt.implicitHeight))
        fragmentShader: "shaders/archivewash.frag.qsb"

        Behavior on artOpacity { NumberAnimation { duration: 600 } }
    }
}
