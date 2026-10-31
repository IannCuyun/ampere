import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "GalleryShuffleLayout"
    when: windowShown
    visible: true
    width: 680
    height: 955

    property var backend: provider

    QtObject {
        id: provider
        property var currentSong: ({ file: "", title: "Track", artist: "Artist", album: "Album" })
        property var likedFiles: []
        property var dislikedFiles: []
        property var lyrics: []
        property var queue: []
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

        property int radiosStarted: 0
        function startBeaconRadio() { radiosStarted++ }
        function artistPath() { return "" }
        function songStory() { return null }
        function trackChapters() { return [] }
        function requestSeek() {}
        function requestVolume() {}
        function requestPlayPause() {}
        function requestPrevious() {}
        function requestNext() {}
        function requestCycleRepeat() {}
        function cycleContextShuffle() {}
        function toggleLike() {}
        function toggleDislike() {}
        function playPosition() {}
    }

    GalleryNowPlayingView {
        id: gallery
        parent: testCase
        anchors.fill: parent
        active: true
        queueOpen: true
        windowGeometryChanging: true
    }

    function initTestCase() {
        Theme.heartsOn = true
        wait(0)
    }

    function leftOf(item) {
        return item.mapToItem(gallery, 0, 0).x
    }

    function verifyCoreControlsDoNotOverlap() {
        const shuffle = findChild(gallery, "contextShuffleControl")
        const previous = findChild(gallery, "galleryPreviousControl")
        const play = findChild(gallery, "galleryPlayControl")
        const next = findChild(gallery, "galleryNextControl")
        verify(shuffle !== null)
        verify(previous !== null)
        verify(play !== null)
        verify(next !== null)
        compare(shuffle.width, 44)
        compare(shuffle.height, 44)
        compare(play.width, 50)
        verify(leftOf(shuffle) + shuffle.width <= leftOf(previous) + 0.5)
        verify(leftOf(previous) + previous.width <= leftOf(play) + 0.5)
        verify(leftOf(play) + play.width <= leftOf(next) + 0.5)
    }

    function test_compactPanelProtectsCoreTransportTargets() {
        gallery.queueOpen = true
        const like = findChild(gallery, "galleryLikeControl")
        const dislike = findChild(gallery, "galleryDislikeControl")
        verify(like !== null)
        verify(dislike !== null)

        testCase.width = 680
        wait(0)
        verify(!like.visible)
        verify(!dislike.visible)
        verifyCoreControlsDoNotOverlap()

        testCase.width = 720
        wait(0)
        verify(!like.visible)
        verify(!dislike.visible)
        verifyCoreControlsDoNotOverlap()

        testCase.width = 780
        wait(0)
        verify(like.visible)
        verify(dislike.visible)
        verifyCoreControlsDoNotOverlap()
    }

    function test_supportedShallowWindowKeepsSleeveAboveDeck() {
        gallery.queueOpen = false
        gallery.lyricsOpen = false
        testCase.width = 720
        testCase.height = 480
        wait(0)
        verify(gallery.artSide >= gallery.minimumContainedArtSide)
        verify(gallery.artTopY + gallery.artSide
               <= gallery.deckTopY - 31.5)

        gallery.queueOpen = true
        wait(0)
        verify(gallery.panelArtSide >= gallery.minimumContainedArtSide)
        verify(gallery.artTopY + gallery.panelArtSide
               <= gallery.deckTopY - 31.5)
    }
    function test_beacon_entrance_and_compact_separation() {
        const beacon = findChild(gallery, "galleryRadioControl")
        verify(beacon !== null)
        compare(beacon.width, 46)
        compare(beacon.height, 46)
        provider.currentSong = {file: "", title: "Track", artist: "Artist", album: "Album", year: ""}
        wait(0)
        verify(!beacon.enabled)
        provider.currentSong = {file: "Artist/Album/01.flac", title: "Track", artist: "Artist", album: "Album", year: ""}
        wait(0)
        verify(beacon.enabled)
        beacon.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(provider.radiosStarted, 1)
        for (var w of [720, 780, 948, 1600]) {
            testCase.width = w
            for (var panel of [false, true]) {
                gallery.queueOpen = panel
                gallery.lyricsOpen = false
                wait(0)
                const dislike = findChild(gallery, "galleryDislikeControl")
                const loop = findChild(gallery, "galleryLoopControl")
                const last = dislike.visible ? dislike : loop
                verify(leftOf(last) + last.width <= leftOf(beacon) + 0.5,
                       "Transport collides with Beacon at " + w + " panel=" + panel + " end=" + (leftOf(last) + last.width) + " beacon=" + leftOf(beacon))
            }
        }
    }

}
