"""Spotify -> local playlist bridge for Ampere.

Imports one of Iann's Spotify playlists (the Crate series etc.) and
MATERIALIZES it as a local M3U built from library files he actually owns.

Auth piggybacks on the existing spotify-crate credentials
(~/.config/spotify-crate/config.json — client_id/client_secret/refresh_token);
no secrets live in this repo.

Feb-2026 Spotify API quirks respected:
  * playlist track reads are GET /playlists/{id}/items, rows may carry the
    track under an "item" key (new) or "track" (old) — both handled
  * no batch /artists calls (403), no search needed here

Matching is offline: MPD library index vs. Spotify metadata, normalized with
ampere.search.normalize, tiered exact -> fuzzy (rapidfuzz).

CLI:
  python -m ampere.spotbridge --list
  python -m ampere.spotbridge --sync NAME [--dir DIR]
"""

import argparse
import json
import sys
import time
from base64 import b64encode
from pathlib import Path

import requests
from rapidfuzz import fuzz

from ampere.persistence import atomic_write_text
from ampere.search import normalize

CONFIG = Path.home() / ".config" / "spotify-crate" / "config.json"
API = "https://api.spotify.com/v1"
DEFAULT_PLAYLISTS_DIR = "~/MusicLibrary/Playlists"

FUZZY_ARTIST_MIN = 75   # tier 2: exact title, fuzzy artist
FUZZY_TITLE_MIN = 87    # tier 3: fuzzy title
FUZZY_TITLE_ARTIST_MIN = 60  # tier 3 still needs the artist in the ballpark


# ---------------------------------------------------------------- Spotify API

