import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ampere.mpd_config import MpdConfigService, NormalizationResult
from ampere.mpdclient import Backend


class MpdConfigServiceTests(unittest.TestCase):
    def service(self, directory, text):
        path = Path(directory) / "mpd.conf"
        path.write_text(text)
        return path, MpdConfigService(path, "/run/user/1000/mpd/socket")

    def test_reads_quoted_and_unquoted_preamps_with_safe_defaults(self):
        with TemporaryDirectory() as tmp:
            _path, service = self.service(
                tmp,
                'replaygain_preamp "-2.5"\nreplaygain_missing_preamp 3\n',
            )
            self.assertEqual((-2.5, 3.0), service.read_preamps())

    def test_preamps_are_clamped_and_inserted_as_one_atomic_document(self):
        with TemporaryDirectory() as tmp:
            path, service = self.service(tmp, 'replaygain "track"\naudio_output {}\n')
            self.assertEqual((15.0, -15.0), service.set_preamps(99, -99))
            text = path.read_text()
            self.assertIn('replaygain_preamp "15"', text)
            self.assertIn('replaygain_missing_preamp "-15"', text)
            self.assertEqual((15.0, -15.0), service.read_preamps())

    def test_existing_preamps_are_replaced_without_duplicates(self):
        with TemporaryDirectory() as tmp:
            path, service = self.service(
                tmp,
                'replaygain_preamp "1"\nreplaygain_missing_preamp "6"\n',
            )
            service.set_preamps(-4.4, 5.6)
            text = path.read_text()
            self.assertEqual(1, text.count("replaygain_preamp"))
            self.assertEqual(1, text.count("replaygain_missing_preamp"))
            self.assertEqual((-4.0, 6.0), service.read_preamps())

    def test_socket_binding_is_idempotent_and_backup_is_first_version(self):
        with TemporaryDirectory() as tmp:
            path, service = self.service(tmp, 'music_directory "/music"\n')
            original = path.read_text()
            self.assertTrue(service.ensure_socket_binding())
            self.assertFalse(service.ensure_socket_binding())
            backup = path.with_suffix(".conf.ampere-bak")
            self.assertEqual(original, backup.read_text())
            self.assertEqual(1, path.read_text().count("/run/user/1000/mpd/socket"))

    def test_socket_activation_restart_requires_authoritative_stopped_state(self):
        self.assertTrue(MpdConfigService.socket_restart_safe({"state": "stop"}))
        for status in (None, {}, {"state": "pause"}, {"state": "play"},
                       {"state": "unknown"}):
            with self.subTest(status=status):
                self.assertFalse(MpdConfigService.socket_restart_safe(status))

    def test_backend_socket_repair_never_restarts_a_paused_session(self):
        events = []

        class Config:
            def ensure_socket_binding(self):
                events.append("binding")

            socket_restart_safe = staticmethod(
                MpdConfigService.socket_restart_safe)

        class Probe:
            def status(self):
                return {"state": "pause", "songid": "42"}

        class Scope:
            def __enter__(self):
                return Probe()

            def __exit__(self, *_args):
                pass

        backend = type("BackendStub", (), {
            "_mpd_config": Config(), "_workers": object(),
            "_start_worker": lambda self, work, **_kwargs: work() or True,
        })()
        with patch.dict(os.environ, {"AMPERE_MPD_HOST": ""}), \
                patch("ampere.mpdclient.os.path.exists", return_value=False), \
                patch("ampere.mpdclient.temporary_mpd_client",
                      return_value=Scope()), \
                patch("ampere.mpdclient.subprocess.run") as restart:
            Backend._ensure_mpd_socket(backend)

        self.assertEqual(["binding"], events)
        restart.assert_not_called()

    def test_socket_activation_defers_probe_and_restart_to_owned_worker(self):
        events = []

        class Config:
            def ensure_socket_binding(self):
                events.append("binding")

            socket_restart_safe = staticmethod(
                MpdConfigService.socket_restart_safe)

        class Probe:
            def status(self):
                events.append("probe")
                return {"state": "stop"}

        class Scope:
            def __enter__(self):
                return Probe()

            def __exit__(self, *_args):
                pass

        pending = []
        backend = type("BackendStub", (), {
            "_mpd_config": Config(), "_workers": object(),
            "_start_worker": lambda self, work, **kwargs: (
                pending.append((work, kwargs)) or True),
        })()
        with patch.dict(os.environ, {"AMPERE_MPD_HOST": ""}), \
                patch("ampere.mpdclient.os.path.exists", return_value=False), \
                patch("ampere.mpdclient.temporary_mpd_client",
                      return_value=Scope()), \
                patch("ampere.mpdclient.subprocess.run") as restart:
            Backend._ensure_mpd_socket(backend)

            self.assertEqual(["binding"], events)
            restart.assert_not_called()
            self.assertEqual("ampere-mpd-socket-activation",
                             pending[0][1]["name"])

            pending[0][0]()

        self.assertEqual(["binding", "probe"], events)
        restart.assert_called_once_with(
            ["systemctl", "--user", "restart", "mpd"], check=False)

    def test_normalization_restores_exact_document_after_restart_failure(self):
        with TemporaryDirectory() as tmp:
            original = ('replaygain "track"\nreplaygain_preamp "1"\n'
                        'replaygain_missing_preamp "2"\n')
            path, service = self.service(tmp, original)
            outcomes = iter([False, True])

            result = service.apply_preamps(
                6, -6, restart=lambda: next(outcomes))

            self.assertEqual(
                NormalizationResult(False, 6.0, -6.0, True), result)
            self.assertEqual(original, path.read_text())

    def test_normalization_publishes_values_after_successful_restart(self):
        with TemporaryDirectory() as tmp:
            path, service = self.service(tmp, 'replaygain "track"\n')
            calls = []
            result = service.apply_preamps(
                2.4, -2.6, restart=lambda: calls.append(True) or True)
            self.assertEqual(
                NormalizationResult(True, 2.0, -3.0), result)
            self.assertEqual([True], calls)
            self.assertEqual((2.0, -3.0), service.read_preamps())

    def test_backend_normalization_delegates_and_publishes_saved_values(self):
        events = []

        class Signal:
            def emit(self, *values): events.append(values or ("changed",))

        backend = type("BackendStub", (), {})()
        backend._normalization_busy = True
        backend.errorOccurred = Signal()
        backend.settingsChanged = Signal()
        backend._mark_disconnected = lambda: events.append(("disconnected",))
        backend.requestStatusRefresh = lambda: events.append(("status",))
        backend._request_queue_refresh = lambda: events.append(("queue",))
        backend._refresh_replay_gain = lambda: events.append(("replaygain",))
        Backend._on_normalization_ready(backend, {
            "result": NormalizationResult(True, 2.0, -3.0),
        })

        self.assertEqual((2.0, -3.0),
                         (backend._rg_preamp, backend._rg_missing_preamp))
        self.assertEqual([
            ("changed",), ("disconnected",), ("status",), ("queue",),
            ("replaygain",),
        ], events)

    def test_backend_normalization_admits_only_one_owned_worker(self):
        backend = type("BackendStub", (), {})()
        backend._normalization_busy = False
        launched = []
        emitted = []
        backend._mpd_config = type("Config", (), {
            "apply_preamps": lambda _self, preamp, missing, *, restart: (
                restart() and NormalizationResult(
                    True, float(preamp), float(missing))),
        })()
        backend._normalizationReady = type("Signal", (), {
            "emit": lambda _self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **kwargs: (
            launched.append((work, kwargs)) or True)

        self.assertTrue(Backend.applyNormalization(backend, 2.4, -2.6))
        self.assertFalse(Backend.applyNormalization(backend, 6, 6))
        self.assertEqual("ampere-normalization-apply",
                         launched[0][1]["name"])
        with patch("ampere.mpdclient.subprocess.run") as restart:
            restart.return_value.returncode = 0
            launched[0][0]()
        restart.assert_called_once_with(
            ["systemctl", "--user", "restart", "mpd"], check=False)
        self.assertTrue(emitted[0]["result"].success)

    def test_backend_retains_published_values_when_activation_rolls_back(self):
        events = []

        class Config:
            def apply_preamps(self, *_args, **_kwargs):
                return NormalizationResult(False, 6.0, 6.0, True)

        class Signal:
            def emit(self, *values):
                events.append(values)

        backend = type("BackendStub", (), {})()
        backend._normalization_busy = True
        backend._rg_preamp, backend._rg_missing_preamp = 1.0, 2.0
        backend.errorOccurred = Signal()
        backend.settingsChanged = Signal()

        Backend._on_normalization_ready(backend, {
            "result": Config().apply_preamps(),
        })

        self.assertEqual((1.0, 2.0),
                         (backend._rg_preamp, backend._rg_missing_preamp))
        self.assertIn("prior configuration was restored", events[-1][0])


if __name__ == "__main__":
    unittest.main()
