"""Playback and queue transactions independent of Qt presentation."""

from __future__ import annotations

from dataclasses import dataclass
import math

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from .queue_mutations import QueueMutationCoordinator


@dataclass(frozen=True)
class QueueSnapshotResult:
    success: bool
    songs: tuple[dict, ...]


@dataclass(frozen=True)
class PlaybackOptionsResult:
    committed: bool
    repeat: bool
    single: bool
    rollback_complete: bool = True


@dataclass(frozen=True)
class PlaybackBooleanResult:
    committed: bool
    value: bool
    rollback_complete: bool = True
    previous: bool | None = None


@dataclass(frozen=True)
class PlaybackVolumeResult:
    committed: bool
    value: int | None
    rollback_complete: bool = True


@dataclass(frozen=True)
class PlaybackStateResult:
    committed: bool
    state: str


@dataclass(frozen=True)
class QueuePlayResult:
    """Truthful outcome for a staged queue addition plus playhead move."""

    status: str
    target_id: str = ""
    message: str = ""

    @property
    def committed(self) -> bool:
        return self.status == "committed"

    @property
    def rolled_back(self) -> bool:
        return self.status == "rolled-back"

    @property
    def indeterminate(self) -> bool:
        return self.status == "indeterminate"


class QueueSnapshotStore:
    """Publish only complete queue snapshots while retaining the last good one."""

    def __init__(self, *, normalize):
        self._normalize = normalize
        self._songs: tuple[dict, ...] = ()

    @property
    def songs(self) -> tuple[dict, ...]:
        return tuple(dict(song) for song in self._songs)

    def publish(self, items) -> QueueSnapshotResult:
        if items is None:
            return QueueSnapshotResult(False, self.songs)
        try:
            songs = tuple(self._normalize(item) for item in items)
        except Exception:
            return QueueSnapshotResult(False, self.songs)
        self._songs = songs
        return QueueSnapshotResult(True, self.songs)

    def publish_normalized(self, songs) -> QueueSnapshotResult:
        """Publish rows already normalized by an owned worker."""
        try:
            normalized = tuple(dict(song) for song in songs)
            if any(not song.get("file") for song in normalized):
                raise ValueError("queue row missing file")
        except Exception:
            return QueueSnapshotResult(False, self.songs)
        self._songs = normalized
        return QueueSnapshotResult(True, self.songs)


