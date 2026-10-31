import QtQuick
import QtTest
import "../../qml"

TestCase {
    id: testCase
    name: "GlowButtonResponsiveness"
    when: windowShown
    visible: true
    width: 180
    height: 100

    SignalSpy { id: clickSpy; target: button; signalName: "clicked" }

    GlowButton {
        id: button
        parent: testCase
        width: 64
        height: 44
        visible: true
        anchors.centerIn: parent
        icon: "play"
    }

    function test_press_acknowledges_before_release() {
        verify(button.visible)
        verify(button.enabled)
        mouseMove(button, button.width / 2, button.height / 2)
        wait(20)
        mousePress(button, button.width / 2, button.height / 2,
                   Qt.LeftButton)
        tryCompare(button, "pressed", true)
        tryVerify(function() { return button.scale < 1 }, 100)
        compare(clickSpy.count, 0)

        mouseRelease(button, button.width / 2, button.height / 2,
                     Qt.LeftButton)
        tryCompare(button, "pressed", false)
        compare(clickSpy.count, 1)
    }
}
