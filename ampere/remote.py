"""Ampere — tiny phone remote served from inside ampere.

A stdlib http.server ThreadingHTTPServer on a daemon thread exposing a
mobile single-page remote plus a small JSON API over MPD.

Threading: python-mpd2 clients have thread affinity, so this module NEVER
touches the app's client. It owns one private read-only MPDClient guarded by a
threading.Lock, reconnecting on error. Every mutation is submitted to the
application's asynchronous intent boundary and can be polled to commitment.

Security posture: loopback is trusted for local app/audit integration.
The only permitted non-loopback bind is a verified Tailscale IPv4 address, so
remote traffic stays inside the encrypted overlay. Non-loopback clients must
also present the persistent pairing token supplied by the integrator,
initially in the URL and subsequently in an HttpOnly cookie.
"""

from __future__ import annotations

from ampere.compat import cache_path
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from mpd import MPDClient
from mpd.base import CommandError, ConnectionError as MPDConnectionError

from .mpdgateway import close_mpd_client, create_mpd_client

ART_CACHE = Path(cache_path('art'))
MAX_BODY_BYTES = 64 * 1024
TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")

# 1x1 transparent PNG served when no cached art exists.
_BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _MPD:
    """One private MPDClient behind a lock with explicit retry semantics."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6600):
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._client: MPDClient | None = None

    def _connect(self) -> MPDClient:
        c = create_mpd_client()
        c.timeout = 5
        try:
            c.connect(self._host, self._port)
        except Exception:
            close_mpd_client(c)
            raise
        return c

    def call(self, fn):
        """Run an idempotent/read callback with one reconnect retry."""
        with self._lock:
            for attempt in (0, 1):
                if self._client is None:
                    self._client = self._connect()
                try:
                    return fn(self._client)
                except (MPDConnectionError, OSError):
                    close_mpd_client(self._client)
                    self._client = None
                    if attempt:
                        raise
                except CommandError:
                    # Invalid read commands are deterministic; reconnecting
                    # cannot make the request valid.
                    raise
            return None  # unreachable

    def close(self):
        with self._lock:
            if self._client is not None:
                close_mpd_client(self._client)
                self._client = None


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _tag(v) -> str:
    """Flatten an MPD tag value (python-mpd2 may return a list) to a string."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v) if v is not None else ""


def _is_loopback(host: str) -> bool:
    """Recognize literal loopback peers without trusting proxy headers."""
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _tailscale_ipv4(value: str) -> str:
    """Return a verified Tailscale IPv4 address or an empty string."""
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return ""
    if address.version != 4 or address not in TAILSCALE_IPV4_NETWORK:
        return ""
    return str(address)


def _loopback_host_allowed(host: str) -> bool:
    """Reject DNS-rebound Host names while retaining native HTTP/1.0 use."""
    host = str(host or "").strip()
    if not host:
        return True
    try:
        name = urlparse("//" + host).hostname or ""
    except ValueError:
        return False
    return name.casefold() == "localhost" or _is_loopback(name)


def _cookie_token(value: str) -> str:
    try:
        cookie = SimpleCookie()
        cookie.load(value)
        morsel = cookie.get("ampere_token")
        return morsel.value if morsel else ""
    except Exception:
        return ""


def request_authorized(client_host: str, expected: str, *, header: str = "",
                       cookie: str = "", query: str = "",
                       host: str = "") -> bool:
    """Authorize a peer using loopback trust or a constant-time token match."""
    if _is_loopback(client_host) and _loopback_host_allowed(host):
        return True
    if not expected:
        return False
    return any(candidate and hmac.compare_digest(expected, candidate)
               for candidate in (header, query, _cookie_token(cookie)))


def request_origin_allowed(origin: str, host: str) -> bool:
    """Allow native/no-Origin clients and same-origin browser requests only."""
    origin = str(origin or "").strip()
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return (parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and parsed.netloc.casefold() == str(host or "").strip().casefold())


class RemoteCommand:
    """Thread-safe lifecycle shared by an HTTP request and the Qt backend."""

    TERMINAL = frozenset({"committed", "failed", "indeterminate"})

    def __init__(self, action: str, payload: dict | None = None):
        self.id = secrets.token_urlsafe(12)
        self.action = str(action)
        self.payload = dict(payload or {})
        self._lock = threading.Lock()
        self._status = "queued"
        self._accepted = False
        self._message = ""

    def admit(self) -> bool:
        with self._lock:
            if self._status != "queued":
                return False
            self._status = "admitted"
            self._accepted = True
            return True

    def finish(self, success: bool, message: str = "") -> bool:
        with self._lock:
            if self._status in self.TERMINAL:
                return False
            self._status = "committed" if success else "failed"
            self._message = str(message or "")
            return True

    def mark_indeterminate(self, message: str = "") -> bool:
        with self._lock:
            if self._status in self.TERMINAL:
                return False
            self._status = "indeterminate"
            self._message = str(
                message or "Command outcome could not be verified")
            return True

    def snapshot(self) -> dict:
        with self._lock:
            result = {
                "id": self.id,
                "action": self.action,
                "status": self._status,
                "accepted": self._accepted,
                "committed": self._status == "committed",
            }
            if self._message:
                result["message"] = self._message
            return result


