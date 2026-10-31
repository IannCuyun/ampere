"""Renaming must retain the same data and audio owner on existing installs."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ampere.compat import audio_identity, environment, state_directory


class IdentityCompatibilityTests(unittest.TestCase):
    def test_new_install_uses_ampere(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(state_directory('config', home), home / '.config/ampere')
            self.assertEqual(audio_identity(home)[0], 'ampere_eq')

    def test_existing_state_wins_without_copy_or_overwrite(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            for kind in ('config', 'cache'):
                old = home / f'.{kind}/esper'
                old.mkdir(parents=True)
                (old / 'proof').write_text('listening state')
                (home / f'.{kind}/ampere').mkdir()
                self.assertEqual(state_directory(kind, home), old)
                self.assertEqual((old / 'proof').read_text(), 'listening state')

    def test_existing_audio_route_is_preserved(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            old = home / '.config/pipewire/filter-chain.conf.d/esper-eq.conf'
            old.parent.mkdir(parents=True)
            old.write_text('existing chain')
            self.assertEqual(audio_identity(home), ('esper_eq', old))
            self.assertEqual(old.read_text(), 'existing chain')

    def test_new_environment_takes_precedence_and_old_still_works(self):
        with patch.dict(os.environ, {'ESPER_MPD_HOST': 'legacy'}, clear=True):
            self.assertEqual(environment('MPD_HOST'), 'legacy')
            os.environ['AMPERE_MPD_HOST'] = 'canonical'
            self.assertEqual(environment('MPD_HOST'), 'canonical')
