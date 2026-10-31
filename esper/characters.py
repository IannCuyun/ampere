"""The audited sound vocabulary: ten characters a listener can ask for.

Every character here survived an audit against an independent signal (the
embedded genre tag) plus title spot-checks (design/DECISIONS.md,
2026-08-22).  What was cut is as important as what stayed:

  * brightness only works as DARK.  At the top end it measures
    high-frequency energy, so distorted guitars and cymbals outrank
    strings — "airy" is not a thing this library can select on.
  * dynamic range only works as CRUSHED.  A wide range means quiet verse
    into loud hook as often as it means an uncompressed master, so
    "audiophile" put Eminem next to Handel.
  * onset density is too weak to define anything (d=0.87 / 0.13).
  * tempo is right on steady 4/4 and wrong on hip-hop, so it may narrow a
    selection and may never define one.

Everything below rests on energy, bass and dynamic range, which measured
strong, plus brightness in its one reliable direction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .queue_sequencing import QueueSequencer

# Skits, intros and interludes contaminated every quiet character: 15% of
# the sparse bucket was under two minutes.  A track has to be long enough to
# BE a listening experience before its measurements mean anything.
MIN_SECONDS = 150.0


def _band(value, low, high):
    """1.0 dead centre of [low, high], falling to 0 at the edges."""
    if value is None or not (low <= value <= high):
        return 0.0
    centre, half = (low + high) / 2.0, max(1e-6, (high - low) / 2.0)
    return max(0.0, 1.0 - abs(value - centre) / half)


CHARACTERS = (
    dict(key="still", label="STILL & SPARSE",
         blurb="quiet and uncluttered, with room around every sound",
         match=lambda f: f.get("energy") is not None and f["energy"] < 0.42
                         and f.get("dyn") is not None and f["dyn"] >= 11.0,
         fit=lambda f: _band(f.get("energy"), 0.0, 0.42)),
    dict(key="mellow", label="MELLOW",
         blurb="low intensity, whatever the instrument",
         match=lambda f: f.get("energy") is not None and f["energy"] < 0.50,
         fit=lambda f: _band(f.get("energy"), 0.0, 0.50)),
    dict(key="quiet-dark", label="QUIET & DARK",
         blurb="subdued and low-lit",
         match=lambda f: f.get("energy") is not None and f["energy"] < 0.50
                         and f.get("bright") is not None and f["bright"] < 0.30,
         fit=lambda f: (_band(f.get("energy"), 0.0, 0.50)
                        + _band(f.get("bright"), 0.0, 0.30)) / 2.0),
    dict(key="dark", label="DARK",
         blurb="the tone sits low and unlit",
         match=lambda f: f.get("bright") is not None and f["bright"] < 0.25,
         fit=lambda f: _band(f.get("bright"), 0.0, 0.25)),
    dict(key="heavy-low", label="HEAVY LOW END",
         blurb="the bottom of the mix carries the record",
         match=lambda f: f.get("bass") is not None and f["bass"] >= 0.75,
         fit=lambda f: _band(f.get("bass"), 0.75, 1.0)),
    dict(key="subsonic", label="SUBSONIC",
         blurb="the deepest low end in the library",
         match=lambda f: f.get("bass") is not None and f["bass"] >= 0.92,
         fit=lambda f: _band(f.get("bass"), 0.92, 1.0)),
    dict(key="driving", label="DRIVING",
         blurb="sustained forward push without tipping into assault",
         match=lambda f: f.get("energy") is not None
                         and 0.72 <= f["energy"] < 0.85,
         fit=lambda f: _band(f.get("energy"), 0.72, 0.85)),
    dict(key="punishing", label="PUNISHING",
         blurb="the most intense thing you own",
         match=lambda f: f.get("energy") is not None and f["energy"] >= 0.88,
         fit=lambda f: _band(f.get("energy"), 0.88, 1.0)),
    dict(key="wall", label="WALL OF SOUND",
         blurb="loud and flat to the ceiling, no air left in it",
         match=lambda f: f.get("energy") is not None and f["energy"] >= 0.80
                         and f.get("dyn") is not None and f["dyn"] < 7.0,
         fit=lambda f: _band(f.get("energy"), 0.80, 1.0)),
    dict(key="crushed", label="CRUSHED",
         blurb="loudness-war masters, to seek out or to steer around",
         match=lambda f: f.get("dyn") is not None and f["dyn"] < 5.5,
         # The flatter the master, the truer the character.
         fit=lambda f: (max(0.0, 1.0 - f["dyn"] / 5.5)
                        if f.get("dyn") is not None else 0.0)),
)

BY_KEY = {c["key"]: c for c in CHARACTERS}
KEYS = tuple(c["key"] for c in CHARACTERS)


def label(key: str) -> str:
    entry = BY_KEY.get(str(key))
    return entry["label"] if entry else ""


def matches(key: str, features: Mapping) -> bool:
    entry = BY_KEY.get(str(key))
    return bool(entry and entry["match"](features))


def fit(key: str, features: Mapping) -> float:
    entry = BY_KEY.get(str(key))
    return float(entry["fit"](features)) if entry else 0.0


def select(songs: Sequence[Mapping], features: Mapping[str, Mapping], *,
           character: str, count: int = 25, disliked=(), queued=(),
           durations: Mapping[str, float] | None = None,
           min_seconds: float = MIN_SECONDS) -> list[str]:
    """Rank one character's members, best fit first, artists spread out.

    `features` maps file -> {"energy", "bass", "bright", "dyn"}. A file with
    no measurements is never guessed at; it simply is not a candidate.
    """
    if character not in BY_KEY:
        return []
    durations = durations or {}
    disliked, queued = set(disliked), set(queued)
    scored = []
    for song in songs:
        file = song.get("file", "")
        if not file or file in disliked or file in queued:
            continue
        if float(durations.get(file, 0.0) or 0.0) < min_seconds:
            continue
        row = features.get(file)
        if not row or not matches(character, row):
            continue
        scored.append((fit(character, row), file))
    scored.sort(key=lambda pair: -pair[0])
    keys = {song.get("file", ""): song.get("artist", "") for song in songs}
    return QueueSequencer.artist_spread(
        [file for _, file in scored[:max(count * 3, count)]],
        artist_keys=keys)[:count]
