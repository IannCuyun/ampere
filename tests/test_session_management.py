import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mpd.base import ConnectionError as MPDConnectionError

from ampere.mpdclient import Backend, LIKED_PLAYLIST
from ampere.playlists import PlaylistRepository
from ampere.playlist_service import PlaylistReadResult, PlaylistService
from ampere.library import normalize_song
from ampere.metadata import MetadataService
from ampere.playback import PlaybackBooleanResult, PlaybackController
from ampere.queue_mutations import QueueMutationCoordinator
from ampere.queue_sequencing import QueueSequencer
from ampere.sessions import SessionService


class SignalStub:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class PlaybackStub:
    def __init__(self):
        self.removals = []
        self.reorders = []

    def remove_ids(self, song_ids):
        self.removals.append(list(song_ids))
        return True

    def reorder_window(self, song_ids, start):
        self.reorders.append((list(song_ids), start))
        return True


class BackendStub:
    def __init__(self):
        self._queue_pos = 3
        self._duration = 180.0
        self._queue = [{"id": i + 10, "file": f"track-{i}"}
                       for i in range(10)]
        self._playback = PlaybackStub()
        self._queue_sequencer = QueueSequencer(
            shuffle=lambda values: values.reverse())
        self._dj_on = False
        self._queue_reorder_busy = False
        self._queue_reorder_generation = 0
        self._queue_mutations = QueueMutationCoordinator()
        self._workers = object()
        self._playlists = ["Road trip", "Focus", LIKED_PLAYLIST]
        self._playlist_repository = PlaylistRepository()
        self._playlist_repository.replace_playlists(
            [{"playlist": name} for name in self._playlists])
        self.calls = []
        self.writes = []
        self.once_writes = []
        self.refreshes = 0
        self.queue_intents = []
        self.errorOccurred = SignalStub()
        self._seek_current_once = lambda seconds: \
            Backend._seek_current_once(self, seconds)
        self._playlist_read_failed = False
        self._playlist_track_snapshots = {}
        self.playlist_rows = [{
            "file": "Rock/Artist/Album/01 Song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration": "180.5",
        }]
        self._report_playlist_read = lambda success: \
            Backend._report_playlist_read(self, success)
        self._playlist_service = PlaylistService(
            self._playlist_repository, read=self._call, write=self._write_once,
            refresh=self._refresh_playlists,
            save_files=lambda _name, _files: True,
            filter_allowed=self._playlist_repository.filter_allowed,
            normalize_song=normalize_song)

    def _request_queue_intent(self, kind, request=None, *, on_finished=None):
        self.queue_intents.append((kind, dict(request or {}), on_finished))
        return True

    def _request_soft_queue_intent(
            self, kind, request=None, *, on_finished=None):
        return self._request_queue_intent(
            kind, request, on_finished=on_finished)

    def _call(self, name, *args, default=None):
        self.calls.append((name, args))
        if name == "listplaylistinfo":
            return self.playlist_rows
        return default

    def _write(self, name, *args, **kwargs):
        self.writes.append((name, args))
        return True

    def _write_once(self, name, *args, **kwargs):
        self.once_writes.append((name, args))
        return True

    def _set_random_mode(self, enabled):
        return self._write("random", 1 if enabled else 0)

    def _set_random_mode_result(self, enabled):
        committed = self._set_random_mode(enabled)
        return PlaybackBooleanResult(
            committed, bool(enabled), previous=True)

    def _restore_ordered_random(self, result):
        return self._set_random_mode(result.previous)

    def _refresh_playlists(self):
        self.refreshes += 1
        return True

    def refreshQueue(self):
        self.refreshes += 1


