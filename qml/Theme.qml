pragma Singleton
import QtQuick
import QtCore

// Theme v7 — ONE room: the album IS the room. The theme is rebuilt per
// song from the playing cover's palette (Plexamp-style saturated space);
// no art -> neutral grey. The three HSL inputs ease over themeMs and every
// token derives from the eased values, so transitions travel through hue
// space (never through grey mud) and the whole room moves on one clock.
// Readability is guaranteed, not hoped for: text-bearing tokens lift their
// lightness until they clear WCAG against the surfaces they sit on, for
// EVERY possible album color.
Item {
    id: t
    visible: false

    // Utility rooms stay calm; playback rooms may use the full album palette.
    // Main.qml owns this state so color supports the current job instead of
    // tinting every organizational surface at maximum intensity.
    property bool immersive: false

    // animate page changes (fade + drift) instead of hard switches
    property bool pageAnim: true

    // paint the app from the playing cover's palette; off = the neutral
    // grey room regardless of art
    property bool albumColors: true

    // settings depth: simple = every feature is one best-default switch;
    // advanced additionally reveals the fine controls behind each switch
    property bool advancedSettings: false

    // rating systems — each can be switched off app-wide in Settings
    property bool heartsOn: true    // ♥ like / 💔 dislike

    // extra shuffle placements: "off" | "menu" (right-click) | "bar" (also
    // in the shuffle button's click cycle)
    property string shuffleAlbumOpt: "off"
    property string shuffleGenreOpt: "off"

    // UI prefs survive restarts under the application settings owner.
    Settings {
        category: "ui"
        property alias pageAnim: t.pageAnim
        property alias albumColors: t.albumColors
        property alias advancedSettings: t.advancedSettings
        property alias heartsOn: t.heartsOn
        property alias shuffleAlbumOpt: t.shuffleAlbumOpt
        property alias shuffleGenreOpt: t.shuffleGenreOpt
    }

    readonly property color artVivid: (albumColors && backend.artColors && backend.artColors[0]) || "#8f8f97"
    readonly property color artMuted: (albumColors && backend.artColors && backend.artColors[1]) || "#5a5a62"

    // ---- targets: instant recompute per song (hslHue is -1 for achromatic) ----
    readonly property real _hT: { var h = Qt.color(artVivid).hslHue; return h < 0 ? 0.65 : h }
    readonly property real _sT: Math.max(0.30, Math.min(0.68, Qt.color(artVivid).hslSaturation))
    readonly property real _lT: Math.max(0, Math.min(1, Qt.color(artVivid).hslLightness))
    readonly property real _sFullT: Math.max(0, Qt.color(artVivid).hslSaturation)
    // Black, white, and genuinely grayscale covers do not carry a meaningful
    // hue. They use Ampere's white ink as the accent instead of allowing the
    // hue fallback plus saturation floor to invent a color.
    function _isAchromatic(c) {
        return Qt.color(c).hslSaturation < 0.12
    }
    readonly property real _achromaticT: _isAchromatic(artVivid) ? 1 : 0

    // ---- the eased engine: one clock for all four channels ----
    readonly property int themeMs: 1200

    // hue rides an UNWRAPPED accumulator so 0.95 -> 0.05 travels the short
    // arc through 1.0; hue() takes the fract, and the _snap renormalize is
    // fract-identical so it can never flash
    property real _h: 0.65
    property bool _snap: false
    Behavior on _h {
        enabled: !t._snap
        NumberAnimation { duration: t.themeMs; easing.type: Easing.InOutSine }
    }
    property real _s: _sT
    Behavior on _s { NumberAnimation { duration: t.themeMs; easing.type: Easing.InOutSine } }
    property real _l: _lT
    Behavior on _l { NumberAnimation { duration: t.themeMs; easing.type: Easing.InOutSine } }
    property real _sFull: _sFullT
    Behavior on _sFull { NumberAnimation { duration: t.themeMs; easing.type: Easing.InOutSine } }
    property real _achromatic: _achromaticT
    Behavior on _achromatic { NumberAnimation { duration: t.themeMs; easing.type: Easing.InOutSine } }

    function hue(off) { var h = _h + (off || 0); return h - Math.floor(h) }

    on_HTChanged: {
        var cur = _h - Math.floor(_h)
        var d = _hT - cur
        if (d > 0.5) d -= 1
        else if (d < -0.5) d += 1
        _snap = true; _h = cur; _snap = false
        _h = cur + d
    }
    Component.onCompleted: { _snap = true; _h = _hT; _snap = false }

    function mix(a, b, k) {
        a = Qt.color(a); b = Qt.color(b)
        return Qt.rgba(a.r * (1 - k) + b.r * k,
                       a.g * (1 - k) + b.g * k,
                       a.b * (1 - k) + b.b * k, 1)
    }
    function _albumPrimary(chromaticPrimary, achromaticWeight) {
        return mix(chromaticPrimary, text, achromaticWeight)
    }

    // ---- WCAG plumbing: lightness moves until the ratio clears ----
    function _lum(c) {
        function f(u) { return u <= 0.04045 ? u / 12.92 : Math.pow((u + 0.055) / 1.055, 2.4) }
        return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
    }
    function _ratio(a, b) {
        var la = _lum(a), lb = _lum(b)
        if (la < lb) { var tmp = la; la = lb; lb = tmp }
        return (la + 0.05) / (lb + 0.05)
    }
    // lighten (h,s,l) until it reads against EVERY base at >= target
    function _reach(h, s, l, bases, target) {
        var c = Qt.hsla(h, s, l, 1)
        for (var i = 0; i < 30; i++) {
            var worst = 99
            for (var j = 0; j < bases.length; j++) {
                var r = _ratio(c, bases[j])
                if (r < worst) worst = r
            }
            if (worst >= target) break
            l = Math.min(1, l + 0.02)
            c = Qt.hsla(h, s, l, 1)
        }
        return c
    }
    // darken a surface until fixed near-white text reads on it
    function _reachDown(h, s, l, fg, target) {
        var c = Qt.hsla(h, s, l, 1)
        for (var i = 0; i < 30 && _ratio(fg, c) < target; i++) {
            l = Math.max(0, l - 0.02)
            c = Qt.hsla(h, s, l, 1)
        }
        return c
    }

    // ---- derived tokens (all eased via _h/_s/_l/_sFull) ----
    // The room's dynamic range follows the album color's own brightness:
    // luminous covers get a glowing top, dark covers stay subdued — but the
    // top is darkened as far as body text needs.
    // Utility rooms still belong to the playing record.  Earlier revisions
    // reduced the album signal so far that the library read as generic grey.
    // Keep the shell calm, but let the cover act as ambient light everywhere.
    readonly property real roomS: immersive ? _s : _s * 0.34
    readonly property color bg:     Qt.hsla(hue(), roomS * 0.62, 0.14 + 0.045 * _l, 1)
    readonly property color bgHigh: _reachDown(hue(), roomS * 0.78, 0.19 + (immersive ? 0.22 : 0.08) * _l, text, 4.5)
    readonly property color bgLow:  Qt.hsla(hue(), roomS * 0.58, 0.105 + 0.04 * _l, 1)
    readonly property color surface:        Qt.hsla(hue(), roomS * 0.6, 0.185, 1)
    readonly property color surfaceVariant: Qt.hsla(hue(), roomS * 0.62, 0.245, 1)
    readonly property color outline: _reach(hue(), roomS * 0.66, 0.38, [bg], 3.0)
    readonly property color text: "#f4f1f6"
    readonly property color textDim: _reach(hue(), _s * 0.3, 0.79, [bgHigh, surfaceVariant], 4.5)

    // accent: the vivid art color pushed into the readable band — readable
    // by LUMINANCE (a saturated blue at HSL-L 0.58 is perceptually dark),
    // and against every surface it can sit on
    readonly property color _chromaticPrimary:
        _reach(hue(), Math.max(0.55, _sFull), Math.min(0.72, Math.max(0.58, _l)),
               [bg, surfaceVariant, bgHigh], 4.5)
    readonly property color primary: _albumPrimary(_chromaticPrimary, _achromatic)
    readonly property color secondary: _reach(hue(0.07), 0.4, 0.66, [bg, surfaceVariant, bgHigh], 4.5)
    readonly property color tertiary:  _reach(hue(0.5), 0.45, 0.62, [bg, surfaceVariant, bgHigh], 4.5)
    readonly property color error: "#ff5c8a"
    readonly property color inkOnPrimary: "#14100a"

    // Semantic shell surfaces. These deliberately change far less than the
    // album room so navigation retains a stable visual home.
    readonly property color navSurface: Qt.hsla(hue(), roomS * 0.30, 0.105, 1)
    readonly property color raisedSurface: Qt.hsla(hue(), roomS * 0.42, 0.225, 1)
    readonly property color hoverSurface: Qt.alpha(primary, 0.075)
    readonly property color divider: Qt.alpha(text, 0.10)
    readonly property color textMuted: Qt.alpha(text, 0.72)
    readonly property color textSubtle: Qt.alpha(text, 0.48)

    // the vivid art color itself, reconstructed from the eased channels —
    // for gradient mixes that would otherwise snap on song change
    readonly property color artVividEased: Qt.hsla(hue(), _sFull, _l, 1)

    readonly property string font: "Inter"
    readonly property string displayFont: "Rajdhani"

    // ---- Archive Wash ink set (locked visual system — design/SPEC.md) ----
    // Warm-neutral inks that sit on the washed album room (L.01 mockup hexes).
    // The accent on wash surfaces stays the adaptive `primary`.
    // Inks brightened + type scaled 125% per Iann's dialed legibility
    // numbers (2026-08-01 playground: veil 0.91 · text 125% · bleed 0.09).
    readonly property color washInk: "#f4f0ea"
    readonly property color washMuted: "#c8bfb6"
    readonly property color washFaint: "#8f867f"
    readonly property color washHair: Qt.alpha("#ffffff", 0.12)
    // wash type scale (use these on wash surfaces, not raw sizes)
    readonly property int washMicro: 12      // was 10 — caps/eyebrows/tabs
    readonly property int washLabel: 13      // small captions
    readonly property int washBody: 16       // card/row titles (was 13)
    readonly property int washSub: 12        // sublines (was 10)

    // ---- scales ----
    readonly property int radiusSm: 6
    readonly property int radius: 10
    readonly property int radiusLg: 14

    // Signal Room composition tokens.  Broad planes and aligned whitespace
    // carry hierarchy; outlines and pills are reserved for actual controls.
    readonly property int spaceXs: 4
    readonly property int spaceSm: 8
    readonly property int spaceMd: 16
    readonly property int spaceLg: 24
    readonly property int spaceXl: 32
    readonly property int space2xl: 48
    readonly property int pagePad: 32

    // Protected wordmark band (SPEC.md · Now Playing: "The AMPERE wordmark
    // stays fully visible in a protected top band"). WhisperRail draws the
    // wordmark at x = max(34, w * 0.045), y = max(22, h * 0.032), 188 × 46,
    // so any page painting its own breadcrumb/title must start below and
    // inside it. These are the shipped Open Shelves values (LibraryView,
    // SHIPPED 2026-08-01) promoted to tokens so every room shares one
    // origin instead of each page inventing a margin.
    function pageGutter(w) { return w < 700 ? 66 : Math.max(78, w * 0.07) }
    // SPEC row 206 defines the origin as height x 0.11. The old `h < 620 ? 66`
    // clamp spent MORE than that on short windows — 66px of air in a 384px
    // room at the 720x480 floor — which is where pages ran out of height and
    // pushed their own controls into the player (ROADMAP 5.1, 2026-08-22).
    // This restores the spec formula with one absolute floor.
    function pageTop(h) { return Math.max(28, h * 0.11) }

    readonly property int railWidth: 192
    readonly property int headerHeight: 58
    readonly property int playerHeight: 96
    readonly property int motionFast: 160
    readonly property int motionPage: 220
    readonly property color planeQuiet: Qt.alpha(surface, 0.34)
    readonly property color planeRaised: Qt.alpha(raisedSurface, 0.72)
    readonly property color focusRing: primary

    // the 7-step type scale (do not add sizes outside it)
    // Alphabet-rail bucketing. Latin keeps its letter; every other script
    // gets its OWN bucket instead of being dumped in "#" with the numerals,
    // so a Cyrillic, Japanese, Chinese, Korean or Greek collection is
    // reachable from the rail rather than buried (Iann, 2026-08-21).
    function alphaBucket(text) {
        var s = String(text || "")
        if (!s.length) return "#"
        var c = s.charAt(0).toUpperCase()
        if (c >= "A" && c <= "Z") return c
        var u = s.charCodeAt(0)
        if (u >= 0x0400 && u <= 0x052F) return "\u0410"        // Cyrillic
        if (u >= 0x0370 && u <= 0x03FF) return "\u03A9"        // Greek
        if (u >= 0x3040 && u <= 0x30FF) return "\u3042"        // kana
        if (u >= 0x1100 && u <= 0x11FF) return "\uD55C"        // Hangul jamo
        if (u >= 0xAC00 && u <= 0xD7AF) return "\uD55C"        // Hangul
        if ((u >= 0x3400 && u <= 0x4DBF) || (u >= 0x4E00 && u <= 0x9FFF)
            || (u >= 0xF900 && u <= 0xFAFF)) return "\u4E2D"   // Han
        if (u >= 0x0590 && u <= 0x05FF) return "\u05D0"        // Hebrew
        if (u >= 0x0600 && u <= 0x06FF) return "\u0627"        // Arabic
        return "#"
    }

    readonly property int fsMicro: 11
    readonly property int fsSmall: 13
    readonly property int fsBody: 15
    readonly property int fsEmph: 18
    readonly property int fsTitle: 24
    readonly property int fsStat: 32
    readonly property int fsHero: 44

    function glow(c, strength) { return Qt.alpha(c, strength === undefined ? 0.35 : strength) }
    function fmtTime(s) {
        s = Math.max(0, Math.round(s))
        var m = Math.floor(s / 60)
        var sec = s % 60
        return m + ":" + (sec < 10 ? "0" : "") + sec
    }
}
