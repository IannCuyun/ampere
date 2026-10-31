import threading
import unittest

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from ampere.playback import PlaybackController, QueueSnapshotStore
from ampere.queue_mutations import QueueMutationCoordinator


class QueueClient:
    def __init__(self, files=()):
        self.queue = []
        self.next_id = 1
        for file in files:
            self._append(file)
        self.fail_begin_once = False
        self.fail_add_file = None
        self.fail_end_after_apply = False
        self.fail_delete_once = False
        self.fail_delete_always = False
        self.fail_move_after = None
        self.move_count = 0
        self.transactions = []
        self.played = []
        self.fail_play = False
        self.lose_play_reply = False
        self.status_unavailable = False
        self.stopped = False

    def _append(self, file):
        item = {"id": str(self.next_id), "file": str(file)}
        self.next_id += 1
        self.queue.append(item)
        return item

    def playlistinfo(self):
        return [dict(item) for item in self.queue]

    def command_list_ok_begin(self):
        if self.fail_begin_once:
            self.fail_begin_once = False
            raise MPDConnectionError("gone")
        self.current = []

    def add(self, file):
        self.current.append(file)
        if file == self.fail_add_file:
            raise CommandError("missing")
        self._append(file)

    def deleteid(self, song_id):
        if self.fail_delete_always:
            raise CommandError("delete rejected")
        for index, item in enumerate(self.queue):
            if item["id"] == str(song_id):
                self.queue.pop(index)
                if self.fail_delete_once:
                    self.fail_delete_once = False
                    raise MPDConnectionError("delete reply lost")
                return
        raise CommandError("No such song")

    def moveid(self, song_id, position):
        source = next((index for index, item in enumerate(self.queue)
                       if item["id"] == str(song_id)), None)
        if source is None:
            raise CommandError("No such song")
        item = self.queue.pop(source)
        self.queue.insert(int(position), item)
        self.move_count += 1
        if (self.fail_move_after is not None
                and self.move_count == self.fail_move_after):
            self.fail_move_after = None
            raise MPDConnectionError("partial reorder reply lost")

    def command_list_end(self):
        self.transactions.append(list(self.current))
        if self.fail_end_after_apply:
            self.fail_end_after_apply = False
            raise MPDConnectionError("reply lost")

    def playid(self, song_id):
        if not any(item["id"] == str(song_id) for item in self.queue):
            raise CommandError("No such song")
        if self.fail_play:
            raise CommandError("play rejected")
        self.played.append(str(song_id))
        self.stopped = False
        if self.lose_play_reply:
            self.lose_play_reply = False
            raise MPDConnectionError("play reply lost")

    def status(self):
        if self.status_unavailable:
            raise MPDConnectionError("status unavailable")
        result = {"state": "stop" if self.stopped else "play"}
        if self.played:
            result["songid"] = self.played[-1]
        return result

    def stop(self):
        self.stopped = True


