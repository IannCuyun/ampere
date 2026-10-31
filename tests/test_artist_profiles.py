import threading
import time
import unittest

from ampere.artist_profiles import ArtistPortraitCoordinator
from ampere.workers import WorkerRegistry


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class FakeService:
    def __init__(self, cached=None, results=None):
        self.cached = dict(cached or {})
        self.results = dict(results or {})
        self.peeks = []
        self.gets = []
        self.maintenance_calls = 0
        self.lock = threading.Lock()

    def maintain_portrait_cache(self):
        with self.lock:
            self.maintenance_calls += 1

    def peek_cached(self, name):
        with self.lock:
            self.peeks.append(name)
        value = self.cached.get(name)
        return dict(value) if value else None

    def get(self, name):
        with self.lock:
            self.gets.append(name)
        value = self.results.get(name, {
            "found": False, "portrait": "", "portraitRetryable": False,
        })
        if callable(value):
            value = value()
        return dict(value)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.workers = WorkerRegistry()
        self.results = []
        self.batches = []

    def tearDown(self):
        self.workers.shutdown(timeout=1)

    def coordinator(self, service, **kwargs):
        kwargs.setdefault("retry_delay", 0.01)
        return ArtistPortraitCoordinator(
            service, self.workers,
            canonicalize=lambda name: {"Alias": "Artist"}.get(name, name),
            on_result=lambda name, info: self.results.append((name, info)),
            on_batch=lambda batch: self.batches.append(batch),
            **kwargs)

    def test_prime_hydrates_cache_in_one_batch_without_network(self):
        service = FakeService(cached={
            "Alpha": {"portrait": "alpha", "found": True},
            "Beta": {"portrait": "beta", "found": True},
        })
        coordinator = self.coordinator(service)

        coordinator.prime(["Alpha", "Beta"])

        self.assertTrue(wait_until(lambda: len(self.batches) == 1))
        self.assertEqual({"Alpha": "alpha", "Beta": "beta"},
                         self.batches[0])
        self.assertEqual([], service.gets)
        self.assertEqual(1, service.maintenance_calls)

    def test_visible_promotes_a_queued_idle_artist(self):
        gate = threading.Event()

        def blocking():
            gate.wait(1)
            return {"portrait": "ready", "found": True}

        service = FakeService(results={
            "Alpha": blocking, "Beta": blocking, "Gamma": blocking,
        })
        coordinator = self.coordinator(service, max_workers=1, max_idle=1)
        coordinator.prime(["Alpha", "Beta", "Gamma"])
        self.assertTrue(wait_until(lambda: len(service.peeks) == 3))
        coordinator.set_active(True)
        self.assertTrue(wait_until(lambda: len(service.gets) == 1))

        coordinator.prioritize(["Gamma"], [])
        gate.set()

        self.assertTrue(wait_until(lambda: len(service.gets) >= 2))
        self.assertEqual("Gamma", service.gets[1])

    def test_total_and_idle_concurrency_are_bounded(self):
        gate = threading.Event()
        active = 0
        peak = 0
        lock = threading.Lock()

        def blocking():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            gate.wait(1)
            with lock:
                active -= 1
            return {"portrait": "ready", "found": True}

        names = [f"Artist {index}" for index in range(8)]
        service = FakeService(results={name: blocking for name in names})
        coordinator = self.coordinator(service, max_workers=4, max_idle=2)
        coordinator.prime(names)
        coordinator.set_active(True)
        self.assertTrue(wait_until(lambda: len(service.gets) == 2))

        coordinator.prioritize(names[2:6], [])
        self.assertTrue(wait_until(lambda: len(service.gets) == 4))
        time.sleep(0.03)
        self.assertEqual(4, peak)
        gate.set()

    def test_requests_coalesce_across_alias_and_direct_consumers(self):
        gate = threading.Event()

        def blocking():
            gate.wait(1)
            return {"portrait": "ready", "found": True}

        service = FakeService(results={"Artist": blocking})
        coordinator = self.coordinator(service)
        coordinator.request("Alias")
        coordinator.request("Artist")
        self.assertTrue(wait_until(lambda: len(service.gets) == 1))
        gate.set()
        self.assertTrue(wait_until(lambda: len(self.results) == 2))
        self.assertEqual({"Alias", "Artist"},
                         {name for name, _result in self.results})
        self.assertEqual(["Artist"], service.gets)

    def test_idle_pauses_and_resumes_with_artist_room(self):
        service = FakeService(results={
            "Alpha": {"portrait": "alpha", "found": True},
        })
        coordinator = self.coordinator(service)
        coordinator.prime(["Alpha"])
        self.assertTrue(wait_until(lambda: service.peeks == ["Alpha"]))
        time.sleep(0.03)
        self.assertEqual([], service.gets)

        coordinator.set_active(True)
        self.assertTrue(wait_until(lambda: service.gets == ["Alpha"]))

    def test_retryable_miss_retries_once(self):
        calls = 0

        def result():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"portrait": "", "portraitRetryable": True}
            return {"portrait": "ready", "found": True}

        service = FakeService(results={"Alpha": result})
        coordinator = self.coordinator(service)
        coordinator.request("Alpha")

        self.assertTrue(wait_until(lambda: len(self.results) == 1))
        self.assertEqual(2, calls)
        self.assertEqual("ready", self.results[0][1]["portrait"])

    def test_direct_request_promotes_an_idle_retry_while_room_is_inactive(self):
        first_done = threading.Event()
        calls = 0

        def result():
            nonlocal calls
            calls += 1
            if calls == 1:
                first_done.set()
                return {"portrait": "", "portraitRetryable": True}
            return {"portrait": "ready", "found": True}

        service = FakeService(results={"Alpha": result})
        coordinator = self.coordinator(service, retry_delay=0.05)
        coordinator.prime(["Alpha"])
        coordinator.set_active(True)
        self.assertTrue(first_done.wait(1))
        coordinator.set_active(False)
        coordinator.request("Alpha")

        self.assertTrue(wait_until(lambda: len(self.results) == 1))
        self.assertEqual(2, calls)


if __name__ == "__main__":
    unittest.main()
