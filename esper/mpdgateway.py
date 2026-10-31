"""Connection and single-command reliability boundary for MPD."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading

from mpd import MPDClient
from mpd.base import CommandError, ConnectionError as MPDConnectionError

_client_lock = threading.Lock()
_clients = set()


@dataclass(frozen=True)
class MpdReadResult:
    available: bool
    value: object = None


def track_mpd_client(client):
    """Retain a client until its transport has been explicitly closed."""
    with _client_lock:
        _clients.add(client)
    return client


def _release_mpd_client(client) -> None:
    with _client_lock:
        _clients.discard(client)


def create_mpd_client(factory=MPDClient):
    return track_mpd_client(factory())


def tracked_mpd_clients() -> tuple:
    with _client_lock:
        return tuple(_clients)


def close_all_mpd_clients() -> int:
    """Close every still-reachable client before the MPD peer exits."""
    clients = tracked_mpd_clients()
    for client in clients:
        close_mpd_client(client)
    return len(clients)


def retire_mpd_writer(client) -> None:
    """Close an idle client's writer before forcibly waking its read socket."""
    writer = getattr(client, "_wfile", None)
    if writer is None or type(writer).__name__ == "_NotConnected":
        return
    try:
        writer.close()
    except Exception:
        pass
    finally:
        # Never let a later disconnect/finalizer retry a failed flush after
        # the socket has deliberately been shut down.
        client._wfile = None


def close_mpd_client(client) -> None:
    """Release every python-mpd2 transport even if one close operation fails.

    Upstream ``disconnect`` stops at the first exception. A broken writer
    flush can therefore strand ``_wfile``/``_sock`` until interpreter
    finalization, where it raises again after MPD has exited.
    """
    parts = [getattr(client, name, None)
             for name in ("_rbfile", "_wfile", "_sock")]
    if not any(part is not None for part in parts):
        try:
            client.disconnect()
        except Exception:
            pass
        finally:
            _release_mpd_client(client)
        return
    # Retire the text writer while the socket is still healthy. It is the only
    # transport part whose close may flush bytes and therefore must precede
    # reader/socket teardown.
    for part in (parts[1], parts[0], parts[2]):
        if part is not None:
            try:
                part.close()
            except Exception:
                pass
    reset = getattr(client, "_reset", None)
    if reset is not None:
        try:
            reset()
        except Exception:
            pass
    _release_mpd_client(client)


def open_temporary_mpd_client(host, port, *, timeout=15, factory=MPDClient):
    """Open a worker client, cleaning partial socket state on failure."""
    client = create_mpd_client(factory)
    client.timeout = timeout
    try:
        client.connect(host, port)
    except Exception:
        close_mpd_client(client)
        raise
    return client


@contextmanager
def temporary_mpd_client(host, port, *, timeout=15, factory=MPDClient,
                         registry=None):
    """Yield one connected worker client and always release its socket.

    ``connect`` is intentionally inside the protected region: python-mpd2 can
    allocate socket-backed readers before a handshake fails, so failed opens
    need the same cleanup as successful commands.
    """
    client = open_temporary_mpd_client(
        host, port, timeout=timeout, factory=factory)
    if registry is not None:
        registry.acquire(client, close_mpd_client)
    try:
        yield client
    finally:
        if registry is not None:
            registry.release(client)
        close_mpd_client(client)


class MpdGateway:
    """Own one MPD command client and its reconnect/error semantics.

    Multi-command mutations deliberately remain outside ``call``/``write``:
    they need transaction-specific idempotency rather than per-command retry.
    """

    def __init__(self, client, host, port, *, state_changed=lambda _state: None,
                 connected=lambda: None, error=lambda _message: None):
        self.client = client
        self.host = host
        self.port = port
        self._state_changed = state_changed
        self._connected_callback = connected
        self._error = error
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def close(self) -> None:
        """Close socket-backed readers/writers before their peer disappears."""
        self._is_connected = False
        close_mpd_client(self.client)

    def mark_disconnected(self) -> None:
        was_connected = self._is_connected
        self.close()
        if was_connected:
            self._state_changed(False)

    def ensure_connected(self, silent: bool = False) -> bool:
        if self._is_connected:
            try:
                self.client.ping()
                return True
            except (MPDConnectionError, OSError):
                self.mark_disconnected()
        try:
            self.client.connect(self.host, self.port)
            self._is_connected = True
            self._state_changed(True)
            self._connected_callback()
            return True
        except (MPDConnectionError, OSError) as exc:
            self.mark_disconnected()
            if not silent:
                self._error(f"MPD not reachable at {self.host}:{self.port} ({exc})")
            return False

    def call(self, name: str, *args, default=None, quiet: bool = False):
        for attempt in (0, 1):
            if not self.ensure_connected(silent=attempt == 0):
                continue
            try:
                return getattr(self.client, name)(*args)
            except (MPDConnectionError, OSError):
                self.mark_disconnected()
            except CommandError as exc:
                if not quiet:
                    self._error(str(exc))
                return default
        return default

    def observe(self, name: str, *args, default=None, missing_ok=False,
                quiet: bool = False) -> MpdReadResult:
        """Read while preserving whether the result is authoritative.

        ``call`` intentionally offers a convenient default-only API. State
        that will feed a later write must also distinguish an expected MPD
        absence from transport failure, or a fallback value can overwrite
        durable data after reconnect.
        """
        for attempt in (0, 1):
            if not self.ensure_connected(silent=attempt == 0):
                continue
            try:
                return MpdReadResult(True, getattr(self.client, name)(*args))
            except (MPDConnectionError, OSError):
                self.mark_disconnected()
            except CommandError as exc:
                if missing_ok:
                    return MpdReadResult(True, default)
                if not quiet:
                    self._error(str(exc))
                return MpdReadResult(False, default)
        return MpdReadResult(False, default)

    def write(self, name: str, *args, quiet: bool = False) -> bool:
        for attempt in (0, 1):
            if not self.ensure_connected(silent=attempt == 0):
                continue
            try:
                getattr(self.client, name)(*args)
                return True
            except (MPDConnectionError, OSError):
                self.mark_disconnected()
            except CommandError as exc:
                if not quiet:
                    self._error(str(exc))
                return False
        return False

    def write_once(self, name: str, *args, quiet: bool = False) -> bool:
        """Issue a non-idempotent command at most once.

        A connection failure after dispatch has an ambiguous outcome: MPD may
        have applied the command before its reply was lost.  Replaying it can
        skip twice or corrupt relative queue edits, so reconnect is left to a
        later read instead.
        """
        if not self.ensure_connected():
            return False
        try:
            getattr(self.client, name)(*args)
            return True
        except (MPDConnectionError, OSError):
            self.mark_disconnected()
            if not quiet:
                self._error(
                    f"MPD connection lost while applying {name}; "
                    "the result may already be in effect")
            return False
        except CommandError as exc:
            if not quiet:
                self._error(str(exc))
            return False
