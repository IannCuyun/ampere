"""Qt-thread Beacon lifecycle; workers plan, queue transactions commit."""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
from PySide6.QtCore import QObject, Signal, QTimer
from .beacon import clean_sessions, local_edges, names, plan, INITIAL_COUNT, REFILL_COUNT, REFILL_AT
from .beacon_provider import MusicBrainzRelationships
from .paths import MUSIC_ROOT


class RadioRecovery:
    """Small durable journal; queue I/O and capture happen on the queue worker."""
    def __init__(self, path, *, predecessor=None):
        self.path = Path(path)
        self.lock = predecessor.lock if predecessor else threading.RLock()
        self.valid = True
        self.data = None
        self.unreadable = False
        self.rebind_after_restart = False
        self.pending_clear = bool(predecessor and (predecessor.pending_clear or predecessor.data is not None or predecessor.unreadable))
        if predecessor is not None:
            return
        try:
            value = json.loads(self.path.read_text())
            if value is not None:
                original = value['original']
                assert isinstance(original['files'], list)
                assert all(isinstance(f, str) and f for f in original['files'])
                assert isinstance(original['index'], int)
                assert -1 <= original['index'] < len(original['files']) or (not original['files'] and original['index'] == -1)
                assert original['state'] in ('play', 'pause', 'stop')
                assert isinstance(original['random'], bool)
                assert math.isfinite(float(original['elapsed'])) and original['elapsed'] >= 0
                assert original['state'] == 'stop' or original['index'] >= 0
                assert isinstance(value['expected'], list)
                self.data = value
                self.rebind_after_restart = True
        except FileNotFoundError:
            pass
        except Exception:
            self.unreadable = True

    def write(self, value):
        with self.lock:
            if not self.valid:
                raise RuntimeError('Radio ownership was cancelled')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w') as handle:
                json.dump(value, handle)
                handle.flush()
                os.fsync(handle.fileno())
            if not self.valid:
                temporary.unlink(missing_ok=True)
                raise RuntimeError('Radio ownership was cancelled')
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.data = copy.deepcopy(value)
            self.pending_clear = False
            self.unreadable = False

    def capture(self, playback):
        with self.lock:
            if self.unreadable:
                raise RuntimeError('Pre-Radio recovery evidence is unreadable')
            self.rebind(playback)
            current = playback.capture_queue_restore()
            if self.data is None:
                self.write({'original': current, 'expected': current['identity']})
            elif current['identity'] != self.data['expected']:
                raise RuntimeError('Radio no longer owns this queue; choose a normal queue before starting Radio')

    def reconcile(self, client, *, allowed=None):
        with self.lock:
            if self.valid and self.data is not None:
                rows = client.playlistinfo()
                identity = [[str(r['id']), r['file']] for r in rows]
                if allowed is not None:
                    actual = {tuple(row) for row in identity}
                    if identity != [list(row) for row in allowed if tuple(row) in actual]:
                        return
                # Keep verified identity usable in-process even if durable
                # storage fails after MPD has already committed the queue.
                self.data = {**self.data, 'expected': identity}
                self.write(self.data)

    def rebind(self, playback):
        """Daemon-owned song IDs can be regenerated during an app restart.

        A once-per-load full ordered-file match permits rebinding only the
        journal's Radio queue, never reconstructing a missing original.
        """
        with self.lock:
            if not self.rebind_after_restart or self.data is None:
                return
            current = playback.capture_queue_restore()
            if current['files'] != [row[1] for row in self.data['expected']]:
                raise RuntimeError('The recovered Radio queue no longer matches playback')
            self.write({**self.data, 'expected': current['identity']})
            self.rebind_after_restart = False

    def clear_if_unused(self):
        with self.lock:
            if self.valid and self.data is None:
                self.clear()

    def clear(self):
        with self.lock:
            self.write(None)



