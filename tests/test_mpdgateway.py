import unittest
import gc
import weakref

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from ampere.mpdgateway import (MpdGateway, close_all_mpd_clients,
                              close_mpd_client, create_mpd_client,
                              retire_mpd_writer,
                              temporary_mpd_client, tracked_mpd_clients)


class Client:
    def __init__(self):
        self.connected = False
        self.fail_once = False
        self.calls = []

    def connect(self, _host, _port):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def ping(self):
        if not self.connected:
            raise MPDConnectionError("gone")

    def status(self):
        self.calls.append("status")
        if self.fail_once:
            self.fail_once = False
            self.connected = False
            raise MPDConnectionError("gone")
        return {"state": "play"}

    def invalid(self):
        self.calls.append("invalid")
        raise CommandError("bad command")

    def next(self):
        self.calls.append("next")
        if self.fail_once:
            self.fail_once = False
            self.connected = False
            raise MPDConnectionError("reply lost")


class MpdGatewayTests(unittest.TestCase):
    def test_idle_writer_is_retired_before_socket_wakeup(self):
        events = []

        class Writer:
            def close(self): events.append("writer")

        client = type("IdleClient", (), {"_wfile": Writer()})()
        retire_mpd_writer(client)
        events.append("socket")

        self.assertEqual(["writer", "socket"], events)
        self.assertIsNone(client._wfile)

    def test_factory_tracks_clients_and_close_all_releases_transport(self):
        client = create_mpd_client(Client)
        self.assertIn(client, tracked_mpd_clients())
        client.connect("socket", 0)

        closed = close_all_mpd_clients()

        self.assertGreaterEqual(closed, 1)
        self.assertFalse(client.connected)

    def test_registry_retains_an_active_client_until_explicit_close(self):
        client = create_mpd_client(Client)
        client.connect("socket", 0)
        reference = weakref.ref(client)
        del client
        gc.collect()

        self.assertIsNotNone(reference())
        self.assertIn(reference(), tracked_mpd_clients())

        close_all_mpd_clients()
        gc.collect()
        self.assertIsNone(reference())

    def test_robust_close_finishes_after_a_writer_flush_failure(self):
        events = []

        class Part:
            def __init__(self, name, fail=False):
                self.name = name
                self.fail = fail

            def close(self):
                events.append(self.name)
                if self.fail:
                    raise BrokenPipeError("peer closed")

        class PartialClient:
            _rbfile = Part("reader")
            _wfile = Part("writer", fail=True)
            _sock = Part("socket")

            def _reset(self):
                events.append("reset")
                self._rbfile = self._wfile = self._sock = None

        client = PartialClient()
        close_mpd_client(client)

        self.assertEqual(["writer", "reader", "socket", "reset"], events)
        self.assertIsNone(client._wfile)

    def test_temporary_client_closes_after_successful_use(self):
        client = Client()

        with temporary_mpd_client("socket", 0, timeout=27,
                                  factory=lambda: client) as leased:
            self.assertIs(client, leased)
            self.assertTrue(client.connected)
            self.assertEqual(27, client.timeout)

        self.assertFalse(client.connected)

    def test_temporary_client_closes_when_work_raises(self):
        client = Client()

        with self.assertRaisesRegex(RuntimeError, "scan failed"):
            with temporary_mpd_client("socket", 0,
                                      factory=lambda: client):
                raise RuntimeError("scan failed")

        self.assertFalse(client.connected)

    def test_temporary_client_cleans_up_a_failed_connect(self):
        class FailedClient(Client):
            def connect(self, _host, _port):
                self.connected = True
                raise MPDConnectionError("handshake failed")

        client = FailedClient()
        with self.assertRaises(MPDConnectionError):
            with temporary_mpd_client("socket", 0,
                                      factory=lambda: client):
                self.fail("a failed connect must not yield")

        self.assertFalse(client.connected)

    def test_read_reconnects_once_after_a_stale_socket(self):
        client = Client()
        errors = []
        gateway = MpdGateway(client, "socket", 0, error=errors.append)
        self.assertTrue(gateway.ensure_connected())
        client.fail_once = True
        self.assertEqual({"state": "play"}, gateway.call("status"))
        self.assertEqual(["status", "status"], client.calls)
        self.assertEqual([], errors)

    def test_command_errors_fail_without_retry(self):
        client = Client()
        errors = []
        gateway = MpdGateway(client, "socket", 0, error=errors.append)
        self.assertIsNone(gateway.call("invalid"))
        self.assertEqual(["invalid"], client.calls)
        self.assertEqual(["bad command"], errors)

    def test_non_idempotent_write_is_not_replayed_after_lost_reply(self):
        client = Client()
        errors = []
        gateway = MpdGateway(client, "socket", 0, error=errors.append)
        self.assertTrue(gateway.ensure_connected())
        client.fail_once = True

        self.assertFalse(gateway.write_once("next"))

        self.assertEqual(["next"], client.calls)
        self.assertFalse(gateway.is_connected)
        self.assertEqual(1, len(errors))
        self.assertIn("may already be in effect", errors[0])

    def test_non_idempotent_write_reconnects_before_dispatch(self):
        client = Client()
        gateway = MpdGateway(client, "socket", 0)

        self.assertTrue(gateway.write_once("next"))

        self.assertEqual(["next"], client.calls)

    def test_quiet_write_suppresses_expected_command_error(self):
        client = Client()
        errors = []
        gateway = MpdGateway(client, "socket", 0, error=errors.append)
        self.assertFalse(gateway.write("invalid", quiet=True))
        self.assertEqual([], errors)

    def test_quiet_read_suppresses_expected_command_error(self):
        client = Client()
        errors = []
        gateway = MpdGateway(client, "socket", 0, error=errors.append)
        self.assertEqual("missing", gateway.call(
            "invalid", default="missing", quiet=True))
        self.assertEqual(["invalid"], client.calls)
        self.assertEqual([], errors)

    def test_observed_read_distinguishes_missing_from_transport_failure(self):
        client = Client()
        gateway = MpdGateway(client, "socket", 0)

        missing = gateway.observe("invalid", default="absent", missing_ok=True)
        self.assertTrue(missing.available)
        self.assertEqual("absent", missing.value)

        client.fail_once = True
        unavailable = gateway.observe("status", default={})
        # The ordinary one-time fault reconnects and remains authoritative.
        self.assertTrue(unavailable.available)
        client.status = lambda: (_ for _ in ()).throw(
            MPDConnectionError("offline"))
        unavailable = gateway.observe("status", default={})
        self.assertFalse(unavailable.available)
        self.assertEqual({}, unavailable.value)

    def test_close_releases_socket_files_without_publishing_a_state_change(self):
        client = Client()
        states = []
        gateway = MpdGateway(client, "socket", 0,
                             state_changed=states.append)
        self.assertTrue(gateway.ensure_connected())
        states.clear()

        gateway.close()
        gateway.close()

        self.assertFalse(client.connected)
        self.assertFalse(gateway.is_connected)
        self.assertEqual([], states)


if __name__ == "__main__":
    unittest.main()