class SessionQueueTests(unittest.TestCase):
    def test_ordered_play_defers_random_and_replacement_to_queue_intent(self):
        backend = type("OrderedBackend", (), {})()
        backend._drop_disliked = lambda files, keep="": list(files)
        backend._explicit_queue_request = lambda *args, **kwargs: (
            Backend._explicit_queue_request(backend, *args, **kwargs))
        backend._play_explicit = lambda files, index, *, keep_disliked: (
            Backend._play_explicit(
                backend, files, index, keep_disliked=keep_disliked))
        backend._set_random_mode_result = lambda _enabled: self.fail(
            "Qt caller must not touch MPD random mode")
        intents = []
        backend._reapply_context_shuffle = lambda success: True
        backend._request_soft_queue_intent = lambda kind, request, **kwargs: (
            intents.append((kind, request)) or True)

        self.assertTrue(Backend.playFiles(backend, ["new.flac"], 0))
        self.assertEqual("replace", intents[0][0])
        self.assertEqual(("new.flac",), intents[0][1]["files"])
        self.assertEqual("manual", intents[0][1]["session"])

    def test_play_album_keeps_disliked_membership_in_parent_album_scope(self):
        backend = type("AlbumBackend", (), {})()
        backend._drop_disliked = lambda files, keep="": [
            file for file in files if file != "bad.flac"]
        backend._explicit_queue_request = lambda *args, **kwargs: (
            Backend._explicit_queue_request(backend, *args, **kwargs))
        backend._play_explicit = lambda files, index, *, keep_disliked: (
            Backend._play_explicit(
                backend, files, index, keep_disliked=keep_disliked))
        intents = []
        backend._reapply_context_shuffle = lambda success: True
        backend._request_soft_queue_intent = lambda kind, request, **kwargs: (
            intents.append((kind, request)) or True)

        self.assertTrue(Backend.playAlbum(
            backend, ["one.flac", "bad.flac", "two.flac"], 1))

        self.assertEqual(
            ("one.flac", "bad.flac", "two.flac"),
            intents[0][1]["files"])
        self.assertEqual(1, intents[0][1]["startIndex"])
        self.assertEqual("album", intents[0][1]["source"])
        self.assertTrue(intents[0][1]["allowDisliked"])

    def test_empty_ordered_play_never_schedules_queue_intent(self):
        backend = type("OrderedBackend", (), {})()
        backend._drop_disliked = lambda _files, keep="": []
        backend._explicit_queue_request = lambda *args, **kwargs: (
            Backend._explicit_queue_request(backend, *args, **kwargs))
        backend._play_explicit = lambda files, index, *, keep_disliked: (
            Backend._play_explicit(
                backend, files, index, keep_disliked=keep_disliked))
        backend._soft_move = lambda _action: self.fail("scheduled empty play")
        errors = []
        backend.errorOccurred = type("Signal", (), {
            "emit": staticmethod(errors.append)})()

        self.assertFalse(Backend.playFiles(backend, ["new.flac"], 0))
        self.assertEqual(
            ["Nothing playable here — every track is out of rotation"], errors)

    def test_explicit_play_skips_members_missing_from_verified_library(self):
        backend = type("OrderedBackend", (), {})()
        backend._library = type("Library", (), {
            "generation": 4,
            "by_file": {"one.flac": {}, "three.flac": {}},
        })()
        backend._drop_disliked = lambda files, keep="": list(files)
        backend._explicit_queue_request = lambda *args, **kwargs: (
            Backend._explicit_queue_request(backend, *args, **kwargs))
        intents = []
        backend._reapply_context_shuffle = lambda success: True
        backend._request_soft_queue_intent = lambda kind, request, **kwargs: (
            intents.append((kind, request)) or True)

        self.assertTrue(Backend._play_explicit(
            backend, ["one.flac", "gone.flac", "three.flac"], 1,
            keep_disliked=False))

        self.assertEqual(
            ("one.flac", "three.flac"), intents[0][1]["files"])
        self.assertEqual(0, intents[0][1]["startIndex"])

    def test_curated_start_reports_async_queue_failure_without_state_commit(self):
        backend = type("CuratedBackend", (), {})()
        backend._drop_disliked = lambda files, keep="": list(files)
        backend._explicit_queue_request = lambda *args, **kwargs: (
            Backend._explicit_queue_request(backend, *args, **kwargs))
        backend._soft_move = lambda action: action()
        backend._request_soft_queue_intent = lambda _kind, _request, \
                on_finished=None: (on_finished(False) or True)
        completed = []

        result = Backend._play_curated_session(
            backend, ["new.flac"], mood="calm",
            on_finished=completed.append)

        self.assertTrue(result)
        self.assertEqual([False], completed)

    def test_stopped_radio_plans_before_changing_prior_session(self):
        backend = type("Harness", (), {})()
        backend._state = "stop"
        backend._song = {"file": "current.flac"}
        backend._sessions = SessionService()
        backend._sessions.commit_curated(mood="calm")
        backend._mood_on = "calm"
        backend._sonic_on = ""
        backend._autoplay_on = True
        backend.errorOccurred = SignalStub()
        backend._last_played_song = lambda: {}
        backend._radio_picks = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("planning failed"))
        backend._end_mood_session = lambda: self.fail(
            "prior session must survive failed stopped-state planning")
        backend.setAutoplayOn = lambda _on: self.fail(
            "Autoplay must not publish before a queue commits")

        Backend.startRadio(backend)

        self.assertEqual("mood", backend._sessions.state.kind)
        self.assertIn("queue was not changed",
                      backend.errorOccurred.messages[0])

    def test_stopped_radio_delegates_random_gating_to_curated_boundary(self):
        backend = type("Harness", (), {})()
        backend._state = "stop"
        backend._song = {"file": "current.flac"}
        backend.errorOccurred = SignalStub()
        backend._last_played_song = lambda: {}
        backend._radio_picks = lambda *_args, **_kwargs: ["next.flac"]
        started = []
        backend._play_curated_session = lambda files: (
            started.append(files) or False)

        Backend.startRadio(backend)

        self.assertEqual([["next.flac"]], started)

    def test_stopped_radio_delegates_transactional_session_commit(self):
        backend = type("Harness", (), {})()
        backend._state = "stop"
        backend._song = {"file": "current.flac"}
        backend.errorOccurred = SignalStub()
        backend._last_played_song = lambda: {}
        backend._radio_picks = lambda *_args, **kwargs: (
            ["next.flac"] if kwargs.get("plain") else self.fail(
                "cold start must ignore prior curated-session routing"))
        backend._set_random_mode = lambda enabled: not enabled
        started = []
        backend._play_curated_session = lambda files: started.append(files)

        Backend.startRadio(backend)

        self.assertEqual([["next.flac"]], started)

    def test_last_played_seed_and_plain_radio_use_cached_evidence(self):
        backend = type("Harness", (), {})()
        backend._library_planning_ready = True
        backend._library_last_played = {
            "Rock/Artist/old.flac": "100",
            "Rock/Artist/new.flac": "200",
        }
        backend._library = type("Library", (), {"by_file": {
            "Rock/Artist/old.flac": {"file": "Rock/Artist/old.flac"},
            "Rock/Artist/new.flac": {"file": "Rock/Artist/new.flac"},
        }})()
        backend._sticker_map = lambda *_args: self.fail("scanned lastPlayed")

        self.assertEqual(
            "Rock/Artist/new.flac",
            Backend._last_played_song(backend)["file"])

    def test_plain_radio_cached_mode_never_reads_listening_stickers(self):
        backend = type("Harness", (), {})()
        backend._sonic_on = ""
        backend._mood_on = ""
        backend._radio_mood = "match"
        backend._library_planning_ready = True
        backend._library_playcounts = {"Rock/A/next.flac": 2}
        backend._library_planning_ratings = {"Rock/A/next.flac": "6"}
        backend._library_last_played = {"Rock/A/next.flac": "100"}
        backend._library_energies = {"Rock/A/next.flac": .6}
        backend._library_bpms = {}
        backend._cached_listening_evidence = lambda: \
            Backend._cached_listening_evidence(backend)
        backend._library = type("Library", (), {"songs": [
            {"file": "Rock/A/current.flac", "artist": "A"},
            {"file": "Rock/A/next.flac", "artist": "B"},
        ]})()
        backend._song = {"file": "Rock/A/current.flac", "artist": "A"}
        backend._queue = []
        backend._liked = []
        backend._disliked = []
        backend._planning_counts = lambda *_args: self.fail("scanned counts")
        backend._planning_sticker_map = lambda *_args: self.fail(
            "scanned stickers")
        backend._planning_energies = lambda *_args: self.fail(
            "scanned energy")
        backend._sessions = SessionService()
        backend._gapless_extend = lambda files, cli=None: list(files)

        result = Backend._radio_picks(
            backend, count=5, plain=True, cached=True)

        self.assertEqual(["Rock/A/next.flac"], result)

    def test_seek_dispatches_once_with_a_bounded_position(self):
        backend = BackendStub()

        Backend.seek(backend, 999.96)

        self.assertEqual(backend.once_writes, [("seekcur", (180.0,))])
        self.assertEqual([], backend.calls)

    def test_seek_rejects_non_finite_positions_without_dispatch(self):
        backend = BackendStub()

        self.assertFalse(Backend._seek_current_once(backend, float("nan")))
        self.assertFalse(Backend._seek_current_once(backend, float("inf")))

        self.assertEqual([], backend.once_writes)

    def test_resume_seek_uses_the_same_at_most_once_boundary(self):
        backend = BackendStub()

        self.assertTrue(Backend._seek_current_once(backend, 74.26))

        self.assertEqual(backend.once_writes, [("seekcur", (74.3,))])
        self.assertEqual([], backend.calls)

    def test_trim_played_preserves_the_current_song(self):
        backend = BackendStub()
        Backend.trimPlayed(backend)
        self.assertEqual(
            ("remove", {
                "songIds": (10, 11, 12), "manualQueueEdit": True,
            }),
            backend.queue_intents[0][:2])

    def test_keep_next_caps_only_the_future(self):
        backend = BackendStub()
        Backend.keepNext(backend, 2)
        self.assertEqual(
            ("remove", {
                "songIds": (16, 17, 18, 19), "manualQueueEdit": True,
            }),
            backend.queue_intents[0][:2])

    def test_remove_position_targets_the_captured_song_id(self):
        backend = BackendStub()

        Backend.removePosition(backend, 4)

        self.assertEqual(
            ("remove", {
                "songIds": (14,), "manualQueueEdit": True,
            }),
            backend.queue_intents[0][:2])

    def test_move_queue_reconciles_the_full_stable_id_order(self):
        backend = BackendStub()

        Backend.moveInQueue(backend, 2, 6)

        self.assertEqual("reorder", backend.queue_intents[0][0])
        self.assertEqual(
            (10, 11, 13, 14, 15, 16, 12, 17, 18, 19),
            backend.queue_intents[0][1]["songIds"])

    def test_play_position_uses_stable_id_at_most_once(self):
        backend = BackendStub()
        backend._soft_move = lambda action: action()

        Backend.playPosition(backend, 5)

        self.assertEqual(
            ("jump", {"songId": 15}), backend.queue_intents[0][:2])

    def test_reshuffle_reorders_only_upcoming_stable_ids(self):
        backend = BackendStub()
        backend._queueReorderReady = type("QueuedSignal", (), {
            "emit": lambda _signal, payload:
                Backend._on_queue_reorder_ready(backend, payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        client_scope = unittest.mock.MagicMock()
        client_scope.__enter__.return_value = object()
        client_scope.__exit__.return_value = False

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=client_scope), \
                patch("ampere.mpdclient.PlaybackController",
                      return_value=backend._playback):
            self.assertTrue(Backend.reshuffleQueue(backend))

        self.assertEqual(backend._playback.reorders, [
            (["19", "18", "17", "16", "15", "14"], 4)])
        self.assertEqual(backend.writes, [("random", (0,))])
        self.assertEqual(1, backend.refreshes)
        self.assertFalse(backend._queue_reorder_busy)
        self.assertEqual("", backend._queue_mutations.active_owner)

    def test_interactive_reshuffle_defers_random_and_reorder_io_to_worker(self):
        backend = BackendStub()
        launched = []
        backend._start_worker = lambda work, **_kwargs: (
            launched.append(work) or True)
        backend._set_random_mode_result = lambda _enabled: self.fail(
            "Qt caller must not perform the random-mode transaction")

        self.assertTrue(Backend.requestReshuffleQueue(backend))

        self.assertEqual(1, len(launched))
        self.assertEqual([], backend.writes)
        self.assertTrue(backend._queue_reorder_busy)

    def test_reshuffle_rejects_active_dj_session_without_mutation(self):
        backend = BackendStub()
        backend._dj_on = True

        self.assertFalse(Backend.reshuffleQueue(backend))

        self.assertEqual([], backend._playback.reorders)
        self.assertIn("End the DJ set", backend.errorOccurred.messages[-1])

    def test_reshuffle_does_not_mutate_queue_if_random_off_is_unverified(self):
        backend = BackendStub()
        backend._set_random_mode_result = lambda _enabled: (
            PlaybackBooleanResult(False, True, previous=True))

        self.assertFalse(Backend.reshuffleQueue(backend))

        self.assertEqual([], backend._playback.reorders)
        self.assertEqual(0, backend.refreshes)

    def test_repeat_one_cycles_to_off_without_changing_autoplay(self):
        class LoopBackend:
            _autoplay_on = True
            _repeat = True
            _single = True

            def setLoopStatus(self, mode):
                self.mode = mode
                return True

        backend = LoopBackend()
        Backend.cycleRepeat(backend)
        self.assertEqual("None", backend.mode)
        self.assertTrue(backend._autoplay_on)

    def test_autoplay_toggle_persists_without_mutating_session_state(self):
        backend = type("Harness", (), {})()
        backend._autoplay_on = False
        backend._autoplay_generation = 4
        backend._radio_retry_at = 30.0
        backend._sessions = SessionService()
        backend._sessions.commit_curated(mood="calm")
        saves = []
        signals = []
        refills = []
        backend._save_conf = lambda: saves.append(True)
        backend.settingsChanged = type("Signal", (), {
            "emit": staticmethod(lambda: signals.append(True))})()
        backend._maybe_radio_refill = lambda: refills.append(True)

        Backend.setAutoplayOn(backend, True)

        self.assertTrue(backend._autoplay_on)
        self.assertEqual(5, backend._autoplay_generation)
        self.assertEqual(0.0, backend._radio_retry_at)
        self.assertEqual("mood", backend._sessions.state.kind)
        self.assertEqual([True], saves)
        self.assertEqual([True], signals)
        self.assertEqual([True], refills)


class PlaylistManagementTests(unittest.TestCase):
    def test_playlist_controls_route_all_membership_reads_off_thread(self):
        backend = type("Harness", (), {})()
        backend.actions = []
        backend._request_playlist_action = lambda action, name: \
            backend.actions.append((action, name)) or True

        self.assertTrue(Backend.loadPlaylist(backend, "Focus", True))
        self.assertTrue(Backend.loadPlaylist(backend, "Focus", False))
        self.assertTrue(Backend.shufflePlaylist(backend, "Focus"))
        self.assertTrue(Backend.shufflePlaylistNow(backend, "Focus"))

        self.assertEqual([
            ("play", "Focus"), ("queue", "Focus"),
            ("shuffle", "Focus"), ("shuffle-now", "Focus"),
        ], backend.actions)

    def test_playlist_action_worker_uses_owned_client(self):
        backend = type("Harness", (), {})()
        backend._playlist_action_busy = False
        backend._playlist_action_pending = None
        backend._playlist_action_generation = 0
        backend._workers = object()
        emitted = []
        backend._playlistActionReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        client = type("Client", (), {
            "listplaylistinfo": lambda self, name: [
                {"file": f"{name}/one.flac"}],
        })()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=Scope()):
            self.assertTrue(Backend._request_playlist_action(
                backend, "play", "Focus"))

        self.assertTrue(emitted[0]["result"].success)
        self.assertEqual(("Focus/one.flac",), emitted[0]["result"].files)

    def test_superseded_playlist_result_launches_latest_only(self):
        backend = type("Harness", (), {})()
        backend._playlist_action_busy = True
        backend._playlist_action_pending = None
        backend._playlist_action_generation = 7
        self.assertTrue(Backend._request_playlist_action(
            backend, "queue", "Latest"))
        launched = []
        backend._request_playlist_action = lambda *request: \
            launched.append(request) or True
        backend._launch_pending_playlist_action = lambda: \
            Backend._launch_pending_playlist_action(backend)
        backend._apply_playlist_action = lambda *_args: self.fail(
            "superseded playlist must not mutate playback")

        Backend._on_playlist_action_ready(backend, {
            "generation": 7, "action": "play", "name": "Old",
            "result": PlaylistReadResult(True, ("Old/one.flac",)),
        })

        self.assertEqual([("queue", "Latest")], launched)

    def test_unavailable_playlist_result_never_reaches_mutation(self):
        backend = type("Harness", (), {})()
        backend._playlist_action_generation = 2
        backend._playlist_action_busy = True
        backend._playlist_action_pending = None
        backend._launch_pending_playlist_action = lambda: False
        reported = []
        backend._report_playlist_read = lambda success: reported.append(success)
        backend._apply_playlist_action = lambda *_args: self.fail(
            "unverified playlist must not mutate playback")

        Backend._on_playlist_action_ready(backend, {
            "generation": 2, "action": "play", "name": "Focus",
            "result": PlaylistReadResult(False),
        })

        self.assertEqual([False], reported)

    def test_verified_playlist_result_applies_only_after_publication(self):
        backend = type("Harness", (), {})()
        backend._playlist_action_generation = 5
        backend._playlist_action_busy = True
        backend._playlist_action_pending = None
        backend._launch_pending_playlist_action = lambda: False
        events = []
        backend._report_playlist_read = lambda success: \
            events.append(("reported", success))
        backend._apply_playlist_action = lambda action, name, files: \
            events.append((action, name, list(files))) or True

        Backend._on_playlist_action_ready(backend, {
            "generation": 5, "action": "queue", "name": "Focus",
            "result": PlaylistReadResult(
                True, ("Focus/one.flac", "Focus/two.flac")),
        })

        self.assertEqual([
            ("reported", True),
            ("queue", "Focus", ["Focus/one.flac", "Focus/two.flac"]),
        ], events)

    def test_playlist_action_preserves_empty_and_disliked_outcomes(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, message):
                self.messages.append(message)

        backend = type("Harness", (), {})()
        backend.errorOccurred = Signal()
        backend._drop_disliked = lambda files: [
            file for file in files if file != "bad.flac"]

        self.assertFalse(Backend._apply_playlist_action(
            backend, "play", "Focus", []))
        self.assertFalse(Backend._apply_playlist_action(
            backend, "play", "Focus", ["bad.flac"]))

        self.assertEqual(
            ["Playlist is empty", "Everything in there is disliked"],
            backend.errorOccurred.messages)

    def test_playlist_launch_count_persists_only_confirmed_play(self):
        class UsageSignal:
            def __init__(self):
                self.count = 0

            def emit(self):
                self.count += 1

        with TemporaryDirectory() as tmp:
            from ampere.settings import SettingsRepository

            backend = type("Harness", (), {})()
            backend._settings = SettingsRepository(Path(tmp, "config.json"))
            backend._settings.load()
            backend._playlist_play_counts = {}
            backend.playlistUsageChanged = UsageSignal()
            backend.errorOccurred = SignalStub()
            backend._settings_save_failed = False
            backend._settings_save_failure_message = ""
            backend._drop_disliked = lambda files: list(files)
            backend._request_queue_intent = lambda *_args, **_kwargs: True

            self.assertFalse(Backend._finish_playlist_launch(
                backend, "Focus", False))
            self.assertEqual({}, backend._playlist_play_counts)
            self.assertTrue(Backend._apply_playlist_action(
                backend, "queue", "Focus", ["Focus/one.flac"]))
            self.assertEqual({}, backend._playlist_play_counts)

            self.assertTrue(Backend._finish_playlist_launch(
                backend, "Focus", True))
            self.assertEqual({"Focus": 1}, backend._playlist_play_counts)
            self.assertEqual(1, backend.playlistUsageChanged.count)
            self.assertEqual(
                {"Focus": 1},
                backend._settings.load()["playlist_play_counts"])

    def test_playlist_tracks_return_cache_and_launch_without_gui_client_io(self):
        backend = type("Harness", (), {})()
        backend._playlist_track_snapshots = {
            "Road trip": [{"file": "cached.flac", "title": "Cached"}],
        }
        backend._playlist_track_generation = 0
        backend._playlist_track_request = None
        backend._workers = object()
        emitted = []
        backend._playlistTracksReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        launched = []
        backend._start_worker = lambda work, **_kwargs: (
            launched.append(work) or True)
        rows = Backend.playlistTracks(backend, "Road trip")

        self.assertEqual("cached.flac", rows[0]["file"])
        self.assertEqual((1, "Road trip"), backend._playlist_track_request)
        self.assertEqual(1, len(launched))
        self.assertEqual([], emitted)

    def test_playlist_track_worker_uses_owned_client(self):
        backend = type("Harness", (), {})()
        backend._playlist_track_snapshots = {}
        backend._playlist_track_generation = 0
        backend._playlist_track_request = None
        backend._workers = object()
        emitted = []
        backend._playlistTracksReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        calls = []
        client = type("Client", (), {
            "listplaylistinfo": lambda self, name: (
                calls.append(name) or [{
                    "file": "Rock/Artist/song.flac", "title": "Song",
                }]),
        })()

        class Scope:
            def __enter__(self):
                return client

            def __exit__(self, *_args):
                return False

        with patch("ampere.mpdclient.temporary_mpd_client",
                   return_value=Scope()):
            rows = Backend.playlistTracks(backend, "Road trip")

        self.assertEqual([], rows)
        self.assertEqual(["Road trip"], calls)
        self.assertTrue(emitted[0]["result"].success)
        self.assertEqual(0, emitted[0]["result"].tracks[0]["playlistPos"])

    def test_playlist_track_publication_is_positioned_and_retained_on_failure(self):
        class Signal:
            def __init__(self):
                self.messages = []

            def emit(self, *args):
                self.messages.append(args)

        backend = type("Harness", (), {})()
        backend._playlist_track_request = (1, "Road trip")
        backend._playlist_track_snapshots = {}
        backend._playlist_read_failed = False
        backend.errorOccurred = Signal()
        backend.playlistTracksReady = Signal()
        backend._report_playlist_read = lambda success: \
            Backend._report_playlist_read(backend, success)
        result = PlaylistReadResult(True, ("song.flac",), ({
            "file": "song.flac", "title": "Song", "playlistPos": 0,
        },))

        Backend._on_playlist_tracks_ready(backend, {
            "generation": 1, "name": "Road trip", "result": result,
        })

        self.assertEqual(0, backend._playlist_track_snapshots[
            "Road trip"][0]["playlistPos"])
        self.assertEqual(("Road trip", [{
            "file": "song.flac", "title": "Song", "playlistPos": 0,
        }], True), backend.playlistTracksReady.messages[-1])

        backend._playlist_track_request = (2, "Road trip")
        Backend._on_playlist_tracks_ready(backend, {
            "generation": 2, "name": "Road trip", "result": None,
        })
        self.assertEqual("song.flac", backend.playlistTracksReady.messages[-1][1][0]["file"])
        self.assertFalse(backend.playlistTracksReady.messages[-1][2])
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_stale_playlist_track_result_cannot_replace_newer_selection(self):
        backend = type("Harness", (), {})()
        backend._playlist_track_request = (2, "Focus")
        backend._playlist_track_snapshots = {"Focus": []}
        backend.playlistTracksReady = type("Signal", (), {
            "emit": lambda *_args: self.fail("stale result was published"),
        })()

        Backend._on_playlist_tracks_ready(backend, {
            "generation": 1, "name": "Road trip",
            "result": PlaylistReadResult(True, (), ()),
        })

        self.assertEqual((2, "Focus"), backend._playlist_track_request)

class ClearQueueTests(unittest.TestCase):
    def test_backend_captures_stable_ids_for_async_clear(self):
        backend = type("BackendHarness", (), {})()
        backend._queue = [{"id": 10}, {"id": 12}]
        intents = []
        backend._request_queue_intent = lambda kind, request: (
            intents.append((kind, request)) or True)

        self.assertTrue(Backend.clearQueue(backend))

        self.assertEqual(
            [("remove", {
                "songIds": (10, 12), "manualQueueEdit": True,
            })], intents)


class MetadataSafetyTests(unittest.TestCase):
    def test_editor_rejects_files_outside_the_library(self):
        with TemporaryDirectory() as tmp:
            service = MetadataService(tmp, Path(tmp) / "backups")
            result = service.read("../outside.flac")
        self.assertFalse(result["editable"])

    def test_writer_rejects_unsupported_formats_before_touching_tags(self):
        with TemporaryDirectory() as tmp:
            Path(tmp, "song.mp3").write_bytes(b"not audio")
            service = MetadataService(tmp, Path(tmp) / "backups")
            with self.assertRaisesRegex(ValueError, "Only FLAC"):
                service.update("song.mp3", {"title": "Changed"})

    def test_delete_worker_rejects_paths_outside_library(self):
        class DeleteBackend:
            _delete_remote_host = ""
            _delete_remote_root = ""

            def __init__(self):
                self.result = None
                self._deleteDone = type(
                    "Signal", (), {"emit": lambda inner, deleted, failed:
                    setattr(self, "result", (deleted, failed))})()

        backend = DeleteBackend()
        with TemporaryDirectory() as tmp:
            outside = Path(tmp).parent / "must-not-delete.flac"
            outside.write_bytes(b"safe")
            try:
                with patch("ampere.mpdclient.MUSIC_ROOT", tmp):
                    Backend._delete_worker(
                        backend, ["../must-not-delete.flac", str(outside)])
                self.assertTrue(outside.exists())
                self.assertEqual(backend.result[0], [])
                self.assertEqual(len(backend.result[1]), 2)
            finally:
                outside.unlink(missing_ok=True)


class QueueClient:
    def __init__(self, fail_first=False):
        self.fail_first = fail_first
        self.transactions = []
        self.current = []
        self.played = []
        self.disconnected = 0
        self.queue = []
        self.next_id = 1

    def playlistinfo(self):
        return [dict(item) for item in self.queue]

    def command_list_ok_begin(self):
        if self.fail_first:
            self.fail_first = False
            raise MPDConnectionError("Not connected")
        self.current = []

    def clear(self):
        self.current = []

    def add(self, file):
        self.current.append(file)
        self.queue.append({"id": str(self.next_id), "file": str(file)})
        self.next_id += 1

    def deleteid(self, song_id):
        self.queue = [item for item in self.queue
                      if item["id"] != str(song_id)]

    def command_list_end(self):
        self.transactions.append(list(self.current))

    def playid(self, song_id):
        self.played.append(str(song_id))

    def disconnect(self):
        self.disconnected += 1


class QueueReconnectTests(unittest.TestCase):
    @staticmethod
    def _publication_backend():
        class CountSignal:
            def __init__(self):
                self.count = 0
                self.messages = []

            def emit(self, *args):
                self.count += 1
                self.messages.append(args)

        backend = type("PublicationBackend", (), {})()
        backend._queue_intent_generation = 1
        backend._queue_mutations = QueueMutationCoordinator()
        backend._random = False
        backend._sessions = SessionService(radio_enabled=True)
        backend._mood_on = ""
        backend._sonic_on = ""
        backend._autoplay_on = True
        backend.statusChanged = CountSignal()
        backend.settingsChanged = CountSignal()
        backend.errorOccurred = CountSignal()
        backend._end_mood_session = lambda: Backend._end_mood_session(backend)
        backend._sync_session_state = lambda: Backend._sync_session_state(
            backend)
        backend._save_conf = lambda: True
        backend._invalidate_queue_refresh = lambda: None
        backend._request_queue_refresh = lambda: True
        backend.requestStatusRefresh = lambda: True
        return backend

    def test_replace_queue_recovers_silently_from_stale_client(self):
        backend = BackendStub()
        backend._cmd = QueueClient(fail_first=True)
        backend._connected = True
        ensure_calls = []

        def ensure(silent=False):
            ensure_calls.append(silent)
            backend._connected = True
            return True

        backend._ensure_connected = ensure
        backend._playback = PlaybackController(
            backend._cmd, ensure_connected=ensure,
            mark_disconnected=lambda: setattr(backend, "_connected", False),
            error=backend.errorOccurred.emit)

        self.assertTrue(Backend._replace_queue(
            backend, ["one.flac", "two.flac"], 1))
        self.assertEqual([item["file"] for item in backend._cmd.queue],
                         ["one.flac", "two.flac"])
        self.assertEqual(backend._cmd.played, ["2"])
        self.assertGreaterEqual(len(ensure_calls), 2)
        self.assertEqual(backend.errorOccurred.messages, [])

    def test_curated_session_captures_commit_context_for_soft_intent(self):
        class CuratedBackend:
            def __init__(self):
                self.intent = None

            def _drop_disliked(self, files, keep=""):
                return list(files)

            def _explicit_queue_request(self, *args, **kwargs):
                return Backend._explicit_queue_request(self, *args, **kwargs)

            def _request_soft_queue_intent(
                    self, kind, request, *, on_finished=None):
                self.intent = (kind, request, on_finished)
                return True

        backend = CuratedBackend()
        completed = []
        Backend._play_curated_session(
            backend, ["song.flac"], mood="calm",
            on_finished=completed.append)

        self.assertEqual("replace", backend.intent[0])
        self.assertEqual("curated", backend.intent[1]["session"])
        self.assertEqual("calm", backend.intent[1]["mood"])
        self.assertEqual([], completed)

    def test_failed_delayed_curated_queue_reports_failure_without_commit(self):
        backend = self._publication_backend()
        backend._sessions.commit_curated(mood="calm")
        completed = []
        lease, _ = backend._queue_mutations.acquire("test")

        Backend._on_queue_intent_ready(backend, {
            "generation": 1, "success": False,
            "request": {"session": "curated", "sonic": "profile"},
            "messages": ("replacement failed",), "lease": lease,
            "onFinished": completed.append,
        })

        self.assertEqual([False], completed)
        self.assertEqual("mood", backend._sessions.state.kind)
        self.assertEqual(0, backend.settingsChanged.count)

    def test_failed_manual_queue_replacement_preserves_curated_session(self):
        backend = self._publication_backend()
        backend._sessions.commit_curated(mood="calm")
        lease, _ = backend._queue_mutations.acquire("test")

        result = Backend._on_queue_intent_ready(backend, {
            "generation": 1, "success": False,
            "request": {"session": "manual"},
            "messages": ("replacement failed",), "lease": lease,
        })

        self.assertFalse(result)
        self.assertEqual("mood", backend._sessions.state.kind)

    def test_successful_manual_queue_replacement_ends_curated_session(self):
        backend = self._publication_backend()
        backend._sessions.commit_curated(mood="calm")
        lease, _ = backend._queue_mutations.acquire("test")

        result = Backend._on_queue_intent_ready(backend, {
            "generation": 1, "success": True,
            "request": {"session": "manual"}, "lease": lease,
        })

        self.assertTrue(result)
        self.assertEqual("radio", backend._sessions.state.kind)

    def test_failed_upcoming_replacement_preserves_curated_session(self):
        backend = type("UpcomingBackend", (), {})()
        backend._queue_pos = 0
        backend._queue = [{"id": 9, "file": "current.flac"}]
        backend._state = "pause"
        backend._drop_disliked = lambda files: list(files)
        intents = []
        backend._request_queue_intent = lambda kind, request: (
            intents.append((kind, request)) or False)

        result = Backend._queue_after_current(backend, ["next.flac"])

        self.assertFalse(result)
        self.assertEqual("replace-upcoming", intents[0][0])
        self.assertEqual(9, intents[0][1]["currentId"])

    def test_successful_upcoming_replacement_ends_curated_session(self):
        backend = type("UpcomingBackend", (), {})()
        backend._queue_pos = 0
        backend._queue = [{"id": 9, "file": "current.flac"}]
        backend._state = "play"
        backend._drop_disliked = lambda files: list(files)
        intents = []
        backend._request_queue_intent = lambda kind, request: (
            intents.append((kind, request)) or True)

        result = Backend._queue_after_current(backend, ["next.flac"])

        self.assertTrue(result)
        self.assertEqual("manual", intents[0][1]["session"])

if __name__ == "__main__":
    unittest.main()
