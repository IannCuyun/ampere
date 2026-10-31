"""Beacon pure planning, provenance, persistence, and exact identity contracts."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from ampere.beacon import plan, local_edges, clean_sessions
from ampere.beacon_provider import MusicBrainzRelationships
from ampere.settings import SettingsRepository
from ampere.library import normalize_song


def song(file, artist='Travis Scott', title=None, genre='Hip Hop', **extra):
    return dict(file=file, artist=artist, title=title or file, album='Album', duration=180,
                genre=genre, genres=[genre], **extra)


class PlannerTests(unittest.TestCase):
    def test_actual_named_tempos_reject_mismatch_every_opening_tier(self):
        seed = song('FE!N')
        paranoid = song('Paranoid', 'Kanye West')
        credit = song('credit', 'Travis Scott, Kanye West')
        energies = {'FE!N': .743, 'Paranoid': .802}
        bpms = {'FE!N': 147.8, 'Paranoid': 115.0}
        rows, _ = plan(seed, [seed, paranoid, credit], energies, bpms)
        self.assertEqual([], rows)
        iknow = song('I KNOW?')
        energies['I KNOW?'], bpms['I KNOW?'] = .618, 118.2
        rows, _ = plan(iknow, [iknow, paranoid, credit], energies, bpms)
        self.assertEqual(['Paranoid'], [r['file'] for r in rows])
        self.assertEqual(2, rows[0]['provenance']['tier'])

    def test_missing_analysis_dislike_and_siblings_never_pass(self):
        seed = song('seed', title='Song')
        songs = [seed, song('remaster', title='Song (Remastered)'), song('unknown'), song('bad'), song('safe')]
        features = {s['file']: .7 for s in songs if s['file'] != 'unknown'}
        bpms = {s['file']: 120 for s in songs}
        rows, _ = plan(seed, songs, features, bpms, disliked=['bad'])
        self.assertEqual(['safe'], [r['file'] for r in rows])
        self.assertEqual([], plan(seed, songs, {}, bpms)[0])

    def test_guests_direct_not_seed_roots_and_tier_opportunities_interleave(self):
        seed = song('seed', 'Travis Scott, Playboi Carti')
        songs = [seed, *(song('travis'+str(i)) for i in range(5)),
                 song('carti', 'Playboi Carti'), song('unrelated', 'Other')]
        energies = {s['file']: .7 for s in songs}
        bpms = {s['file']: 140 for s in songs}
        rows, _ = plan(seed, songs, energies, bpms, count=3)
        self.assertEqual([1, 2, 1], [r['provenance']['tier'] for r in rows])

    def test_previous_song_gate_blocks_discontinuous_jump_even_after_widening(self):
        seed, prev, candidate = song('seed'), song('prev'), song('candidate')
        energies = {'seed': .6, 'prev': .4, 'candidate': .8}
        bpms = dict.fromkeys(energies, 120)
        rows, _ = plan(seed, [candidate], energies, bpms, previous=prev,
                       used=[song(str(i)) for i in range(50)])
        self.assertEqual([], rows)

    def test_ids_survive_normalization_and_recording_duplicates_excluded(self):
        a = song('a', musicbrainz_trackid='recording')
        b = song('b', title='Other billing', musicbrainz_trackid='recording')
        self.assertEqual('recording', normalize_song(a)['musicbrainz_trackid'])
        self.assertEqual([], plan(a, [a, b], {'a': .7, 'b': .7}, {'a': 120, 'b': 120})[0])


class PersistenceTests(unittest.TestCase):
    def test_fourth_evicts_oldest_and_full_shutdown_snapshot_roundtrips(self):
        sessions = [{'id': str(i), 'title': str(i), 'seed': song(str(i)),
                     'tracks': [song(str(i))], 'createdAt': i} for i in range(4)]
        with tempfile.TemporaryDirectory() as directory:
            repo = SettingsRepository(Path(directory) / 'settings.json')
            self.assertTrue(repo.try_patch({'beacon_sessions': sessions}).success)
            loaded = repo.load()
            self.assertEqual(['3', '2', '1'], [s['id'] for s in loaded['beacon_sessions']])
            self.assertTrue(repo.try_save(loaded).success)
            self.assertEqual(loaded['beacon_sessions'], repo.load()['beacon_sessions'])

    def test_malformed_history_rejected_and_seed_copies_are_independent(self):
        self.assertEqual([], clean_sessions([{'id':'x', 'seed': None}]))
        raw = [{'id':'x','seed':song('seed'),'tracks':[song('seed')], 'createdAt':1}]
        result = clean_sessions(raw)
        result[0]['seed']['title'] = 'changed'
        self.assertEqual('seed', raw[0]['seed']['title'])


class ProviderTests(unittest.TestCase):
    ROOT = '00000000-0000-0000-0000-000000000001'
    TARGET = '00000000-0000-0000-0000-000000000002'

    def test_exact_name_resolution_and_recording_credit_relationship(self):
        calls = []
        def fetch(path):
            calls.append(path)
            if 'query=' in path:
                artist = 'root' if 'root' in path else 'target'
                return {'count': 1, 'artists':[{'name':artist, 'id':self.ROOT if artist=='root' else self.TARGET}]}
            if path.startswith('recording/'):
                return {'recordings':[{'id':'recording', 'artist-credit':[{'artist':{'id':self.ROOT,'name':'root'}}, {'artist':{'id':self.TARGET,'name':'target'}}]}]}
            return {'id':self.ROOT if self.ROOT in path else self.TARGET, 'relations':[]}
        with tempfile.TemporaryDirectory() as directory:
            provider = MusicBrainzRelationships(Path(directory)/'cache.json', fetch=fetch)
            with patch.object(provider, '_request', side_effect=lambda path, cancel: fetch(path)):
                graph = provider.relationships({'root':set(), 'irrelevant':set(), 'target':set()}, threading.Event(), refresh=True)
            self.assertEqual('recording co-credit', graph['root']['target']['edgeType'])
            self.assertLessEqual(len(calls), provider.MAX_REQUESTS)
            self.assertEqual(graph['root']['target'], provider.relationships({'root':set(),'target':set()}, threading.Event())['root']['target'])

    def test_ambiguous_identity_and_labels_never_create_edges(self):
        def fetch(path):
            return {'count':2,'artists':[{'name':'root','id':self.ROOT},{'name':'root','id':self.TARGET}]}
        with tempfile.TemporaryDirectory() as directory:
            provider = MusicBrainzRelationships(Path(directory)/'cache.json', fetch=fetch)
            with patch.object(provider, '_request', side_effect=lambda path, cancel: fetch(path)):
                self.assertEqual({}, provider.relationships({'root':set()}, threading.Event(), refresh=True))
