"""Lifecycle and state ownership for refillable listening sessions."""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
import math

from .intelligence import TrackFeatures, discovery_score
from .queue_sequencing import QueueSequencer


@dataclass(frozen=True)
class SessionState:
    mood: str = ""
    sonic_profile: str = ""
    radio_enabled: bool = False
    smart_shuffle_seed: dict = None

    def __post_init__(self):
        if self.smart_shuffle_seed is None:
            object.__setattr__(self, "smart_shuffle_seed", {})

    @property
    def kind(self) -> str:
        if self.mood:
            return "mood"
        if self.sonic_profile:
            return "sound-profile"
        if self.radio_enabled:
            return "radio"
        if self.smart_shuffle_seed:
            return "smart-shuffle"
        return "manual"

    @property
    def smart_shuffle_active(self) -> bool:
        return bool(self.smart_shuffle_seed)


class SessionService:
    """Own mutually-exclusive recommendation-session state."""

    def __init__(self, *, radio_enabled: bool = False):
        self._state = SessionState(radio_enabled=bool(radio_enabled))

    @property
    def state(self) -> SessionState:
        return self._state

    def set_radio(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        state = self._state
        updated = SessionState(
            mood=state.mood if enabled else "",
            sonic_profile=state.sonic_profile if enabled else "",
            radio_enabled=enabled)
        changed = updated != state
        self._state = updated
        return changed

    def set_smart_shuffle(self, seed: dict | None) -> bool:
        state = self._state
        seed = dict(seed) if seed else {}
        updated = SessionState(
            mood="",
            sonic_profile="",
            radio_enabled=False,
            smart_shuffle_seed=seed if seed else {})
        changed = updated != state
        self._state = updated
        return changed

    def commit_curated(self, *, mood: str = "", sonic_profile: str = "") -> bool:
        if mood and sonic_profile:
            raise ValueError("mood and sound-profile sessions are mutually exclusive")
        updated = SessionState(mood=str(mood), sonic_profile=str(sonic_profile),
                               radio_enabled=True)
        changed = updated != self._state
        self._state = updated
        return changed

    def end_curated(self) -> bool:
        state = self._state
        if not state.mood and not state.sonic_profile:
            return False
        self._state = SessionState(radio_enabled=state.radio_enabled)
        return True

    def end_smart_shuffle(self) -> bool:
        state = self._state
        if not state.smart_shuffle_seed:
            return False
        self._state = SessionState(radio_enabled=state.radio_enabled)
        return True

    @staticmethod
    def artist_spread(files, window: int = 1, *, artist_keys=None) -> list[str]:
        return QueueSequencer.artist_spread(
            files, window, artist_keys=artist_keys)

    def radio_picks(self, songs, *, seed, queued=(), counts=None, ratings=None,
                    last_played=None, liked=(), disliked=(), energies=None,
                    mood="match", count=15, now=None, rng=None) -> list[str]:
        """Rank a plain library-radio continuation from supplied snapshots."""
        file = seed.get("file", "")
        if not file:
            return []
        counts, ratings = counts or {}, ratings or {}
        last_played, energies = last_played or {}, energies or {}
        queued, liked, disliked = set(queued), set(liked), set(disliked)
        now, rng = now or time.time(), rng or random.Random()
        parts = file.split("/")
        genre = parts[0] if "/" in file else ""
        subgenre = "/".join(parts[:2]) + "/" if len(parts) > 2 else None
        seed_artist = (seed.get("artist") or "").lower()
        seed_energy = energies.get(file)

        def rank(pool):
            candidates = []
            for song in pool:
                candidate = song["file"]
                if candidate in queued or candidate == file or candidate in disliked:
                    continue
                energy = energies.get(candidate)
                if energy is not None and ((mood == "calm" and energy > .55)
                                           or (mood == "heavy" and energy < .50)):
                    continue
                compatibility = .22
                if energy is not None:
                    if mood == "match" and seed_energy is not None:
                        compatibility += .42 * (1 - min(1, abs(energy-seed_energy)*2))
                    elif mood == "calm":
                        compatibility += .35 * (1 - energy)
                    elif mood == "heavy":
                        compatibility += .35 * energy
                if subgenre and candidate.startswith(subgenre):
                    compatibility += .28
                elif genre and candidate.startswith(genre + "/"):
                    compatibility += .14
                if seed_artist and (song.get("artist") or "").lower() == seed_artist:
                    compatibility += .08
                try:
                    rating = int(ratings.get(candidate, 0) or 0)
                    last = float(last_played.get(candidate, 0) or 0)
                except (TypeError, ValueError):
                    rating, last = 0, 0.0
                feature = TrackFeatures(
                    candidate, artist=song.get("artist", ""),
                    title=song.get("title", ""), album=song.get("album", ""),
                    energy=energy, plays=counts.get(candidate, 0), rating=rating,
                    last_played=last, liked=candidate in liked)
                score, _ = discovery_score(
                    feature, now=now, compatibility=min(1, compatibility), rng=rng)
                candidates.append((score, candidate))
            candidates.sort(key=lambda pair: -pair[0])
            return [candidate for _, candidate in candidates]

        same_genre = [song for song in songs
                      if song["file"].startswith(genre + "/")] if genre else []
        picks = rank(same_genre)
        if len(picks) < count:
            picks = rank(songs)
        artist_keys = {song["file"]: song.get("artist", "") for song in songs}
        return self.artist_spread(
            picks[:count * 3], artist_keys=artist_keys)[:count]

    def mood_picks(self, songs, spec, *, exemplars=(), queued=(), counts=None,
                   ratings=None, last_played=None, liked=(), disliked=(),
                   energies=None, count=25, now=None, rng=None) -> list[str]:
        """Rank a whole-library mood session without touching MPD or Qt."""
        counts, ratings = counts or {}, ratings or {}
        last_played, energies = last_played or {}, energies or {}
        exemplars, queued = set(exemplars), set(queued)
        liked, disliked = set(liked), set(disliked)
        now, rng = now or time.time(), rng or random.Random()
        low, high = spec["energy"]
        center, half_width = (low + high) / 2, (high - low) / 2
        candidates = []
        for song in songs:
            file = song["file"]
            if file in queued or file in disliked:
                continue
            exemplar = file in exemplars
            parts = file.split("/")
            weight = spec["genres"].get("/".join(parts[:2])) if len(parts) >= 3 else None
            if weight is None and len(parts) >= 2:
                weight = spec["genres"].get(parts[0])
            if (weight is None or weight < 0) and not exemplar:
                continue
            energy = energies.get(file)
            if energy is not None and not exemplar and not (
                    low - .12 <= energy <= high + .12):
                continue
            compatibility = .25 + (.38 if exemplar else 0)
            if weight is not None and weight > 0:
                compatibility += .22 * weight
            if energy is not None:
                compatibility += .32 * max(
                    0, 1 - abs(energy-center)/(half_width+.12))
            try:
                rating = int(ratings.get(file, 0) or 0)
                last = float(last_played.get(file, 0) or 0)
            except (TypeError, ValueError):
                rating, last = 0, 0.0
            feature = TrackFeatures(
                file, artist=song.get("artist", ""), title=song.get("title", ""),
                album=song.get("album", ""), energy=energy,
                plays=counts.get(file, 0), rating=rating,
                last_played=last, liked=file in liked)
            score, _ = discovery_score(
                feature, now=now, compatibility=min(1, compatibility), rng=rng)
            candidates.append((score, file))
        candidates.sort(key=lambda pair: -pair[0])
        artist_keys = {song["file"]: song.get("artist", "") for song in songs}
        return self.artist_spread(
            [file for _, file in candidates][:count * 3],
            artist_keys=artist_keys)[:count]

    def sonic_picks(self, songs, bands, trait_maps, *, queued=(), counts=None,
                    ratings=None, last_played=None, liked=(), disliked=(),
                    count=25, now=None, rng=None) -> list[str]:
        """Rank tracks against validated sonic trait bands."""
        queued, liked, disliked = set(queued), set(liked), set(disliked)
        counts, ratings = counts or {}, ratings or {}
        last_played = last_played or {}
        now, rng = now or time.time(), rng or random.Random()
        candidates = []
        for song in songs:
            file = song["file"]
            if file in queued or file in disliked:
                continue
            score, outside = rng.random(), False
            for key, (low, high, margin) in bands.items():
                value = trait_maps.get(key, {}).get(file)
                if value is None:
                    continue
                if value < low - margin or value > high + margin:
                    outside = True
                    break
                center, half_width = (low + high) / 2, (high - low) / 2
                score += .7 * max(0, 1 - abs(value-center)/(half_width+margin))
            if outside:
                continue
            plays = counts.get(file, 0)
            if plays:
                score += min(1.2, .3 * math.log2(1 + plays))
            try:
                score += .12 * int(ratings.get(file, 0))
            except (TypeError, ValueError):
                pass
            if file in liked:
                score += .6
            try:
                if now - int(last_played.get(file, 0)) < 6 * 3600:
                    score -= 2
            except (TypeError, ValueError):
                pass
            candidates.append((score, file))
        candidates.sort(key=lambda pair: -pair[0])
        artist_keys = {song["file"]: song.get("artist", "") for song in songs}
        return self.artist_spread(
            [file for _, file in candidates][:count * 3],
            artist_keys=artist_keys)[:count]
