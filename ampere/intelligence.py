"""Pure music-intelligence primitives used by DJ, radio and playlists.

The module deliberately has no Qt or MPD dependencies.  Keeping ranking here
makes the musical policy testable: Ampere can change how it gathers features
without quietly changing what "a good session" means.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
import re
from typing import Callable, Iterable


EMOTIONAL_WORDS = re.compile(
    r"\b(sad|sorrow|grief|dying|death|funeral|requiem|lament|alone|lonely|"
    r"goodbye|farewell|memory|memories|heartbreak|tears?|mourning|god|"
    r"heaven|ashes|fragile|still|sleep|dream|lost)\b", re.I)


@dataclass(frozen=True)
class TrackFeatures:
    file: str
    artist: str = ""
    title: str = ""
    album: str = ""
    genre: str = ""
    bpm: float = 0.0
    energy: float | None = None
    key: int = -1
    cue_quality: float = 0.0
    vocal: float = 0.0
    plays: int = 0
    rating: int = 0
    last_played: float = 0.0
    liked: bool = False
    anchor: bool = False

    @property
    def artist_key(self) -> str:
        return self.artist.casefold().strip() or self.file.rsplit("/", 2)[0]

    @property
    def emotional(self) -> float:
        """Likelihood that the track needs space instead of a showy cut."""
        text = " ".join((self.title, self.album, self.file.replace("_", " ")))
        word = 0.65 if EMOTIONAL_WORDS.search(text) else 0.0
        quiet = max(0.0, 0.55 - self.energy) * 1.15 if self.energy is not None else 0.0
        vocal = max(0.0, self.vocal - 0.35) * 0.45
        return min(1.0, word + quiet + vocal)


@dataclass(frozen=True)
class TransitionIntent:
    style: str
    score: float
    confidence: float
    reason: str


def tempo_distance(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.35
    ratio = b / a
    while ratio > 1.5:
        ratio /= 2.0
    while ratio < 0.75:
        ratio *= 2.0
    return min(1.0, abs(math.log2(ratio)) / math.log2(1.5))


def key_compatibility(a: int, b: int) -> float:
    """Musical compatibility for Ampere's 0–11 major / 12–23 minor keys."""
    if a < 0 or b < 0:
        return 0.5
    a_tonic, b_tonic = a % 12, b % 12
    a_minor, b_minor = a >= 12, b >= 12
    interval = (b_tonic - a_tonic) % 12
    if a == b:
        return 1.0
    if a_minor != b_minor and interval in (3, 9):
        return 0.92
    if a_minor == b_minor and interval in (5, 7):
        return 0.84
    if a_tonic == b_tonic:
        return 0.72
    if interval in (2, 10):
        return 0.48
    return 0.24


def transition_intent(a: TrackFeatures, b: TrackFeatures,
                      key_compat: float = 0.5) -> TransitionIntent:
    """Choose a musical hand-off before the renderer chooses mechanics.

    Slams are only recommended when the incoming track sustains or raises
    energy and neither side looks emotionally delicate.  A slam can therefore
    still be frequent in an energetic set without bulldozing reflective songs.
    """
    td = tempo_distance(a.bpm, b.bpm)
    cue = min(a.cue_quality, b.cue_quality)
    emotional = max(a.emotional, b.emotional)
    delta = ((b.energy or 0.5) - (a.energy or 0.5))
    continuity = 1.0 - td
    blend = .38 * continuity + .25 * key_compat + .25 * cue + .12 * (1 - emotional)
    slam = .38 * cue + .27 * max(0.0, min(1.0, delta * 2 + .45)) \
        + .20 * (1 - emotional) + .15 * td
    if emotional >= .55:
        return TransitionIntent("soft", max(.2, blend), .75,
                                "giving the song room to land emotionally")
    if delta < -.12:
        return TransitionIntent("blend", blend, .68,
                                "lowering the energy without a hard interruption")
    if slam >= .62 and cue >= .48:
        why = "raising the room" if delta > .08 else "holding the energy"
        return TransitionIntent("slam", slam, min(.95, .5 + cue / 2), why)
    if continuity >= .58:
        return TransitionIntent("blend", blend, min(.92, .5 + continuity / 2),
                                "tempo and phrasing support a continuous blend")
    return TransitionIntent("soft", max(.25, blend), .55,
                            "a clean reset serves this change better")


