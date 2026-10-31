import tempfile
import unittest
from pathlib import Path

from ampere.cache_maintenance import CacheClearResult, CacheMaintenanceService
from ampere.mpdclient import Backend


class Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class CacheMaintenanceTests(unittest.TestCase):
    def test_clears_only_configured_cache_directories(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            art = root / "art"
            waves = root / "waves"
            adjacent = root / "keep"
            for path in (art, waves, adjacent):
                path.mkdir()
                (path / "entry").write_text("data")

            result = CacheMaintenanceService(
                {"art": art, "waveform": waves}).clear()

            self.assertTrue(result.success)
            self.assertEqual(("art", "waveform"), result.cleared)
            self.assertFalse(art.exists())
            self.assertFalse(waves.exists())
            self.assertTrue((adjacent / "entry").exists())

    def test_missing_caches_are_a_valid_idempotent_success(self):
        with tempfile.TemporaryDirectory() as root:
            result = CacheMaintenanceService({
                "art": Path(root) / "missing-art",
                "waveform": Path(root) / "missing-waves",
            }).clear()

        self.assertTrue(result.success)
        self.assertEqual(("art", "waveform"), result.already_empty)
        self.assertEqual((), result.failures)

    def test_partial_failure_is_explicit_and_other_cache_still_clears(self):
        def remove(path):
            if path.name == "art":
                raise PermissionError("read only")
            path.rmdir()

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            art = root / "art"
            waves = root / "waves"
            art.mkdir()
            waves.mkdir()
            result = CacheMaintenanceService(
                {"art": art, "waveform": waves}, remove=remove).clear()

        self.assertFalse(result.success)
        self.assertEqual(("waveform",), result.cleared)
        self.assertEqual("art", result.failures[0][0])
        self.assertIn("read only", result.failures[0][1])


class CacheMaintenanceBackendTests(unittest.TestCase):
    def backend(self, result):
        backend = type("CacheAdapter", (), {})()
        backend._cache_clear_busy = False
        backend._cache_maintenance = type(
            "Service", (), {"clear": lambda _self: result})()
        backend._workers = object()
        backend.results = []
        backend._cacheClearReady = type("ReadySignal", (), {
            "emit": lambda _self, value: backend.results.append(value),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        backend.errorOccurred = Signal()
        return backend

    def test_backend_reports_verified_success(self):
        backend = self.backend(CacheClearResult(True, ("art", "waveform")))

        self.assertTrue(Backend.clearCaches(backend))
        self.assertTrue(backend._cache_clear_busy)
        self.assertEqual([], backend.errorOccurred.messages)
        self.assertTrue(Backend._on_cache_clear_ready(
            backend, backend.results[0]))
        self.assertFalse(backend._cache_clear_busy)
        self.assertEqual(
            ["Art + waveform + artist biography caches cleared"],
                         backend.errorOccurred.messages)

    def test_backend_reports_partial_failure_without_claiming_success(self):
        backend = self.backend(CacheClearResult(
            False, ("waveform",), (), (("art", "permission denied"),)))

        self.assertTrue(Backend.clearCaches(backend))
        self.assertFalse(Backend._on_cache_clear_ready(
            backend, backend.results[0]))
        self.assertEqual(
            ["Cache clear incomplete · could not remove art"],
            backend.errorOccurred.messages)

    def test_duplicate_click_is_rejected_without_second_delete(self):
        backend = self.backend(CacheClearResult(True))
        backend._cache_clear_busy = True
        backend._cache_maintenance.clear = lambda: self.fail(
            "duplicate must not start another delete")

        self.assertFalse(Backend.clearCaches(backend))

        self.assertEqual(
            ["Cache clear is already running"],
            backend.errorOccurred.messages)

    def test_worker_start_failure_releases_busy_state(self):
        backend = self.backend(CacheClearResult(True))
        backend._start_worker = lambda *_args, **_kwargs: False

        self.assertFalse(Backend.clearCaches(backend))

        self.assertFalse(backend._cache_clear_busy)
        self.assertEqual(
            ["Cache clear could not finish · retry from Settings"],
            backend.errorOccurred.messages)


if __name__ == "__main__":
    unittest.main()
