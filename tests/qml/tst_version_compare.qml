import "../../qml"
import QtQuick
import QtTest

// The duplicate-version page Iann asked for on 2026-08-21: two recordings
// side by side with every fact that decides whether they are the same
// performance. "Prefer this version" moved here out of the Doctor list when
// F2 replaced it, and its contract moved with it (2026-08-23).
TestCase {
    id: testCase
    name: "VersionCompareBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property var currentSong: ({ file: "current.flac" })
        property var preferred: []
        property var played: []
        function preferVersion(file) { preferred = preferred.concat([file]) }
        function playFiles(files, index) { played = played.concat([files[index]]) }
        function requestVersionDetails(files) { return true }
        signal versionDetailsReady(var payload)
    }

    VersionCompareView {
        id: page
        parent: testCase
        width: testCase.width
        height: testCase.height
    }

    function groups() {
        return [{
            title: "Signal", artist: "The Artist",
            files: [{file: "record/signal.flac"}, {file: "single/signal.flac"}]
        }, {
            title: "Second", artist: "The Artist",
            files: [{file: "a/second.flac"}, {file: "b/second.flac"}]
        }]
    }

    function init() {
        provider.preferred = []
        provider.played = []
        page.open(groups(), 0)
        wait(0)
    }

    function test_it_states_which_group_of_how_many() {
        const position = findChild(page, "versionComparePosition")
        verify(position !== null)
        page.rows = [{file: "record/signal.flac"}, {file: "single/signal.flac"}]
        wait(0)
        compare(position.text, "1 OF 2")
    }

    function test_the_edge_arrows_walk_the_findings() {
        // The arrows wrap: the finding set is a ring, and the arrows are
        // disabled outright when there is only one group.
        page.step(1)
        compare(page.index, 1)
        page.step(1)
        compare(page.index, 0)
        page.step(-1)
        compare(page.index, 1)
    }

    function test_escape_closes_without_touching_anything() {
        const spy = closedSpy
        spy.clear()
        page.forceActiveFocus()
        keyClick(Qt.Key_Escape)
        compare(spy.count, 1)
        compare(provider.preferred.length, 0)
        compare(provider.played.length, 0)
    }

    SignalSpy {
        id: closedSpy
        target: page
        signalName: "closed"
    }
}
