"""Forgiving search and result presentation for Ampere.

Layers, per Iann's spec:
  1. punctuation/diacritic-blind matching  — "Cant Hold Us" finds "Can't Hold Us"
  2. number-word canonicalization          — "six foot seven foot" finds "6 Foot 7 Foot"
  3. leet/stylization decoding             — "fein" finds "FE!N", "kesha" finds "Ke$ha"
  4. fused-acronym matching                — "byob" finds "B.Y.O.B."
  5. typo tolerance with suggestions       — "Hyena" suggests "HYAENA"

Both the index and the query are normalized two ways: SPACED (punctuation
becomes word breaks) and FUSED (punctuation vanishes, word spaces kept).
A song matches if the query lands in either form; fuzzy scoring also tries
both. Exact/substring hits rank first; fuzzy matches come back separately as
"closest matches" so the UI can label them honestly.
"""

import os
import re
import unicodedata
from functools import lru_cache
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock

from rapidfuzz import fuzz

from .albums import AlbumPresenter


@dataclass(frozen=True)
class LyricIndexResult:
    generation: int
    total: int
    done: int
    indexed: int
    failed: int
    cancelled: bool = False
    published: bool = False

NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "hundred": "100",
}
# symbols used as letters INSIDE words (FE!N, Ke$ha, A$AP, P!NK) — only
# replaced when flanked by letters/digits, so "Help!" stays "help"
_LEET = [
    (re.compile(r"(?<=[a-z0-9])!(?=[a-z0-9])"), "i"),
    (re.compile(r"(?<=[a-z0-9])\$(?=[a-z0-9])"), "s"),
    (re.compile(r"(?<=[a-z0-9])@(?=[a-z0-9])"), "a"),
]
_APOS = re.compile(r"[’'`´ʼ]")
_SPACES = re.compile(r" +")

# Script ranges used for romanization routing and Library bucketing. A title
# is never tagged with a language — Ampere reads only what the characters are.
_KANA = ((0x3040, 0x30FF), (0x31F0, 0x31FF))
_HAN = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))


def _in_ranges(text: str, ranges) -> bool:
    return any(lo <= ord(c) <= hi for c in text for lo, hi in ranges)


# Punctuation policy, script-blind. The old regexes were `[^a-z0-9]`, which
# silently deleted EVERY non-Latin letter — Japanese, Chinese, Cyrillic and
# Greek titles all normalized to the empty string and could not be found even
# by typing them exactly. Any unicode letter or digit is a searchable
# character, so the classes below are the exact complement of `str.isalnum`:
# Python's `\w` is alphanumerics plus the underscore, which is punctuation
# here. Character-at-a-time filtering cost 40% of a full index rebuild; these
# do the same work inside the regex engine.
_PUNCT_SPACED = re.compile(r"[\W_]+")     # every run of punctuation is a break
_PUNCT_FUSED = re.compile(r"[^\w ]|_")    # punctuation vanishes, spaces kept


@lru_cache(maxsize=65536)
def normalize(s: str, fused: bool = False) -> str:
    """Canonical form: lowercase, leet decoded, no diacritics, apostrophes
    fused, & = and, number words as digits. fused=True removes punctuation
    entirely (B.Y.O.B. -> byob); fused=False turns it into word breaks.
    Non-Latin letters are preserved so a title can be found in its own
    script; `romanizations` supplies the Latin way in.

    Cached: one library generation normalizes the same artist and album names
    once per record, and every keystroke re-normalizes the query."""
    s = s.lower()
    # Leet decoding runs BEFORE NFKD on purpose: "é!n" must not become "ein",
    # because the marker only stands in for a letter when real letters flank it.
    if "!" in s or "$" in s or "@" in s:
        for rx, rep in _LEET:
            s = rx.sub(rep, s)
    if not s.isascii():           # NFKD and the combining filter are identity
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
    s = _APOS.sub("", s)          # can't -> cant (fused, not split)
    if "&" in s:
        s = s.replace("&", " and ")
    s = (_PUNCT_FUSED if fused else _PUNCT_SPACED).sub(
        "" if fused else " ", s)
    s = _SPACES.sub(" ", s).strip()
    if not s:
        return s
    return " ".join(NUM_WORDS.get(t, t) for t in s.split())


