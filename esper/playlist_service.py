"""Stored-playlist application behavior over MPD persistence primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from .playlists import DISLIKED_PLAYLIST, LIKED_PLAYLIST, PlaylistRepository


@dataclass(frozen=True)
class PlaylistResult:
    ok: bool
    message: str = ""
    files: tuple[str, ...] = ()
    available: bool = True


@dataclass(frozen=True)
class PlaylistReadResult:
    success: bool
    files: tuple[str, ...] = ()
    tracks: tuple[dict, ...] = ()


def plan_queue_save(name: str, queue, count=0, *, existing=()) \
        -> PlaylistResult:
    """Validate and snapshot a queue save without retaining I/O callbacks."""
    name = str(name or "").strip()
    if not name:
        return PlaylistResult(False)
    if name in (LIKED_PLAYLIST, DISLIKED_PLAYLIST):
        return PlaylistResult(False, f"{name} is a built-in collection")
    queue = list(queue)
    if not queue:
        return PlaylistResult(False, "Queue is empty — nothing to save")
    saveable = [song for song in queue
                if song.get("file")
                and not str(song["file"]).startswith("/")]
    count = int(count)
    chosen = saveable[:count] if 0 < count < len(saveable) else saveable
    if not chosen:
        return PlaylistResult(False, "Queue has no saveable library tracks")
    action = "Replaced" if name in set(existing) else "Saved"
    return PlaylistResult(
        True, f"{action} playlist “{name}” ({len(chosen)} tracks)",
        tuple(str(song["file"]) for song in chosen))


class PlaylistService:
    """Own playlist validation, normalization, and safe mutation outcomes."""

    def __init__(self, repository: PlaylistRepository, *, read, write, refresh,
                 save_files, filter_allowed, normalize_song):
        self._repository = repository
        self._read = read
        self._write = write
        self._refresh = refresh
        self._save_files = save_files
        self._filter_allowed = filter_allowed
        self._normalize_song = normalize_song

    def tracks_result(self, name: str) -> PlaylistReadResult:
        rows = self._read("listplaylistinfo", name, default=None)
        if rows is None:
            return PlaylistReadResult(False)
        try:
            tracks = []
            files = []
            for position, row in enumerate(rows):
                if not isinstance(row, dict) or not row.get("file"):
                    return PlaylistReadResult(False)
                song = self._normalize_song(row)
                song["playlistPos"] = position
                tracks.append(song)
                if song.get("file"):
                    files.append(str(song["file"]))
        except Exception:
            return PlaylistReadResult(False)
        return PlaylistReadResult(
            True, tuple(files), tuple(tracks))

    @staticmethod
    def client_tracks_result(client, name: str, normalize_song) \
            -> PlaylistReadResult:
        """Decode display rows from a worker-owned MPD client."""
        try:
            rows = client.listplaylistinfo(name)
        except (CommandError, MPDConnectionError, OSError):
            return PlaylistReadResult(False)
        except Exception:
            return PlaylistReadResult(False)
        if rows is None:
            return PlaylistReadResult(False)
        try:
            tracks = []
            files = []
            for position, row in enumerate(rows):
                if not isinstance(row, Mapping) or not row.get("file"):
                    return PlaylistReadResult(False)
                song = normalize_song(dict(row))
                if not isinstance(song, dict) or not song.get("file"):
                    return PlaylistReadResult(False)
                song["playlistPos"] = position
                tracks.append(song)
                files.append(str(song["file"]))
        except Exception:
            return PlaylistReadResult(False)
        return PlaylistReadResult(True, tuple(files), tuple(tracks))

    @staticmethod
    def client_files_result(client, name: str) -> PlaylistReadResult:
        """Read a playlist on a worker client without hiding transport loss."""
        try:
            rows = client.listplaylistinfo(name)
        except CommandError:
            # Curated exemplar playlists are optional; MPD explicitly saying
            # one does not exist is authoritative absence, not an outage.
            return PlaylistReadResult(True)
        except (MPDConnectionError, OSError):
            return PlaylistReadResult(False)
        except Exception:
            return PlaylistReadResult(False)
        if rows is None:
            return PlaylistReadResult(False)
        try:
            files = tuple(str(row["file"]) for row in rows
                          if isinstance(row, Mapping) and row.get("file"))
            if len(files) != len(rows):
                return PlaylistReadResult(False)
        except (TypeError, ValueError):
            return PlaylistReadResult(False)
        return PlaylistReadResult(True, files)

    def tracks(self, name: str) -> list[dict]:
        return list(self.tracks_result(name).tracks)

    def files_result(self, name: str) -> PlaylistReadResult:
        rows = self._read("listplaylistinfo", name, default=None)
        if rows is None:
            return PlaylistReadResult(False)
        try:
            files = []
            for row in rows:
                if not isinstance(row, dict) or not row.get("file"):
                    return PlaylistReadResult(False)
                files.append(str(row["file"]))
        except Exception:
            return PlaylistReadResult(False)
        return PlaylistReadResult(True, tuple(files))

    def files(self, name: str) -> list[str]:
        return list(self.files_result(name).files)

    def rename(self, old_name: str, new_name: str) -> PlaylistResult:
        old_name, new_name = old_name.strip(), new_name.strip()
        allowed, message = self._repository.can_rename(old_name, new_name)
        if not allowed:
            return PlaylistResult(False, message)
        if old_name not in self._repository.snapshot.playlists:
            return PlaylistResult(False, "Playlist no longer exists")
        wrote = self._write("rename", old_name, new_name, quiet=True)
        refreshed = bool(self._refresh())
        names = self._repository.snapshot.playlists
        committed = new_name in names and old_name not in names
        if wrote or (refreshed and committed):
            return PlaylistResult(True)
        if not refreshed:
            return PlaylistResult(
                False,
                "Playlist rename could not be confirmed — refresh collections before retrying",
                available=False)
        return PlaylistResult(False, "Playlist rename was not applied")

    def delete(self, name: str) -> PlaylistResult:
        name = name.strip()
        allowed, message = self._repository.can_delete(name)
        if not allowed:
            return PlaylistResult(False, message)
        if name not in self._repository.snapshot.playlists:
            return PlaylistResult(False, "Playlist no longer exists")
        wrote = self._write("rm", name, quiet=True)
        refreshed = bool(self._refresh())
        committed = name not in self._repository.snapshot.playlists
        if wrote or (refreshed and committed):
            return PlaylistResult(True)
        if not refreshed:
            return PlaylistResult(
                False,
                "Playlist deletion could not be confirmed — refresh collections before retrying",
                available=False)
        return PlaylistResult(False, "Playlist deletion was not applied")

    def remove_position_result(self, name: str, position: int) -> PlaylistResult:
        read = self.files_result(name)
        if not read.success:
            return PlaylistResult(
                False, "Playlist is unavailable — reconnect and try again",
                available=False)
        files = list(read.files)
        position = int(position)
        if not name or position < 0 or position >= len(files):
            return PlaylistResult(False)
        del files[position]
        if not self._save_files(name, files):
            return PlaylistResult(
                False, "Playlist edit could not be saved — the previous copy is intact")
        return PlaylistResult(True)

    def remove_position(self, name: str, position: int) -> bool:
        return self.remove_position_result(name, position).ok

    def move_position_result(self, name: str, old_position: int,
                             new_position: int) -> PlaylistResult:
        read = self.files_result(name)
        if not read.success:
            return PlaylistResult(
                False, "Playlist is unavailable — reconnect and try again",
                available=False)
        files = list(read.files)
        old_position, new_position = int(old_position), int(new_position)
        if (not name or old_position < 0 or old_position >= len(files)
                or new_position < 0 or new_position >= len(files)
                or old_position == new_position):
            return PlaylistResult(False)
        file = files.pop(old_position)
        files.insert(new_position, file)
        if not self._save_files(name, files):
            return PlaylistResult(
                False, "Playlist edit could not be saved — the previous copy is intact")
        return PlaylistResult(True)

    def move_position(self, name: str, old_position: int,
                      new_position: int) -> bool:
        return self.move_position_result(name, old_position, new_position).ok

    def load(self, name: str) -> PlaylistResult:
        read = self.files_result(name)
        if not read.success:
            return PlaylistResult(
                False, "Playlist is unavailable — reconnect and try again",
                available=False)
        files = self._filter_allowed(read.files)
        if not files:
            message = ("Playlist is empty" if not read.files else
                       "Everything in there is disliked")
            return PlaylistResult(False, message)
        return PlaylistResult(True, files=tuple(files))

    def save_queue(self, name: str, queue, count=0) -> PlaylistResult:
        plan = self.plan_queue_save(name, queue, count)
        if not plan.ok:
            return plan
        if not self._save_files(name, plan.files):
            return PlaylistResult(
                False, "Playlist could not be saved — the previous copy is intact")
        return plan

    def plan_queue_save(self, name: str, queue, count=0) -> PlaylistResult:
        """Validate and snapshot a queue save before asynchronous persistence."""
        return plan_queue_save(
            name, queue, count,
            existing=self._repository.snapshot.playlists)
