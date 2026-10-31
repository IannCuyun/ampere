import threading
import unittest

from ampere.enrichment import EnrichmentCoordinator
from ampere.workers import WorkerRegistry


class EnrichmentCoordinatorTests(unittest.TestCase):
    def test_named_job_is_exclusive_and_completion_runs(self):
        workers = WorkerRegistry()
        coordinator = EnrichmentCoordinator(workers)
        entered, release, finished = (threading.Event() for _ in range(3))

        def job():
            entered.set()
            release.wait(1)

        self.assertEqual("started", coordinator.launch(
            "energy", job, on_finished=finished.set))
        self.assertTrue(entered.wait(1))
        self.assertEqual("busy", coordinator.launch("energy", self.fail))
        release.set()
        self.assertTrue(finished.wait(1))
        self.assertFalse(coordinator.running("energy"))
        workers.shutdown()

    def test_coalescing_retains_only_one_pending_rerun(self):
        workers = WorkerRegistry()
        coordinator = EnrichmentCoordinator(workers)
        entered, release, finished = (threading.Event() for _ in range(3))

        self.assertEqual("started", coordinator.launch(
            "index", lambda: (entered.set(), release.wait(1)),
            coalesce=True, on_finished=finished.set))
        self.assertTrue(entered.wait(1))
        self.assertEqual("pending", coordinator.launch(
            "index", self.fail, coalesce=True))
        self.assertEqual("pending", coordinator.launch(
            "index", self.fail, coalesce=True))
        release.set()
        self.assertTrue(finished.wait(1))
        self.assertTrue(coordinator.consume_pending("index"))
        self.assertFalse(coordinator.consume_pending("index"))
        workers.shutdown()

    def test_shutdown_rejects_launch_without_leaving_job_active(self):
        workers = WorkerRegistry()
        workers.shutdown()
        coordinator = EnrichmentCoordinator(workers)

        self.assertEqual("stopping", coordinator.launch("rg", self.fail))
        self.assertFalse(coordinator.running("rg"))


if __name__ == "__main__":
    unittest.main()
