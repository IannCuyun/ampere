"""Canonical artist-credit projection for Ampere's library surfaces."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache


# Explicit aliases are catalog identity, not fuzzy search.  Additions require a
# real user/library verdict so similarly named artists can never be merged by
# guesswork.  The seed ships one historical pairing; everything else arrives
# from Iann's own alias table (settings key ``artist_aliases``) through
# ``set_aliases``, and every entry there is a decision he made by hand.
_SEED_ALIASES = {
    "ye": "Kanye West",
}
_ALIASES = dict(_SEED_ALIASES)


def set_aliases(values: Mapping | None) -> dict:
    """Install the user's alias table over the shipped seed.

    Replacing the whole mapping keeps removal trivially reversible: an alias
    the user deletes simply is not in the next call.  Returns the table now in
    force so a caller can publish it without reaching into module state.
    """
    table = dict(_SEED_ALIASES)
    for alias, canonical in (values or {}).items():
        name = clean_artist_name(alias)
        target = clean_artist_name(canonical)
        if name and target and name.casefold() != target.casefold():
            table[name.casefold()] = target
    _ALIASES.clear()
    _ALIASES.update(table)
    # Every cached projection below is an answer under the OLD table.
    _invalidate_credit_caches()
    return aliases()


def _invalidate_credit_caches() -> None:
    """Drop every memoized credit projection; the alias table just moved."""
    _canonical_artist_name.cache_clear()
    _credited_artists.cache_clear()
    _song_credits.cache_clear()


def aliases() -> dict:
    """The alias table in force, keyed by the folded alias name."""
    return dict(_ALIASES)


def clean_artist_name(value) -> str:
    """Return one whitespace-normalized artist display name."""
    return " ".join(str(value or "").split()).strip()


def canonical_artist_name(value) -> str:
    """Resolve an exact, explicit alias while preserving normal display text."""
    return _canonical_artist_name(str(value or ""))


@lru_cache(maxsize=16384)
def _canonical_artist_name(value: str) -> str:
    """Cached resolution: a library pass asks for the same few thousand credit
    strings once per song. `set_aliases` clears every cache here, so a stale
    table can never survive a change."""
    name = clean_artist_name(value)
    return _ALIASES.get(name.casefold(), name)


def artist_key(value) -> str:
    """Return the case-insensitive key for one canonical artist identity."""
    return canonical_artist_name(value).casefold()


def _frames(value) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = clean_artist_name(raw)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


# A featuring marker separates the PRIMARY billing from its guests.  It must
# stand as its own token: an artist whose name merely contains these letters
# is not split.  SPEC row 38 keeps ampersands inside a name (``Royal & the
# Serpent``, ``Macklemore & Ryan Lewis``), so the ampersand is a separator
# only on the GUEST side of the marker, where it genuinely lists people.
# `w` ALONE is not a marker: "C.W. Stoneking" split into "C." + "Stoneking"
# when it was (found against the real library, 2026-08-21). The abbreviated
# form must carry its slash.
_FEATURE_MARKER = re.compile(
    r"\s*[\(\[]?\s*(?:\b(?:feat|feats|ft|featuring)\b\.?|\bw\s*/)\s*",
    re.IGNORECASE)
# A credit line may leave the marker stranded between commas
# ("Tech N9ne, Krizz Kaliko, feat., Eric Boone"). A marker is not a person.
_MARKER_ONLY = re.compile(
    r"^\s*[\(\[]?\s*(?:feat|feats|ft|featuring|with|w)\b\.?\s*/?\s*[\)\]]?\s*$",
    re.IGNORECASE)
_GUEST_SPLIT = re.compile(
    r"\s*(?:[,;&]|\bw\s*/|\bwith\b|\band\b|\bx\b)\s*", re.IGNORECASE)
_TRAILING_BRACKET = re.compile(r"[\)\]]\s*$")


def split_featured(value) -> tuple[str, list[str]]:
    """Split one credit line into its primary billing and its guests.

    ``Travis Scott Feat. Drake`` is not an artist: it is Travis Scott with a
    guest, and before this both halves collapsed into a single invented
    identity (SPEC UNDESIGNED #17).  The display text is never altered — only
    how Ampere reads it.

    Returns ``(primary, guests)``; ``guests`` is empty when the line carries
    no marker, so a plain name passes through untouched.
    """
    text = clean_artist_name(value)
    if not text:
        return "", []
    match = _FEATURE_MARKER.search(text)
    if not match or match.start() == 0:
        return text, []
    primary = clean_artist_name(text[:match.start()])
    tail = _TRAILING_BRACKET.sub("", text[match.end():])
    if not primary or not tail.strip():
        return text, []
    guests = [clean_artist_name(part) for part in _GUEST_SPLIT.split(tail)]
    return primary, [guest for guest in guests if guest]


def credited_artists(value) -> list[str]:
    """Project a tag's discrete artists without inventing names.

    Ampere's library uses repeated frames and comma/semicolon credit lines for
    collaborations, and marks guests with ``feat.``/``ft.``/``w/``.  Ampersands remain part of an artist name (for example,
    ``Royal & the Serpent``); only the separators used by the catalog are
    expanded.  The combined display string is deliberately not emitted as a
    third pseudo-artist.
    """
    return list(_credited_artists(_credit_frames(value)))


def _credit_frames(value) -> tuple[str, ...]:
    """Freeze one tag value into the hashable form the cache is keyed by."""
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value or ""),)


@lru_cache(maxsize=16384)
def _credited_artists(value: tuple[str, ...]) -> tuple[str, ...]:
    """The regex-heavy half of :func:`credited_artists`, memoized per credit.

    One artist's name repeats across every track they appear on, so a library
    pass asks this the same question thousands of times."""
    result: list[str] = []
    seen: set[str] = set()
    for frame in _frames(value):
        for part in re.split(r"\s*[,;]\s*", frame):
            if _MARKER_ONLY.match(part or ""):
                continue
            primary, guests = split_featured(part)
            for candidate in [primary, *guests]:
                name = canonical_artist_name(candidate)
                key = name.casefold()
                if name and key not in seen:
                    seen.add(key)
                    result.append(name)
    return tuple(result)


def primary_artist_credit(value) -> str:
    """Return the first discrete contributor for one page destination.

    A combined credit remains useful display text, but it is not an artist
    identity.  Surfaces that can open only one Artist page resolve the first
    credited contributor deterministically; membership projection still puts
    the shared recording under every contributor returned by
    :func:`credited_artists`.
    """
    names = credited_artists(value)
    return names[0] if names else canonical_artist_name(value)


def song_credited_artists(song: Mapping) -> list[str]:
    """Return each canonical primary or album artist credited on ``song``."""
    return list(_song_credits(_credit_frames(song.get("artist") or ""),
                              _credit_frames(song.get("albumartist") or "")))


@lru_cache(maxsize=16384)
def _song_credits(artist: tuple[str, ...],
                  albumartist: tuple[str, ...]) -> tuple[str, ...]:
    """Memoized per credit PAIR: every track on a release shares one."""
    result: list[str] = []
    seen: set[str] = set()
    for field in (artist, albumartist):
        for name in _credited_artists(field):
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                result.append(name)
    return tuple(result)
