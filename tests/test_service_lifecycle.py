import unittest
import threading
import socket
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from PySide6.QtCore import QProcess

from ampere.mpdclient import Backend
from ampere.main import ApplicationLifecycle, _engine_down
from ampere.peq import EqManager
from ampere.workers import WorkerShutdownReport


class TimerStub:
    def __init__(self): self.stops = 0
    def stop(self): self.stops += 1


class ResourceStub:
    def __init__(self): self.stops = 0
    def stop(self): self.stops += 1


class WatcherStub:
    class Signal:
        def __init__(self): self.disconnected = 0
        def disconnect(self, _slot): self.disconnected += 1

    def __init__(self):
        self.readyReadStandardOutput = self.Signal()
        self.terminated = self.killed = self.deleted = 0

    def state(self): return QProcess.ProcessState.Running
    def terminate(self): self.terminated += 1
    def waitForFinished(self, _timeout): return True
    def kill(self): self.killed += 1
    def deleteLater(self): self.deleted += 1


class SocketStub:
    def __init__(self): self.shutdowns = []
    def shutdown(self, how): self.shutdowns.append(how)


class IdleClientStub:
    def __init__(self): self._sock = SocketStub()


class ThreadStub:
    def __init__(self): self.joins = []
    def join(self, timeout=None): self.joins.append(timeout)


class WorkersStub:
    def __init__(self, report):
        self.report = report
        self.timeouts = []

    def shutdown(self, timeout=None):
        self.timeouts.append(timeout)
        return self.report


