import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ToastFeedbackContractTests(unittest.TestCase):
    def test_backend_confirms_queue_actions_through_notice(self):
        src = (ROOT / "ampere" / "mpdclient.py").read_text(encoding="utf-8")
        self.assertIn("notice = Signal(str)", src)
        self.assertIn('"Added to queue" if count == 1 else f"Queued {count} tracks"', src)
        self.assertIn('self._queued_notice(1, "Playing next")', src)
        self.assertIn('self.notice.emit("Finding more like this…")', src)
        self.assertEqual(4, src.count("on_finished=self._queued_notice("))

    def test_toast_is_archive_wash_and_queues_confirmation_bursts(self):
        main = (ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        toast = main.split("id: toast\n", 1)[1].split("Connections {", 1)[0]
        self.assertIn("radius: 0", toast)
        self.assertIn("color: Qt.alpha(Theme.bgLow, 0.92)", toast)
        self.assertIn("border.color: Theme.washHair", toast)
        self.assertIn("color: Theme.washInk", toast)
        self.assertIn("font.family: Theme.font", toast)
        self.assertIn("if (pending.length >= 3) return", toast)
        self.assertIn("onTriggered: toast.next()", toast)
        self.assertIn("function onNotice(msg) { toast.show(msg) }", main)
        self.assertIn(
            'function onErrorOccurred(msg) { console.warn("Ampere backend: " + msg) }',
            main)
        self.assertNotIn("toast.show(msg, true)", main)
        self.assertNotIn("toast.visible = true", main)


if __name__ == "__main__":
    unittest.main()
