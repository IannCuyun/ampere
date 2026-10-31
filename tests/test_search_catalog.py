import unittest

from ampere.search import LyricIndexer, SearchCatalog


def song(file, title, artist, album, year="", albumartist=""):
    return {"file": file, "title": title, "artist": artist, "album": album,
            "year": year, "albumartist": albumartist}


class SearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.songs = [
            song("Rap/Travis/Rodeo/01.flac", "90210", "Travis Scott", "Rodeo"),
            song("Rap/Travis/Utopia/01.flac", "HYAENA", "Travis Scott", "Utopia", "2023"),
            song("Rap/Tyler/Igor/01.flac", "EARFQUAKE", "Tyler, The Creator", "IGOR"),
        ]
        plays = {"Rap/Travis/Rodeo/01.flac": 8,
                 "Rap/Travis/Utopia/01.flac": 4}
        self.catalog = SearchCatalog(
            artist_path=lambda file, _artist: file.rsplit("/", 2)[0])
        self.catalog.replace_playcounts(plays)
        self.generation = self.catalog.replace_songs(self.songs)

    def test_query_groups_tracks_artists_and_albums(self):
        result = self.catalog.query("uto")
        self.assertEqual(["Utopia"], [a["album"] for a in result["albums"]])
        self.assertEqual("2023", result["albums"][0]["year"])
        self.assertEqual("HYAENA", result["hits"][0]["title"])

        artist = self.catalog.query("tra")
        self.assertTrue(artist["artistFirst"])
        self.assertEqual("Travis Scott", artist["artists"][0]["name"])

    def test_lyric_results_are_bound_to_the_library_generation(self):
        self.assertTrue(self.catalog.replace_lyrics(
            {"Rap/Travis/Utopia/01.flac": "The situation we are in"},
            self.generation))
        self.assertEqual("HYAENA", self.catalog.lyric_query("situation")[0]["title"])

        new_generation = self.catalog.replace_songs(self.songs[:1])
        self.assertFalse(self.catalog.replace_lyrics(
            {"Rap/Travis/Utopia/01.flac": "stale result"}, self.generation))
        self.assertEqual([], self.catalog.lyric_query("stale"))
        self.assertGreater(new_generation, self.generation)

    def test_short_queries_return_a_complete_empty_contract(self):
        self.assertEqual(SearchCatalog.EMPTY_RESULT, self.catalog.query("x"))

    # ---- Record Wall contract (DECISIONS 2026-08-20 · AUDIT S-01/S-03/S-05) ----

    def test_every_matching_file_is_its_own_row_with_format_disambiguation(self):
        catalog = SearchCatalog()
        catalog.replace_songs([
            song("Rap/Kanye/Graduation/bully.flac", "Bully", "Kanye West", "Graduation"),
            song("Rap/Kanye/Graduation/bully.mp3", "Bully", "Kanye West", "Graduation"),
            song("Rap/Kanye/Singles/bully.mp3", "Bully", "Kanye West", "Bully - Single"),
            song("Rap/Kanye/Graduation/other.flac", "Bully Remix", "Kanye West", "Graduation"),
        ])
        result = catalog.query("bully")
        files = [hit["file"] for hit in result["hits"]]
        self.assertEqual(4, len(files))
        self.assertEqual(4, len(set(files)))
        by_file = {hit["file"]: hit for hit in result["hits"]}
        # same title + artist + album: only the format tells them apart
        self.assertTrue(by_file["Rap/Kanye/Graduation/bully.flac"]["disambiguate"])
        self.assertTrue(by_file["Rap/Kanye/Graduation/bully.mp3"]["disambiguate"])
        # same title + artist, different album: the album sub line suffices
        self.assertFalse(by_file["Rap/Kanye/Singles/bully.mp3"]["disambiguate"])
        self.assertFalse(by_file["Rap/Kanye/Graduation/other.flac"]["disambiguate"])
        self.assertEqual("FLAC", by_file["Rap/Kanye/Graduation/bully.flac"]["format"])
        self.assertEqual("MP3", by_file["Rap/Kanye/Singles/bully.mp3"]["format"])

    def test_best_match_prefers_exact_identity_then_prefix_tiers(self):
        catalog = SearchCatalog(artist_path=lambda file, _a: file.rsplit("/", 2)[0])
        catalog.replace_songs([
            song("Pop/HIM/Dark Light/01.flac", "Vampire Heart", "HIM", "Dark Light"),
            song("Rap/Kanye/808s/01.flac", "Heartless", "Kanye West", "808s & Heartbreak"),
            song("Rock/Heart/Dreamboat/01.flac", "Magic Man", "Heart", "Dreamboat Annie"),
            song("Rap/Kanye/Graduation/02.flac", "Heart", "Kanye West", "Graduation"),
        ])
        exact_title = catalog.query("heart")
        self.assertEqual("song", exact_title["best"]["kind"])
        self.assertEqual("Rap/Kanye/Graduation/02.flac", exact_title["best"]["item"]["file"])
        self.assertTrue(exact_title["best"]["exact"])

        exact_album = catalog.query("808s & heartbreak")
        self.assertEqual("album", exact_album["best"]["kind"])
        self.assertEqual("Rap/Kanye/808s", exact_album["best"]["item"]["dir"])

        prefix_title = catalog.query("heartl")
        self.assertEqual("song", prefix_title["best"]["kind"])
        self.assertEqual("Heartless", prefix_title["best"]["item"]["title"])

    def test_fuzzy_only_results_flag_the_best_match_as_closest(self):
        result = self.catalog.query("hyena")
        self.assertEqual([], result["hits"])
        self.assertEqual("HYAENA", result["suggestions"][0]["title"])
        self.assertEqual("song", result["best"]["kind"])
        self.assertFalse(result["best"]["exact"])

    def test_albums_holding_matching_songs_join_the_sleeve_row_with_counts(self):
        catalog = SearchCatalog()
        catalog.replace_songs([
            song("Pop/HIM/Dark Light/01.flac", "Vampire Heart", "HIM", "Dark Light"),
            song("Pop/HIM/Dark Light/02.flac", "Heartache Every Moment", "HIM", "Dark Light"),
            song("Rap/Kanye/808s/01.flac", "Heartless", "Kanye West", "808s & Heartbreak"),
            song("Rap/Kanye/808s/02.flac", "Say You Will", "Kanye West", "808s & Heartbreak"),
        ])
        albums = catalog.query("heart")["albums"]
        rows = {album["album"]: album for album in albums}
        self.assertTrue(rows["808s & Heartbreak"]["nameMatch"])
        self.assertEqual(2, rows["808s & Heartbreak"]["trackCount"])
        self.assertFalse(rows["Dark Light"]["nameMatch"])
        self.assertEqual(2, rows["Dark Light"]["matchingSongs"])
        self.assertEqual("808s & Heartbreak", albums[0]["album"])

    def test_no_preview_limits_hide_matches(self):
        catalog = SearchCatalog()
        catalog.replace_songs([
            song(f"Lib/Artist {i}/Album {i}/heart.flac", f"Heart {i}",
                 f"Heart Artist {i}", f"Heart Album {i}")
            for i in range(12)])
        result = catalog.query("heart")
        self.assertEqual(12, len(result["hits"]))
        self.assertEqual(12, len(result["albums"]))
        self.assertEqual(12, len(result["artists"]))

    def test_artist_ranking_uses_a_copied_playcount_snapshot(self):
        catalog = SearchCatalog(artist_path=lambda *_args: "")
        catalog.replace_songs([
            song("a.flac", "One", "Trace Alpha", "A"),
            song("b.flac", "Two", "Trace Beta", "B"),
        ])
        counts = {"b.flac": 9}
        catalog.replace_playcounts(counts)
        counts["a.flac"] = 99

        result = catalog.query("tra")

        self.assertEqual("Trace Beta", result["artists"][0]["name"])

    def test_same_title_releases_keep_folder_identity_and_album_artist(self):
        catalog = SearchCatalog()
        catalog.replace_songs([
            song("A/Primary A/Shared/01.flac", "One", "Featured A",
                 "Shared", albumartist="Primary A"),
            song("B/Primary B/Shared/01.flac", "Two", "Featured B",
                 "Shared", albumartist="Primary B"),
        ])

        albums = catalog.query("shared")["albums"]

        self.assertEqual([
            ("A/Primary A/Shared", "Shared", "Primary A"),
            ("B/Primary B/Shared", "Shared", "Primary B"),
        ], [(row["dir"], row["album"], row["artist"]) for row in albums])


