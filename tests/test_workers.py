import threading
import time
import unittest

from ampere.workers import WorkerRegistry, WorkerStopping


class WorkerRegistryTests(unittest.TestCase):
    def test_shutdown_rejects_new_work_and_joins_active_work(self):
        registry = WorkerRegistry()
        entered = threading.Event()

        def work():
            entered.set()
            registry.stop_requested.wait(1)

        self.assertTrue(registry.start(work, name="owned-worker"))
        self.assertTrue(entered.wait(1))
        report = registry.shutdown(timeout=1)
        self.assertTrue(report.clean)
        self.assertEqual((), report.survivors)
        self.assertEqual((), report.pending_durable_jobs)
        self.assertFalse(registry.start(self.fail, name="too-late"))

    def test_shutdown_closes_resources_before_waiting_for_workers(self):
        registry = WorkerRegistry()
        entered = threading.Event()
        released = threading.Event()
        resource = object()

        def work():
            registry.acquire(resource, lambda _resource: released.set())
            entered.set()
            released.wait(1)
            registry.release(resource)

        registry.start(work, name="socket-worker")
        self.assertTrue(entered.wait(1))
        self.assertTrue(registry.shutdown(timeout=1).clean)
        self.assertTrue(released.is_set())

    def test_acquire_after_shutdown_closes_immediately(self):
        registry = WorkerRegistry()
        registry.shutdown()
        closed = []
        with self.assertRaises(WorkerStopping):
            registry.acquire(object(), lambda resource: closed.append(resource))
        self.assertEqual(1, len(closed))

    def test_join_budget_is_total_not_per_worker(self):
        registry = WorkerRegistry()
        gate = threading.Event()
        for number in range(3):
            registry.start(lambda: gate.wait(1), name=f"stuck-{number}")

        started = time.monotonic()
        report = registry.shutdown(timeout=0.03)
        elapsed = time.monotonic() - started
        gate.set()

        self.assertLess(elapsed, 0.15)
        self.assertEqual(("stuck-0", "stuck-1", "stuck-2"),
                         report.survivors)
        self.assertEqual((), report.pending_durable_jobs)

    def test_shutdown_identifies_surviving_durable_work(self):
        registry = WorkerRegistry()
        gate = threading.Event()
        entered = threading.Event()

        def work():
            entered.set()
            gate.wait(1)

        registry.start(
            work, name="writer-thread", durable="listening-history")
        self.assertTrue(entered.wait(1))
        report = registry.shutdown(timeout=0)
        gate.set()

        self.assertEqual(("writer-thread",), report.survivors)
        self.assertEqual(("listening-history",),
                         report.pending_durable_jobs)
        self.assertFalse(report.clean)
        self.assertIn("surviving workers: writer-thread",
                      report.failure_message)
        self.assertIn("pending durable jobs: listening-history",
                      report.failure_message)

    def test_completed_durable_work_is_not_reported_pending(self):
        registry = WorkerRegistry()
        finished = threading.Event()

        def work():
            finished.set()

        registry.start(work, name="fast-writer", durable=True)
        self.assertTrue(finished.wait(1))
        report = registry.shutdown(timeout=1)

        self.assertTrue(report.clean)
        self.assertEqual((), report.pending_durable_jobs)


if __name__ == "__main__":
    unittest.main()
