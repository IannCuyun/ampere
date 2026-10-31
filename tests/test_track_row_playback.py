import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrackRowPlaybackContractTests(unittest.TestCase):
    def test_direct_track_play_never_inherits_parent_album_exception(self):
        source = (ROOT / "qml/TrackRow.qml").read_text(encoding="utf-8")

        self.assertIn(
            "backend.playFiles(row.fileList, row.rowIndex)", source)
        self.assertNotIn("backend.playAlbum(row.fileList", source)
        self.assertNotIn("else row.playHere()", source)


if __name__ == "__main__":
    unittest.main()
