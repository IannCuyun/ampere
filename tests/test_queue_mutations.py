import threading
import unittest

from ampere.queue_mutations import QueueMutationCoordinator


class QueueMutationCoordinatorTests(unittest.TestCase):
    def test_contender_is_rejected_without_waiting(self):
        coordinator = QueueMutationCoordinator()
        entered = threading.Event()
        release = threading.Event()

        def operation():
            entered.set()
            release.wait(1)
            return "done"

        result = []
        worker = threading.Thread(
            target=lambda: result.append(coordinator.run("bridge", operation)))
        worker.start()
        self.assertTrue(entered.wait(1))

        rejected = coordinator.run("playback", lambda: "must not run")
        self.assertFalse(rejected.accepted)
        self.assertEqual("bridge", rejected.active_owner)

        release.set()
        worker.join(1)
        self.assertTrue(result[0].accepted)
        self.assertEqual("done", result[0].value)

    def test_failure_releases_owner_and_next_generation_can_run(self):
        coordinator = QueueMutationCoordinator()

        with self.assertRaisesRegex(RuntimeError, "boom"):
            coordinator.run(
                "failed", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        recovered = coordinator.run("next", lambda: True)
        self.assertTrue(recovered.accepted)
        self.assertTrue(recovered.value)
        self.assertEqual(2, recovered.generation)
        self.assertEqual("", coordinator.active_owner)

    def test_explicit_lease_holds_authority_until_publication_releases(self):
        coordinator = QueueMutationCoordinator()
        lease, rejected = coordinator.acquire("bridge-worker")

        self.assertIsNone(rejected)
        self.assertEqual("bridge-worker", coordinator.active_owner)
        contender = coordinator.run("dj-reset", lambda: True)
        self.assertFalse(contender.accepted)
        self.assertEqual("bridge-worker", contender.active_owner)

        lease.release()
        self.assertEqual("", coordinator.active_owner)
        self.assertTrue(coordinator.run("dj-reset", lambda: True).accepted)
