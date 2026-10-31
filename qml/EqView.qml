import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Reference Room: a persistent band instrument beside one dominant response
// stage. The view owns presentation and interaction only; `eq` remains the
// single owner of audio state, persistence, variants, and device changes.
Item {
    id: view

    property var localBands: eq.bands
    property bool dragging: false
    property int selBand: 1
    property bool freqLock: false
    property int hoveredFrequencyRegion: -1
    property int pinnedFrequencyRegion: -1
    readonly property bool compact: width < 760
    readonly property real displayDbRange: 12.0
    readonly property real editDbLimit: 18.0
    readonly property int eqDataTextSize:
        compact ? Theme.fsSmall : Theme.fsBody
    readonly property int eqSupportTextSize:
        compact ? Theme.washMicro : Theme.fsSmall
    readonly property var selectedBand: localBands[selBand] || ({})
    readonly property var frequencyRegions: [
        {
            name: "Sub bass", shortName: "SUB", start: 20, end: 80,
            description: "Rumble, depth, and low-end growl."
        },
        {
            name: "Mid bass", shortName: "MID BASS", start: 80, end: 300,
            description: "Punch, impact, and rhythmic weight."
        },
        {
            name: "Lower midrange", shortName: "LOW MID", start: 300, end: 1000,
            description: "Note body and richness. Too much muddies; too little thins."
        },
        {
            name: "Upper midrange", shortName: "UPPER MID", start: 1000, end: 6000,
            description: "Presence and harmonics. Too much shouts; too little dulls."
        },
        {
            name: "Treble", shortName: "TREBLE", start: 6000, end: 10000,
            description: "Sparkle, edge, and sibilance. More reads bright; less reads dark."
        },
        {
            name: "Air", shortName: "AIR", start: 10000, end: 20000,
            description: "Upper harmonics, openness, and fine detail."
        }
    ]
    readonly property int selectedFrequencyRegion:
        frequencyRegionFor(Number(selectedBand.freq) || 20)
    readonly property int activeFrequencyRegion:
        hoveredFrequencyRegion >= 0 ? hoveredFrequencyRegion
        : (pinnedFrequencyRegion >= 0 ? pinnedFrequencyRegion
                                      : selectedFrequencyRegion)
    readonly property var activeRegion:
        frequencyRegions[activeFrequencyRegion] || frequencyRegions[0]

    onSelBandChanged: pinnedFrequencyRegion = -1

    onLocalBandsChanged: {
        if (selBand >= localBands.length)
            selBand = Math.max(0, localBands.length - 1)
    }

    Connections {
        target: eq
        function onChanged() {
            if (!view.dragging)
                view.localBands = eq.bands
            canvas.requestPaint()
        }
        function onDeviceChanged() {
            view.localBands = eq.bands
            canvas.requestPaint()
        }
    }

    function typeColor(type) {
        return type === "LS" ? Theme.secondary
             : type === "HS" ? Theme.tertiary : Theme.primary
    }

    function bandFrequency(band) {
        return band.freq !== undefined ? Math.round(band.freq) : 0
    }

    function bandGain(band) {
        if (band.gain === undefined)
            return "+0.00"
        return (band.gain >= 0 ? "+" : "") + band.gain.toFixed(2)
    }

    function bandTypeLabel(type) {
        return type === "LS" ? "Low shelf"
             : type === "HS" ? "High shelf" : "Bell"
    }

    function frequencyRegionFor(frequency) {
        for (var i = 0; i < frequencyRegions.length; ++i) {
            if (frequency < frequencyRegions[i].end
                    || i === frequencyRegions.length - 1)
                return i
        }
        return frequencyRegions.length - 1
    }

    function frequencyLabel(frequency) {
        if (frequency >= 1000)
            return (frequency / 1000) + " kHz"
        return frequency + " Hz"
    }

    function regionRangeLabel(region) {
        return frequencyLabel(region.start) + "–" + frequencyLabel(region.end)
    }

    component ValueField: Item {
        id: valueRoot
        property string val: ""
        property string suffix: ""
        property string accessibleName: "Value"
        property int textSize: view.eqDataTextSize
        property int suffixTextSize: view.eqSupportTextSize
        property alias editor: field
        property bool finishingEdit: false
        signal committed(real value)

        implicitWidth: 76
        implicitHeight: 30
        onValChanged: if (!field.activeFocus) field.text = val

        TextField {
            id: field
            anchors.fill: parent
            anchors.rightMargin: suffixLabel.visible ? suffixLabel.width + 6 : 0
            leftPadding: 2
            rightPadding: 2
            background: null
            color: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: valueRoot.textSize
            horizontalAlignment: TextInput.AlignRight
            text: valueRoot.val
            selectByMouse: true
            Accessible.name: valueRoot.accessibleName
            onEditingFinished: {
                if (valueRoot.finishingEdit)
                    return
                valueRoot.finishingEdit = true
                var parsed = parseFloat(text)
                if (!isNaN(parsed))
                    valueRoot.committed(parsed)
                text = valueRoot.val
                focus = false
                Qt.callLater(function() { valueRoot.finishingEdit = false })
            }
            Keys.onEscapePressed: {
                valueRoot.finishingEdit = true
                text = valueRoot.val
                focus = false
                Qt.callLater(function() { valueRoot.finishingEdit = false })
            }
            onActiveFocusChanged: if (activeFocus) selectAll()
        }

        Text {
            id: suffixLabel
            visible: text !== ""
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: valueRoot.suffix
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: valueRoot.suffixTextSize
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: field.activeFocus ? Theme.focusRing : Theme.washHair
        }
    }

    component MetricField: Item {
        id: metricRoot
        property string label: ""
        property string val: ""
        property string suffix: ""
        property string accessibleName: label
        signal committed(real value)

        implicitHeight: 52

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            text: metricRoot.label
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 1.6
        }
        ValueField {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            val: metricRoot.val
            suffix: metricRoot.suffix
            accessibleName: metricRoot.accessibleName
            onCommitted: value => metricRoot.committed(value)
        }
    }

    component ToneSlider: Item {
        id: toneRoot
        property string name: ""
        property real val: 0
        property real lo: -8
        property real hi: 8
        property string fmt: "dB"
        property alias editor: toneValue
        property bool finishingEdit: false
        signal moved(real value)
        signal committed(real value)

        function displayValue() {
            if (fmt === "dB")
                return (val >= 0 ? "+" : "") + val.toFixed(1) + " dB"
            if (Math.abs(val) < 0.5)
                return "0%"
            return Math.round(val) + "%"
        }

        function parseValue(raw) {
            var clean = raw.trim().toLowerCase()
            if (fmt === "bal") {
                if (clean === "center" || clean === "centre")
                    return 0
                var direction = clean.charAt(0)
                var parsedBalance = parseFloat(clean.replace(/[^0-9.+-]/g, ""))
                if (isNaN(parsedBalance))
                    return NaN
                if (direction === "l")
                    parsedBalance = -Math.abs(parsedBalance)
                else if (direction === "r")
                    parsedBalance = Math.abs(parsedBalance)
                return parsedBalance
            }
            return parseFloat(clean)
        }

        function finishEdit() {
            if (finishingEdit)
                return
            finishingEdit = true
            var parsed = parseValue(toneValue.text)
            if (!isNaN(parsed))
                committed(Math.max(lo, Math.min(hi, parsed)))
            toneValue.text = displayValue()
            toneValue.focus = false
            Qt.callLater(function() { toneRoot.finishingEdit = false })
        }

        onValChanged: if (!toneValue.activeFocus)
                          toneValue.text = displayValue()

        implicitWidth: 250
        implicitHeight: 40

        Text {
            id: toneLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 66
            text: toneRoot.name
            color: Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 2
            font.capitalization: Font.AllUppercase
        }

        AmpereSlider {
            id: toneSlider
            objectName: "eqToneSlider_" + toneRoot.name.toLowerCase()
            anchors.left: toneLabel.right
            anchors.right: toneValue.left
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            from: toneRoot.lo
            to: toneRoot.hi
            accent: Theme.secondary
            Accessible.name: toneRoot.name
            onMoved: toneRoot.moved(value)
            Binding {
                target: toneSlider
                property: "value"
                value: toneRoot.val
                when: !toneSlider.pressed
            }
        }

        TextField {
            id: toneValue
            objectName: "eqToneValue_" + toneRoot.name.toLowerCase()
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 64
            leftPadding: 1
            rightPadding: 1
            background: null
            horizontalAlignment: TextInput.AlignRight
            text: toneRoot.displayValue()
            color: activeFocus ? Theme.washInk : Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            selectByMouse: true
            Accessible.name: toneRoot.name + " direct value"
            onEditingFinished: toneRoot.finishEdit()
            Keys.onEscapePressed: {
                toneRoot.finishingEdit = true
                text = toneRoot.displayValue()
                focus = false
                Qt.callLater(function() { toneRoot.finishingEdit = false })
            }
            onActiveFocusChanged: if (activeFocus) selectAll()

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: toneValue.activeFocus ? Theme.focusRing : Theme.washHair
            }
        }
    }

    component VariantCreator: Item {
        id: variantRoot
        property bool expanded: false
        implicitWidth: expanded ? 132 : 34
        implicitHeight: 36

        TextField {
            id: newVariant
            anchors.left: parent.left
            anchors.right: variantAction.left
            anchors.verticalCenter: parent.verticalCenter
            visible: variantRoot.expanded
            background: null
            color: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: Theme.fsSmall
            placeholderText: "name"
            Accessible.name: "New profile variant name"
            placeholderTextColor: Theme.washFaint
            onAccepted: {
                if (text)
                    eq.newVariant(text)
                text = ""
                variantRoot.expanded = false
            }
        }

        Rectangle {
            visible: variantRoot.expanded
            anchors.left: parent.left
            anchors.right: variantAction.left
            anchors.bottom: parent.bottom
            height: 1
            color: newVariant.activeFocus ? Theme.focusRing : Theme.washHair
        }

        Icon {
            id: variantAction
            color: activeFocus ? Theme.primary : Theme.washMuted
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            name: variantRoot.expanded ? "check" : "plus"
            size: 16
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: variantRoot.expanded
                ? "Save profile variant" : "Add profile variant"

            function activate() {
                if (variantRoot.expanded && newVariant.text) {
                    eq.newVariant(newVariant.text)
                    newVariant.text = ""
                }
                variantRoot.expanded = !variantRoot.expanded
                if (variantRoot.expanded)
                    newVariant.forceActiveFocus()
            }

            Accessible.onPressAction: activate()
            Keys.onReturnPressed: activate()
            Keys.onSpacePressed: activate()
            MouseArea {
                anchors.fill: parent
                anchors.margins: -10
                cursorShape: Qt.PointingHandCursor
                onClicked: variantAction.activate()
            }
        }
    }

    component BandLedgerRow: Rectangle {
        id: ledgerRow
        required property int index
        readonly property var band: view.localBands[index] || ({})
        readonly property bool selected: view.selBand === index
        property bool compactMode: false

        height: compactMode ? 24 : 40
        color: selected ? Qt.alpha(Theme.primary, 0.11)
             : rowHover.hovered ? Theme.hoverSurface : "transparent"
        border.color: "transparent"
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Band " + (index + 1) + ", " + (band.type || "")
        Accessible.onPressAction: view.selBand = index
        Keys.onReturnPressed: view.selBand = index
        Keys.onSpacePressed: view.selBand = index

        Rectangle {
            visible: ledgerRow.selected
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 3
            color: view.typeColor(ledgerRow.band.type)
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.washHair
        }

        Text {
            id: bandNumber
            anchors.left: parent.left
            anchors.leftMargin: compactMode ? 6 : 10
            anchors.verticalCenter: parent.verticalCenter
            width: compactMode ? 20 : 30
            text: String(index + 1).padStart(2, "0")
            color: ledgerRow.selected ? Theme.primary : Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: compactMode ? Theme.fsSmall : Theme.fsBody
            font.letterSpacing: 1
        }

        Text {
            id: bandType
            anchors.left: bandNumber.right
            anchors.verticalCenter: parent.verticalCenter
            width: compactMode ? 24 : 78
            text: compactMode ? (ledgerRow.band.type || "")
                              : view.bandTypeLabel(ledgerRow.band.type)
            color: ledgerRow.selected
                ? view.typeColor(ledgerRow.band.type) : Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: compactMode ? Theme.fsSmall : Theme.fsBody
        }

        ValueField {
            visible: compactMode
            objectName: "eqCompactBandFrequency_" + index
            anchors.left: bandType.right
            anchors.right: parent.right
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            height: 22
            val: String(view.bandFrequency(ledgerRow.band))
            suffix: "Hz"
            textSize: Theme.fsSmall
            suffixTextSize: Theme.washMicro
            accessibleName: "Band " + (index + 1) + " frequency"
            onCommitted: value => {
                view.selBand = ledgerRow.index
                eq.setBand(ledgerRow.index, value,
                           ledgerRow.band.gain, ledgerRow.band.q)
            }
        }

        RowLayout {
            visible: !compactMode
            anchors.left: bandType.right
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            ValueField {
                objectName: "eqBandFrequency_" + index
                Layout.fillWidth: true
                val: String(view.bandFrequency(ledgerRow.band))
                suffix: "Hz"
                accessibleName: "Band " + (index + 1) + " frequency"
                onCommitted: value => {
                    view.selBand = ledgerRow.index
                    eq.setBand(ledgerRow.index, value,
                               ledgerRow.band.gain, ledgerRow.band.q)
                }
            }
            ValueField {
                objectName: "eqBandGain_" + index
                Layout.preferredWidth: 70
                val: view.bandGain(ledgerRow.band)
                suffix: "dB"
                accessibleName: "Band " + (index + 1) + " gain"
                onCommitted: value => {
                    view.selBand = ledgerRow.index
                    eq.setBand(ledgerRow.index, ledgerRow.band.freq,
                               value, ledgerRow.band.q)
                }
            }
            ValueField {
                objectName: "eqBandQ_" + index
                Layout.preferredWidth: 46
                val: ledgerRow.band.q !== undefined
                    ? ledgerRow.band.q.toFixed(2) : ""
                suffix: "Q"
                accessibleName: "Band " + (index + 1) + " Q"
                onCommitted: value => {
                    view.selBand = ledgerRow.index
                    eq.setBand(ledgerRow.index, ledgerRow.band.freq,
                               ledgerRow.band.gain, value)
                }
            }
        }

        HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: view.selBand = ledgerRow.index }
    }

    AmpereMenu {
        id: presetMenu
        options: eq.presetNames.map(name => ({id: name, label: name.toUpperCase()}))
        onPicked: id => eq.applyPreset(id)
    }

    Flickable {
        id: scroller
        objectName: "eqScroller"
        anchors.fill: parent
        anchors.leftMargin: view.compact ? 16 : Math.max(28, view.width * 0.025)
        anchors.rightMargin: anchors.leftMargin
        anchors.topMargin: Theme.pageTop(view.height)
        // Main's room already ends at the top edge of Pocket Horizon.
        // Reserve only breathing room here; subtracting playerHeight again
        // clips the compact ledger and collapses the response plot.
        anchors.bottomMargin: 12
        contentWidth: width
        contentHeight: col.height + 30
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: col
            width: scroller.width
            spacing: Theme.spaceMd

            Item {
                id: room
                objectName: "eqReferenceRoom"
                Layout.fillWidth: true
                Layout.preferredHeight: view.compact ? Math.max(328, scroller.height)
                                                     : Math.max(680, scroller.height - 12)

                RowLayout {
                    anchors.fill: parent
                    spacing: view.compact ? 16 : 32

                    Item {
                        id: consolePanel
                        objectName: "eqBandLedger"
                        Layout.preferredWidth: view.compact ? 128
                            : Math.min(372, Math.max(348, room.width * 0.22))
                        Layout.fillHeight: true

                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 1
                            color: Theme.washHair
                        }

                        Column {
                            id: consoleColumn
                            anchors.fill: parent
                            anchors.rightMargin: view.compact ? 8 : 24
                            spacing: view.compact ? 0 : 4

                            Item {
                                width: parent.width
                                height: view.compact ? 40 : 76
                                Text {
                                    visible: !view.compact
                                    anchors.left: parent.left
                                    anchors.top: parent.top
                                    text: "SOUND / PARAMETRIC"
                                    color: Theme.primary
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.washMicro
                                    font.letterSpacing: 2.4
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.top: parent.top
                                    anchors.topMargin: view.compact ? 0 : 20
                                    text: view.compact ? "PARAMETRIC EQ" : "Parametric EQ"
                                    color: Theme.washInk
                                    font.family: view.compact ? Theme.displayFont : Theme.font
                                    font.pixelSize: view.compact ? Theme.fsSmall : 30
                                    font.weight: view.compact ? Font.DemiBold : Font.Light
                                    font.letterSpacing: view.compact ? 1.2 : -0.7
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    elide: Text.ElideRight
                                    text: eq.sinkLabel
                                    color: Theme.washMuted
                                    font.family: Theme.font
                                    font.pixelSize: view.compact ? Theme.washSub : Theme.fsSmall
                                }
                            }

                            Row {
                                width: parent.width
                                height: view.compact ? 28 : 40
                                spacing: 20
                                WashLine {
                                    label: eq.enabled ? "EQ on" : "Bypassed"
                                    primaryAction: eq.enabled
                                    onActivated: eq.setEnabled(!eq.enabled)
                                }
                                WashLine {
                                    visible: eq.dirty
                                    label: "Save"
                                    primaryAction: true
                                    onActivated: eq.saveProfile()
                                }
                            }

                            Flow {
                                visible: !view.compact
                                width: parent.width
                                height: visible ? 44 : 0
                                spacing: 12
                                Text {
                                    height: 36
                                    verticalAlignment: Text.AlignVCenter
                                    text: "PROFILE"
                                    color: Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: Theme.washMicro
                                    font.letterSpacing: 2
                                }
                                Repeater {
                                    model: eq.variants
                                    delegate: WashLine {
                                        label: modelData
                                        primaryAction: modelData === eq.activeVariant
                                        onActivated: eq.selectVariant(modelData)
                                    }
                                }
                                VariantCreator { }
                                WashLine {
                                    visible: eq.variants.length > 1
                                    label: "Del"
                                    onActivated: eq.deleteVariant(eq.activeVariant)
                                }
                            }

                            Item {
                                width: parent.width
                                height: view.compact ? 18 : 24
                                Text {
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: view.compact ? "BANDS" : "#   BAND"
                                    color: Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: view.eqSupportTextSize
                                    font.letterSpacing: 1.5
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: view.compact ? "HZ" : "FREQUENCY       GAIN       Q"
                                    color: Theme.washFaint
                                    font.family: Theme.displayFont
                                    font.pixelSize: view.eqSupportTextSize
                                    font.letterSpacing: view.compact ? 0.4 : 0.8
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 1
                                    color: Theme.washHair
                                }
                            }

                            Column {
                                width: parent.width
                                Repeater {
                                    model: view.localBands.length
                                    delegate: BandLedgerRow {
                                        width: consoleColumn.width
                                        compactMode: view.compact
                                    }
                                }
                            }

                            GridLayout {
                                visible: !view.compact
                                width: parent.width
                                height: visible ? implicitHeight : 0
                                columns: 3
                                columnSpacing: 12
                                rowSpacing: 0

                                MetricField {
                                    Layout.fillWidth: true
                                    label: "FREQUENCY"
                                    accessibleName: "Selected band frequency"
                                    val: view.selectedBand.freq !== undefined
                                        ? String(Math.round(view.selectedBand.freq)) : ""
                                    suffix: "Hz"
                                    onCommitted: value => eq.setBand(
                                        view.selBand, value,
                                        view.selectedBand.gain, view.selectedBand.q)
                                }
                                MetricField {
                                    Layout.fillWidth: true
                                    label: "GAIN"
                                    accessibleName: "Selected band gain"
                                    val: view.bandGain(view.selectedBand)
                                    suffix: "dB"
                                    onCommitted: value => eq.setBand(
                                        view.selBand, view.selectedBand.freq,
                                        value, view.selectedBand.q)
                                }
                                MetricField {
                                    Layout.fillWidth: true
                                    label: "Q"
                                    accessibleName: "Selected band Q"
                                    val: view.selectedBand.q !== undefined
                                        ? view.selectedBand.q.toFixed(2) : ""
                                    suffix: "Q"
                                    onCommitted: value => eq.setBand(
                                        view.selBand, view.selectedBand.freq,
                                        view.selectedBand.gain, value)
                                }
                            }

                            Flow {
                                visible: !view.compact
                                width: parent.width
                                height: visible ? 88 : 0
                                spacing: 12
                                WashLine { label: "Add"; onActivated: eq.addBand() }
                                WashLine {
                                    label: "Remove"
                                    visible: (view.selectedBand.type || "") === "PK"
                                    onActivated: eq.removeBand(view.selBand)
                                }
                                WashLine {
                                    label: view.freqLock ? "Frequency locked" : "Frequency free"
                                    primaryAction: view.freqLock
                                    onActivated: view.freqLock = !view.freqLock
                                }
                                WashLine {
                                    label: "Import"
                                    primaryAction: importPanel.visible
                                    onActivated: importPanel.visible = !importPanel.visible
                                }
                                WashLine {
                                    id: desktopPresetAction
                                    label: "Presets"
                                    onActivated: presetMenu.popupAt(
                                        desktopPresetAction, 0, desktopPresetAction.height)
                                }
                            }
                        }
                    }

                    Item {
                        id: responseStage
                        objectName: "eqResponseStage"
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Item {
                            id: stageFrame
                            anchors.fill: parent
                            anchors.leftMargin: view.compact ? 0 : 8
                            anchors.rightMargin: view.compact ? 0 : 8

                            Item {
                                id: stageHeader
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: view.compact ? 54 : 76

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.bottomMargin: 8
                                    spacing: 16

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text {
                                            text: "RESPONSE / BAND "
                                                + String(view.selBand + 1).padStart(2, "0")
                                            color: Theme.primary
                                            font.family: Theme.displayFont
                                            font.pixelSize: Theme.washMicro
                                            font.letterSpacing: 2.2
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 12
                                            Text {
                                                text: view.bandFrequency(view.selectedBand) + " Hz"
                                                color: Theme.washInk
                                                font.family: Theme.font
                                                font.pixelSize: view.compact ? Theme.fsEmph : Theme.fsTitle
                                                font.weight: Font.Light
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                                text: view.bandTypeLabel(view.selectedBand.type)
                                                    + "  ·  " + view.bandGain(view.selectedBand)
                                                    + " dB  ·  Q "
                                                    + (view.selectedBand.q !== undefined
                                                       ? view.selectedBand.q.toFixed(2) : "0.00")
                                                color: Theme.washMuted
                                                font.family: Theme.font
                                                font.pixelSize: view.compact ? Theme.washSub : Theme.fsSmall
                                            }
                                        }
                                    }
                                    WashLine {
                                        label: view.freqLock ? "Frequency locked" : "Frequency free"
                                        primaryAction: view.freqLock
                                        onActivated: view.freqLock = !view.freqLock
                                    }
                                }

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 1
                                    color: Theme.washHair
                                }
                            }

                            Rectangle {
                                id: plot
                                objectName: "eqCurvePlot"
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: stageHeader.bottom
                                anchors.bottom: regionIndex.top
                                color: Qt.alpha(Theme.bgLow, 0.62)
                                border.width: 1
                                border.color: Theme.washHair
                                clip: true

                                readonly property real padL: view.compact ? 30 : 44
                                readonly property real padR: 12
                                readonly property real padT: 12
                                readonly property real padB: 26
                                readonly property real plotW: width - padL - padR
                                readonly property real plotH: height - padT - padB
                                readonly property var frequencyTicks: [
                                    {frequency: 20, label: "20", major: true},
                                    {frequency: 30, label: "30", major: false},
                                    {frequency: 40, label: "40", major: false},
                                    {frequency: 50, label: "50", major: true},
                                    {frequency: 60, label: "60", major: false},
                                    {frequency: 80, label: "80", major: false},
                                    {frequency: 100, label: "100", major: true},
                                    {frequency: 150, label: "150", major: false},
                                    {frequency: 200, label: "200", major: true},
                                    {frequency: 300, label: "300", major: false},
                                    {frequency: 400, label: "400", major: false},
                                    {frequency: 500, label: "500", major: true},
                                    {frequency: 600, label: "600", major: false},
                                    {frequency: 800, label: "800", major: false},
                                    {frequency: 1000, label: "1k", major: true},
                                    {frequency: 1500, label: "1.5k", major: false},
                                    {frequency: 2000, label: "2k", major: true},
                                    {frequency: 3000, label: "3k", major: false},
                                    {frequency: 4000, label: "4k", major: false},
                                    {frequency: 5000, label: "5k", major: true},
                                    {frequency: 6000, label: "6k", major: false},
                                    {frequency: 8000, label: "8k", major: false},
                                    {frequency: 10000, label: "10k", major: true},
                                    {frequency: 15000, label: "15k", major: false},
                                    {frequency: 20000, label: "20k", major: true}
                                ]
                                readonly property bool labelEveryFrequency:
                                    plotW >= 900

                                function fx(frequency) {
                                    return padL + (Math.log10(frequency / 20) / 3) * plotW
                                }
                                function xf(pixelX) {
                                    return 20 * Math.pow(10, 3 * (pixelX - padL) / plotW)
                                }
                                function gy(db) {
                                    return padT + plotH / 2
                                        - (db / view.displayDbRange) * (plotH / 2)
                                }
                                function yg(pixelY) {
                                    return (padT + plotH / 2 - pixelY)
                                        * view.displayDbRange / (plotH / 2)
                                }

                                onWidthChanged: canvas.requestPaint()
                                onHeightChanged: canvas.requestPaint()
                                onVisibleChanged: if (visible) Qt.callLater(canvas.requestPaint)

                                Rectangle {
                                    id: frequencyRegionHighlight
                                    objectName: "eqFrequencyRegionHighlight"
                                    x: plot.fx(view.activeRegion.start)
                                    y: plot.padT
                                    width: Math.max(1, plot.fx(view.activeRegion.end) - x)
                                    height: plot.plotH
                                    color: Qt.alpha(Theme.primary,
                                                    view.compact ? 0.045 : 0.055)

                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        width: 1
                                        color: Qt.alpha(Theme.primary, 0.24)
                                    }
                                    Rectangle {
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        width: 1
                                        color: Qt.alpha(Theme.primary, 0.24)
                                    }
                                }

                                Canvas {
                                    id: canvas
                                    anchors.fill: parent
                                    onPaint: {
                                        var context = getContext("2d")
                                        context.clearRect(0, 0, width, height)
                                        context.font = view.eqSupportTextSize + "px \""
                                            + Theme.displayFont + "\""
                                        var graphHeight = Math.max(
                                            1, height - plot.padT - plot.padB)
                                        var graphMid = plot.padT + graphHeight / 2

                                        context.fillStyle = Theme.washFaint
                                        context.lineWidth = 1
                                        for (var i = 0; i < plot.frequencyTicks.length; i++) {
                                            var tick = plot.frequencyTicks[i]
                                            var x = plot.fx(tick.frequency)
                                            context.strokeStyle = Qt.alpha(
                                                Theme.washInk, tick.major ? 0.11 : 0.045)
                                            context.beginPath()
                                            context.moveTo(x, plot.padT)
                                            context.lineTo(x, plot.padT + plot.plotH)
                                            context.stroke()
                                            if (plot.labelEveryFrequency || tick.major) {
                                                var labelWidth = context.measureText(tick.label).width
                                                var labelX = Math.max(2, Math.min(
                                                    width - labelWidth - 2,
                                                    x - labelWidth / 2))
                                                context.fillText(tick.label, labelX, height - 8)
                                            }
                                        }

                                        for (var db = -12; db <= 12; db += 6) {
                                            var y = graphMid
                                                - (db / view.displayDbRange)
                                                  * (graphHeight / 2)
                                            context.strokeStyle = db === 0
                                                ? Qt.alpha(Theme.washInk, 0.24)
                                                : Qt.alpha(Theme.washInk, 0.09)
                                            context.beginPath()
                                            context.moveTo(plot.padL, y)
                                            context.lineTo(plot.padL + plot.plotW, y)
                                            context.stroke()
                                            context.fillText((db > 0 ? "+" : "") + db, 5, y + 3)
                                        }

                                        var points = eq.responseCurve(240)
                                        if (points.length < 2)
                                            return
                                        context.beginPath()
                                        for (var j = 0; j < points.length; j++) {
                                            var px = plot.padL + (j / (points.length - 1)) * plot.plotW
                                            var responseDb = Math.max(
                                                -view.displayDbRange,
                                                Math.min(view.displayDbRange, points[j]))
                                            var py = graphMid
                                                - (responseDb / view.displayDbRange)
                                                  * (graphHeight / 2)
                                            if (j === 0)
                                                context.moveTo(px, py)
                                            else
                                                context.lineTo(px, py)
                                        }
                                        context.lineJoin = "round"
                                        context.lineCap = "round"
                                        context.strokeStyle = Qt.alpha(Theme.bgLow, 0.9)
                                        context.lineWidth = 5
                                        context.stroke()
                                        context.strokeStyle = eq.enabled
                                            ? Theme.primary : Qt.alpha(Theme.washMuted, 0.55)
                                        context.lineWidth = 2.5
                                        context.stroke()
                                        context.lineTo(plot.padL + plot.plotW, graphMid)
                                        context.lineTo(plot.padL, graphMid)
                                        context.closePath()
                                        context.fillStyle = Qt.alpha(
                                            Theme.primary, eq.enabled ? 0.045 : 0.015)
                                        context.fill()
                                    }
                                    Component.onCompleted: Qt.callLater(requestPaint)
                                }

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.leftMargin: plot.padL
                                    anchors.right: parent.right
                                    anchors.rightMargin: plot.padR
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.verticalCenterOffset: (plot.padT - plot.padB) / 2
                                    height: 1
                                    color: Qt.alpha(Theme.washInk, 0.24)
                                }

                                Repeater {
                                    model: view.localBands.length
                                    delegate: Item {
                                        id: handle
                                        objectName: "eqCurveHandle_" + index
                                        required property int index
                                        readonly property var band: view.localBands[index] || ({})
                                        x: plot.fx(band.freq || 100) - width / 2
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.verticalCenterOffset:
                                            (plot.padT - plot.padB) / 2
                                            - (Math.max(-view.displayDbRange,
                                                        Math.min(view.displayDbRange,
                                                                 Number(band.gain) || 0))
                                               / view.displayDbRange)
                                              * (Math.max(1, plot.height
                                                             - plot.padT - plot.padB) / 2)
                                        width: 30
                                        height: 30
                                        activeFocusOnTab: true
                                        Accessible.role: Accessible.Button
                                        Accessible.name: "Band " + (index + 1) + " curve handle"
                                        Accessible.onPressAction: view.selBand = index
                                        Keys.onReturnPressed: view.selBand = index
                                        Keys.onSpacePressed: view.selBand = index

                                        function setValues(frequency, gain, q) {
                                            var copy = view.localBands.slice()
                                            copy[index] = {
                                                node: band.node, type: band.type,
                                                freq: frequency, gain: gain, q: q
                                            }
                                            view.localBands = copy
                                            eq.setBand(index, frequency, gain, q)
                                        }

                                        Keys.onLeftPressed: {
                                            view.selBand = index
                                            if (!view.freqLock)
                                                setValues(Math.max(20, band.freq / 1.04),
                                                          band.gain, band.q)
                                        }
                                        Keys.onRightPressed: {
                                            view.selBand = index
                                            if (!view.freqLock)
                                                setValues(Math.min(20000, band.freq * 1.04),
                                                          band.gain, band.q)
                                        }
                                        Keys.onUpPressed: {
                                            view.selBand = index
                                            setValues(band.freq,
                                                      Math.min(view.editDbLimit,
                                                               band.gain + 0.25),
                                                      band.q)
                                        }
                                        Keys.onDownPressed: {
                                            view.selBand = index
                                            setValues(band.freq,
                                                      Math.max(-view.editDbLimit,
                                                               band.gain - 0.25),
                                                      band.q)
                                        }

                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: view.selBand === index ? 16 : 11
                                            height: width
                                            radius: width / 2
                                            color: Qt.alpha(view.typeColor(handle.band.type),
                                                            handleMouse.containsMouse
                                                            || view.selBand === index ? 0.95 : 0.62)
                                            border.color: Theme.washInk
                                            border.width: view.selBand === index ? 1 : 0
                                        }

                                        Rectangle {
                                            visible: handle.activeFocus
                                            anchors.centerIn: parent
                                            width: 24
                                            height: 24
                                            radius: 12
                                            color: "transparent"
                                            border.color: Theme.focusRing
                                            border.width: 1
                                        }

                                        MouseArea {
                                            id: handleMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.SizeAllCursor
                                            preventStealing: true
                                            onPressed: {
                                                view.selBand = index
                                                view.dragging = true
                                            }
                                            onReleased: {
                                                view.dragging = false
                                                view.localBands = eq.bands
                                            }
                                            onPositionChanged: mouse => {
                                                if (!pressed)
                                                    return
                                                var point = mapToItem(plot, mouse.x, mouse.y)
                                                var frequency = view.freqLock ? handle.band.freq
                                                    : Math.max(20, Math.min(20000, plot.xf(point.x)))
                                                var gain = Math.max(-view.editDbLimit,
                                                    Math.min(view.editDbLimit,
                                                             plot.yg(point.y)))
                                                handle.setValues(frequency, gain, handle.band.q)
                                            }
                                            onWheel: wheel => {
                                                view.selBand = index
                                                var q = handle.band.q
                                                    * (wheel.angleDelta.y > 0 ? 1.12 : 1 / 1.12)
                                                q = Math.max(0.1, Math.min(12, q))
                                                handle.setValues(handle.band.freq,
                                                                 handle.band.gain, q)
                                            }
                                        }
                                    }
                                }
                            }

                            Item {
                                id: regionIndex
                                objectName: "eqRegionIndex"
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: view.compact ? parent.bottom : toneDeck.top
                                height: view.compact ? 48 : 56

                                Item {
                                    id: regionBand
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    height: view.compact ? 25 : 29

                                    Repeater {
                                        model: view.frequencyRegions
                                        delegate: Item {
                                            id: frequencyRegionControl
                                            objectName: "eqFrequencyRegion_" + index
                                            required property int index
                                            required property var modelData
                                            readonly property var region: modelData || ({
                                                name: "", shortName: "", start: 20,
                                                end: 20, description: ""
                                            })
                                            readonly property bool active:
                                                view.activeFrequencyRegion === index
                                            x: plot.fx(region.start)
                                            width: Math.max(1, plot.fx(region.end) - x)
                                            height: regionBand.height
                                            activeFocusOnTab: true
                                            Accessible.role: Accessible.Button
                                            Accessible.name: region.name + ", "
                                                + view.regionRangeLabel(region) + ". "
                                                + region.description
                                            Accessible.onPressAction: activate()

                                            function activate() {
                                                view.pinnedFrequencyRegion =
                                                    view.pinnedFrequencyRegion === index
                                                    ? -1 : index
                                            }

                                            Keys.onReturnPressed: activate()
                                            Keys.onSpacePressed: activate()
                                            onActiveFocusChanged: {
                                                if (activeFocus)
                                                    view.hoveredFrequencyRegion = index
                                                else if (!regionHover.hovered
                                                         && view.hoveredFrequencyRegion === index)
                                                    view.hoveredFrequencyRegion = -1
                                            }

                                            Rectangle {
                                                anchors.fill: parent
                                                color: frequencyRegionControl.active
                                                    ? Qt.alpha(Theme.primary, 0.045)
                                                    : "transparent"
                                                border.width:
                                                    frequencyRegionControl.activeFocus ? 1 : 0
                                                border.color: Theme.focusRing
                                            }

                                            Text {
                                                anchors.centerIn: parent
                                                width: Math.max(1, parent.width - 4)
                                                horizontalAlignment: Text.AlignHCenter
                                                elide: Text.ElideRight
                                                text: view.compact
                                                    ? ((frequencyRegionControl.region || ({})).shortName || "")
                                                    : ((frequencyRegionControl.region || ({})).name || "").toUpperCase()
                                                color: frequencyRegionControl.active
                                                    ? Theme.primary : Theme.washFaint
                                                font.family: Theme.displayFont
                                                font.pixelSize: view.eqSupportTextSize
                                                font.letterSpacing: view.compact ? 0.1 : 1.1
                                            }

                                            Rectangle {
                                                visible: index > 0
                                                anchors.left: parent.left
                                                anchors.verticalCenter: parent.verticalCenter
                                                width: 1
                                                height: 16
                                                color: frequencyRegionControl.active
                                                    ? Qt.alpha(Theme.primary, 0.28)
                                                    : Theme.washHair
                                            }

                                            HoverHandler {
                                                id: regionHover
                                                cursorShape: Qt.PointingHandCursor
                                                onHoveredChanged: {
                                                    if (hovered)
                                                        view.hoveredFrequencyRegion = index
                                                    else if (!frequencyRegionControl.activeFocus
                                                             && view.hoveredFrequencyRegion === index)
                                                        view.hoveredFrequencyRegion = -1
                                                }
                                            }
                                            TapHandler {
                                                onTapped: frequencyRegionControl.activate()
                                            }
                                        }
                                    }
                                }

                                RowLayout {
                                    id: regionDescription
                                    objectName: "eqFrequencyRegionDescription"
                                    anchors.left: parent.left
                                    anchors.leftMargin: plot.padL
                                    anchors.right: parent.right
                                    anchors.rightMargin: plot.padR
                                    anchors.bottom: parent.bottom
                                    height: view.compact ? 23 : 27
                                    spacing: 8

                                    Text {
                                        Layout.preferredWidth: implicitWidth
                                        text: view.regionRangeLabel(view.activeRegion).toUpperCase()
                                        color: Theme.primary
                                        font.family: Theme.displayFont
                                        font.pixelSize: view.eqSupportTextSize
                                        font.letterSpacing: view.compact ? 0.3 : 1.0
                                    }

                                    Text {
                                        objectName: "eqFrequencyRegionDescriptionText"
                                        Layout.fillWidth: true
                                        text: view.activeRegion.description
                                        color: Theme.washMuted
                                        font.family: Theme.font
                                        font.pixelSize: view.eqSupportTextSize
                                        elide: Text.ElideRight
                                    }
                                }

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: regionDescription.top
                                    height: 1
                                    color: Theme.washHair
                                }
                            }

                            GridLayout {
                                id: toneDeck
                                visible: !view.compact
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: visible ? 112 : 0
                                columns: 2
                                columnSpacing: 28
                                rowSpacing: 0

                                Rectangle {
                                    Layout.columnSpan: 2
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 1
                                    color: Theme.washHair
                                }

                                ToneSlider {
                                    Layout.fillWidth: true
                                    name: "Bass"
                                    val: eq.toneBass
                                    onMoved: value => eq.setToneBass(value)
                                    onCommitted: value => eq.setToneBass(value)
                                }
                                ToneSlider {
                                    Layout.fillWidth: true
                                    name: "Treble"
                                    val: eq.toneTreble
                                    onMoved: value => eq.setToneTreble(value)
                                    onCommitted: value => eq.setToneTreble(value)
                                }
                                ToneSlider {
                                    Layout.fillWidth: true
                                    name: "Balance"
                                    val: eq.balance * 100
                                    lo: -100
                                    hi: 100
                                    fmt: "bal"
                                    onMoved: value => eq.setBalance(value / 100)
                                    onCommitted: value => eq.setBalance(value / 100)
                                }
                                ToneSlider {
                                    Layout.fillWidth: true
                                    name: "Preamp"
                                    val: eq.preamp
                                    lo: -24
                                    hi: 12
                                    onMoved: value => eq.setPreamp(value)
                                    onCommitted: value => eq.setPreamp(value)
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: compactControls
                visible: view.compact
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? compactDeck.implicitHeight + 32 : 0
                color: "transparent"

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: Theme.washHair
                }

                ColumnLayout {
                    id: compactDeck
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 16
                    spacing: 8

                    Text {
                        text: "SELECTED BAND / TONE & PROFILE"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.washMicro
                        font.letterSpacing: 2.2
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 3
                        columnSpacing: 12
                        MetricField {
                            Layout.fillWidth: true
                            label: "FREQUENCY"
                            accessibleName: "Selected band frequency"
                            val: view.selectedBand.freq !== undefined
                                ? String(Math.round(view.selectedBand.freq)) : ""
                            suffix: "Hz"
                            onCommitted: value => eq.setBand(
                                view.selBand, value,
                                view.selectedBand.gain, view.selectedBand.q)
                        }
                        MetricField {
                            Layout.fillWidth: true
                            label: "GAIN"
                            accessibleName: "Selected band gain"
                            val: view.bandGain(view.selectedBand)
                            suffix: "dB"
                            onCommitted: value => eq.setBand(
                                view.selBand, view.selectedBand.freq,
                                value, view.selectedBand.q)
                        }
                        MetricField {
                            Layout.fillWidth: true
                            label: "Q"
                            accessibleName: "Selected band Q"
                            val: view.selectedBand.q !== undefined
                                ? view.selectedBand.q.toFixed(2) : ""
                            suffix: "Q"
                            onCommitted: value => eq.setBand(
                                view.selBand, view.selectedBand.freq,
                                view.selectedBand.gain, value)
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 24
                        rowSpacing: 0
                        ToneSlider {
                            Layout.fillWidth: true
                            name: "Bass"
                            val: eq.toneBass
                            onMoved: value => eq.setToneBass(value)
                            onCommitted: value => eq.setToneBass(value)
                        }
                        ToneSlider {
                            Layout.fillWidth: true
                            name: "Treble"
                            val: eq.toneTreble
                            onMoved: value => eq.setToneTreble(value)
                            onCommitted: value => eq.setToneTreble(value)
                        }
                        ToneSlider {
                            Layout.fillWidth: true
                            name: "Balance"
                            val: eq.balance * 100
                            lo: -100
                            hi: 100
                            fmt: "bal"
                            onMoved: value => eq.setBalance(value / 100)
                            onCommitted: value => eq.setBalance(value / 100)
                        }
                        ToneSlider {
                            Layout.fillWidth: true
                            name: "Preamp"
                            val: eq.preamp
                            lo: -24
                            hi: 12
                            onMoved: value => eq.setPreamp(value)
                            onCommitted: value => eq.setPreamp(value)
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        spacing: 12
                        Text {
                            height: 44
                            verticalAlignment: Text.AlignVCenter
                            text: "PROFILE"
                            color: Theme.washFaint
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 2
                        }
                        Repeater {
                            model: eq.variants
                            delegate: WashLine {
                                label: modelData
                                primaryAction: modelData === eq.activeVariant
                                onActivated: eq.selectVariant(modelData)
                            }
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 88
                        spacing: 12
                        WashLine { label: "Add"; onActivated: eq.addBand() }
                        WashLine {
                            label: "Remove"
                            visible: (view.selectedBand.type || "") === "PK"
                            onActivated: eq.removeBand(view.selBand)
                        }
                        WashLine {
                            label: view.freqLock ? "Frequency locked" : "Frequency free"
                            primaryAction: view.freqLock
                            onActivated: view.freqLock = !view.freqLock
                        }
                        WashLine {
                            label: "Import"
                            primaryAction: importPanel.visible
                            onActivated: importPanel.visible = !importPanel.visible
                        }
                        WashLine {
                            id: compactPresetAction
                            label: "Presets"
                            onActivated: presetMenu.popupAt(
                                compactPresetAction, 0, compactPresetAction.height)
                        }
                        VariantCreator { }
                        WashLine {
                            visible: eq.variants.length > 1
                            label: "Delete profile"
                            onActivated: eq.deleteVariant(eq.activeVariant)
                        }
                    }
                }
            }

            Rectangle {
                id: importPanel
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 164 : 0
                visible: false
                color: Qt.alpha(Theme.bgLow, 0.28)
                border.color: Theme.washHair
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    Text {
                        text: "AUTOEQ IMPORT"
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 2
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TextArea {
                            id: importText
                            background: null
                            color: Theme.washInk
                            font.family: "monospace"
                            font.pixelSize: Theme.fsSmall
                            placeholderText: "Paste an AutoEq ParametricEQ block…\nPreamp: -6.4 dB\nFilter 1: ON PK Fc 105 Hz Gain -3.2 dB Q 0.70"
                            Accessible.name: "AutoEq parametric block"
                            placeholderTextColor: Theme.washFaint
                            wrapMode: TextEdit.NoWrap
                        }
                    }
                    RowLayout {
                        Layout.alignment: Qt.AlignRight
                        spacing: 16
                        WashLine {
                            label: "Apply"
                            primaryAction: true
                            onActivated: {
                                eq.importAutoEq(importText.text)
                                importPanel.visible = false
                            }
                        }
                        WashLine {
                            label: "Cancel"
                            onActivated: importPanel.visible = false
                        }
                    }
                }
            }
        }
    }
}