class PlaybackControllerTests(unittest.TestCase):
    def controller(self, client, errors, disconnects):
        return PlaybackController(
            client, ensure_connected=lambda silent=False: True,
            mark_disconnected=lambda: disconnects.append(True),
            error=errors.append)

    def test_replace_retries_when_connection_failed_before_any_append(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.fail_begin_once = True
        controller = self.controller(client, errors, disconnects)
        self.assertTrue(controller.replace_queue(["one", "two"], 1))
        self.assertEqual([item["file"] for item in client.queue], ["one", "two"])
        self.assertEqual(["3"], client.played)
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_bad_staged_file_preserves_the_original_queue(self):
        client, errors, disconnects = QueueClient(["old-a", "old-b"]), [], []
        client.fail_add_file = "bad"
        controller = self.controller(client, errors, disconnects)

        self.assertFalse(controller.replace_queue(["new", "bad"], 0))

        self.assertEqual(["old-a", "old-b"],
                         [item["file"] for item in client.queue])
        self.assertEqual([], client.played)
        self.assertIn("missing", errors[-1])

    def test_append_and_play_commits_only_after_stable_id_readback(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        controller = self.controller(client, errors, disconnects)

        result = controller.append_and_play("new")

        self.assertTrue(result.committed)
        self.assertEqual(["old", "new"],
                         [item["file"] for item in client.queue])
        self.assertEqual(["2"], client.played)
        self.assertEqual([], errors)

    def test_append_and_play_rolls_back_rejected_playhead_move(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.fail_play = True
        controller = self.controller(client, errors, disconnects)

        result = controller.append_and_play("new")

        self.assertTrue(result.rolled_back)
        self.assertEqual(["old"], [item["file"] for item in client.queue])
        self.assertIn("play rejected", errors[-1])

    def test_append_and_play_reconciles_lost_success_reply(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.lose_play_reply = True
        controller = self.controller(client, errors, disconnects)

        result = controller.append_and_play("new")

        self.assertTrue(result.committed)
        self.assertEqual(["old", "new"],
                         [item["file"] for item in client.queue])
        self.assertEqual(["2"], client.played)
        self.assertEqual(1, len(disconnects))

    def test_unavailable_lost_reply_stays_indeterminate_until_reconciled(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.lose_play_reply = True
        client.status_unavailable = True
        controller = self.controller(client, errors, disconnects)

        pending = controller.append_and_play("new")

        self.assertTrue(pending.indeterminate)
        self.assertEqual(["old", "new"],
                         [item["file"] for item in client.queue])
        client.status_unavailable = False
        resolved = controller.reconcile_append_and_play(pending)
        self.assertTrue(resolved.committed)

    def test_failed_compensation_remains_indeterminate_not_false_failure(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.fail_play = True
        client.fail_delete_always = True
        controller = self.controller(client, errors, disconnects)

        result = controller.append_and_play("new")

        self.assertTrue(result.indeterminate)
        self.assertEqual(["old", "new"],
                         [item["file"] for item in client.queue])

    def test_lost_append_reply_is_verified_without_duplicate_staging(self):
        client, errors, disconnects = QueueClient(["old"]), [], []
        client.fail_end_after_apply = True
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.replace_queue(["one", "two"], 0))

        self.assertEqual(["one", "two"],
                         [item["file"] for item in client.queue])
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_partial_old_queue_commit_recovers_by_stable_song_id(self):
        client, errors, disconnects = QueueClient(["old-a", "old-b"]), [], []
        client.fail_delete_once = True
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.replace_queue(["new-a", "new-b"], 1))

        self.assertEqual(["new-a", "new-b"],
                         [item["file"] for item in client.queue])
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_clear_queue_recovers_lost_reply_without_global_clear(self):
        client, errors, disconnects = QueueClient(["one", "two"]), [], []
        client.fail_delete_once = True
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.clear_queue())

        self.assertEqual([], client.queue)
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_clear_queue_preserves_concurrent_additions(self):
        client, errors, disconnects = QueueClient(["one", "two"]), [], []
        original_delete = client.deleteid
        first = True

        def delete_with_concurrent_add(song_id):
            nonlocal first
            original_delete(song_id)
            if first:
                first = False
                client._append("concurrent")

        client.deleteid = delete_with_concurrent_add
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.clear_queue())

        self.assertEqual(["concurrent"], [item["file"] for item in client.queue])
        self.assertEqual([], errors)

    def test_bench_disliked_advances_then_removes_every_duplicate(self):
        client, errors, disconnects = QueueClient(
            ["played", "bad", "bad", "allowed", "bad"]), [], []
        client.played.append("2")
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.bench_disliked("bad"))

        self.assertEqual("4", client.played[-1])
        self.assertEqual(
            ["played", "allowed"],
            [item["file"] for item in client.queue])
        self.assertEqual([], errors)

    def test_bench_disliked_stops_when_no_allowed_successor_exists(self):
        client, errors, disconnects = QueueClient(["played", "bad"]), [], []
        client.played.append("2")
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.bench_disliked("bad"))

        self.assertTrue(client.stopped)
        self.assertEqual(["played"], [item["file"] for item in client.queue])
        self.assertEqual([], errors)

    def test_bench_noncurrent_disliked_only_removes_queued_copies(self):
        client, errors, disconnects = QueueClient(
            ["current", "bad", "allowed", "bad"]), [], []
        client.played.append("1")
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.bench_disliked("bad"))

        self.assertEqual(["current", "allowed"],
                         [item["file"] for item in client.queue])
        self.assertEqual(["1"], client.played)
        self.assertEqual([], errors)

    def test_replace_upcoming_keeps_current_song_id_and_new_order(self):
        client, errors, disconnects = QueueClient(
            ["played", "current", "old-next"]), [], []
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.replace_upcoming(["new-a", "new-b"], "2"))

        self.assertEqual(
            [("2", "current"), ("4", "new-a"), ("5", "new-b")],
            [(item["id"], item["file"]) for item in client.queue])
        self.assertEqual([], client.played)
        self.assertEqual([], errors)

    def test_append_connection_loss_is_not_retried(self):
        client, errors, disconnects = QueueClient(), [], []
        client.fail_begin_once = True
        controller = self.controller(client, errors, disconnects)
        self.assertFalse(controller.append_files(["one", "two"]))
        self.assertEqual([], client.transactions)
        self.assertEqual(1, len(disconnects))
        self.assertIn("try again", errors[0])

    def test_reorder_window_recovers_from_a_partial_command_list(self):
        client, errors, disconnects = QueueClient(
            ["played", "current", "a", "b", "c", "outside"]), [], []
        client.fail_move_after = 1
        controller = self.controller(client, errors, disconnects)

        self.assertTrue(controller.reorder_window(["5", "3", "4"], 2))

        self.assertEqual(
            [("1", "played"), ("2", "current"), ("5", "c"),
             ("3", "a"), ("4", "b"), ("6", "outside")],
            [(item["id"], item["file"]) for item in client.queue])
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_reorder_window_rejects_stale_membership_without_mutation(self):
        client, errors, disconnects = QueueClient(
            ["current", "a", "replacement", "c"]), [], []
        controller = self.controller(client, errors, disconnects)

        self.assertFalse(controller.reorder_window(["4", "2", "99"], 1))

        self.assertEqual(["current", "a", "replacement", "c"],
                         [item["file"] for item in client.queue])
        self.assertEqual(0, client.move_count)
        self.assertIn("changed", errors[-1])

    def test_structural_change_rejects_busy_dj_owner_without_client_io(self):
        client, errors, disconnects = QueueClient(["one"]), [], []
        coordinator = QueueMutationCoordinator()
        entered = threading.Event()
        release = threading.Event()
        owner = threading.Thread(target=lambda: coordinator.run(
            "dj-bridge-splice", lambda: (entered.set(), release.wait(1))))
        owner.start()
        self.assertTrue(entered.wait(1))
        controller = PlaybackController(
            client, ensure_connected=lambda silent=False: True,
            mark_disconnected=lambda: disconnects.append(True),
            error=errors.append, queue_mutations=coordinator)

        self.assertFalse(controller.remove_ids(["1"]))

        release.set()
        owner.join(1)
        self.assertEqual(["one"], [item["file"] for item in client.queue])
        self.assertIn("finishing another change", errors[-1])


