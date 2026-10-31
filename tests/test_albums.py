import unittest

from ampere.albums import AlbumPresenter, ChapterDetector


class AlbumPresenterTests(unittest.TestCase):
    def test_single_artist_album_preserves_track_order_and_totals_duration(self):
        library = {
            "Artist/Album/02.flac": {"file": "Artist/Album/02.flac",
                                       "album": "The Album", "artist": "Artist",
                                       "duration": "120"},
            "Artist/Album/01.flac": {"file": "Artist/Album/01.flac",
                                       "album": "The Album", "artist": "Artist",
                                       "duration": 180},
        }
        result = AlbumPresenter.present(
            "Artist/Album", files=["Artist/Album/01.flac", "Artist/Album/02.flac"],
            library=library, year="2024")
        self.assertEqual(result["album"], "The Album")
        self.assertEqual(result["artist"], "Artist")
        self.assertEqual(result["year"], "2024")
        self.assertEqual(result["total"], 300)
        self.assertEqual([track["file"] for track in result["tracks"]],
                         ["Artist/Album/01.flac", "Artist/Album/02.flac"])
        self.assertEqual(result["cover"], "Artist/Album/01.flac")

    def test_compilation_and_empty_album_have_honest_fallbacks(self):
        compilation = AlbumPresenter.present(
            "Compilations/Mix", files=["a.flac", "b.flac"], library={
                "a.flac": {"file": "a.flac", "artist": "A", "duration": "bad"},
                "b.flac": {"file": "b.flac", "artist": "B", "duration": 60},
            })
        empty = AlbumPresenter.present("Artist/Untitled", files=[], library={})
        self.assertEqual(compilation["artist"], "VARIOUS ARTISTS")
        self.assertEqual(compilation["album"], "Mix")
        self.assertEqual(compilation["total"], 60)
        self.assertEqual(empty["album"], "Untitled")
        self.assertEqual(empty["cover"], "")

    def test_album_artist_excludes_featured_track_credits(self):
        files = ["Rap/Travis Scott/UTOPIA/01.flac",
                 "Rap/Travis Scott/UTOPIA/02.flac"]
        result = AlbumPresenter.present(
            "Rap/Travis Scott/UTOPIA", files=files, library={
                files[0]: {"file": files[0], "album": "UTOPIA",
                           "artist": "Travis Scott",
                           "albumartist": "Travis Scott"},
                files[1]: {"file": files[1], "album": "UTOPIA",
                           "artist": "Travis Scott Feat. Drake",
                           "albumartist": "Travis Scott"},
            })
        self.assertEqual(result["artist"], "Travis Scott")

    def test_discography_folder_is_legacy_primary_artist_fallback(self):
        files = ["Rap/Travis Scott/UTOPIA/01.flac",
                 "Rap/Travis Scott/UTOPIA/02.flac"]
        result = AlbumPresenter.present(
            "Rap/Travis Scott/UTOPIA", files=files, library={
                files[0]: {"file": files[0],
                           "artist": "Travis Scott Feat. Drake"},
                files[1]: {"file": files[1],
                           "artist": "Travis Scott & Beyoncé"},
            })
        self.assertEqual(result["artist"], "Travis Scott")


class ChapterDetectorTests(unittest.TestCase):
    def test_short_tracks_and_incomplete_envelopes_have_no_chapters(self):
        self.assertEqual(ChapterDetector.detect(1199, [1.0] * 100), [])
        self.assertEqual(ChapterDetector.detect(3600, [1.0] * 39), [])
        self.assertEqual(ChapterDetector.detect(3600, ["bad"] * 100), [])

    def test_deep_separated_valleys_become_bounded_chapter_marks(self):
        peaks = [1.0] * 100
        for center in (20, 60):
            for offset in range(-5, 6):
                peaks[center + offset] = abs(offset) / 10
        marks = ChapterDetector.detect(3600, peaks)
        self.assertTrue(any(abs(mark - 720) < 150 for mark in marks))
        self.assertTrue(any(abs(mark - 2160) < 150 for mark in marks))
        self.assertLessEqual(len(marks), ChapterDetector.MAX_CHAPTERS)
        self.assertTrue(all(b - a >= ChapterDetector.MIN_SPACING
                            for a, b in zip(marks, marks[1:])))


