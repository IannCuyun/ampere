import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "AmpyMixlineBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 900

    property var backend: provider

    QtObject {
        id: provider

        property bool connected: true
        property bool mixtapeBusy: false
        property var artColors: []
        property var currentSong: ({
            file: "Metal/Current/one.flac", album: "Current", artist: "Alpha"
        })
        property var ampyCalls: []
        property int summaryRequests: 0

        signal librarySummaryChanged()
        signal mixtapeFinished(string name, int count, bool started)

        function moodList() {
            return [
                { key: "hyped", label: "HYPED" },
                { key: "happy", label: "HAPPY" },
                { key: "angry", label: "ANGRY" },
                { key: "calm", label: "CALM" },
                { key: "sad", label: "SAD" },
                { key: "dark", label: "DARK" }
            ];
        }

        function homeOverview() {
            return {
                ready: true,
                shelves: {
                    deep: [
                        { file: "Metal/Deep/two.flac", album: "Deep", artist: "Beta" }
                    ],
                    loved: [
                        { file: "Folk/Loved/three.flac", album: "Loved", artist: "Gamma" }
                    ],
                    arrivals: [
                        { file: "Pop/New/four.flac", album: "New", artist: "Delta" }
                    ],
                    history: [],
                    unfinished: []
                }
            };
        }

        function requestLibrarySummary() {
            summaryRequests += 1;
        }

        function startAmpySession(minutes, mood) {
            if (mixtapeBusy)
                return false;
            ampyCalls = ampyCalls.concat([{ minutes: minutes, mood: mood }]);
            mixtapeBusy = true;
            return true;
        }
    }

    AmpyView {
        id: ampy
        parent: testCase
        width: 1256
        height: 820
        active: true
    }

    function init() {
        provider.mixtapeBusy = false;
        provider.ampyCalls = [];
        provider.summaryRequests = 0;
        ampy.width = 1256;
        ampy.height = 820;
        ampy.selectedMood = "";
        ampy.selectedMoodLabel = "";
        ampy.selectedMinutes = 45;
        ampy.say = "Choose the feeling and the clock. Nothing changes until Build & Play.";
        ampy.reload();
        wait(0);
    }

    function test_reload_prefers_dark_and_uses_cached_real_art() {
        compare(ampy.selectedMood, "dark");
        compare(ampy.selectedMoodLabel, "DARK");
        verify(ampy.previewRows.length >= 3);
        verify(provider.summaryRequests > 0);
    }

    function test_mood_and_duration_cycle_with_wraparound_without_side_effects() {
        ampy.cycleMood(1);
        compare(ampy.selectedMood, "hyped");
        ampy.cycleMood(-1);
        compare(ampy.selectedMood, "dark");

        ampy.selectedMinutes = 90;
        ampy.cycleMinutes(1);
        compare(ampy.selectedMinutes, 30);
        ampy.cycleMinutes(-1);
        compare(ampy.selectedMinutes, 90);
        compare(provider.ampyCalls.length, 0);
    }

    function test_build_and_play_submits_both_values_once() {
        ampy.selectedMood = "calm";
        ampy.selectedMoodLabel = "CALM";
        ampy.selectedMinutes = 60;

        var action = findChild(ampy, "ampyBuildAction");
        verify(action !== null);
        action.forceActiveFocus();
        tryCompare(action, "activeFocus", true);
        keyClick(Qt.Key_Return);

        compare(provider.ampyCalls.length, 1);
        compare(provider.ampyCalls[0].minutes, 60);
        compare(provider.ampyCalls[0].mood, "calm");
        ampy.buildAndPlay();
        compare(provider.ampyCalls.length, 1);
    }

    function test_controls_keep_symmetric_accessible_targets() {
        var names = [
            "ampyMoodPrevious", "ampyMoodNext",
            "ampyDurationPrevious", "ampyDurationNext",
            "ampyBuildAction"
        ];
        for (var i = 0; i < names.length; ++i) {
            var action = findChild(ampy, names[i]);
            verify(action !== null, names[i]);
            verify(action.width >= 44 && action.height >= 44, names[i]);
        }
        compare(findChild(ampy, "ampyMoodPrevious").width,
                findChild(ampy, "ampyDurationPrevious").width);
        compare(findChild(ampy, "ampyMoodNext").width,
                findChild(ampy, "ampyDurationNext").width);
    }

    function test_desktop_and_compact_lanes_stay_inside_the_view() {
        var widths = [1256, 680, 560];
        for (var index = 0; index < widths.length; ++index) {
            var targetWidth = widths[index];
            ampy.width = targetWidth;
            tryCompare(ampy, "width", targetWidth);
            var stage = findChild(ampy, "ampyStage");
            var options = findChild(ampy, "ampyOptionGroup");
            var action = findChild(ampy, "ampyBuildAction");
            tryVerify(function() {
                return stage.x >= 0
                    && stage.x + stage.width <= ampy.width + 0.5
                    && options.mapToItem(ampy, 0, 0).x >= -0.5
                    && options.mapToItem(ampy, options.width, 0).x
                        <= ampy.width + 0.5
                    && action.mapToItem(ampy, 0, 0).x >= -0.5
                    && action.mapToItem(ampy, action.width, 0).x
                        <= ampy.width + 0.5;
            }, 1000, "Mixline controls overflow at width " + targetWidth);
        }
    }
}