class OptionsClient:
    def __init__(self, repeat=False, single=False):
        self.repeat_on = repeat
        self.single_on = single
        self.fail_after_first = False
        self.random_on = False
        self.ignore_random_once = False
        self.volume = 40
        self.ignore_volume_once = False
        self.state = "pause"
        self.lose_state_reply_once = False
        self.current = []

    def status(self):
        return {"repeat": "1" if self.repeat_on else "0",
                "single": "1" if self.single_on else "0",
                "random": "1" if self.random_on else "0",
                "volume": str(self.volume),
                "state": self.state}

    def _set_state(self, state):
        self.state = state
        if self.lose_state_reply_once:
            self.lose_state_reply_once = False
            raise MPDConnectionError("state reply lost")

    def play(self):
        self._set_state("play")

    def pause(self, enabled):
        self._set_state("pause" if enabled else "play")

    def stop(self):
        self._set_state("stop")

    def setvol(self, value):
        if self.ignore_volume_once:
            self.ignore_volume_once = False
            return
        self.volume = int(value)

    def random(self, value):
        if self.ignore_random_once:
            self.ignore_random_once = False
            return
        self.random_on = bool(value)

    def command_list_ok_begin(self):
        self.current = []

    def repeat(self, value):
        self.repeat_on = bool(value)
        self.current.append(("repeat", int(value)))
        if self.fail_after_first:
            self.fail_after_first = False
            raise MPDConnectionError("partial options reply lost")

    def single(self, value):
        self.single_on = bool(value)
        self.current.append(("single", int(value)))

    def command_list_end(self):
        pass


