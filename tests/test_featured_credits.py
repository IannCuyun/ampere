"""Featured credits are a primary billing plus guests, not a new artist.

SPEC UNDESIGNED #17 / ROADMAP 1.3. Before this, `Travis Scott Feat. Drake`
became its own artist identity because credit splitting only broke on commas,
so the track appeared under a person who does not exist and under neither of
the two who do.
"""
import unittest

from ampere.artists import (artist_key, credited_artists, primary_artist_credit,
                           set_aliases, split_featured)
from ampere.library import _credit_identities


class SplitFeaturedTests(unittest.TestCase):
    def test_a_guest_is_separated_from_the_primary(self):
        self.assertEqual(("Travis Scott", ["Drake"]),
                         split_featured("Travis Scott Feat. Drake"))

    def test_several_guests_split_on_the_guest_side(self):
        self.assertEqual(("Travis Scott", ["21 Savage", "Rob49"]),
                         split_featured("Travis Scott Feat. 21 Savage & Rob49"))
        self.assertEqual(
            ("Travis Scott", ["Yung Lean", "Dave Chappelle", "Don Toliver"]),
            split_featured(
                "Travis Scott Feat. Yung Lean w/ Dave Chappelle & Don Toliver"))

    def test_an_ampersand_stays_inside_the_primary_billing(self):
        # SPEC row 38: ampersands are part of a name, not a separator
        self.assertEqual(("Macklemore & Ryan Lewis", ["Wanz"]),
                         split_featured("Macklemore & Ryan Lewis feat. Wanz"))

    def test_a_plain_name_passes_through_untouched(self):
        for name in ("Royal & the Serpent", "Bruce Springsteen & The E Street Band",
                     "Wet Leg", "Featurecast", "Tech N9ne"):
            self.assertEqual((name, []), split_featured(name), name)

    def test_a_bare_w_is_never_a_marker(self):
        # found against the real library: this split into "C." + "Stoneking"
        self.assertEqual(("C.W. Stoneking", []), split_featured("C.W. Stoneking"))

    def test_a_marker_with_nothing_after_it_is_not_a_split(self):
        self.assertEqual(("Some Artist feat.", []),
                         split_featured("Some Artist feat."))

    def test_a_leading_marker_is_not_a_split(self):
        self.assertEqual(("feat. Drake", []), split_featured("feat. Drake"))


class CreditedArtistsTests(unittest.TestCase):
    def tearDown(self):
        set_aliases({})

    def test_the_track_files_under_the_primary_and_every_guest(self):
        self.assertEqual(["Travis Scott", "21 Savage", "Rob49"],
                         credited_artists("Travis Scott Feat. 21 Savage & Rob49"))

    def test_the_invented_identity_is_gone(self):
        names = credited_artists("Travis Scott Feat. Drake")
        self.assertNotIn("Travis Scott Feat. Drake", names)
        self.assertEqual(["Travis Scott", "Drake"], names)

    def test_a_stranded_marker_is_not_a_person(self):
        names = credited_artists('Tech N9ne, Krizz Kaliko, feat., Eric "Ezikuhl" Boone')
        self.assertEqual(["Tech N9ne", "Krizz Kaliko", 'Eric "Ezikuhl" Boone'], names)
        for junk in ("feat.", "feat", "ft.", "with"):
            self.assertNotIn(junk, names)

    def test_a_page_destination_resolves_to_the_primary(self):
        self.assertEqual("Travis Scott",
                         primary_artist_credit("Travis Scott Feat. Drake"))

    def test_an_alias_still_applies_to_the_primary(self):
        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        self.assertEqual(["Tech N9ne", "Krizz Kaliko"],
                         credited_artists("Tech N9ne Collabos Feat. Krizz Kaliko"))

    def test_membership_keys_agree_for_the_same_person(self):
        self.assertEqual(artist_key("Drake"),
                         artist_key(credited_artists("Travis Scott Feat. Drake")[1]))


class LibraryIdentityTests(unittest.TestCase):
    def test_the_library_indexes_the_guest_too(self):
        names = _credit_identities("Travis Scott Feat. Drake")
        self.assertIn("Travis Scott", names)
        self.assertIn("Drake", names)

    def test_the_full_credit_line_is_retained_as_display_evidence(self):
        # the tag itself is never rewritten; the combined line stays indexed
        self.assertIn("Travis Scott Feat. Drake",
                      _credit_identities("Travis Scott Feat. Drake"))


if __name__ == "__main__":
    unittest.main()
