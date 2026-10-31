"""Pure, deterministic Beacon Radio selection and bounded history validation."""
from __future__ import annotations

import copy
import math
from .artists import credited_artists
from .versions import VersionPolicy

INITIAL_COUNT = 25
REFILL_COUNT = 15
REFILL_AT = 5


def names(song):
    return tuple(name.casefold() for name in credited_artists(song.get('artist', '')))


def recording_keys(song):
    keys = set()
    value = song.get('musicbrainz_trackid') or song.get('musicbrainz_recordingid')
    for item in value if isinstance(value, (list, tuple)) else [value]:
        if item:
            keys.add(('recording', str(item)))
    sibling = VersionPolicy.key(song)
    if sibling:
        keys.add(('sibling', *sibling))
    return keys


def clean_sessions(values):
    if not isinstance(values, (list, tuple)):
        return []
    result, seen = [], set()
    for raw in values:
        if not isinstance(raw, dict):
            continue
        identity = str(raw.get('id') or '')
        seed = raw.get('seed')
        tracks = raw.get('tracks')
        if (not identity or identity in seen or not isinstance(seed, dict)
                or not seed.get('file') or not isinstance(tracks, list)
                or not tracks or len(tracks) > 10000 or any(not isinstance(t, dict) or not t.get('file') for t in tracks)):
            continue
        try:
            created = float(raw.get('createdAt', 0))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(created):
            continue
        seen.add(identity)
        result.append({'id': identity, 'title': str(raw.get('title') or seed.get('title') or 'Radio'),
                       'seed': copy.deepcopy(seed), 'tracks': copy.deepcopy(tracks),
                       'createdAt': created})
    return sorted(result, key=lambda item: item['createdAt'], reverse=True)[:3]


def local_edges(songs):
    """Only explicit recording co-credits establish local collaboration."""
    edges = {}
    for song in songs:
        credits = names(song)
        for left in credits:
            for right in credits:
                if left != right:
                    edges.setdefault(left, {}).setdefault(right, {
                        'provider': 'local credits', 'edgeType': 'co-credit',
                        'confidence': 1.0, 'retrievedAt': None,
                        'recording': song.get('file', '')})
    return edges


def plan(seed, songs, energies, bpms, *, edges=None, previous=None, used=(), disliked=(), count=25):
    """Tier first, hard sonic gates inside every tier; no unknown-fit padding.

    Seed tempo tolerance widens from 10% to at most 25%; energy .20 to .30
    over 40 admitted songs. Adjacent songs remain within 12% BPM / .20 energy.
    Half/double tempo folding handles metrical analysis ambiguity; energy is
    always independently gated.
    """
    def features(song):
        try:
            energy, bpm = float(energies[song['file']]), float(bpms[song['file']])
            return (energy, bpm) if (math.isfinite(energy) and 0 <= energy <= 1
                                    and math.isfinite(bpm) and bpm > 0) else None
        except (KeyError, TypeError, ValueError):
            return None
    anchor = features(seed)
    last = features(previous or seed)
    if anchor is None or last is None:
        return [], 'Audio analysis is required for the seed and previous song'
    graph = edges if edges is not None else local_edges(songs)
    roots = set(names(seed)[:1])
    direct, second = {}, {}
    for root in sorted(roots):
        for artist, evidence in graph.get(root, {}).items():
            if artist not in roots:
                direct.setdefault(artist, evidence)
    for artist in sorted(direct):
        for target, evidence in graph.get(artist, {}).items():
            if target not in roots and target not in direct:
                second.setdefault(target, {'via': artist, **evidence})
    genre_values = seed.get('genres') or [seed.get('genre')]
    genres = {str(g).casefold() for g in genre_values if g}
    forbidden = set(disliked)
    excluded = {seed['file'], *forbidden}
    keys = recording_keys(seed)
    for song in [*used, *(s for s in songs if s.get('file') in forbidden)]:
        excluded.add(song['file'])
        keys.update(recording_keys(song))
    pool = []
    for song in songs:
        file = song.get('file')
        sonic = features(song)
        if not file or file in excluded or sonic is None or recording_keys(song) & keys:
            continue
        artists = set(names(song))
        if artists & roots:
            tier, evidence = 1, {'provider': 'local credits', 'edgeType': 'seed artist', 'confidence': 1.0, 'retrievedAt': None}
        elif artists & direct.keys():
            tier, evidence = 2, direct[sorted(artists & direct.keys())[0]]
        elif artists & second.keys():
            tier, evidence = 3, second[sorted(artists & second.keys())[0]]
        elif genres & {str(g).casefold() for g in (song.get('genres') or [song.get('genre')]) if g}:
            tier, evidence = 4, {'provider': 'embedded tags', 'edgeType': 'genre', 'confidence': 1.0, 'retrievedAt': None}
        else:
            continue
        pool.append((song, sonic, tier, evidence))
    selected = []
    for offset in range(count):
        width = min(1.0, (max(0, len(used) - 1) + offset) / 40)
        energy_width = .20 + .10 * width
        tempo_width = .10 + .15 * width
        fitting = []
        for song, sonic, tier, evidence in pool:
            if song['file'] in excluded or recording_keys(song) & keys:
                continue
            energy, bpm = sonic
            anchor_tempo = min(abs(bpm * factor / anchor[1] - 1) for factor in (.5, 1, 2))
            previous_tempo = min(abs(bpm * factor / last[1] - 1) for factor in (.5, 1, 2))
            if (abs(energy - anchor[0]) > energy_width + 1e-9
                    or anchor_tempo > tempo_width + 1e-9
                    or abs(energy - last[0]) > .20 + 1e-9
                    or previous_tempo > .12 + 1e-9):
                continue
            score = abs(energy-last[0]) + previous_tempo
            fitting.append((tier, score, song['file'], song, sonic, evidence))
        if not fitting:
            break
        # Seed gets the largest share of opportunities; relationship tiers
        # interleave when they fit. Genre remains a last-resort fallback.
        desired = (1, 2, 1, 2, 1, 3)[(max(0, len(used)-1) + offset) % 6]
        preferred = [item for item in fitting if item[0] == desired]
        tier, _, _, song, last, evidence = min(preferred or fitting, key=lambda item: item[:3])
        row = copy.deepcopy(song)
        row['reason'] = ('Seed artist', 'Direct collaborator', 'Second-hop associate', 'Shared genre')[tier-1]
        row['provenance'] = {**evidence, 'tier': tier, 'bpm': last[1], 'energy': last[0]}
        selected.append(row)
        excluded.add(song['file'])
        keys.update(recording_keys(song))
    return selected, '' if len(selected) == count else 'No more fitting analyzed tracks; sequence kept shorter'
