"""The published generation must answer the same as the scans it replaced.

Phase 5.3 moved artist membership, genre membership, the genre credit-block
set and every folder's child rows off Qt's thread and onto the index worker
that builds the library generation. That is only a performance change if the
answers are identical, so each one is pinned here against the scan it stands
in for — including the paths that are easy to get wrong: hidden folders,
missing names, and a credit that lists a guest.
"""

import unittest

from ampere.albums import LibraryDirectory
from ampere.artists import (artist_key, primary_artist_credit, set_aliases,
                           song_credited_artists)
from ampere.library import LibraryRepository
from ampere import search as searchlib


def scan_artist_files(songs, artist):
    """The library-wide scan `artist_files` replaced, verbatim."""
    wanted = artist_key(primary_artist_credit(artist))
    if not wanted:
        return []
    return [song["file"] for song in songs
            if any(artist_key(name) == wanted
                   for name in song_credited_artists(song))]


def scan_genre_files(songs, name):
    """The library-wide scan the `genreFiles` slot replaced, verbatim."""
    wanted = str(name or "").casefold()
    if not wanted:
        return []
    return [str(song.get("file") or "") for song in songs
            if any(str(genre).casefold() == wanted
                   for genre in (song.get("genres") or ()))]


LIBRARY = [
    {"file": "Rap/Tech N9ne/Collabos/01 Strangeulation.flac",
     "title": "Strangeulation", "artist": "Tech N9ne Feat. Krizz Kaliko",
     "albumartist": "Tech N9ne", "album": "Collabos", "genre": "Rap",
     "added": "300"},
    {"file": "Rap/Tech N9ne/Collabos/02 Party.flac", "title": "Party",
     "artist": "Tech N9ne", "album": "Collabos", "genre": ["Rap", "Hip Hop"],
     "added": "100"},
    {"file": "Rock/Royal & the Serpent/Small/01 Overwhelmed.flac",
     "title": "Overwhelmed", "artist": "Royal & the Serpent",
     "album": "Small", "genre": "Rock", "added": "500"},
    {"file": "Rock/.staging/Unsorted/01 Draft.flac", "title": "Draft",
     "artist": "Nobody", "album": "Unsorted", "genre": "Rock", "added": "700"},
    {"file": "Loose.flac", "title": "Loose", "artist": "Nobody",
     "album": "", "genre": "", "added": "1"},
    {"file": "Rock/Royal & the Serpent/Small/02 Phase.flac", "title": "Phase",
     "artist": "royal & the serpent", "album": "Small", "genre": "rock",
     "added": "bad"},
]

PATHS = ["", "Rock", "Rock/Royal & the Serpent", "Rock/.staging",
         "Rock/.staging/Unsorted", "Rap", "Rap/Tech N9ne",
         "Rap/Tech N9ne/Collabos", "missing", "Rock/", "/Rock/", "  "]


class PublishedMembershipTests(unittest.TestCase):
    def setUp(self):
        set_aliases({})
        self.addCleanup(set_aliases, {})
        self.repo = LibraryRepository()
        self.repo.replace(LIBRARY)
        self.songs = self.repo.songs

    def artist_names(self):
        names = {row["name"] for row in LibraryDirectory.artists(
            self.songs, LibraryRepository.artist_path)}
        return sorted(names | {"", "   ", "Krizz Kaliko", "Unknown Person",
                               "Tech N9ne Feat. Krizz Kaliko"})

    def test_artist_membership_matches_the_scan_it_replaced(self):
        for name in self.artist_names():
            with self.subTest(artist=name):
                self.assertEqual(scan_artist_files(self.songs, name),
                                 self.repo.artist_files(name))

    def test_a_guest_credit_still_files_under_both_people(self):
        self.assertIn("Rap/Tech N9ne/Collabos/01 Strangeulation.flac",
                      self.repo.artist_files("Krizz Kaliko"))
        self.assertEqual(2, len(self.repo.artist_files("Tech N9ne")))

    def test_genre_membership_matches_the_scan_it_replaced(self):
        genres = {genre for song in self.songs
                  for genre in (song.get("genres") or ())}
        for name in sorted(genres | {"", "ROCK", "Nonexistent"}):
            with self.subTest(genre=name):
                self.assertEqual(scan_genre_files(self.songs, name),
                                 self.repo.genre_files(name))

    def test_folder_rows_match_the_scan_they_replaced(self):
        for path in PATHS:
            with self.subTest(path=path):
                self.assertEqual(LibraryDirectory.folders(self.songs, path),
                                 self.repo.folders(path))

    def test_a_dotted_folder_is_hidden_but_what_is_under_it_is_not(self):
        self.assertNotIn(".staging",
                         [row["name"] for row in self.repo.folders("Rock")])
        self.assertEqual(["Unsorted"],
                         [row["name"] for row in
                          self.repo.folders("Rock/.staging")])

    def test_published_credit_keys_match_the_scan_they_replaced(self):
        self.assertEqual(LibraryDirectory._credit_keys(self.songs),
                         set(self.repo.credit_keys))

    def test_genre_detail_from_the_published_generation_is_unchanged(self):
        genres = {genre for song in self.songs
                  for genre in (song.get("genres") or ())}
        for name in sorted(genres | {"", "Nonexistent", "Tech N9ne"}):
            with self.subTest(genre=name):
                members = [self.repo.by_file[file]
                           for file in self.repo.genre_files(name)
                           if file in self.repo.by_file]
                self.assertEqual(
                    LibraryDirectory.genre_detail(self.songs, name),
                    LibraryDirectory.genre_detail(
                        self.songs, name, credit_keys=self.repo.credit_keys,
                        members=members))

    def test_membership_is_rebuilt_when_the_generation_changes(self):
        self.repo.replace([LIBRARY[2]])
        self.assertEqual([], self.repo.artist_files("Tech N9ne"))
        self.assertEqual([], self.repo.genre_files("Rap"))
        self.assertEqual([], self.repo.folders("Rap"))
        self.assertEqual(["Rock/Royal & the Serpent/Small/01 Overwhelmed.flac"],
                         self.repo.artist_files("Royal & the Serpent"))


