"""Run Ampere's Python suite without access to the listener's live MPD."""

from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LIVE_MPD_SOCKET = Path.home() / ".config" / "mpd" / "socket"
LOOPBACK_NAMES = frozenset(("127.0.0.1", "::1", "localhost"))
ISOLATED_ENV_KEYS = (
    "AMPERE_MPD_HOST",
    "AMPERE_MPD_PORT",
    "AMPERE_MUSIC_ROOT",
)


class LiveMpdAccessError(ConnectionRefusedError):
    """A test attempted to cross the live-listening boundary."""


def is_live_mpd_address(address) -> bool:
    """Return whether a socket target is Ampere's production MPD endpoint."""
    if isinstance(address, (str, bytes, os.PathLike)):
        try:
            return Path(os.fsdecode(address)).expanduser() == LIVE_MPD_SOCKET
        except (TypeError, ValueError):
            return False
    if isinstance(address, tuple) and len(address) >= 2:
        host, port = address[0], address[1]
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False
        return str(host).lower() in LOOPBACK_NAMES and port == 6600
    return False


def guarded_connect(real_connect):
    """Wrap ``socket.connect`` with a narrow live-MPD deny rule."""
    def connect(sock, address):
        if is_live_mpd_address(address):
            raise LiveMpdAccessError(
                f"Ampere test isolation blocked live MPD endpoint: {address!r}")
        return real_connect(sock, address)

    return connect


def configure_isolated_environment(directory: str | os.PathLike) -> None:
    """Point all environment-aware MPD/library reads at empty test state."""
    root = Path(directory)
    music = root / "music"
    music.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "AMPERE_MPD_HOST": str(root / "mpd-unavailable.socket"),
        "AMPERE_MPD_PORT": "0",
        "AMPERE_MUSIC_ROOT": str(music),
    })


def main() -> int:
    """Discover and execute the canonical Python gate under isolation."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    previous_env = {key: os.environ.get(key) for key in ISOLATED_ENV_KEYS}
    original_connect = socket.socket.connect
    try:
        with TemporaryDirectory(prefix="ampere-test-isolation-") as directory:
            configure_isolated_environment(directory)
            socket.socket.connect = guarded_connect(original_connect)
            suite = unittest.defaultTestLoader.discover(
                str(TESTS), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            return 0 if result.wasSuccessful() else 1
    finally:
        socket.socket.connect = original_connect
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
