import time
import unittest

from ampere.mpdclient import Backend
class SlowProcess:
    """A capture child whose wait path would expose a synchronous stop."""

    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


class SpectrumLifecycleTests(unittest.TestCase):
    def test_prepare_import_runs_once_through_backend_worker_boundary(self):
        backend = Backend.__new__(Backend)
        backend._spec = None
        backend._spec_owners = set()
        backend._spectrum_module_ready = False
        backend._spectrum_module_warming = False
        launched = []
        prepared = []
        backend._spectrumPrepared = type("Signal", (), {
            "emit": lambda _self, value: prepared.append(value),
        })()
        backend._start_worker = lambda target, **_kwargs: launched.append(target) or True

        backend.prepareSpectrum()
        backend.prepareSpectrum()
        self.assertTrue(backend._spectrum_module_warming)
        self.assertEqual(1, len(launched))

        launched[0]()
        self.assertTrue(backend._spectrum_module_warming)
        self.assertEqual([True], prepared)
        Backend._on_spectrum_prepared(backend, prepared[0])
        self.assertFalse(backend._spectrum_module_warming)
        self.assertTrue(backend._spectrum_module_ready)

    def test_start_while_import_is_warming_never_imports_on_caller(self):
        backend = Backend.__new__(Backend)
        backend._spec = None
        backend._spec_owners = set()
        backend._spectrum_module_ready = False
        backend._spectrum_module_warming = True
        backend.prepareSpectrum = lambda: None
        backend._start_prepared_spectrum = lambda: self.fail(
            "capture cannot start until the prepared signal arrives")

        Backend.startSpectrum(backend, "ambient")

        self.assertEqual({"ambient"}, backend._spec_owners)

    def test_stop_never_waits_for_capture_process_or_reader_thread(self):
        from ampere.spectrum import SpectrumTap

        tap = SpectrumTap()
        proc = SlowProcess()
        tap._proc = proc
        tap._running.set()

        started = time.monotonic()
        tap.stop()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.1)
        self.assertFalse(tap._running.is_set())
        self.assertTrue(proc.terminated)

    def test_stop_is_idempotent(self):
        from ampere.spectrum import SpectrumTap

        tap = SpectrumTap()
        tap.stop()
        tap.stop()


if __name__ == "__main__":
    unittest.main()
