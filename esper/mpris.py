"""MPRIS2 for Ampere, served by the app itself.

Ampere used to borrow its MPRIS presence from `mpd-mpris`, a separate daemon
that watched MPD and mirrored it onto the bus.  That daemon writes as well as
reads: on every position change it called its own ``SetPosition``, which
issues ``seekid`` back to MPD (proven 2026-07-29 — the call never appears on
the session bus, so no client asks for it).  Mid-song the echo is harmless;
at a song change it lands MPD's *reported* position — which during a
crossfade runs ahead of what the speakers are playing — onto the new track,
so every transition seeked a few seconds in and flushed the output buffer.
That was the audible "skips between songs".

So the player owns its own bus presence now.  The one law this file exists to
keep: **nothing in here ever moves playback on its own.**  Every seek, skip
and pause below happens because a client on the bus asked for it in that
moment.  Position is a property clients read; it is never written back.

Transport calls land on Backend's ordinary slots, so bus-driven skips inherit
the same `_soft_move` volume ride as in-app ones.
"""
from __future__ import annotations

from ampere.compat import cache_path
import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtDBus import (QDBusConnection, QDBusMessage, QDBusObjectPath,
                            QDBusVariant, QDBusVirtualObject)

SERVICE = "org.mpris.MediaPlayer2.ampere"
PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECT_IFACE = "org.freedesktop.DBus.Introspectable"   # answered by Qt

ART_CACHE = Path(cache_path('art'))
# The art cache stores a 1-pixel file as its "no art here" marker; anything
# that small must not be handed to a bar widget as a cover.
ART_MIN_BYTES = 1024

INTROSPECT_XML = """
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg name="Offset" type="x" direction="in"/>
    </method>
    <method name="SetPosition">
      <arg name="TrackId" type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <method name="OpenUri">
      <arg name="Uri" type="s" direction="in"/>
    </method>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
"""


def _us(seconds: float) -> int:
    """Seconds -> microseconds, MPRIS's unit for positions and lengths.

    ⚠ PySide6 picks the D-Bus integer width from the VALUE, not the declared
    signature: anything under 2^31 goes out as `i`, above it as `x`. So a
    4-minute track's length is int32 on the wire while an hour-long one is
    int64. Qt-based clients (the bar, KDE Connect) convert either way, which is
    why this is left alone; a GLib client doing a strict `get_int64` would
    object. There is no way to force the width from PySide6 — QDBusArgument
    has no typed `add()` and ClassInfo-declared adaptors don't export here
    (both tried 2026-07-29). Forcing it would mean a C++ helper or a pure
    Python bus library.
    """
    return int(seconds * 1_000_000)


def _art_url(rel: str) -> str:
    """file:// URL of the cached cover, or "" when there isn't a real one.

    Reads the cache only — never decodes art here.  The prefetch worker warms
    these files ahead of each transition, and a bar widget missing a cover for
    one song is a far smaller sin than blocking the GUI thread on a decode.
    """
    if not rel:
        return ""
    f = ART_CACHE / (hashlib.sha1(rel.encode(), usedforsecurity=False).hexdigest() + ".jpg")
    try:
        if f.stat().st_size >= ART_MIN_BYTES:
            return f.as_uri()
    except OSError:
        pass
    return ""