_kakasi_conv = None


def _kakasi():
    global _kakasi_conv
    if _kakasi_conv is None:
        import pykakasi
        _kakasi_conv = pykakasi.kakasi()
    return _kakasi_conv


@lru_cache(maxsize=20000)
def romanizations(s: str) -> tuple[str, ...]:
    """Every plausible Latin reading of a non-Latin string, best first.

    Nothing in a music library declares its language, so Han text gets BOTH
    the Japanese reading and Mandarin pinyin (人間椅子 -> "ningen isu" AND
    "ren jian yi zi") and both are indexed; whichever one the listener types
    finds the record. Missing optional libraries degrade to transliteration
    rather than failing the index."""
    if not s or s.isascii():
        return ()
    forms, kana, han = [], _in_ranges(s, _KANA), _in_ranges(s, _HAN)
    if kana or han:
        try:
            forms.append(" ".join(
                part["hepburn"] for part in _kakasi().convert(s)))
        except Exception:
            pass
    if han:
        try:
            from pypinyin import lazy_pinyin
            forms.append(" ".join(lazy_pinyin(s)))
        except Exception:
            pass
    try:
        from anyascii import anyascii
        forms.append(anyascii(s))
    except Exception:
        pass
    return tuple(f for f in dict.fromkeys(forms) if f and not f.isspace())


def searchable(s: str, fused: bool = False) -> str:
    """`normalize` plus every romanization, joined into one haystack."""
    parts = [normalize(s, fused)]
    parts += [normalize(r, fused) for r in romanizations(s)]
    return " ".join(dict.fromkeys(p for p in parts if p))


def build_index(songs: list[dict]) -> list[dict]:
    """songs = _song_map()-shaped dicts. Returns index entries."""
    index = []
    for s in songs:
        stem = os.path.splitext(os.path.basename(s.get("file", "")))[0]
        ta = f"{s['title']} {s['artist']}"
        full = f"{s['title']} {s['artist']} {s['album']} {stem}"
        index.append({
            "song": s,
            "ta": searchable(ta), "taf": searchable(ta, fused=True),
            "full": searchable(full), "fullf": searchable(full, fused=True),
            # ntitle stays the plain normalized title: it is the sort key and
            # the exact-match test, and must not carry romanized text.
            "ntitle": normalize(s["title"]), "ntitlef": normalize(s["title"], fused=True),
            "rtitle": searchable(s["title"]),
            "rtitlef": searchable(s["title"], fused=True),
        })
    return index


def _fuzzy_score(qn: str, qf: str, entry: dict) -> float:
    score = max(fuzz.token_set_ratio(qn, entry["ta"]),
                fuzz.token_set_ratio(qf, entry["taf"]))
    # short single-word queries: also try best word-vs-word ratio, which is
    # what catches pure typos ("hyena" vs "hyaena")
    if " " not in qn and len(qn) >= 4:
        words = set(entry["ta"].split()) | set(entry["taf"].split())
        best = max((fuzz.ratio(qn, tok) for tok in words), default=0)
        score = max(score, best)
    return score


def format_label(file: str) -> str:
    """Short container label (FLAC, MP3, …) used to tell duplicate files apart."""
    ext = os.path.splitext(str(file or ""))[1].lstrip(".")
    return ext.upper()


def search(index: list[dict], query: str, hit_limit=None, sugg_limit=15):
    """Returns (hits, suggestions) as lists of song dicts.

    Every matching library file is its own hit (Iann verdict 2026-08-20 #4:
    duplicates are shown, never collapsed); ``hit_limit=None`` means all."""
    qn = normalize(query)
    qf = normalize(query, fused=True)
    if not qn:
        return [], []
    tokens = qn.split()

    hits = []
    for e in index:
        tok_hit = all(t in e["full"] or t in e["fullf"] for t in tokens)
        fused_hit = len(qf) >= 3 and qf in e["fullf"]
        if tok_hit or fused_hit:
            # rank: whole query inside the title > inside title+artist > anywhere
            if qn in e["rtitle"] or qf in e["rtitlef"]:
                rank = 0
            elif qn in e["ta"] or qf in e["taf"]:
                rank = 1
            else:
                rank = 2
            hits.append((rank, e))
    hits.sort(key=lambda pair: (pair[0], pair[1]["ntitle"]))
    ranked_hits = hits if hit_limit is None else hits[:hit_limit]
    hit_songs = [e["song"] for _, e in ranked_hits]

    suggestions = []
    if len(hit_songs) < 8 and len(qn) >= 3:
        seen = {s["file"] for s in hit_songs}
        scored = []
        for e in index:
            if e["song"]["file"] in seen:
                continue
            sc = _fuzzy_score(qn, qf, e)
            if sc >= 64:
                scored.append((sc, e))
        scored.sort(key=lambda pair: -pair[0])
        suggestions = [e["song"] for _, e in scored[:sugg_limit]]

    return hit_songs, suggestions