class PlaybackController:
    def __init__(self, client, *, ensure_connected, mark_disconnected,
                 error=lambda _message: None, queue_mutations=None):
        self.client = client
        self._ensure_connected = ensure_connected
        self._mark_disconnected = mark_disconnected
        self._error = error
        self._queue_mutations = queue_mutations or QueueMutationCoordinator()

    def _structural(self, operation) -> bool:
        result = self._queue_mutations.run("playback", operation)
        if not result.accepted:
            self._error(
                "Queue is finishing another change — try again in a moment")
            return False
        return bool(result.value)

    @staticmethod
    def _identity(item) -> tuple[str, str]:
        return str(item.get("id", "")), str(item.get("file", ""))

    def _read_queue(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                items = list(self.client.playlistinfo() or [])
                if all(str(item.get("id", "")) for item in items):
                    return items
                self._error("Playback engine returned a queue without stable IDs")
                return None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError as exc:
                self._error(str(exc))
                return None
        self._error("Playback engine did not respond — try again")
        return None

    def _read_current_song_id(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                status = self.client.status() or {}
                song_id = status.get("songid")
                return str(song_id) if song_id is not None else ""
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                return None
        return None

    def _read_repeat_mode(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                status = self.client.status() or {}
                repeat = status.get("repeat")
                single = status.get("single")
                if (str(repeat) in ("0", "1")
                        and str(single) in ("0", "1", "oneshot")):
                    return str(repeat) == "1", str(single) in ("1", "oneshot")
                return None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                return None
        return None

    def _write_repeat_mode(self, repeat: bool, single: bool) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            self.client.command_list_ok_begin()
            self.client.repeat(1 if repeat else 0)
            self.client.single(1 if single else 0)
            self.client.command_list_end()
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def _read_random_mode(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                value = (self.client.status() or {}).get("random")
                return str(value) == "1" if str(value) in ("0", "1") else None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                return None
        return None

    def _write_random_mode(self, enabled: bool) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            self.client.random(1 if enabled else 0)
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def _read_volume(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                value = int((self.client.status() or {}).get("volume", -1))
                return value if 0 <= value <= 100 else None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except (CommandError, TypeError, ValueError):
                return None
        return None

    def _read_state(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                state = str((self.client.status() or {}).get("state", ""))
                return state if state in ("play", "pause", "stop") else None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                return None
        return None

    def _write_state_once(self, desired: str) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            if desired == "play":
                self.client.play()
            elif desired == "pause":
                self.client.pause(1)
            else:
                self.client.stop()
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def set_state(self, desired: str) -> PlaybackStateResult:
        """Apply an absolute transport state once and verify fresh readback."""
        desired = str(desired)
        if desired not in ("play", "pause", "stop"):
            return PlaybackStateResult(False, "stop")
        baseline = self._read_state()
        if baseline is None:
            self._error("Playback state could not be read — try again")
            return PlaybackStateResult(False, "stop")
        # Pause is a no-op while stopped, matching MPRIS semantics.
        if baseline == desired or (desired == "pause" and baseline == "stop"):
            return PlaybackStateResult(True, baseline)
        self._write_state_once(desired)
        current = self._read_state()
        if current == desired:
            return PlaybackStateResult(True, current)
        self._error("Playback state could not be changed — try again")
        return PlaybackStateResult(False, current or baseline)

    def toggle_state(self) -> PlaybackStateResult:
        """Toggle from authoritative MPD state rather than cached UI state."""
        baseline = self._read_state()
        if baseline is None:
            self._error("Playback state could not be read — try again")
            return PlaybackStateResult(False, "stop")
        desired = "pause" if baseline == "play" else "play"
        self._write_state_once(desired)
        current = self._read_state()
        if current == desired:
            return PlaybackStateResult(True, current)
        self._error("Playback state could not be changed — try again")
        return PlaybackStateResult(False, current or baseline)

    def _write_volume(self, value: int) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            self.client.setvol(int(value))
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def set_volume(self, value: int) -> PlaybackVolumeResult:
        """Publish volume only after MPD readback, rolling back rejection."""
        desired = max(0, min(100, int(value)))
        baseline = self._read_volume()
        if baseline is None:
            self._error("Playback volume could not be read — try again")
            return PlaybackVolumeResult(False, None)
        if baseline == desired:
            return PlaybackVolumeResult(True, desired)

        self._write_volume(desired)
        current = self._read_volume()
        if current == desired:
            return PlaybackVolumeResult(True, desired)

        self._write_volume(baseline)
        restored = self._read_volume()
        rollback_complete = restored == baseline
        detail = ("; playback volume may need another try"
                  if not rollback_complete else "")
        self._error("Playback volume could not be changed" + detail)
        published = restored if restored is not None else baseline
        return PlaybackVolumeResult(
            False, published, rollback_complete=rollback_complete)

    def set_random_mode(self, enabled: bool) -> PlaybackBooleanResult:
        """Apply MPD random mode only after authoritative readback."""
        desired = bool(enabled)
        baseline = self._read_random_mode()
        if baseline is None:
            self._error("Playback random mode could not be read — try again")
            return PlaybackBooleanResult(False, False)
        if baseline == desired:
            return PlaybackBooleanResult(True, desired, previous=baseline)
        self._write_random_mode(desired)
        current = self._read_random_mode()
        if current == desired:
            return PlaybackBooleanResult(True, desired, previous=baseline)

        self._write_random_mode(baseline)
        restored = self._read_random_mode()
        rollback_complete = restored == baseline
        detail = ("; playback random mode may need another try"
                  if not rollback_complete else "")
        self._error("Playback random mode could not be changed" + detail)
        value = restored if restored is not None else baseline
        return PlaybackBooleanResult(
            False, value, rollback_complete=rollback_complete,
            previous=baseline)

    def set_repeat_mode(self, repeat: bool,
                        single: bool) -> PlaybackOptionsResult:
        """Apply and verify MPD's coupled loop options as one state.

        MPD command lists are sequential, so a lost connection can apply only
        one option. Reconcile against a fresh status read; if the requested
        pair is not live, restore and verify the prior pair.
        """
        desired = bool(repeat), bool(single)
        baseline = self._read_repeat_mode()
        if baseline is None:
            self._error("Playback loop state could not be read — try again")
            return PlaybackOptionsResult(False, False, False)
        if baseline == desired:
            return PlaybackOptionsResult(True, *desired)

        self._write_repeat_mode(*desired)
        current = self._read_repeat_mode()
        if current == desired:
            return PlaybackOptionsResult(True, *desired)

        self._write_repeat_mode(*baseline)
        restored = self._read_repeat_mode()
        rollback_complete = restored == baseline
        detail = ("; playback loop state may need another try"
                  if not rollback_complete else "")
        self._error("Playback loop mode could not be changed" + detail)
        published = restored if restored is not None else baseline
        return PlaybackOptionsResult(
            False, *published, rollback_complete=rollback_complete)

    def _remove_ids(self, song_ids) -> bool:
        """Remove exact queue entries, recovering from partial/lost replies."""
        remaining = {str(song_id) for song_id in song_ids}
        for _attempt in range(3):
            items = self._read_queue()
            if items is None:
                return False
            live = {str(item.get("id", "")) for item in items}
            pending = [song_id for song_id in remaining if song_id in live]
            if not pending:
                return True
            try:
                self.client.command_list_ok_begin()
                for song_id in pending:
                    self.client.deleteid(song_id)
                self.client.command_list_end()
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                # A concurrent deletion or a partially executed command list
                # is recoverable because IDs never shift. Re-read and continue.
                pass
        items = self._read_queue()
        live = ({str(item.get("id", "")) for item in items}
                if items is not None else remaining)
        if remaining.isdisjoint(live):
            return True
        self._error("Queue changed during replacement — existing songs were retained")
        return False

    def remove_ids(self, song_ids) -> bool:
        """Remove exact live queue entries and verify their absence."""
        song_ids = tuple(song_ids)
        return self._structural(lambda: self._remove_ids(song_ids))

    def bench_disliked(self, file: str) -> bool:
        """Advance away from ``file`` and remove every queued occurrence.

        Taste persistence happens before this transaction is admitted.  Stable
        MPD song IDs let the cleanup tolerate duplicate files and lost delete
        replies without ever removing an unrelated row.
        """
        file = str(file or "")
        if not file:
            return False
        return self._structural(lambda: self._bench_disliked(file))

    def _bench_disliked(self, file: str) -> bool:
        baseline = self._read_queue()
        if baseline is None:
            return False
        matching = [item for item in baseline
                    if str(item.get("file", "")) == file]
        if not matching:
            return True

        current_id = self._read_current_song_id()
        if current_id is None:
            return False
        matching_ids = {str(item.get("id", "")) for item in matching}
        if current_id in matching_ids:
            current_index = next(
                (index for index, item in enumerate(baseline)
                 if str(item.get("id", "")) == current_id), -1)
            next_allowed = next(
                (item for item in baseline[current_index + 1:]
                 if str(item.get("file", "")) != file), None)
            try:
                if next_allowed is None:
                    self.client.stop()
                else:
                    self.client.playid(str(next_allowed["id"]))
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError as exc:
                self._error(str(exc))

            moved_id = self._read_current_song_id()
            if next_allowed is not None:
                if moved_id != str(next_allowed["id"]):
                    self._error(
                        "Disliked song was saved, but playback could not advance")
                    return False
            elif self._read_state() != "stop":
                self._error(
                    "Disliked song was saved, but playback could not stop")
                return False

        if not self._remove_ids(matching_ids):
            return False
        current = self._read_queue()
        if current is None:
            return False
        if any(str(item.get("file", "")) == file for item in current):
            self._error(
                "Disliked song was saved, but a queued copy could not be removed")
            return False
        return True

    def clear_queue(self) -> bool:
        """Remove the queue snapshot present now, preserving later additions."""
        return self._structural(self._clear_queue)

    def _clear_queue(self) -> bool:
        baseline = self._read_queue()
        if baseline is None:
            return False
        return self._remove_ids(item["id"] for item in baseline)

    def _stage_files(self, files):
        """Append and verify new files while the authoritative queue survives."""
        baseline = self._read_queue()
        if baseline is None:
            return None
        baseline_identity = [self._identity(item) for item in baseline]
        old_length = len(baseline)
        for attempt in (0, 1):
            failed = None
            try:
                self.client.command_list_ok_begin()
                for file in files:
                    self.client.add(file)
                self.client.command_list_end()
            except (MPDConnectionError, OSError) as exc:
                self._mark_disconnected()
                failed = exc
            except CommandError as exc:
                failed = exc

            current = self._read_queue()
            if current is None:
                return None
            if [self._identity(item) for item in current[:old_length]] != baseline_identity:
                self._error("Queue changed during replacement — existing songs were retained")
                return None
            tail = current[old_length:]
            tail_files = [str(item.get("file", "")) for item in tail]
            if tail_files == files:
                return baseline, tail
            if not tail and failed is not None and attempt == 0:
                # The connection failed before MPD accepted any append; a
                # single complete retry cannot duplicate anything.
                continue
            if tail and tail_files == files[:len(tail_files)]:
                self._remove_ids(item["id"] for item in tail)
            if isinstance(failed, CommandError):
                self._error(str(failed))
            else:
                self._error("Queue staging was interrupted — existing songs were retained")
            return None
        self._error("Playback engine did not respond — existing songs were retained")
        return None

    def replace_queue(self, files, start_index=0) -> bool:
        """Replace only after every new entry is staged and verified.

        MPD command lists are sequential, not rollback transactions. Appending
        first means a rejected path can be cleaned up by its new song IDs while
        every old entry—including the playing one—remains authoritative.
        """
        files = tuple(str(file) for file in files)
        return self._structural(
            lambda: self._replace_queue(files, start_index))

    def append_and_play(self, file) -> QueuePlayResult:
        """Append one track and commit its playhead move as one verified intent.

        The queue addition is staged first so rejection cannot disturb the live
        queue. If the playhead move is rejected, the staged entry is removed.
        A lost play reply is reconciled against MPD's stable song ID before the
        intent is reported as committed or rolled back.
        """
        file = str(file or "")
        if not file:
            return QueuePlayResult("rolled-back", message="No track was supplied")
        result = self._queue_mutations.run(
            "playback", lambda: self._append_and_play(file))
        if not result.accepted:
            message = "Queue is finishing another change — try again in a moment"
            self._error(message)
            return QueuePlayResult("rolled-back", message=message)
        return result.value

    def _append_and_play(self, file) -> QueuePlayResult:
        staged = self._stage_files([file])
        if staged is None:
            return QueuePlayResult(
                "rolled-back", message="Track could not be staged for playback")
        _baseline, added = staged
        if len(added) != 1:
            self._error("Track could not be staged for playback")
            return QueuePlayResult(
                "rolled-back", message="Track could not be staged for playback")
        target_id = str(added[0]["id"])
        error = None
        try:
            self.client.playid(target_id)
        except (MPDConnectionError, OSError) as exc:
            error = exc
            self._mark_disconnected()
        except CommandError as exc:
            error = exc

        current_id = self._read_current_song_id()
        if current_id == target_id:
            return QueuePlayResult("committed", target_id=target_id)
        if current_id is None and isinstance(error, (MPDConnectionError, OSError)):
            return QueuePlayResult(
                "indeterminate", target_id=target_id,
                message="Playback reply was lost; reconciling with MPD")
        removed = self._remove_ids((target_id,))
        if removed:
            message = (str(error) if isinstance(error, CommandError)
                       else "Track was queued, but playback was rejected")
            self._error(message)
            return QueuePlayResult(
                "rolled-back", target_id=target_id, message=message)
        return QueuePlayResult(
            "indeterminate", target_id=target_id,
            message="Playback outcome and rollback could not be verified")

    def reconcile_append_and_play(self, result) -> QueuePlayResult:
        """Resolve an ambiguous play reply without replaying the mutation."""
        if not isinstance(result, QueuePlayResult) or not result.indeterminate:
            return result
        current_id = self._read_current_song_id()
        if current_id is None:
            return result
        if current_id == result.target_id:
            return QueuePlayResult("committed", target_id=result.target_id)
        if self._remove_ids((result.target_id,)):
            message = "Playback did not commit; the staged track was removed"
            self._error(message)
            return QueuePlayResult(
                "rolled-back", target_id=result.target_id, message=message)
        return QueuePlayResult(
            "indeterminate", target_id=result.target_id,
            message="Playback outcome and rollback could not be verified")

    def _replace_queue(self, files, start_index=0) -> bool:
        files = list(files)
        staged = self._stage_files(files) if files else (self._read_queue(), [])
        if staged is None or staged[0] is None:
            return False
        baseline, added = staged
        if not self._remove_ids(item["id"] for item in baseline):
            # Commit did not finish. Keep the staged entries: deleting them
            # could remove the only complete replacement after a lost reply.
            return False
        if not added:
            return True
        index = max(0, min(int(start_index), len(added) - 1))
        target_id = str(added[index]["id"])
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                self.client.playid(target_id)
                return True
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError as exc:
                self._error(str(exc))
                return False
        self._error("Queue was replaced, but playback could not start")
        return False

    def capture_queue_restore(self):
        """Read coherent daemon evidence before any destructive Radio command."""
        before = self.client.status()
        rows = self.client.playlistinfo()
        after = self.client.status()
        for key in ('playlist', 'songid', 'state'):
            if before.get(key) != after.get(key):
                raise RuntimeError('Queue changed while capturing the pre-Radio queue')
        if 'playlist' not in after or int(after.get('playlistlength', -1)) != len(rows):
            raise RuntimeError('Complete pre-Radio queue evidence is unavailable')
        files = [str(row.get('file') or '') for row in rows]
        ids = [str(row.get('id') or '') for row in rows]
        state = after.get('state')
        if state not in ('play', 'pause', 'stop') or any(not f for f in files):
            raise RuntimeError('Pre-Radio queue evidence is unavailable')
        if len(set(ids)) != len(ids) or any(not identity for identity in ids):
            raise RuntimeError('Pre-Radio queue IDs are unavailable')
        current = str(after.get('songid', ''))
        index = ids.index(current) if current in ids else -1
        elapsed = float(after.get('elapsed', 0))
        if not math.isfinite(elapsed) or elapsed < 0 or (state != 'stop' and index < 0):
            raise RuntimeError('Pre-Radio playhead evidence is unavailable')
        return {'files': files, 'index': index, 'elapsed': elapsed, 'state': state,
                'random': str(after.get('random', '0')) == '1',
                'identity': [[identity, file] for identity, file in zip(ids, files)]}

    def restore_queue(self, snapshot, *, guard, on_staged=None):
        """Stage the original queue, verify its playhead, then retire Radio IDs.

        Failure before deletion rolls back to the still-present Radio entries.
        Partial deletion is reported as failure and leaves recovery evidence
        available for a later retry; a success always has full readback proof.
        """
        def transact():
            if not guard():
                return False
            baseline = self.capture_queue_restore()
            staged = self._stage_files(list(snapshot['files']))
            if staged is None:
                return False
            old, added = staged
            if on_staged is not None:
                on_staged(added)
            added_ids = {str(row['id']) for row in added}
            def apply_head(value, rows):
                index = value['index']
                if index >= 0:
                    target = str(rows[index]['id'])
                    self.client.playid(target)
                    self.client.seekid(target, value['elapsed'])
                    if value['state'] == 'pause':
                        self.client.pause(1)
                if value['state'] == 'stop':
                    self.client.stop()
                self.client.random(int(value['random']))
            def head_matches(value, rows):
                status = self.client.status()
                if status.get('state') != value['state']:
                    return False
                if (str(status.get('random', '0')) == '1') != value['random']:
                    return False
                if value['index'] >= 0:
                    if str(status.get('songid')) != str(rows[value['index']]['id']):
                        return False
                    # MPD resets elapsed to zero for stopped playback.
                    if value['state'] != 'stop' and abs(float(status.get('elapsed', -100)) - value['elapsed']) > 2:
                        return False
                return True
            try:
                if not guard(added_ids):
                    self._remove_ids(added_ids)
                    return False
                apply_head(snapshot, added)
                if not head_matches(snapshot, added):
                    raise RuntimeError('Restored playhead could not be verified')
                if not guard(added_ids):
                    raise RuntimeError('Radio restoration cancelled before queue retirement')
            except Exception as exc:
                try:
                    rollback = head_matches(baseline, old)
                    if not rollback:
                        apply_head(baseline, old)
                        rollback = head_matches(baseline, old)
                except Exception:
                    rollback = False
                if rollback:
                    self._remove_ids(added_ids)
                self._error('Pre-Radio restoration failed; ' +
                            ('Radio playback restored' if rollback else 'playback needs reconciliation') +
                            ': ' + str(exc))
                return False
            if not self._remove_ids(row['id'] for row in old):
                return False
            rows = self._read_queue()
            return (rows is not None
                    and [row.get('file') for row in rows] == snapshot['files']
                    and head_matches(snapshot, rows))
        return self._structural(transact)

    def beacon_queue(self, kind, files, *, guard, current_id=None, start_index=0, on_staged=None):
        """Stage a Radio batch, then revalidate ownership before commitment.

        A failed/cancelled staging removes only newly allocated IDs. The
        original queue and playhead remain untouched until the guard passes.
        """
        def transact():
            if not guard():
                return False
            staged = self._stage_files(list(files))
            if staged is None:
                return False
            baseline, added = staged
            if on_staged is not None:
                on_staged(added)
            added_ids = {str(item['id']) for item in added}
            try:
                valid = guard(added_ids)
            except Exception:
                valid = False
            if not valid:
                self._remove_ids(added_ids)
                return False
            if kind == 'append':
                return True
            retained = str(current_id) if kind == 'replace-upcoming' else None
            if not self._remove_ids(row['id'] for row in baseline if str(row['id']) != retained):
                return False
            if kind == 'replace' and added:
                index = min(max(0, int(start_index)), len(added)-1)
                target = str(added[index]['id'])
                try:
                    self.client.playid(target)
                except (MPDConnectionError, OSError, CommandError):
                    pass
                return self._read_current_song_id() == target
            return True
        return self._structural(transact)

    def replace_upcoming(self, files, current_id) -> bool:
        """Keep the current song and replace every other queue entry."""
        files = tuple(str(file) for file in files)
        return self._structural(
            lambda: self._replace_upcoming(files, current_id))

    def _replace_upcoming(self, files, current_id) -> bool:
        files = list(files)
        staged = self._stage_files(files)
        if staged is None:
            return False
        baseline, _added = staged
        current_id = str(current_id)
        if not any(str(item["id"]) == current_id for item in baseline):
            self._remove_ids(item["id"] for item in _added)
            self._error("Playing song changed before the new queue was ready")
            return False
        return self._remove_ids(item["id"] for item in baseline
                                if str(item["id"]) != current_id)

    def reorder_window(self, song_ids, start_index) -> bool:
        """Converge one unchanged queue window to a stable-ID order.

        MPD command lists can apply only a prefix before their reply is lost.
        Each pass therefore starts from an authoritative snapshot and computes
        only the moves still required.  A membership or outside-window change
        aborts the transaction rather than moving an unrelated live row.
        """
        desired = tuple(str(song_id) for song_id in song_ids)
        return self._structural(
            lambda: self._reorder_window(desired, start_index))

    def _reorder_window(self, desired, start_index) -> bool:
        if not desired:
            return True
        if len(set(desired)) != len(desired):
            self._error("Queue reorder received duplicate stable IDs")
            return False
        try:
            start = int(start_index)
        except (TypeError, ValueError):
            self._error("Queue reorder received an invalid position")
            return False

        baseline = self._read_queue()
        if baseline is None or start < 0 or start + len(desired) > len(baseline):
            self._error("Queue changed before it could be reordered")
            return False
        baseline_ids = tuple(str(item["id"]) for item in baseline)
        end = start + len(desired)
        if set(baseline_ids[start:end]) != set(desired):
            self._error("Queue changed before it could be reordered")
            return False
        prefix, suffix = baseline_ids[:start], baseline_ids[end:]
        current = baseline

        for _attempt in range(3):
            current_ids = tuple(str(item["id"]) for item in current)
            if (len(current_ids) != len(baseline_ids)
                    or current_ids[:start] != prefix
                    or current_ids[end:] != suffix
                    or set(current_ids[start:end]) != set(desired)):
                self._error("Queue changed during reordering — order was not applied")
                return False
            if current_ids[start:end] == desired:
                return True

            expected = list(current_ids)
            try:
                self.client.command_list_ok_begin()
                for offset, song_id in enumerate(desired):
                    target = start + offset
                    source = expected.index(song_id)
                    if source == target:
                        continue
                    self.client.moveid(song_id, target)
                    expected.insert(target, expected.pop(source))
                self.client.command_list_end()
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                # A partial command list is safe to reconcile because every
                # subsequent move is recomputed from fresh stable IDs.
                pass

            current = self._read_queue()
            if current is None:
                return False

        current_ids = tuple(str(item["id"]) for item in current)
        if current_ids[start:end] == desired:
            return True
        self._error("Queue order could not be verified")
        return False

    def append_files(self, files, *, error_prefix="") -> bool:
        """Append at most once; a lost reply must never duplicate the batch."""
        files = tuple(str(file) for file in files)
        return self._structural(
            lambda: self._append_files(files, error_prefix=error_prefix))

    def _append_files(self, files, *, error_prefix="") -> bool:
        files = list(files)
        if not files:
            return True
        if not self._ensure_connected(silent=True):
            self._error("Playback engine did not respond — try again")
            return False
        try:
            self.client.command_list_ok_begin()
            for file in files:
                self.client.add(file)
            self.client.command_list_end()
            return True
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
            message = "Playback engine connection changed — try again"
        except CommandError as exc:
            message = str(exc)
        self._error(f"{error_prefix}{message}")
        return False
