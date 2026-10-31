import unittest

from ampere.energy_scan import EnergyScanPolicy


class EnergyScanPolicyTests(unittest.TestCase):
    def test_incremental_plan_separates_backfills_from_new_files(self):
        plan = EnergyScanPolicy.plan(
            ["done.flac", "tail.flac", "spectral.flac", "new.flac",
             "new.flac", ""],
            energy_files={"done.flac", "tail.flac", "spectral.flac"},
            tail_files={"done.flac", "spectral.flac"},
            spectral_files={"done.flac", "tail.flac"},
            texture_files={"done.flac", "tail.flac", "spectral.flac"})
        self.assertEqual(plan.tail_backfill, ("tail.flac",))
        self.assertEqual(plan.spectral_backfill, ("spectral.flac",))
        self.assertEqual(plan.texture_backfill, ())
        self.assertEqual(plan.full_analysis, ("new.flac",))

    def test_full_result_has_stable_names_order_and_precision(self):
        values = EnergyScanPolicy.full_stickers({
            "energy": .6789, "bpm": 123.456, "tail_db": -42.04,
            "bass": .1119, "bright": .9876})
        self.assertEqual(values, (
            ("joi_energy", "0.679"), ("joi_bpm", "123.5"),
            ("joi_taildb", "-42.0"), ("joi_bass", "0.112"),
            ("joi_bright", "0.988")))

    def test_optional_bpm_and_tail_are_omitted(self):
        values = dict(EnergyScanPolicy.full_stickers({
            "energy": .2, "bpm": 0, "tail_db": None,
            "bass": .3, "bright": .4}))
        self.assertNotIn("joi_bpm", values)
        self.assertNotIn("joi_taildb", values)
        self.assertEqual(EnergyScanPolicy.tail_stickers(None), ())

    def test_spectral_backfill_uses_three_decimal_contract(self):
        self.assertEqual(EnergyScanPolicy.spectral_stickers((.1239, .8761)),
                         (("joi_bass", "0.124"),
                          ("joi_bright", "0.876")))

    def test_cooldowns_preserve_background_cpu_bounds(self):
        self.assertEqual(EnergyScanPolicy.cooldown(0, lightweight=True), .05)
        self.assertEqual(EnergyScanPolicy.cooldown(9, lightweight=True), 1.0)
        self.assertEqual(EnergyScanPolicy.cooldown(0), .10)
        self.assertEqual(EnergyScanPolicy.cooldown(1), 1.5)
        self.assertEqual(EnergyScanPolicy.cooldown(9), 3.0)


if __name__ == "__main__":
    unittest.main()


class TextureDescriptorTests(unittest.TestCase):
    """Onset density and dynamic range were computed inside the energy blend
    and discarded. They are published in their own right (2026-08-22)."""

    def test_full_result_carries_busy_and_dyn(self):
        values = dict(EnergyScanPolicy.full_stickers({
            "energy": .5, "bpm": 0, "tail_db": None,
            "bass": .3, "bright": .4, "busy": 4.567, "dyn": 11.234}))
        self.assertEqual("4.57", values["joi_busy"])
        self.assertEqual("11.23", values["joi_dyn"])

    def test_texture_backfill_contract(self):
        self.assertEqual(EnergyScanPolicy.texture_stickers((3.1, 9.87)),
                         (("joi_busy", "3.10"), ("joi_dyn", "9.87")))
        self.assertEqual(EnergyScanPolicy.texture_stickers(None), ())

    def test_a_track_analyzed_before_this_backfills_without_re_analysis(self):
        plan = EnergyScanPolicy.plan(
            ["old.flac"], energy_files={"old.flac"},
            tail_files={"old.flac"}, spectral_files={"old.flac"},
            texture_files=set())
        self.assertEqual(plan.texture_backfill, ("old.flac",))
        self.assertEqual(plan.full_analysis, ())