def discovery_score(t: TrackFeatures, *, now: float, compatibility: float,
                    rng: random.Random) -> tuple[float, list[str]]:
    """Score a track for rediscovery, with compatibility as guard rails."""
    plays = max(0, t.plays)
    obscurity = 1.0 / math.sqrt(1.0 + plays)
    age_days = (now - t.last_played) / 86400 if t.last_played else 3650.0
    rested = min(1.0, max(0.0, age_days / 90.0))
    taste = (.18 if t.liked else 0.0) + min(.18, t.rating / 55.0)
    score = .43 * obscurity + .22 * rested + .27 * compatibility + taste
    score += rng.uniform(-.035, .035)
    reasons = []
    if plays == 0:
        reasons.append("unplayed")
    elif plays <= 2:
        reasons.append("rarely played")
    if age_days >= 180:
        reasons.append("long absent")
    if compatibility >= .72:
        reasons.append("strong fit")
    if t.liked:
        reasons.append("liked anchor")
    return score, reasons[:2]


def beam_sequence(candidates: Iterable[TrackFeatures], *, count: int,
                  shape: Callable[[float], float] | None = None,
                  start: TrackFeatures | None = None, beam_width: int = 14,
                  rng: random.Random | None = None) -> list[TrackFeatures]:
    """Optimize a whole set instead of greedily choosing one neighbor.

    A bounded beam makes aggressive reordering practical for hundreds of
    candidates while retaining several possible future arcs at every step.
    """
    rng = rng or random.Random()
    pool = list(candidates)
    if not pool or count <= 0:
        return []
    target_n = min(count, len(pool))
    # (score, sequence, remaining indices)
    beams = [(0.0, [start] if start else [], tuple(range(len(pool))))]
    for pos in range(target_n):
        expanded = []
        frac = pos / max(1, target_n - 1)
        target_e = shape(frac) if shape else None
        for total, seq, remaining in beams:
            prev = seq[-1] if seq else None
            # Rank before bounding the expansion. A random 20-song sample
            # could omit every strong continuation from a large pool.
            ranked = []
            recent_artists = {x.artist_key for x in seq[-3:]}
            for idx in remaining:
                t = pool[idx]
                preview = .20 * t.cue_quality
                if prev:
                    preview += .62 * transition_intent(
                        prev, t, key_compatibility(prev.key, t.key)).score
                    if t.artist_key in recent_artists:
                        preview -= .72
                if target_e is not None and t.energy is not None:
                    preview -= .78 * abs(t.energy - target_e)
                ranked.append((preview + rng.uniform(0, .02), idx))
            ranked.sort(reverse=True)
            shortlist = [idx for _score, idx in ranked[:min(20, len(ranked))]]
            for idx in shortlist:
                t = pool[idx]
                gain = .20 * t.cue_quality
                if prev:
                    kc = key_compatibility(prev.key, t.key)
                    intent = transition_intent(prev, t, kc)
                    gain += .62 * intent.score
                    if t.artist_key in recent_artists:
                        gain -= .72
                if target_e is not None and t.energy is not None:
                    gain -= .78 * abs(t.energy - target_e)
                gain += rng.uniform(0, .025)
                expanded.append((total + gain, seq + [t],
                                 tuple(i for i in remaining if i != idx)))
        expanded.sort(key=lambda x: x[0], reverse=True)
        beams = expanded[:beam_width]
        if not beams:
            break
    best = beams[0][1] if beams else []
    return best[1:] if start and best and best[0] is start else best
