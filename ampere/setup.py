"""Explicit first-install setup and read-only diagnostics; never starts services."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .compat import state_directory, audio_identity


def configured_music_root(home=None):
    path = state_directory('config', home) / 'library.json'
    try:
        value = json.loads(path.read_text())['music_directory']
        if isinstance(value, str) and Path(value).is_absolute():
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _quoted(value):
    value = str(value)
    if any(c in value for c in '\n\r\0'):
        raise ValueError('Paths must not contain line breaks or NUL characters')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def setup_plan(home, music, executable, data_dir, *, desktop=True):
    home, music = Path(home), Path(music).expanduser().resolve()
    if not music.is_dir():
        raise ValueError(f'Music directory does not exist: {music}')
    conf = home / '.config/mpd'
    state = home / '.local/state/ampere/mpd'
    config = '\n'.join([
        '# Created by ampere-setup; existing files are never overwritten.',
        f'music_directory {_quoted(music)}',
        f'playlist_directory {_quoted(state / "playlists")}',
        f'db_file {_quoted(state / "database")}',
        f'state_file {_quoted(state / "state")}',
        f'sticker_file {_quoted(state / "stickers")}',
        'bind_to_address "127.0.0.1"',
        f'bind_to_address {_quoted(conf / "socket")}',
        'port "6600"', 'restore_paused "yes"', 'auto_update "yes"',
        'audio_output {', '    type "pulse"', '    name "Ampere"',
        f'    sink {_quoted(audio_identity(home)[0])}', '}', '',
    ])
    files = {conf / 'mpd.conf': config.encode(),
             state_directory('config', home) / 'library.json':
             (json.dumps({'music_directory': str(music)}, indent=2) + '\n').encode()}
    if desktop:
        # Desktop Exec uses its own escaping rules, not shell quoting.
        command = str(executable)
        if any(c in command for c in '\n\r\0'):
            raise ValueError('Invalid executable path')
        command = command.replace('\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%')
        icon = home / '.local/share/icons/hicolor/512x512/apps/icon-ampere.png'
        files[icon] = (Path(data_dir) / 'branding/icon-ampere.png').read_bytes()
        files[home / '.local/share/applications/ampere.desktop'] = (
            '[Desktop Entry]\nType=Application\nName=Ampere\n'
            f'Exec="{command}"\nIcon=icon-ampere\nTerminal=false\n'
            'Categories=AudioVideo;Audio;Player;\nStartupWMClass=ampere\n').encode()
    return files, state / 'playlists'


def apply_plan(files, playlist_dir):
    # Check the complete plan before writing; repeat runs with identical inputs
    # are safe. Exclusive creation also prevents overwriting a concurrent writer.
    for path, contents in files.items():
        if path.is_symlink() or (path.exists() and path.read_bytes() != contents):
            raise FileExistsError(f'Refusing to replace existing file: {path}')
    made = []
    try:
        for path, contents in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Publish complete bytes atomically without replacing another
            # installer's file. Revalidate conflicts at publication time.
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())
                    try:
                        os.link(temporary, path)
                    except FileExistsError:
                        if path.is_symlink() or path.read_bytes() != contents:
                            raise FileExistsError(f'Refusing to replace existing file: {path}')
                    else:
                        made.append((path, path.stat().st_ino))
                finally:
                    temporary.unlink(missing_ok=True)
        playlist_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        for path, inode in reversed(made):
            if path.exists() and not path.is_symlink() and path.stat().st_ino == inode:
                path.unlink()
        raise
    return [path for path, _inode in made]


def diagnose():
    failures = 0
    for command in ('mpd', 'mpc', 'ffmpeg', 'ffprobe', 'pactl', 'pipewire',
                    'pw-cli', 'pw-dump', 'pw-metadata', 'systemctl'):
        found = shutil.which(command)
        print(f'{"OK" if found else "MISSING"} {command}' + (f': {found}' if found else ''))
        failures += not bool(found)
    root = configured_music_root() or os.path.expanduser('~/MusicLibrary')
    from .compat import environment
    root = os.path.expanduser(environment('MUSIC_ROOT', root))
    for label, path in [('music directory', Path(root)),
                        ('MPD configuration', Path.home() / '.config/mpd/mpd.conf')]:
        good = path.exists()
        print(f'{"OK" if good else "MISSING"} {label}: {path}')
        failures += not good
    for unit in ('mpd.service', 'filter-chain.service'):
        try:
            result = subprocess.run(['systemctl', '--user', 'cat', unit],
                                    capture_output=True, timeout=5)
            good = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            good = False
        print(f'{"OK" if good else "UNAVAILABLE"} user service: {unit}')
        failures += not good
    for label, command in (
            ('PipeWire PulseAudio connection', ['pactl', 'info']),
            ('desktop session bus', ['dbus-send', '--session', '--print-reply',
             '--dest=org.freedesktop.DBus', '/org/freedesktop/DBus',
             'org.freedesktop.DBus.ListNames'])):
        try:
            good = subprocess.run(command, capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            good = False
        print(f'{"OK" if good else "UNAVAILABLE"} {label}')
        failures += not good
    return int(bool(failures))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doctor', action='store_true', help='Check prerequisites without changing anything')
    parser.add_argument('--music-dir', type=Path, help='Existing local music folder')
    parser.add_argument('--no-desktop', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.doctor:
        return diagnose()
    if args.music_dir is None:
        parser.error('--music-dir is required for setup; use --doctor for diagnostics')
    executable = Path(sys.executable).parent / 'ampere'
    data = Path(sys.prefix) / 'share/ampere'
    if not data.is_dir():
        data = Path(__file__).resolve().parent.parent
    try:
        files, playlists = setup_plan(Path.home(), args.music_dir, executable, data,
                                     desktop=not args.no_desktop)
        if args.dry_run:
            for path in files:
                print(f'Would create (never overwrite): {path}')
            return 0
        made = apply_plan(files, playlists)
    except (OSError, ValueError) as exc:
        print(f'Ampere setup: {exc}', file=sys.stderr)
        return 1
    print(f'Setup complete: {len(made)} files created. No services were started.')
    print('Run ampere-setup --doctor, then ampere. In Settings, use Rescan to index your music.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
