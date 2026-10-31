import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "DiscoverNeedleDropBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 900

    property var backend: provider

    QtObject {
        id: provider
        property var artColors: []
        property int refreshes: 0
        property var playedAlbums: []
        property var projection: ({
            ready: true,
            lanes: [
                {
                    key: "loved", ordinal: "01", shortTitle: "Forgotten",
                    title: "Bring something back", subtitle: "Loved, then quiet",
                    eyebrow: "DISCOVER / A FAVORITE OUT OF ROTATION",
                    reason: "A favorite has slipped out of rotation.", count: 2,
                    entry: {file: "Rap/Artist/Album/01.flac", album: "Album",
                            artist: "Artist", date: "2024",
                            files: ["Rap/Artist/Album/01.flac",
                                    "Rap/Artist/Album/02.flac"]}
                },
                {
                    key: "arrivals", ordinal: "02", shortTitle: "New",
                    title: "Open a recent arrival", subtitle: "Waiting for a first spin",
                    eyebrow: "DISCOVER / RECENTLY ADDED",
                    reason: "Recently added.", count: 1,
                    entry: {file: "Metal/Band/New Album/01.flac", album: "New Album",
                            artist: "Band",
                            files: ["Metal/Band/New Album/01.flac"]}
                },
                {
                    key: "deep", ordinal: "03", shortTitle: "Unheard",
                    title: "Go deeper", subtitle: "Unplayed from familiar rooms",
                    eyebrow: "DISCOVER / DEEP IN A FAMILIAR ROOM",
                    reason: "Overlooked.", count: 0, entry: {}
                }
            ]
        })
        signal librarySummaryChanged()
        function discoverOverview() { return projection }
        function requestLibrarySummary() { refreshes += 1 }
        function playAlbum(files, index) {
            playedAlbums = playedAlbums.concat([{files: files, index: index}])
            return true
        }
    }

    DiscoverView {
        id: discover
        parent: testCase
        width: 1256
        height: 820
        active: true
    }

    function sampleProjection() {
        return {
            ready: true,
            lanes: [
                {
                    key: "loved", ordinal: "01", shortTitle: "Forgotten",
                    title: "Bring something back", subtitle: "Loved, then quiet",
                    eyebrow: "DISCOVER / A FAVORITE OUT OF ROTATION",
                    reason: "A favorite has slipped out of rotation.", count: 2,
                    entry: {file: "Rap/Artist/Album/01.flac", album: "Album",
                            artist: "Artist", date: "2024",
                            files: ["Rap/Artist/Album/01.flac",
                                    "Rap/Artist/Album/02.flac"]}
                },
                {
                    key: "arrivals", ordinal: "02", shortTitle: "New",
                    title: "Open a recent arrival", subtitle: "Waiting for a first spin",
                    eyebrow: "DISCOVER / RECENTLY ADDED",
                    reason: "Recently added.", count: 1,
                    entry: {file: "Metal/Band/New Album/01.flac", album: "New Album",
                            artist: "Band",
                            files: ["Metal/Band/New Album/01.flac"]}
                },
                {
                    key: "deep", ordinal: "03", shortTitle: "Unheard",
                    title: "Go deeper", subtitle: "Unplayed from familiar rooms",
                    eyebrow: "DISCOVER / DEEP IN A FAMILIAR ROOM",
                    reason: "Overlooked.", count: 0, entry: {}
                }
            ]
        }
    }

    function init() {
        provider.playedAlbums = []
        provider.projection = sampleProjection()
        discover.width = 1256
        discover.loadCachedOverview()
        wait(0)
    }

    function test_default_lane_and_primary_action_use_exact_album_membership() {
        compare(discover.selectedKey, "loved")
        var action = findChild(discover, "needleAction")
        verify(action !== null)
        verify(action.visible)
        action.forceActiveFocus()
        tryCompare(action, "activeFocus", true)
        keyClick(Qt.Key_Return)
        wait(0)
        compare(provider.playedAlbums.length, 1)
        compare(provider.playedAlbums[0].index, 0)
        compare(provider.playedAlbums[0].files.length, 2)
        compare(provider.playedAlbums[0].files[0],
                "Rap/Artist/Album/01.flac")
        compare(provider.playedAlbums[0].files[1],
                "Rap/Artist/Album/02.flac")
    }

    function test_lane_selection_does_not_mutate_playback() {
        var lane = findChild(discover, "needleLane1")
        verify(lane !== null)
        lane.forceActiveFocus()
        keyClick(Qt.Key_Space)
        compare(discover.selectedKey, "arrivals")
        compare(provider.playedAlbums.length, 0)
    }

    function test_compact_stage_and_lanes_stay_inside_the_view() {
        discover.width = 680
        wait(0)
        var stage = findChild(discover, "needleStage")
        var lanes = findChild(discover, "needleLanes")
        verify(stage !== null)
        verify(lanes !== null)
        verify(stage.x >= 0)
        verify(stage.x + stage.width <= discover.width + 0.5)
        verify(lanes.x >= 0)
        verify(lanes.x + lanes.width <= stage.width + 0.5)
    }

    function test_loading_and_verified_empty_states_are_distinct() {
        var loading = findChild(discover, "needleLoading")
        var empty = findChild(discover, "needleEmpty")
        verify(loading !== null)
        verify(empty !== null)

        discover.overview = {ready: false, lanes: []}
        discover.selectedIndex = -1
        provider.projection = {ready: false, lanes: []}
        discover.loadCachedOverview()
        tryCompare(loading, "visible", true)
        compare(empty.visible, false)

        provider.projection = {
            ready: true,
            lanes: [
                {key: "loved", ordinal: "01", shortTitle: "Forgotten",
                 title: "Bring something back", subtitle: "Loved, then quiet", entry: {}},
                {key: "arrivals", ordinal: "02", shortTitle: "New",
                 title: "Open a recent arrival", subtitle: "Waiting", entry: {}},
                {key: "deep", ordinal: "03", shortTitle: "Unheard",
                 title: "Go deeper", subtitle: "Unplayed", entry: {}}
            ]
        }
        discover.loadCachedOverview()
        tryCompare(empty, "visible", true)
        compare(loading.visible, false)
    }
}
