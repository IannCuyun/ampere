import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "DislikedContactSheetBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property bool deletingDisliked: false
        property string deleteMode: "server"
        property var artColors: []
        property var dislikedFiles: ["one.flac", "two.flac", "three.flac", "four.flac", "five.flac"]
        property var restored: []
        property var deleted: []
        signal dislikedChanged()
        signal librarySummaryChanged()

        function songInfo(file) {
            return {
                file: file,
                title: "Title " + file,
                artist: "Artist " + file,
                album: "Album " + file
            }
        }

        function toggleDislike(file) { restored = restored.concat([file]) }
        function deleteDislikedSongs(files) { deleted = Array.from(files) }
    }

    DislikedView {
        id: disliked
        parent: testCase
        width: testCase.width
        height: testCase.height
    }

    function init() {
        provider.deletingDisliked = false
        provider.deleteMode = "server"
        provider.dislikedFiles = ["one.flac", "two.flac", "three.flac", "four.flac", "five.flac"]
        provider.restored = []
        provider.deleted = []
        provider.dislikedChanged()
        provider.librarySummaryChanged()
        wait(0)
    }

    function test_initial_selection_centers_a_complete_five_sleeve_run() {
        compare(disliked.selectedIndex, 2)
        compare(disliked.selectedFile, "three.flac")
        const sheet = findChild(disliked, "dislikedContactSheet")
        verify(sheet !== null)
        verify(sheet.tileSize >= 220)
        verify(sheet.tileSize <= 300)
    }

    function test_async_collection_arrival_still_centers_the_third_sleeve() {
        provider.dislikedFiles = []
        provider.dislikedChanged()
        wait(0)
        compare(disliked.selectedIndex, -1)

        provider.dislikedFiles = ["one.flac", "two.flac", "three.flac", "four.flac", "five.flac"]
        provider.dislikedChanged()
        wait(0)
        compare(disliked.selectedIndex, 2)
        compare(disliked.selectedFile, "three.flac")
    }

    function test_concurrent_refresh_signals_keep_the_intended_center_selection() {
        provider.dislikedFiles = []
        provider.dislikedChanged()
        wait(0)
        compare(disliked.selectedIndex, -1)

        provider.dislikedFiles = ["one.flac", "two.flac", "three.flac", "four.flac", "five.flac"]
        provider.dislikedChanged()
        provider.librarySummaryChanged()
        wait(0)
        compare(disliked.selectedIndex, 2)
        compare(disliked.selectedFile, "three.flac")
    }

    function test_selection_and_restore_dispatch_the_exact_file() {
        disliked.selectIndex(1)
        wait(0)
        compare(disliked.selectedFile, "two.flac")
        disliked.restoreSelected()
        compare(provider.restored.length, 1)
        compare(provider.restored[0], "two.flac")
    }

    function test_delete_confirmation_keeps_selected_and_all_scopes_distinct() {
        disliked.selectIndex(3)
        wait(0)
        disliked.confirmSelectedDeletion()
        const dialog = findChild(disliked, "dislikedDeleteDialog")
        verify(dialog !== null)
        verify(dialog.visible)
        compare(dialog.count, 1)
        compare(dialog.files.length, 1)
        compare(dialog.files[0], "four.flac")

        dialog.visible = false
        disliked.confirmDeletion(provider.dislikedFiles,
                                  "Delete every disliked file?",
                                  provider.dislikedFiles.length)
        verify(dialog.visible)
        compare(dialog.count, 5)
        compare(dialog.files.length, 5)
        dialog.visible = false
    }

    function test_compact_recomposes_to_three_sleeve_geometry() {
        testCase.width = 680
        wait(0)
        verify(disliked.compact)
        const sheet = findChild(disliked, "dislikedContactSheet")
        verify(sheet.tileSize >= 148)
        verify(sheet.tileSize <= 220)
        verify(sheet.tileSize * 3 + sheet.spacing * 2 <= sheet.width + 1)
        testCase.width = 1280
    }

    function test_minimum_window_keeps_delete_all_visible_and_usable() {
        testCase.width = 720
        // The persistent player owns the remaining 96px of a 480px window.
        testCase.height = 384
        wait(0)
        const button = findChild(disliked, "dislikedDeleteAllCompact")
        verify(button !== null && button.visible && button.enabled)
        const position = button.mapToItem(disliked, 0, 0)
        verify(position.y >= 0)
        verify(position.y + button.height <= disliked.height)
        verify(button.height >= 44)
        mouseClick(button, button.width / 2, button.height / 2)
        const dialog = findChild(disliked, "dislikedDeleteDialog")
        verify(dialog.visible)
        compare(dialog.count, provider.dislikedFiles.length)
        compare(provider.deleted.length, 0)
        dialog.visible = false
        testCase.width = 1280
        testCase.height = 820
    }

    function test_empty_state_clears_selection_without_side_effects() {
        provider.dislikedFiles = []
        provider.dislikedChanged()
        wait(0)
        compare(disliked.selectedIndex, -1)
        compare(disliked.selectedFile, "")
        compare(provider.restored.length, 0)
        compare(provider.deleted.length, 0)
    }
}
