import os
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.run_isolated import (
    LIVE_MPD_SOCKET,
    LiveMpdAccessError,
    configure_isolated_environment,
    guarded_connect,
    is_live_mpd_address,
)


class MpdTestIsolationTests(unittest.TestCase):
    def test_known_live_endpoints_are_classified(self):
        targets = (
            str(LIVE_MPD_SOCKET),
            os.fsencode(LIVE_MPD_SOCKET),
            ("127.0.0.1", 6600),
            ("localhost", "6600"),
            ("::1", 6600, 0, 0),
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue(is_live_mpd_address(target))

    def test_non_mpd_sockets_remain_allowed(self):
        targets = (
            ("127.0.0.1", 8480),
            ("::1", 8480, 0, 0),
            "/tmp/ampere-test-private.socket",
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertFalse(is_live_mpd_address(target))

    def test_guard_fails_before_the_live_connector_runs(self):
        calls = []
        connect = guarded_connect(
            lambda _sock, address: calls.append(address) or "connected")

        with self.assertRaisesRegex(LiveMpdAccessError, "blocked live MPD"):
            connect(object(), str(LIVE_MPD_SOCKET))

        self.assertEqual([], calls)

    def test_guard_preserves_unrelated_loopback_connections(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        address = listener.getsockname()
        original_connect = socket.socket.connect
        try:
            with patch.object(
                    socket.socket, "connect",
                    new=guarded_connect(original_connect)):
                client = socket.create_connection(address, timeout=1)
                peer, _ = listener.accept()
                peer.close()
                client.close()
        finally:
            listener.close()

    def test_environment_is_private_before_module_discovery(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            configure_isolated_environment(directory)

            self.assertEqual(
                str(Path(directory) / "mpd-unavailable.socket"),
                os.environ["AMPERE_MPD_HOST"])
            self.assertEqual("0", os.environ["AMPERE_MPD_PORT"])
            self.assertEqual(
                str(Path(directory) / "music"),
                os.environ["AMPERE_MUSIC_ROOT"])


if __name__ == "__main__":
    unittest.main()
