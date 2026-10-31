"""Pure rediscovery-shelf selection over an explicit library snapshot."""

from __future__ import annotations

import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ArrivalSnapshotResult:
    success: bool
    rows: tuple[dict, ...]
    retained: bool = False


class ShelfService:
    """Own the policy behind Ampere's computed rediscovery shelves."""

    NAMES = ("arrivals", "heavy", "loved", "deep", "throwback", "history")

    def __init__(self, *, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
        self._clock = clock
        self._rng = rng or random.Random()
        self._arrivals: tuple[dict, ...] = ()
        self._arrivals_verified = False

    def publish_arrivals(self, items) -> ArrivalSnapshotResult:
        """Accept only a complete MPD modified-time search snapshot."""
        if not isinstance(items, (list, tuple)):
            return ArrivalSnapshotResult(
                False, self._arrivals, retained=self._arrivals_verified)
        rows = []
        for item in items:
            if not isinstance(item, Mapping):
                return ArrivalSnapshotResult(
                    False, self._arrivals, retained=self._arrivals_verified)
            file = item.get("file")
            modified = item.get("last-modified", "")
            if not isinstance(file, str) or not file:
                return ArrivalSnapshotResult(
                    False, self._arrivals, retained=self._arrivals_verified)
            if not isinstance(modified, str):
                return ArrivalSnapshotResult(
                    False, self._arrivals, retained=self._arrivals_verified)
            rows.append(dict(item))
        self._arrivals = tuple(rows)
        self._arrivals_verified = True
        return ArrivalSnapshotResult(True, self._arrivals)

    def select(self, name: str, *, library: Mapping[str, Mapping],
               search_index: Sequence[Mapping], disliked: Sequence[str],
               liked: Sequence[str], last_raw: Mapping[str, object],
               counts: Mapping[str, int], ratings: Mapping[str, object],
               arrivals: Sequence[Mapping] = ()) -> list[dict]:
        now = self._clock()
        last = self._integers(last_raw)
        hidden = set(disliked)

        def rows(triples, cap=150):
            result = []
            for _, file, when in triples[:cap]:
                song = library.get(file)
                if song and file not in hidden:
                    row = dict(song)
                    row["when"] = when
                    result.append(row)
            return result

        if name == "deep":
            share: dict[str, int] = {}
            for file, count in counts.items():
                subgenre = "/".join(file.split("/")[:2])
                share[subgenre] = share.get(subgenre, 0) + count
            triples = []
            for entry in search_index:
                file = entry["song"]["file"]
                plays = counts.get(file, 0)
                affinity = share.get("/".join(file.split("/")[:2]), 0)
                if plays > 2 or file.startswith("Incoming") or affinity <= 0:
                    continue
                score = -(affinity + self._rng.random() * affinity * 0.5)
                triples.append((score, file,
                                f"{plays} plays" if plays else "never played"))
            triples.sort(key=lambda item: item[0])
            return rows(triples)

        if name == "arrivals":
            triples = []
            for song in arrivals:
                file = song.get("file")
                if file and file in library:
                    triples.append((song.get("last-modified", ""), file, 0))
            triples.sort(key=lambda item: item[0], reverse=True)
            return rows(triples)

        if name == "heavy":
            triples = [(count, file, last.get(file, 0))
                       for file, count in counts.items()
                       if now - last.get(file, 0) <= 30 * 86400]
            triples.sort(key=lambda item: (-item[0], -item[2]))
            return rows(triples)

        if name == "loved":
            loved = set(liked)
            loved.update(file for file, rating in self._integers(ratings).items()
                         if rating >= 8)
            stale = 21 * 86400
            triples = [(last.get(file, 0), file, last.get(file, 0))
                       for file in loved if now - last.get(file, 0) >= stale]
            triples.sort(key=lambda item: item[0])
            return rows(triples)

        if name == "history":
            triples = [(played, file, played) for file, played in last.items()]
            triples.sort(key=lambda item: -item[0])
            return rows(triples, cap=200)

        if name == "throwback":
            low, high = 14 * 86400, 120 * 86400
            triples = [(counts.get(file, 0), file, played)
                       for file, played in last.items()
                       if low <= now - played <= high]
            triples.sort(key=lambda item: (-item[0], item[2]))
            return rows(triples)

        return []

    def summaries(self, select: Callable[[str], list[dict]]) -> list[dict]:
        result = []
        for name in self.NAMES:
            rows = select(name)
            result.append({"shelf": name, "count": len(rows),
                           "cover": rows[0]["file"] if rows else ""})
        return result

    @staticmethod
    def _integers(values: Mapping[str, object]) -> dict[str, int]:
        result = {}
        for key, value in values.items():
            try:
                result[key] = int(value)
            except (TypeError, ValueError):
                continue
        return result
