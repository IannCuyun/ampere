"""Source characterization for the selected Pocket Horizon window contract.

Behavioral seek and containment coverage lives in tests/qml/tst_player_bar.qml.
These checks only keep the QML shell's exact mini-window constants visible.
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlaybackCompactSourceCharacterization(unittest.TestCase):
    def test_mini_window_requests_the_selected_560_by_96_composition(self):
        main = (ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        mini = main.split("function toggleMini()", 1)[1].split(
            "// sleep timer", 1)[0]
        self.assertIn("minimumWidth: mini ? 560 : 720", main)
        self.assertIn("minimumHeight: mini ? 96 : 480", main)
        self.assertIn("width = 560", mini)
        self.assertIn("height = 96", mini)
        self.assertIn("_restoreVisibility = visibility", mini)
        self.assertIn("visibility = _restoreVisibility", mini)


if __name__ == "__main__":
    unittest.main()
