import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "EqReferenceRoomGeometry"
    when: windowShown
    visible: true
    width: 1904
    height: 1019

    property var eq: provider

    QtObject {
        id: provider
        property var bands: [
            {node: "ls", type: "LS", freq: 80, gain: 0, q: 0.71},
            {node: "p1", type: "PK", freq: 64, gain: 0, q: 1.0},
            {node: "p2", type: "PK", freq: 125, gain: 0, q: 1.0},
            {node: "p3", type: "PK", freq: 250, gain: 0, q: 1.0},
            {node: "p4", type: "PK", freq: 500, gain: 0, q: 1.0},
            {node: "p5", type: "PK", freq: 1000, gain: 0, q: 1.0},
            {node: "p6", type: "PK", freq: 2000, gain: 0, q: 1.0},
            {node: "p7", type: "PK", freq: 4000, gain: 0, q: 1.0},
            {node: "p8", type: "PK", freq: 8000, gain: 0, q: 1.0},
            {node: "hs", type: "HS", freq: 10000, gain: 0, q: 0.71}
        ]
        property string sinkLabel: "M Series Line Out"
        property bool enabled: true
        property bool dirty: false
        property var variants: ["Default"]
        property string activeVariant: "Default"
        property var presetNames: []
        property real toneBass: 0
        property real toneTreble: 0
        property real balance: 0
        property real preamp: 0
        property var lastBand: ({})
        property int bandSetCount: 0
        property real lastBass: 0
        property real lastTreble: 0
        property real lastBalance: 0
        property real lastPreamp: 0
        signal changed()
        signal deviceChanged()
        function responseCurve(count) {
            var result = []
            for (var i = 0; i < count; ++i)
                result.push(0)
            return result
        }
        function setEnabled(value) {}
        function addBand() {}
        function removeBand(index) {}
        function applyPreset(name) {}
        function importAutoEq(text) {}
        function saveProfile() {}
        function selectVariant(name) {}
        function newVariant(name) {}
        function deleteVariant(name) {}
        function setToneBass(value) { lastBass = value }
        function setToneTreble(value) { lastTreble = value }
        function setBalance(value) { lastBalance = value }
        function setPreamp(value) { lastPreamp = value }
        function setBand(index, frequency, gain, q) {
            lastBand = {index: index, frequency: frequency, gain: gain, q: q}
            bandSetCount += 1
        }
    }

    EqView {
        id: view
        parent: testCase
        width: testCase.width
        // Main owns Pocket Horizon and gives pages only the player-safe room.
        height: testCase.height - Theme.playerHeight
    }

    function init() {
        testCase.width = 1904
        testCase.height = 1019
        view.selBand = 1
        view.hoveredFrequencyRegion = -1
        view.pinnedFrequencyRegion = -1
        provider.lastBand = ({})
        provider.bandSetCount = 0
        provider.lastBass = 0
        provider.lastBalance = 0
        wait(0)
    }

    function test_flat_band_handles_share_the_response_centerline() {
        wait(0)
        const plot = findChild(view, "eqCurvePlot")
        const first = findChild(view, "eqCurveHandle_0")
        const last = findChild(view, "eqCurveHandle_9")
        verify(plot !== null && first !== null && last !== null)
        const expected = plot.mapToItem(view, 0, plot.padT + plot.plotH / 2).y
        const firstCenter = first.mapToItem(view, first.width / 2, first.height / 2).y
        const lastCenter = last.mapToItem(view, last.width / 2, last.height / 2).y
        fuzzyCompare(firstCenter, expected, 1)
        fuzzyCompare(lastCenter, expected, 1)
    }

    function test_compact_room_keeps_the_full_ledger_in_its_first_surface() {
        testCase.width = 720
        testCase.height = 480
        wait(0)
        const room = findChild(view, "eqReferenceRoom")
        const ledger = findChild(view, "eqBandLedger")
        const last = findChild(view, "eqCurveHandle_9")
        verify(room !== null && ledger !== null && last !== null)
        compare(ledger.width, 128)
        verify(room.height >= 328)
        const plot = findChild(view, "eqCurvePlot")
        verify(plot !== null)
        compare(plot.frequencyTicks.length, 25)
        compare(plot.labelEveryFrequency, false)
    }

    function test_response_display_gives_six_db_one_quarter_of_plot_height() {
        const plot = findChild(view, "eqCurvePlot")
        verify(plot !== null)
        fuzzyCompare(plot.gy(0) - plot.gy(6), plot.plotH / 4, 1)
        compare(view.displayDbRange, 12)
        compare(view.editDbLimit, 18)
    }

    function test_frequency_ticks_match_reference_and_keep_log_spacing() {
        const plot = findChild(view, "eqCurvePlot")
        verify(plot !== null)
        const expected = [20, 30, 40, 50, 60, 80, 100, 150, 200, 300,
                          400, 500, 600, 800, 1000, 1500, 2000, 3000,
                          4000, 5000, 6000, 8000, 10000, 15000, 20000]
        compare(plot.frequencyTicks.length, expected.length)
        for (var i = 0; i < expected.length; ++i)
            compare(plot.frequencyTicks[i].frequency, expected[i])
        fuzzyCompare(plot.fx(200) - plot.fx(20),
                     plot.fx(2000) - plot.fx(200), 0.01)
        fuzzyCompare(plot.fx(2000) - plot.fx(200),
                     plot.fx(20000) - plot.fx(2000), 0.01)
        compare(plot.labelEveryFrequency, true)
    }

    function test_frequency_regions_match_reference_and_highlight_exact_span() {
        const expected = [[20, 80], [80, 300], [300, 1000], [1000, 6000],
                          [6000, 10000], [10000, 20000]]
        compare(view.frequencyRegions.length, expected.length)
        for (var i = 0; i < expected.length; ++i) {
            compare(view.frequencyRegions[i].start, expected[i][0])
            compare(view.frequencyRegions[i].end, expected[i][1])
        }
        compare(view.frequencyRegionFor(79.9), 0)
        compare(view.frequencyRegionFor(80), 1)
        compare(view.frequencyRegionFor(300), 2)
        compare(view.frequencyRegionFor(1000), 3)
        compare(view.frequencyRegionFor(6000), 4)
        compare(view.frequencyRegionFor(10000), 5)

        const plot = findChild(view, "eqCurvePlot")
        const highlight = findChild(view, "eqFrequencyRegionHighlight")
        const description = findChild(view, "eqFrequencyRegionDescriptionText")
        verify(plot !== null && highlight !== null && description !== null)
        compare(view.activeFrequencyRegion, 0)
        fuzzyCompare(highlight.x, plot.fx(20), 0.01)
        fuzzyCompare(highlight.width, plot.fx(80) - plot.fx(20), 0.01)
        verify(description.text.indexOf("Rumble") >= 0)

        const upperMid = findChild(view, "eqFrequencyRegion_3")
        verify(upperMid !== null)
        upperMid.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(view.pinnedFrequencyRegion, 3)
        compare(view.activeFrequencyRegion, 3)
        fuzzyCompare(highlight.x, plot.fx(1000), 0.01)
        fuzzyCompare(highlight.width, plot.fx(6000) - plot.fx(1000), 0.01)
        verify(description.text.indexOf("Presence") >= 0)

        keyClick(Qt.Key_Return)
        compare(view.pinnedFrequencyRegion, -1)
        compare(view.activeFrequencyRegion, 3)
        upperMid.focus = false
        wait(0)
        compare(view.activeFrequencyRegion, 0)

        view.selBand = 2
        compare(view.activeFrequencyRegion, 1)
    }

    function test_peq_type_roles_promote_without_crowding_compact() {
        const desktopGain = findChild(view, "eqBandGain_2")
        const desktopTone = findChild(view, "eqToneValue_bass")
        const description = findChild(view, "eqFrequencyRegionDescriptionText")
        verify(desktopGain !== null && desktopTone !== null && description !== null)
        compare(view.eqDataTextSize, Theme.fsBody)
        compare(view.eqSupportTextSize, Theme.fsSmall)
        compare(desktopGain.textSize, Theme.fsBody)
        compare(desktopGain.suffixTextSize, Theme.fsSmall)
        compare(desktopTone.font.pixelSize, Theme.fsSmall)
        compare(description.font.pixelSize, Theme.fsSmall)

        testCase.width = 720
        testCase.height = 480
        wait(0)
        const compactFrequency = findChild(view, "eqCompactBandFrequency_2")
        const room = findChild(view, "eqReferenceRoom")
        const plot = findChild(view, "eqCurvePlot")
        verify(compactFrequency !== null && room !== null && plot !== null)
        compare(view.eqDataTextSize, Theme.fsSmall)
        compare(view.eqSupportTextSize, Theme.washMicro)
        compare(compactFrequency.textSize, Theme.fsSmall)
        compare(compactFrequency.suffixTextSize, Theme.washMicro)
        compare(description.font.pixelSize, Theme.washMicro)
        verify(room.height >= 328)
        verify(plot.width > 0 && plot.height > 0)
    }

    function test_band_values_commit_direct_text_and_invalid_text_reverts() {
        const gainField = findChild(view, "eqBandGain_2")
        verify(gainField !== null)
        mouseClick(gainField.editor,
                   gainField.editor.width / 2, gainField.editor.height / 2)
        verify(gainField.editor.activeFocus)
        gainField.editor.text = "+4.5"
        gainField.editor.editingFinished()
        compare(provider.lastBand.index, 2)
        fuzzyCompare(provider.lastBand.gain, 4.5, 0.001)
        wait(0)

        const calls = provider.bandSetCount
        gainField.editor.text = "not a number"
        gainField.editor.editingFinished()
        compare(provider.bandSetCount, calls)
        compare(gainField.editor.text, "+0.00")
    }

    function test_slider_readout_commits_direct_text() {
        const bassField = findChild(view, "eqToneValue_bass")
        verify(bassField !== null)
        mouseClick(bassField, bassField.width / 2, bassField.height / 2)
        verify(bassField.activeFocus)
        bassField.text = "+3.5 dB"
        bassField.editingFinished()
        fuzzyCompare(provider.lastBass, 3.5, 0.001)
        compare(bassField.text, "+0.0 dB")
    }

    function test_balance_slider_and_text_use_signed_percentage_scale() {
        const balanceSlider = findChild(view, "eqToneSlider_balance")
        const balanceField = findChild(view, "eqToneValue_balance")
        verify(balanceSlider !== null && balanceField !== null)
        compare(balanceSlider.from, -100)
        compare(balanceSlider.to, 100)
        fuzzyCompare(balanceSlider.value, 0, 0.001)
        compare(balanceField.text, "0%")

        mouseClick(balanceField,
                   balanceField.width / 2, balanceField.height / 2)
        verify(balanceField.activeFocus)
        balanceField.text = "-3"
        balanceField.editingFinished()
        fuzzyCompare(provider.lastBalance, -0.03, 0.001)
        wait(0)

        mouseClick(balanceField,
                   balanceField.width / 2, balanceField.height / 2)
        balanceField.text = "-3%"
        balanceField.editingFinished()
        fuzzyCompare(provider.lastBalance, -0.03, 0.001)
        wait(0)

        provider.balance = 1
        wait(0)
        fuzzyCompare(balanceSlider.value, 100, 0.001)
        compare(balanceField.text, "100%")
        provider.balance = -1
        wait(0)
        fuzzyCompare(balanceSlider.value, -100, 0.001)
        compare(balanceField.text, "-100%")
        provider.balance = 0
    }
}