class BeaconController(QObject):
    ready = Signal(object)
    refreshed = Signal(object)

    def __init__(self, backend, values, cache_path):
        super().__init__(backend)
        self.backend = backend
        self.sessions = clean_sessions(values)
        self.selected_id = self.sessions[0]['id'] if self.sessions else ''
        self.active_id = ''
        self.busy = False
        self.status = ''
        self.token = threading.Event()
        self.generation = 0
        self.exhausted = False
        self.queue_identity = None
        self.provider = MusicBrainzRelationships(cache_path)
        self.network_busy = False
        self.restoring = False
        self.recovery = RadioRecovery(Path(cache_path).with_name('beacon-queue-recovery.json'))
        self.ready.connect(self._ready)
        self.refreshed.connect(self._refreshed)

    @property
    def selected(self):
        return copy.deepcopy(next((s for s in self.sessions if s['id'] == self.selected_id), {}))

    @property
    def active(self):
        return bool((self.active_id and self.active_id == self.selected_id)
                    or (not self.active_id and self.recovery.data is not None))

    def changed(self):
        self.backend.beaconChanged.emit()

    def cancel(self, reason='Radio paused after another playback choice', *, preserve=False):
        if not preserve:
            previous = self.recovery
            previous.valid = False
            replacement = RadioRecovery(previous.path, predecessor=previous)
            self.recovery = replacement
            if replacement.pending_clear:
                def clear_recovery():
                    try:
                        replacement.clear_if_unused()
                    except Exception:
                        self.backend.errorOccurred.emit('Radio recovery could not be cleared; disk state needs attention')
                if not self.backend._start_worker(clear_recovery, name='ampere-radio-recovery-clear'):
                    self.backend.errorOccurred.emit('Radio recovery clear could not start')
            self.restoring = False
        self.token.set()
        self.token = threading.Event()
        self.generation += 1
        was_owned = bool(self.active_id or self.busy)
        self.active_id = ''
        self.queue_identity = None
        self.busy = False
        if was_owned:
            self.status = reason
            self.changed()

    def exit(self):
        if self.restoring:
            return False
        had_ownership = bool(self.active_id)
        self.cancel('', preserve=True)
        self._exit_had_ownership = had_ownership
        self.restoring = True
        self.busy = True
        self.status = 'Restoring pre-Radio queue'
        self.changed()
        self._restore_when_idle(self.generation)
        return True

    def _restore_when_idle(self, generation):
        if generation != self.generation or not self.restoring:
            return
        b = self.backend
        if b._queue_mutations.active_owner:
            QTimer.singleShot(50, lambda: self._restore_when_idle(generation))
            return
        if self.recovery.data is None:
            actual = tuple(row['file'] for row in b._queue)
            legacy = any(actual == tuple(row['file'] for row in s['tracks']) for s in self.sessions)
            if self.recovery.unreadable or legacy or self._exit_had_ownership:
                self._restore_finished(generation, False, 'Pre-Radio queue is unavailable for this session')
            else:
                self._restore_finished(generation, True)
            return
        original = self.recovery.data['original']
        if any(file in b._disliked for file in original['files']):
            self._restore_finished(generation, False,
                'Pre-Radio queue contains disliked songs; restore them from Out of Rotation before exiting')
            return
        b._request_queue_intent('restore-radio', {
            'beaconOwner': True, 'radioRecovery': self.recovery,
            'cancelEvent': self.token, 'session': 'manual', 'manualQueueEdit': True,
        }, on_finished=lambda success: self._restore_finished(generation, success))

    def _restore_finished(self, generation, success, message=''):
        if generation != self.generation:
            return
        self.restoring = False
        self.busy = False
        self.status = ('Pre-Radio queue restored' if success else
                       message or 'Pre-Radio restoration failed; recovery is retained. Try Exit again.')
        self.changed()
        if success:
            self.backend.navRequested.emit('now', '')
        else:
            self.backend.errorOccurred.emit(self.status)

    def _fingerprint(self):
        return tuple((str(s.get('id')), s.get('file')) for s in self.backend._queue)

    def _blocked(self):
        b = self.backend
        return bool(b._repeat or getattr(b, '_single', False) or b._dj_on)

    def _legacy_without_original(self):
        actual = tuple(row['file'] for row in self.backend._queue)
        return self.recovery.data is None and any(
            actual == tuple(row['file'] for row in session['tracks']) for session in self.sessions)

    def start(self):
        b = self.backend
        if self._legacy_without_original():
            self.status = 'Pre-Radio queue is unavailable; choose a normal queue before starting another Radio'
            self.changed()
            return False
        seed = copy.deepcopy(b._song)
        if not seed.get('file') or str(seed.get('id', '-1')) == '-1':
            self.status = 'Play a song to start Radio'
            self.changed()
            return False
        if self._blocked():
            self.status = 'Turn off Loop or end the DJ session to start Radio'
            self.changed()
            return False
        if self.restoring:
            return False
        self.cancel('', preserve=True)
        self.exhausted = False
        session = {'id': uuid.uuid4().hex, 'title': str(seed.get('title') or 'Song') + ' Radio',
                   'seed': seed, 'tracks': [{**seed, 'reason': 'Original seed'}], 'createdAt': time.time()}
        return self._plan(session, initial=True)

    def open(self, identity):
        if any(s['id'] == identity for s in self.sessions):
            self.selected_id = identity
            self.changed()
            return True
        return False

    def resume(self, identity, index=0):
        b = self.backend
        if self._legacy_without_original():
            self.status = 'Pre-Radio queue is unavailable; choose a normal queue before resuming Radio'
            self.changed()
            return False
        session = copy.deepcopy(next((s for s in self.sessions if s['id'] == identity), {}))
        if not session or self._blocked() or not 0 <= index < len(session['tracks']):
            return False
        available = {s['file'] for s in b._library.songs}
        if any(t['file'] not in available or t['file'] in b._disliked for t in session['tracks']):
            self.status = 'This sequence contains unavailable or disliked songs'
            self.changed()
            return False
        if self.restoring:
            return False
        self.cancel('', preserve=True)
        generation = self.generation
        self.busy = True
        self.status = 'Resuming Radio'
        self.selected_id = identity
        self.exhausted = False
        self.changed()
        request = {'files': tuple(t['file'] for t in session['tracks']), 'startIndex': index,
                   'session': 'beacon', 'beaconOwner': True, 'queueContext': 'radio',
                   'radioRecovery': self.recovery, 'cancelEvent': self.token, 'beaconGuard': {'queue': self._fingerprint()}}
        return b._request_queue_intent('replace', request, on_finished=lambda success: self._committed(
            generation, session, success, '', False))

    def play(self, index):
        session = self.selected
        if not session or not 0 <= index < len(session['tracks']):
            return False
        file = session['tracks'][index]['file']
        if self.active:
            row = next((t for t in self.backend._queue if t['file'] == file), None)
            if row:
                return self.backend._request_queue_intent('jump', {'songId': row['id'], 'beaconOwner': True})
        return self.resume(self.selected_id, index)

    def save(self, name):
        session = self.selected
        if not session:
            return False
        return self.backend._request_generated_playlist_save('beacon', name,
            [t['file'] for t in session['tracks']])

    def save_finished(self, success):
        self.status = 'Playlist saved' if success else 'Playlist could not be saved; choose an unused name'
        self.changed()

    def tick(self):
        if not (self.active_id or self.busy):
            return
        if self._blocked() or (self.active_id and getattr(self.backend, '_random', False)):
            self.cancel()
            return
        if not self.active_id or self.busy:
            return
        b = self.backend
        session = next((s for s in self.sessions if s['id'] == self.active_id), None)
        if not session:
            self.cancel()
            return
        expected = tuple(t['file'] for t in session['tracks'])
        actual = tuple(t['file'] for t in b._queue)
        # Queue refresh may lag our successful transaction; defer until its
        # already-scheduled authoritative read has completed.
        if getattr(b, '_queue_refresh_busy', False):
            return
        if actual != expected:
            self.cancel('Radio paused because the queue changed')
            return
        identity = self._fingerprint()
        if self.queue_identity is not None and identity != self.queue_identity:
            self.cancel('Radio paused because the queue changed')
            return
        self.queue_identity = identity
        if self.exhausted:
            return
        if b._state == 'play' and 0 <= b._queue_pos and len(actual)-1-b._queue_pos <= REFILL_AT:
            self._plan(copy.deepcopy(session), initial=False)

    def _plan(self, session, *, initial):
        b = self.backend
        self.busy = True
        self.status = 'Finding fitting songs'
        self.changed()
        generation, token = self.generation, self.token
        fingerprint = self._fingerprint()
        def present(song):
            path = Path(MUSIC_ROOT) / song['file']
            return path.is_file() and path.resolve().is_relative_to(Path(MUSIC_ROOT).resolve())
        songs = tuple(copy.deepcopy(s) for s in b._library.songs)
        # Filesystem validation is part of the worker, never Qt input handling.
        energies, bpms = dict(b._library_energies), dict(b._library_bpms)
        disliked = tuple(b._disliked)
        artists = {}
        for song in songs:
            credits = names(song)
            ids = song.get('musicbrainz_artistid') or []
            ids = ids if isinstance(ids, (list, tuple)) else [ids]
            for artist in credits:
                artists.setdefault(artist, set())
            if len(credits) == 1:
                artists[credits[0]].update(ids)
        # Seed roots first, then local direct associates; bounded external
        # refresh improves later generation without rewriting accepted rows.
        roots = names(session['seed'])
        graph = local_edges(songs)
        ordering = list(dict.fromkeys([*roots, *(a for r in roots for a in graph.get(r, {})), *artists]))
        artists = {a: artists.get(a, set()) for a in ordering}
        def work():
            try:
                playable = tuple(s for s in songs if present(s))
                cached = self.provider.relationships(artists, token, refresh=initial)
                for source, targets in cached.items():
                    graph.setdefault(source, {}).update(targets)
                rows, status = plan(session['seed'], playable, energies, bpms,
                    edges=graph, previous=session['tracks'][-1], used=session['tracks'],
                    disliked=disliked, count=min(INITIAL_COUNT if initial else REFILL_COUNT,
                                                10000 - len(session["tracks"])))
                payload = {'rows': rows, 'status': status}
            except Exception:
                payload = {'rows': [], 'status': 'Radio planning failed; playback is unchanged'}
            self.ready.emit({**payload, 'generation': generation, 'session': session,
                             'initial': initial, 'fingerprint': fingerprint, 'artists': artists})
        if b._start_worker(work, name='ampere-beacon-plan'):
            return True
        self.busy = False
        self.status = 'Radio could not start while Ampere is closing'
        self.changed()
        return False

    def _ready(self, payload):
        b = self.backend
        if payload['generation'] != self.generation:
            return
        self.busy = False
        if self.token.is_set() or self._blocked() or payload['fingerprint'] != self._fingerprint():
            self.cancel('Radio cancelled because playback changed')
            return
        session, rows = payload['session'], payload['rows']
        if payload['initial'] and (str(b._song.get('id')) != str(session['seed'].get('id'))
                                   or b._song.get('file') != session['seed'].get('file')):
            self.cancel('Radio cancelled because the playing song changed')
            return
        if not rows:
            self.status = payload['status']
            self.exhausted = True
            self.changed()
            if not payload['initial']:
                self._refresh(payload['artists'])
            return
        session['tracks'].extend(rows)
        self.busy = True
        guard = {'queue': payload['fingerprint']}
        request = {'files': tuple(r['file'] for r in rows), 'beaconOwner': True,
                   'radioRecovery': self.recovery, 'cancelEvent': self.token, 'beaconGuard': guard, 'session': 'beacon',
                   'preserveQueueContext': True}
        if payload['initial']:
            guard['songId'] = str(session['seed']['id'])
            guard['file'] = session['seed']['file']
            request['currentId'] = session['seed']['id']
        result = b._request_queue_intent('replace-upcoming' if payload['initial'] else 'append', request,
            on_finished=lambda success: self._committed(payload['generation'], session, success,
                                                        payload['status'], payload['initial']))
        if not payload['initial']:
            self._refresh(payload['artists'])
        return result

    def _committed(self, generation, session, success, status, initial):
        if generation != self.generation:
            return
        self.busy = False
        if not success:
            self.status = 'Radio could not update the queue; playback was reconciled'
            self.exhausted = True
            self.changed()
            return
        b = self.backend
        self.sessions = clean_sessions([session, *(s for s in self.sessions if s['id'] != session['id'])])
        if initial or not self.active_id:
            self.selected_id = session['id']
        self.active_id = session['id']
        self.queue_identity = None
        self.status = status or 'Radio is playing'
        self.exhausted = bool(status)
        if len(session['tracks']) >= 10000:
            self.exhausted = True
            self.status = 'Radio reached its sequence limit; start another Radio'
        b._sessions.set_radio(False)
        b._sync_session_state()
        b._defined_queue_active = False
        b._defined_queue_kind = 'radio'
        b._defined_queue_files = ()
        b._set_context_shuffle_mode('off')
        b._autoplay_generation = getattr(b, '_autoplay_generation', 0) + 1
        result = b._settings.try_patch({'beacon_sessions': self.sessions})
        if not b._handle_settings_save_result(result):
            self.status = 'Radio is playing; recent history could not be saved'
        self.changed()
        if initial:
            b.navRequested.emit('radio', '')

    def _refresh(self, artists):
        if self.network_busy:
            return
        self.network_busy = True
        token, generation = self.token, self.generation
        def work():
            before = copy.deepcopy(self.provider.cache)
            try:
                self.provider.relationships(artists, token, refresh=True)
            finally:
                self.refreshed.emit({'generation': generation,
                                     'changed': before != self.provider.cache})
        if not self.backend._start_worker(work, name='ampere-beacon-evidence'):
            self.network_busy = False

    def _refreshed(self, payload):
        self.network_busy = False
        if (isinstance(payload, dict) and payload.get('generation') == self.generation
                and payload.get('changed') and self.active_id):
            self.exhausted = False
