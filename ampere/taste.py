"""Durable like, dislike, and rating behavior backed by MPD stores."""

from __future__ import annotations

from dataclasses import dataclass

from .playlists import DISLIKED_PLAYLIST, LIKED_PLAYLIST, PlaylistRepository


@dataclass(frozen=True)
class TasteUpdate:
    attempted: bool = False
    success: bool = False
    liked_changed: bool = False
    disliked_changed: bool = False
    skip_current: bool = False
    rollback_complete: bool = True


@dataclass(frozen=True)
class TasteRefreshResult:
    success: bool
    changed: bool
    files: tuple[str, ...]


class TasteService:
    """Own taste mutations while MPD remains the persistence engine."""

    def __init__(self, repository: PlaylistRepository, *, read, write,
                 replace_files):
        self._repository = repository
        self._read = read
        self._write = write
        self._replace_files = replace_files

    @property
    def liked(self) -> tuple[str, ...]:
        return self._repository.snapshot.liked

    @property
    def disliked(self) -> tuple[str, ...]:
        return self._repository.snapshot.disliked

    def refresh_liked_result(self) -> TasteRefreshResult:
        rows = self._read("listplaylist", LIKED_PLAYLIST, default=None)
        if rows is None:
            return TasteRefreshResult(False, False, self.liked)
        try:
            changed = self._repository.replace_liked(rows)
        except Exception:
            return TasteRefreshResult(False, False, self.liked)
        return TasteRefreshResult(True, changed, self.liked)

    def refresh_liked(self) -> bool:
        return self.refresh_liked_result().changed

    def refresh_disliked_result(self) -> TasteRefreshResult:
        rows = self._read("listplaylist", DISLIKED_PLAYLIST, default=None)
        if rows is None:
            return TasteRefreshResult(False, False, self.disliked)
        try:
            changed = self._repository.replace_disliked(rows)
        except Exception:
            return TasteRefreshResult(False, False, self.disliked)
        return TasteRefreshResult(True, changed, self.disliked)

    def refresh_disliked(self) -> bool:
        return self.refresh_disliked_result().changed

    def _replace_collection(self, name: str, desired,
                            refresh) -> TasteRefreshResult:
        desired = tuple(str(file) for file in desired if file)
        self._replace_files(name, desired)
        result = refresh()
        return TasteRefreshResult(
            result.success and result.files == desired,
            result.changed, result.files)

    def toggle_like(self, file: str) -> TasteUpdate:
        if not file:
            return TasteUpdate()
        disliked_changed = False
        if file in self.liked:
            desired = tuple(item for item in self.liked if item != file)
        else:
            desired = self.liked + (file,)
        try:
            result = self._replace_collection(
                LIKED_PLAYLIST, desired, self.refresh_liked_result)
        except Exception:
            return TasteUpdate(attempted=True)
        if not result.success:
            return TasteUpdate(attempted=True)
        adding = file in desired
        if adding and file in self.disliked:
            disliked = tuple(
                item for item in self.disliked if item != file)
            try:
                disliked_result = self._replace_collection(
                    DISLIKED_PLAYLIST, disliked,
                    self.refresh_disliked_result)
            except Exception:
                disliked_result = TasteRefreshResult(
                    False, False, self.disliked)
            if not disliked_result.success:
                # Like and Dislike describe opposite durable intent. If the
                # secondary Disliked edit cannot commit, undo the new Like so
                # callers never publish contradictory state.
                rollback = tuple(item for item in desired if item != file)
                try:
                    rollback_result = self._replace_collection(
                        LIKED_PLAYLIST, rollback,
                        self.refresh_liked_result)
                    rollback_complete = (
                        rollback_result.success
                        and rollback_result.files == rollback)
                except Exception:
                    rollback_complete = False
                return TasteUpdate(
                    attempted=True, rollback_complete=rollback_complete)
            disliked_changed = disliked_result.changed
        return TasteUpdate(
            attempted=True, success=True,
            liked_changed=result.changed,
            disliked_changed=disliked_changed)

    def toggle_dislike(self, file: str, *, current_file="") -> TasteUpdate:
        if not file:
            return TasteUpdate()
        liked_changed = False
        if file in self.disliked:
            desired = tuple(item for item in self.disliked if item != file)
        else:
            desired = self.disliked + (file,)
        try:
            result = self._replace_collection(
                DISLIKED_PLAYLIST, desired, self.refresh_disliked_result)
        except Exception:
            return TasteUpdate(attempted=True)
        if not result.success:
            return TasteUpdate(attempted=True)
        adding = file in desired
        if adding and file in self.liked:
            liked = tuple(item for item in self.liked if item != file)
            try:
                liked_result = self._replace_collection(
                    LIKED_PLAYLIST, liked, self.refresh_liked_result)
            except Exception:
                liked_result = TasteRefreshResult(False, False, self.liked)
            if not liked_result.success:
                # Preserve the mutual-exclusion invariant. If the secondary
                # Liked edit cannot commit, undo the primary Disliked edit
                # through the same verified transaction boundary.
                rollback = tuple(item for item in desired if item != file)
                try:
                    rollback_result = self._replace_collection(
                        DISLIKED_PLAYLIST, rollback,
                        self.refresh_disliked_result)
                    rollback_complete = (
                        rollback_result.success
                        and rollback_result.files == rollback)
                except Exception:
                    rollback_complete = False
                return TasteUpdate(
                    attempted=True, rollback_complete=rollback_complete)
            liked_changed = liked_result.changed
        return TasteUpdate(
            attempted=True,
            success=True,
            liked_changed=liked_changed,
            disliked_changed=result.changed,
            skip_current=adding and file == current_file)

    def rating(self, file: str) -> float:
        if not file:
            return 0.0
        value = self._read(
            "sticker_get", "song", file, "rating", default="", quiet=True)
        return self._repository.decode_rating(value)

    def set_rating(self, file: str, stars: float) -> tuple[bool, float]:
        if not file:
            return False, 0.0
        stars = self._repository.clamp_rating(stars)
        if stars <= 0:
            ok = self._write(
                "sticker_delete", "song", file, "rating", quiet=True)
        else:
            ok = self._write(
                "sticker_set", "song", file, "rating",
                str(int(stars * 2)))
        return bool(ok), stars