class PlaybackOptionsTests(unittest.TestCase):
    def controller(self, client, errors, disconnects):
        return PlaybackController(
            client, ensure_connected=lambda silent=False: True,
            mark_disconnected=lambda: disconnects.append(True),
            error=errors.append)

    def test_repeat_mode_commits_only_after_verified_pair(self):
        client, errors, disconnects = OptionsClient(), [], []
        result = self.controller(client, errors, disconnects).set_repeat_mode(
            True, True)
        self.assertTrue(result.committed)
        self.assertEqual((True, True), (client.repeat_on, client.single_on))
        self.assertEqual([], errors)

    def test_toggle_uses_authoritative_state_and_verifies_lost_reply(self):
        client, errors, disconnects = OptionsClient(), [], []
        client.state = "play"
        client.lose_state_reply_once = True

        result = self.controller(client, errors, disconnects).toggle_state()

        self.assertTrue(result.committed)
        self.assertEqual("pause", result.state)
        self.assertEqual(1, len(disconnects))
        self.assertEqual([], errors)

    def test_explicit_transport_state_is_dispatched_only_once(self):
        client, errors, disconnects = OptionsClient(), [], []
        calls = []
        original = client.play

        def play():
            calls.append(True)
            original()

        client.play = play
        client.lose_state_reply_once = True

        result = self.controller(client, errors, disconnects).set_state("play")

        self.assertTrue(result.committed)
        self.assertEqual([True], calls)
        self.assertEqual("play", result.state)

    def test_pause_while_stopped_is_a_verified_noop(self):
        client, errors, disconnects = OptionsClient(), [], []
        client.state = "stop"

        result = self.controller(client, errors, disconnects).set_state("pause")

        self.assertTrue(result.committed)
        self.assertEqual("stop", result.state)
        self.assertEqual([], errors)

    def test_partial_repeat_mode_write_rolls_back_the_prior_pair(self):
        client, errors, disconnects = OptionsClient(False, False), [], []
        client.fail_after_first = True
        result = self.controller(client, errors, disconnects).set_repeat_mode(
            True, True)
        self.assertFalse(result.committed)
        self.assertTrue(result.rollback_complete)
        self.assertEqual((False, False), (client.repeat_on, client.single_on))
        self.assertEqual(1, len(disconnects))
        self.assertIn("could not be changed", errors[-1])

    def test_repeat_mode_accepts_mpd_oneshot_as_single(self):
        client, errors, disconnects = OptionsClient(True, True), [], []
        client.status = lambda: {"repeat": "1", "single": "oneshot"}
        result = self.controller(client, errors, disconnects).set_repeat_mode(
            True, True)
        self.assertTrue(result.committed)
        self.assertEqual([], errors)

    def test_random_mode_commits_only_after_readback(self):
        client, errors, disconnects = OptionsClient(), [], []
        result = self.controller(client, errors, disconnects).set_random_mode(True)

        self.assertTrue(result.committed)
        self.assertTrue(result.value)
        self.assertFalse(result.previous)
        self.assertEqual([], errors)

    def test_rejected_random_mode_restores_authoritative_baseline(self):
        client, errors, disconnects = OptionsClient(), [], []
        client.ignore_random_once = True
        result = self.controller(client, errors, disconnects).set_random_mode(True)

        self.assertFalse(result.committed)
        self.assertFalse(result.value)
        self.assertFalse(result.previous)
        self.assertTrue(result.rollback_complete)
        self.assertIn("could not be changed", errors[-1])

    def test_volume_commits_only_after_authoritative_readback(self):
        client, errors, disconnects = OptionsClient(), [], []

        result = self.controller(client, errors, disconnects).set_volume(64)

        self.assertTrue(result.committed)
        self.assertEqual(64, result.value)
        self.assertEqual(64, client.volume)
        self.assertEqual([], errors)

    def test_rejected_volume_restores_the_verified_baseline(self):
        client, errors, disconnects = OptionsClient(), [], []
        client.ignore_volume_once = True

        result = self.controller(client, errors, disconnects).set_volume(64)

        self.assertFalse(result.committed)
        self.assertTrue(result.rollback_complete)
        self.assertEqual(40, result.value)
        self.assertEqual(40, client.volume)
        self.assertIn("could not be changed", errors[-1])


class QueueSnapshotStoreTests(unittest.TestCase):
    def store(self):
        return QueueSnapshotStore(
            normalize=lambda item: {"file": str(item["file"]),
                                    "id": int(item.get("id", -1))})

    def test_failed_read_preserves_last_verified_snapshot(self):
        store = self.store()
        store.publish([{"file": "one", "id": "1"}])

        result = store.publish(None)

        self.assertFalse(result.success)
        self.assertEqual("one", result.songs[0]["file"])
        self.assertEqual("one", store.songs[0]["file"])

    def test_valid_empty_queue_is_a_successful_publication(self):
        store = self.store()
        store.publish([{"file": "one"}])
        result = store.publish([])
        self.assertTrue(result.success)
        self.assertEqual((), result.songs)

    def test_malformed_snapshot_cannot_replace_verified_state(self):
        store = self.store()
        store.publish([{"file": "one"}])
        result = store.publish([{"missing": "file"}])
        self.assertFalse(result.success)
        self.assertEqual("one", result.songs[0]["file"])


if __name__ == "__main__":
    unittest.main()
