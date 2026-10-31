import unittest
from contextlib import nullcontext
from unittest.mock import patch

from ampere.mpdclient import Backend


class Signal:
    def __init__(self, callback=None):
        self.messages = []
        self.callback = callback

    def emit(self, *message):
        self.messages.append(message)
        if self.callback:
            self.callback(*message)


class DoctorLifecycleTests(unittest.TestCase):
    def backend(self, launch):
        backend = type("Harness", (), {})()
        backend._doctor_busy = False
        backend._doctor = {
            "lowBitrate": [], "missingRg": [], "untagged": [],
            "outliers": [], "versionGroups": [], "scanned": 1,
            "ts": 1,
        }
        backend._doctor_verified = dict(backend._doctor)
        backend._search_index = [{"song": {"file": "track.flac"}}]
        backend._library = type("Library", (), {
            "by_file": {"track.flac": {"title": "Track", "artist": "Artist"}}
        })()
        backend._workers = object()
        backend._planning_counts = lambda cli: {}
        backend._planning_sticker_map = lambda _key, cli: {}
        backend._version_groups = lambda: {}
        backend._doctor_worker = lambda *args: Backend._doctor_worker(
            backend, *args)
        backend.doctorChanged = Signal()
        backend.errorOccurred = Signal()
        backend._doctorReady = Signal(
            lambda report: Backend._on_doctor(backend, report))
        backend._start_worker = launch
        backend._finish_doctor_failure = lambda message=(
            "Library scan failed; the last verified report was kept"
        ): Backend._finish_doctor_failure(backend, message)
        return backend

    @staticmethod
    def run_backend(backend):
        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=nullcontext(object())):
            Backend.runDoctor(backend)

    def test_launch_returns_busy_without_sticker_io_on_caller(self):
        launches = []
        backend = self.backend(
            lambda target, **kwargs: launches.append((target, kwargs)) or True)
        backend._planning_counts = lambda _cli: self.fail("read play counts")
        backend._planning_sticker_map = lambda *_args: self.fail(
            "read preferences")

        self.run_backend(backend)

        self.assertTrue(backend._doctor_busy)
        self.assertEqual("ampere-library-doctor",
                         launches[0][1]["name"])

    def test_worker_failure_restores_report_and_releases_busy_state(self):
        def launch(target, *, args, **_kwargs):
            target(*args)
            return True

        backend = self.backend(launch)
        previous = dict(backend._doctor)
        with patch("ampere.doctor.scan", side_effect=OSError("unreadable")):
            self.run_backend(backend)

        self.assertFalse(backend._doctor_busy)
        self.assertEqual(previous, backend._doctor)
        self.assertEqual(
            "Library scan failed; the last verified report was kept",
            backend.errorOccurred.messages[-1][0])

    def test_rejected_worker_launch_restores_report(self):
        backend = self.backend(lambda *_args, **_kwargs: False)
        previous = dict(backend._doctor)

        self.run_backend(backend)

        self.assertFalse(backend._doctor_busy)
        self.assertEqual(previous, backend._doctor)
        self.assertIn("could not start", backend.errorOccurred.messages[-1][0])

    def test_evidence_failure_occurs_inside_worker_and_restores_report(self):
        def launch(target, *, args, **_kwargs):
            target(*args)
            return True

        backend = self.backend(launch)
        previous = dict(backend._doctor)
        backend._planning_counts = lambda _cli: 1 / 0

        self.run_backend(backend)

        self.assertFalse(backend._doctor_busy)
        self.assertEqual(previous, backend._doctor)
        self.assertTrue(backend.errorOccurred.messages)

    def test_success_replaces_verified_report_and_releases_busy_state(self):
        def launch(target, *, args, **_kwargs):
            target(*args)
            return True

        backend = self.backend(launch)
        report = {"lowBitrate": [{"file": "track.flac", "kbps": 128}],
                  "missingRg": [], "untagged": [], "outliers": [],
                  "scanned": 1}
        with patch("ampere.doctor.scan", return_value=report):
            self.run_backend(backend)

        self.assertFalse(backend._doctor_busy)
        self.assertEqual(report["lowBitrate"], backend._doctor["lowBitrate"])
        self.assertEqual(backend._doctor, backend._doctor_verified)
        self.assertEqual([], backend.errorOccurred.messages)


class DoctorFindingIdentityTests(unittest.TestCase):
    def test_scan_findings_carry_same_file_library_identity(self):
        from ampere import doctor

        class Info:
            bitrate = 192000

        class Media(dict):
            info = Info()

        library = {
            "Artist/Record/Signal.mp3": {
                "file": "Artist/Record/Signal.mp3",
                "title": "Signal",
                "artist": "The Artist",
                "album": "The Record",
            }
        }
        with patch("mutagen.File", return_value=Media()):
            report = doctor.scan("/music", list(library), library)

        for key in ("lowBitrate", "missingRg"):
            self.assertEqual("Artist/Record/Signal.mp3",
                             report[key][0]["file"])
            self.assertEqual("Signal", report[key][0]["title"])
            self.assertEqual("The Artist", report[key][0]["artist"])
            self.assertEqual("The Record", report[key][0]["album"])


if __name__ == "__main__":
    unittest.main()
