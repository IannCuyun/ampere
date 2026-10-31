"""Library health scan for the Doctor page.

One pass of tag reads (mutagen, ~ms/file) over the whole library; runs in
a background thread from the backend. Findings:
  lowBitrate — lossy files under 256 kbps (re-source lossless candidates)
  missingRg  — no ReplayGain track gain (leveling can't hold them steady)
  untagged   — unreadable files or missing title/artist tags
  outliers   — extreme ReplayGain values (masters that will fight leveling)
"""
from __future__ import annotations

import os

LOSSY = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma")
LOW_KBPS = 256
GAIN_LO, GAIN_HI = -14.0, 4.0


def _identity(file: str, idx: dict) -> dict:
    """Return the stable display identity for one scan finding.

    The Doctor worker already receives an immutable library snapshot. Enriching
    findings here keeps presentation free of secondary lookups and guarantees
    that the artwork key and visible metadata describe the same file.
    """
    song = idx.get(file, {}) or {}
    return {
        "file": file,
        "title": str(song.get("title") or ""),
        "artist": str(song.get("artist") or ""),
        "album": str(song.get("album") or ""),
    }


# The core tags a record needs to file itself correctly. A tag finding shows
# this exact block so the problem is visible in the tile rather than described
# in a sentence (Iann, 2026-08-21).
TAG_FIELDS = ("title", "artist", "album", "albumartist", "year", "track")


def _tag_state(file: str, idx: dict, readable: bool) -> dict:
    """Which core tags this file carries, and which are missing.

    Reports only what the library snapshot already holds — nothing is opened
    a second time, and no tag is ever written."""
    song = idx.get(file, {}) or {}
    present, missing = {}, []
    for field in TAG_FIELDS:
        value = song.get(field)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        text = str(value or "").strip()
        if text:
            present[field] = text
        else:
            missing.append(field)
    return {"readable": readable, "tags": present, "missing": missing,
            "missingCount": len(missing)}


def _track_gain(mf):
    """ReplayGain track gain from an open mutagen file, or None."""
    try:
        g = (mf.get("replaygain_track_gain")
             or mf.get("TXXX:replaygain_track_gain") or [None])[0]
        if g is None:
            return None
        if hasattr(g, "text"):
            g = (g.text or [None])[0]
        if g is None:
            return None
        return float(str(g).split()[0])
    except Exception:
        return None


def scan(root: str, files: list, idx: dict, progress=None) -> dict:
    from mutagen import File as MutagenFile

    low, no_rg, untagged, outliers = [], [], [], []
    for i, f in enumerate(files):
        if progress and i % 200 == 0:
            progress(i, len(files))
        try:
            mf = MutagenFile(os.path.join(root, f))
        except Exception:
            mf = None
        if mf is None:
            untagged.append({**_identity(f, idx), "why": "unreadable",
                             **_tag_state(f, idx, False)})
            continue
        s = idx.get(f, {})
        if not s.get("title") or not s.get("artist"):
            untagged.append({**_identity(f, idx),
                             "why": "missing title/artist tag",
                             **_tag_state(f, idx, True)})
        ext = os.path.splitext(f)[1].lower()
        kbps = int(getattr(getattr(mf, "info", None), "bitrate", 0)
                   or 0) // 1000
        if ext in LOSSY and 0 < kbps < LOW_KBPS:
            low.append({**_identity(f, idx), "kbps": kbps})
        g = _track_gain(mf)
        if g is None:
            no_rg.append(_identity(f, idx))
        elif g <= GAIN_LO or g >= GAIN_HI:
            outliers.append({**_identity(f, idx), "gain": round(g, 1)})
    low.sort(key=lambda d: d["kbps"])
    outliers.sort(key=lambda d: d["gain"])
    return {"lowBitrate": low, "missingRg": no_rg,
            "untagged": untagged, "outliers": outliers,
            "scanned": len(files)}
