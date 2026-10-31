import json
import tempfile
import threading
import unittest
from pathlib import Path

from ampere.metadata import MetadataService
from ampere.library import LibraryUpdateResult
from ampere.mpdclient import Backend


class FakeFlac(dict):
    def __init__(self, values=None, *, fail_save=False):
        super().__init__(values or {})
        self.tags = self
        self.fail_save = fail_save
        self.saves = 0

    def save(self):
        self.saves += 1
        if self.fail_save:
            raise OSError("disk full")


class MetadataServiceTests(unittest.TestCase):
    def setup(self, suffix=".flac", audio=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name) / "library"
        root.mkdir()
        path = root / f"track{suffix}"
        path.write_bytes(b"fixture")
        audio = audio or FakeFlac({"title": ["Original"], "genre": ["Rock"]})
        service = MetadataService(
            root, Path(temp.name) / "backups", flac_factory=lambda _: audio)
        return temp, service, audio, path.name

    def test_projection_exposes_only_editable_first_values(self):
        temp, service, _, file = self.setup(audio=FakeFlac({
            "title": ["First", "Alternate"], "artist": ["Artist"],
            "custom": ["untouched"]}))
        with temp:
            result = service.read(file)
            self.assertTrue(result["editable"])
            self.assertEqual(result["title"], "First")
            self.assertEqual(result["artist"], "Artist")
            self.assertNotIn("custom", result)

    def test_traversal_absolute_symlink_escape_and_nonflac_are_rejected(self):
        temp, service, _, _ = self.setup()
        with temp:
            root = Path(temp.name) / "library"
            outside = Path(temp.name) / "outside.flac"
            outside.write_bytes(b"safe")
            (root / "link.flac").symlink_to(outside)
            for file in ("../outside.flac", str(outside), "link.flac"):
                self.assertFalse(service.read(file)["editable"])
            (root / "track.mp3").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "Only FLAC"):
                service.update("track.mp3", {})

    def test_update_writes_snapshot_once_and_deletes_empty_allowed_tag(self):
        temp, service, audio, file = self.setup()
        with temp:
            first = service.update(file, {"title": " Changed ", "genre": ""})
            snapshot = json.loads(first.backup_path.read_text())
            self.assertEqual(snapshot["tags"]["title"], ["Original"])
            self.assertEqual(audio["title"], ["Changed"])
            self.assertNotIn("genre", audio)
            service.update(file, {"title": "Again"})
            self.assertEqual(json.loads(first.backup_path.read_text()), snapshot)
            self.assertEqual(audio.saves, 2)

    def test_root_level_and_nested_updates_return_narrow_scan_parent(self):
        temp, service, _, file = self.setup()
        with temp:
            self.assertEqual(service.update(file, {}).parent, "")
            root = Path(temp.name) / "library"
            (root / "Artist").mkdir()
            (root / "Artist" / "song.flac").write_bytes(b"fixture")
            self.assertEqual(service.update("Artist/song.flac", {}).parent,
                             "Artist")

    def test_failed_audio_save_still_leaves_original_recovery_snapshot(self):
        audio = FakeFlac({"title": ["Original"]}, fail_save=True)
        temp, service, _, file = self.setup(audio=audio)
        with temp:
            with self.assertRaisesRegex(OSError, "disk full"):
                service.update(file, {"title": "Changed"})
            backup = service._backup_path(file)
            self.assertEqual(json.loads(backup.read_text())["tags"]["title"],
                             ["Original"])

    def test_silent_save_mismatch_is_rejected_after_durable_readback(self):
        writer = FakeFlac({"title": ["Original"]})
        stale = FakeFlac({"title": ["Original"]})
        temp = tempfile.TemporaryDirectory()
        with temp:
            root = Path(temp.name) / "library"
            root.mkdir()
            (root / "track.flac").write_bytes(b"fixture")
            audios = iter([writer, stale])
            service = MetadataService(
                root, Path(temp.name) / "backups",
                flac_factory=lambda _path: next(audios))

            with self.assertRaisesRegex(OSError, "could not be verified"):
                service.update("track.flac", {"title": "Changed"})

            backup = service._backup_path("track.flac")
            self.assertEqual("Original",
                             json.loads(backup.read_text())["tags"]["title"][0])

    def test_two_service_instances_preserve_each_others_tag_changes(self):
        temp = tempfile.TemporaryDirectory()
        with temp:
            root = Path(temp.name) / "library"
            root.mkdir()
            path = root / "track.flac"
            path.write_bytes(b"fixture")
            stored = {"title": ["Original"], "genre": ["Rock"]}
            first_save_entered = threading.Event()
            release_first_save = threading.Event()
            second_opened = threading.Event()
            factory_calls = 0
            calls_lock = threading.Lock()

            class DiskFlac(FakeFlac):
                def save(self):
                    nonlocal factory_calls
                    if self.get("title") == ["Changed"]:
                        first_save_entered.set()
                        release_first_save.wait(timeout=2)
                    stored.clear()
                    stored.update({key: list(value)
                                   for key, value in self.items()})

            def factory(_path):
                nonlocal factory_calls
                with calls_lock:
                    factory_calls += 1
                    if factory_calls >= 2 and first_save_entered.is_set():
                        second_opened.set()
                return DiskFlac({key: list(value)
                                 for key, value in stored.items()})

            first = MetadataService(
                root, Path(temp.name) / "backups", flac_factory=factory)
            second = MetadataService(
                root, Path(temp.name) / "backups", flac_factory=factory)
            errors = []

            one = threading.Thread(
                target=lambda: self._capture_error(
                    errors, first.update, "track.flac", {"title": "Changed",
                                                          "genre": "Rock"}))
            two = threading.Thread(
                target=lambda: self._capture_error(
                    errors, second.update, "track.flac", {"title": "Changed",
                                                           "genre": "Jazz"}))
            one.start()
            self.assertTrue(first_save_entered.wait(timeout=2))
            two.start()
            self.assertFalse(second_opened.wait(timeout=0.05))
            release_first_save.set()
            one.join(timeout=2)
            two.join(timeout=2)

            self.assertEqual([], errors)
            self.assertEqual(["Changed"], stored["title"])
            self.assertEqual(["Jazz"], stored["genre"])

    @staticmethod
    def _capture_error(errors, operation, *args):
        try:
            operation(*args)
        except Exception as exc:
            errors.append(exc)


