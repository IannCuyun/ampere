import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "BrowseClickPlayback"
    when: windowShown
    visible: true
    width: 1260
    height: 900
    property var backend: provider
    QtObject {
        id: provider
        property var currentSong: ({})
        property var likedFiles: []
        property var playlists: []
        property var artColors: []
        property bool libraryReady: true
        property int libraryTotalSongs: 2
        property var calls: []
        signal databaseUpdated()
        function browse(path) { return [
            {type: "dir", path: "Music/Child", name: "Child"},
            {type: "file", file: "Music/one.flac", title: "One", artist: "Artist", duration: 200},
            {type: "file", file: "Music/two.flac", title: "Two", artist: "Artist", duration: 200}
        ] }
        function playFiles(files, index) { calls = calls.concat([{files: files, index: index}]) }
    }
    Component { id: browser; BrowseView { path: "Music" } }
    function rows(item, result) {
        if (item.playOnSingleClick !== undefined) result.push(item)
        for (var i = 0; i < item.children.length; ++i) rows(item.children[i], result)
        return result
    }
    function test_singleClick_data() { return [{tag: "desktop", width: 1260}, {tag: "compact", width: 720}] }
    function test_singleClick(data) {
        provider.calls = []
        var view = createTemporaryObject(browser, testCase, {width: data.width, height: 480})
        verify(view)
        var tracks = []
        tryVerify(function() { tracks = rows(view, []); return tracks.length === 2 })
        tracks.sort(function(a,b) { return a.rowIndex - b.rowIndex })
        mouseClick(tracks[1], 100, 22, Qt.LeftButton)
        compare(provider.calls.length, 1)
        compare(provider.calls[0].index, 1)
        compare(provider.calls[0].files.join(","), "Music/one.flac,Music/two.flac")
        mouseClick(tracks[0], 100, 22, Qt.RightButton)
        compare(provider.calls.length, 1)
    }
}
