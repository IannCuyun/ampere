import unittest

from ampere.discover import DiscoverProjection
from ampere.mpdclient import Backend


class DiscoverProjectionTests(unittest.TestCase):
    def setUp(self):
        self.service = DiscoverProjection()

    def test_incomplete_cache_is_loading_with_stable_empty_lanes(self):
        result = self.service.build({})

        self.assertFalse(result["ready"])
        self.assertEqual(["loved", "arrivals", "deep"],
                         [lane["key"] for lane in result["lanes"]])
        self.assertEqual([0, 0, 0],
                         [lane["count"] for lane in result["lanes"]])
        self.assertTrue(all(not lane["entry"] for lane in result["lanes"]))

    def test_verified_empty_cache_is_ready_for_explicit_empty_state(self):
        result = self.service.build({
            "loved": [], "arrivals": [], "deep": [],
        })

        self.assertTrue(result["ready"])
        self.assertTrue(all(not lane["entry"] for lane in result["lanes"]))

    def test_lanes_prefer_distinct_albums_without_reordering_evidence(self):
        shared = {"file": "Rap/Artist/Shared/01.flac",
                  "artist": "Artist", "album": "Shared"}
        arrival = {"file": "Rap/Artist/New/01.flac",
                   "artist": "Artist", "album": "New"}
        deep = {"file": "Rock/Other/Deep/01.flac",
                "artist": "Other", "album": "Deep"}
        result = self.service.build({
            "loved": [shared],
            "arrivals": [shared, arrival],
            "deep": [shared, deep],
        })

        self.assertTrue(result["ready"])
        self.assertEqual(
            [shared["file"], arrival["file"], deep["file"]],
            [lane["entry"]["file"] for lane in result["lanes"]])
        self.assertEqual([1, 2, 2],
                         [lane["count"] for lane in result["lanes"]])

    def test_overlapping_only_lanes_remain_explicitly_empty(self):
        shared = {"file": "Rap/Artist/Shared/01.flac",
                  "artist": "Artist", "album": "Shared"}

        result = self.service.build({
            "loved": [shared],
            "arrivals": [shared],
            "deep": [shared],
        })

        self.assertEqual(
            [shared["file"], "", ""],
            [lane["entry"].get("file", "") for lane in result["lanes"]])
        self.assertEqual([1, 1, 1],
                         [lane["count"] for lane in result["lanes"]])

    def test_track_artists_do_not_split_one_album_folder(self):
        lead = {"file": "Compilations/Shared/01.flac",
                "artist": "Lead", "album": "Shared"}
        guest = {"file": "Compilations/Shared/02.flac",
                 "artist": "Guest", "album": "Shared"}

        result = self.service.build({
            "loved": [lead],
            "arrivals": [guest],
            "deep": [],
        })

        self.assertEqual(lead["file"], result["lanes"][0]["entry"]["file"])
        self.assertEqual({}, result["lanes"][1]["entry"])

    def test_same_tags_in_distinct_folders_remain_distinct_releases(self):
        original = {"file": "Artist/Original/01.flac",
                    "albumartist": "Artist", "album": "Same Title"}
        remaster = {"file": "Artist/Remaster/01.flac",
                    "albumartist": "Artist", "album": "Same Title"}

        result = self.service.build({
            "loved": [original],
            "arrivals": [remaster],
            "deep": [],
        })

        self.assertEqual(
            [original["file"], remaster["file"]],
            [result["lanes"][0]["entry"]["file"],
             result["lanes"][1]["entry"]["file"]])

    def test_release_files_preserve_folder_and_album_tag_membership(self):
        chosen = {"file": "Metal/Signs/death-whistle.flac",
                  "album": "Absolvere", "artist": "Signs"}
        sibling = {"file": "Metal/Signs/iwontletyoudie.flac",
                   "album": "Amongst the Low & Empty", "artist": "Signs"}
        second = {"file": "Metal/Signs/death-path.flac",
                  "album": "Absolvere", "artist": "Signs"}
        library = {row["file"]: row for row in (chosen, sibling, second)}

        result = self.service.build({
            "loved": [chosen], "arrivals": [], "deep": [],
        }, library=library)

        self.assertEqual(
            [chosen["file"], second["file"]],
            result["lanes"][0]["entry"]["files"])

    def test_root_level_tracks_share_a_tagged_release_identity(self):
        first = {"file": "01.flac", "album": "Root Record"}
        second = {"file": "02.flac", "album": "Root Record"}
        library = {row["file"]: row for row in (first, second)}

        result = self.service.build({
            "loved": [first], "arrivals": [second], "deep": [],
        }, library=library)

        self.assertEqual(["01.flac", "02.flac"],
                         result["lanes"][0]["entry"]["files"])
        self.assertEqual({}, result["lanes"][1]["entry"])

    def test_untagged_files_remain_explicit_single_file_releases(self):
        first = {"file": "Loose/01.flac", "album": ""}
        second = {"file": "Loose/02.flac", "album": ""}
        library = {row["file"]: row for row in (first, second)}

        result = self.service.build({
            "loved": [first], "arrivals": [second], "deep": [],
        }, library=library)

        self.assertEqual(["Loose/01.flac"],
                         result["lanes"][0]["entry"]["files"])
        self.assertEqual(["Loose/02.flac"],
                         result["lanes"][1]["entry"]["files"])

    def test_projection_returns_copies_not_mutable_cache_aliases(self):
        source = {"file": "Folk/Artist/Album/01.flac",
                  "artist": "Artist", "album": "Album"}
        shelves = {"loved": [source], "arrivals": [], "deep": []}

        result = self.service.build(shelves)
        result["lanes"][0]["entry"]["album"] = "Changed"

        self.assertEqual("Album", source["album"])

    def test_backend_slot_reads_only_the_cached_projection(self):
        backend = type("Harness", (), {})()
        shelves = {
            "loved": [{"file": "A/B/C.flac"}],
            "arrivals": [],
            "deep": [],
        }
        backend._discover_overview = self.service.build(
            shelves, library={"A/B/C.flac": {"file": "A/B/C.flac"}})

        result = Backend.discoverOverview(backend)

        self.assertTrue(result["ready"])
        self.assertEqual("A/B/C.flac", result["lanes"][0]["entry"]["file"])
        self.assertEqual(["A/B/C.flac"],
                         result["lanes"][0]["entry"]["files"])
        result["lanes"][0]["entry"]["files"].append("changed.flac")
        self.assertEqual(
            ["A/B/C.flac"],
            backend._discover_overview["lanes"][0]["entry"]["files"])


if __name__ == "__main__":
    unittest.main()
