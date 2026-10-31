import unittest
import io
import socket
import time
from unittest.mock import patch

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from ampere.mpdclient import Backend
from ampere.playback import PlaybackVolumeResult
from ampere.remote import (RemoteCommand, RemoteCommandRegistry,
                          RemoteControlService, RemoteServer, _Handler, _MPD,
                          _PAGE, request_authorized, request_origin_allowed)


class ClientStub:
    def __init__(self):
        self.disconnected = 0

    def disconnect(self):
        self.disconnected += 1

    def ping(self):
        raise MPDConnectionError("reply lost")


class RemoteMpdTests(unittest.TestCase):
    def test_private_remote_adapter_has_no_mutation_api(self):
        self.assertFalse(hasattr(_MPD, "write_once"))
        self.assertFalse(hasattr(_MPD, "replace_queue"))

    def test_command_errors_are_not_retried(self):
        mpd = _MPD()
        mpd._client = ClientStub()
        calls = []

        def invalid(_client):
            calls.append(True)
            raise CommandError("bad command")

        with self.assertRaises(CommandError):
            mpd.call(invalid)
        self.assertEqual(len(calls), 1)
        self.assertEqual(mpd._client.disconnected, 0)

    def test_read_still_reconnects_once_after_transport_loss(self):
        first = ClientStub()
        second = object()
        mpd = _MPD()
        mpd._client = first
        mpd._connect = lambda: second
        calls = []

        def read(current):
            calls.append(current)
            if current is first:
                raise MPDConnectionError("stale")
            return "fresh"

        self.assertEqual("fresh", mpd.call(read))
        self.assertEqual([first, second], calls)

