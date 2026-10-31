import "../../qml"
import QtQuick
import QtTest
TestCase {
    id: testCase
    name: "RadioGalleryReference"
    when: windowShown
    visible: true
    width: 1920
    height: 1080
    property var backend: provider
    QtObject {
        id: provider
        property var currentSong: ({file:"Artist/Album/01.flac",title:"Playing",artist:"Artist",album:"Album"})
        property var likedFiles: []
        property var dislikedFiles: []
        property var lyrics: []
        property var queue: [{file:"Artist/Album/01.flac", title:"Playing", artist:"Artist", album:"Album", pos:0, duration:200}, {file:"Artist/Album/02.flac",title:"Next",artist:"Artist",pos:1,duration:220}]
        property int queuePos: 0
        property int queueRemainingCount: 0
        property int visibleQueuePlayPos: 0
        property real elapsed: 40
        property real duration: 200
        property int volume: 80
        property int liveKbps: 0
        property string state: "play"
        property string audioInfo: "FLAC"
        property string contextShuffleMode: "off"
        property bool lyricsSynced: false
        property bool repeat: false
        property bool single: false
        property bool autoplayOn: false
        property bool djOn: false
        property bool smartMixOn: false

        property var beaconSession: ({seed:currentSong, tracks:queue})
        property bool beaconBusy: false
        property bool beaconActive: true
        property bool beaconRestoring: false
        property string saved: ""
        property int pauses: 0
        property int jumps: 0
        property int radioJumps: 0
        function playBeaconPosition(pos) { radioJumps++ }
        property int radiosStarted: 0
        function saveBeaconPlaylist(name) { saved = name }
        function startBeaconRadio() { radiosStarted++ }
        function artistPath() { return "" }
        function songStory() { return null }
        function trackChapters() { return [] }
        function requestSeek() {}
        function requestVolume() {}
        function requestPlayPause() { pauses++ }
        function requestPrevious() {}
        function requestNext() {}
        function requestCycleRepeat() {}
        function cycleContextShuffle() {}
        function toggleLike() {}
        function toggleDislike() {}
        function playPosition() { jumps++ }
    }

    RadioView { id: radio; anchors.fill: parent; active: true; windowGeometryChanging: true }
    SignalSpy { id: exitSpy; target: radio; signalName: "exitRadioRequested" }
    WhisperRail { id: rail; anchors.fill: parent; visible: false }
    function init() {
        provider.beaconRestoring = false
        provider.lyrics = []
        provider.lyricsSynced = false
        width = 1920; height = 1080
        radio.setQueue(true)
        provider.saved = ""; provider.pauses = 0; provider.jumps = 0; provider.radiosStarted = 0
        exitSpy.clear()
        wait(20)
    }
    function visibleChild(parent, name) {
        return findChild(findChild(parent, radio.lyricsOpen ? "lyricRadioHeader" : "queueRadioHeader"), name)
    }
    function activate(item) {
        verify(item !== null)
        item.forceActiveFocus()
        keyClick(Qt.Key_Return)
    }
    function test_panel_switch_keeps_playback_and_identity() {
        verify(radio.queueOpen)
        compare(visibleChild(radio, "radioPanelHeading").text, "RADIO QUEUE")
        var before = JSON.stringify(provider.queue)
        activate(findChild(radio, "galleryLyricsControl"))
        verify(radio.lyricsOpen && !radio.queueOpen)
        compare(visibleChild(radio, "radioPanelHeading").text, "RADIO · LYRICS")
        activate(findChild(radio, "galleryQueueControl"))
        verify(radio.queueOpen && !radio.lyricsOpen)
        compare(provider.pauses, 0); compare(provider.jumps, 0); compare(provider.radiosStarted, 0)
        compare(JSON.stringify(provider.queue), before)
    }
    function test_exit_reachable_from_both_panels() {
        activate(visibleChild(radio, "radioExitControl"))
        compare(exitSpy.count, 1)
        radio.setLyrics(true)
        wait(20)
        activate(visibleChild(radio, "radioExitControl"))
        compare(exitSpy.count, 2)
    }
    function test_radio_queue_jump_keeps_ownership() {
        provider.radioJumps = 0
        provider.beaconActive = true
        radio.playQueueRow({pos:1})
        compare(provider.radioJumps, 1)
        compare(provider.jumps, 0)
        provider.beaconActive = false
        radio.playQueueRow({pos:1})
        compare(provider.radioJumps, 2)
        compare(provider.jumps, 0)
        provider.beaconActive = true
    }
    function test_restore_disables_duplicate_exit() {
        provider.beaconRestoring = true
        var control = visibleChild(radio, "radioExitControl")
        verify(!control.enabled)
        compare(control.label, "Restoring queue…")
    }
    function test_radio_lyrics_restore_viewport_after_manual_scroll() {
        var lines = []
        for (var i=0; i<60; i++) lines.push({t:i*20,line:"Lyric "+i})
        provider.lyrics = lines; provider.lyricsSynced = true; provider.elapsed = 180
        radio.setLyrics(true)
        wait(250)
        var list = findChild(radio, "galleryLyricList")
        var timer = findChild(radio, "galleryResumeLyricFollow")
        compare(list.currentIndex, 9)
        radio.lyricAutoFollow = false
        list.contentY += 600
        timer.restart()
        tryCompare(radio, "lyricAutoFollow", true, 4500)
        var line = list.itemAtIndex(9)
        verify(line !== null)
        verify(line.y >= list.contentY && line.y + line.height <= list.contentY + list.height)
    }
    function test_radio_queue_focus_reveals_clipped_row() {
        var original = provider.queue
        var queue = []
        for (var i=0; i<60; i++) queue.push({file:"Artist/"+i+".flac",title:"Track "+i,pos:i})
        provider.queue = queue
        wait(20) // Let ListView apply the replacement model before positioning.
        var list = findChild(radio, "galleryQueueList")
        list.positionViewAtIndex(20,ListView.Center)
        wait(20)
        var row = list.itemAtIndex(20)
        verify(row !== null)
        list.contentY = row.y + 20
        row.forceActiveFocus()
        wait(10)
        verify(row.activeFocus, "Queue row receives active focus")
        verify(row.y >= list.contentY && row.y + row.height <= list.contentY + list.height,
               "row="+row.y+" height="+row.height+" viewport="+list.contentY+"/"+list.height)
        provider.queue = original
    }
    function test_save_existing_session() {
        activate(visibleChild(radio, "radioSaveControl"))
        var dialog = findChild(radio, "radioSaveDialog")
        tryCompare(dialog, "opened", true)
        var input = findChild(radio, "radioPlaylistName")
        compare(input.text, "Radio—Artist")
        input.text = "Radio copy"
        dialog.accept()
        compare(provider.saved, "Radio copy")
    }
    function test_header_has_no_global_radio() {
        rail.visible = true
        rail.currentMode = "radio"
        compare(findChild(rail, "dest-radio"), null)
        rail.visible = false
    }
    function test_reference_geometry_data() {
        return [{tag:"desktop",w:1920,h:1080},{tag:"compact",w:948,h:1000},{tag:"floor",w:720,h:480}]
    }
    function test_reference_geometry(data) {
        width = data.w; height = data.h
        wait(20)
        var exit = visibleChild(radio, "radioExitControl")
        var heading = visibleChild(radio, "radioPanelHeading")
        var point = exit.mapToItem(radio, 0, 0)
        verify(point.x >= 0 && point.x + exit.width <= width)
        verify(point.y >= 0 && point.y + exit.height <= height)
        verify(exit.height >= 44)
        var list = findChild(radio, "galleryQueueList")
        var listPoint = list.mapToItem(radio, 0, 0)
        verify(listPoint.y >= point.y + exit.height)
        verify(listPoint.y + list.height <= radio.transportCenterY - 25)
        verify(list.height > 0)
        verify(!heading.truncated)
    }
}
