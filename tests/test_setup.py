import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import os
from ampere.setup import setup_plan, apply_plan, configured_music_root


class SetupTests(unittest.TestCase):
    def test_conflict_created_during_publication_is_preserved(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / 'config'
            def concurrent_create(source, destination):
                target.write_text('another writer')
                raise FileExistsError()
            with patch('ampere.setup.os.link', side_effect=concurrent_create):
                with self.assertRaises(FileExistsError):
                    apply_plan({target: b'ours'}, home / 'playlists')
            self.assertEqual('another writer', target.read_text())
            self.assertEqual([target], list(home.iterdir()))

    def test_failed_install_rolls_back_new_files_only(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            existing, new = home / 'existing', home / 'new'
            existing.write_bytes(b'kept')
            bad = home / 'not-a-directory'
            bad.write_text('keep')
            with self.assertRaises(FileExistsError):
                apply_plan({existing: b'kept', new: b'new'}, bad)
            self.assertEqual(b'kept', existing.read_bytes())
            self.assertFalse(new.exists())

    def test_first_install_is_repeatable_and_uses_selected_music(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            music = home / 'My Music'
            music.mkdir()
            files, playlists = setup_plan(home, music, '/venv/bin/ampere', home, desktop=False)
            self.assertEqual(2, len(apply_plan(files, playlists)))
            self.assertEqual([], apply_plan(files, playlists))
            self.assertEqual(str(music), configured_music_root(home))
            self.assertTrue(playlists.is_dir())
            text = (home / '.config/mpd/mpd.conf').read_text()
            self.assertIn('sink "ampere_eq"', text)
            self.assertIn('bind_to_address "127.0.0.1"', text)

    def test_existing_configuration_prevents_all_writes(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            files, playlists = setup_plan(home, home, '/venv/bin/ampere', home, desktop=False)
            config = home / '.config/mpd/mpd.conf'
            config.parent.mkdir(parents=True)
            config.write_text('existing user config')
            with self.assertRaises(FileExistsError):
                apply_plan(files, playlists)
            self.assertEqual('existing user config', config.read_text())
            self.assertFalse((home / '.config/ampere/library.json').exists())

    def test_invalid_music_directory_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                setup_plan(Path(tmp), Path(tmp) / 'absent', '/app', tmp, desktop=False)
            self.assertEqual([], list(Path(tmp).iterdir()))

    def test_legacy_state_root_and_malformed_settings(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            old = home / '.config/esper'
            old.mkdir(parents=True)
            path = old / 'library.json'
            path.write_text('broken')
            self.assertIsNone(configured_music_root(home))
            path.write_text(json.dumps({'music_directory': str(home)}))
            self.assertEqual(str(home), configured_music_root(home))

    def test_symlink_configuration_is_never_followed_for_write(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            files, playlists = setup_plan(home, home, '/app', home, desktop=False)
            config = home / '.config/mpd/mpd.conf'
            config.parent.mkdir(parents=True)
            target = home / 'target'
            target.write_bytes(files[config])
            config.symlink_to(target)
            with self.assertRaises(FileExistsError):
                apply_plan(files, playlists)
