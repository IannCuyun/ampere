"""Pure song selection and queue-order planning for Ampere's smart mix."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .intelligence import TrackFeatures, discovery_score, tempo_distance


@dataclass(frozen=True)
class QueueOrderPlan:
    start: int
    frontier: int
    songs: tuple[Mapping, ...] = ()

    @property
    def reorderable(self) -> bool:
        return len(self.songs) >= 3


class SmartMixPlanner:
    """Select discovery-forward songs and order a bounded queue window."""

    def __init__(self, *, rng: random.Random | None = None, clock=time.time):
        self._rng = rng or random.Random()
        self._clock = clock

    def select(self, seed: Mapping, songs: Sequence[Mapping], *,
               counts: Mapping[str, int] | None = None,
               ratings: Mapping[str, object] | None = None,
               last_played: Mapping[str, object] | None = None,
               energies: Mapping[str, float] | None = None,
               bpms: Mapping[str, object] | None = None,
               liked: Sequence[str] = (), disliked: Sequence[str] = (),
               limit: int = 50) -> list[Mapping]:
        file = str(seed.get("file") or "")
        if not file or limit <= 0:
            return []
        counts, ratings = counts or {}, ratings or {}
        last_played, energies, bpms = last_played or {}, energies or {}, bpms or {}
        liked, disliked = set(liked), set(disliked)
        seed_genres = self._genre_keys(seed)
        seed_artist = str(seed.get("artist") or "").casefold()
        seed_energy = energies.get(file)
        seed_bpm = self._number(bpms.get(file))
        now = self._clock()
        candidates = []
        for song in songs:
            candidate = str(song.get("file") or "")
            if not candidate or candidate == file or candidate in disliked:
                continue
            # Folder paths express Iann's storage system, not musical genre.
            # Fit comes only from normalized embedded metadata and analyzed
            # audio evidence; an untagged track remains eligible at the quiet
            # baseline rather than inheriting meaning from its directory.
            compatibility = .18
            candidate_genres = self._genre_keys(song)
            if seed_genres and candidate_genres:
                shared = len(seed_genres & candidate_genres)
                total = len(seed_genres | candidate_genres)
                compatibility += .46 * (shared / max(1, total))
            if seed_artist and str(song.get("artist") or "").casefold() == seed_artist:
                compatibility += .12
            energy = energies.get(candidate)
            if energy is not None and seed_energy is not None:
                compatibility += .18 * (
                    1 - min(1.0, abs(energy - seed_energy) * 2))
            bpm = self._number(bpms.get(candidate))
            if bpm and seed_bpm:
                compatibility += .12 * (1 - tempo_distance(seed_bpm, bpm))
            rating = self._integer(ratings.get(candidate))
            last = self._number(last_played.get(candidate))
            feature = TrackFeatures(
                candidate, artist=song.get("artist", ""),
                title=song.get("title", ""), album=song.get("album", ""),
                energy=energy, bpm=bpm, plays=counts.get(candidate, 0),
                rating=rating, last_played=last,
                liked=candidate in liked)
            # Smart Shuffle is FIT + FLOW, not discovery radio.  The old
            # composite let obscurity and age outweigh compatibility, so an
            # unrelated unplayed song could beat a familiar strong match.
            # Keep rediscovery as a bounded secondary signal inside the
            # fitted pool; the planner below owns Flow after selection.
            discovery, _ = discovery_score(
                feature, now=now, compatibility=0.0, rng=self._rng)
            fit = min(1.0, compatibility)
            discovery = min(1.0, max(0.0, discovery))
            score = .80 * fit + .20 * discovery
            candidates.append((score, song))
        candidates.sort(key=lambda pair: -pair[0])
        picks, recent_artists, deferred = [], [], []
        for _, song in candidates:
            if len(picks) >= limit:
                break
            artist = str(song.get("artist") or "").casefold()
            if artist and artist in recent_artists:
                deferred.append(song)
                continue
            picks.append(song)
            recent_artists = (recent_artists + [artist])[-2:]
        picks.extend(deferred[:max(0, limit - len(picks))])
        return picks

    def order_window(self, queue: Sequence[Mapping], *, queue_pos: int,
                     frontier: int, window_size: int,
                     energies: Mapping[str, float] | None = None,
                     bpms: Mapping[str, float] | None = None,
                     arc: bool = False, fresh: bool = False) -> QueueOrderPlan:
        energies, bpms = energies or {}, bpms or {}
        start = max(queue_pos, frontier)
        window = list(queue[start + 1:start + 1 + window_size])
        if len(window) < 3:
            return QueueOrderPlan(start, len(queue))
        anchor = str(queue[start].get("file") or "") if start >= 0 else ""
        current_energy = energies.get(anchor, .5) if anchor else .5
        current_bpm = bpms.get(anchor)
        previous = queue[start] if 0 <= start < len(queue) else None
        low, high = min(.35, current_energy), max(.8, current_energy)
        pending, ordered, recent_artists = list(window), [], []
        for index in range(len(window)):
            target = self._target(index, len(window), current_energy,
                                  low, high, arc)
            best = min(pending, key=lambda song: self._order_cost(
                song, target=target, current_bpm=current_bpm,
                recent_artists=recent_artists, energies=energies, bpms=bpms,
                previous=previous, fresh=fresh))
            pending.remove(best)
            ordered.append(best)
            file = str(best.get("file") or "")
            current_energy = energies.get(file, .5)
            current_bpm = bpms.get(file) or current_bpm
            previous = best
            artist = str(best.get("artist") or "").casefold()
            recent_artists = (recent_artists + [artist])[-2:]
        return QueueOrderPlan(start, start + len(window), tuple(ordered))

    def _order_cost(self, song, *, target, current_bpm, recent_artists,
                    energies, bpms, previous, fresh):
        file = str(song.get("file") or "")
        cost = abs(energies.get(file, .5) - target)
        bpm = bpms.get(file)
        if bpm and current_bpm and bpm > 0 and current_bpm > 0:
            cost += .12 * min(1.0, abs(math.log2(bpm / current_bpm)))
        else:
            cost += .06
        artist = str(song.get("artist") or "").casefold()
        if artist and artist in recent_artists:
            cost += .5
        previous_genres = self._genre_keys(previous or {})
        candidate_genres = self._genre_keys(song)
        if previous_genres and candidate_genres:
            cost += (-.08 if previous_genres & candidate_genres else .12)
        cost += .04 * self._rng.random() * (2.0 if fresh else 1.0)
        return cost

    @staticmethod
    def _genre_keys(song: Mapping) -> frozenset[str]:
        """Normalize embedded genre frames without inventing path taxonomy."""
        raw = song.get("genres") or song.get("genre") or ()
        values = raw if isinstance(raw, (list, tuple)) else (raw,)
        keys: set[str] = set()
        for value in values:
            for part in str(value or "").split(";"):
                key = " ".join(part.split()).strip().casefold()
                if key:
                    keys.add(key)
        return frozenset(keys)

    @staticmethod
    def _target(index, length, current, low, high, arc):
        if not arc:
            return current
        position = (index + 1) / (length + 1)
        phase = (math.sin(math.pi * min(1.0, position / .55 * .5))
                 if position <= .55 else
                 math.sin(math.pi * (.5 + .5 * (position - .55) / .45)))
        return low + (high - low) * phase

    @staticmethod
    def _number(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _integer(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