class BackendMetadataPublicationTests(unittest.TestCase):
    class Signal:
        def __init__(self):
            self.messages = []

        def emit(self, message):
            self.messages.append(message)

    class Service:
        def update(self, _file, _values):
            from ampere.metadata import MetadataUpdate
            return MetadataUpdate("Artist", Path("backup.json"))

    def backend(self, refresh):
        backend = type("Harness", (), {})()
        backend._metadata = self.Service()
        backend.errorOccurred = self.Signal()
        backend._metadata_update_busy = True
        backend.trackMetadataUpdateFinished = type("Finished", (), {
            "values": [],
            "emit": lambda self, *value: self.values.append(value),
        })()
        return backend

    def test_backend_distinguishes_saved_tags_from_failed_rescan(self):
        failed = self.backend(LibraryUpdateResult(False, confirmed=True))
        Backend._on_metadata_update_ready(failed, {
            "file": "song.flac", "success": True,
            "refresh": LibraryUpdateResult(False, confirmed=True),
        })
        self.assertIn("refresh could not start",
                      failed.errorOccurred.messages[-1])
        self.assertEqual(("song.flac", True),
                         failed.trackMetadataUpdateFinished.values[-1])

        started = self.backend(LibraryUpdateResult(True, started=True))
        Backend._on_metadata_update_ready(started, {
            "file": "song.flac", "success": True,
            "refresh": LibraryUpdateResult(True, started=True),
        })
        self.assertNotIn("refresh could not start",
                         started.errorOccurred.messages[-1])

    def test_duplicate_save_is_rejected_before_worker_start(self):
        backend = type("Harness", (), {
            "_metadata_update_busy": True,
            "errorOccurred": self.Signal(),
        })()
        self.assertFalse(Backend.updateTrackMetadata(
            backend, "song.flac", {"title": "Changed"}))
        self.assertIn("already running", backend.errorOccurred.messages[-1])

    def test_stale_metadata_read_cannot_publish(self):
        published = []
        backend = type("Harness", (), {
            "_metadata_read_generation": 2,
            "trackMetadataReady": type("Ready", (), {
                "emit": lambda _self, *value: published.append(value),
            })(),
        })()
        Backend._on_metadata_read_ready(backend, {
            "generation": 1, "file": "old.flac",
            "metadata": {"editable": True},
        })
        self.assertEqual([], published)


if __name__ == "__main__":
    unittest.main()