class _MprisObject(QDBusVirtualObject):
    """Raw message handling for the MPRIS object.

    A virtual object (rather than an adaptor) keeps the wire types under our
    control: MPRIS is strict about `x` positions and the `a{sv}` metadata map,
    and clients like KDE Connect parse them literally.
    """

    def __init__(self, service: "MprisService"):
        super().__init__()
        self._svc = service

    def introspect(self, path: str) -> str:
        return INTROSPECT_XML

    def handleMessage(self, message: QDBusMessage, connection: QDBusConnection) -> bool:
        iface, member = message.interface(), message.member()
        args = message.arguments()
        try:
            # Introspect is Qt's to answer — it wraps introspect() above in the
            # <node> envelope. Replying here too would put two replies on the
            # wire for one call.
            if iface == PROPS_IFACE:
                return self._props(message, connection, member, args)
            if iface == ROOT_IFACE:
                return self._root(message, connection, member)
            if iface == PLAYER_IFACE:
                return self._player(message, connection, member, args)
        except Exception as exc:                       # never kill the bus loop
            connection.send(message.createErrorReply(
                "org.mpris.MediaPlayer2.Error", str(exc)))
            return True
        return False

    # ---- org.freedesktop.DBus.Properties ---------------------------------

    def _reply(self, message, connection, args) -> bool:
        """Send a reply with an explicit argument list.

        createReply(list) marshals the list itself as ONE array argument, which
        silently turns a property read into `as`; setArguments is the only way
        to say "these are the arguments".
        """
        reply = message.createReply()
        reply.setArguments(args)
        connection.send(reply)
        return True

    def _props(self, message, connection, member, args) -> bool:
        if member == "Get" and len(args) >= 2:
            value = self._svc.get_property(str(args[0]), str(args[1]))
            if value is None:
                connection.send(message.createErrorReply(
                    "org.freedesktop.DBus.Error.UnknownProperty", str(args[1])))
                return True
            return self._reply(message, connection, [QDBusVariant(value)])
        if member == "GetAll" and args:
            # A plain dict already marshals as a{sv} — wrapping the values in
            # QDBusVariant too would nest a variant inside a variant, which
            # clients read as an opaque box instead of a string.
            return self._reply(message, connection,
                               [self._svc.all_properties(str(args[0]))])
        if member == "Set" and len(args) >= 3:
            raw = args[2]
            self._svc.set_property(str(args[0]), str(args[1]),
                                   raw.variant() if isinstance(raw, QDBusVariant) else raw)
            return self._reply(message, connection, [])
        return False

    # ---- org.mpris.MediaPlayer2 ------------------------------------------

    def _root(self, message, connection, member) -> bool:
        if member == "Raise":
            self._svc.raise_window()
        elif member == "Quit":
            self._svc.quit_app()
        else:
            return False
        connection.send(message.createReply())
        return True

    # ---- org.mpris.MediaPlayer2.Player -----------------------------------

    def _player(self, message, connection, member, args) -> bool:
        svc = self._svc
        if member == "Next":
            svc.backend.requestNext()
        elif member == "Previous":
            svc.backend.requestPrevious()
        elif member == "Pause":
            svc.pause()
        elif member == "PlayPause":
            svc.backend.requestPlayPause()
        elif member == "Stop":
            svc.backend.requestTransport("stop")
        elif member == "Play":
            svc.play()
        elif member == "Seek" and args:
            svc.seek_relative(int(args[0]))
        elif member == "SetPosition" and len(args) >= 2:
            svc.set_position(args[0], int(args[1]))
        elif member == "OpenUri":
            return False                               # library-only player
        else:
            return False
        connection.send(message.createReply())
        return True


