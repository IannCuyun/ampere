# Ampere

*Everything you want to hear.*

A session-first local music player for Linux and for people who own their
music. MPD does the playing, a PySide6/QML face does the looking, and a
per-device parametric EQ lives directly in PipeWire — switch outputs and the
correction follows.

## What it does

- **Library as a place** — stable navigation across folders, albums, artists,
  editable playlists, album-led detail rooms, and computed shelves for new,
  forgotten, loved, and heavily played music.
- **Sessions, not just queues** — standard shuffle keeps the room you chose;
  smart shuffle builds a wider musical thread. Mood, character, mixtape, and
  rediscovery tools create sessions you can inspect and save.
- **Listening intelligence** — discovery-first planning favors unheard,
  rarely played, and long-absent music while duplicate versions, dislikes,
  artist spacing, energy, tempo, and verified gapless joins stay coherent.
- **Immersive playback** — Gallery Monolith Now Playing and Stillpoint Ambient
  give the complete album sleeve, waveform, synchronized lyrics, and adaptive
  album color enough room to matter.
- **Sound** — per-device parametric EQ, AutoEq import, loudness leveling,
  ReplayGain analysis, crossfades, and MixRamp-aware transitions live directly
  on the local PipeWire path.
- **Search and repair** — Unicode and romanized search, exact art and credit
  trust, reversible artist aliases, tag repair, and preferred-version tools
  keep a real-world library usable without rewriting its identity by guesswork.

## Install and run

Ampere targets Linux desktops with systemd user services and PipeWire.
Install Python 3.12+, MPD, mpc, ffmpeg, PipeWire and its PulseAudio tools using
your distribution's package manager. Then:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps .
.venv/bin/ampere-setup --music-dir "$HOME/Music"
.venv/bin/ampere-setup --doctor
.venv/bin/ampere
```

Use your actual music folder. Setup creates configuration and a desktop
launcher without overwriting existing files or starting services. See
[installation, service setup and troubleshooting](docs/INSTALL.md) for the
complete first-run path, existing installations, and upgrades.

Ampere is licensed under [GPLv3](LICENSE). See [copyright and warranty
information](COPYRIGHT) and [third-party dependency notices](THIRD_PARTY_NOTICES.md).
Source and releases: https://github.com/IannCuyun/ampere .

## Testing

Run the complete Python gate through Ampere's MPD-isolated discovery runner:

```bash
./.venv/bin/python tests/run_isolated.py
```

The runner redirects environment-aware clients to temporary empty state and
fails closed if any test attempts to connect to the listener's live MPD socket
or loopback port. Do not use raw `unittest discover` as a release gate while a
listening session exists. The QML gate uses the same PySide6/Qt runtime as the installed application:

```bash
./.venv/bin/python tests/run_qml.py
```

## Versioning

Semantic versioning from 1.0 onward, tagged in git, with human-written history
in [CHANGELOG.md](CHANGELOG.md). Feature ledger and design laws live in
[NOTES.md](NOTES.md).

### Core player release

Version 1.0.0 focuses on Home, Library and playback. The unfinished Features
tab is omitted while its tools are reviewed individually. Ampy is pending
rebranding and rework. Existing feature source is retained for development.