class SearchCatalog:
    """Own Ampere's immutable search snapshots and result presentation.

    The Qt backend remains the public facade, but it should not also own the
    rules for artist intent, album grouping, lyric snippets, and snapshot
    consistency. Replacing complete references keeps reads cheap and safe
    while the index and lyric workers finish on background threads.
    """

    EMPTY_RESULT = {"hits": [], "suggestions": [], "artists": [],
                    "albums": [], "artistFirst": False, "best": None,
                    "lyrics": []}

    def __init__(self, *,
                 artist_path: Callable[[str, str], str] | None = None):
        self._playcounts: Mapping[str, int] = {}
        self._artist_path = artist_path or (lambda _file, _name: "")
        self._index: tuple[dict, ...] = ()
        self._lyrics: dict[str, str] = {}
        self._generation = 0
        self._lock = Lock()

    @property
    def index(self) -> tuple[dict, ...]:
        return self._index

    @property
    def generation(self) -> int:
        return self._generation

    def snapshot(self) -> tuple[int, tuple[dict, ...]]:
        with self._lock:
            return self._generation, self._index

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def replace_songs(self, songs: Sequence[dict]) -> int:
        """Publish a complete new library snapshot and invalidate lyrics."""
        return self.replace_index(build_index(list(songs)))

    def replace_index(self, index: Sequence[dict]) -> int:
        """Publish an index already built by the owning library repository."""
        with self._lock:
            self._index = tuple(index)
            self._lyrics = {}
            self._generation += 1
            return self._generation

    def replace_playcounts(self, values: Mapping[str, int]) -> None:
        """Publish one immutable artist-ranking snapshot for lock-free reads."""
        self._playcounts = {
            str(file): int(count) for file, count in values.items()
        }

    def replace_lyrics(self, lyrics: Mapping[str, str], generation: int) -> bool:
        """Publish lyric text only if it belongs to the current library."""
        cleaned = {str(file): str(text).lower() for file, text in lyrics.items()
                   if file and text}
        with self._lock:
            if generation != self._generation:
                return False
            self._lyrics = cleaned
            return True

    def query(self, text: str) -> dict:
        text = text.strip()
        if len(text) < 2:
            return dict(self.EMPTY_RESULT)
        index = self._index
        hits, suggestions = search(index, text)
        hits = _disambiguated(hits)
        suggestions = _disambiguated(suggestions)
        artists = self._artists(index, text)
        qn = normalize(text)
        artist_first = bool(artists) and (
            (artists[0]["tier"] == 0 and len(qn) >= 3)
            or (artists[0]["span"] >= 0.45
                and (artists[0]["tier"] <= 1 or artists[0]["score"] >= 92)))
        albums = self._albums(index, text, hits=hits)
        return {"hits": hits, "suggestions": suggestions, "artists": artists,
                "albums": albums, "artistFirst": artist_first,
                "best": _best_match(text, hits, suggestions, artists, albums,
                                    artist_first),
                "lyrics": []}

    def lyric_query(self, text: str, limit: int = 12) -> list[dict]:
        query = text.strip().lower()
        if len(query) < 3:
            return []
        index, lyrics = self._index, self._lyrics
        songs = {entry["song"]["file"]: entry["song"] for entry in index}
        out = []
        for file, lyric in lyrics.items():
            offset = lyric.find(query)
            song = songs.get(file)
            if offset < 0 or not song:
                continue
            result = dict(song)
            excerpt = lyric[max(0, offset - 32):offset + len(query) + 32].strip()
            result["snippet"] = f"…{excerpt}…"
            out.append(result)
            if len(out) >= limit:
                break
        return out

    def _artists(self, index: Sequence[dict], text: str,
                 limit: int | None = None) -> list[dict]:
        qn, qf = normalize(text), normalize(text, fused=True)
        if not qn:
            return []
        seen, plays = {}, {}
        counts = self._playcounts
        for entry in index:
            song = entry["song"]
            name = song.get("artist") or ""
            if not name:
                continue
            seen.setdefault(name, song["file"])
            plays[name] = plays.get(name, 0) + int(counts.get(song["file"], 0) or 0)
        ranked = []
        for name, file in seen.items():
            normal, fused = searchable(name), searchable(name, fused=True)
            if normal.startswith(qn) or fused.startswith(qf):
                tier, score = 0, 100
            elif qn in normal or qf in fused:
                tier, score = 1, 94
            elif len(qn) >= 4:
                words = set(normal.split()) | set(fused.split()) | {normal, fused}
                score = max(fuzz.ratio(qn, word) for word in words)
                if score < 85:
                    continue
                tier = 2
            else:
                continue
            ranked.append((tier, -score, -plays.get(name, 0), len(normal),
                           name, file, score))
        ranked.sort()
        out = []
        for tier, _, _, _, name, file, score in (
                ranked if limit is None else ranked[:limit]):
            path = self._artist_path(file, name)
            out.append({"name": name, "path": path, "cover": path or file,
                        "score": score, "tier": tier,
                        "span": min(1.0, len(qn) / max(1, len(normalize(name))))})
        return out

    @staticmethod
    def _albums(index: Sequence[dict], text: str, limit: int | None = None,
                hits: Sequence[dict] = ()) -> list[dict]:
        """Albums whose name matches, then albums holding matching songs.

        Each row carries ``nameMatch`` and ``matchingSongs`` so the sleeve
        row can state "Artist · Album" or "Artist · 2 matching songs"."""
        qn, qf = normalize(text), normalize(text, fused=True)
        if not qn:
            return []
        hit_counts: dict[tuple[str, str], int] = {}
        for song in hits:
            album = song.get("album") or ""
            if album:
                key = (str(PurePosixPath(song["file"]).parent), album.casefold())
                hit_counts[key] = hit_counts.get(key, 0) + 1
        seen: dict[tuple[str, str], dict] = {}
        for entry in index:
            song = entry["song"]
            album = song.get("album") or ""
            if album:
                directory = str(PurePosixPath(song["file"]).parent)
                key = (directory, album.casefold())
                release = seen.setdefault(key, {
                    "album": album, "dir": directory, "tracks": [],
                })
                release["tracks"].append(song)
        ranked = []
        for key, release in seen.items():
            album = release["album"]
            normal, fused = searchable(album), searchable(album, fused=True)
            count = hit_counts.get(key, 0)
            if qn in normal or qf in fused:
                ranked.append((0 if normal.startswith(qn) else 1,
                               len(normal), album, release["dir"], release,
                               True, count))
            elif count:
                ranked.append((2, -count, album, release["dir"], release,
                               False, count))
        ranked.sort(key=lambda row: row[:4])
        result = []
        for _, _, album, directory, release, name_match, count in (
                ranked if limit is None else ranked[:limit]):
            tracks = release["tracks"]
            result.append({
                "album": album,
                "artist": AlbumPresenter.primary_artist(
                    directory, tracks, various_label="Various artists"),
                "cover": tracks[0]["file"],
                "year": next((str(track.get("year")) for track in tracks
                              if track.get("year")), ""),
                "dir": directory,
                "trackCount": len(tracks),
                "nameMatch": name_match,
                "matchingSongs": count,
            })
        return result


