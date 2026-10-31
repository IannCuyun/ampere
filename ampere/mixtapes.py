"""Deterministic planning for exact-length, energy-shaped mixtapes."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .intelligence import TrackFeatures, beam_sequence
from .versions import VersionKey, VersionPolicy


@dataclass(frozen=True)
class MixtapePlan:
    files: tuple[str, ...] = ()
    target_seconds: int = 0
    total_seconds: float = 0.0
    eligible_count: int = 0

    @property
    def viable(self) -> bool:
        return len(self.files) >= 3


class MixtapePlanner:
    """Choose a duration-fitting set, then sequence its complete energy arc."""

    MIN_TRACK_SECONDS = 60.0
    MAX_TRACK_SECONDS = 720.0
    DURATION_TOLERANCE = 90.0

    def __init__(self, *, rng: random.Random | None = None):
        self._rng = rng or random.Random()

    def plan(self, minutes: int, path: str, *,
             library: Mapping[str, Mapping], disliked: Sequence[str] = (),
             liked: Sequence[str] = (), counts: Mapping[str, int] | None = None,
             energies: Mapping[str, float] | None = None,
             bpms: Mapping[str, object] | None = None,
             version_groups: Mapping[VersionKey, Sequence[str]] | None = None,
             preferences: Mapping[str, object] | None = None) -> MixtapePlan:
        counts, energies, bpms = counts or {}, energies or {}, bpms or {}
        version_groups, preferences = version_groups or {}, preferences or {}
        target = max(600, int(minutes) * 60)
        prefix = path.rstrip("/") + "/" if path else ""
        hidden = set(disliked)
        pool = [file for file, song in library.items()
                if (not prefix or file.startswith(prefix))
                and file not in hidden
                and self.MIN_TRACK_SECONDS < self._duration(song)
                < self.MAX_TRACK_SECONDS]
        pool = VersionPolicy.collapse(
            pool, groups=version_groups, playcounts=counts,
            preferences=preferences)
        if len(pool) < 5:
            return MixtapePlan(target_seconds=target,
                               eligible_count=len(pool))

        loved = set(liked)

        def appeal(file: str) -> float:
            plays = max(0, int(counts.get(file, 0) or 0))
            return (self._rng.random() * .2
                    + 1.0 / math.sqrt(1 + plays)
                    + (0.5 if file in loved else 0.0))

        scored = sorted(((appeal(file), file) for file in pool), reverse=True)
        chosen = self._fit_duration(scored, library, target)
        total = sum(self._duration(library[file]) for file in chosen)
        if len(chosen) < 3:
            return MixtapePlan(target_seconds=target, total_seconds=total,
                               eligible_count=len(pool))

        features = []
        for file in chosen:
            song = library[file]
            try:
                bpm = float(bpms.get(file, 0) or 0)
            except (TypeError, ValueError):
                bpm = 0.0
            features.append(TrackFeatures(
                file, artist=song.get("artist", ""),
                title=song.get("title", ""), album=song.get("album", ""),
                bpm=bpm, energy=energies.get(file),
                plays=int(counts.get(file, 0) or 0),
                liked=file in loved, cue_quality=.5))
        ordered = beam_sequence(
            features, count=len(features), shape=self.energy_arc,
            beam_width=14, rng=self._rng)
        return MixtapePlan(tuple(track.file for track in ordered), target,
                           total, len(pool))

    @staticmethod
    def energy_arc(position: float) -> float:
        return (.35 + .55 * (position / .66) if position < .66
                else .90 - .38 * ((position - .66) / .34))

    def _fit_duration(self, scored: Sequence[tuple[float, str]],
                      library: Mapping[str, Mapping], target: int) -> list[str]:
        """Find the closest in-window duration while retaining high appeal.

        Bounding to 240 already-ranked candidates keeps the dynamic search
        below roughly 1.4 million state visits for a 90-minute tape while
        leaving far more musical choice than any finished tape consumes.
        """
        ceiling = int(target + self.DURATION_TOLERANCE)
        states: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
        for score, file in scored[:240]:
            duration = max(1, round(self._duration(library[file])))
            for total, (appeal, files) in list(states.items()):
                updated_total = total + duration
                if updated_total > ceiling:
                    continue
                updated = (appeal + score, files + (file,))
                existing = states.get(updated_total)
                if existing is None or updated[0] > existing[0]:
                    states[updated_total] = updated
        floor = int(target - self.DURATION_TOLERANCE)
        viable = [(total, appeal, files)
                  for total, (appeal, files) in states.items()
                  if floor <= total <= ceiling and len(files) >= 3]
        if not viable:
            return []
        _total, _appeal, files = min(
            viable, key=lambda row: (abs(row[0] - target), -row[1]))
        return list(files)

    @staticmethod
    def _duration(song: Mapping) -> float:
        try:
            return float(song.get("duration", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
