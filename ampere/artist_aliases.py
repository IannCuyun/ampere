"""Alias SUGGESTIONS for Ampere's Library Doctor.

Every function here proposes; nothing here decides.  SPEC UNDESIGNED #17
forbids inventing fuzzy aliases, so a suggestion is only ever a candidate put
in front of Iann, and it becomes an alias when he says so.  The rules are
deliberately narrow and explainable — each candidate carries the REASON it was
offered, so a wrong suggestion is obvious on sight rather than mysterious.

Only single credits take part on either side: a comma-separated collaboration
line is not an identity, and offering one as an alias would quietly merge a
whole collaboration into one artist.

What this can find: name-extension identities, which is the common real case —
``Tech N9ne Collabos`` under ``Tech N9ne``, ``Shawn James and the
Shapeshifters`` under ``Shawn James``.  What it deliberately cannot find:
unrelated stage names such as ``Ye`` for ``Kanye West``.  No amount of string
comparison recovers that, and guessing at it is exactly what the rule forbids;
that pairing is made by hand through the searchable list instead.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from .artists import clean_artist_name

# Words that join a performer to a backing group, and words that name the group
# itself.  A remainder starting with one of these reads as "the same artist,
# billed with a band"; a remainder that is just another name does not.
# "…and the Shapeshifters" is the SAME act billed with its band.
_BAND_CONNECTORS = {"and", "y", "und", "et", "avec", "con"}
# "…Feat. Drake" is the same PRIMARY act with a guest on the track. Merging
# these tidies browsing but costs the guest their credit, so they are marked
# apart and ranked last for Iann to weigh — see ROADMAP 1.3, where featured
# credits should be resolved structurally rather than by alias.
_GUEST_CONNECTORS = {
    "feat", "feat.", "featuring", "ft", "ft.", "w", "w/", "with",
    "presents", "vs", "vs.", "meets",
}
_CONNECTORS = _BAND_CONNECTORS | _GUEST_CONNECTORS
_GROUP_WORDS = {
    "collabos", "collabo", "collaborations", "band", "orchestra", "orchestre",
    "ensemble", "trio", "quartet", "quintet", "sextet", "septet", "octet",
    "choir", "chorus", "project", "experience", "experiment", "group",
    "collective", "crew", "posse", "allstars", "all-stars", "quartetto",
    "singers", "players", "company", "revue", "sound", "soundsystem",
    "unit", "gang", "family", "friends", "co", "band.",
}
_SEPARATORS = re.compile(r"[\s,;:&/+\-–—]+")
# A comma or semicolon is how this catalog writes a COMBINED credit line
# ("King Iso, Tech N9ne, X-Raided"). SPEC is explicit that a combined credit
# never becomes a third pseudo-artist, so such a line is not an identity and
# may neither be aliased nor be offered as one.
_COMBINED = re.compile(r"[,;]")


def fold(value: str) -> str:
    """Comparison form: accent-blind, punctuation-blind, case-blind."""
    text = unicodedata.normalize("NFKD", clean_artist_name(value).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_SEPARATORS.split(text)).strip()


def _tokens(value: str) -> list[str]:
    return [t for t in fold(value).split(" ") if t]


def _remainder(longer: Sequence[str], shorter: Sequence[str]) -> list[str] | None:
    """The tail of `longer` when `shorter` is its exact leading run."""
    if len(longer) <= len(shorter) or list(longer[:len(shorter)]) != list(shorter):
        return None
    return list(longer[len(shorter):])


def _reason(tail: Sequence[str]) -> str:
    """Why this tail reads as the same artist — or "" when it does not."""
    if not tail:
        return ""
    head = tail[0]
    if head in _GUEST_CONNECTORS:
        return "same act, guest on the track"
    if head in _BAND_CONNECTORS or (head == "the" and len(tail) > 1):
        return "billed with a group"
    if head in _GROUP_WORDS or tail[-1] in _GROUP_WORDS:
        return "a named project or band"
    return ""


def is_single_credit(value: str) -> bool:
    """True when a name is one artist rather than a combined credit line."""
    return bool(clean_artist_name(value)) and not _COMBINED.search(str(value))


def suggest(chosen: str, artists: Iterable[str], *, limit: int = 8) -> list[dict]:
    """Candidate aliases for `chosen`, best first.

    Each result is ``{"name", "reason"}``.  Name-identical variants (case or
    punctuation only) rank first because they are almost always the same
    artist typed two ways; extensions follow, shortest tail first, because a
    short tail is a stronger signal than a long one.
    """
    if not is_single_credit(chosen):
        return []
    target = _tokens(chosen)
    if not target:
        return []
    target_key = " ".join(target)
    seen: set[str] = {target_key}
    scored: list[tuple[int, int, str, dict]] = []
    for raw in artists:
        name = clean_artist_name(raw)
        if not name or not is_single_credit(raw):
            continue
        tokens = _tokens(name)
        key = " ".join(tokens)
        if not key or key in seen:
            continue
        tail = _remainder(tokens, target)
        if tail is None:
            # Iann may have picked the LONGER billing; offer the short form.
            lead = _remainder(target, tokens)
            if lead is None:
                continue
            reason = _reason(lead)
            if not reason:
                continue
            seen.add(key)
            scored.append((2, len(lead), key,
                           {"name": name, "reason": "the shorter billing of the same artist"}))
            continue
        reason = _reason(tail)
        if not reason:
            continue
        seen.add(key)
        rank = 3 if reason.startswith("same act") else 1
        scored.append((rank, len(tail), key, {"name": name, "reason": reason}))
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in scored[:max(0, limit)]]