def token() -> str:
    cfg = json.loads(CONFIG.read_text())
    basic = b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "refresh_token", "refresh_token": cfg["refresh_token"],
    }, headers={"Authorization": f"Basic {basic}"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _get(tok: str, path: str, params=None) -> dict:
    for attempt in range(8):
        r = requests.get(f"{API}{path}", params=params, timeout=20,
                         headers={"Authorization": f"Bearer {tok}"})
        if r.status_code == 429:
            wait = min(int(r.headers.get("Retry-After", "30")) + 5, 300)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def list_playlists(tok: str | None = None) -> list[dict]:
    """The user's own playlists: [{id, name, count}], paginated."""
    tok = tok or token()
    out, offset = [], 0
    while True:
        page = _get(tok, "/me/playlists", {"limit": 50, "offset": offset})
        for pl in page.get("items", []):
            if not pl:
                continue
            # Feb-2026 API: track count lives under "items"; older shape "tracks"
            meta = pl.get("items") or pl.get("tracks") or {}
            out.append({"id": pl["id"], "name": pl["name"],
                        "count": meta.get("total", 0)})
        offset += 50
        if not page.get("next") or not page.get("items"):
            break
    return out


def fetch_tracks(playlist_id: str, tok: str | None = None) -> list[dict]:
    """[{title, artist, album}] via /playlists/{id}/items.

    Rows may nest the track under "item" (Feb-2026 API) or "track" (older
    shape) — both handled. Local files / episodes / null rows are skipped.
    """
    tok = tok or token()
    out, offset = [], 0
    while True:
        page = _get(tok, f"/playlists/{playlist_id}/items",
                    {"limit": 100, "offset": offset})
        rows = page.get("items", [])
        for row in rows:
            t = (row or {}).get("item") or (row or {}).get("track")
            if not t or t.get("type") == "episode" or not t.get("name"):
                continue
            out.append({
                "title": t["name"],
                "artist": ", ".join(a["name"] for a in t.get("artists", []) if a),
                "album": (t.get("album") or {}).get("name", ""),
            })
        offset += 100
        if not page.get("next") or not rows:
            break
    return out


# ------------------------------------------------------------------- matching

def _first_artist(artist: str) -> str:
    return artist.split(",")[0].strip() if artist else ""


def match(tracks: list[dict], index: list[dict]) -> dict:
    """Match Spotify tracks against a local library index (no network).

    index: [{"file", "title", "artist"}, ...]
    Returns {"matched": [(spotify_track, local_file, score)], "missing": [...]}.
    Tiers: exact normalized title+artist -> exact title + fuzzy artist ->
    fuzzy title (>= 87) with the artist at least in the ballpark.
    """
    entries = []
    by_ta = {}       # (ntitle, nartist) -> entry, spaced + fused forms
    by_title = {}    # ntitle -> [entries]
    for s in index:
        e = {
            "file": s["file"],
            "nt": normalize(s.get("title", "")),
            "ntf": normalize(s.get("title", ""), fused=True),
            "na": normalize(s.get("artist", "")),
            "naf": normalize(s.get("artist", ""), fused=True),
        }
        if not e["nt"]:
            continue
        entries.append(e)
        by_ta.setdefault((e["nt"], e["na"]), e)
        by_ta.setdefault((e["ntf"], e["naf"]), e)
        by_title.setdefault(e["nt"], []).append(e)
        by_title.setdefault(e["ntf"], []).append(e)

    matched, missing = [], []
    for t in tracks:
        qt, qtf = normalize(t["title"]), normalize(t["title"], fused=True)
        # try the full artist string and the primary artist alone
        artists = [t["artist"], _first_artist(t["artist"])]
        qas = [normalize(a) for a in artists if a]
        qafs = [normalize(a, fused=True) for a in artists if a]

        # tier 1: exact normalized title+artist
        hit = None
        for ta in [(qt, a) for a in qas] + [(qtf, a) for a in qafs]:
            if ta in by_ta:
                hit = (by_ta[ta], 100)
                break
        # tier 2: exact title, fuzzy artist
        if not hit:
            best, best_sc = None, 0
            for e in by_title.get(qt, []) + by_title.get(qtf, []):
                sc = max(fuzz.token_set_ratio(a, e["na"]) for a in qas) if qas else 0
                if sc > best_sc:
                    best, best_sc = e, sc
            if best and best_sc >= FUZZY_ARTIST_MIN:
                hit = (best, best_sc)
        # tier 3: fuzzy title, artist in the ballpark
        if not hit:
            best, best_sc = None, 0
            for e in entries:
                tsc = max(fuzz.token_set_ratio(qt, e["nt"]),
                          fuzz.token_set_ratio(qtf, e["ntf"]))
                if tsc < FUZZY_TITLE_MIN:
                    continue
                asc = max(fuzz.token_set_ratio(a, e["na"]) for a in qas) if qas else 0
                if asc < FUZZY_TITLE_ARTIST_MIN:
                    continue
                sc = 0.7 * tsc + 0.3 * asc
                if sc > best_sc:
                    best, best_sc = e, sc
            if best:
                hit = (best, round(best_sc, 1))

        if hit:
            matched.append((t, hit[0]["file"], hit[1]))
        else:
            missing.append(t)
    return {"matched": matched, "missing": missing}


# -------------------------------------------------------------- materializing

def materialize(name: str, files: list[str],
                playlists_dir: str = DEFAULT_PLAYLISTS_DIR) -> str:
    """Write '<name> (Spotify).m3u' with library-relative paths (MPD
    convention: relative to the music root, no leading slash). Overwrites."""
    pdir = Path(playlists_dir).expanduser()
    pdir.mkdir(parents=True, exist_ok=True)
    # Playlist names are remote data. Keep separators/control characters from
    # escaping the selected directory or creating surprising nested paths.
    safe_name = "".join(
        " " if ch in "/\\" or ord(ch) < 32 else ch for ch in name
    ).strip().strip(".")
    if not safe_name:
        raise ValueError("playlist name has no usable filename characters")
    path = pdir / f"{safe_name} (Spotify).m3u"
    lines = [f.lstrip("/") for f in files]
    if not any(lines):
        raise ValueError(
            "refusing to replace a local playlist with no matched tracks")
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return str(path)


# ---------------------------------------------------------------------- sync

def sync(playlist_name_or_id: str, index: list[dict],
         playlists_dir: str = DEFAULT_PLAYLISTS_DIR) -> dict:
    """Import one Spotify playlist as a local M3U. Returns a report dict."""
    tok = token()
    playlists = list_playlists(tok)
    pl = next((p for p in playlists
               if p["id"] == playlist_name_or_id
               or p["name"].lower() == playlist_name_or_id.lower()), None)
    if pl is None:
        raise ValueError(f"no Spotify playlist named/with id {playlist_name_or_id!r}; "
                         f"have: {', '.join(p['name'] for p in playlists)}")

    tracks = fetch_tracks(pl["id"], tok)
    if not tracks:
        raise ValueError(f"Spotify playlist {pl['name']!r} contains no tracks")
    res = match(tracks, index)
    files, seen = [], set()
    for _t, f, _sc in res["matched"]:
        if f not in seen:
            seen.add(f)
            files.append(f)
    if not files:
        raise ValueError(
            f"none of the {len(tracks)} Spotify tracks matched the local library")
    m3u = materialize(pl["name"], files, playlists_dir)
    return {
        "name": pl["name"],
        "total": len(tracks),
        "matched": len(res["matched"]),
        "missing": [f"{t['artist']} — {t['title']}" for t in res["missing"]],
        "m3u": m3u,
    }


# ----------------------------------------------------------------------- CLI

def _mpd_index(host: str = "localhost", port: int = 6600) -> list[dict]:
    from .mpdgateway import close_mpd_client, create_mpd_client
    c = create_mpd_client()
    c.connect(host, port)
    try:
        songs = c.listallinfo()
    finally:
        close_mpd_client(c)

    def _s(v):  # mpd2 may hand back lists for multi-value tags
        return ", ".join(v) if isinstance(v, list) else (v or "")

    return [{"file": s["file"], "title": _s(s.get("title", "")),
             "artist": _s(s.get("artist", ""))}
            for s in songs if "file" in s]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ampere.spotbridge",
                                 description="Materialize a Spotify playlist as a local M3U.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="list your Spotify playlists")
    g.add_argument("--sync", metavar="NAME", help="playlist name or id to import")
    ap.add_argument("--dir", default=DEFAULT_PLAYLISTS_DIR,
                    help=f"playlists dir (default {DEFAULT_PLAYLISTS_DIR})")
    args = ap.parse_args(argv)

    if args.list:
        for p in list_playlists():
            print(f"{p['id']}  {p['count']:>4}  {p['name']}")
        return 0

    report = sync(args.sync, _mpd_index(), args.dir)
    print(f"{report['name']}: {report['matched']}/{report['total']} matched "
          f"-> {report['m3u']}")
    if report["missing"]:
        print(f"missing ({len(report['missing'])}):")
        for m in report["missing"]:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
