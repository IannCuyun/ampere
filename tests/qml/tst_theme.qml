import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "AdaptiveAlbumTheme"
    when: windowShown
    visible: true
    width: 320
    height: 240

    function colorDistance(a, b) {
        return Math.max(Math.abs(a.r - b.r),
                        Math.abs(a.g - b.g),
                        Math.abs(a.b - b.b))
    }

    function test_achromaticArtUsesWhiteWhileChromaticArtKeepsItsHue() {
        Theme.albumColors = true
        verify(Theme._isAchromatic("#000000"))
        verify(Theme._isAchromatic("#ffffff"))
        verify(Theme._isAchromatic("#797979"))
        verify(!Theme._isAchromatic("#b24c42"))

        var chromatic = Qt.color("#b24c42")
        var neutralPrimary = Theme._albumPrimary(chromatic, 1)
        var chromaticPrimary = Theme._albumPrimary(chromatic, 0)
        verify(colorDistance(neutralPrimary, Theme.text) < 0.005)
        verify(colorDistance(chromaticPrimary, Theme.text) > 0.08)

        // With no application backend the singleton uses its grayscale
        // no-art fallback, which must resolve through the same white path.
        wait(Theme.themeMs + 100)
        verify(colorDistance(Theme.primary, Theme.text) < 0.005)
    }
}