class CreditCacheInvalidationTests(unittest.TestCase):
    """A memoized credit projection must never outlive its alias table."""

    def setUp(self):
        set_aliases({})
        self.addCleanup(set_aliases, {})

    def test_an_alias_change_is_visible_to_every_cached_projection(self):
        songs = [{"file": "a/b/01 One.flac", "title": "One",
                  "artist": "Tech N9ne Collabos", "album": "b"}]
        repo = LibraryRepository()
        repo.replace(songs)
        self.assertEqual([], repo.artist_files("Tech N9ne"))

        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        repo.replace(songs)
        self.assertEqual(["a/b/01 One.flac"], repo.artist_files("Tech N9ne"))
        self.assertEqual(["Tech N9ne"],
                         song_credited_artists(repo.songs[0]))

        set_aliases({})
        repo.replace(songs)
        self.assertEqual([], repo.artist_files("Tech N9ne"))


class NormalizeFastPathTests(unittest.TestCase):
    """The cached, regex-based normalizer must answer as the old one did."""

    CASES = [
        "", " ", "  ", "!", "Help!", "FE!N", "Ke$ha", "A$AP Rocky", "P!NK",
        "B.Y.O.B.", "Can't Hold Us", "can’t", "ca`nt", "ca´nt", "caʼnt",
        "six foot seven foot", "Salt & Pepa", "&", "AC/DC", "R&B",
        "é!n", "É!N", "naïve", "Björk", "Motörhead", "人間椅子", "Пикник",
        "_underscore_", "a_b", "9½ Weeks", "ﬁ", "ｆｕｌｌｗｉｄｔｈ",
        "  leading and trailing  ", "emoji 🎵 title", "20 twenty hundred",
    ]

    @staticmethod
    def reference(s, fused):
        """The pre-cache implementation, kept as the definition of correct."""
        import re
        import unicodedata
        s = s.lower()
        for rx, rep in searchlib._LEET:
            s = rx.sub(rep, s)
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = searchlib._APOS.sub("", s)
        s = s.replace("&", " and ")
        out = []
        for c in s:
            if c.isalnum():
                out.append(c)
            elif c == " " or not fused:
                out.append(" ")
        s = re.sub(r" +", " ", "".join(out)).strip()
        return " ".join(searchlib.NUM_WORDS.get(t, t) for t in s.split())

    def test_every_documented_case_normalizes_identically(self):
        for case in self.CASES:
            for fused in (False, True):
                with self.subTest(case=case, fused=fused):
                    self.assertEqual(self.reference(case, fused),
                                     searchlib.normalize(case, fused))

    def test_a_marker_only_becomes_a_letter_between_real_characters(self):
        # Leet decoding runs before NFKD: the accented flank is not a letter
        # yet, so "é!n" must not collapse to "ein".
        self.assertEqual("e n", searchlib.normalize("é!n"))
        self.assertEqual("fein", searchlib.normalize("FE!N"))
        self.assertEqual("help", searchlib.normalize("Help!"))


if __name__ == "__main__":
    unittest.main()
