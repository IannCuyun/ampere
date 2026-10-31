import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "DoctorConditionTheatreBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property var currentSong: ({
            file: "current.flac", title: "Current", artist: "Artist"
        })
        property var doctorReport: ({})
        property var preferred: []
        property int scans: 0
        signal doctorChanged()

        function runDoctor() { scans += 1 }
        function preferVersion(file) { preferred = preferred.concat([file]) }
    }

    DoctorView {
        id: doctor
        parent: testCase
        width: testCase.width
        height: testCase.height
        active: true
    }

    function populatedReport() {
        return {
            versionGroups: [
                {
                    title: "Signal",
                    artist: "The Artist",
                    files: [
                        {file: "record/signal.flac", plays: 8, pref: true},
                        {file: "single/signal.flac", plays: 2, pref: false}
                    ]
                },
                {
                    title: "Signal Two",
                    artist: "The Artist",
                    files: [
                        {file: "record/two.flac", plays: 3, pref: false},
                        {file: "single/two.flac", plays: 1, pref: true}
                    ]
                }
            ],
            lowBitrate: [{
                file: "lossy.mp3", title: "Lossy", artist: "Artist",
                album: "Record", kbps: 192
            }],
            missingRg: [],
            untagged: [],
            outliers: [],
            scanned: 4
        }
    }

    function init() {
        testCase.width = 1280
        provider.preferred = []
        provider.scans = 0
        provider.doctorReport = populatedReport()
        provider.doctorChanged()
        wait(0)
    }

    function test_report_uses_one_selected_condition_and_finding() {
        const index = findChild(doctor, "doctorConditionIndex")
        // Artist Aliases joined the index as a sixth row (SPEC UNDESIGNED
        // #17, Iann 2026-08-21).
        compare(index.count, 6)
        const firstCondition = findChild(doctor, "doctorCondition_0")
        verify(firstCondition !== null)
        verify(firstCondition.visible)
        verify(firstCondition.width >= 260,
               "desktop condition width=" + firstCondition.width
               + ", index width=" + index.width)
        verify(firstCondition.height >= 64)
        compare(doctor.selectedCondition, 0)
        compare(doctor.selectedFinding, 0)
        compare(doctor.selectedRows.length, 2)
        compare(doctor.selectedFile, "record/signal.flac")
        compare(doctor.secondaryFile, "single/signal.flac")
        compare(doctor.totalFindings, 3)

        doctor.moveFinding(1)
        compare(doctor.selectedFinding, 1)
        compare(doctor.selectedFile, "record/two.flac")

        doctor.selectCondition(1)
        compare(doctor.selectedFinding, 0)
        compare(doctor.selectedFile, "lossy.mp3")
        compare(doctor.titleFor(doctor.selectedData), "Lossy")
    }

    function test_scanning_and_clean_states_remain_distinct() {
        provider.doctorReport = {scanning: 220, total: 400}
        provider.doctorChanged()
        wait(0)
        verify(doctor.scanning)
        verify(!doctor.hasReport)

        provider.doctorReport = {
            versionGroups: [], lowBitrate: [], missingRg: [], untagged: [],
            outliers: [], scanned: 400
        }
        provider.doctorChanged()
        wait(0)
        verify(doctor.hasReport)
        verify(doctor.reportIsClean)
        compare(doctor.totalFindings, 0)
    }

    function test_compact_recomposes_index_above_the_stage() {
        testCase.width = 760
        wait(0)
        verify(doctor.compact)
        // Compact WRAPS the conditions rather than scrolling them sideways:
        // a horizontal rail put two of the six past the right edge with no
        // affordance (2026-08-22). The vertical ListView is desktop-only.
        const index = findChild(doctor, "doctorConditionIndex")
        const flow = findChild(doctor, "doctorConditionFlow")
        const detail = findChild(doctor, "doctorDetailScroll")
        verify(index !== null && flow !== null && detail !== null)
        verify(!index.visible)
        verify(flow.visible)
        verify(flow.y < detail.y)
        verify(flow.height >= 72)
    }
}
