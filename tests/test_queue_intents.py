import ast
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject

from ampere.mpdclient import Backend
from ampere.playback import PlaybackBooleanResult, QueuePlayResult
from ampere.queue_mutations import QueueMutationCoordinator
from ampere.remote import RemoteCommandRegistry
from ampere.sessions import SessionService


ROOT = Path(__file__).resolve().parents[1]


class QueueIntentBoundaryTests(unittest.TestCase):
    @staticmethod
    def request_backend():
        backend = Backend.__new__(Backend)
        QObject.__init__(backend)
        backend._queue_mutations = QueueMutationCoordinator()
        backend._queue_intent_generation = 0
        backend._disliked = []
        backend._pending_disliked_cleanup = []
        backend.launched = []
        backend.errors = []
        backend.errorOccurred.connect(backend.errors.append)
        backend._start_worker = lambda work, **_kwargs: (
            backend.launched.append(work) or True)
        return backend

    def test_every_file_queue_boundary_rejects_disliked_tracks(self):
        for kind, request in (
                ("play-now", {"file": "bad.flac"}),
                ("insert-next", {"file": "bad.flac"}),
                ("append", {"files": ("bad.flac",)}),
                ("replace", {"files": ("bad.flac",), "startIndex": 0}),
                ("replace-upcoming", {"files": ("bad.flac",)})):
            with self.subTest(kind=kind):
                backend = self.request_backend()
                backend._disliked = ["bad.flac"]
                completed = []

                self.assertFalse(Backend._request_queue_intent(
                    backend, kind, request, on_finished=completed.append))

                self.assertEqual([], backend.launched)
                self.assertEqual([False], completed)
                self.assertIn("Restore", backend.errors[-1])

    def test_queue_admission_filters_newly_disliked_file_from_stale_plan(self):
        backend = self.request_backend()
        backend._disliked = ["bad.flac"]

        self.assertTrue(Backend._request_queue_intent(
            backend, "replace", {
                "files": ("bad.flac", "good.flac"), "startIndex": 0,
            }))

        admission = backend.launched.pop()
        captured = []
        backend._execute_queue_intent = lambda kind, request: (
            captured.append((kind, request)) or {
                "success": True, "messages": (),
                "randomResult": None, "finalRandom": None,
            })
        admission()
        self.assertEqual(("good.flac",), captured[0][1]["files"])
        self.assertEqual(0, captured[0][1]["startIndex"])

    def test_only_parent_album_scope_can_admit_disliked_membership(self):
        backend = self.request_backend()
        backend._disliked = ["bad.flac"]

        album = Backend._admit_queue_intent(
            backend, "append", {
                "files": ("one.flac", "bad.flac", "two.flac"),
                "allowDisliked": True,
                "source": "album",
            })

        self.assertIsNotNone(album)
        self.assertEqual(
            ("one.flac", "bad.flac", "two.flac"),
            album["request"]["files"])
        self.assertNotIn("allowDisliked", album["request"])
        album["lease"].release()

        non_album = Backend._admit_queue_intent(
            backend, "append", {
                "files": ("one.flac", "bad.flac", "two.flac"),
                "allowDisliked": True,
                "source": "playlist",
            })
        self.assertIsNotNone(non_album)
        self.assertEqual(
            ("one.flac", "two.flac"),
            non_album["request"]["files"])
        non_album["lease"].release()

    def test_dislike_cleanup_waits_behind_active_queue_owner(self):
        backend = self.request_backend()
        lease, _ = backend._queue_mutations.acquire("existing")

        self.assertTrue(Backend._request_disliked_queue_cleanup(
            backend, "bad.flac"))
        self.assertEqual(["bad.flac"], backend._pending_disliked_cleanup)
        self.assertEqual([], backend.launched)

        lease.release()
        self.assertTrue(Backend._drain_disliked_queue_cleanup(backend))
        self.assertEqual([], backend._pending_disliked_cleanup)
        self.assertEqual(1, len(backend.launched))

    def test_request_admits_and_defers_all_io_to_owned_worker(self):
        backend = self.request_backend()
        calls = []
        backend._execute_queue_intent = lambda kind, request: (
            calls.append((kind, request, threading.get_ident())) or {
                "success": True, "messages": (),
                "randomResult": None, "finalRandom": None,
            })

        caller = threading.get_ident()
        self.assertTrue(Backend._request_queue_intent(
            backend, "remove", {"songIds": (4,)}))

        self.assertEqual([], calls)
        self.assertEqual(1, len(backend.launched))
        self.assertEqual("queue-intent:remove",
                         backend._queue_mutations.active_owner)

        worker = threading.Thread(target=backend.launched[0])
        worker.start()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertNotEqual(caller, calls[0][2])
        backend._queue_mutations._release(
            backend._queue_mutations.active_owner,
            backend._queue_mutations.generation)

    def test_contender_is_rejected_without_launch_or_wait(self):
        backend = self.request_backend()
        lease, _ = backend._queue_mutations.acquire("existing")
        completed = []

        self.assertFalse(Backend._request_queue_intent(
            backend, "append", {"files": ("song.flac",)},
            on_finished=completed.append))

        self.assertEqual([], backend.launched)
        self.assertEqual([False], completed)
        self.assertIn("another change", backend.errors[-1])
        lease.release()

    def test_soft_intent_reserves_lease_before_deferred_fade_action(self):
        backend = self.request_backend()
        pending = []
        backend._soft_move = pending.append

        self.assertTrue(Backend._request_soft_queue_intent(
            backend, "jump", {"songId": 8}))

        self.assertEqual("queue-intent:jump",
                         backend._queue_mutations.active_owner)
        self.assertEqual([], backend.launched)
        self.assertEqual(1, len(pending))
        self.assertFalse(Backend._request_queue_intent(
            backend, "remove", {"songIds": (9,)}))

        pending[0]()
        self.assertEqual(1, len(backend.launched))
        backend._queue_mutations._release(
            backend._queue_mutations.active_owner,
            backend._queue_mutations.generation)

    def test_worker_marks_shutdown_indeterminate_before_queued_publication(self):
        backend = self.request_backend()
        events = []
        backend._execute_queue_intent = lambda _kind, _request: {
            "success": None, "messages": ("reconciling",),
            "randomResult": None, "finalRandom": None,
        }
        backend._queueIntentReady.connect(
            lambda payload: events.append(
                ("signal", payload["completionPublished"])))
        registry = RemoteCommandRegistry(lambda command: command.admit())
        command = registry.submit("play-now", {"file": "one.flac"})

        self.assertTrue(Backend._request_queue_intent(
            backend, "play-now", {"file": "one.flac", "session": "manual"},
            on_finished=lambda result: (
                Backend._finish_remote_command(command, result, "uncertain"),
                events.append(("callback", result)))))
        backend.launched.pop()()
        registry.close()

        self.assertEqual(
            [("callback", None), ("signal", True)], events)
        self.assertEqual("indeterminate", command.snapshot()["status"])

    def test_explicit_replacement_restores_random_after_failed_commit(self):
        backend = type("WorkerBackend", (), {})()
        backend._workers = object()
        backend._random = True
        events = []

        class Playback:
            def __init__(self, *_args, **_kwargs):
                pass

            def set_random_mode(self, enabled):
                events.append(("random", enabled))
                if enabled:
                    return PlaybackBooleanResult(
                        True, True, previous=False)
                return PlaybackBooleanResult(
                    True, False, previous=True)

            def replace_queue(self, files, start):
                events.append(("replace", tuple(files), start))
                return False

        @contextmanager
        def client_scope():
            yield object()

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=client_scope()), patch(
                       "ampere.mpdclient.PlaybackController", Playback):
            result = Backend._execute_queue_intent(backend, "replace", {
                "files": ("one.flac",), "startIndex": 0,
            })

        self.assertFalse(result["success"])
        self.assertEqual([
            ("random", False),
            ("replace", ("one.flac",), 0),
            ("random", True),
        ], events)
        self.assertTrue(result["finalRandom"])

    def test_indeterminate_play_now_reconciles_before_reporting_commit(self):
        backend = type("WorkerBackend", (), {})()
        backend._workers = type("Workers", (), {
            "stop_requested": threading.Event(),
        })()
        events = []

        class Client:
            def ping(self): pass
            def connect(self, _host, _port): pass

        class Playback:
            def __init__(self, *_args, **_kwargs): pass
            def append_and_play(self, file):
                events.append(("append", file))
                return QueuePlayResult(
                    "indeterminate", target_id="9", message="reconciling")
            def reconcile_append_and_play(self, result):
                events.append(("reconcile", result.target_id))
                return QueuePlayResult("committed", target_id=result.target_id)

        @contextmanager
        def client_scope():
            yield Client()

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=client_scope()), patch(
                       "ampere.mpdclient.PlaybackController", Playback):
            result = Backend._execute_queue_intent(
                backend, "play-now", {"file": "one.flac"})

        self.assertIs(result["success"], True)
        self.assertEqual(
            [("append", "one.flac"), ("reconcile", "9")], events)

    def test_shutdown_does_not_convert_indeterminate_play_now_to_failure(self):
        backend = type("WorkerBackend", (), {})()
        stopped = threading.Event()
        stopped.set()
        backend._workers = type("Workers", (), {
            "stop_requested": stopped,
        })()

        class Client:
            def ping(self): pass
            def connect(self, _host, _port): pass

        class Playback:
            def __init__(self, *_args, **_kwargs): pass
            def append_and_play(self, _file):
                return QueuePlayResult(
                    "indeterminate", target_id="9", message="reconciling")

        @contextmanager
        def client_scope():
            yield Client()

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=client_scope()), patch(
                       "ampere.mpdclient.PlaybackController", Playback):
            result = Backend._execute_queue_intent(
                backend, "play-now", {"file": "one.flac"})

        self.assertIsNone(result["success"])
        self.assertTrue(result["playNowResult"].indeterminate)

    def test_success_publication_commits_curated_state_then_releases_lease(self):
        class Signal:
            def __init__(self):
                self.count = 0

            def emit(self, *_args):
                self.count += 1

        backend = type("PublicationBackend", (), {})()
        backend._queue_intent_generation = 1
        backend._queue_mutations = QueueMutationCoordinator()
        lease, _ = backend._queue_mutations.acquire("test")
        backend._random = True
        backend._sessions = SessionService()
        backend._mood_on = ""
        backend._sonic_on = ""
        backend._autoplay_on = False
        backend.statusChanged = Signal()
        backend.settingsChanged = Signal()
        backend.errorOccurred = Signal()
        backend._sync_session_state = lambda: Backend._sync_session_state(
            backend)
        backend._save_conf = lambda: True
        backend._invalidate_queue_refresh = lambda: None
        backend._request_queue_refresh = lambda: True
        backend.requestStatusRefresh = lambda: True
        completed = []

        result = Backend._on_queue_intent_ready(backend, {
            "generation": 1, "success": True,
            "request": {
                "session": "curated", "mood": "calm", "sonic": "",
            },
            "finalRandom": False, "lease": lease,
            "onFinished": completed.append,
        })

        self.assertTrue(result)
        self.assertEqual("mood", backend._sessions.state.kind)
        self.assertEqual("calm", backend._mood_on)
        self.assertFalse(backend._random)
        self.assertEqual([True], completed)
        self.assertEqual("", backend._queue_mutations.active_owner)

    def test_indeterminate_publication_releases_lease_without_false_callback(self):
        class Signal:
            def emit(self, *_args): pass

        backend = type("PublicationBackend", (), {})()
        backend._queue_intent_generation = 1
        backend._queue_mutations = QueueMutationCoordinator()
        lease, _ = backend._queue_mutations.acquire("test")
        backend._random = False
        backend.statusChanged = Signal()
        backend.settingsChanged = Signal()
        backend.errorOccurred = Signal()
        backend._invalidate_queue_refresh = lambda: None
        backend._request_queue_refresh = lambda: True
        backend.requestStatusRefresh = lambda: True
        completed = []

        result = Backend._on_queue_intent_ready(backend, {
            "generation": 1, "success": None,
            "request": {"session": "manual"}, "lease": lease,
            "onFinished": completed.append,
            "messages": ("still reconciling",),
        })

        self.assertIsNone(result)
        self.assertEqual([None], completed)
        self.assertEqual("", backend._queue_mutations.active_owner)

    def test_active_entry_points_have_no_direct_gui_client_mutation(self):
        source = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        active = {
            "playPosition", "removePosition", "clearQueue", "trimPlayed",
            "keepNext", "queueFiles", "playNext", "moveInQueue",
            "playFiles", "playAlbum", "_play_explicit",
            "_play_curated_session", "_queue_after_current",
            "_on_radio_ready", "_on_mix_maps", "_on_delete_done",
            "_on_dj_session_ready", "_on_dj_replay_ready",
        }
        forbidden = {
            "_write", "_write_once", "_replace_queue", "_append_files",
            "_set_random_mode", "_set_random_mode_result",
        }
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    or node.name not in active:
                continue
            for call in ast.walk(node):
                target = call.func if isinstance(call, ast.Call) else None
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in forbidden):
                    violations.append((node.name, target.attr, call.lineno))
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Attribute)
                        and isinstance(target.value.value, ast.Name)
                        and target.value.value.id == "self"
                        and target.value.attr == "_playback"):
                    violations.append((node.name, target.attr, call.lineno))
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
