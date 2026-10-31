"""Shared MPD + library constants — dependency-free so both the app
(mpdclient) and the DJ engine (dj.planner) import them without a cycle.

Extracted from mpdclient.py 2026-07-19 during the DJ planner extraction: the
moved planner methods reference HOST/PORT/MUSIC_ROOT as module globals, and a
back-import from mpdclient would be circular. This module imports nothing from
ampere, so it's safe for anyone to import.
"""
from ampere.compat import environment
import os
from ampere.setup import configured_music_root

# unix socket preferred: socket clients may play absolute paths (the DJ
# bridge renders live outside the library), and it's faster. TCP stays
# bound for mpc/remote; AMPERE_MPD_HOST still overrides everything.
MPD_SOCKET = os.path.expanduser("~/.config/mpd/socket")
HOST = environment("MPD_HOST") or (
    MPD_SOCKET if os.path.exists(MPD_SOCKET) else "127.0.0.1")
PORT = int(environment("MPD_PORT", "6600"))
MUSIC_ROOT = os.path.expanduser(environment(
    "MUSIC_ROOT", configured_music_root() or "~/MusicLibrary"))
