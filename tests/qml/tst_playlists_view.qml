import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "PlaylistNavigationBehavior"
    when: windowShown
    visible: true
    width: 1180
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property var playlists: ["Dark Passage", "Night Drive"]
        property var playlistPlayCounts: ({})
        property var requestedNames: []
        property var actions: []
        property var artColors: ["#b26c65", "#3b5368"]
        property var currentSong: ({})
        property var likedFiles: []
        signal playlistCoversChanged()
        signal playlistTracksReady(string name, var rows, bool success)

        function playlistCovers() { return ({}) }
        function requestPlaylistCovers() {}
        function playlistTracks(name) {
            requestedNames = requestedNames.concat([name])
            return [
                {file: name + "/01.flac", title: "Zulu",
                 artist: "Beta", album: name, duration: 180,
                 added: 30, playlistPos: 0},
                {file: name + "/02.flac", title: "Alpha",
                 artist: "Gamma", album: name, duration: 190,
                 added: 10, playlistPos: 1},
                {file: name + "/03.flac", title: "Middle",
                 artist: "Alpha", album: name, duration: 200,
                 added: 20, playlistPos: 2}
            ]
        }
        function loadPlaylist(name, replace) {
            actions = actions.concat([{name: name, replace: replace}])
        }
        function shufflePlaylistNow(name) {
            actions = actions.concat([{name: name, shuffle: true}])
        }
        function playNext(file) {}
        function queuePath(file) {}
        function toggleLike(file) {}
        function moreLikeThis(file) {}
        function playFiles(files, index) {
            actions = actions.concat([{files: Array.from(files), index: index}])
        }
        function playPlaylistFiles(name, files, index) {
            actions = actions.concat([{
                name: name, files: Array.from(files), index: index
            }])
        }
    }

    PlaylistsView {
        id: view
        parent: testCase
        width: testCase.width
        height: testCase.height
    }

    function init() {
        testCase.width = 1180
        view.width = 1180
        view.showAll()
        provider.requestedNames = []
        provider.actions = []
        provider.playlistPlayCounts = ({})
        wait(0)
    }

    function test_card_opens_the_exact_sequence_without_a_route_change() {
        const card = findChild(view, "playlistSequence_1")
        verify(card !== null)
        card.forceActiveFocus()
        verify(card.activeFocus)
        keyClick(Qt.Key_Return)
        compare(view.selected, "Night Drive")
        compare(provider.requestedNames.length, 1)
        compare(provider.requestedNames[0], "Night Drive")
    }

    function test_component_has_one_local_owner_without_a_second_library_frame() {
        compare(findChild(view, "playlistWall") !== null, true)
        compare(findChild(view, "libraryFrame"), null)
    }

    function test_highest_verified_play_count_owns_the_large_tile() {
        provider.playlistPlayCounts = ({"Night Drive": 9,
                                        "Dark Passage": 2})
        wait(0)
        const wall = findChild(view, "playlistWall")
        const lead = findChild(view, "playlistSequence_0")
        const continuation = findChild(view, "playlistSequence_1")
        verify(wall !== null && lead !== null && continuation !== null)
        compare(lead.sequenceName, "Night Drive")
        compare(continuation.sequenceName, "Dark Passage")
        verify(lead.height > continuation.height)
    }

    function test_equal_counts_keep_the_visible_playlist_order() {
        provider.playlistPlayCounts = ({"Night Drive": 4,
                                        "Dark Passage": 4})
        wait(0)
        const lead = findChild(view, "playlistSequence_0")
        const continuation = findChild(view, "playlistSequence_1")
        verify(lead !== null && continuation !== null)
        compare(lead.sequenceName, "Dark Passage")
        compare(continuation.sequenceName, "Night Drive")
    }

    function test_all_sequences_returns_to_the_same_local_wall() {
        view.openPlaylist("Dark Passage")
        compare(view.selected, "Dark Passage")
        view.showAll()
        compare(view.selected, "")
        compare(view.tracks.length, 0)
    }

    function test_wall_selects_in_place_and_stays_contained() {
        wait(0)
        const wall = findChild(view, "playlistWall")
        const second = findChild(view, "playlistSequence_1")
        verify(wall !== null && second !== null)
        verify(wall.cols >= 2)
        verify(second.x >= 0)
        verify(second.x + second.width <= wall.width + 0.5)
        second.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(view.selected, "Night Drive")
        const tracks = findChild(view, "playlistTrackList")
        verify(tracks !== null)
        compare(tracks.cols, 2)
        verify(findChild(view, "playlistSelectedMosaic") !== null)
        compare(findChild(view, "playlistLeadTrack"), null)
        compare(tracks.count, view.displayTracks.length)
        verify(findChild(view, "librarySleeveTrackArt_0") !== null)
        verify(tracks.x >= 0)
        verify(tracks.x + tracks.width <= tracks.parent.width + 0.5)
    }

    function test_sort_field_and_direction_drive_the_play_projection() {
        view.openPlaylist("Dark Passage")
        compare(view.sortKey, "playlist")
        compare(view.sortDescending, false)
        compare(view.displayTracks[0].title, "Zulu")

        view.sortDescending = true
        compare(view.displayTracks[0].title, "Middle")

        view.sortKey = "title"
        view.sortDescending = false
        compare(view.displayTracks[0].title, "Alpha")
        compare(view.fileList[0], "Dark Passage/02.flac")
        compare(view.displayTracks[1].title, "Middle")

        view.sortDescending = true
        compare(view.displayTracks[0].title, "Zulu")
        compare(view.fileList[0], "Dark Passage/01.flac")

        view.sortKey = "artist"
        view.sortDescending = false
        compare(view.displayTracks[0].title, "Middle")
        view.sortDescending = true
        compare(view.displayTracks[0].title, "Alpha")

        view.sortKey = "added"
        view.sortDescending = false
        compare(view.displayTracks[0].title, "Alpha")
        view.sortDescending = true
        compare(view.displayTracks[0].title, "Zulu")

        const picker = findChild(view, "playlistSortPicker")
        const direction = findChild(view, "playlistSortDirection")
        verify(picker !== null && direction !== null)
        compare(picker.height, 44)
        compare(direction.height, 44)
        compare(view.sortOptions.length, 4)
    }

    function test_compact_wall_and_actions_remain_reachable() {
        testCase.width = 620
        view.width = 620
        wait(0)
        const wall = findChild(view, "playlistWall")
        compare(wall.cols, 2)
        view.openPlaylist("Dark Passage")
        wait(0)
        const queue = findChild(view, "playlistQueueAction")
        const shuffle = findChild(view, "playlistShuffleAction")
        const play = findChild(view, "playlistPlayAction")
        const tracks = findChild(view, "playlistTrackList")
        verify(queue !== null && shuffle !== null && play !== null)
        compare(tracks.cols, 1)
        compare(findChild(view, "playlistLeadTrack"), null)
        compare(tracks.count, view.displayTracks.length)
        compare(queue.height, 44)
        compare(shuffle.height, 44)
        compare(play.height, 44)
        play.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(provider.actions.length, 1)
        compare(provider.actions[0].name, "Dark Passage")
        compare(provider.actions[0].index, 0)
        compare(provider.actions[0].files.length, view.fileList.length)
        compare(provider.actions[0].files[0], view.fileList[0])
    }
}
