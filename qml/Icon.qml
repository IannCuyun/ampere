import QtQuick
import QtQuick.Shapes
import "."

// The Ampere icon set — every symbol drawn, one voice: 24-grid monoline,
// round caps/joins, geometry echoing the A-sine mark (the wave IS the
// mark's crossbar). No unicode glyph soup: if a symbol is needed, it gets
// drawn here and named. Entries: s = stroked subpaths, f = filled subpaths,
// w = stroke-width override (24-grid units).
Item {
    id: root
    property string name: ""
    property color color: Theme.textDim
    property real size: 16
    width: size
    height: size

    readonly property var _reg: ({
        "play": { s: "M9.3 6.9 L17.5 12 L9.3 17.1 Z", w: 1.9 },
        "beacon": { s: "M12 10 V19 M8.6 19 L12 11.5 L15.4 19 M9.5 8.2 A3.5 3.5 0 0 1 9.5 3.8 M14.5 3.8 A3.5 3.5 0 0 1 14.5 8.2 M6.9 10.5 A6.8 6.8 0 0 1 6.9 1.5 M17.1 1.5 A6.8 6.8 0 0 1 17.1 10.5", f: "M11 6 a1 1 0 1 0 2 0 a1 1 0 1 0 -2 0", w: 1.7 },
        "pause": { s: "M9.3 7 V17 M14.7 7 V17", w: 2.3 },
        "prev": { s: "M7.8 7 V17 M16.8 7.1 L9.8 12 L16.8 16.9", w: 1.9 },
        "next": { s: "M7.2 7.1 L14.2 12 L7.2 16.9 M16.2 7 V17", w: 1.9 },
        "chevron-left": { s: "M14.2 6.8 L9.4 12 L14.2 17.2" },
        "chevron-right":{ s: "M9.8 6.8 L14.6 12 L9.8 17.2" },
        "chevron-down": { s: "M6.8 9.8 L12 14.6 L17.2 9.8" },
        "arrow-up":     { s: "M12 18 V6 M7.5 10.5 L12 6 L16.5 10.5" },
        "close":        { s: "M7.6 7.6 L16.4 16.4 M16.4 7.6 L7.6 16.4" },
        "check":        { s: "M6.8 12.6 L10.6 16.2 L17.2 7.8" },
        "plus":         { s: "M12 6.6 V17.4 M6.6 12 H17.4" },
        "minus":        { s: "M6.6 12 H17.4" },
        "search": { s: "M5.2 10.3 A5.1 5.1 0 1 0 15.4 10.3 A5.1 5.1 0 1 0 5.2 10.3 M14 14.1 L19 19.1", w: 1.9 },
        "gear":         { s: "M7.8 12 a4.2 4.2 0 1 0 8.4 0 a4.2 4.2 0 1 0 -8.4 0 M17.2 12 H19.4 M4.6 12 H6.8 M12 17.2 V19.4 M12 4.6 V6.8 M15.7 15.7 L17.2 17.2 M6.8 6.8 L8.3 8.3 M15.7 8.3 L17.2 6.8 M6.8 17.2 L8.3 15.7", w: 2 },
        "save":         { s: "M12 5.4 V12.6 M8.8 9.6 L12 12.8 L15.2 9.6 M5.8 15.2 V17.8 H18.2 V15.2" },
        "trash":        { s: "M6.8 8.6 H17.2 M10 8.6 V7 H14 V8.6 M8.4 8.6 L9.1 17.6 H14.9 L15.6 8.6 M10.9 11.2 V15 M13.1 11.2 V15", w: 2 },
        "list": { s: "M6 7.4 H18 M6 12 H18 M6 16.6 H14.3", w: 1.9 },
        "playlist":     { s: "M5.8 7.6 H13.2 M5.8 11.6 H11.2 M5.8 15.6 H9.4 M18.2 15.6 V7.2",
                          f: "M14.5 15.7 a1.85 1.85 0 1 0 3.7 0 a1.85 1.85 0 1 0 -3.7 0" },
        "note":         { s: "M12.6 16.5 V6.8 L17.2 8.2 M8.4 16.6 C8.4 15.4 9.4 14.6 10.7 14.6 C11.9 14.6 12.6 15.3 12.6 16.5 C12.6 17.7 11.6 18.5 10.3 18.5 C9.1 18.5 8.4 17.8 8.4 16.6", w: 1.9 },
        "eq":           { s: "M7.6 6.6 V17.4 M12 6.6 V17.4 M16.4 6.6 V17.4 M5.9 10.4 H9.3 M10.3 13.8 H13.7 M14.7 8.6 H18.1", w: 2 },
        "wave":         { s: "M5.2 12 C 7.5 7.6, 9.7 7.6, 12 12 S 16.5 16.4, 18.8 12" },
        "loop":         { s: "M7.1 8.4 C8.4 7 10 6.3 12 6.3 C15.3 6.3 18 8.4 18.7 11.3 M16 8.6 L18.7 11.3 L20 8.1 M16.9 15.6 C15.6 17 14 17.7 12 17.7 C8.7 17.7 6 15.6 5.3 12.7 M8 15.4 L5.3 12.7 L4 15.9", w: 1.9 },
        "history":      { s: "M6.4 10.4 A5.8 5.8 0 1 1 6.4 13.6 M12 9.2 V12 L14.2 13.4",
                          f: "M7.8 13.2 L3.8 13.2 L5.8 16.4 Z" },
        "infinity":     { s: "M6.2 12 C 6.2 9.9 7.9 8.7 9.5 9.8 L14.5 14.2 C 16.1 15.3 17.8 14.1 17.8 12 C 17.8 9.9 16.1 8.7 14.5 9.8 L9.5 14.2 C 7.9 15.3 6.2 14.1 6.2 12 Z" },
        "moon": { s: "M15.8 6.2 C11.5 6.1 8.2 9 8.2 12.7 C8.2 15.2 9.8 17.3 12.2 18.2 C8.3 18.3 5.3 15.7 5.3 12.1 C5.3 8.6 8 5.8 11.7 5.8", w: 1.9 },
        "fullscreen": { s: "M5.5 9.2 V5.5 H9.2 M14.8 5.5 H18.5 V9.2 M18.5 14.8 V18.5 H14.8 M9.2 18.5 H5.5 V14.8", w: 1.9 },
        // Needle drew mini with corner brackets, making it a smaller copy of
        // "fullscreen" on the same screen. Same weight, unambiguous mark.
        "mini": { s: "M5.4 7 H18.6 V17 H5.4 Z M12.3 12.1 H17.2 V16.2 H12.3 Z", w: 1.9 },
        "grid":         { s: "M6.2 6.2 H10.9 V10.9 H6.2 Z M13.1 6.2 H17.8 V10.9 H13.1 Z M6.2 13.1 H10.9 V17.8 H6.2 Z M13.1 13.1 H17.8 V17.8 H13.1 Z", w: 1.9 },
        "disc":         { s: "M5.6 12 a6.4 6.4 0 1 0 12.8 0 a6.4 6.4 0 1 0 -12.8 0",
                          f: "M10.6 12 a1.4 1.4 0 1 0 2.8 0 a1.4 1.4 0 1 0 -2.8 0" },
        "dj":           { s: "M5 12 a3.9 3.9 0 1 0 7.8 0 a3.9 3.9 0 1 0 -7.8 0 M11.2 12 a3.9 3.9 0 1 0 7.8 0 a3.9 3.9 0 1 0 -7.8 0",
                          f: "M8 12 a1 1 0 1 0 2 0 a1 1 0 1 0 -2 0 M14 12 a1 1 0 1 0 2 0 a1 1 0 1 0 -2 0", w: 1.9 },
        "sparkle":      { f: "M12 5 Q12.8 11.2 19 12 Q12.8 12.8 12 19 Q11.2 12.8 5 12 Q11.2 11.2 12 5 Z" },
        "bars":         { s: "M7.4 17.4 V11.8 M12 17.4 V7.4 M16.6 17.4 V10.2", w: 2.6 },
        "clock":        { s: "M5.6 12 a6.4 6.4 0 1 0 12.8 0 a6.4 6.4 0 1 0 -12.8 0 M12 8.4 V12 L14.8 13.8" },
        "ring":         { s: "M6.8 12 a5.2 5.2 0 1 0 10.4 0 a5.2 5.2 0 1 0 -10.4 0" },
        "ring-dot":     { s: "M6.8 12 a5.2 5.2 0 1 0 10.4 0 a5.2 5.2 0 1 0 -10.4 0",
                          f: "M9.9 12 a2.1 2.1 0 1 0 4.2 0 a2.1 2.1 0 1 0 -4.2 0" },
        "freq-lock":    { s: "M9.3 6.6 V17.4 M6.6 9.3 L9.3 6.6 L12 9.3 M14.7 6.6 V17.4 M12 14.7 L14.7 17.4 L17.4 14.7", w: 2 },
        "swap":         { s: "M6 9.3 H16.4 M13.9 6.6 L16.6 9.3 L13.9 12 M18 14.7 H7.6 M10.1 12 L7.4 14.7 L10.1 17.4", w: 2 },
        "heart": { f: "M12 17.5 C6.8 14.1 6.4 10.6 8.2 8.8 C9.6 7.4 11.3 8 12 9.5 C12.7 8 14.4 7.4 15.8 8.8 C17.6 10.6 17.2 14.1 12 17.5 Z" },
        "heart-o": { s: "M12 18 C7.2 14.8 5.7 11.5 7.4 8.9 C9 6.7 11.4 7.5 12 9.4 C12.6 7.5 15 6.7 16.6 8.9 C18.3 11.5 16.8 14.8 12 18", w: 1.9 },
        "heart-crack":  { s: "M12 17.8 C 5.6 13.4 5.2 9.1 7.7 7.4 C 9.6 6.2 11.5 7.2 12 8.6 C 12.5 7.2 14.4 6.2 16.3 7.4 C 18.8 9.1 18.4 13.4 12 17.8 Z M12 8.8 L10.7 11.2 L13.1 13.2 L11.7 15.6", w: 1.9 },
        "inbox":        { s: "M5.6 12.6 H9.4 L11 14.8 H13 L14.6 12.6 H18.4 M5.6 12.6 V17.2 H18.4 V12.6 M12 5.4 V9.6 M9.8 7.6 L12 9.8 L14.2 7.6" },
        "folder":       { s: "M5.6 17 V7.4 H10 L11.6 9.2 H18.4 V17 Z" },
        // Ampy — the curator's face: round head, bright eyes, and the
        // A-sine wave as the mouth (the mark's crossbar IS the smile)
        // (mouth = ONE smile arc — a half-period of the mark's sine. A full
        // sine mouth reads as a frown/confusion at small sizes; two
        // screenshot rounds proved it 2026-07-20. Don't re-wave the mouth.)
        "ampy":         { s: "M4.9 12 a7.1 7.1 0 1 0 14.2 0 a7.1 7.1 0 1 0 -14.2 0 M8.7 13.6 C 9.9 15.5, 14.1 15.5, 15.3 13.6",
                          f: "M8.3 9.9 a1.15 1.15 0 1 0 2.3 0 a1.15 1.15 0 1 0 -2.3 0 M13.4 9.9 a1.15 1.15 0 1 0 2.3 0 a1.15 1.15 0 1 0 -2.3 0", w: 2 },
        "shuffle":      { s: "M5.2 7.5 H7.8 C10.8 7.5 13.2 16.5 16.3 16.5 H18.8 M16 13.9 L18.8 16.5 L16 19.1 M5.2 16.5 H7.8 C10.8 16.5 13.2 7.5 16.3 7.5 H18.8 M16 4.9 L18.8 7.5 L16 10.1", w: 1.9 },
        "smart-shuffle": {
            s: "M8.4 9 H10.2 C12.7 9 14.7 16 17.2 16 H19 M16.6 13.7 L19 16 L16.6 18.3 M8.4 16 H10.2 C12.7 16 14.7 9 17.2 9 H19 M16.6 6.7 L19 9 L16.6 11.3",
            f: "M5.5 3.5 Q5.9 6.1 8.5 6.5 Q5.9 6.9 5.5 9.5 Q5.1 6.9 2.5 6.5 Q5.1 6.1 5.5 3.5 Z M5.9 15.4 Q6.2 16.9 7.7 17.2 Q6.2 17.5 5.9 19 Q5.6 17.5 4.1 17.2 Q5.6 16.9 5.9 15.4 Z",
            w: 1.9
        },
        "volume":       { s: "M5 10 H8 L12.2 6.4 V17.6 L8 14 H5 M14.7 9 C15.8 9.8 16.3 10.8 16.3 12 C16.3 13.2 15.8 14.2 14.7 15 M17.1 6.9 C18.8 8.3 19.6 10 19.6 12 C19.6 14 18.8 15.7 17.1 17.1", w: 1.9 },
        "volume-muted": { s: "M5 10 H8 L12.2 6.4 V17.6 L8 14 H5 M15.1 8.8 L19.2 15.2 M19.2 8.8 L15.1 15.2", w: 1.9 },
        "sliders":      { s: "M5.8 7.6 H18.2 M5.8 12 H18.2 M5.8 16.4 H18.2",
                          f: "M8.3 7.6 a1.7 1.7 0 1 0 3.4 0 a1.7 1.7 0 1 0 -3.4 0 M13.5 12 a1.7 1.7 0 1 0 3.4 0 a1.7 1.7 0 1 0 -3.4 0 M6.7 16.4 a1.7 1.7 0 1 0 3.4 0 a1.7 1.7 0 1 0 -3.4 0", w: 2 }
    })
    readonly property var _e: _reg[name] || {}

    Shape {
        anchors.centerIn: parent
        width: 24
        height: 24
        scale: root.size / 24
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root._e.s ? root.color : "transparent"
            strokeWidth: root._e.w || 2.2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root._e.s || "" }
        }
        ShapePath {
            strokeColor: "transparent"
            fillColor: root._e.f ? root.color : "transparent"
            PathSvg { path: root._e.f || "" }
        }
    }
}