class RemoteQueueIdentityTests(unittest.TestCase):
    def handler(self):
        class Client:
            def __init__(self):
                self.played = []

            def playid(self, song_id):
                self.played.append(song_id)

        class Mpd:
            def __init__(self):
                self.client = Client()

            def write_once(self, fn):
                return fn(self.client)

        handler = object.__new__(_Handler)
        mpd = Mpd()
        commands = []
        handler.path = "/api/jump"
        handler.client_address = ("127.0.0.1", 1234)
        handler.server = type("Server", (), {
            "auth_token": "secret", "mpd": mpd,
            "commands": RemoteCommandRegistry(commands.append),
        })()
        return handler, mpd, commands

    def dispatch(self, handler, body):
        encoded = body.encode()
        handler.headers = {
            "Host": "127.0.0.1:8480", "Origin": "",
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        handler.rfile = io.BytesIO(encoded)
        responses = []
        handler._json = lambda value, code=200: responses.append((value, code))
        handler.do_POST()
        return responses

    def test_jump_submits_stable_song_id_without_remote_mpd_write(self):
        handler, mpd, commands = self.handler()
        responses = self.dispatch(handler, '{"id": 42, "pos": 3}')
        self.assertEqual([], mpd.client.played)
        self.assertEqual("jump", commands[0].action)
        self.assertEqual({"songId": 42}, commands[0].payload)
        self.assertEqual("queued", responses[-1][0]["status"])
        self.assertEqual(202, responses[-1][1])

    def test_position_only_jump_is_rejected_without_mutation(self):
        handler, mpd, commands = self.handler()
        responses = self.dispatch(handler, '{"pos": 3}')
        self.assertEqual([], mpd.client.played)
        self.assertEqual([], commands)
        self.assertEqual(400, responses[-1][1])

    def test_playnow_submits_one_transactional_backend_command(self):
        handler, mpd, commands = self.handler()
        handler.path = "/api/playnow"

        responses = self.dispatch(handler, '{"file": "Album/song.flac"}')

        self.assertEqual([], mpd.client.played)
        self.assertEqual("play-now", commands[0].action)
        self.assertEqual({"file": "Album/song.flac"}, commands[0].payload)
        self.assertEqual(202, responses[-1][1])

    def test_queue_payload_and_embedded_ui_use_stable_identity(self):
        handler = object.__new__(_Handler)

        class Catalog:
            def status(self):
                return {"song": "0"}

            def playlistinfo(self, _window):
                return [{
                    "id": "42", "pos": "3", "file": "song.flac",
                    "title": "Song", "artist": "Artist",
                }]

        handler.server = type("Server", (), {
            "mpd": type("Mpd", (), {
                "call": lambda _self, fn: fn(Catalog()),
            })(),
        })()
        self.assertEqual(42, handler._queue()[0]["id"])
        self.assertIn("post('/api/jump', { id: it.id })", _PAGE)


class RemoteAuthorizationTests(unittest.TestCase):
    def test_loopback_is_trusted_without_a_token(self):
        self.assertTrue(request_authorized("127.0.0.1", "secret"))
        self.assertTrue(request_authorized("::1", "secret"))
        self.assertTrue(request_authorized(
            "127.0.0.1", "secret", host="localhost:8480"))
        self.assertTrue(request_authorized(
            "::1", "secret", host="[::1]:8480"))

    def test_loopback_trust_rejects_a_dns_rebound_host(self):
        self.assertFalse(request_authorized(
            "127.0.0.1", "secret", host="attacker.example"))
        self.assertTrue(request_authorized(
            "127.0.0.1", "secret", host="attacker.example",
            header="secret"))

    def test_non_loopback_requires_the_exact_token(self):
        self.assertFalse(request_authorized("192.0.2.4", "secret"))
        self.assertFalse(request_authorized("192.0.2.4", "secret",
                                            header="wrong"))
        self.assertTrue(request_authorized("192.0.2.4", "secret",
                                           header="secret"))
        self.assertTrue(request_authorized("192.0.2.4", "secret",
                                           query="secret"))
        self.assertTrue(request_authorized(
            "192.0.2.4", "secret", cookie="other=x; ampere_token=secret"))

    def test_non_loopback_is_closed_when_server_has_no_token(self):
        self.assertFalse(request_authorized("192.0.2.4", ""))

    def test_pairing_query_is_removed_from_browser_history(self):
        self.assertIn("history.replaceState(null, '', location.pathname)", _PAGE)

    def test_browser_mutations_require_same_origin(self):
        self.assertTrue(request_origin_allowed("", "127.0.0.1:8480"))
        self.assertTrue(request_origin_allowed(
            "http://127.0.0.1:8480", "127.0.0.1:8480"))
        self.assertFalse(request_origin_allowed(
            "https://evil.example", "127.0.0.1:8480"))
        self.assertFalse(request_origin_allowed("null", "127.0.0.1:8480"))

    def test_loopback_mutation_rejects_non_json_before_dispatch(self):
        handler = object.__new__(_Handler)
        handler.path = "/api/next"
        handler.client_address = ("127.0.0.1", 1234)
        handler.server = type("Server", (), {"auth_token": "secret"})()
        handler.headers = {
            "Host": "127.0.0.1:8480", "Origin": "https://evil.example",
            "Content-Type": "application/json",
            "Content-Length": "2",
        }
        responses = []
        handler._json = lambda body, code=200: responses.append((body, code))

        handler.do_POST()
        handler.headers["Origin"] = ""
        handler.headers["Content-Type"] = "text/plain"
        handler.do_POST()

        self.assertEqual([403, 415], [response[1] for response in responses])

    def test_dns_rebound_loopback_mutation_is_rejected_before_dispatch(self):
        handler = object.__new__(_Handler)
        handler.path = "/api/next"
        handler.client_address = ("127.0.0.1", 1234)
        moves = []
        handler.server = type("Server", (), {
            "auth_token": "secret", "move_cb": moves.append,
        })()
        body = b"{}"
        handler.headers = {
            "Host": "attacker.example",
            "Origin": "http://attacker.example",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        responses = []
        handler._json = lambda value, code=200: responses.append((value, code))

        handler.do_POST()

        self.assertEqual([], moves)
        self.assertEqual(401, responses[-1][1])

    def test_feature_navigation_reaches_the_router(self):
        for mode in ("ampy", "discover", "artist"):
            with self.subTest(mode=mode):
                handler = object.__new__(_Handler)
                handler.path = "/api/nav"
                handler.client_address = ("127.0.0.1", 1234)
                navigations = []
                handler.server = type("Server", (), {
                    "auth_token": "secret",
                    "nav_cb": staticmethod(
                        lambda m, a: navigations.append((m, a))),
                })()
                body = ('{"mode":"' + mode + '"}').encode()
                handler.headers = {
                    "Host": "127.0.0.1:8480", "Origin": "",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                handler.rfile = io.BytesIO(body)
                responses = []
                handler._json = lambda value, code=200: responses.append(
                    (value, code))

                handler.do_POST()

                self.assertEqual([(mode, "")], navigations)
                self.assertEqual(200, responses[-1][1])

    def test_responses_include_browser_security_policy(self):
        handler = object.__new__(_Handler)
        headers = {}
        handler.send_response = lambda _code: None
        handler.send_header = lambda name, value: headers.__setitem__(name, value)
        handler.end_headers = lambda: None
        handler.wfile = type("Writer", (), {"write": lambda _self, _body: None})()

        handler._send(200, b"ok", "text/plain")

        self.assertEqual("DENY", headers["X-Frame-Options"])
        self.assertIn("frame-ancestors 'none'",
                      headers["Content-Security-Policy"])
        self.assertEqual("camera=(), microphone=(), geolocation=()",
                         headers["Permissions-Policy"])

    def test_volume_dispatches_through_app_callback_when_available(self):
        handler = object.__new__(_Handler)
        commands = []
        handler.path = "/api/volume"
        handler.client_address = ("127.0.0.1", 1234)
        handler.server = type("Server", (), {
            "auth_token": "secret",
            "commands": RemoteCommandRegistry(commands.append),
        })()
        body = b'{"value": 64}'
        handler.headers = {
            "Host": "127.0.0.1:8480", "Origin": "",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        responses = []
        handler._json = lambda value, code=200: responses.append((value, code))

        handler.do_POST()

        self.assertEqual("volume", commands[0].action)
        self.assertEqual({"value": 64}, commands[0].payload)
        self.assertEqual(202, responses[-1][1])

    def test_play_target_dispatches_through_app_callback_when_available(self):
        handler = object.__new__(_Handler)
        commands = []
        handler.path = "/api/play"
        handler.client_address = ("127.0.0.1", 1234)
        handler.server = type("Server", (), {
            "auth_token": "secret",
            "commands": RemoteCommandRegistry(commands.append),
        })()
        body = b'{"playlist": "Drive", "shuffle": true}'
        handler.headers = {
            "Host": "127.0.0.1:8480", "Origin": "",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        responses = []
        handler._json = lambda value, code=200: responses.append((value, code))

        handler.do_POST()

        self.assertEqual("play-target", commands[0].action)
        self.assertEqual(
            {"playlist": "Drive", "shuffle": True}, commands[0].payload)
        self.assertEqual(202, responses[-1][1])

    def test_transport_dispatches_through_verified_app_callback(self):
        for path, expected in (("/api/play", "play"),
                               ("/api/pause", "toggle")):
            with self.subTest(path=path):
                handler = object.__new__(_Handler)
                commands = []
                handler.path = path
                handler.client_address = ("127.0.0.1", 1234)
                handler.server = type("Server", (), {
                    "auth_token": "secret",
                    "commands": RemoteCommandRegistry(commands.append),
                })()
                body = b'{}'
                handler.headers = {
                    "Host": "127.0.0.1:8480", "Origin": "",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                handler.rfile = io.BytesIO(body)
                handler._json = lambda _value, code=200: None

                handler.do_POST()

                self.assertEqual("transport", commands[0].action)
                self.assertEqual(expected, commands[0].payload["action"])


class RemoteCommandLifecycleTests(unittest.TestCase):
    def test_registry_exposes_queued_admitted_and_committed_states(self):
        dispatched = []
        registry = RemoteCommandRegistry(dispatched.append)

        command = registry.submit("volume", {"value": 64})
        self.assertEqual("queued", registry.snapshot(command.id)["status"])
        self.assertFalse(registry.snapshot(command.id)["accepted"])

        self.assertTrue(dispatched[0].admit())
        self.assertEqual("admitted", registry.snapshot(command.id)["status"])
        self.assertTrue(registry.snapshot(command.id)["accepted"])
        self.assertFalse(registry.snapshot(command.id)["committed"])

        self.assertTrue(dispatched[0].finish(True))
        self.assertEqual("committed", registry.snapshot(command.id)["status"])
        self.assertTrue(registry.snapshot(command.id)["committed"])

    def test_registry_close_fails_every_uncommitted_command(self):
        dispatched = []
        registry = RemoteCommandRegistry(dispatched.append)
        queued = registry.submit("seek", {"seconds": 5})
        admitted = registry.submit("jump", {"songId": 9})
        admitted.admit()

        registry.close()

        self.assertEqual("failed", queued.snapshot()["status"])
        self.assertEqual("failed", admitted.snapshot()["status"])
        self.assertIn("closed", admitted.snapshot()["message"])

    def test_registry_close_preserves_explicit_indeterminate_truth(self):
        registry = RemoteCommandRegistry(lambda _command: None)
        command = registry.submit("play-now", {"file": "one.flac"})
        command.admit()
        command.mark_indeterminate("MPD stopped before readback")

        registry.close()

        self.assertEqual("indeterminate", command.snapshot()["status"])
        self.assertTrue(command.snapshot()["accepted"])
        self.assertEqual(
            "MPD stopped before readback", command.snapshot()["message"])

    def test_http_mutation_dispatch_has_no_private_mpd_write_fallback(self):
        import inspect
        source = inspect.getsource(_Handler.do_POST)
        self.assertNotIn("self._mpd", source)
        self.assertIn("_dispatch_command", source)
        self.assertIn("/api/playnow", source)

    def test_embedded_page_polls_eventual_command_failure(self):
        self.assertIn("/api/commands/", _PAGE)
        self.assertIn("command.status === 'failed'", _PAGE)
        self.assertIn("command.status === 'indeterminate'", _PAGE)
        self.assertIn('aria-live="polite"', _PAGE)
        self.assertIn("const delay = (attempts || 0) < 80 ? 250 : 2000", _PAGE)
        self.assertIn("if (!r.ok) throw new Error", _PAGE)
        self.assertNotIn("Command is still pending", _PAGE)


class BackendRemoteCommandTests(unittest.TestCase):
    def test_previous_remote_command_uses_shared_threshold_policy(self):
        backend = type("BackendHarness", (), {})()
        callbacks = []
        backend._request_previous_action = lambda **kwargs: (
            callbacks.append(kwargs["on_finished"]) or True)
        command = RemoteCommand("move", {"command": "previous"})

        self.assertTrue(Backend._on_remote_command_requested(backend, command))
        self.assertEqual("admitted", command.snapshot()["status"])

        callbacks[0](True)
        self.assertEqual("committed", command.snapshot()["status"])

    def test_queue_command_is_admitted_before_worker_commit(self):
        backend = type("BackendHarness", (), {})()
        callbacks = []
        backend._request_queue_intent = lambda kind, request, **kwargs: (
            callbacks.append((kind, request, kwargs["on_finished"])) or True)
        command = RemoteCommand("queue-append", {"file": "one.flac"})

        self.assertTrue(Backend._on_remote_command_requested(backend, command))
        self.assertEqual("admitted", command.snapshot()["status"])
        self.assertEqual(("one.flac",), callbacks[0][1]["files"])

        callbacks[0][2](True)
        self.assertEqual("committed", command.snapshot()["status"])

    def test_rejected_queue_command_surfaces_eventual_failure(self):
        backend = type("BackendHarness", (), {})()
        def reject(_kind, _request, **kwargs):
            kwargs["on_finished"](False)
            return False
        backend._request_queue_intent = reject
        command = RemoteCommand("play-now", {"file": "one.flac"})

        self.assertFalse(Backend._on_remote_command_requested(backend, command))

        self.assertEqual("failed", command.snapshot()["status"])
        self.assertTrue(command.snapshot()["accepted"])

    def test_play_now_enters_the_manual_session_boundary(self):
        backend = type("BackendHarness", (), {})()
        admitted = []
        backend._request_queue_intent = lambda kind, request, **kwargs: (
            admitted.append((kind, request, kwargs["on_finished"])) or True)
        command = RemoteCommand("play-now", {"file": "one.flac"})

        self.assertTrue(Backend._on_remote_command_requested(backend, command))

        self.assertEqual("play-now", admitted[0][0])
        self.assertEqual("manual", admitted[0][1]["session"])
        self.assertEqual("admitted", command.snapshot()["status"])
        admitted[0][2](True)
        self.assertEqual("committed", command.snapshot()["status"])

    def test_shutdown_indeterminate_play_now_is_not_mislabeled_failed(self):
        backend = type("BackendHarness", (), {})()
        admitted = []
        backend._request_queue_intent = lambda kind, request, **kwargs: (
            admitted.append(kwargs["on_finished"]) or True)
        registry = RemoteCommandRegistry(lambda command: (
            Backend._on_remote_command_requested(backend, command)))
        command = registry.submit("play-now", {"file": "one.flac"})

        admitted[0](None)
        registry.close()

        self.assertEqual("indeterminate", command.snapshot()["status"])
        self.assertTrue(command.snapshot()["accepted"])

    def test_playback_failure_completes_the_same_command_ticket(self):
        backend = type("BackendHarness", (), {})()
        completions = []
        backend._request_playback_intent = lambda key, request, **kwargs: (
            completions.append(kwargs["on_finished"]) or True)
        command = RemoteCommand("volume", {"value": 72})

        self.assertTrue(Backend._on_remote_command_requested(backend, command))
        self.assertEqual("admitted", command.snapshot()["status"])
        completions[0](False, "MPD rejected the volume")

        self.assertEqual("failed", command.snapshot()["status"])
        self.assertEqual("MPD rejected the volume", command.snapshot()["message"])


class RemoteLifecycleTests(unittest.TestCase):
    def test_loopback_bind_is_mandatory_before_overlay_bind(self):
        attempts = []

        def refuse_loopback(address, _handler):
            attempts.append(address[0])
            if address[0] == "127.0.0.1":
                raise OSError("occupied")
            self.fail("overlay must not start without loopback")

        remote = RemoteServer(auth_token="secret")
        with patch("ampere.remote._RemoteHttpServer",
                   side_effect=refuse_loopback):
            with self.assertRaisesRegex(OSError, "loopback"):
                remote.start(hosts=["100.64.0.8"], port=8480)

        self.assertEqual(["127.0.0.1"], attempts)
        self.assertEqual([], remote._servers)

    def test_disconnected_client_is_reaped_before_idempotent_stop_returns(self):
        remote = RemoteServer(auth_token="secret")
        remote.start(hosts=["127.0.0.1"], port=0)
        httpd, server_thread = remote._servers[0]
        port = httpd.server_address[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            client.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            # Closing without reading forces the server's response path to
            # tolerate a reset instead of leaving a socket writer behind.
        for _ in range(20):
            workers = getattr(httpd, "_threads", ())
            if not any(worker.is_alive() for worker in workers):
                break
            time.sleep(0.01)

        remote.stop()
        remote.stop()

        self.assertFalse(server_thread.is_alive())
        self.assertFalse(any(worker.is_alive()
                             for worker in getattr(httpd, "_threads", ())))


class RemoteControlServiceTests(unittest.TestCase):
    class Result:
        returncode = 0
        stdout = "100.64.0.8\n"

    class Server:
        def __init__(self, **values):
            self.values = values
            self.starts = []
            self.stops = 0

        def start(self, **values):
            self.starts.append(values)

        def stop(self):
            self.stops += 1

    def test_tailscale_address_drives_bind_set_and_pairing_url(self):
        servers = []

        def factory(**values):
            server = self.Server(**values)
            servers.append(server)
            return server

        command_events = []
        command_cb = command_events.append
        service = RemoteControlService(
            auth_token="a/b", command_cb=command_cb,
            server_factory=factory,
            run=lambda *_args, **_values: self.Result())

        self.assertTrue(service.start())
        self.assertTrue(service.start())
        self.assertEqual(
            [{"hosts": ["127.0.0.1", "100.64.0.8"], "port": 8480}],
            servers[0].starts,
        )
        self.assertEqual("http://100.64.0.8:8480/?token=a%2Fb", service.url)
        self.assertIs(command_cb, servers[0].values["command_cb"])
        service.stop()
        service.stop()
        self.assertEqual(1, servers[0].stops)

    def test_failed_start_is_cleaned_and_reported(self):
        errors = []

        class BrokenServer(self.Server):
            def start(self, **_values):
                raise OSError("occupied")

        server = BrokenServer()
        service = RemoteControlService(
            auth_token="secret", error=errors.append,
            server_factory=lambda **_values: server,
            run=lambda *_args, **_values: self.Result())

        self.assertFalse(service.start())
        self.assertFalse(service.running)
        self.assertEqual(1, server.stops)
        self.assertIn("occupied", errors[0])

    def test_failed_tailscale_lookup_remains_local_only_and_is_cached(self):
        calls = []
        failed = type("Result", (), {"returncode": 1, "stdout": ""})()
        service = RemoteControlService(
            auth_token="secret",
            run=lambda *_args, **_values: calls.append(True) or failed)

        self.assertEqual("127.0.0.1", service.resolve_address())
        self.assertEqual("127.0.0.1", service.resolve_address())
        self.assertEqual([True], calls)

    def test_non_overlay_command_output_is_rejected(self):
        for output in ("192.168.1.20\n", "203.0.113.9\n", "not-an-ip\n",
                       "fd7a:115c:a1e0::1\n", ""):
            with self.subTest(output=output):
                result = type("Result", (), {
                    "returncode": 0, "stdout": output,
                })()
                servers = []
                service = RemoteControlService(
                    auth_token="secret",
                    server_factory=lambda **_values: servers.append(
                        self.Server(**_values)) or servers[-1],
                    run=lambda *_args, **_values: result)

                self.assertTrue(service.start())
                self.assertEqual(
                    [{"hosts": ["127.0.0.1"], "port": 8480}],
                    servers[0].starts,
                )
                self.assertEqual(
                    "http://127.0.0.1:8480/?token=secret", service.url)
                service.stop()


class BackendRemotePairingTests(unittest.TestCase):
    class Control:
        def __init__(self, starts=True):
            self.starts = 0
            self.stops = 0
            self.start_result = starts
            self.running = False

        def start(self):
            self.starts += 1
            self.running = self.start_result
            return self.running

        def stop(self):
            self.stops += 1
            self.running = False

    class Signal:
        def __init__(self):
            self.emits = 0

        def emit(self):
            self.emits += 1

    class PayloadSignal:
        def __init__(self):
            self.payloads = []

        def emit(self, payload):
            self.payloads.append(payload)

    def harness(self, saves, *, starts=True):
        backend = type("BackendHarness", (), {})()
        backend._remote_token_new = True
        backend._remote_on = False
        backend._remote_control = self.Control(starts)
        backend.settingsChanged = self.Signal()
        backend.errorOccurred = self.PayloadSignal()
        backend._remoteLifecycleReady = self.PayloadSignal()
        backend._remote_lifecycle_busy = False
        backend._remote_lifecycle_active = None
        backend._remote_lifecycle_pending = None
        backend._remote_lifecycle_generation = 0
        backend.save_results = iter(saves)
        backend._save_conf = lambda: next(backend.save_results)
        backend._persist_remote_token = lambda: (
            Backend._persist_remote_token(backend))
        backend._start_worker = lambda target, **_values: (target(), True)[1]
        backend._start_remote_lifecycle_request = lambda request: (
            Backend._start_remote_lifecycle_request(backend, request))
        backend._request_remote_lifecycle = lambda on: (
            Backend._request_remote_lifecycle(backend, on))
        return backend

    def test_failed_token_save_blocks_listener_and_remains_retryable(self):
        backend = self.harness([False, True])

        self.assertFalse(Backend._request_remote_lifecycle(backend, True))
        self.assertTrue(backend._remote_token_new)
        self.assertEqual(0, backend._remote_control.starts)

        self.assertTrue(Backend._request_remote_lifecycle(backend, True))
        self.assertFalse(backend._remote_token_new)
        self.assertEqual(1, backend._remote_control.starts)

    def test_explicit_enable_publishes_actual_start_result(self):
        backend = self.harness([True, True], starts=False)

        Backend.setRemoteOn(backend, True)

        payload = backend._remoteLifecycleReady.payloads.pop()
        Backend._on_remote_lifecycle_ready(backend, payload)

        self.assertFalse(backend._remote_on)
        self.assertEqual(1, backend._remote_control.starts)
        self.assertEqual(1, backend.settingsChanged.emits)

    def test_latest_toggle_runs_after_inflight_request(self):
        backend = self.harness([True, True, True])
        queued = []
        backend._start_worker = lambda target, **_values: (
            queued.append(target) or True)

        Backend.setRemoteOn(backend, True)
        Backend.setRemoteOn(backend, False)
        queued.pop(0)()
        first = backend._remoteLifecycleReady.payloads.pop(0)
        Backend._on_remote_lifecycle_ready(backend, first)
        queued.pop(0)()
        second = backend._remoteLifecycleReady.payloads.pop(0)
        Backend._on_remote_lifecycle_ready(backend, second)

        self.assertFalse(backend._remote_on)
        self.assertEqual(1, backend._remote_control.starts)
        self.assertEqual(1, backend._remote_control.stops)

    def test_remote_url_read_uses_cache_without_discovery(self):
        service = RemoteControlService(
            auth_token="hello world",
            run=lambda *_args, **_values: self.fail("discovery ran"))
        backend = type("BackendHarness", (), {"_remote_control": service})()

        self.assertEqual(
            "http://127.0.0.1:8480/?token=hello%20world",
            Backend.remoteUrl.fget(backend))


class BackendRemoteVolumeTests(unittest.TestCase):
    @staticmethod
    def backend(result):
        backend = type("BackendHarness", (), {})()
        backend._vol_device = "headphones"
        backend._device_vols = {"headphones": 40}
        backend._volume = 40
        backend.timer_starts = 0
        backend.status_emits = 0
        backend._conf_save_timer = type("Timer", (), {
            "start": lambda _self: setattr(
                backend, "timer_starts", backend.timer_starts + 1)})()
        backend.statusChanged = type("Signal", (), {
            "emit": lambda _self: setattr(
                backend, "status_emits", backend.status_emits + 1)})()
        backend._playback = type("Playback", (), {
            "set_volume": lambda _self, _value: result})()
        return backend

    def test_verified_volume_updates_active_device_memory(self):
        backend = self.backend(PlaybackVolumeResult(True, 64))

        Backend.setVolume(backend, 64)

        self.assertEqual(64, backend._device_vols["headphones"])
        self.assertEqual(64, backend._volume)
        self.assertEqual(1, backend.timer_starts)

    def test_rejected_volume_retains_device_memory_and_publishes_baseline(self):
        backend = self.backend(PlaybackVolumeResult(False, 40))

        Backend.setVolume(backend, 64)

        self.assertEqual(40, backend._device_vols["headphones"])
        self.assertEqual(40, backend._volume)
        self.assertEqual(0, backend.timer_starts)

    def test_device_switch_restores_memory_through_verified_volume_boundary(self):
        backend = type("BackendHarness", (), {})()
        backend._vol_device = "speakers"
        backend._volume = 40
        backend._device_vols = {"headphones": 64}
        backend.calls = []
        backend.setVolume = lambda value: backend.calls.append(value)
        backend._save_conf = lambda: backend.calls.append("save")

        Backend.deviceSwitched(backend, "headphones")

        self.assertEqual("headphones", backend._vol_device)
        self.assertEqual(40, backend._device_vols["speakers"])
        self.assertEqual([64, "save"], backend.calls)


class BackendRemotePlayTests(unittest.TestCase):
    class Signal:
        def __init__(self):
            self.messages = []

        def emit(self, message):
            self.messages.append(message)

    def harness(self):
        backend = type("BackendHarness", (), {})()
        backend.errorOccurred = self.Signal()
        backend.calls = []
        backend.plays = []
        backend._playlist_files = lambda name: [
            f"{name}/one.flac", "disliked.flac", f"{name}/two.flac"]
        backend._path_files = lambda path: [
            f"{path}/one.flac", f"{path}/target.flac", "disliked.flac"]
        backend._drop_disliked = lambda files, keep="": [
            file for file in files if file != "disliked.flac" or file == keep]
        backend._shuffle_order = lambda files: list(reversed(files))
        backend._call = lambda *args: backend.calls.append(args)
        backend._set_random_mode = lambda on: (
            backend.calls.append(("random", 1 if on else 0)) or True)
        backend._explicit_queue_request = lambda files, start, **_kwargs: {
            "files": tuple(files), "startIndex": start, "session": "manual",
        }
        def request_queue(kind, request, *, on_finished=None):
            self.assertEqual("replace", kind)
            backend.plays.append(
                (list(request["files"]), request["startIndex"]))
            if on_finished:
                on_finished(True)
            return True
        backend._request_soft_queue_intent = request_queue
        return backend

    def test_remote_callback_routes_resolution_off_thread(self):
        backend = self.harness()
        requests = []
        backend._request_remote_play = lambda request: \
            requests.append(dict(request)) or True

        self.assertTrue(Backend._on_remote_play_requested(
            backend, {"playlist": "Drive", "shuffle": True}))

        self.assertEqual(
            [{"playlist": "Drive", "shuffle": True}], requests)

    def test_remote_file_keeps_album_context_and_explicit_start(self):
        backend = self.harness()
        Backend._apply_remote_play(
            backend, {"file": "Album/target.flac"},
            ["Album/one.flac", "Album/target.flac", "disliked.flac"])
        self.assertEqual([
            (["Album/one.flac", "Album/target.flac"], 1)
        ], backend.plays)

    def test_remote_playlist_uses_house_shuffle_and_disliked_filter(self):
        backend = self.harness()
        Backend._apply_remote_play(
            backend, {"playlist": "Drive", "shuffle": True},
            ["Drive/one.flac", "disliked.flac", "Drive/two.flac"])
        self.assertEqual([], backend.calls)
        self.assertEqual([
            (["Drive/two.flac", "Drive/one.flac"], 0)
        ], backend.plays)

    def test_remote_shuffle_delegates_random_transaction_to_play_boundary(self):
        backend = self.harness()
        backend._set_random_mode = lambda _on: False

        Backend._apply_remote_play(
            backend, {"playlist": "Drive", "shuffle": True},
            ["Drive/one.flac", "disliked.flac", "Drive/two.flac"])

        self.assertEqual([
            (["Drive/two.flac", "Drive/one.flac"], 0)
        ], backend.plays)

    def test_remote_worker_uses_owned_client_for_playlist(self):
        backend = type("BackendHarness", (), {})()
        backend._remote_play_busy = False
        backend._remote_play_pending = None
        backend._remote_play_generation = 0
        backend._workers = object()
        emitted = []
        backend._remotePlayReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        client = type("Client", (), {
            "listplaylistinfo": lambda self, name: [
                {"file": f"{name}/one.flac"}],
        })()

        import contextlib
        from unittest.mock import patch

        @contextlib.contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            self.assertTrue(Backend._request_remote_play(
                backend, {"playlist": "Drive"}))

        self.assertTrue(emitted[0]["success"])
        self.assertEqual(("Drive/one.flac",), emitted[0]["files"])

    def test_superseded_remote_result_launches_latest_only(self):
        backend = type("BackendHarness", (), {})()
        backend._remote_play_busy = True
        backend._remote_play_pending = None
        backend._remote_play_generation = 4
        self.assertTrue(Backend._request_remote_play(
            backend, {"path": "Rap"}))
        launched = []
        backend._request_remote_play = lambda request: \
            launched.append(dict(request)) or True
        backend._launch_pending_remote_play = lambda: \
            Backend._launch_pending_remote_play(backend)
        backend._apply_remote_play = lambda *_args: self.fail(
            "superseded remote result must not play")

        Backend._on_remote_play_ready(backend, {
            "generation": 4, "request": {"playlist": "Old"},
            "kind": "playlist", "success": True,
            "files": ("Old/one.flac",),
        })

        self.assertEqual([{"path": "Rap"}], launched)

    def test_superseded_target_ticket_fails_while_latest_target_launches(self):
        backend = type("BackendHarness", (), {})()
        backend._remote_play_busy = True
        backend._remote_play_pending = None
        backend._remote_play_generation = 4
        old = RemoteCommand("play-target", {"playlist": "Old"})
        latest = RemoteCommand("play-target", {"path": "Rap"})
        old.admit()
        latest.admit()

        self.assertTrue(Backend._request_remote_play(
            backend, {"path": "Rap", "_remoteCommand": latest}))
        launched = []
        backend._request_remote_play = lambda request: (
            launched.append(request) or True)
        backend._launch_pending_remote_play = lambda: (
            Backend._launch_pending_remote_play(backend))

        Backend._on_remote_play_ready(backend, {
            "generation": 4,
            "request": {"playlist": "Old", "_remoteCommand": old},
            "kind": "playlist", "success": True,
            "files": ("Old/one.flac",),
        })

        self.assertEqual("failed", old.snapshot()["status"])
        self.assertIn("Superseded", old.snapshot()["message"])
        self.assertIs(latest, launched[0]["_remoteCommand"])

    def test_unavailable_remote_result_never_reaches_playback(self):
        backend = self.harness()
        backend._remote_play_generation = 2
        backend._remote_play_busy = True
        backend._remote_play_pending = None
        backend._launch_pending_remote_play = lambda: False
        backend._report_library_read = lambda success: \
            backend.calls.append(("library", success))
        backend._apply_remote_play = lambda *_args: self.fail(
            "unverified remote membership must not play")

        Backend._on_remote_play_ready(backend, {
            "generation": 2, "request": {"path": "Rap"},
            "kind": "path", "success": False, "files": (),
        })

        self.assertEqual([("library", False)], backend.calls)

    def test_explicit_file_degrades_to_direct_target_after_context_outage(self):
        backend = self.harness()
        backend._remote_play_generation = 3
        backend._remote_play_busy = True
        backend._remote_play_pending = None
        backend._launch_pending_remote_play = lambda: False
        backend._report_library_read = lambda success: \
            backend.calls.append(("library", success))
        backend._apply_remote_play = lambda request, files: \
            Backend._apply_remote_play(backend, request, files)

        Backend._on_remote_play_ready(backend, {
            "generation": 3, "request": {"file": "Album/target.flac"},
            "kind": "path", "success": True,
            "files": ("Album/target.flac",), "path": "Album",
            "degraded": True,
        })

        self.assertEqual([("library", False)], backend.calls)
        self.assertEqual(
            [(["Album/target.flac"], 0)], backend.plays)


if __name__ == "__main__":
    unittest.main()
