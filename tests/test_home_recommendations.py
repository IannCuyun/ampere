import unittest
from datetime import datetime
from ampere.home import listening_recommendations


class HomeRecommendationsTests(unittest.TestCase):
    def setUp(self):
        self.library = {f'A/{a}/{i}.flac': {
            'file': f'A/{a}/{i}.flac', 'album': a, 'artist': 'A',
            'title': str(i), 'genre': 'Rock'}
            for a in ('Old', 'New', 'Unheard', 'Hidden') for i in range(2)}
        self.args = dict(library=self.library, counts={'A/Old/0.flac': 12},
                         last_played={}, liked=['A/Old/0.flac'],
                         disliked=['A/Hidden/0.flac'], entries=[],
                         arrivals=[self.library['A/New/0.flac']],
                         now=datetime(2026, 10, 31, 12).timestamp())

    def cards(self):
        return [c for s in listening_recommendations(**self.args) for c in s['cards']]

    def test_month_uses_complete_calendar_month_not_rolling_thirty_days(self):
        self.args['entries'] = [(datetime(2026, 9, 1, 12).timestamp(), 'A/Old/0.flac'),
                                (datetime(2026, 10, 1).timestamp(), 'A/New/0.flac')]
        awards = self.cards()[:2]
        self.assertEqual(awards[0]['kind'], 'song')
        self.assertEqual(awards[0]['file'], 'A/Old/0.flac')
        self.assertIn('September 2026', awards[0]['reason'])
        self.assertEqual(awards[1]['album'], 'Old')

    def test_unheard_uses_events_as_well_as_stickers_and_excludes_dislikes(self):
        self.args['entries'] = [(self.args['now'] - 60, 'A/Unheard/0.flac')]
        cards = self.cards()
        self.assertFalse(any(c['album'] == 'Hidden' for c in cards))
        self.assertFalse(any(c['album'] == 'Unheard' and 'unheard' in c['label'] for c in cards))
        self.assertTrue(any(c['label'] == 'Recent & underplayed' for c in cards))

    def test_repeat_builds_are_stable_and_dont_mutate_inputs(self):
        self.assertEqual(self.cards(), self.cards())
        self.assertNotIn('label', self.library['A/New/0.flac'])

    def test_no_history_does_not_fabricate_favorites_or_affinity(self):
        self.args.update(counts={}, liked=[], arrivals=[])
        self.assertTrue(self.cards())
        self.assertTrue(all(c['label'] == 'Explore your library' for c in self.cards()))

    def test_no_library_is_empty(self):
        self.args['library'] = {}
        self.assertEqual(self.cards(), [])