class RemoteCommandRegistry:
    """Bounded command ledger exposing eventual completion to phone clients."""

    def __init__(self, dispatch=None, *, limit: int = 256):
        self._dispatch = dispatch
        self._limit = max(16, int(limit))
        self._lock = threading.Lock()
        self._commands: dict[str, RemoteCommand] = {}
        self._closed = False

    def submit(self, action: str, payload: dict | None = None) -> RemoteCommand:
        command = RemoteCommand(action, payload)
        with self._lock:
            terminal = [key for key, value in self._commands.items()
                        if value.snapshot()["status"] in RemoteCommand.TERMINAL]
            while len(self._commands) >= self._limit and terminal:
                self._commands.pop(terminal.pop(0), None)
            if self._closed or len(self._commands) >= self._limit:
                command.finish(False, "Phone command service is unavailable")
                return command
            self._commands[command.id] = command
            dispatch = self._dispatch
        if not callable(dispatch):
            command.finish(False, "Phone command service is unavailable")
            return command
        try:
            dispatch(command)
        except Exception:
            command.finish(False, "Phone command could not be submitted")
        return command

    def snapshot(self, command_id: str) -> dict | None:
        with self._lock:
            command = self._commands.get(str(command_id))
        return command.snapshot() if command is not None else None

    def close(self):
        with self._lock:
            self._closed = True
            commands = tuple(self._commands.values())
        for command in commands:
            command.finish(False, "Ampere closed before the command committed")