def _disambiguated(songs: Sequence[dict]) -> list[dict]:
    """Copy each song with ``format`` and a ``disambiguate`` flag.

    Every file stays its own row (verdict #4). Rows sharing title + artist
    are told apart by the album in their sub line; the format suffix is
    added only when title + artist + album are all identical, because only
    then does the sub line fail to separate them."""
    keys = []
    for song in songs:
        keys.append((normalize(str(song.get("title") or "")),
                     normalize(str(song.get("artist") or "")),
                     normalize(str(song.get("album") or ""))))
    counts: dict[tuple[str, str, str], int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    out = []
    for song, key in zip(songs, keys):
        row = dict(song)
        row["format"] = format_label(song.get("file", ""))
        row["disambiguate"] = counts[key] > 1
        out.append(row)
    return out


def _best_match(text: str, hits: Sequence[dict], suggestions: Sequence[dict],
                artists: Sequence[dict], albums: Sequence[dict],
                artist_first: bool) -> dict | None:
    """Pick the hero by exact tiers (audit S-03).

    Tier 0: the query *is* a title, album, or artist name.
    Tier 1: the query starts an artist (existing artist-first rule), an
            album, or a title.
    Tier 2: any substring hit — songs, then albums, then artists.
    Tier 3: a fuzzy suggestion, flagged ``exact: False`` ("CLOSEST MATCH").
    """
    qn, qf = normalize(text), normalize(text, fused=True)
    if not qn:
        return None

    def equal(value) -> bool:
        value = str(value or "")
        return normalize(value) == qn or normalize(value, fused=True) == qf

    def starts(value) -> bool:
        value = str(value or "")
        return (normalize(value).startswith(qn)
                or normalize(value, fused=True).startswith(qf))

    def pick(kind, item, exact=True):
        return {"kind": kind, "item": dict(item), "exact": exact}

    for song in hits:
        if equal(song.get("title")):
            return pick("song", song)
    for album in albums:
        if album.get("nameMatch") and equal(album.get("album")):
            return pick("album", album)
    for artist in artists:
        if equal(artist.get("name")):
            return pick("artist", artist)
    if artist_first and artists:
        return pick("artist", artists[0])
    for album in albums:
        if album.get("nameMatch") and starts(album.get("album")):
            return pick("album", album)
    for song in hits:
        if starts(song.get("title")):
            return pick("song", song)
    if hits:
        return pick("song", hits[0])
    if any(album.get("nameMatch") for album in albums):
        return pick("album", next(a for a in albums if a.get("nameMatch")))
    if artists:
        return pick("artist", artists[0])
    if suggestions:
        return pick("song", suggestions[0], exact=False)
    return None


def run_quick_search(catalog: "SearchCatalog", query: str, *, serial: int,
                     lyrics_pending: bool, on_ready: Callable[[str, dict], None],
                     on_failed: Callable[[str, int, str], None]) -> bool:
    """One quick-search job body: never lets an exception vanish (S-06).

    The result carries ``serial`` and the catalog ``generation`` so the UI can
    reject anything older than its newest request (S-08)."""
    try:
        generation = catalog.generation
        result = catalog.query(query)
        result["lyrics"] = [] if lyrics_pending else catalog.lyric_query(query)
        result["lyricsPending"] = bool(lyrics_pending)
        result["serial"] = int(serial)
        result["generation"] = int(generation)
    except Exception as exc:  # noqa: BLE001 — the UI needs the failure
        on_failed(query, int(serial), str(exc) or exc.__class__.__name__)
        return False
    on_ready(query, result)
    return True


class LyricIndexer:
    """Build one lyric-search snapshot and stop when its catalog is stale."""

    def __init__(self, catalog: SearchCatalog, music_root: str | Path, *,
                 read_lyrics):
        self._catalog = catalog
        self._music_root = Path(music_root)
        self._read_lyrics = read_lyrics

    def scan(self, *, should_stop=lambda: False) -> LyricIndexResult:
        generation, index = self._catalog.snapshot()
        total = len(index)
        done = indexed = failed = 0
        lyrics = {}
        for entry in index:
            if should_stop() or not self._catalog.is_current(generation):
                return LyricIndexResult(
                    generation, total, done, indexed, failed,
                    cancelled=True, published=False)
            try:
                file = entry["song"]["file"]
                lines, _synced = self._read_lyrics(
                    str(self._music_root / file))
                text = " / ".join(
                    str(line.get("line") or "") for line in lines
                    if line.get("line"))
                if text:
                    lyrics[file] = text.lower()
                    indexed += 1
            except Exception:
                failed += 1
            done += 1

        published = self._catalog.replace_lyrics(lyrics, generation)
        return LyricIndexResult(
            generation, total, done, indexed, failed,
            cancelled=not published, published=published)
