import QtQuick
import QtQuick.Layouts
import "."

Item {
    id: view
    property int sleepMinutes: 0
    property string activeCategory: "playback"
    signal sleepPicked(int minutes)
    signal openDoctor()

    property var libStats: ({})
    function reloadStats() { libStats = backend.stats() }
    Component.onCompleted: reloadStats()
    onVisibleChanged: if (visible) {
        reloadStats()
        backend.requestLibrarySummary()
        scroller.keyboardFocus = false
        scroller.forceActiveFocus()
    }
    // Tab/Backtab bubble here from whichever child had focus before focus
    // navigation runs, so keyboard arrival at the scroller lights its ring
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab)
            scroller.keyboardFocus = true
    }
    Connections {
        target: backend
        function onDatabaseUpdated() { view.reloadStats() }
        function onLibraryStatsChanged() { view.reloadStats() }
    }

    // B.4 chapter head: quiet light title over a hairline — no raised plane
    component SectionLabel: Item {
        property alias text: sectionText.text
        property string index: ""
        Layout.fillWidth: true
        Layout.topMargin: Theme.spaceMd
        implicitHeight: 46

        Row {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            spacing: Theme.spaceSm
            Text {
                id: sectionText
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: Theme.fsEmph
                font.weight: Font.Light
            }
            Text {
                visible: parent.parent.index !== ""
                text: parent.parent.index
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.8
                anchors.baseline: sectionText.baseline
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
    component RowLabel: Text {
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.fsEmph
        Layout.preferredWidth: scroller.width < 620 ? 112 : 170
    }
    // B.4 portrait cell: quiet wash panel, light value, Rajdhani caption
    component SummaryCard: Rectangle {
        property string value: ""
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: view.width < 620 ? 68 : 84
        color: Qt.alpha("#0d0c0c", 0.55)
        border.width: 1
        border.color: Theme.washHair

        Column {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spaceMd
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: parent.parent.value
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: view.width < 620
                                ? Theme.fsEmph : Theme.fsTitle
                font.weight: Font.Light
            }
            Text {
                text: parent.parent.caption
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.8
            }
        }
    }
    // B.4 category tab: whisper text, accent underline on the active chapter
    component RailButton: Rectangle {
        property string label: ""
        property string sectionKey: ""
        property bool current: false
        implicitWidth: railLabel.implicitWidth + 12
        implicitHeight: 40
        color: "transparent"
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: label + " settings section"
        Accessible.onPressAction: {
            view.activeCategory = sectionKey
            scroller.contentY = 0
        }
        border.width: activeFocus ? 1 : 0
        border.color: activeFocus ? Theme.focusRing : "transparent"

        Text {
            id: railLabel
            anchors.centerIn: parent
            text: parent.label
            color: parent.current ? Theme.washInk
                 : railTap.hovered ? Theme.washMuted : Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.6
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            width: railLabel.width
            height: 1
            color: Theme.primary
            visible: parent.current
        }
        HoverHandler { id: railTap; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            onTapped: {
                view.activeCategory = parent.sectionKey
                scroller.contentY = 0
            }
        }
        Keys.onSpacePressed: {
            view.activeCategory = sectionKey
            scroller.contentY = 0
        }
        Keys.onReturnPressed: {
            view.activeCategory = sectionKey
            scroller.contentY = 0
        }
    }

    Flickable {
        id: scroller
        anchors.fill: parent
        anchors.leftMargin: view.width < 620 ? Theme.spaceMd
            : Math.max(Theme.pagePad,
                (view.width - Math.min(1040, view.width - Theme.pagePad * 2)) / 2)
        anchors.rightMargin: anchors.leftMargin
        anchors.topMargin: Theme.pageTop(view.height)
        anchors.bottomMargin: Theme.pagePad
        contentHeight: col.height + 30
        contentWidth: width
        clip: true
        activeFocusOnTab: true
        // the focus ring is a keyboard affordance: show it only once keys
        // drove focus here, never for the page-entry focus grab
        property bool keyboardFocus: false
        onActiveFocusChanged: if (!activeFocus) keyboardFocus = false
        Accessible.role: Accessible.Client
        Accessible.name: "Playback settings"
        function moveBy(amount) {
            contentY = Math.max(0, Math.min(contentY + amount,
                Math.max(0, contentHeight - height)))
        }
        Keys.onPressed: event => {
            keyboardFocus = true
            if (event.key === Qt.Key_PageDown) moveBy(height * 0.8)
            else if (event.key === Qt.Key_PageUp) moveBy(-height * 0.8)
            else if (event.key === Qt.Key_Home) contentY = 0
            else if (event.key === Qt.Key_End)
                contentY = Math.max(0, contentHeight - height)
            else return
            event.accepted = true
        }

        ColumnLayout {
            id: col
            width: scroller.width
            spacing: 12

            // ---- B.4 "Compact Index" (SPEC sprint-lock): micro + light
            // title, then current state and control depth in ONE band ----
            Text {
                text: "LISTENING PROFILE"
                color: Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 2
                text: "Your playback"
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: scroller.width < 620 ? 28 : 36
                font.weight: Font.Light
                    font.letterSpacing: -((scroller.width < 620 ? 28 : 36) * 0.03)
            }
            Text {
                Layout.fillWidth: true
                Layout.preferredWidth: scroller.width
                Layout.minimumWidth: 0
                text: "Current behavior and control depth share one index before the settings chapters begin."
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
                font.weight: Font.Light
                wrapMode: Text.WordWrap
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                columns: scroller.width < 620 ? 2 : 4
                rowSpacing: 8
                columnSpacing: 8
                SummaryCard {
                    value: backend.crossfade > 0 ? backend.crossfade + " s" : "Off"
                    caption: "CROSSFADE"
                }
                SummaryCard {
                    value: backend.mixRampOn
                           ? (backend.mixStyle === "fade" ? "Fade" : "Blend") : "Off"
                    caption: "AUTO-MIX"
                }
                SummaryCard {
                    value: backend.loudnessOn
                           ? backend.replayGain.charAt(0).toUpperCase()
                             + backend.replayGain.slice(1) : "Off"
                    caption: "LOUDNESS"
                }
                // the depth block completes the compact index: same band,
                // same cell voice, but it's the page's one mode control
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: view.width < 620 ? 68 : 84
                    color: "transparent"
                    border.width: 1
                    border.color: parent.activeFocus ? Theme.focusRing : depthTap.hovered
                                  ? Qt.alpha(Theme.primary, 0.65) : Theme.washHair
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: Theme.advancedSettings
                                     ? "Control depth: advanced — switch to simple"
                                     : "Control depth: simple — switch to advanced"
                    Accessible.onPressAction: Theme.advancedSettings = !Theme.advancedSettings
                    Keys.onReturnPressed: Theme.advancedSettings = !Theme.advancedSettings
                    Keys.onSpacePressed: Theme.advancedSettings = !Theme.advancedSettings
                    Rectangle {
                        anchors.fill: parent
                        color: depthTap.hovered ? Qt.alpha(Theme.primary, 0.07) : "transparent"
                    }
                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.spaceMd
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Row {
                            spacing: 8
                            Icon {
                                name: Theme.advancedSettings ? "ring-dot" : "ring"
                                size: 15
                                color: Theme.primary
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: Theme.advancedSettings ? "Advanced" : "Simple"
                                color: Theme.washInk
                                font.family: Theme.font
                                font.pixelSize: view.width < 620 ? Theme.fsEmph : Theme.fsTitle
                                font.weight: Font.Light
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Text {
                            text: "CONTROL DEPTH"
                            color: Theme.washMuted
                            font.family: Theme.displayFont
                            font.pixelSize: Theme.washMicro
                            font.letterSpacing: 1.8
                        }
                    }
                    HoverHandler { id: depthTap; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: Theme.advancedSettings = !Theme.advancedSettings }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                RailButton {
                    label: "PLAYBACK"
                    sectionKey: "playback"
                    current: view.activeCategory === sectionKey
                }
                RailButton {
                    label: "EXPERIENCE"
                    sectionKey: "experience"
                    current: view.activeCategory === sectionKey
                }
                RailButton {
                    label: "LIBRARY & SYSTEM"
                    sectionKey: "library"
                    current: view.activeCategory === sectionKey
                }
                Item { Layout.fillWidth: true }
            }

            SectionLabel {
                id: experienceHeader
                visible: view.activeCategory === "experience"
                text: "Experience"
                index: "02"
            }

            RowLayout {
                visible: view.activeCategory === "experience"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Album colors" }
                GlowButton {
                    label: Theme.albumColors ? "ON" : "OFF"
                    active: Theme.albumColors
                    tip: "Paint the whole app from the playing cover's palette; off keeps the neutral grey room"
                    onClicked: Theme.albumColors = !Theme.albumColors
                }
            }

            RowLayout {
                visible: view.activeCategory === "experience"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Transitions" }
                GlowButton {
                    label: Theme.pageAnim ? "ON" : "OFF"
                    active: Theme.pageAnim
                    tip: "Animate page changes (crossfade + drift) instead of hard switches"
                    onClicked: Theme.pageAnim = !Theme.pageAnim
                }
            }

            SectionLabel {
                id: playbackHeader
                visible: view.activeCategory === "playback"
                text: "Hand-offs & queue behavior"
                index: "01"
            }

            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 12
                RowLabel { text: "Crossfade" }
                AmpereSlider {
                    Layout.preferredWidth: scroller.width < 620
                        ? Math.max(120, scroller.width - 205) : 220
                    from: 0; to: 12; stepSize: 1
                    value: backend.crossfade
                    Accessible.name: "Crossfade seconds"
                    onMoved: backend.setCrossfade(value)
                }
                Text {
                    text: backend.crossfade > 0 ? backend.crossfade + " s" : "off"
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                }
                Text {
                    visible: backend.mixRampOn && backend.mixStyle === "fade"
                             && scroller.width >= 620
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: "auto-mix fade times each hand-off per song — this is only the base for unanalyzed files"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }

            // ---- extra shuffles: where album/genre shuffle live ----
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Album shuffle" }
                Repeater {
                    model: [
                        {id: "off",  label: "OFF",        tip: "Hidden everywhere"},
                        {id: "menu", label: "MENU",       tip: "In the shuffle button's right-click menu"},
                        {id: "bar",  label: "MENU + BAR", tip: "Also a stop in the shuffle button's click cycle"},
                    ]
                    delegate: GlowButton {
                        label: modelData.label
                        active: Theme.shuffleAlbumOpt === modelData.id
                        tip: modelData.tip
                        onClicked: Theme.shuffleAlbumOpt = modelData.id
                    }
                }
            }
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Genre shuffle" }
                Repeater {
                    model: [
                        {id: "off",  label: "OFF",        tip: "Hidden everywhere"},
                        {id: "menu", label: "MENU",       tip: "In the shuffle button's right-click menu"},
                        {id: "bar",  label: "MENU + BAR", tip: "Also a stop in the shuffle button's click cycle"},
                    ]
                    delegate: GlowButton {
                        label: modelData.label
                        active: Theme.shuffleGenreOpt === modelData.id
                        tip: modelData.tip
                        onClicked: Theme.shuffleGenreOpt = modelData.id
                    }
                }
            }

            // ---- Autoplay (independent from loop) ----
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 12
                RowLabel { text: "Autoplay" }
                GlowButton {
                    label: backend.autoplayOn ? "ON" : "OFF"
                    active: backend.autoplayOn
                    tip: "Continue with new songs after the selected queue ends"
                    Accessible.name: backend.autoplayOn
                        ? "Autoplay on — turn off"
                        : "Autoplay off — turn on"
                    onClicked: backend.setAutoplayOn(!backend.autoplayOn)
                }
                Text {
                    visible: scroller.width >= 620
                    text: backend.autoplayOn
                        ? "new songs continue after this queue (waits while a loop owns playback)"
                        : "playback stops at the end of the queue"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }

            // ---- phone remote ----
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 12
                RowLabel { text: "Phone remote" }
                GlowButton {
                    label: backend.remoteOn ? "ON" : "OFF"
                    active: backend.remoteOn
                    tip: "Control playback from your phone — open the address in its browser (LAN/tailnet)"
                    onClicked: backend.setRemoteOn(!backend.remoteOn)
                }
                GlowButton {
                    visible: backend.remoteOn
                    label: scroller.width < 620 ? "OPEN REMOTE" : "OPEN PAIRED REMOTE"
                    icon: "chevron-right"
                    tip: "Open the paired remote in this device's browser"
                    onClicked: Qt.openUrlExternally(backend.remoteUrl)
                }
                Text {
                    visible: backend.remoteOn && scroller.width >= 620
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: backend.remoteUrl.split("?")[0]
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }

            // ---- auto-mix: ONE panel owns the hand-off (audit #9 Stage 3) ----
            // [on] · [ordering] · advanced: threshold, style, analysis.
            // Ordering is the old "smart mix" — the queue-sequencing arm of
            // auto-mix, not a shuffle; silent tails are always trimmed
            // (the old Trim silence toggle is folded in, behavior unchanged).
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 12
                RowLabel { text: "Auto-mix" }
                GlowButton {
                    label: backend.mixRampOn ? "ON" : "OFF"
                    active: backend.mixRampOn
                    tip: "MixRamp: overlap songs where the outro is still loud — needs analyzed files"
                    onClicked: backend.setMixRampOn(!backend.mixRampOn)
                }
                Text {
                    visible: scroller.width >= 620
                    text: backend.mixRampOn
                        ? "songs blend where the music allows it"
                        : "songs hand off with the plain crossfade"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Ordering" }
                GlowButton {
                    label: "OFF"
                    active: !backend.smartMixOn
                    tip: "The queue plays in its own order"
                    onClicked: backend.smartMixOff()
                }
                GlowButton {
                    label: "SMOOTH"
                    active: backend.smartMixOn && !backend.mixArc
                    tip: "Each song bridges to the closest-energy neighbor — a flat, seamless flow"
                    onClicked: { backend.setMixArc(false); backend.smartMixStart() }
                }
                GlowButton {
                    label: "WAVE ARC"
                    active: backend.smartMixOn && backend.mixArc
                    tip: "The mix rises to an energy peak and cools back down, like a set with an arc"
                    onClicked: { backend.setMixArc(true); backend.smartMixStart() }
                }
                Text {
                    visible: scroller.width >= 620
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: "auto-mix's ordering arm (✦ in the bar) — arranges the queue so neighbors join smoothly"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings
                spacing: 12
                RowLabel { text: "" }
                AmpereSlider {
                    id: mrSlider
                    Layout.preferredWidth: 180
                    from: -40; to: -6; stepSize: 1
                    Accessible.name: "MixRamp entry threshold"
                    onMoved: backend.setMixRampDb(value)
                    Binding { target: mrSlider; property: "value"; value: backend.mixRampDb; when: !mrSlider.pressed }
                }
                Text {
                    text: backend.mixRampDb.toFixed(0) + " dB threshold — entries only start below this outro level"
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings && backend.mixRampOn
                spacing: 8
                RowLabel { text: "" }
                GlowButton {
                    label: "LEVEL BLEND"
                    active: backend.mixStyle === "blend"
                    tip: "MixRamp overlap: the next song enters at full level where both tracks are loud"
                    onClicked: backend.setMixStyle("blend")
                }
                GlowButton {
                    label: "FADE IN"
                    active: backend.mixStyle === "fade"
                    tip: "The next song fades in from silence across the outro's quiet tail (tag-timed crossfade)"
                    onClicked: backend.setMixStyle("fade")
                }
                Text {
                    text: backend.mixStyle === "fade"
                        ? "entry swells up instead of landing at full volume"
                        : "entries land at their natural level"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings
                spacing: 12
                property string mrState: ""
                id: mrRow
                Connections {
                    target: backend
                    function onMixrampProgress(done, total, tagged) {
                        mrRow.mrState = done >= total
                            ? "done — " + tagged + " newly tagged"
                            : done + " / " + total + "  (" + tagged + " tagged)"
                    }
                }
                RowLabel { text: "" }
                GlowButton {
                    label: "ANALYZE LIBRARY"
                    icon: "wave"
                    tip: "One-time pass: computes MixRamp tags for every FLAC (writes tags into the files; skips already-analyzed ones)"
                    onClicked: backend.analyzeMixRamp(false)
                }
                Text {
                    text: mrRow.mrState
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }

            // ---- loudness leveling: the ONE Plexamp-style switch ----
            SectionLabel {
                visible: view.activeCategory === "playback"
                text: "Volume consistency"
            }

            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 12
                id: rgRow
                property string scanState: ""
                RowLabel { text: "Loudness leveling" }
                GlowButton {
                    label: backend.loudnessOn ? "ON" : "OFF"
                    active: backend.loudnessOn
                    tip: "Every song at the same perceived volume — files without loudness tags get analyzed automatically in the background"
                    onClicked: backend.setLoudnessLeveling(!backend.loudnessOn)
                }
                Text {
                    text: rgRow.scanState !== "" ? rgRow.scanState
                        : backend.loudnessOn ? "songs play at matched volume"
                                             : "songs play at their native volume"
                    color: Qt.alpha(Theme.textDim, 0.75)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
                Connections {
                    target: backend
                    function onRgProgress(done, total, tagged) {
                        rgRow.scanState = total === 0 ? ""
                            : done >= total
                              ? (tagged > 0 ? "leveled " + tagged + " new files ✓" : "")
                              : "analyzing " + done + " / " + total + " unleveled files…"
                    }
                }
            }

            // simple: the overall level in three words — both preamps move together
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && backend.loudnessOn
                spacing: 8
                RowLabel { text: "" }
                Repeater {
                    model: [
                        {db: -6, label: "QUIETER",  tip: "Leveled, 6 dB softer overall — extra headroom, turn the amp up instead"},
                        {db: 0,  label: "STANDARD", tip: "Leveled at the reference volume (the default)"},
                        {db: 6,  label: "LOUDER",   tip: "Leveled, 6 dB hotter overall — dynamic tracks may clip"},
                    ]
                    delegate: GlowButton {
                        label: modelData.label
                        active: backend.rgPreamp === modelData.db
                                && backend.rgMissingPreamp === modelData.db
                        tip: modelData.tip + ". Applies with a quick engine restart — playback comes back paused at the same spot."
                        onClicked: backend.applyNormalization(modelData.db, modelData.db)
                    }
                }
                Text {
                    visible: backend.rgPreamp !== backend.rgMissingPreamp
                          || [-6, 0, 6].indexOf(backend.rgPreamp) < 0
                    text: "custom trim: " + (backend.rgPreamp >= 0 ? "+" : "") + backend.rgPreamp
                          + " dB tagged · " + (backend.rgMissingPreamp >= 0 ? "+" : "")
                          + backend.rgMissingPreamp + " dB untagged"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }

            // advanced: the leveling flavor MPD actually runs
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings && backend.loudnessOn
                spacing: 8
                RowLabel { text: "Leveling mode" }
                Repeater {
                    model: [
                        {id: "track", label: "TRACK", tip: "Every song to the same loudness — transitions always settle at the same volume (the default; DJ mixing assumes this)"},
                        {id: "album", label: "ALBUM", tip: "Albums keep their internal loud/quiet contrast — songs settle at DIFFERENT volumes; DJ transitions may jump"},
                        {id: "auto",  label: "AUTO",  tip: "Album-leveled when playing in order, track-leveled when shuffling — volume varies with play mode; DJ transitions may jump"},
                    ]
                    delegate: GlowButton {
                        label: modelData.label
                        active: backend.replayGain === modelData.id
                        tip: modelData.tip
                        onClicked: backend.setReplayGain(modelData.id)
                    }
                }
            }

            // advanced: the exact dB behind the presets — tagged files ride
            // replaygain_preamp, unscanned ones replaygain_missing_preamp
            RowLayout {
                Layout.fillWidth: true
                id: trimRow
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings && backend.loudnessOn
                spacing: 8
                property real pendPre: 0
                property real pendMiss: 0
                onVisibleChanged: if (visible) {
                    pendPre = backend.rgPreamp
                    pendMiss = backend.rgMissingPreamp
                }
                RowLabel { text: "Fine trim" }
                Text {
                    text: "tagged"
                    Layout.preferredWidth: 62
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font; font.pixelSize: Theme.fsSmall
                }
                AmpereSlider {
                    id: preSl
                    Layout.preferredWidth: 130
                    from: -15; to: 15; stepSize: 1
                    Accessible.name: "Tagged track fine trim"
                    onMoved: trimRow.pendPre = value
                    Binding { target: preSl; property: "value"; value: trimRow.pendPre; when: !preSl.pressed }
                }
                Text {
                    text: (trimRow.pendPre >= 0 ? "+" : "") + trimRow.pendPre + " dB"
                    color: Theme.textDim
                    font.family: Theme.font; font.pixelSize: Theme.fsBody
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: view.activeCategory === "playback"
                         && Theme.advancedSettings && backend.loudnessOn
                spacing: 8
                RowLabel { text: "" }
                Text {
                    text: "untagged"
                    Layout.preferredWidth: 62
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font; font.pixelSize: Theme.fsSmall
                }
                AmpereSlider {
                    id: missSl
                    Layout.preferredWidth: 130
                    from: -15; to: 15; stepSize: 1
                    Accessible.name: "Untagged track fine trim"
                    onMoved: trimRow.pendMiss = value
                    Binding { target: missSl; property: "value"; value: trimRow.pendMiss; when: !missSl.pressed }
                }
                Text {
                    text: (trimRow.pendMiss >= 0 ? "+" : "") + trimRow.pendMiss + " dB"
                    color: Theme.textDim
                    font.family: Theme.font; font.pixelSize: Theme.fsBody
                }
                GlowButton {
                    label: "APPLY"
                    visible: trimRow.pendPre !== backend.rgPreamp
                          || trimRow.pendMiss !== backend.rgMissingPreamp
                    tip: "Writes the trims and restarts the engine — playback comes back paused at the same spot"
                    onClicked: backend.applyNormalization(trimRow.pendPre, trimRow.pendMiss)
                }
            }

            SectionLabel {
                visible: view.activeCategory === "playback"
                text: "Sleep timer"
            }

            RowLayout {
                visible: view.activeCategory === "playback"
                Layout.fillWidth: true
                spacing: 8
                RowLabel { text: "Sleep timer"; visible: scroller.width >= 620 }
                Repeater {
                    model: [0, 15, 30, 60, 90]
                    delegate: GlowButton {
                        label: modelData === 0 ? "OFF" : modelData + " MIN"
                        active: view.sleepMinutes === modelData
                        onClicked: view.sleepPicked(modelData)
                    }
                }
                Text {
                    visible: view.sleepMinutes > 0
                    text: "pauses playback"
                    color: Qt.alpha(Theme.textDim, 0.7)
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
            }

            SectionLabel {
                id: libraryHeader
                visible: view.activeCategory === "library"
                text: "Library & system"
                index: "03"
            }

            Text {
                visible: view.activeCategory === "library"
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: (view.libStats.songs || 0) + " songs · " + (view.libStats.albums || 0)
                      + " albums · " + (view.libStats.artists || 0) + " artists · "
                      + (view.libStats.playtimeHours || 0) + " h of music"
                color: Theme.textDim
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
            }

            GridLayout {
                visible: view.activeCategory === "library"
                Layout.fillWidth: true
                columns: scroller.width < 620 ? 1 : 3
                rowSpacing: 8
                columnSpacing: 8
                GlowButton {
                    Layout.fillWidth: scroller.width < 620
                    icon: "search"; label: "LIBRARY DOCTOR"
                    tip: "Health check: duplicates, low bitrate, missing tags, loudness"
                    onClicked: view.openDoctor()
                }
                GlowButton {
                    Layout.fillWidth: scroller.width < 620
                    icon: "loop"; label: "UPDATE DATABASE"
                    tip: "Rescan your music folder (usually automatic)"
                    onClicked: backend.updateDatabase()
                }
                GlowButton {
                    Layout.fillWidth: scroller.width < 620
                    icon: "close"; label: "CLEAR MEDIA CACHES"
                    tip: "Artwork, artist portraits and waveforms regenerate on demand"
                    onClicked: backend.clearCaches()
                }
            }

            Rectangle {
                visible: view.activeCategory === "library"
                Layout.fillWidth: true
                height: 1
                color: Qt.alpha(Theme.outline, 0.5)
            }

            Text {
                visible: view.activeCategory === "library"
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: "Ampere " + backend.version
                      + " · everything you want to hear · MPD engine · per-device PEQ on PipeWire"
                color: Qt.alpha(Theme.textDim, 0.55)
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.letterSpacing: 1.5
            }
        }
    }
    Rectangle {
        anchors.fill: scroller
        z: 5
        enabled: false
        color: "transparent"
        border.width: scroller.activeFocus && scroller.keyboardFocus ? 1 : 0
        border.color: Theme.focusRing
    }
}
