"""Explicit artist aliases — storage, resolution and SUGGESTIONS.

Iann's direction (2026-08-21, SPEC UNDESIGNED #17): he combines aliases
himself from Library Doctor. Nothing here may infer an identity — a
suggestion is a proposal he confirms, never an applied merge.
"""
import unittest

from ampere.artist_aliases import suggest
from ampere.artists import (aliases, artist_key, canonical_artist_name,
                           set_aliases)
from ampere.settings import ALIAS_LIMIT, DEFAULTS, _validated, clean_artist_aliases

LIBRARY = [
    "Tech N9ne", "Tech N9ne Collabos", "Tech N9ne & Krizz Kaliko",
    "Shawn James", "Shawn James and the Shapeshifters", "Shawn Mendes",
    "Kanye West", "Ye", "Travis Scott", "Bruce Springsteen",
    "Bruce Springsteen & The E Street Band",
]


class AliasStorageTests(unittest.TestCase):
    def tearDown(self):
        set_aliases({})

    def test_defaults_carry_an_empty_user_table(self):
        self.assertEqual({}, DEFAULTS["artist_aliases"])

    def test_settings_validate_and_survive_a_round_trip(self):
        values = _validated({"artist_aliases": {
            "Tech N9ne Collabos": "Tech N9ne", "  Ye  ": "Kanye West"}})
        self.assertEqual({"Tech N9ne Collabos": "Tech N9ne", "Ye": "Kanye West"},
                         values["artist_aliases"])

    def test_junk_never_reaches_the_table(self):
        self.assertEqual({}, clean_artist_aliases("not a mapping"))
        self.assertEqual({}, clean_artist_aliases({"": "Tech N9ne"}))
        self.assertEqual({}, clean_artist_aliases({"Tech N9ne": ""}))

    def test_an_alias_can_never_point_at_itself(self):
        self.assertEqual({}, clean_artist_aliases({"Ye": "ye"}))

    def test_a_cycle_cannot_hang_a_projection(self):
        self.assertEqual({}, clean_artist_aliases({"A": "B", "B": "A"}))

    def test_a_chain_is_settled_at_write_time(self):
        self.assertEqual({"X": "Z", "Y": "Z"},
                         clean_artist_aliases({"X": "Y", "Y": "Z"}))

    def test_the_table_is_bounded(self):
        big = {f"artist {i}": "Target" for i in range(ALIAS_LIMIT + 50)}
        self.assertEqual(ALIAS_LIMIT, len(clean_artist_aliases(big)))


class AliasResolutionTests(unittest.TestCase):
    def tearDown(self):
        set_aliases({})

    def test_the_shipped_seed_survives_an_empty_user_table(self):
        set_aliases({})
        self.assertEqual("Kanye West", canonical_artist_name("Ye"))

    def test_a_user_alias_resolves_through_the_catalog_key(self):
        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        self.assertEqual("Tech N9ne", canonical_artist_name("Tech N9ne Collabos"))
        self.assertEqual(artist_key("Tech N9ne"),
                         artist_key("Tech N9ne Collabos"))

    def test_resolution_is_case_blind_but_display_text_is_preserved(self):
        set_aliases({"Shawn James and the Shapeshifters": "Shawn James"})
        self.assertEqual(
            "Shawn James",
            canonical_artist_name("shawn james AND THE shapeshifters"))
        self.assertEqual("Travis Scott", canonical_artist_name("Travis Scott"))

    def test_removing_an_alias_restores_the_separate_identity(self):
        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        set_aliases({})
        self.assertEqual("Tech N9ne Collabos",
                         canonical_artist_name("Tech N9ne Collabos"))
        self.assertNotEqual(artist_key("Tech N9ne"),
                            artist_key("Tech N9ne Collabos"))

    def test_an_unrelated_artist_is_never_touched(self):
        set_aliases({"Shawn James and the Shapeshifters": "Shawn James"})
        self.assertEqual("Shawn Mendes", canonical_artist_name("Shawn Mendes"))

    def test_the_table_in_force_is_readable(self):
        set_aliases({"Tech N9ne Collabos": "Tech N9ne"})
        self.assertEqual("Tech N9ne", aliases()["tech n9ne collabos"])


