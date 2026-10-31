"""Bounded MusicBrainz relationship evidence; never a playable-track source."""
from __future__ import annotations
import json
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .persistence import atomic_write_json

# Artist-to-artist performance relationships only. No labels, membership,
# geography, shared URLs or stylistic inference can establish collaboration.
ALLOWED_RELATIONSHIPS = frozenset({'collaboration', 'supporting musician', 'vocal supporting musician', 'instrumental supporting musician'})


class MusicBrainzRelationships:
    _lock = threading.Lock()
    _last_request = 0.0
    TTL = 30 * 86400
    MAX_REQUESTS = 8
    MAX_CACHE = 256

    def __init__(self, path, *, fetch=None, clock=time.time):
        self.path = Path(path)
        self.fetch = fetch or self._fetch
        self.clock = clock
        try:
            value = json.loads(self.path.read_text())
            self.cache = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            self.cache = {}

    @staticmethod
    def _fetch(path):
        request = Request('https://musicbrainz.org/ws/2/' + path, headers={
            'User-Agent': 'Ampere/1.0 (Beacon Radio; iann.cuyun@pm.me)',
            'Accept': 'application/json'})
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with build_opener(NoRedirect).open(request, timeout=4) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError('MusicBrainz response exceeds evidence limit')
            return json.loads(payload)

    def _request(self, path, cancel):
        with self._lock:
            wait = max(0, 1.05 - (time.monotonic() - type(self)._last_request))
            if cancel.wait(wait):
                return None
            type(self)._last_request = time.monotonic()
            return self.fetch(path)

    @staticmethod
    def _valid_id(value):
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            return ''

    def relationships(self, artists, cancel, *, refresh=False):
        """Resolve exact identities and bounded two-hop performance evidence."""
        graph, budget = {}, self.MAX_REQUESTS
        def request(path):
            nonlocal budget
            if budget <= 0 or cancel.is_set():
                return {}
            budget -= 1
            result = self._request(path, cancel)
            return result if isinstance(result, dict) else {}
        def cache_entry(key):
            value = self.cache.get(key, {})
            return value if isinstance(value, dict) else {}
        def resolve(name):
            ids = {self._valid_id(v) for v in artists.get(name, ())} - {''}
            if len(ids) > 1:
                return ''
            if ids:
                return next(iter(ids))
            entry = cache_entry('name:' + name)
            identity = self._valid_id(entry.get('id'))
            if identity or not refresh:
                return identity
            data = request('artist/?' + urlencode({'query': 'artist:"' + name.replace('"', '') + '"', 'fmt': 'json', 'limit': 100}))
            exact = [a for a in data.get('artists', []) if isinstance(a, dict) and str(a.get('name', '')).casefold() == name.casefold()]
            if int(data.get('count', 0)) > 100 or len(exact) != 1:
                return ''
            identity = self._valid_id(exact[0].get('id'))
            if identity:
                self.cache['name:' + name] = {'id': identity, 'retrievedAt': self.clock()}
            return identity
        pending = [(name, 0) for name in artists]
        visited = set()
        while pending and not cancel.is_set():
            name, depth = pending.pop(0)
            if name in visited:
                continue
            visited.add(name)
            try:
                identity = resolve(name)
                if not identity:
                    continue
                entry = cache_entry(identity)
                try:
                    valid = self.clock() - float(entry.get('retrievedAt', 0)) < self.TTL
                except (TypeError, ValueError):
                    valid = False
                if refresh and not valid and budget > 0:
                    data = request('artist/' + identity + '?inc=artist-rels&fmt=json')
                    if data.get('id') != identity:
                        continue
                    relations = []
                    for relation in data.get('relations', []):
                        if not isinstance(relation, dict):
                            continue
                        target = relation.get('artist') or {}
                        if relation.get('type') in ALLOWED_RELATIONSHIPS and isinstance(target, dict):
                            relations.append({'name': str(target.get('name', '')).casefold(), 'id': self._valid_id(target.get('id')), 'edgeType': relation['type']})
                    # MusicBrainz artist credits, rather than stylistic tags,
                    # expose real co-performances on recordings. One bounded
                    # browse page is evidence, never an exhaustive assertion.
                    if budget > 0:
                        data = request('recording/?' + urlencode({'artist': identity, 'inc': 'artist-credits', 'fmt': 'json', 'limit': 100}))
                        for recording in data.get('recordings', []):
                            if not isinstance(recording, dict):
                                continue
                            raw_credits = recording.get('artist-credit', [])
                            if not isinstance(raw_credits, list):
                                continue
                            credits = [c['artist'] for c in raw_credits
                                       if isinstance(c, dict) and isinstance(c.get('artist'), dict)]
                            if identity not in {c.get('id') for c in credits}:
                                continue
                            for target in credits:
                                if target.get('id') != identity:
                                    relations.append({'name': str(target.get('name', '')).casefold(), 'id': self._valid_id(target.get('id')), 'edgeType': 'recording co-credit', 'recordingId': recording.get('id')})
                    entry = {'id': identity, 'retrievedAt': self.clock(), 'relations': relations[:200]}
                    self.cache[identity] = entry
                relations = entry.get('relations', [])
                if not isinstance(relations, list):
                    continue
                for relation in relations:
                    if not isinstance(relation, dict):
                        continue
                    target = relation.get('name', '')
                    if (target not in artists or not relation.get('id')
                            or relation.get('edgeType') not in ALLOWED_RELATIONSHIPS | {'recording co-credit'}):
                        continue
                    target_identity = resolve(target)
                    if target_identity != relation['id']:
                        continue
                    graph.setdefault(name, {})[target] = {
                        'provider': 'MusicBrainz', 'edgeType': relation['edgeType'],
                        'confidence': 1.0, 'retrievedAt': entry.get('retrievedAt'),
                        'sourceId': identity, 'targetId': relation['id'],
                        'recordingId': relation.get('recordingId')}
                    if depth < 1 and target not in visited:
                        pending.insert(0, (target, depth+1))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
        if refresh and not cancel.is_set():
            def stamp(row):
                try:
                    return float(row[1].get('retrievedAt', 0))
                except (AttributeError, TypeError, ValueError):
                    return 0
            self.cache = dict(sorted(self.cache.items(), key=stamp, reverse=True)[:self.MAX_CACHE])
            try:
                atomic_write_json(self.path, self.cache)
            except OSError:
                pass
        return graph
