import unittest
import contextlib
from unittest.mock import patch

from mpd.base import ConnectionError as MPDConnectionError

from ampere.loudness import (ReplayGainModeController, ReplayGainModeResult,
                            ReplayGainScanner)
from ampere.mpdclient import Backend


class ReplayGainScannerTests(unittest.TestCase):
    def test_scans_only_missing_files_and_batches_progress(self):
        tagged_paths, reports, sleeps = [], [], []
        scanner = ReplayGainScanner(
            "/music",
            has_rg=lambda path: path.endswith("ready.flac"),
            tag_file=lambda path: tagged_paths.append(path) or "tagged",
            clock=iter([0.0, 0.2, 1.0, 1.4]).__next__,
            sleep=sleeps.append,
        )

        result = scanner.scan(
            ["ready.flac", "one.flac", "two.flac"], progress=lambda *v: reports.append(v))

        self.assertEqual(["/music/one.flac", "/music/two.flac"], tagged_paths)
        self.assertEqual([(2, 2, 2)], reports)
        self.assertEqual(2, len(sleeps))
        self.assertAlmostEqual(0.2, sleeps[0])
        self.assertAlmostEqual(0.4, sleeps[1])
        self.assertEqual((2, 2, False),
                         (result.done, result.tagged, result.cancelled))

    def test_cancellation_reports_actual_work_instead_of_false_completion(self):
        stopped, reports = [False], []

        def tag(_path):
            stopped[0] = True
            return "tagged"

        scanner = ReplayGainScanner(
            "/music", has_rg=lambda _path: False, tag_file=tag,
            clock=lambda: 0.0, sleep=lambda _seconds: None)
        result = scanner.scan(
            ["one", "two", "three"], should_stop=lambda: stopped[0],
            progress=lambda *v: reports.append(v))

        self.assertEqual([(1, 3, 1)], reports)
        self.assertEqual((3, 1, 1, True),
                         (result.total, result.done, result.tagged,
                          result.cancelled))

    def test_complete_library_emits_stable_empty_progress(self):
        reports = []
        scanner = ReplayGainScanner(
            "/music", has_rg=lambda _path: True,
            tag_file=lambda _path: self.fail("nothing should be tagged"))
        result = scanner.scan(["ready"], progress=lambda *v: reports.append(v))
        self.assertEqual([(0, 0, 0)], reports)
        self.assertEqual(0, result.total)


class ReplayGainClient:
    def __init__(self, mode="off"):
        self.mode = mode
        self.fail_after_apply = False

    def replay_gain_status(self):
        return {"replay_gain_mode": self.mode}

    def replay_gain_mode(self, mode):
        self.mode = mode
        if self.fail_after_apply:
            self.fail_after_apply = False
            raise MPDConnectionError("reply lost")


class ReplayGainModeControllerTests(unittest.TestCase):
    def controller(self, client, errors, disconnects):
        return ReplayGainModeController(
            client, ensure_connected=lambda silent=False: True,
            mark_disconnected=lambda: disconnects.append(True),
            error=errors.append)

    def test_mode_commits_after_authoritative_readback(self):
        client, errors, disconnects = ReplayGainClient(), [], []
        result = self.controller(client, errors, disconnects).apply("track")
        self.assertTrue(result.committed)
        self.assertEqual("track", client.mode)
        self.assertEqual([], errors)

    def test_lost_reply_is_reconciled_without_false_failure(self):
        client, errors, disconnects = ReplayGainClient(), [], []
        client.fail_after_apply = True
        result = self.controller(client, errors, disconnects).apply("album")
        self.assertTrue(result.committed)
        self.assertEqual("album", client.mode)
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)


class ReplayGainPublicationTests(unittest.TestCase):
    def test_loudness_scan_starts_only_after_mode_commit(self):
        backend = type("Harness", (), {})()
        backend._rg_on_mode = "track"
        backend._replay_gain = "off"
        backend._replay_gain_generation = 1
        backend._replay_gain_busy = True
        backend._replay_gain_pending = None
        backend.saved = backend.changed = backend.scans = 0
        backend._save_conf = lambda: setattr(backend, "saved", backend.saved + 1)
        backend.settingsChanged = type("Signal", (), {
            "emit": lambda _self: setattr(backend, "changed", backend.changed + 1)})()
        backend.errorOccurred = type("Signal", (), {
            "emit": lambda _self, _message: None})()
        backend._start_rg_scan = lambda: setattr(
            backend, "scans", backend.scans + 1)

        Backend._on_replay_gain_ready(backend, {
            "generation": 1, "mode": "track", "persist": True,
            "scan": True, "result": ReplayGainModeResult(False, "off"),
        })
        self.assertEqual(("off", 0, 0, 0), (
            backend._replay_gain, backend.saved, backend.changed, backend.scans))

        backend._replay_gain_busy = True
        Backend._on_replay_gain_ready(backend, {
            "generation": 1, "mode": "track", "persist": True,
            "scan": True, "result": ReplayGainModeResult(True, "track"),
        })
        self.assertEqual(("track", 1, 1, 1), (
            backend._replay_gain, backend.saved, backend.changed, backend.scans))

    def test_latest_mode_intent_replaces_pending_request(self):
        backend = type("Harness", (), {})()
        backend._replay_gain_generation = 0
        backend._replay_gain_busy = False
        backend._replay_gain_pending = None
        launched = []

        def launch(request):
            launched.append(dict(request))
            backend._replay_gain_busy = True
            return True

        backend._start_replay_gain_request = launch

        self.assertTrue(Backend._request_replay_gain(
            backend, "track", persist=True))
        self.assertTrue(Backend._request_replay_gain(
            backend, "album", persist=True))
        self.assertTrue(Backend._request_replay_gain(
            backend, "off", persist=True))

        self.assertEqual("track", launched[0]["mode"])
        self.assertEqual("off", backend._replay_gain_pending["mode"])
        self.assertEqual(3, backend._replay_gain_pending["generation"])

    def test_mode_worker_uses_one_owned_client(self):
        backend = type("Harness", (), {})()
        backend._replay_gain_busy = False
        backend._replay_gain_pending = None
        backend._replay_gain_generation = 1
        backend._workers = object()
        emitted = []
        backend._replayGainReady = type("Signal", (), {
            "emit": lambda _self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        class Client:
            def __init__(self):
                self.mode = "off"
                self.calls = []

            def ping(self):
                self.calls.append("ping")

            def replay_gain_status(self):
                self.calls.append("read")
                return self.mode

            def replay_gain_mode(self, mode):
                self.calls.append(("write", mode))
                self.mode = mode

        client = Client()

        @contextlib.contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend._start_replay_gain_request(backend, {
                "generation": 1, "mode": "track", "persist": True,
                "scan": False,
            }))

        self.assertEqual("track", client.mode)
        self.assertTrue(emitted[0]["result"].committed)
        self.assertEqual(["ping", "read", "ping", ("write", "track"),
                          "ping", "read"], client.calls)


if __name__ == "__main__":
    unittest.main()
