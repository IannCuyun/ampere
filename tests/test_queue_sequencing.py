import unittest

from ampere.queue_sequencing import QueueSequencer


class QueueSequencerTests(unittest.TestCase):
    def test_artist_spread_defers_repeated_artist_without_losing_membership(self):
        files = ["A/01", "A/02", "B/01", "A/03"]
        self.assertEqual(
            ["A/01", "B/01", "A/02", "A/03"],
            QueueSequencer.artist_spread(files),
        )

    def test_artist_metadata_spreads_tracks_across_different_album_folders(self):
        files = [
            "Rap/Trap/Artist A/Album One/01.flac",
            "Rap/Trap/Artist A/Album Two/01.flac",
            "Rap/Trap/Artist B/Album/01.flac",
            "Rap/Trap/Artist C/Album/01.flac",
        ]
        artists = {
            files[0]: "Artist A", files[1]: "artist a",
            files[2]: "Artist B", files[3]: "Artist C",
        }

        self.assertEqual(
            [files[0], files[2], files[1], files[3]],
            QueueSequencer.artist_spread(files, artist_keys=artists),
        )

    def test_greedy_spread_uses_later_candidates_before_unavoidable_repeat(self):
        files = ["A/1", "A/2", "A/3", "B/1", "C/1"]
        artists = {file: file.split("/", 1)[0] for file in files}

        result = QueueSequencer.artist_spread(
            files, window=2, artist_keys=artists)

        self.assertEqual(["A/1", "B/1", "C/1", "A/2", "A/3"], result)
        self.assertCountEqual(files, result)

    def test_spread_does_not_leave_an_avoidable_repeat_at_the_tail(self):
        files = ["B/1", "C/1", "A/1", "A/2"]
        artists = {file: file.split("/", 1)[0] for file in files}

        result = QueueSequencer.artist_spread(files, artist_keys=artists)

        self.assertFalse(any(
            artists[left] == artists[right]
            for left, right in zip(result, result[1:])))

    def test_album_successors_are_local_and_filename_sorted(self):
        entries = [
            {"song": {"file": "Album/02.flac"}},
            {"song": {"file": "Other/01.flac"}},
            {"song": {"file": "Album/01.flac"}},
            {"missing": True},
        ]
        self.assertEqual(
            {"Album/01.flac": "Album/02.flac"},
            QueueSequencer.album_successors(entries),
        )

    def test_gapless_extension_is_chain_bounded_and_deduplicated(self):
        sequencer = QueueSequencer(chain_limit=2)
        result = sequencer.extend_gapless(
            ["Album/01", "Other/01", "Album/02"],
            tail_levels={"Album/01": -10, "Album/02": -12, "Album/03": -9},
            successors={
                "Album/01": "Album/02",
                "Album/02": "Album/03",
                "Album/03": "Album/04",
            },
        )
        self.assertEqual(["Album/01", "Album/02", "Album/03", "Other/01"], result)

    def test_shuffle_uses_injected_randomizer_then_spreads_artists(self):
        def reverse(values):
            values.reverse()

        sequencer = QueueSequencer(shuffle=reverse)
        self.assertEqual(
            ["A/02", "B/01", "A/01"],
            sequencer.shuffle_order(["A/01", "B/01", "A/02"]),
        )

    def test_shuffle_passes_metadata_identity_to_artist_spread(self):
        sequencer = QueueSequencer(shuffle=lambda _values: None)
        files = ["A/One/1", "A/Two/1", "B/One/1"]

        self.assertEqual(
            [files[0], files[2], files[1]],
            sequencer.shuffle_order(files, artist_keys={
                files[0]: "A", files[1]: "A", files[2]: "B"}),
        )

    def test_reshuffle_preserves_played_and_current_window_boundary(self):
        def reverse(values):
            values.reverse()

        queue = [
            {"id": "1", "file": "played", "artist": "P"},
            {"id": "2", "file": "current", "artist": "C"},
            {"id": "3", "file": "next-a", "artist": "A"},
            {"id": "4", "file": "next-b", "artist": "B"},
        ]
        plan = QueueSequencer(shuffle=reverse).reshuffle_upcoming(queue, 1)

        self.assertEqual(2, plan.start)
        self.assertEqual(("4", "3"), plan.song_ids)
        self.assertEqual("", plan.blocked_reason)

    def test_reshuffle_keeps_duplicate_files_distinct_by_song_id(self):
        queue = [
            {"id": "7", "file": "same.flac", "artist": "A"},
            {"id": "8", "file": "same.flac", "artist": "A"},
        ]
        plan = QueueSequencer(shuffle=lambda values: values.reverse()) \
            .reshuffle_upcoming(queue, -1)

        self.assertEqual(("8", "7"), plan.song_ids)

    def test_reshuffle_blocks_rendered_transition_entries(self):
        plan = QueueSequencer().reshuffle_upcoming([
            {"id": "1", "file": "song.flac", "artist": "A"},
            {"id": "2", "file": "/cache/bridge.wav", "artist": ""},
        ], 0)

        self.assertIn("DJ transitions", plan.blocked_reason)
        self.assertEqual((), plan.song_ids)


if __name__ == "__main__":
    unittest.main()
