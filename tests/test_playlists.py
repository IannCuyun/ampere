import unittest

from ampere.playlists import PlaylistRepository


class PlaylistRepositoryTests(unittest.TestCase):
    def test_snapshots_normalize_mpd_rows_and_hide_disliked_store(self):
        repository = PlaylistRepository()
        repository.replace_playlists([
            {"playlist": "Focus"}, {"playlist": "Disliked"},
            {"playlist": "Road trip"},
        ])
        repository.replace_liked([{"file": "one.flac"}, "two.flac"])
        repository.replace_disliked([{"file": "bad.flac"}])
        self.assertEqual(("Focus", "Road trip"), repository.snapshot.playlists)
        self.assertEqual(("one.flac", "two.flac"), repository.snapshot.liked)
        self.assertEqual(["keep.flac", "bad.flac"], repository.filter_allowed(
            ["keep.flac", "bad.flac"], keep="bad.flac"))

    def test_playlist_name_rules_protect_builtin_and_collisions(self):
        repository = PlaylistRepository()
        repository.replace_playlists([{"playlist": "Focus"}])
        self.assertFalse(repository.can_rename("Liked", "Hearts")[0])
        self.assertFalse(repository.can_rename("Road trip", "Disliked")[0])
        self.assertFalse(repository.can_rename("Road trip", "Focus")[0])
        self.assertTrue(repository.can_rename("Road trip", "Driving")[0])
        self.assertFalse(repository.can_delete("Liked")[0])
        self.assertFalse(repository.can_delete("Disliked")[0])

    def test_ratings_use_half_star_units_and_fail_closed(self):
        self.assertEqual(4.5, PlaylistRepository.clamp_rating(4.74))
        self.assertEqual(5.0, PlaylistRepository.clamp_rating(9))
        self.assertEqual(3.5, PlaylistRepository.decode_rating("rating=7"))
        self.assertEqual(0.0, PlaylistRepository.decode_rating("broken"))

    def test_failed_catalog_publication_preserves_last_snapshot(self):
        repository = PlaylistRepository()
        repository.publish_playlists([{"playlist": "Focus"}])

        unavailable = repository.publish_playlists(None)
        malformed = repository.publish_playlists([{"playlist": "Road"}, 7])

        self.assertFalse(unavailable.success)
        self.assertFalse(malformed.success)
        self.assertEqual(("Focus",), repository.snapshot.playlists)

    def test_valid_empty_catalog_is_success_and_change_aware(self):
        repository = PlaylistRepository()
        first = repository.publish_playlists([])
        repository.publish_playlists([{"playlist": "Focus"}])
        emptied = repository.publish_playlists([])
        repeated = repository.publish_playlists([])

        self.assertTrue(first.success)
        self.assertFalse(first.changed)
        self.assertTrue(emptied.success and emptied.changed)
        self.assertFalse(repeated.changed)

    def test_complete_collection_generation_replaces_atomically(self):
        repository = PlaylistRepository()
        repository.replace_snapshot(
            playlists=("Old",), liked=("old-like",),
            disliked=("old-dislike",))

        changed = repository.replace_snapshot(
            playlists=("New",), liked=("new-like",), disliked=())

        self.assertEqual((True, True, True), changed)
        self.assertEqual(("New",), repository.snapshot.playlists)
        self.assertEqual(("new-like",), repository.snapshot.liked)
        self.assertEqual((), repository.snapshot.disliked)


if __name__ == "__main__":
    unittest.main()