class _Handler(BaseHTTPRequestHandler):
    server_version = "Ampere/1.0"
    mpd: _MPD  # set on the server class at start()

    # ---- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):  # silence per-request stderr noise
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              headers: dict[str, str] | None = None):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'; img-src 'self' data:; "
                "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'")
            self.send_header("Connection", "close")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # Phones disappear mid-response routinely (sleep, Wi-Fi handoff,
            # browser navigation). Treat the whole header/body write as one
            # best-effort operation and ensure the handler does not keep the
            # broken stream alive for interpreter finalization.
            self.close_connection = True

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode())

    def _body_json(self) -> dict | None:
        n = _i(self.headers.get("Content-Length"), 0)
        if n <= 0:
            return {}
        if n > MAX_BODY_BYTES:
            return None
        try:
            value = json.loads(self.rfile.read(n).decode() or "{}")
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeDecodeError):
            return None

    @property
    def _mpd(self) -> _MPD:
        return self.server.mpd  # type: ignore[attr-defined]

    def _authorize(self, url) -> tuple[bool, bool]:
        expected = getattr(self.server, "auth_token", "")
        query = parse_qs(url.query).get("token", [""])[0]
        peer = self.client_address[0]
        allowed = request_authorized(
            peer, expected, header=self.headers.get("X-Ampere-Token", ""),
            cookie=self.headers.get("Cookie", ""), query=query,
            host=self.headers.get("Host", ""))
        paired = bool(not _is_loopback(peer) and query and expected
                      and hmac.compare_digest(expected, query))
        return allowed, paired

    # ---- routes -----------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)
        allowed, paired = self._authorize(url)
        if not allowed:
            self._json({"error": "pairing required"}, 401)
            return
        try:
            if path == "/":
                headers = None
                if paired:
                    token = getattr(self.server, "auth_token", "")
                    headers = {"Set-Cookie":
                               f"ampere_token={token}; Path=/; Max-Age=31536000; "
                               "HttpOnly; SameSite=Strict"}
                self._send(200, _PAGE.encode(), "text/html; charset=utf-8",
                           headers=headers)
            elif path == "/api/status":
                self._json(self._status())
            elif path == "/api/queue":
                self._json(self._queue())
            elif path == "/api/browse":
                self._json(self._browse(qs.get("path", [""])[0]))
            elif path == "/api/search":
                self._json(self._search(qs.get("q", [""])[0]))
            elif path == "/api/playlists":
                self._json(self._playlists())
            elif path.startswith("/api/commands/"):
                command_id = path.rsplit("/", 1)[-1]
                registry = getattr(self.server, "commands", None)
                result = registry.snapshot(command_id) if registry else None
                if result is None:
                    self._json({"error": "command not found"}, 404)
                else:
                    self._json(result)
            elif path == "/art/current":
                self._art()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        if not request_origin_allowed(
                self.headers.get("Origin", ""), self.headers.get("Host", "")):
            self._json({"error": "cross-origin request denied"}, 403)
            return
        allowed, _paired = self._authorize(url)
        if not allowed:
            self._json({"error": "pairing required"}, 401)
            return
        content_type = self.headers.get("Content-Type", "").partition(";")[0]
        if content_type.strip().casefold() != "application/json":
            self._json({"error": "application/json required"}, 415)
            return
        body = self._body_json()
        if body is None:
            code = 413 if _i(self.headers.get("Content-Length"), 0) > MAX_BODY_BYTES else 400
            self._json({"error": "request body too large" if code == 413
                        else "invalid JSON object"}, code)
            return
        try:
            if path == "/api/play":
                if body.get("path") or body.get("file") or body.get("playlist"):
                    return self._dispatch_command("play-target", body)
                else:
                    return self._dispatch_command(
                        "transport", {"action": "play"})
            elif path == "/api/playnow":
                f = str(body.get("file") or "")
                if not f:
                    self._json({"error": "no file"}, 400)
                    return
                return self._dispatch_command("play-now", {"file": f})
            elif path == "/api/queue":
                f = str(body.get("file") or "")
                if not f:
                    self._json({"error": "no file"}, 400)
                    return
                return self._dispatch_command("queue-append", {"file": f})
            elif path == "/api/pause":
                return self._dispatch_command(
                    "transport", {"action": "toggle"})
            elif path == "/api/next":
                return self._dispatch_command("move", {"command": "next"})
            elif path == "/api/prev":
                return self._dispatch_command(
                    "move", {"command": "previous"})
            elif path == "/api/volume":
                v = max(0, min(100, _i(body.get("value"))))
                return self._dispatch_command("volume", {"value": v})
            elif path == "/api/seek":
                s = max(0.0, _f(body.get("seconds")))
                return self._dispatch_command("seek", {"seconds": s})
            elif path == "/api/jump":
                song_id = _i(body.get("id"), -1)
                if song_id < 0:
                    self._json({"error": "bad song id"}, 400)
                    return
                return self._dispatch_command("jump", {"songId": song_id})
            elif path == "/api/nav":
                mode = str(body.get("mode", ""))
                arg = str(body.get("arg", ""))
                cb = getattr(self.server, "nav_cb", None)
                ok = {"home", "browse", "genres", "playlists", "eq", "lyrics",
                      "settings", "now", "smart", "rewind", "results", "search",
                      "disliked", "dj", "queue", "ambient", "doctor", "album",
                      "library", "features", "ampy", "discover", "artist", "radio"}
                if cb is None or mode not in ok:
                    self._json({"error": "bad mode"}, 400)
                    return
                cb(mode, arg)
            else:
                self._json({"error": "not found"}, 404)
                return
            self._json({"ok": True, "status": "committed"})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---- handlers ---------------------------------------------------------

    def _dispatch_command(self, action: str, payload: dict):
        registry = getattr(self.server, "commands", None)
        if registry is None:
            self._json({"error": "phone command service unavailable"}, 503)
            return
        command = registry.submit(action, payload)
        result = command.snapshot()
        code = 503 if result["status"] == "failed" else 202
        self._json(result, code)

    def _status(self) -> dict:
        def go(c: MPDClient):
            return c.status(), c.currentsong()

        status, song = self._mpd.call(go)
        return {
            "state": status.get("state", "stop"),
            "title": song.get("title") or Path(song.get("file", "")).stem,
            "artist": song.get("artist", ""),
            "elapsed": _f(status.get("elapsed")),
            "duration": _f(status.get("duration")),
            "volume": _i(status.get("volume"), -1),
            "queueLength": _i(status.get("playlistlength")),
            "file": song.get("file", ""),
        }

    def _queue(self) -> list:
        def go(c: MPDClient):
            pos = _i(c.status().get("song"), -1)
            start = pos + 1
            return c.playlistinfo(f"{start}:{start + 20}") if start >= 0 else \
                c.playlistinfo("0:20")

        items = self._mpd.call(go) or []
        out = []
        for it in items:
            out.append({
                "title": it.get("title") or Path(it.get("file", "")).stem,
                "artist": it.get("artist", ""),
                "pos": _i(it.get("pos"), -1),
                "id": _i(it.get("id"), -1),
            })
        return out

    def _browse(self, rel: str) -> list:
        items = self._mpd.call(lambda c: c.lsinfo(rel or "")) or []
        out = []
        for it in items:
            if "directory" in it:
                p = it["directory"]
                out.append({"type": "dir", "name": Path(p).name, "path": p})
            elif "file" in it:
                p = it["file"]
                out.append({
                    "type": "file", "name": Path(p).name, "path": p,
                    "artist": _tag(it.get("artist")),
                    "title": _tag(it.get("title")) or Path(p).stem,
                })
        return out

    def _search(self, q: str) -> list:
        q = q.strip()
        if not q:
            return []
        items = self._mpd.call(lambda c: c.search("any", q)) or []
        out = []
        for it in items:
            f = it.get("file")
            if not f:
                continue
            out.append({
                "file": f,
                "title": _tag(it.get("title")) or Path(f).stem,
                "artist": _tag(it.get("artist")),
            })
            if len(out) >= 30:
                break
        return out

    def _playlists(self) -> list:
        items = self._mpd.call(lambda c: c.listplaylists()) or []
        names = sorted((p.get("playlist", "") for p in items), key=str.lower)
        return [{"name": n} for n in names if n and n != "Disliked"]

    def _art(self):
        rel = ""
        try:
            song = self._mpd.call(lambda c: c.currentsong())
            rel = song.get("file", "") or ""
        except Exception:
            pass
        if rel:
            f = ART_CACHE / (hashlib.sha1(rel.encode(), usedforsecurity=False).hexdigest() + ".jpg")
            if f.is_file():
                try:
                    data = f.read_bytes()
                    if len(data) > 100:  # skip 1px negative-cache markers
                        self._send(200, data, "image/jpeg")
                        return
                except OSError:
                    pass
        self._send(200, _BLANK_PNG, "image/png")


