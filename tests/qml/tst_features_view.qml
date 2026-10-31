import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "FeaturesListeningAtlasBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 900

    property var backend: provider

    QtObject {
        id: provider
        signal librarySummaryChanged()
        property var currentSong: ({
            file: "Electronic/Artist/Album/01.flac",
            title: "Current track",
            artist: "Artist",
            album: "Album"
        })
        function requestLibrarySummary() {}
        function homeOverview() {
            return {
                ready: true,
                metrics: { week: 22, artists: 17 },
                shelves: {
                    history: [
                        { file: "A/One/01.flac", album: "One", artist: "A" },
                        { file: "B/Two/01.flac", album: "Two", artist: "B" },
                        { file: "C/Three/01.flac", album: "Three", artist: "C" }
                    ],
                    loved: [{ file: "D/Loved/01.flac", album: "Loved", artist: "D" }],
                    arrivals: [],
                    deep: [{ file: "E/Deep/01.flac", album: "Deep", artist: "E" }],
                    unfinished: []
                }
            }
        }
    }

    FeaturesView {
        id: features
        parent: testCase
        width: 1256
        height: 900
        active: true
    }

    SignalSpy {
        id: openSpy
        target: features
        signalName: "openFeature"
    }

    function init() {
        testCase.width = 1280
        testCase.height = 900
        features.width = 1256
        features.height = 900
        openSpy.clear()
        wait(25)
        var flick = findChild(features, "featuresAtlasFlick")
        if (flick) flick.contentY = 0
    }

    function test_truthful_feature_set_and_exact_activation() {
        compare(features.featureModes.join(","),
                "discover,rewind,ampy,ambient,eq,doctor,smart-shuffle,autoplay,disliked")

        var discover = findChild(features, "featureTile-discover")
        verify(discover !== null)
        discover.forceActiveFocus()
        tryCompare(discover, "activeFocus", true)
        keyClick(Qt.Key_Return)
        compare(openSpy.count, 1)
        compare(openSpy.signalArguments[0][0], "discover")

        var autoplay = findChild(features, "featureTile-autoplay")
        verify(autoplay !== null)
        autoplay.forceActiveFocus()
        tryCompare(autoplay, "activeFocus", true)
        keyClick(Qt.Key_Space)
        compare(openSpy.count, 2)
        compare(openSpy.signalArguments[1][0], "autoplay")
    }

    function test_all_tiles_keep_accessible_target_geometry() {
        for (var index = 0; index < features.featureModes.length; ++index) {
            var tile = findChild(features,
                                 "featureTile-" + features.featureModes[index])
            verify(tile !== null, features.featureModes[index])
            verify(tile.width >= 44, features.featureModes[index] + " width")
            verify(tile.height >= 44, features.featureModes[index] + " height")
            verify(tile.activeFocusOnTab, features.featureModes[index] + " tab focus")
        }
    }

    function test_desktop_preserves_the_irregular_art_led_first_fold() {
        var intro = findChild(features, "featuresAtlasIntro")
        var discover = findChild(features, "featureTile-discover")
        var rewind = findChild(features, "featureTile-rewind")
        var ampy = findChild(features, "featureTile-ampy")
        var eq = findChild(features, "featureTile-eq")
        var doctor = findChild(features, "featureTile-doctor")
        verify(intro && discover && rewind && ampy && eq && doctor)

        var introOrigin = intro.mapToItem(features, 0, 0)
        var discoverOrigin = discover.mapToItem(features, 0, 0)
        var rewindOrigin = rewind.mapToItem(features, 0, 0)
        var eqOrigin = eq.mapToItem(features, 0, 0)

        verify(introOrigin.x + intro.width < discoverOrigin.x)
        verify(discover.width > rewind.width)
        verify(discover.height > rewind.height)
        compare(discoverOrigin.y, rewindOrigin.y)
        verify(eqOrigin.y >= discoverOrigin.y + discover.height)
        verify(eq.width > doctor.width)
        verify(eqOrigin.y + eq.height <= features.height + 0.5)
    }

    function test_compact_is_a_scrollable_two_column_continuation() {
        features.width = 720
        features.height = 384
        wait(50)

        var flick = findChild(features, "featuresAtlasFlick")
        var discover = findChild(features, "featureTile-discover")
        var rewind = findChild(features, "featureTile-rewind")
        var ampy = findChild(features, "featureTile-ampy")
        var autoplay = findChild(features, "featureTile-autoplay")
        var disliked = findChild(features, "featureTile-disliked")
        verify(flick && discover && rewind && ampy && autoplay && disliked)
        verify(flick.contentHeight > flick.height)

        var discoverOrigin = discover.mapToItem(features, 0, 0)
        var rewindOrigin = rewind.mapToItem(features, 0, 0)
        var ampyOrigin = ampy.mapToItem(features, 0, 0)
        compare(Math.round(discover.width), Math.round(flick.width - 40))
        compare(Math.round(rewindOrigin.y), Math.round(ampyOrigin.y))
        verify(ampyOrigin.x > rewindOrigin.x + rewind.width)
        verify(rewindOrigin.y >= discoverOrigin.y + discover.height)

        flick.contentY = flick.contentHeight - flick.height
        wait(25)
        var autoplayVisible = autoplay.mapToItem(features, 0, 0)
        var dislikedVisible = disliked.mapToItem(features, 0, 0)
        verify(autoplayVisible.y >= 0)
        verify(dislikedVisible.y >= 0)
        verify(autoplayVisible.y + autoplay.height <= features.height + 0.5)
        verify(dislikedVisible.y + disliked.height <= features.height + 0.5)
        compare(Math.round(autoplayVisible.y), Math.round(dislikedVisible.y))
        verify(dislikedVisible.x > autoplayVisible.x + autoplay.width)
    }
}