class MprisService(QObject):
    """Publishes Ampere on the session bus and keeps clients in sync.

    Property changes are diffed before they go out: Backend's statusChanged
    fires once a second while playing, and a bar widget does not need a
    PropertiesChanged storm to redraw the same values.  Position is left out
    of the signal entirely, exactly as the spec wants — clients poll it or
    track it themselves, and `Seeked` covers the jumps.
    """

    def __init__(self, backend, app, window_cb=None):
        super().__init__()
        self.backend = backend
        self._app = app
        self._window_cb = window_cb
        self._obj = _MprisObject(self)
        self._last = {}
        self._last_pos = 0.0
        self._last_song = ""
        self._registered = False

        conn = QDBusConnection.sessionBus()
        if not conn.isConnected():
            print("MPRIS: no session bus — skipping", flush=True)
            return
        if not conn.registerVirtualObject(PATH, self._obj,
                                          QDBusConnection.VirtualObjectRegisterOption.SingleNode):
            print("MPRIS: could not register object", flush=True)
            return
        if not conn.registerService(SERVICE):
            print(f"MPRIS: could not take {SERVICE} (another instance?)", flush=True)
            conn.unregisterObject(PATH)
            return
        self._registered = True

        backend.statusChanged.connect(self._on_change)
        backend.songChanged.connect(self._on_change)
        # Seeked is about jumps a client didn't make itself, so it needs a
        # clock of its own: compare where playback IS against where a second
        # of wall time says it should be.
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(1000)
        self._pos_timer.timeout.connect(self._check_seek)
        self._pos_timer.start()
        self._last = self.all_properties(PLAYER_IFACE)
        self._last_pos = float(backend.elapsed)
        self._last_song = (backend.currentSong or {}).get("file", "")
        print(f"MPRIS: serving {SERVICE}", flush=True)

    # ---- teardown --------------------------------------------------------

    def shutdown(self):
        if not self._registered:
            return
        conn = QDBusConnection.sessionBus()
        conn.unregisterService(SERVICE)
        conn.unregisterObject(PATH)
        self._registered = False

    # ---- property reads --------------------------------------------------

    def _metadata(self) -> dict:
        b = self.backend
        song = b.currentSong or {}
        file = song.get("file", "")
        sid = int(song.get("id", -1))
        meta = {
            # A track id must be a unique object path; MPD's queue id is
            # exactly that identity, and "/NoTrack" is the spec's null.
            "mpris:trackid": QDBusObjectPath(
                f"/org/ampere/Track/{sid}" if sid >= 0
                else "/org/mpris/MediaPlayer2/TrackList/NoTrack"),
            "mpris:length": _us(float(song.get("duration", 0.0))),
            "xesam:title": song.get("title", ""),
            "xesam:album": song.get("album", ""),
            "xesam:artist": [song.get("artist", "")] if song.get("artist") else [],
        }
        art = _art_url(file)
        if art:
            meta["mpris:artUrl"] = art
        if file:
            meta["xesam:url"] = Path(
                os.path.expanduser("~/MusicLibrary")).joinpath(file).as_uri()
        return meta

    def _loop_status(self) -> str:
        if getattr(self.backend, "single", False) and self.backend.repeat:
            return "Track"
        return "Playlist" if self.backend.repeat else "None"

    def get_property(self, iface: str, name: str):
        b = self.backend
        if iface == ROOT_IFACE:
            return {
                "CanQuit": True,
                "CanRaise": True,
                "HasTrackList": False,
                "Identity": "Ampere",
                "DesktopEntry": "ampere",
                # Ampere is library-first and deliberately does not implement
                # OpenUri. Advertising file/audio support while rejecting the
                # method made MPRIS clients offer a broken “open with” route.
                "SupportedUriSchemes": [],
                "SupportedMimeTypes": [],
            }.get(name)
        if iface != PLAYER_IFACE:
            return None
        state = b.state
        return {
            "PlaybackStatus": {"play": "Playing", "pause": "Paused"}.get(state, "Stopped"),
            "LoopStatus": self._loop_status(),
            "Rate": 1.0,
            "Shuffle": bool(b.random),
            "Metadata": self._metadata(),
            "Volume": float(b.volume) / 100.0,
            "Position": _us(float(b.elapsed)),
            "MinimumRate": 1.0,
            "MaximumRate": 1.0,
            "CanGoNext": True,
            "CanGoPrevious": True,
            "CanPlay": True,
            "CanPause": True,
            "CanSeek": float(b.duration) > 0,
            "CanControl": True,
        }.get(name)

    def all_properties(self, iface: str) -> dict:
        names = {
            ROOT_IFACE: ("CanQuit", "CanRaise", "HasTrackList", "Identity",
                         "DesktopEntry", "SupportedUriSchemes", "SupportedMimeTypes"),
            PLAYER_IFACE: ("PlaybackStatus", "LoopStatus", "Rate", "Shuffle",
                           "Metadata", "Volume", "Position", "MinimumRate",
                           "MaximumRate", "CanGoNext", "CanGoPrevious", "CanPlay",
                           "CanPause", "CanSeek", "CanControl"),
        }.get(iface, ())
        return {n: self.get_property(iface, n) for n in names}

    # ---- property writes (clients only) ----------------------------------

    def set_property(self, iface: str, name: str, value):
        if iface != PLAYER_IFACE:
            return
        b = self.backend
        if name == "Volume":
            b.requestVolume(int(round(float(value) * 100)))
        elif name == "Shuffle":
            b.requestRandom(bool(value))
        elif name == "LoopStatus":
            loop = str(value)
            if loop in ("Track", "Playlist", "None"):
                b.requestLoopStatus(loop)

    # ---- transport helpers ------------------------------------------------

    def play(self):
        self.backend.requestTransport("play")

    def pause(self):
        self.backend.requestTransport("pause")

    def seek_relative(self, offset_us: int):
        target = float(self.backend.elapsed) + offset_us / 1_000_000
        self.backend.requestSeek(max(0.0, target))

    def set_position(self, track_id, position_us: int):
        """Spec-correct SetPosition: a stale track id is ignored.

        This guard is the whole reason the old daemon hurt — it applied a
        position captured against one track to whatever was playing when the
        call landed.  A song change between read and write must be a no-op,
        not a seek.
        """
        want = str(track_id)
        current = str(self._metadata().get("mpris:trackid", ""))
        if want and want != current:
            return
        self.backend.requestSeek(max(0.0, position_us / 1_000_000))

    def raise_window(self):
        if callable(self._window_cb):
            self._window_cb()

    def quit_app(self):
        self._app.quit()

    # ---- change notification ---------------------------------------------

    @Slot()
    def _on_change(self):
        if not self._registered:
            return
        now = self.all_properties(PLAYER_IFACE)
        now.pop("Position", None)                      # never in PropertiesChanged
        changed = {k: v for k, v in now.items() if self._last.get(k) != v}
        self._last.update(now)
        if not changed:
            return
        msg = QDBusMessage.createSignal(PATH, PROPS_IFACE, "PropertiesChanged")
        msg.setArguments([PLAYER_IFACE, changed, []])
        QDBusConnection.sessionBus().send(msg)

    def _check_seek(self):
        if not self._registered:
            return
        pos = float(self.backend.elapsed)
        song = (self.backend.currentSong or {}).get("file", "")
        expected = self._last_pos + (1.0 if self.backend.state == "play" else 0.0)
        changed_song = song != self._last_song
        self._last_pos, self._last_song = pos, song
        # A new song resets the clock legitimately — and under a crossfade it
        # starts several seconds in, which reads exactly like a seek. Only
        # report jumps that happen inside one track.
        if changed_song:
            return
        if abs(pos - expected) > 1.0 and pos > 0.0:
            msg = QDBusMessage.createSignal(PATH, PLAYER_IFACE, "Seeked")
            msg.setArguments([int(pos * 1_000_000)])
            QDBusConnection.sessionBus().send(msg)