class _RemoteHttpServer(ThreadingHTTPServer):
    """Track request workers so ``server_close`` can reap every socket."""

    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True
    request_timeout = 5.0

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.request_timeout)
        return request, address


class RemoteServer:
    """Phone remote. start()/stop(); server runs on a daemon thread."""

    def __init__(self, mpd_host: str = "127.0.0.1", mpd_port: int = 6600,
                 nav_cb=None, command_cb=None,
                 auth_token: str = ""):
        self._mpd_host = mpd_host
        self._mpd_port = mpd_port
        self._nav_cb = nav_cb  # e.g. a Qt Signal.emit — auto-queues to the GUI thread
        self._commands = RemoteCommandRegistry(command_cb)
        self._auth_token = auth_token
        self._servers: list[tuple[ThreadingHTTPServer, threading.Thread]] = []

    def start(self, hosts: list[str] | None = None, port: int = 8480):
        """Bind loopback, then one optional encrypted-overlay listener.

        Loopback is mandatory for the local app/audit integration. An optional
        Tailscale bind may fail without taking local control down, but a server
        must never report success with only the non-loopback listener. Every
        non-loopback peer is still denied without the pairing token."""
        if self._servers:
            return
        seen: list[str] = ["127.0.0.1"]
        for h in (hosts or []):
            if h and h not in seen:
                seen.append(h)
        for h in seen:
            try:
                mpd = _MPD(self._mpd_host, self._mpd_port)
                httpd = _RemoteHttpServer((h, port), _Handler)
                httpd.mpd = mpd  # type: ignore[attr-defined]
                httpd.nav_cb = self._nav_cb  # type: ignore[attr-defined]
                httpd.commands = self._commands  # type: ignore[attr-defined]
                httpd.auth_token = self._auth_token  # type: ignore[attr-defined]
                t = threading.Thread(target=httpd.serve_forever,
                                     name=f"ampere-remote-{h}", daemon=True)
                t.start()
                self._servers.append((httpd, t))
            except OSError as exc:
                if _is_loopback(h):
                    self.stop()
                    raise OSError(
                        "phone remote: loopback could not be bound") from exc
                continue  # optional overlay failure leaves local control alive

    def stop(self):
        self._commands.close()
        servers, self._servers = self._servers, []
        for httpd, t in servers:
            try:
                httpd.shutdown()
            except Exception:
                pass
            t.join(timeout=5)
            try:
                # Joins every non-daemon request handler before its socket or
                # private MPD client is released.
                httpd.server_close()
            except Exception:
                pass
            try:
                httpd.mpd.close()  # type: ignore[attr-defined]
            except Exception:
                pass


class RemoteControlService:
    """Own remote discovery, binding, pairing URL, and server lifecycle."""

    def __init__(self, *, auth_token: str, nav_cb=None, command_cb=None,
                 error=lambda _message: None, port: int = 8480,
                 server_factory=RemoteServer, run=subprocess.run):
        self._auth_token = str(auth_token)
        self._nav_cb = nav_cb
        self._command_cb = command_cb
        self._error = error
        self._port = int(port)
        self._server_factory = server_factory
        self._run = run
        self._server = None
        self._address = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def resolve_address(self) -> str:
        """Return verified Tailscale IPv4, otherwise remain local-only."""
        if self._address is not None:
            return self._address
        address = ""
        try:
            result = self._run(
                ["tailscale", "ip", "-4"], capture_output=True,
                text=True, timeout=3)
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                address = _tailscale_ipv4(lines[0] if lines else "")
        except Exception:
            pass
        self._address = address or "127.0.0.1"
        return self._address

    def start(self) -> bool:
        if self._server is not None:
            return True
        address = self.resolve_address()
        hosts = ["127.0.0.1"]
        if address != "127.0.0.1":
            hosts.append(address)
        candidate = self._server_factory(
            nav_cb=self._nav_cb, command_cb=self._command_cb,
            auth_token=self._auth_token)
        try:
            candidate.start(hosts=hosts, port=self._port)
        except Exception as exc:
            try:
                candidate.stop()
            except Exception:
                pass
            self._error(f"Phone remote failed to start: {exc}")
            return False
        self._server = candidate
        return True

    def stop(self):
        server, self._server = self._server, None
        if server is None:
            return
        try:
            server.stop()
        except Exception:
            pass

    @property
    def url(self) -> str:
        token = quote(self._auth_token, safe="")
        return f"http://{self.resolve_address()}:{self._port}/?token={token}"

    @property
    def cached_url(self) -> str:
        """Return a pairing URL without performing network discovery.

        The loopback URL is immediately usable on the host. Once a worker has
        resolved a verified Tailscale address, subsequent reads expose that
        cached address instead. UI property reads must never launch discovery.
        """
        token = quote(self._auth_token, safe="")
        address = self._address or "127.0.0.1"
        return f"http://{address}:{self._port}/?token={token}"