if __name__ == "__main__":
    unittest.main()


class LibraryDirectoryTests(unittest.TestCase):
    SONGS = [
        {"file": "Rap/Kanye West/Kanye West - 808s/01.flac", "album": "808s",
         "artist": "Kanye West", "year": "2008", "added": 100.0,
         "genres": ["Art Pop", "Electronic"]},
        {"file": "Rap/Kanye West/Kanye West - 808s/02.flac", "album": "808s",
         "artist": "Kanye West", "year": "", "added": 250.0,
         "genres": ["art pop"]},
        {"file": "Rap/Travis Scott/UTOPIA/01.flac", "album": "UTOPIA",
         "artist": "Travis Scott", "year": "2023", "added": 900.0,
         "genres": ["Hip-Hop", "Electronic"]},
        {"file": "Folk/Shawn James/The Dark/01.flac", "album": "The Dark",
         "artist": "Shawn James", "year": "2019", "added": 50.0,
         "genres": ["Dark Americana"]},
        {"file": "Playlists/x.m3u", "album": "", "artist": "", "added": 0.0},
        {"file": "loose.flac", "album": "", "artist": "", "added": 0.0},
    ]

    def test_albums_group_by_folder_with_recency_default(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.albums(self.SONGS)
        self.assertEqual([row["album"] for row in rows],
                         ["UTOPIA", "808s", "The Dark"])
        first = rows[1]
        self.assertEqual(first["artist"], "Kanye West")
        self.assertEqual(first["year"], "2008")
        self.assertEqual(first["songs"], 2)
        self.assertEqual(first["added"], 250.0)
        self.assertEqual(first["cover"],
                         "Rap/Kanye West/Kanye West - 808s/01.flac")

    def test_album_rows_use_album_artist_not_featured_track_credits(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.albums([
            {"file": "Rap/Travis Scott/UTOPIA/01.flac",
             "album": "UTOPIA", "artist": "Travis Scott",
             "albumartist": "Travis Scott"},
            {"file": "Rap/Travis Scott/UTOPIA/02.flac",
             "album": "UTOPIA", "artist": "Travis Scott Feat. Drake",
             "albumartist": "Travis Scott"},
        ])
        self.assertEqual("Travis Scott", rows[0]["artist"])

    def test_albums_sharing_artist_folder_remain_separate_rows(self):
        from ampere.albums import LibraryDirectory
        folder = "Metal/Signs of the Swarm"
        rows = LibraryDirectory.albums([
            {"file": folder + "/death-whistle.flac",
             "album": "Absolvere", "artist": "Signs of the Swarm"},
            {"file": folder + "/iwontletyoudie.flac",
             "album": "Amongst the Low & Empty",
             "artist": "Signs of the Swarm"},
            {"file": folder + "/cesspool.flac",
             "album": "Vital Deprivation",
             "artist": "Signs of the Swarm"},
        ])
        self.assertEqual(
            ["Absolvere", "Amongst the Low & Empty", "Vital Deprivation"],
            [row["album"] for row in rows])
        self.assertTrue(all(row["songs"] == 1 for row in rows))
        self.assertTrue(all(row["path"] == folder for row in rows))

    def test_artists_register_counts_albums_and_sorts_alphabetically(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.artists(
            self.SONGS, lambda file, artist: "path:" + artist)
        self.assertEqual([row["name"] for row in rows],
                         ["Kanye West", "Shawn James", "Travis Scott"])
        kanye = rows[0]
        self.assertEqual(kanye["albums"], 1)
        self.assertEqual(kanye["songs"], 2)
        self.assertEqual(kanye["path"], "path:Kanye West")

    def test_artists_merge_aliases_and_expand_joint_credits(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.artists([
            {"file": "Rap/Kanye/solo.flac", "album": "Solo",
             "artist": "Kanye West", "albumartist": "Kanye West"},
            {"file": "Rap/Ye/alias.flac", "album": "BULLY",
             "artist": "Ye", "albumartist": "Ye"},
            {"file": "Rap/Watch/joint.flac", "album": "Watch the Throne",
             "artist": "Jay Z, Kanye West", "albumartist": "Jay Z"},
        ], lambda file, artist: "path:" + artist)

        self.assertEqual(["Jay Z", "Kanye West"],
                         [row["name"] for row in rows])
        kanye = rows[1]
        self.assertEqual(3, kanye["songs"])
        self.assertEqual(3, kanye["albums"])
        self.assertNotIn("Ye", [row["name"] for row in rows])
        self.assertNotIn("Jay Z, Kanye West", [row["name"] for row in rows])

    def test_genres_use_only_metadata_and_carry_distinct_album_art(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.genres(self.SONGS)
        self.assertEqual([row["name"] for row in rows],
                         ["Art Pop", "Dark Americana", "Electronic",
                          "Hip-Hop"])
        electronic = rows[2]
        self.assertEqual(electronic["albums"], 2)
        self.assertEqual(electronic["artists"], 2)
        self.assertEqual(electronic["songs"], 2)
        self.assertEqual(2, len(electronic["covers"]))
        self.assertNotIn("path", electronic)

    def test_genres_do_not_fall_back_to_directory_names(self):
        from ampere.albums import LibraryDirectory
        rows = LibraryDirectory.genres([
            {"file": "Folder-Taxonomy/Artist/Track.flac",
             "album": "Album", "artist": "Artist", "genres": []},
        ])
        self.assertEqual([], rows)

    def test_genres_exclude_names_used_as_artist_attribution_anywhere(self):
        from ampere.albums import LibraryDirectory
        songs = [
            {"file": "Classical/Work/01.flac", "album": "Work",
             "artist": "Soloist", "genres": ["Carl Orff", "Classical"]},
            {"file": "Classical/Other/01.flac", "album": "Other",
             "artist": "Carl Orff", "genres": ["Classical"]},
        ]

        rows = LibraryDirectory.genres(songs)
        self.assertEqual(["Classical"], [row["name"] for row in rows])
        self.assertEqual({}, LibraryDirectory.genre_detail(songs, "Carl Orff"))
        self.assertEqual(2, len(
            LibraryDirectory.genre_detail(songs, "Classical")["tracks"]))

    def test_genres_exclude_preserved_multi_credit_identities(self):
        from ampere.albums import LibraryDirectory
        songs = [{
            "file": "Opera/Tosca/01.flac", "album": "Tosca",
            "artist": "Giacomo Puccini, Luciano Pavarotti",
            "creditNames": ["Giacomo Puccini", "Luciano Pavarotti"],
            "genres": ["Giacomo Puccini", "Opera"],
        }]

        self.assertEqual(
            ["Opera"],
            [row["name"] for row in LibraryDirectory.genres(songs)])

    def test_genre_detail_is_exact_metadata_membership_with_album_projection(self):
        from ampere.albums import LibraryDirectory
        detail = LibraryDirectory.genre_detail(self.SONGS, "  electronic ")

        self.assertEqual("Electronic", detail["name"])
        self.assertEqual(
            ["Rap/Kanye West/Kanye West - 808s/01.flac",
             "Rap/Travis Scott/UTOPIA/01.flac"],
            [track["file"] for track in detail["tracks"]])
        self.assertEqual(["UTOPIA", "808s"],
                         [album["album"] for album in detail["albums"]])
        self.assertEqual(2, detail["artists"])
        self.assertEqual(2, detail["songs"])
        self.assertEqual(2, len(detail["covers"]))

    def test_genre_detail_never_uses_folder_taxonomy_or_partial_matches(self):
        from ampere.albums import LibraryDirectory
        songs = self.SONGS + [{
            "file": "Electronic/Artist/Track.flac",
            "album": "Folder Album", "artist": "Folder Artist",
            "genres": ["Electro"],
        }]

        self.assertEqual({}, LibraryDirectory.genre_detail(songs, "Metal"))
        self.assertEqual({}, LibraryDirectory.genre_detail(songs, "Electron"))

    def test_folders_list_direct_children_with_freshness(self):
        from ampere.albums import LibraryDirectory
        top = LibraryDirectory.folders(self.SONGS)
        self.assertEqual([row["name"] for row in top],
                         ["Folk", "Playlists", "Rap"])
        rap = LibraryDirectory.folders(self.SONGS, "Rap")
        self.assertEqual([row["name"] for row in rap],
                         ["Kanye West", "Travis Scott"])
        self.assertEqual(rap[0]["modified"], 250.0)
        self.assertEqual(rap[0]["path"], "Rap/Kanye West")
