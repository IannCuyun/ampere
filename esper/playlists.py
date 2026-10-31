"""Playlist, like/dislike, and rating-domain rules for Ampere."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

LIKED_PLAYLIST = "Liked"
DISLIKED_PLAYLIST = "Disliked"


def playlist_files(rows: Iterable) -> tuple[str, ...]:
    files = []
    for row in rows:
        file = row.get("file") if isinstance(row, dict) else row
        if file:
            files.append(str(file))
    return tuple(files)


@dataclass(frozen=True)
class CollectionSnapshot:
    playlists: tuple[str, ...] = ()
    liked: tuple[str, ...] = ()
    disliked: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaylistPublication:
    success: bool
    changed: bool
    playlists: tuple[str, ...]


class PlaylistRepository:
    """Own normalized collection state; MPD remains the persistence engine."""

    def __init__(self):
        self._snapshot = CollectionSnapshot()

    @property
    def snapshot(self) -> CollectionSnapshot:
        return self._snapshot

    def replace_snapshot(self, *, playlists=(), liked=(), disliked=()) \
            -> tuple[bool, bool, bool]:
        """Atomically publish one complete collection generation."""
        normalized = CollectionSnapshot(
            tuple(str(name) for name in playlists if name),
            tuple(str(file) for file in liked if file),
            tuple(str(file) for file in disliked if file))
        previous = self._snapshot
        self._snapshot = normalized
        return (normalized.playlists != previous.playlists,
                normalized.liked != previous.liked,
                normalized.disliked != previous.disliked)

    def replace_playlists(self, rows: Iterable[dict]) -> bool:
        names = tuple(sorted(row.get("playlist", "") for row in rows
                             if row.get("playlist")
                             and row.get("playlist") != DISLIKED_PLAYLIST))
        if names == self._snapshot.playlists:
            return False
        self._snapshot = CollectionSnapshot(names, self._snapshot.liked,
                                            self._snapshot.disliked)
        return True

    def publish_playlists(self, rows) -> PlaylistPublication:
        if rows is None:
            return PlaylistPublication(
                False, False, self._snapshot.playlists)
        try:
            changed = self.replace_playlists(rows)
        except Exception:
            return PlaylistPublication(
                False, False, self._snapshot.playlists)
        return PlaylistPublication(
            True, changed, self._snapshot.playlists)

    def replace_liked(self, rows: Iterable) -> bool:
        liked = playlist_files(rows)
        if liked == self._snapshot.liked:
            return False
        self._snapshot = CollectionSnapshot(self._snapshot.playlists, liked,
                                            self._snapshot.disliked)
        return True

    def replace_disliked(self, rows: Iterable) -> bool:
        disliked = playlist_files(rows)
        if disliked == self._snapshot.disliked:
            return False
        self._snapshot = CollectionSnapshot(self._snapshot.playlists,
                                            self._snapshot.liked, disliked)
        return True

    def filter_allowed(self, files: Sequence[str], keep: str = "") -> list[str]:
        disliked = set(self._snapshot.disliked)
        return [file for file in files if file == keep or file not in disliked]

    def can_rename(self, old_name: str, new_name: str) -> tuple[bool, str]:
        old_name, new_name = old_name.strip(), new_name.strip()
        if not old_name or not new_name or old_name == new_name:
            return False, ""
        if old_name in (LIKED_PLAYLIST, DISLIKED_PLAYLIST):
            return False, f"{old_name} is a built-in collection"
        if new_name in (LIKED_PLAYLIST, DISLIKED_PLAYLIST):
            return False, f"{new_name} is a built-in collection"
        if new_name in self._snapshot.playlists:
            return False, f"A playlist named “{new_name}” already exists"
        return True, ""

    @staticmethod
    def can_delete(name: str) -> tuple[bool, str]:
        name = name.strip()
        if not name:
            return False, ""
        if name in (LIKED_PLAYLIST, DISLIKED_PLAYLIST):
            return False, f"{name} is a built-in collection"
        return True, ""

    @staticmethod
    def clamp_rating(stars: float) -> float:
        return max(0.0, min(5.0, round(float(stars) * 2) / 2.0))

    @staticmethod
    def decode_rating(value) -> float:
        try:
            raw = value.split("=", 1)[1] if "=" in value else value
            return max(0.0, min(5.0, int(raw) / 2.0))
        except (TypeError, ValueError):
            return 0.0