class AliasSuggestionTests(unittest.TestCase):
    def names(self, artist):
        return [row["name"] for row in suggest(artist, LIBRARY)]

    def test_it_finds_the_release_series_credit(self):
        self.assertIn("Tech N9ne Collabos", self.names("Tech N9ne"))

    def test_it_finds_the_backing_band_billing(self):
        self.assertIn("Shawn James and the Shapeshifters",
                      self.names("Shawn James"))
        self.assertIn("Bruce Springsteen & The E Street Band",
                      self.names("Bruce Springsteen"))

    def test_it_never_proposes_a_different_person_sharing_a_name(self):
        self.assertNotIn("Shawn Mendes", self.names("Shawn James"))

    def test_a_collaboration_is_not_an_identity(self):
        # SPEC: a combined credit never becomes a third pseudo-artist, and it
        # is certainly not the same identity as either contributor.
        self.assertNotIn("Tech N9ne & Krizz Kaliko", self.names("Tech N9ne"))

    def test_it_admits_what_it_cannot_know(self):
        # No string comparison recovers a separate stage name; guessing at it
        # is exactly what SPEC forbids. That pairing is made by hand.
        self.assertEqual([], self.names("Kanye West"))

    def test_every_suggestion_explains_itself(self):
        for row in suggest("Shawn James", LIBRARY):
            self.assertTrue(row["reason"])

    def test_the_shorter_billing_is_offered_from_the_longer_one(self):
        self.assertIn("Shawn James",
                      self.names("Shawn James and the Shapeshifters"))

    def test_the_chosen_artist_is_never_its_own_suggestion(self):
        self.assertNotIn("Tech N9ne", self.names("Tech N9ne"))

    def test_an_empty_choice_proposes_nothing(self):
        self.assertEqual([], suggest("", LIBRARY))
        self.assertEqual([], suggest("Tech N9ne", []))


if __name__ == "__main__":
    unittest.main()


class CombinedCreditTests(unittest.TestCase):
    """A combined credit line is not an identity (SPEC · Artist page).

    Caught against Iann's real library on 2026-08-21: comma-separated credit
    lines such as "King Iso, Tech N9ne, X-Raided" were being offered as
    aliases of "King Iso, Tech N9ne", which would merge a whole collaboration
    into one artist.
    """

    REAL = [
        "Tech N9ne", "Tech N9ne Collabos",
        "King Iso, Tech N9ne", "King Iso, Tech N9ne, X-Raided",
        "Tech N9ne Collabos, Krizz Kaliko, Makzilla",
        "Tech N9ne, Krizz Kaliko",
    ]

    def names(self, artist):
        return [row["name"] for row in suggest(artist, self.REAL)]

    def test_a_combined_line_is_never_offered_as_an_alias(self):
        for name in self.names("Tech N9ne"):
            self.assertNotIn(",", name, name)

    def test_a_combined_line_cannot_be_the_chosen_artist(self):
        self.assertEqual([], suggest("King Iso, Tech N9ne", self.REAL))
        self.assertEqual([], suggest("Tech N9ne, Krizz Kaliko", self.REAL))

    def test_the_real_identity_is_still_found(self):
        self.assertEqual(["Tech N9ne Collabos"], self.names("Tech N9ne"))


class GuestCreditTests(unittest.TestCase):
    """A guest on a track is marked apart from a backing band.

    Merging "Travis Scott Feat. Drake" into "Travis Scott" tidies browsing but
    costs Drake his credit, so it is offered LAST and labelled for what it is.
    ROADMAP 1.3 should resolve featured credits structurally instead.
    """

    REAL = ["Travis Scott", "Travis Scott Feat. Drake",
            "Shawn James", "Shawn James and the Shapeshifters"]

    def rows(self, artist):
        return suggest(artist, self.REAL)

    def test_a_guest_billing_is_labelled_as_such(self):
        row = [r for r in self.rows("Travis Scott")
               if r["name"] == "Travis Scott Feat. Drake"][0]
        self.assertEqual("same act, guest on the track", row["reason"])

    def test_a_backing_band_reads_differently(self):
        row = [r for r in self.rows("Shawn James")
               if r["name"].endswith("Shapeshifters")][0]
        self.assertEqual("billed with a group", row["reason"])

    def test_band_billings_outrank_guest_billings(self):
        mixed = ["Shawn James", "Shawn James Feat. Someone",
                 "Shawn James and the Shapeshifters"]
        names = [r["name"] for r in suggest("Shawn James", mixed)]
        self.assertLess(names.index("Shawn James and the Shapeshifters"),
                        names.index("Shawn James Feat. Someone"))
