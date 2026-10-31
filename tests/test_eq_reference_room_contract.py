"""Source-level guards for the approved Parametric EQ Reference Room."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "qml" / "EqView.qml").read_text(encoding="utf-8")


class EqReferenceRoomContractTests(unittest.TestCase):
    def test_approved_split_pane_anatomy_is_present(self) -> None:
        self.assertIn('objectName: "eqReferenceRoom"', SOURCE)
        self.assertIn('objectName: "eqBandLedger"', SOURCE)
        self.assertIn('objectName: "eqResponseStage"', SOURCE)
        self.assertIn('objectName: "eqCurvePlot"', SOURCE)
        self.assertIn('objectName: "eqRegionIndex"', SOURCE)

    def test_compact_is_a_deliberate_ledger_and_curve_composition(self) -> None:
        self.assertIn("readonly property bool compact: width < 760", SOURCE)
        self.assertIn("Layout.preferredWidth: view.compact ? 128", SOURCE)
        self.assertIn("view.compact ? Math.max(328, scroller.height)", SOURCE)
        self.assertIn("height: compactMode ? 24 : 40", SOURCE)
        self.assertIn("anchors.bottom: regionIndex.top", SOURCE)
        self.assertIn("color: Qt.alpha(Theme.bgLow, 0.62)", SOURCE)
        self.assertIn("component MetricField: Item", SOURCE)
        self.assertIn("anchors.bottomMargin: 12", SOURCE)
        self.assertNotIn("anchors.bottomMargin: Theme.playerHeight + 12", SOURCE)

    def test_existing_eq_transactions_remain_reachable(self) -> None:
        required_calls = (
            "eq.setEnabled(",
            "eq.addBand()",
            "eq.removeBand(",
            "eq.applyPreset(",
            "eq.importAutoEq(",
            "eq.saveProfile()",
            "eq.selectVariant(",
            "eq.newVariant(",
            "eq.deleteVariant(",
            "eq.setToneBass(",
            "eq.setToneTreble(",
            "eq.setBalance(",
            "eq.setPreamp(",
            "eq.setBand(",
        )
        for call in required_calls:
            self.assertIn(call, SOURCE, call)

        self.assertIn("onPositionChanged: mouse =>", SOURCE)
        self.assertIn("onWheel: wheel =>", SOURCE)
        self.assertIn("activeFocusOnTab: true", SOURCE)
        self.assertIn("Accessible.onPressAction", SOURCE)


if __name__ == "__main__":
    unittest.main()
