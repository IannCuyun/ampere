import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: suite
    name: "AlbumControls"
    when: windowShown
    visible: true
    width: 1440
    height: 900
    property var backend: provider
    QtObject {
        id: provider
        property var currentSong: ({file: "playing.flac"})
        property bool libraryReady: true
        property int libraryTotalSongs: 0
        property int radioCalls: 0
        function startBeaconRadio() { radioCalls++ }
    }
    Component {
        id: album
        AlbumView { info: ({album: "Album", artist: "Artist", tracks: []}) }
    }
    SignalSpy { id: radioSpy; signalName: "radioRequested" }
    function test_controls_data() {
        return [{tag: "desktop", w: 1440}, {tag: "compact", w: 800}]
    }
    function test_controls(data) {
        provider.currentSong = {file: "playing.flac"}
        provider.radioCalls = 0
        var page = createTemporaryObject(album, suite, {width: data.w, height: 700})
        verify(page)
        radioSpy.target = page
        radioSpy.clear()
        var radio = findChild(page, "albumRadioControl")
        var crumb = findChild(page, "albumBreadcrumb")
        verify(radio && crumb)
        verify(!crumb.activeFocusOnTab)
        compare(crumb.children.length, 0)
        wait(50)
        var pos = radio.mapToItem(page, 0, 0)
        verify(pos.x + radio.width <= page.width)
        mouseClick(radio, radio.width / 2, radio.height / 2)
        compare(provider.radioCalls, 1)
        compare(radioSpy.count, 1)
        radio.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(provider.radioCalls, 2)
        provider.currentSong = {}
        tryCompare(radio, "enabled", false)
        radio.activated() // Includes accessibility activation path.
        compare(provider.radioCalls, 2)
        compare(radioSpy.count, 2)
    }
}