class ServiceLifecycleTests(unittest.TestCase):
    def test_engine_closes_all_tracked_clients_before_stopping_mpd(self):
        events = []

        class Gateway:
            def close(self): events.append("gateway")

        backend = type("BackendStub", (), {
            "_state": "pause",
            "_gateway": Gateway(),
            "_save_conf": lambda self: events.append("save"),
        })()
        with patch("ampere.main.close_all_mpd_clients",
                   side_effect=lambda: events.append("all")), \
                patch("ampere.main.subprocess.run",
                      side_effect=lambda *_args, **_kwargs: events.append("mpd")):
            _engine_down(backend)

        self.assertEqual(["save", "gateway", "all", "mpd"], events)

    def test_application_lifecycle_releases_services_in_order_once(self):
        events = []

        class BackendLifecycleStub:
            def shutdownServices(self): events.append("backend")

        class NamedResource:
            def __init__(self, name): self.name = name
            def stop(self): events.append(self.name)
            def shutdown(self): events.append(self.name)

        backend = BackendLifecycleStub()
        lifecycle = ApplicationLifecycle(
            backend, engine_down=lambda owner: events.append(
                "engine" if owner is backend else "wrong owner"))
        lifecycle.attach_eq(NamedResource("eq"))
        lifecycle.attach_mpris(NamedResource("mpris"))

        lifecycle.shutdown()
        lifecycle.shutdown()

        self.assertEqual(["mpris", "eq", "backend", "engine"], events)

    def test_application_lifecycle_continues_after_one_cleanup_fails(self):
        events = []

        class BrokenMpris:
            def shutdown(self):
                events.append("mpris")
                raise RuntimeError("already gone")

        class EqStub:
            def stop(self): events.append("eq")

        class BackendStub:
            def shutdownServices(self): events.append("backend")

        backend = BackendStub()
        lifecycle = ApplicationLifecycle(
            backend, engine_down=lambda _owner: events.append("engine"))
        lifecycle.attach_mpris(BrokenMpris())
        lifecycle.attach_eq(EqStub())

        stderr = StringIO()
        with redirect_stderr(stderr):
            failures = lifecycle.shutdown()

        self.assertEqual(["mpris", "eq", "backend", "engine"], events)
        self.assertEqual((("MPRIS", "already gone"),), failures)
        self.assertIn("shutdown warning [MPRIS]: already gone",
                      stderr.getvalue())

    def test_application_lifecycle_retains_every_failed_stage_once(self):
        class BrokenBackend:
            def shutdownServices(self):
                raise RuntimeError("worker stuck")

        lifecycle = ApplicationLifecycle(
            BrokenBackend(),
            engine_down=lambda _owner: (_ for _ in ()).throw(
                RuntimeError("service remained active")))

        stderr = StringIO()
        with redirect_stderr(stderr):
            first = lifecycle.shutdown()
            second = lifecycle.shutdown()

        self.assertEqual(first, second)
        self.assertEqual((
            ("Backend services", "worker stuck"),
            ("MPD engine", "service remained active"),
        ), first)
        self.assertEqual(2, stderr.getvalue().count("Ampere shutdown warning"))

    def test_application_lifecycle_propagates_nonclean_worker_report(self):
        events = []

        class BackendStub:
            def shutdownServices(self):
                events.append("backend")
                return WorkerShutdownReport(
                    survivors=("ampere-library-delete",),
                    pending_durable_jobs=("ampere-library-delete",),
                )

        lifecycle = ApplicationLifecycle(
            BackendStub(),
            engine_down=lambda _owner: events.append("engine"))

        stderr = StringIO()
        with redirect_stderr(stderr):
            failures = lifecycle.shutdown()

        self.assertEqual(["backend", "engine"], events)
        self.assertEqual((
            ("Backend services",
             "surviving workers: ampere-library-delete; pending durable "
             "jobs: ampere-library-delete"),
        ), failures)
        self.assertIn("ampere-library-delete", stderr.getvalue())

    def test_engine_stop_rejection_is_failure_after_clients_close(self):
        events = []
        stopped = type("Completed", (), {"returncode": 1})()
        with patch("ampere.main.close_all_mpd_clients",
                   side_effect=lambda: events.append("clients")), \
                patch("ampere.main.subprocess.run",
                      side_effect=lambda *_args, **_kwargs: (
                          events.append("stop") or stopped)):
            with self.assertRaisesRegex(RuntimeError,
                                        "systemctl exited 1"):
                _engine_down()

        self.assertEqual(["clients", "stop"], events)

    def test_eq_stop_reaps_subscription_and_is_idempotent(self):
        manager = EqManager()
        watcher = WatcherStub()
        manager._watcher = watcher
        manager.stop()
        manager.stop()
        self.assertEqual(watcher.terminated, 1)
        self.assertEqual(watcher.killed, 0)
        self.assertEqual(watcher.deleted, 1)

    def test_backend_shutdown_releases_remote_and_spectrum_once(self):
        remote, spectrum, timer = ResourceStub(), ResourceStub(), TimerStub()
        backend = type("BackendStub", (), {})()
        backend._conf_save_timer = timer
        backend._save_conf = lambda: None
        backend._remote_control = remote
        backend._spec = spectrum
        backend._spec_owners = {"now", "ambient"}
        backend._idle_stop = threading.Event()
        backend._idle_client = IdleClientStub()
        backend._idle_thread = ThreadStub()
        first = Backend.shutdownServices(backend)
        second = Backend.shutdownServices(backend)
        self.assertTrue(first.clean)
        self.assertTrue(second.clean)
        self.assertEqual(remote.stops, 1)
        self.assertEqual(spectrum.stops, 1)
        self.assertEqual(timer.stops, 2)
        self.assertEqual(backend._spec_owners, set())
        self.assertTrue(backend._idle_stop.is_set())
        self.assertEqual(backend._idle_client._sock.shutdowns,
                         [socket.SHUT_RDWR, socket.SHUT_RDWR])

    def test_backend_names_queued_durable_jobs_without_guessing_busy_flags(self):
        backend = type("BackendStub", (), {})()
        backend._listening_progress_jobs = [{}, {}]
        backend._replay_gain_pending = {"mode": "track"}
        backend._remote_lifecycle_pending = None
        backend._transition_settings_pending = {"crossfade": 5}
        backend._transition_internal_pending = None
        backend._dj_set_save_lock = threading.Lock()
        backend._dj_set_save_pending = {"snapshot": {}}

        self.assertEqual((
            "ampere-dj-set-save (queued)",
            "ampere-listening-progress (2 queued)",
            "ampere-replay-gain-mode (queued)",
            "ampere-transition-settings (queued)",
        ), Backend._pending_durable_shutdown_jobs(backend))

    def test_backend_names_queued_internal_transition_work(self):
        backend = type("BackendStub", (), {})()
        backend._transition_internal_pending = {
            "internal": True, "crossfade": 9,
        }

        self.assertEqual((
            "ampere-transition-settings (queued)",
        ), Backend._pending_durable_shutdown_jobs(backend))

    def test_backend_keeps_unpublished_durable_work_nonclean(self):
        backend = type("BackendStub", (), {})()
        backend._replay_gain_active = {"persist": True, "mode": "track"}
        backend._remote_lifecycle_active = {"on": True}
        backend._transition_settings_active = {
            "internal": False, "crossfade": 5,
        }
        backend._deleting = True

        self.assertEqual((
            "ampere-library-delete-workflow",
            "ampere-remote-lifecycle",
            "ampere-replay-gain-mode",
            "ampere-transition-settings",
        ), Backend._pending_durable_shutdown_jobs(backend))

    def test_backend_returns_worker_failure_after_finishing_other_cleanup(self):
        remote, spectrum, timer = ResourceStub(), ResourceStub(), TimerStub()
        report = WorkerShutdownReport(
            survivors=("stuck-reader", "stuck-writer"),
            pending_durable_jobs=("stuck-writer",),
        )
        workers = WorkersStub(report)
        backend = type("BackendStub", (), {})()
        backend._conf_save_timer = timer
        backend._save_conf = lambda: None
        backend._workers = workers
        backend._remote_control = remote
        backend._spec = spectrum
        backend._spec_owners = set()
        backend._idle_stop = threading.Event()
        backend._idle_client = IdleClientStub()
        backend._idle_thread = ThreadStub()

        result = Backend.shutdownServices(backend)

        self.assertIs(report, result)
        self.assertEqual([3], workers.timeouts)
        self.assertEqual(remote.stops, 1)
        self.assertEqual(spectrum.stops, 1)


if __name__ == "__main__":
    unittest.main()