# ---------------------------------------------------------------------------
# The page — single file, no external assets.
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a0e15">
<title>Ampere</title>
<style>
  :root {
    --bg: #0a0e15; --panel: #101623; --line: #1c2536;
    --cyan: #5ee7f2; --pink: #f26df9; --dim: #6b7a94; --fg: #dce6f2;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; }
  body {
    background: var(--bg); color: var(--fg);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center;
    padding: max(10px, env(safe-area-inset-top)) 16px
             calc(74px + env(safe-area-inset-bottom));
    user-select: none;
  }
  .wrap { width: 100%; max-width: 430px; display: flex; flex-direction: column; gap: 14px; }
  .wordmark {
    display: flex; align-items: center; justify-content: center; gap: 12px;
    font-style: italic; font-weight: 300;
    font-size: 28px; letter-spacing: .55em;
    color: var(--cyan); text-shadow: 0 0 18px rgba(94,231,242,.45);
    margin: 4px 0 2px;
  }
  .wordmark .amark { width: 30px; height: 30px; flex: none;
    filter: drop-shadow(0 0 9px rgba(94,231,242,.5)); }
  .wordmark span { padding-left: .55em; }
  .art {
    width: 100%; aspect-ratio: 1; border-radius: 14px; overflow: hidden;
    background: var(--panel); border: 1px solid var(--line);
    box-shadow: 0 8px 40px rgba(0,0,0,.5);
  }
  .art img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .meta { text-align: center; min-height: 52px; }
  .title { font-size: 19px; font-weight: 600; white-space: nowrap;
           overflow: hidden; text-overflow: ellipsis; }
  .artist { font-size: 15px; color: var(--pink); margin-top: 3px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .prog { display: flex; align-items: center; gap: 10px; font-size: 12px;
          color: var(--dim); font-variant-numeric: tabular-nums; }
  .bar { flex: 1; height: 30px; display: flex; align-items: center; cursor: pointer; }
  .bar .track { width: 100%; height: 4px; border-radius: 2px; background: var(--line);
                overflow: hidden; }
  .bar .fill { height: 100%; width: 0%; background: var(--cyan);
               box-shadow: 0 0 8px rgba(94,231,242,.7); transition: width .3s linear; }
  .controls { display: flex; justify-content: center; align-items: center; gap: 26px; }
  button { background: none; border: none; color: var(--fg); cursor: pointer;
           display: flex; align-items: center; justify-content: center; }
  button:active { transform: scale(.92); }
  .skip { width: 64px; height: 64px; }
  .skip svg { width: 34px; height: 34px; fill: var(--fg); }
  .pp { width: 84px; height: 84px; border-radius: 50%;
        border: 2px solid var(--cyan); box-shadow: 0 0 22px rgba(94,231,242,.35),
        inset 0 0 14px rgba(94,231,242,.12); }
  .pp svg { width: 36px; height: 36px; fill: var(--cyan); }
  .vol { display: flex; align-items: center; gap: 12px; }
  .vol svg { width: 20px; height: 20px; fill: var(--dim); flex: none; }
  input[type=range] { flex: 1; appearance: none; -webkit-appearance: none;
    height: 30px; background: transparent; }
  input[type=range]::-webkit-slider-runnable-track {
    height: 4px; border-radius: 2px; background: var(--line); }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance: none;
    width: 26px; height: 26px; border-radius: 50%; margin-top: -11px;
    background: var(--pink); box-shadow: 0 0 10px rgba(242,109,249,.6); }
  input[type=range]::-moz-range-track {
    height: 4px; border-radius: 2px; background: var(--line); }
  input[type=range]::-moz-range-thumb { width: 26px; height: 26px; border: none;
    border-radius: 50%; background: var(--pink);
    box-shadow: 0 0 10px rgba(242,109,249,.6); }
  .nexthead { font-size: 11px; letter-spacing: .35em; color: var(--dim);
              margin-top: 4px; }
  .queue { display: flex; flex-direction: column; }
  .row { display: flex; align-items: center; gap: 12px; padding: 12px 6px;
         border-bottom: 1px solid var(--line); cursor: pointer; }
  .row:active { background: var(--panel); }
  .row .n { color: var(--cyan); font-size: 12px; width: 26px; flex: none;
            font-variant-numeric: tabular-nums; }
  .row .t { flex: 1; min-width: 0; }
  .row .t .tt { font-size: 15px; white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
  .row .t .ta { font-size: 12px; color: var(--dim); white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }
  .empty { color: var(--dim); font-size: 13px; padding: 14px 6px; }
  .tab { display: flex; flex-direction: column; gap: 14px; }
  .tab.hidden { display: none; }
  .tabs { position: fixed; left: 0; right: 0; bottom: 0; z-index: 10;
          display: flex; justify-content: center;
          background: rgba(10,14,21,.96); border-top: 1px solid var(--line);
          padding-bottom: env(safe-area-inset-bottom);
          backdrop-filter: blur(8px); }
  .tabs .inner { width: 100%; max-width: 430px; display: flex; }
  .tabbtn { flex: 1; min-height: 54px; flex-direction: column; gap: 3px;
            color: var(--dim); font-size: 9px; letter-spacing: .22em; }
  .tabbtn svg { width: 20px; height: 20px; fill: currentColor; }
  .tabbtn.on { color: var(--cyan); text-shadow: 0 0 10px rgba(94,231,242,.5); }
  .pane-title { font-size: 11px; letter-spacing: .35em; color: var(--dim);
                margin-top: 4px; white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
  .list { display: flex; flex-direction: column; }
  .row.item { min-height: 44px; }
  .mini { border: 1px solid var(--line); border-radius: 8px; flex: none;
          color: var(--cyan); font-size: 10px; letter-spacing: .12em;
          padding: 10px 11px; background: var(--panel); }
  .mini.alt { color: var(--pink); }
  .searchbar { display: flex; gap: 8px; margin-top: 4px; }
  .searchbar input[type=text] { flex: 1; min-height: 44px; border-radius: 10px;
      border: 1px solid var(--line); background: var(--panel); color: var(--fg);
      padding: 0 12px; font-size: 15px; outline: none; }
  .searchbar input[type=text]:focus { border-color: var(--cyan); }
  .go { border: 1px solid var(--cyan); border-radius: 10px; color: var(--cyan);
        padding: 0 16px; min-height: 44px; font-size: 12px; letter-spacing: .2em; }
  .command-status { min-height: 18px; color: var(--dim); text-align: center;
                    font-size: 12px; }
  .command-status.error { color: var(--pink); }
</style>
</head>
<body>
<div class="wrap">
  <div class="wordmark"><svg class="amark" viewBox="0 0 512 512"><g fill="none"
    stroke="currentColor" stroke-linecap="round"><path stroke-width="44"
    d="M256 88 L128 424 M256 88 L384 424"/><path stroke-width="36"
    d="M174 300 C 201 248, 228 248, 255 300 S 311 352, 338 300"/></g></svg><span>AMPERE</span></div>
  <div class="tab" id="tab-now">
  <div class="art"><img id="art" src="/art/current" alt=""></div>
  <div class="meta">
    <div class="title" id="title">&mdash;</div>
    <div class="artist" id="artist"></div>
  </div>
  <div class="prog">
    <span id="el">0:00</span>
    <div class="bar" id="bar"><div class="track"><div class="fill" id="fill"></div></div></div>
    <span id="du">0:00</span>
  </div>
  <div class="controls">
    <button class="skip" id="prev" aria-label="Previous">
      <svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg>
    </button>
    <button class="pp" id="pp" aria-label="Play/Pause">
      <svg id="ppicon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
    </button>
    <button class="skip" id="next" aria-label="Next">
      <svg viewBox="0 0 24 24"><path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z"/></svg>
    </button>
  </div>
  <div class="command-status" id="command-status" role="status"
       aria-live="polite"></div>
  <div class="vol">
    <svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4z"/></svg>
    <input type="range" id="vol" min="0" max="100" value="50">
  </div>
  <div class="nexthead">UP NEXT</div>
  <div class="queue" id="queue"><div class="empty">&mdash;</div></div>
  </div>
  <div class="tab hidden" id="tab-lib">
    <div class="pane-title" id="libpath">LIBRARY</div>
    <div class="list" id="liblist"><div class="empty">&mdash;</div></div>
  </div>
  <div class="tab hidden" id="tab-search">
    <div class="searchbar">
      <input type="text" id="q" placeholder="Search library" autocomplete="off"
             enterkeyhint="search">
      <button class="go" id="qgo">GO</button>
    </div>
    <div class="list" id="searchlist"><div class="empty">Type to search</div></div>
  </div>
  <div class="tab hidden" id="tab-pl">
    <div class="pane-title">PLAYLISTS</div>
    <div class="list" id="pllist"><div class="empty">&mdash;</div></div>
  </div>
</div>
<div class="tabs"><div class="inner">
  <button class="tabbtn on" id="tb-now" aria-label="Now Playing">
    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>NOW</button>
  <button class="tabbtn" id="tb-lib" aria-label="Library">
    <svg viewBox="0 0 24 24"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>LIBRARY</button>
  <button class="tabbtn" id="tb-search" aria-label="Search">
    <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 4.99L20.49 19zM9.5 14A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14z"/></svg>SEARCH</button>
  <button class="tabbtn" id="tb-pl" aria-label="Playlists">
    <svg viewBox="0 0 24 24"><path d="M4 6h2v2H4zm4 0h12v2H8zM4 11h2v2H4zm4 0h12v2H8zM4 16h2v2H4zm4 0h12v2H8z"/></svg>LISTS</button>
</div></div>
<script>
(() => {
  if (location.search) history.replaceState(null, '', location.pathname);
  const $ = id => document.getElementById(id);
  const PLAY  = 'M8 5v14l11-7z';
  const PAUSE = 'M6 5h4v14H6zm8 0h4v14h-4z';
  let st = { elapsed: 0, duration: 0, file: null };
  let volHeld = false, lastFile;
  let noticeTimer;

  const fmt = s => {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  };
  function showCommand(message, error) {
    const notice = $('command-status');
    notice.textContent = message || '';
    notice.classList.toggle('error', !!error);
    clearTimeout(noticeTimer);
    if (message && !error) {
      noticeTimer = setTimeout(() => { notice.textContent = ''; }, 1800);
    }
  }

  function watchCommand(command, attempts) {
    if (!command || !command.id) return;
    if (command.status === 'committed') {
      showCommand('Done', false);
      setTimeout(poll, 150);
      return;
    }
    if (command.status === 'failed') {
      showCommand(command.message || 'Command failed', true);
      return;
    }
    if (command.status === 'indeterminate') {
      showCommand(command.message || 'Command outcome could not be verified', true);
      return;
    }
    showCommand(command.status === 'admitted' ? 'Working\u2026' : 'Queued\u2026', false);
    const delay = (attempts || 0) < 80 ? 250 : 2000;
    setTimeout(() => fetch('/api/commands/' + encodeURIComponent(command.id))
      .then(async r => {
        const next = await r.json();
        if (!r.ok) throw new Error(next.error || 'Command status unavailable');
        watchCommand(next, (attempts || 0) + 1);
      })
      .catch(() => {
        showCommand('Command status unavailable; retrying', true);
        setTimeout(() => watchCommand(command, (attempts || 0) + 1), 2000);
      }), delay);
  }

  const post = (p, body) => fetch(p, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : null
  }).then(async r => {
    const result = await r.json();
    if (!r.ok && !result.id) throw new Error(result.error || 'Command failed');
    watchCommand(result, 0);
  }).catch(error => showCommand(error.message || 'Command failed', true));

  function render(s) {
    st = s;
    $('title').textContent = s.title || '\\u2014';
    $('artist').textContent = s.artist || '';
    $('el').textContent = fmt(s.elapsed);
    $('du').textContent = fmt(s.duration);
    $('fill').style.width = s.duration ? (100 * s.elapsed / s.duration) + '%' : '0%';
    $('ppicon').firstElementChild.setAttribute('d', s.state === 'play' ? PAUSE : PLAY);
    if (!volHeld && s.volume >= 0) $('vol').value = s.volume;
    if (s.file !== lastFile) {
      lastFile = s.file;
      $('art').src = '/art/current?t=' + Date.now();
      loadQueue();
    }
  }

  function loadQueue() {
    fetch('/api/queue').then(r => r.json()).then(items => {
      const q = $('queue');
      q.innerHTML = '';
      if (!items.length) {
        q.innerHTML = '<div class="empty">Nothing queued</div>';
        return;
      }
      items.forEach(it => {
        const row = document.createElement('div');
        row.className = 'row';
        const n = document.createElement('div'); n.className = 'n';
        n.textContent = it.pos + 1;
        const t = document.createElement('div'); t.className = 't';
        const tt = document.createElement('div'); tt.className = 'tt';
        tt.textContent = it.title;
        const ta = document.createElement('div'); ta.className = 'ta';
        ta.textContent = it.artist;
        t.append(tt, ta); row.append(n, t);
        row.onclick = () => post('/api/jump', { id: it.id });
        q.appendChild(row);
      });
    }).catch(() => {});
  }

  function poll() {
    fetch('/api/status').then(r => r.json()).then(render).catch(() => {});
  }

  $('pp').onclick = () => post('/api/pause');
  $('next').onclick = () => post('/api/next');
  $('prev').onclick = () => post('/api/prev');
  $('bar').onclick = e => {
    if (!st.duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    post('/api/seek', { seconds: frac * st.duration });
  };
  const vol = $('vol');
  vol.oninput = () => { volHeld = true; };
  vol.onchange = () => {
    volHeld = false;
    post('/api/volume', { value: +vol.value });
  };

  // ---- tabs ---------------------------------------------------------------
  const TABS = ['now', 'lib', 'search', 'pl'];
  let libPath = '', libLoaded = false;

  function showTab(name) {
    TABS.forEach(t => {
      $('tab-' + t).classList.toggle('hidden', t !== name);
      $('tb-' + t).classList.toggle('on', t === name);
    });
    if (name === 'lib' && !libLoaded) { libLoaded = true; loadLib(''); }
    if (name === 'pl') loadPlaylists();
  }
  TABS.forEach(t => { $('tb-' + t).onclick = () => showTab(t); });

  const emptyDiv = txt => {
    const d = document.createElement('div');
    d.className = 'empty'; d.textContent = txt;
    return d;
  };

  function mkRow(tt, ta, onTap, btns) {
    const row = document.createElement('div');
    row.className = 'row item';
    const t = document.createElement('div'); t.className = 't';
    const a = document.createElement('div'); a.className = 'tt';
    a.textContent = tt;
    t.appendChild(a);
    if (ta) {
      const b = document.createElement('div'); b.className = 'ta';
      b.textContent = ta;
      t.appendChild(b);
    }
    row.appendChild(t);
    (btns || []).forEach(spec => {
      const bt = document.createElement('button');
      bt.className = 'mini' + (spec[1] ? ' alt' : '');
      bt.textContent = spec[0];
      bt.onclick = e => { e.stopPropagation(); spec[2](); };
      row.appendChild(bt);
    });
    if (onTap) row.onclick = onTap;
    return row;
  }

  // ---- library ------------------------------------------------------------
  function loadLib(p) {
    libPath = p;
    $('libpath').textContent = p ? p.toUpperCase() : 'LIBRARY';
    const box = $('liblist');
    box.innerHTML = '';
    box.appendChild(emptyDiv('Loading\\u2026'));
    fetch('/api/browse?path=' + encodeURIComponent(p))
      .then(r => r.json()).then(items => {
        box.innerHTML = '';
        if (p) {
          const up = p.indexOf('/') >= 0 ? p.slice(0, p.lastIndexOf('/')) : '';
          box.appendChild(mkRow('\\u2039 Back', '', () => loadLib(up)));
        }
        if (!Array.isArray(items) || !items.length) {
          box.appendChild(emptyDiv('Empty folder'));
          return;
        }
        items.forEach(it => {
          if (it.type === 'dir') {
            box.appendChild(mkRow(it.name, '', () => loadLib(it.path), [
              ['PLAY', false, () => post('/api/play', { path: it.path })],
              ['SHUF', true,
               () => post('/api/play', { path: it.path, shuffle: true })]
            ]));
          } else {
            box.appendChild(mkRow(it.title, it.artist,
              () => post('/api/play', { file: it.path })));
          }
        });
      }).catch(() => {
        box.innerHTML = '';
        box.appendChild(emptyDiv('Browse failed'));
      });
  }

  // ---- search -------------------------------------------------------------
  function runSearch() {
    const q = $('q').value.trim();
    const box = $('searchlist');
    box.innerHTML = '';
    if (!q) { box.appendChild(emptyDiv('Type to search')); return; }
    box.appendChild(emptyDiv('Searching\\u2026'));
    fetch('/api/search?q=' + encodeURIComponent(q))
      .then(r => r.json()).then(items => {
        box.innerHTML = '';
        if (!Array.isArray(items) || !items.length) {
          box.appendChild(emptyDiv('No matches'));
          return;
        }
        items.forEach(it => {
          box.appendChild(mkRow(it.title, it.artist,
            () => post('/api/playnow', { file: it.file }),
            [['+', true, () => post('/api/queue', { file: it.file })]]));
        });
      }).catch(() => {
        box.innerHTML = '';
        box.appendChild(emptyDiv('Search failed'));
      });
  }
  $('qgo').onclick = runSearch;
  $('q').addEventListener('keydown', e => {
    if (e.key === 'Enter') { runSearch(); $('q').blur(); }
  });

  // ---- playlists ----------------------------------------------------------
  function loadPlaylists() {
    const box = $('pllist');
    fetch('/api/playlists').then(r => r.json()).then(items => {
      box.innerHTML = '';
      if (!Array.isArray(items) || !items.length) {
        box.appendChild(emptyDiv('No playlists'));
        return;
      }
      items.forEach(it => {
        box.appendChild(mkRow(it.name, '', null, [
          ['PLAY', false, () => post('/api/play', { playlist: it.name })],
          ['SHUF', true,
           () => post('/api/play', { playlist: it.name, shuffle: true })]
        ]));
      });
    }).catch(() => {});
  }

  poll();
  loadQueue();
  setInterval(poll, 2000);
})();
</script>
</body>
</html>
"""
