"""Pure album presentation and long-form chapter policy."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence

from .artists import artist_key, canonical_artist_name, song_credited_artists


class AlbumPresenter:
    """Build the stable AlbumView contract from explicit snapshots."""

    @staticmethod
    def primary_artist(path: str, tracks: Sequence[Mapping],
                       *, various_label: str = "VARIOUS ARTISTS") -> str:
        """Return the album's primary discography artist, not track guests.

        ``albumartist`` is the authoritative album-level tag. Older libraries
        without that tag fall back to the owning artist folder when it appears
        in the track credits, then to a strict majority of exact artist tags.
        """
        album_artists = [str(track.get("albumartist", "")).strip()
                         for track in tracks if track.get("albumartist")]
        if album_artists:
            counts = Counter(album_artists)
            winner, votes = counts.most_common(1)[0]
            if sum(count == votes for count in counts.values()) == 1:
                return winner
            return various_label

        artists = [str(track.get("artist", "")).strip()
                   for track in tracks if track.get("artist")]
        if not artists:
            return ""

        owner = os.path.basename(os.path.dirname(path.rstrip("/"))).strip()
        if owner and any(owner.casefold() in artist.casefold()
                         for artist in artists):
            return owner

        counts = Counter(artists)
        winner, votes = counts.most_common(1)[0]
        if votes > len(artists) / 2:
            return winner
        return various_label

    @staticmethod
    def present(path: str, *, files: Sequence[str],
                library: Mapping[str, Mapping], year: str = "") -> dict:
        tracks = [dict(library[file]) for file in files if file in library]
        fallback = os.path.basename(path.rstrip("/"))
        album = next((track.get("album") for track in tracks
                      if track.get("album")), fallback)
        artist = AlbumPresenter.primary_artist(path, tracks)
        total = sum(AlbumPresenter._duration(track) for track in tracks)
        return {"album": album, "artist": artist, "year": year,
                "tracks": tracks, "total": total, "path": path,
                "cover": files[0] if files else ""}

    @staticmethod
    def _duration(track: Mapping) -> float:
        try:
            return float(track.get("duration", 0) or 0)
        except (TypeError, ValueError):
            return 0.0


class ChapterDetector:
    """Find quiet section boundaries in a cached RMS waveform."""

    MIN_DURATION = 20 * 60
    MIN_PEAKS = 40
    MIN_SPACING = 90.0
    MAX_CHAPTERS = 24

    @classmethod
    def detect(cls, duration: float, peaks: Sequence[float]) -> list[float]:
        try:
            duration = float(duration)
            values = [float(value) for value in peaks]
        except (TypeError, ValueError):
            return []
        if duration < cls.MIN_DURATION or len(values) < cls.MIN_PEAKS:
            return []
        window = 5
        smooth = [
            sum(values[max(0, index - window):index + window + 1])
            / len(values[max(0, index - window):index + window + 1])
            for index in range(len(values))
        ]
        median = sorted(smooth)[len(smooth) // 2] or 0.001
        marks: list[float] = []
        for index in range(2, len(smooth) - 2):
            if (smooth[index] < 0.4 * median
                    and smooth[index] <= smooth[index - 1]
                    and smooth[index] <= smooth[index + 1]):
                timestamp = index / len(smooth) * duration
                if all(abs(timestamp - mark) >= cls.MIN_SPACING for mark in marks):
                    marks.append(round(timestamp, 1))
                    if len(marks) == cls.MAX_CHAPTERS:
                        break
        return marks


class LibraryDirectory:
    """Pure read models for the six Library destinations (L.01 contract).

    Every method takes explicit snapshot data and returns plain rows for QML.
    No I/O, no Qt: the caller feeds the verified in-memory library generation.
    """

    RESERVED_ROOTS = ("Playlists",)

    @staticmethod
    def _credit_keys(songs) -> set[str]:
        """Return creator identities that must never become genre rooms.

        A caller holding a published library generation already has this set
        (`LibraryRepository.credit_keys`) and should pass it rather than pay
        for a second library-wide scan on Qt's thread."""
        keys: set[str] = set()
        for song in songs:
            values = song.get("creditNames") or ()
            if isinstance(values, str):
                values = (values,)
            for value in (*values, song.get("artist", ""),
                          song.get("albumartist", "")):
                name = " ".join(str(value or "").split()).strip()
                if name:
                    keys.add(name.casefold())
        return keys

    @classmethod
    def albums(cls, songs) -> list[dict]:
        """One row per tagged album, even when albums share one folder."""
        rows: dict[tuple[str, str], dict] = {}
        for song in songs:
            file = str(song.get("file", ""))
            folder = os.path.dirname(file)
            if not folder or file.split("/", 1)[0] in cls.RESERVED_ROOTS:
                continue
            album = str(song.get("album", "")).strip()
            key = (folder, album.casefold())
            row = rows.get(key)
            if row is None:
                row = rows[key] = {
                    "path": folder,
                    "album": album, "artist": "", "year": "",
                    "cover": file, "added": 0.0, "songs": 0,
                    "_credits": [],
                }
            row["songs"] += 1
            if not row["year"] and song.get("year"):
                row["year"] = str(song["year"])
            row["_credits"].append({
                "artist": song.get("artist", ""),
                "albumartist": song.get("albumartist", ""),
            })
            try:
                row["added"] = max(row["added"],
                                   float(song.get("added", 0) or 0))
            except (TypeError, ValueError):
                pass
        result = []
        for row in rows.values():
            row["artist"] = AlbumPresenter.primary_artist(
                row["path"], row.pop("_credits"),
                various_label="Various artists")
            if not row["album"]:
                row["album"] = os.path.basename(row["path"])
            result.append(row)
        result.sort(key=lambda item: -item["added"])
        return result

    @staticmethod
    def artists(songs, artist_path) -> list[dict]:
        """One row per canonical credited artist, with no collaboration rows."""
        rows: dict[str, dict] = {}
        for song in songs:
            file = str(song.get("file", ""))
            for artist in song_credited_artists(song):
                name = canonical_artist_name(artist)
                key = artist_key(name)
                row = rows.get(key)
                if row is None:
                    row = rows[key] = {
                        "name": name, "portrait": file,
                        "path": artist_path(file, name),
                        "songs": 0, "_albums": set(),
                    }
                row["songs"] += 1
                folder = os.path.dirname(file)
                album = str(song.get("album", "")).strip().casefold()
                if folder or album:
                    row["_albums"].add((folder, album))
        result = []
        for row in rows.values():
            row["albums"] = len(row.pop("_albums"))
            result.append(row)
        result.sort(key=lambda item: item["name"].casefold())
        return result

    @classmethod
    def genres(cls, songs, credit_keys=None) -> list[dict]:
        """Embedded-tag genre rooms with two distinct album-art anchors.

        The directory tree is deliberately absent from genre identity. It may
        help establish album identity for counting and art diversity, but a
        folder name can never create or rename a genre.
        """
        songs = tuple(songs)
        blocked = (cls._credit_keys(songs) if credit_keys is None
                   else credit_keys)
        rows: dict[str, dict] = {}
        for song in songs:
            file = str(song.get("file", ""))
            raw_genres = song.get("genres") or ()
            genres = ([raw_genres] if isinstance(raw_genres, str)
                      else raw_genres)
            for raw_genre in genres:
                name = " ".join(str(raw_genre or "").split()).strip()
                key = name.casefold()
                if not key or key in blocked:
                    continue
                row = rows.get(key)
                if row is None:
                    row = rows[key] = {
                        "name": name, "cover": "", "covers": [],
                        "songs": 0, "_albums": set(), "_artists": set(),
                    }
                row["songs"] += 1
                folder = os.path.dirname(file)
                album = str(song.get("album", "")).strip().casefold()
                album_key = (folder or file, album)
                if album_key not in row["_albums"]:
                    row["_albums"].add(album_key)
                    if file and len(row["covers"]) < 2:
                        row["covers"].append(file)
                if song.get("artist"):
                    row["_artists"].add(str(song["artist"]).casefold())
        result = []
        for row in rows.values():
            row["albums"] = len(row.pop("_albums"))
            row["artists"] = len(row.pop("_artists"))
            row["cover"] = row["covers"][0] if row["covers"] else ""
            result.append(row)
        result.sort(key=lambda item: item["name"].casefold())
        return result

    @classmethod
    def genre_detail(cls, songs, name: str, *, credit_keys=None,
                     members=None) -> dict:
        """Project one exact embedded genre into albums and playable tracks.

        ``credit_keys`` and ``members`` come from the published library
        generation when the caller has one. Both were re-derived here by
        scanning the whole library twice — the cost the Genres room paid on
        Qt's thread every time it opened.
        """
        wanted = " ".join(str(name or "").split()).strip().casefold()
        blocked = (cls._credit_keys(tuple(songs)) if credit_keys is None
                   else credit_keys)
        if not wanted or wanted in blocked:
            return {}
        rows = tuple(songs) if members is None else tuple(members)
        members = []
        canonical_name = ""
        for song in rows:
            raw_genres = song.get("genres") or ()
            genres = [raw_genres] if isinstance(raw_genres, str) else raw_genres
            for raw_genre in genres:
                genre = " ".join(str(raw_genre or "").split()).strip()
                if genre.casefold() == wanted:
                    canonical_name = canonical_name or genre
                    members.append(dict(song))
                    break
        if not members:
            return {}

        summary = next(
            (row for row in cls.genres(members, blocked)
             if row["name"].casefold() == wanted), {})
        return {
            **summary,
            "name": canonical_name,
            "albums": cls.albums(members),
            "tracks": members,
        }

    @staticmethod
    def folders(songs, path: str = "") -> list[dict]:
        """Direct child folders of ``path`` with item counts and freshness."""
        path = str(path or "").strip("/")
        prefix = path + "/" if path else ""
        rows: dict[str, dict] = {}
        order: list[str] = []
        for song in songs:
            file = str(song.get("file", ""))
            if prefix and not file.startswith(prefix):
                continue
            rest = file[len(prefix):]
            if "/" not in rest:
                continue
            child = rest.split("/", 1)[0]
            if child.startswith("."):
                continue
            row = rows.get(child)
            if row is None:
                row = rows[child] = {
                    "name": child,
                    "path": prefix + child,
                    "cover": file, "items": 0, "modified": 0.0,
                }
                order.append(child)
            row["items"] += 1
            try:
                row["modified"] = max(row["modified"],
                                      float(song.get("added", 0) or 0))
            except (TypeError, ValueError):
                pass
        return [rows[name] for name in sorted(order, key=str.casefold)]
