import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase

    property var calls: []
    property var playedFiles: []
    property int playedIndex: -1
    property var queued: []
    property var committed: []
    property bool failNext: false

    function init() {
        dropdown.width = testCase.width;
        dropdown.height = testCase.height;
        dropdown.close();
        dropdown.query = "";
        dropdown.clearResults();
        calls = [];
        playedFiles = [];
        playedIndex = -1;
        queued = [];
        committed = [];
        failNext = false;
        wait(0);
    }

    function test_rapidTypingRunsOnlyFinalSearch() {
        dropdown.query = "me";
        wait(10);
        dropdown.query = "meta";
        wait(10);
        dropdown.query = "metal";
        compare(calls.length, 0);
        verify(dropdown.searchPending);
        wait(60);
        compare(calls.length, 1);
        compare(calls[0].query, "metal");
        compare(dropdown.allHits.length, 14);
        compare(dropdown.displayedSongs.length, 4);
        compare(dropdown.allAlbums.length, 5);
        compare(dropdown.allArtists.length, 7);
        compare(dropdown.sleeveItems.length, 12);
        compare(dropdown.bestKind, "song");
        compare(dropdown.resultsQuery, "metal");
        compare(dropdown.inFlightQuery, "");
        compare(dropdown.focus, false);
    }

    function test_bestMatchComesFromTheCatalog() {
        dropdown.query = "artist";
        wait(60);
        compare(dropdown.bestKind, "artist");
        compare(dropdown.bestItem.name, "Artist 0");
        verify(dropdown.bestExact);
    }

    function test_activatingASongQueuesOnlyThatSong() {
        dropdown.query = "metal";
        wait(60);
        dropdown.activateBest();
        compare(playedFiles.length, 1);
        compare(playedFiles[0], "track-0");
        compare(playedIndex, 0);
        compare(committed, ["metal"]);
        verify(!dropdown.opened);
    }

    function test_expandAllShowsEveryRowInsideTheRoom() {
        dropdown.query = "metal";
        wait(60);
        compare(dropdown.displayedSongs.length, 4);
        dropdown.expandAll();
        compare(dropdown.expanded, true);
        compare(dropdown.displayedSongs.length, 14);
        compare(committed, ["metal"]);
    }

    function test_returnBeforeResultsArriveExpandsOnArrival() {
        dropdown.query = "metal";
        dropdown.expandAll();
        verify(dropdown.expandOnArrival);
        wait(60);
        compare(dropdown.expanded, true);
        compare(dropdown.displayedSongs.length, 14);
    }

    function test_staleResultDoesNotReplaceCurrentProjection() {
        dropdown.query = "metal";
        wait(60);
        compare(dropdown.allHits[0].file, "track-0");
        dropdown.query = "current";
        dropdown.applyResults("metal", {
            "hits": [{"file": "stale", "title": "Stale"}],
            "albums": [], "artists": [], "suggestions": []
        });
        compare(dropdown.allHits[0].file, "track-0");
        wait(60);
        compare(dropdown.allHits[0].file, "track-0");
    }

    function test_olderSerialForTheSameQueryIsRejected() {
        dropdown.query = "metal";
        wait(60);
        var newest = dropdown.requestSerial;
        dropdown.applyResults("metal", {
            "serial": newest - 1,
            "hits": [{"file": "old-index", "title": "Old"}],
            "albums": [], "artists": [], "suggestions": []
        });
        compare(dropdown.allHits[0].file, "track-0");
        dropdown.applyResults("metal", {
            "serial": newest,
            "hits": [{"file": "fresh", "title": "Fresh"}],
            "albums": [], "artists": [], "suggestions": []
        });
        compare(dropdown.allHits[0].file, "fresh");
    }

    function test_failureEndsPendingAndStatesItself() {
        failNext = true;
        dropdown.query = "metal";
        wait(60);
        compare(dropdown.inFlightQuery, "");
        compare(dropdown.failure, "index exploded");
        verify(dropdown.opened);
        var line = findChild(dropdown, "searchFailureLine");
        verify(line !== null);
        verify(line.visible);
    }

    function test_shortQueryKeepsRestoredResultsAndHintsAtOneChar() {
        dropdown.query = "system";
        verify(dropdown.searchPending);
        wait(60);
        compare(dropdown.allHits.length, 14);
        dropdown.query = "s";
        verify(!dropdown.searchPending);
        verify(dropdown.hintOnly);
        verify(dropdown.opened);
        wait(60);
        compare(calls.length, 1);
        compare(dropdown.allHits.length, 14);
        dropdown.query = "";
        compare(dropdown.allHits.length, 14);
        verify(dropdown.opened);
    }

    function test_keyboardWalkIsFlatAcrossHeroSleevesAndRows() {
        dropdown.width = 1200;
        dropdown.height = 800;
        dropdown.query = "metal";
        wait(60);
        var items = dropdown.navItems();
        var sleevesAll = findChild(dropdown, "searchSleevesAllLink");
        compare(items.length, 1 + 12 + (sleevesAll.visible ? 1 : 0) + 4 + 1);
        dropdown.focusFirst();
        compare(items[0].activeFocus, true);
        dropdown.focusRelative(items[0], 1);
        compare(items[1].activeFocus, true);
        dropdown.focusRelative(items[1], -1);
        compare(items[0].activeFocus, true);
    }

    function test_sleeveRowExpandsIntoAWrappingGrid() {
        dropdown.width = 1100;
        dropdown.height = 800;
        dropdown.query = "metal";
        wait(60);
        var link = findChild(dropdown, "searchSleevesAllLink");
        var fade = findChild(dropdown, "searchSleeveFade");
        var grid = findChild(dropdown, "searchSleeveGrid");
        var songsHeader = findChild(dropdown, "searchSongsHeader");
        // The sleeve Row measures after its Repeater has populated. Under a
        // full-suite load that deferred layout can land just after the search
        // result itself, so wait for the overflow geometry we are testing.
        tryVerify(function() { return link.visible; });
        tryVerify(function() { return fade.visible; });
        verify(!grid.visible);
        dropdown.sleevesExpanded = true;
        tryVerify(function() { return grid.visible && grid.height > 150 * 2; });
        verify(!link.visible);
        verify(songsHeader.mapToItem(dropdown, 0, 0).y
               >= grid.mapToItem(dropdown, 0, grid.height).y);
        compare(dropdown.navItems().length, 1 + 12 + 4 + 1);
    }

    function test_desktopPlacesBestMatchBesideTheLedger() {
        dropdown.width = 1200;
        dropdown.height = 800;
        dropdown.query = "metal";
        wait(60);
        var hero = findChild(dropdown, "searchBestMatch");
        var songs = findChild(dropdown, "songsLedger");
        var sleeves = findChild(dropdown, "searchSleeveRow");
        verify(hero !== null);
        verify(songs !== null);
        verify(sleeves !== null);
        compare(hero.width, 420);
        verify(songs.mapToItem(dropdown, 0, 0).x >= hero.mapToItem(dropdown, 0, 0).x + 420 + 64);
        verify(sleeves.mapToItem(dropdown, 0, 0).y < songs.mapToItem(dropdown, 0, 0).y);
    }

    function test_compactStacksBestMatchAboveTheLedger() {
        dropdown.width = 948;
        dropdown.height = 800;
        dropdown.query = "metal";
        wait(60);
        var hero = findChild(dropdown, "searchBestMatch");
        var songs = findChild(dropdown, "songsLedger");
        // Stacked, the best match owns the full content width and the
        // SLEEVE is what gives way — the desktop 420 belongs to the sleeve,
        // not to the column (corrected 2026-08-23).
        verify(dropdown.compact);
        verify(dropdown.sleeveSide < 420);
        verify(hero.width > 420);
        verify(songs.mapToItem(dropdown, 0, 0).y > hero.mapToItem(dropdown, 0, 0).y + hero.height - 1);
    }

    name: "SearchRecordWall"
    when: windowShown
    // Without this the TestCase itself is invisible and Qt Quick propagates
    // that to every child, so four assertions on `visible` could never pass
    // (found 2026-08-23; the suite had never run — see 951ea6f).
    visible: true
    width: 700
    height: 600

    QtObject {
        id: provider

        signal quickSearchReady(string query, var result)
        signal quickSearchFailed(string query, int serial, string reason)
        signal artistBioReady(string artist, var info)
        signal lyricsIndexChanged()

        function requestQuickSearch(searchQuery, serial) {
            testCase.calls.push({"query": searchQuery, "serial": serial});
            if (testCase.failNext) {
                testCase.failNext = false;
                quickSearchFailed(searchQuery, serial, "index exploded");
                return;
            }
            var tracks = [];
            var artists = [];
            var albums = [];
            for (var i = 0; i < 14; ++i) tracks.push({
                "file": "track-" + i,
                "title": "Track " + i,
                "artist": "Artist",
                "album": "Album " + i,
                "duration": 180 + i,
                "format": "FLAC",
                "disambiguate": false
            })
            for (var j = 0; j < 7; ++j) artists.push({
                "name": "Artist " + j,
                "path": "artist-" + j
            })
            for (var k = 0; k < 5; ++k) albums.push({
                "album": "Album " + k,
                "artist": "Artist",
                "cover": "track-" + k,
                "dir": "artist/album-" + k,
                "nameMatch": true,
                "matchingSongs": 1
            })
            var artistFirst = searchQuery === "artist";
            quickSearchReady(searchQuery, {
                "serial": serial,
                "hits": tracks,
                "suggestions": [],
                "artists": artists,
                "albums": albums,
                "artistFirst": artistFirst,
                "best": artistFirst
                    ? {"kind": "artist", "item": artists[0], "exact": true}
                    : {"kind": "song", "item": tracks[0], "exact": true}
            });
        }

        function requestArtistBio(artistName) {
            artistBioReady(artistName, {"portrait": "portrait-key"});
        }

        function playFiles(files, index) {
            testCase.playedFiles = files;
            testCase.playedIndex = index;
        }
        function queuePath(file) { testCase.queued.push(file); }
    }

    SearchDropdown {
        id: dropdown

        parent: testCase
        width: testCase.width
        height: testCase.height
        debounceInterval: 40
        searchProvider: provider
        actionProvider: provider
        bioProvider: provider
        onQueryCommitted: q => testCase.committed.push(q)
    }

}
