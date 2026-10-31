"""Failure-safe replacement transactions for generated MPD playlists."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from .mpdgateway import close_mpd_client


@dataclass(frozen=True)
class PlaylistRecovery:
    catalog_available: bool
    committed: bool = False
    restored: bool = False
    stage_removed: bool = False


class GeneratedPlaylistWriter:
    def __init__(self, client, *, ensure_connected: Callable[..., bool],
                 list_playlists: Callable[[], Iterable],
                 write: Callable[..., bool], refresh: Callable[[], None],
                 connection_failed: Callable[[], None] | None = None,
                 token: Callable[[], str] | None = None):
        self._client = client
        self._ensure_connected = ensure_connected
        self._list_playlists = list_playlists
        self._write = write
        self._refresh = refresh
        self._connection_failed = connection_failed or (lambda: None)
        self._token = token or (lambda: uuid.uuid4().hex)
        self.last_recovery = PlaylistRecovery(True)

    def save(self, name, files, *, existing=()) -> bool:
        name = str(name or "").strip()
        files = tuple(str(file) for file in files if file)
        if not name or not files or not self._ensure_connected(silent=True):
            return False
        stage = f".ampere-stage-{self._token()}"
        backup = f".ampere-backup-{self._token()}"
        replaces = name in set(existing)
        install_started = False
        try:
            self._client.command_list_ok_begin()
            for file in files:
                self._client.playlistadd(stage, file)
            self._client.command_list_end()
            install_started = True
            self._client.command_list_ok_begin()
            if replaces:
                self._client.rename(name, backup)
            self._client.rename(stage, name)
            self._client.command_list_end()
            if replaces:
                self._write("rm", backup, quiet=True)
            self._refresh()
            return True
        except (MPDConnectionError, OSError, CommandError) as exc:
            if isinstance(exc, (MPDConnectionError, OSError)):
                self._connection_failed()
                close_mpd_client(self._client)
            recovery = self._recover(
                name, stage, backup, replaces=replaces,
                install_started=install_started)
            self.last_recovery = recovery
            if recovery.committed:
                self._refresh()
                return True
            return False

    def _recover(self, name, stage, backup, *, replaces, install_started):
        def write(command, *args):
            try:
                return bool(self._write(command, *args, quiet=True))
            except Exception:
                return False

        try:
            if not self._ensure_connected(silent=True):
                return PlaylistRecovery(False)
            rows = self._list_playlists()
            if rows is None:
                # With no authoritative catalog, restoring backup→name is
                # idempotent and safest: it succeeds only when name is absent.
                restored = write("rename", backup, name)
                removed = write("rm", stage)
                return PlaylistRecovery(
                    False, restored=restored, stage_removed=removed)
            names = {row.get("playlist", "") if isinstance(row, dict) else str(row)
                     for row in rows}
            # A destination may have been created by another client after
            # our catalog read. Our unique stage disappears only when its
            # installation succeeds; destination existence alone proves nothing.
            committed = (install_started and stage not in names
                         and name in names and (not replaces or backup in names))
            if committed:
                # The install completed and only its reply/cleanup was lost.
                if backup in names:
                    write("rm", backup)
                removed = write("rm", stage) if stage in names else False
                return PlaylistRecovery(
                    True, committed=True, stage_removed=removed)
            restored = False
            if name not in names and backup in names:
                restored = write("rename", backup, name)
            removed = write("rm", stage) if stage in names else False
            return PlaylistRecovery(
                True, restored=restored, stage_removed=removed)
        except Exception:
            return PlaylistRecovery(False)
