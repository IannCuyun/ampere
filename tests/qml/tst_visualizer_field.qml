import QtQuick
import QtTest
import "../../qml"

TestCase {
    id: testCase
    name: "VisualizerFieldLifecycle"
    when: windowShown
    width: 936
    height: 700

    VisualizerField {
        id: field
        anchors.fill: parent
        active: false
    }

    function test_reusesGpuTargetAndStopsWithOwner() {
        compare(field.canvasRenderTarget, Canvas.Image)
        compare(field.animationRunning, false)
        field.active = true
        tryCompare(field, "animationRunning", true)
        field.active = false
        tryCompare(field, "animationRunning", false)
    }
}