class LyricIndexerTests(unittest.TestCase):
    def catalog(self):
        catalog = SearchCatalog()
        catalog.replace_songs([
            song("one.flac", "One", "Artist", "Album"),
            song("two.flac", "Two", "Artist", "Album"),
        ])
        return catalog

    def test_builds_and_publishes_lowercase_search_text(self):
        catalog = self.catalog()
        result = LyricIndexer(
            catalog, "/music",
            read_lyrics=lambda path: ([{"line": path.rsplit("/", 1)[-1]}],
                                      False)).scan()

        self.assertTrue(result.published)
        self.assertEqual((2, 2, 2, 0), (
            result.total, result.done, result.indexed, result.failed))
        self.assertEqual("One", catalog.lyric_query("one.flac")[0]["title"])

    def test_generation_change_stops_stale_file_reads_immediately(self):
        catalog = self.catalog()
        reads = []

        def read(path):
            reads.append(path)
            catalog.replace_songs([song("new.flac", "New", "A", "B")])
            return ([{"line": "stale"}], False)

        result = LyricIndexer(catalog, "/music", read_lyrics=read).scan()

        self.assertEqual(1, len(reads))
        self.assertTrue(result.cancelled)
        self.assertFalse(result.published)
        self.assertEqual([], catalog.lyric_query("stale"))

    def test_stop_request_cancels_without_publication(self):
        catalog = self.catalog()
        result = LyricIndexer(
            catalog, "/music",
            read_lyrics=lambda _path: self.fail("must not read")).scan(
                should_stop=lambda: True)
        self.assertTrue(result.cancelled)
        self.assertEqual(0, result.done)


if __name__ == "__main__":
    unittest.main()
