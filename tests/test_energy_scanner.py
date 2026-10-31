import contextlib
import unittest

from ampere.energy_scan import EnergyScanner


class Client:
    def __init__(self, inventories=None, *, inventory_error=False):
        self.inventories = inventories or {}
        self.inventory_error = inventory_error
        self.writes = []

    def sticker_find(self, _kind, _uri, key):
        if self.inventory_error:
            raise OSError("MPD unavailable")
        return [{"file": file} for file in self.inventories.get(key, ())]

    def sticker_set(self, _kind, file, key, value):
        self.writes.append((file, key, value))


def scope(client):
    return lambda: contextlib.nullcontext(client)


class EnergyScannerTests(unittest.TestCase):
    def test_executes_each_incremental_lane_and_accounts_for_work(self):
        client = Client({
            "joi_energy": ["tail", "spectral"],
            "joi_taildb": ["spectral"],
            "joi_bass": ["tail"],
        })
        sleeps = []
        scanner = EnergyScanner(
            "/music", client_scope=scope(client),
            tail_db=lambda path: -12.25,
            spectral=lambda path: (.2, .8),
            texture=lambda path: (4.5, 11.0),
            analyze=lambda path: {
                "energy": .5, "bpm": 120, "tail_db": -9,
                "bass": .3, "bright": .7, "busy": 4.5, "dyn": 11.0,
            },
            clock=iter([0, .2, 1, 1.4, 2, 2.5, 3, 3.4, 4, 4.5]).__next__,
            sleep=sleeps.append)

        result = scanner.scan(["tail", "spectral", "full"])

        # Onset density and dynamic range are a fourth incremental lane:
        # both already-analyzed files carry joi_energy but no joi_busy, so
        # they backfill without a re-analysis (2026-08-22).
        self.assertEqual((5, 5, 1, 1, 2, 1, 0, False), (
            result.total, result.done, result.tail_backfilled,
            result.spectral_backfilled, result.texture_backfilled,
            result.fully_analyzed, result.failed, result.cancelled))
        self.assertEqual(5, len(sleeps))
        self.assertIn(("full", "joi_bpm", "120.0"), client.writes)
        self.assertIn(("full", "joi_busy", "4.50"), client.writes)
        self.assertIn(("tail", "joi_dyn", "11.00"), client.writes)

    def test_inventory_failure_aborts_instead_of_scheduling_full_library(self):
        analyses = []
        result = EnergyScanner(
            "/music", client_scope=scope(Client(inventory_error=True)),
            analyze=lambda path: analyses.append(path)).scan(["one", "two"])

        self.assertEqual([], analyses)
        self.assertTrue(result.inventory_failed)
        self.assertTrue(result.cancelled)
        self.assertEqual((0, 1), (result.done, result.failed))

    def test_cancellation_reports_actual_completed_work(self):
        client = Client()
        stopped = [False]

        def analyze(_path):
            stopped[0] = True
            return {"energy": .5, "bass": .2, "bright": .8}

        result = EnergyScanner(
            "/music", client_scope=scope(client), analyze=analyze,
            sleep=lambda _seconds: None).scan(
                ["one", "two"], should_stop=lambda: stopped[0])

        self.assertEqual((2, 1, 1, True), (
            result.total, result.done, result.fully_analyzed,
            result.cancelled))

    def test_analysis_failure_is_contained_and_counted(self):
        result = EnergyScanner(
            "/music", client_scope=scope(Client()),
            analyze=lambda _path: 1 / 0,
            sleep=lambda _seconds: None).scan(["bad"])
        self.assertEqual((1, 1, 0, False), (
            result.done, result.failed, result.fully_analyzed,
            result.cancelled))


if __name__ == "__main__":
    unittest.main()
