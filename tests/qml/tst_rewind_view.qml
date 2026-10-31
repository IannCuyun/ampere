import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "RewindMemoryArc"
    when: windowShown
    width: 1280
    height: 900

    property var backend: provider

    QtObject {
        id: provider
        signal databaseUpdated
        signal librarySummaryChanged
        signal soundProfileChanged
        signal recapSaveFinished(string name, bool success)

        function requestLibrarySummary() {}
        function requestSoundProfile() {}
        function soundProfile() { return {ready: true, summary: "A dark, melodic room."} }
        function saveRecap(_key) { return true }
        function rewindOverview() {
            var days = []
            var base = 1786752000
            for (var i = 0; i < 14; ++i) {
                days.push({
                    label: "Day " + String(i + 1),
                    count: i + 1,
                    t0: base + i * 86400,
                    t1: base + (i + 1) * 86400,
                    file: "Music/Album " + i + "/song.flac",
                    title: "Song " + i,
                    artist: "Artist " + i,
                    album: "Album " + i,
                    records: i % 4 + 1
                })
            }
            return {
                ready: true,
                stats: {totalPlays: 1713, hours: 107, tracksPlayed: 980, week: 319},
                history: {days: days, rows: []},
                chapters: []
            }
        }
    }

    RewindView {
        id: rewind
        parent: testCase
        width: 1256
        height: 820
        active: true
    }

    function init() {
        rewind.width = 1256
        rewind.height = 820
        rewind.tab = "listening"
        rewind.reload()
        wait(40)
    }

    function test_desktopUsesSevenDayContactSheetAndSelectedArc() {
        var room = findChild(rewind, "rewindMemoryRoom")
        var sleeve = findChild(rewind, "rewindSelectedSleeve")
        var sheet = findChild(rewind, "rewindContactSheet")
        verify(room !== null && sleeve !== null && sheet !== null)
        compare(rewind.contactDayCount, 7)
        compare(rewind.contactDays.length, 7)
        compare(rewind.selectedDayIndex, 13)
        compare(sleeve.width, sleeve.height)
        verify(sleeve.x >= 0 && sleeve.x + sleeve.width <= sleeve.parent.width + 0.5)
        verify(sheet.x >= 0 && sheet.x + sheet.width <= sheet.parent.width + 0.5)
    }

    function test_compactRecomposesToFiveDaysWithoutOverflow() {
        rewind.width = 680
        wait(40)
        var room = findChild(rewind, "rewindMemoryRoom")
        var sleeve = findChild(rewind, "rewindSelectedSleeve")
        var sheet = findChild(rewind, "rewindContactSheet")
        compare(rewind.contactDayCount, 5)
        compare(rewind.contactDays.length, 5)
        verify(sleeve.x >= 0 && sleeve.x + sleeve.width <= sleeve.parent.width + 0.5)
        verify(sheet.x >= 0 && sheet.x + sheet.width <= sheet.parent.width + 0.5)
        verify(room.height >= 650)
    }

    function test_low_height_scroll_reaches_the_existing_contact_sheet() {
        rewind.width = 720
        rewind.height = 384
        wait(40)
        var scroller = findChild(rewind, "rewindScroller")
        var sheet = findChild(rewind, "rewindContactSheet")
        verify(scroller !== null && sheet !== null)
        verify(scroller.contentHeight > scroller.height)

        scroller.contentY = scroller.contentHeight - scroller.height
        wait(0)
        var sheetInRewind = sheet.mapToItem(rewind, 0, 0)
        verify(sheetInRewind.y < rewind.height)
        verify(sheetInRewind.y + sheet.height <= rewind.height + 0.5)
    }

    function test_selectionAndPagingPreserveTheFullHistory() {
        rewind.selectDay(4)
        compare(rewind.selectedDayIndex, 4)
        compare(rewind.dayT0, rewind.h.days[4].t0)
        verify(rewind.contactPageStart <= 4)
        verify(rewind.contactPageStart + rewind.contactDayCount > 4)

        rewind.shiftContactPage(-1)
        compare(rewind.contactPageStart, 0)
        rewind.shiftContactPage(1)
        compare(rewind.contactPageStart, 7)
    }
}
