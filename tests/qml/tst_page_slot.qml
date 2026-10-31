import QtQuick
import QtTest
import "../../qml"

TestCase {
    id: testCase
    name: "PageSlot"
    when: windowShown

    width: 900
    height: 600

    Component {
        id: slotComponent
        PageSlot {
            width: 600
            height: 400
            current: true

            Rectangle {
                anchors.fill: parent
                color: "black"
            }
        }
    }

    function test_activeGeometryCoalescesBeforeNextFrame() {
        var slot = createTemporaryObject(slotComponent, testCase)
        verify(slot !== null)
        compare(slot.contentWidth, 600)
        compare(slot.contentHeight, 400)

        // Native width and height notifications are coalesced into one latest
        // geometry pair before the next rendered frame. No mixed-aspect layout
        // is exposed and no scale transform is involved.
        slot.width = 840
        slot.height = 540
        tryCompare(slot, "contentWidth", 840)
        compare(slot.contentHeight, 540)

        slot.current = false
        slot.width = 760
        slot.height = 500
        compare(slot.contentWidth, 840)
        compare(slot.contentHeight, 540)

        slot.current = true
        compare(slot.contentWidth, 760)
        compare(slot.contentHeight, 500)
    }
}
