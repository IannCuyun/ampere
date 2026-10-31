"""Pre-Radio recovery, verified worker transactions, and cancellation boundaries."""
import copy
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject
from mpd.base import CommandError

from ampere.beacon_controller import BeaconController, RadioRecovery
from ampere.mpdclient import Backend
from ampere.playback import PlaybackController
from ampere.queue_mutations import QueueMutationCoordinator
from test_playback import QueueClient


class RestoreClient(QueueClient):
    def __init__(self, files=(), index=0, state='pause', elapsed=34.5):
        super().__init__(files)
        self.state = state
        self.elapsed = elapsed
        self.random_mode = False
        self.fail_seek_once = False
        self.fail_capture = False
        if self.queue:
            self.played = [self.queue[index]['id']]

    def status(self):
        if self.fail_capture:
            raise CommandError('status failed')
        value = super().status()
        value.update(state=self.state, elapsed=str(self.elapsed),
                     random=str(int(self.random_mode)), repeat='0', single='0',
                     playlist=str(self.next_id + len(self.queue)), playlistlength=str(len(self.queue)))
        return value

    def playid(self, identity):
        super().playid(identity)
        self.state = 'play'
        self.elapsed = 0

    def seekid(self, identity, elapsed):
        if self.fail_seek_once:
            self.fail_seek_once = False
            raise CommandError('seek rejected')
        self.elapsed = float(elapsed)

    def pause(self, value):
        self.state = 'pause' if value else 'play'

    def stop(self):
        super().stop()
        self.state = 'stop'
        self.elapsed = 0

    def random(self, enabled):
        self.random_mode = bool(enabled)

    def ping(self):
        pass

    def currentsong(self):
        return next((r for r in self.queue if self.played and r['id'] == self.played[-1]), {})


class RadioRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'recovery.json'
        self.errors = []

    def playback(self, client):
        return PlaybackController(client, ensure_connected=lambda **_: True,
                                  mark_disconnected=lambda: None, error=self.errors.append)

    def backend(self):
        b = Backend.__new__(Backend)
        QObject.__init__(b)
        b._queue_mutations = QueueMutationCoordinator()
        b._queue_intent_generation = 0
        b._workers = SimpleNamespace(stop_requested=threading.Event())
        b._start_worker = lambda work, **kwargs: (work() or True)
        b._disliked = []
        b._queue = []
        b._repeat = b._single = b._dj_on = False
        b._song = {'id': 1, 'file': 'old', 'title': 'Old'}
        b._beacon = BeaconController(b, [], self.path.with_name('provider.json'))
        b.events = []
        b.navRequested.connect(lambda *args: b.events.append(args))
        return b

    def execute(self, client, backend, kind, request):
        @contextmanager
        def temporary(*args, **kwargs):
            yield client
        with patch('ampere.mpdclient.temporary_mpd_client', temporary):
            return backend._execute_queue_intent(kind, request)

    def radio(self, client, backend, files=('radio',), recovery=None):
        recovery = recovery or backend._beacon.recovery
        result = self.execute(client, backend, 'replace', {
            'files': files, 'cancelEvent': threading.Event(), 'radioRecovery': recovery,
            'beaconGuard': {'queue': tuple((r['id'], r['file']) for r in client.queue)},
        })
        return recovery, result

    def restore(self, client, backend, recovery):
        return self.execute(client, backend, 'restore-radio', {
            'radioRecovery': recovery, 'cancelEvent': threading.Event(),
        })

    def test_original_full_queue_duplicates_index_elapsed_pause_and_random_restore(self):
        b = self.backend()
        client = RestoreClient(['a', 'b', 'a'], index=2)
        client.random_mode = True
        recovery, result = self.radio(client, b)
        self.assertTrue(result['success'])
        self.assertEqual(['a', 'b', 'a'], recovery.data['original']['files'])
        self.assertTrue(self.restore(client, b, recovery)['success'])
        self.assertEqual(['a', 'b', 'a'], [r['file'] for r in client.queue])
        self.assertEqual(client.queue[2]['id'], client.status()['songid'])
        self.assertEqual('pause', client.state)
        self.assertEqual(34.5, client.elapsed)
        self.assertTrue(client.random_mode)
        self.assertIsNone(RadioRecovery(recovery.path).data)

    def test_original_survives_second_radio_and_restart(self):
        b = self.backend()
        client = RestoreClient(['old', 'later'], state='play')
        recovery, _ = self.radio(client, b)
        original = copy.deepcopy(recovery.data['original'])
        self.radio(client, b, files=('second', 'third'))
        loaded = RadioRecovery(recovery.path)
        self.assertEqual(original, loaded.data['original'])
        self.assertTrue(self.restore(client, b, loaded)['success'])
        self.assertEqual('play', client.state)

    def test_capture_failure_cannot_stage_or_change_random(self):
        b = self.backend()
        client = RestoreClient(['old'])
        client.fail_capture = True
        _recovery, result = self.radio(client, b)
        self.assertFalse(result['success'])
        self.assertEqual(['old'], [r['file'] for r in client.queue])
        self.assertEqual([], client.transactions)

    def test_durable_capture_failure_precedes_destructive_commands(self):
        b = self.backend()
        client = RestoreClient(['old'])
        with patch.object(b._beacon.recovery, 'write', side_effect=OSError('disk full')):
            _, result = self.radio(client, b)
        self.assertFalse(result['success'])
        self.assertEqual(['old'], [r['file'] for r in client.queue])
        self.assertEqual([], client.transactions)

    def test_initial_bad_file_keeps_original_recoverable(self):
        b = self.backend()
        client = RestoreClient(['old', 'later'])
        client.fail_add_file = 'bad'
        recovery, result = self.radio(client, b, files=('bad',))
        self.assertFalse(result['success'])
        self.assertEqual(['old', 'later'], [r['file'] for r in client.queue])
        self.assertEqual(['old', 'later'], recovery.data['original']['files'])

    def test_seek_failure_rolls_back_radio_and_retry_retains_original(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        client.elapsed = 12
        client.fail_seek_once = True
        self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(['radio'], [r['file'] for r in client.queue])
        self.assertEqual(12, client.elapsed)
        self.assertIsNotNone(RadioRecovery(recovery.path).data)
        self.assertTrue(self.restore(client, b, recovery)['success'])

    def test_disliked_original_fails_without_silently_filtering(self):
        b = self.backend()
        client = RestoreClient(['old', 'bad'])
        recovery, _ = self.radio(client, b)
        b._disliked = ['bad']
        before = copy.deepcopy(client.queue)
        self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(before, client.queue)
        self.assertIsNotNone(recovery.data)

    def test_external_takeover_is_never_overwritten_or_adopted(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        expected = copy.deepcopy(recovery.data['expected'])
        client._append('deliberate')
        before = copy.deepcopy(client.queue)
        self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(before, client.queue)
        self.assertEqual(expected, recovery.data['expected'])

    def test_cancelled_worker_cannot_publish_and_stale_plan_is_ignored(self):
        b = self.backend()
        client = RestoreClient(['old'])
        token = threading.Event()
        token.set()
        result = self.execute(client, b, 'append', {'files': ['radio'], 'cancelEvent': token})
        self.assertFalse(result['success'])
        b._beacon._ready({'generation': -1})
        self.assertEqual(['old'], [r['file'] for r in client.queue])

    def test_manual_takeover_revokes_recovery_and_stale_worker_cannot_rewrite_it(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        b._beacon.cancel()
        recovery.reconcile(client)
        self.assertFalse(recovery.valid)
        self.assertIsNone(RadioRecovery(recovery.path).data)
        self.assertIsNone(b._beacon.recovery.data)

    def test_exit_waits_for_verified_callback_and_failure_retains_recovery(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        b._queue = client.playlistinfo()
        pending = []
        b._request_queue_intent = lambda kind, request, on_finished: pending.append(on_finished) or True
        b._beacon.exit()
        self.assertTrue(b._beacon.restoring)
        self.assertEqual([], b.events)
        self.assertFalse(b._beacon.exit())
        pending.pop()(False)
        self.assertFalse(b._beacon.restoring)
        self.assertIsNotNone(recovery.data)
        self.assertEqual([], b.events)
        b._beacon.exit()
        pending.pop()(True)
        self.assertEqual([('now', '')], b.events)

    def test_legacy_radio_without_original_cannot_claim_success(self):
        b = self.backend()
        b._beacon.active_id = 'legacy'
        b._beacon.exit()
        self.assertEqual([], b.events)
        self.assertIn('unavailable', b._beacon.status)

    def test_duplicate_radio_position_uses_exact_id_without_manual_takeover(self):
        b = self.backend()
        b._queue = [{'id': 11, 'file': 'same'}, {'id': 12, 'file': 'same'}]
        b._beacon.active_id = b._beacon.selected_id = 'active'
        requests = []
        b._request_soft_queue_intent = lambda kind, request: requests.append((kind, request)) or True
        self.assertTrue(b.playBeaconPosition(1))
        self.assertEqual([('jump', {'songId': 12, 'beaconOwner': True})], requests)
        self.assertFalse(b.playBeaconPosition(2))

    def test_empty_and_stopped_originals_restore_without_starting_playback(self):
        for files, index in (([], 0), (['old', 'later'], 1)):
            with self.subTest(files=files):
                b = self.backend()
                client = RestoreClient(files, index=index, state='stop', elapsed=0)
                recovery, result = self.radio(client, b)
                self.assertTrue(result['success'])
                self.assertTrue(self.restore(client, b, recovery)['success'])
                self.assertEqual(files, [r['file'] for r in client.queue])
                self.assertEqual('stop', client.state)

    def test_rejected_play_preserves_radio_without_leaking_staged_rows(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        client.fail_play = True
        self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(['radio'], [r['file'] for r in client.queue])
        self.assertIsNotNone(recovery.data)

    def test_delete_failure_never_claims_success_and_retry_can_finish(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        client.fail_delete_always = True
        self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertIsNotNone(recovery.data)
        client.fail_delete_always = False
        self.assertTrue(self.restore(client, b, recovery)['success'])
        self.assertEqual(['old'], [r['file'] for r in client.queue])

    def test_exit_cancels_old_plan_and_waits_for_queue_lease(self):
        b = self.backend()
        client = RestoreClient(['old'])
        self.radio(client, b)
        old_token, old_generation = b._beacon.token, b._beacon.generation
        lease, _ = b._queue_mutations.acquire('radio-publication')
        scheduled, requests = [], []
        b._request_queue_intent = lambda *args, **kwargs: requests.append((args, kwargs)) or True
        with patch('ampere.beacon_controller.QTimer.singleShot', side_effect=lambda delay, call: scheduled.append(call)):
            b._beacon.exit()
        self.assertTrue(old_token.is_set())
        self.assertGreater(b._beacon.generation, old_generation)
        self.assertEqual([], requests)
        b._beacon._ready({'generation': old_generation})
        lease.release()
        scheduled.pop()()
        self.assertEqual('restore-radio', requests[0][0][0])
        self.assertEqual([], b.events)

    def test_staged_stale_refill_is_removed_without_adopting_external_queue(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        expected = copy.deepcopy(recovery.data['expected'])
        original_end = client.command_list_end
        def mutate_during_stage():
            original_end()
            client._append('external')
        client.command_list_end = mutate_during_stage
        result = self.execute(client, b, 'append', {
            'files': ['refill'], 'cancelEvent': threading.Event(), 'radioRecovery': recovery,
            'beaconGuard': {'queue': tuple((r['id'], r['file']) for r in client.queue)},
        })
        self.assertFalse(result['success'])
        # Staging cannot establish which appended row belongs to another client;
        # it must retain external changes and never bind them to Radio recovery.
        self.assertEqual(expected, recovery.data['expected'])

    def test_recovered_original_blocks_autoplay_until_explicit_exit_or_takeover(self):
        b = self.backend()
        client = RestoreClient(['old'])
        self.radio(client, b)
        b._beacon.active_id = ''
        b._beacon.busy = False
        self.assertEqual('beacon', b._session_kind())

    def test_restart_rebinds_new_ids_only_for_exact_ordered_files(self):
        b = self.backend()
        client = RestoreClient(['old', 'later'])
        recovery, _ = self.radio(client, b, files=('radio', 'second'))
        loaded = RadioRecovery(recovery.path)
        restarted = RestoreClient(['radio', 'second'])
        self.assertNotEqual(loaded.data['expected'][0][0], restarted.queue[0]['id'])
        self.assertTrue(self.restore(restarted, b, loaded)['success'])
        self.assertEqual(['old', 'later'], [r['file'] for r in restarted.queue])

    def test_restart_does_not_rebind_different_queue(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b, files=('radio', 'second'))
        loaded = RadioRecovery(recovery.path)
        changed = RestoreClient(['second', 'radio'])
        before = copy.deepcopy(changed.queue)
        self.assertFalse(self.restore(changed, b, loaded)['success'])
        self.assertEqual(before, changed.queue)

    def test_clear_failure_retains_verified_restored_identity_for_retry(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        with patch.object(recovery, 'clear', side_effect=OSError('clear failed')):
            self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(['old'], [r['file'] for r in client.queue])
        self.assertEqual([[r['id'], r['file']] for r in client.queue], recovery.data['expected'])
        self.assertTrue(self.restore(client, b, recovery)['success'])

    def test_delayed_manual_clear_cannot_erase_new_original(self):
        b = self.backend()
        client = RestoreClient(['old'])
        self.radio(client, b)
        pending = []
        b._start_worker = lambda work, **kwargs: pending.append(work) or True
        b._beacon.cancel()
        replacement = b._beacon.recovery
        new_queue = RestoreClient(['deliberate'])
        replacement.capture(self.playback(new_queue))
        pending.pop()()
        self.assertEqual(['deliberate'], RadioRecovery(replacement.path).data['original']['files'])

    def test_cancellation_during_seek_rolls_back_before_retiring_radio(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        event = threading.Event()
        seek = client.seekid
        def cancel_on_seek(identity, elapsed):
            seek(identity, elapsed)
            event.set()
        client.seekid = cancel_on_seek
        result = self.execute(client, b, 'restore-radio', {
            'radioRecovery': recovery, 'cancelEvent': event,
        })
        self.assertFalse(result['success'])
        self.assertEqual(['radio'], [r['file'] for r in client.queue])
        self.assertIsNotNone(recovery.data)

    def test_repeated_manual_cancel_still_clears_durable_original(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        pending = []
        b._start_worker = lambda work, **kwargs: pending.append(work) or True
        b._beacon.cancel()
        b._beacon.cancel()
        for work in pending:
            work()
        self.assertIsNone(RadioRecovery(recovery.path).data)

    def test_failed_exit_keeps_radio_row_playback_within_recovery_ownership(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        b._queue = client.playlistinfo()
        b._beacon.active_id = ''
        self.assertTrue(b.beaconActive)
        requests = []
        b._request_soft_queue_intent = lambda kind, request: requests.append(request) or True
        self.assertTrue(b.playBeaconPosition(0))
        self.assertTrue(requests[0]['beaconOwner'])
        self.assertIsNotNone(recovery.data)

    def test_post_commit_journal_failure_retains_in_memory_retry_identity(self):
        b = self.backend()
        client = RestoreClient(['old'])
        recovery, _ = self.radio(client, b)
        with patch.object(recovery, 'write', side_effect=OSError('disk full')):
            self.assertFalse(self.restore(client, b, recovery)['success'])
        self.assertEqual(['old'], [r['file'] for r in client.queue])
        self.assertEqual([[r['id'], r['file']] for r in client.queue], recovery.data['expected'])
        self.assertTrue(self.restore(client, b, recovery)['success'])
