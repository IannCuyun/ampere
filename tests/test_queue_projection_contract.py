import unittest
from pathlib import Path
import re

from ampere.mpdclient import Backend


class QueueProjectionContractTests(unittest.TestCase):
    def test_always_alive_queue_facts_do_not_copy_the_full_queue(self):
        backend = type("BackendStub", (), {})()
        backend._queue_pos = 1
        backend._queue = [
            {"file": f"track-{index}", "duration": 10 + index}
            for index in range(30)
        ]

        self.assertEqual(30, Backend.queueLength.fget(backend))
        self.assertEqual(28, Backend.queueRemainingCount.fget(backend))
        self.assertEqual(12, len(Backend.upcomingQueue.fget(backend)))
        self.assertEqual("track-2", Backend.upcomingQueue.fget(backend)[0]["file"])

    def test_hidden_queue_surfaces_gate_full_qvariant_list_access(self):
        qml = Path(__file__).parents[1] / "qml"
        main = (qml / "Main.qml").read_text()
        queue_pane = (qml / "QueuePane.qml").read_text()
        gallery = (qml / "GalleryNowPlayingView.qml").read_text()

        self.assertIn("GalleryNowPlayingView {", main)
        self.assertIsNone(re.search(r"(?m)^\s*NowPlayingView\s*\{", main))
        self.assertIn("pane.visible ? backend.queue.filter", queue_pane)
        self.assertIn("view.queueOpen ? backend.queue.filter", gallery)

    def test_gallery_queue_rows_keep_accessible_keyboard_activation(self):
        gallery = (
            Path(__file__).parents[1] / "qml" / "GalleryNowPlayingView.qml"
        ).read_text()
        queue_rows = gallery.split("id: queueList", 1)[1].split(
            "anchors.centerIn: queueList", 1
        )[0]

        self.assertIn("id: queueTrack", queue_rows)
        self.assertIn("activeFocusOnTab: true", queue_rows)
        self.assertIn("Accessible.role: Accessible.Button", queue_rows)
        self.assertIn("Accessible.name: \"Play \"", queue_rows)
        self.assertIn(
            "Accessible.onPressAction: view.playQueueRow(modelData)",
            queue_rows,
        )
        self.assertIn(
            "Keys.onReturnPressed: view.playQueueRow(modelData)",
            queue_rows,
        )
        self.assertIn(
            "Keys.onSpacePressed: view.playQueueRow(modelData)",
            queue_rows,
        )
        self.assertIn("border.width: queueTrack.activeFocus ? 1 : 0", queue_rows)


if __name__ == "__main__":
    unittest.main()
