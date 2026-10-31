"""Pure sequencing policy for shuffled and gapless-aware queues."""

from __future__ import annotations

import os
import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueOrderPlan:
    start: int
    song_ids: tuple[str, ...] = ()
    blocked_reason: str = ""


class QueueSequencer:
    """Arrange files without owning playback or MPD state."""

    def __init__(self, *, tail_threshold_db: float = -21.0,
                 chain_limit: int = 3,
                 shuffle: Callable[[list[str]], None] = random.shuffle):
        self.tail_threshold_db = float(tail_threshold_db)
        self.chain_limit = max(0, int(chain_limit))
        self._shuffle = shuffle

    @staticmethod
    def artist_spread(files: Iterable[str], window: int = 1, *,
                      artist_keys: Mapping[str, str] | None = None) -> list[str]:
        """Greedily avoid nearby artists while retaining every track.

        Indexed artist tags are authoritative because Ampere's immediate
        parent directory is normally an album, not an artist. Callers without
        an index retain the conservative folder proxy used by older builds.
        """
        output: list[str] = []
        recent: list[str] = []
        remaining = [str(value) for value in files]
        artist_keys = artist_keys or {}
        window = max(0, int(window))
        while remaining:
            identities = [
                (artist_keys.get(candidate) or os.path.dirname(candidate))
                .strip().casefold()
                for candidate in remaining
            ]
            counts = Counter(identity for identity in identities if identity)
            eligible = []
            if window:
                for index, artist in enumerate(identities):
                    if not artist or artist not in recent:
                        eligible.append(index)
            else:
                eligible = list(range(len(remaining)))
            # Scheduling the most constrained artist first avoids painting the
            # tail into an adjacent-repeat corner when a valid spread exists.
            selected = min(
                eligible,
                key=lambda index: (-counts.get(identities[index], 0), index),
                default=0)
            file = remaining.pop(selected)
            artist = identities[selected]
            output.append(file)
            recent = (recent + [artist])[-window:] if window else []
        return output

    @staticmethod
    def album_successors(search_entries: Iterable[Mapping]) -> dict[str, str]:
        """Map each indexed file to the filename-sorted next album track."""
        by_directory: dict[str, list[str]] = {}
        for entry in search_entries:
            song = entry.get("song", {}) if isinstance(entry, Mapping) else {}
            file = str(song.get("file", "")) if isinstance(song, Mapping) else ""
            if file:
                by_directory.setdefault(os.path.dirname(file), []).append(file)
        successors: dict[str, str] = {}
        for files in by_directory.values():
            files.sort()
            successors.update(zip(files, files[1:]))
        return successors

    def extend_gapless(self, files: Iterable[str], *,
                       tail_levels: Mapping[str, float],
                       successors: Mapping[str, str]) -> list[str]:
        """Keep hot-ending album transitions together, without duplicates."""
        output: list[str] = []
        placed: set[str] = set()
        for value in files:
            file = str(value)
            if file in placed:
                continue
            output.append(file)
            placed.add(file)
            current = file
            for _hop in range(self.chain_limit):
                if tail_levels.get(current, -120.0) < self.tail_threshold_db:
                    break
                following = successors.get(current)
                if not following or following in placed:
                    break
                output.append(following)
                placed.add(following)
                current = following
        return output

    def shuffle_order(self, files: Iterable[str], *, window: int = 2,
                      artist_keys: Mapping[str, str] | None = None) -> list[str]:
        """Return a shuffled copy with nearby artist repetition deferred."""
        ordered = [str(file) for file in files]
        self._shuffle(ordered)
        return self.artist_spread(ordered, window, artist_keys=artist_keys)

    def reshuffle_upcoming(self, songs: Iterable[Mapping], queue_pos: int) \
            -> QueueOrderPlan:
        """Plan a membership-preserving stable-ID shuffle after the playhead."""
        queue = [song for song in songs if isinstance(song, Mapping)]
        if any(str(song.get("file", "")).startswith("/") for song in queue):
            return QueueOrderPlan(
                0, blocked_reason="Rendered DJ transitions cannot be reshuffled")
        try:
            position = int(queue_pos)
        except (TypeError, ValueError):
            position = -1
        start = max(0, min(len(queue), position + 1))
        upcoming = queue[start:]
        song_ids = [str(song.get("id", "")) for song in upcoming]
        if any(not song_id for song_id in song_ids):
            return QueueOrderPlan(
                start, blocked_reason="Queue snapshot has no stable IDs")
        if len(set(song_ids)) != len(song_ids):
            return QueueOrderPlan(
                start, blocked_reason="Queue snapshot has duplicate stable IDs")
        artist_keys = {
            song_id: str(song.get("artist", ""))
            for song_id, song in zip(song_ids, upcoming)
        }
        return QueueOrderPlan(
            start, tuple(self.shuffle_order(
                song_ids, artist_keys=artist_keys)))
