"""Framework-independent snapshots and presentation helpers for the library."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from dataclasses import dataclass
from types import MappingProxyType

from . import search as searchlib
from .artists import (artist_key, primary_artist_credit,
                      song_credited_artists, split_featured)


def _normalize_genres(value) -> list[str]:
    """Return stable embedded genre identities without inventing taxonomy.

    MPD may expose repeated GENRE frames as a list while some taggers encode
    several values in one semicolon-delimited frame. Commas and slashes remain
    part of the genre name because both are common, meaningful genre syntax.
    """
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for part in str(raw or "").split(";"):
            genre = " ".join(part.split()).strip()
            key = genre.casefold()
            if genre and key not in seen:
                seen.add(key)
                result.append(genre)
    return result


def _normalize_credit_names(value) -> list[str]:
    """Preserve each embedded attribution identity as a normalized name."""
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = " ".join(str(raw or "").split()).strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _credit_identities(value) -> list[str]:
    """Expand combined display credits without altering their display text."""
    result: list[str] = []
    seen: set[str] = set()
    for frame in _normalize_credit_names(value):
        # MPD may return either repeated ARTIST frames or one tagger-authored
        # comma/semicolon credit line. Keep the full credit and its people as
        # attribution identities; do not split slash or ampersand artist names.
        # A guest is a real attribution identity, not part of the primary
        # billing: "Travis Scott Feat. Drake" files under BOTH (SPEC row 38,
        # UNDESIGNED #17 resolved 2026-08-21).
        candidates = [frame]
        for part in re.split(r"\s*[,;]\s*", frame):
            primary, guests = split_featured(part)
            candidates.extend([part, primary, *guests])
        for candidate in candidates:
            name = " ".join(candidate.split()).strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                result.append(name)
    return result


def normalize_song(song: Mapping) -> dict:
    """Normalize an MPD song dictionary into Ampere's stable QML schema."""
    file = str(song.get("file", ""))
    title = song.get("title") or os.path.splitext(os.path.basename(file))[0]
    artist_names = _normalize_credit_names(
        song.get("artist") or song.get("albumartist") or "")
    albumartist_names = _normalize_credit_names(song.get("albumartist") or "")
    artist = ", ".join(artist_names)
    albumartist = ", ".join(albumartist_names)
    if isinstance(title, list):
        title = title[0] if title else ""
    album = song.get("album", "")
    if isinstance(album, list):
        album = album[0] if album else ""
    try:
        duration = float(song.get("duration") or song.get("time") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    range_start = range_end = 0.0
    value = song.get("range", "")
    if value and "-" in value:
        try:
            low, high = value.split("-", 1)
            range_start = float(low or 0)
            range_end = float(high) if high else 0.0
        except (TypeError, ValueError):
            range_start = range_end = 0.0
    try:
        position = int(song.get("pos", -1))
    except (TypeError, ValueError):
        position = -1
    try:
        song_id = int(song.get("id", -1))
    except (TypeError, ValueError):
        song_id = -1
    date = song.get("date") or song.get("originaldate") or song.get("year") or ""
    if isinstance(date, (list, tuple)):
        date = date[0] if date else ""
    match = re.search(r"(?:^|\D)(\d{4})(?:\D|$)", str(date))
    year = match.group(1) if match else ""
    added = 0.0
    modified = song.get("last-modified", "")
    if isinstance(modified, (list, tuple)):
        modified = modified[0] if modified else ""
    if modified:
        try:
            added = datetime.fromisoformat(
                str(modified).replace("Z", "+00:00")).timestamp()
        except ValueError:
            added = 0.0
    # Attribution duplicated into GENRE is malformed metadata, not a new
    # music taxonomy. Preserve the individual repeated credit frames before
    # joining the display artist and fail closed against every common role.
    credit_names: list[str] = []
    credit_keys: set[str] = set()
    for field in ("artist", "albumartist", "composer", "performer",
                  "conductor", "ensemble"):
        for name in _credit_identities(song.get(field) or ""):
            key = name.casefold()
            if key not in credit_keys:
                credit_keys.add(key)
                credit_names.append(name)
    genres = [genre for genre in _normalize_genres(song.get("genre", ()))
              if genre.casefold() not in credit_keys]
    return {
        **{key: song[key] for key in ("musicbrainz_artistid", "musicbrainz_trackid",
                                     "musicbrainz_recordingid") if song.get(key)},
        "type": "file", "file": file, "title": title,
        "artist": artist, "albumartist": albumartist,
        "creditNames": credit_names,
        "album": album, "duration": duration,
        "id": song_id, "pos": position,
        "rangeStart": range_start, "rangeEnd": range_end,
        "year": year, "added": added,
        "genre": genres[0] if genres else "", "genres": genres,
    }


@dataclass(frozen=True)
class LibrarySnapshot:
    songs: tuple[dict, ...]
    by_file: Mapping[str, dict]
    search_index: tuple[dict, ...]
    browse: Mapping[str, tuple[dict, ...]]
    generation: int
    # Membership, derived once on the index worker with the generation it
    # belongs to. The GUI thread answers "which files" with a dict lookup
    # instead of a scan whose cost grows with the collection.
    by_artist: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    folder_rows: Mapping[str, tuple[dict, ...]] = MappingProxyType({})
    by_genre: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    credit_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LibraryIndexResult:
    success: bool
    generation: int = 0
    total: int = 0
    search_index: tuple[dict, ...] = ()
    error: str = ""
    directory: Mapping[str, tuple[dict, ...]] | None = None


@dataclass(frozen=True)
class LibraryPathResult:
    success: bool
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class LibraryStatsResult:
    success: bool
    songs: int = 0
    albums: int = 0
    artists: int = 0
    playtime_hours: float = 0.0


@dataclass(frozen=True)
class LibraryUpdateResult:
    success: bool
    started: bool = False
    already_running: bool = False
    confirmed: bool = True


class LibraryUpdateController:
    """Start one MPD database job without replaying an ambiguous request."""

    def __init__(self, *, read, write_once):
        self._read = read
        self._write_once = write_once

    @staticmethod
    def _running(status) -> bool:
        return isinstance(status, Mapping) and bool(status.get("updating_db"))

    def request(self, path: str = "") -> LibraryUpdateResult:
        baseline = self._read("status", default=None)
        if baseline is None:
            return LibraryUpdateResult(False, confirmed=False)
        if self._running(baseline):
            return LibraryUpdateResult(
                True, already_running=True)

        args = (str(path),) if path else ()
        if self._write_once("update", *args, quiet=True):
            return LibraryUpdateResult(True, started=True)

        observed = self._read("status", default=None)
        if observed is None:
            return LibraryUpdateResult(False, confirmed=False)
        if self._running(observed):
            return LibraryUpdateResult(True, started=True)
        return LibraryUpdateResult(False)


class LibraryRepository:
    """Own the current immutable music-database snapshot."""

    def __init__(self):
        self._snapshot = LibrarySnapshot(
            (), MappingProxyType({}), (), MappingProxyType({}), 0)
        self._path_snapshots: dict[str, tuple[str, ...]] = {}
        self._stats_snapshot = LibraryStatsResult(False)

    @property
    def songs(self) -> tuple[dict, ...]:
        return self._snapshot.songs

    @property
    def by_file(self) -> Mapping[str, dict]:
        return self._snapshot.by_file

    @property
    def search_index(self) -> tuple[dict, ...]:
        return self._snapshot.search_index

    @property
    def generation(self) -> int:
        return self._snapshot.generation

    @property
    def stats(self) -> LibraryStatsResult:
        """Return the last verified totals without touching MPD."""
        return self._stats_snapshot

    def replace(self, songs: Sequence[Mapping]) -> int:
        normalized = tuple(normalize_song(song) for song in songs
                           if song.get("file")
                           and ".sync-conflict-" not in str(song["file"]))
        by_file = MappingProxyType({song["file"]: song for song in normalized})
        search_index = tuple(searchlib.build_index(list(normalized)))
        browse = self._build_browse_snapshot(normalized)
        by_artist, by_genre, credit_keys = self._build_membership(normalized)
        folder_rows = self._build_folder_rows(normalized)
        generation = self._snapshot.generation + 1
        # One reference assignment publishes a coherent generation to readers.
        self._snapshot = LibrarySnapshot(
            normalized, by_file, search_index, browse, generation,
            by_artist, folder_rows, by_genre, credit_keys)
        return generation

    @staticmethod
    def _build_membership(songs: Sequence[Mapping]):
        """Index artist and genre membership in one pass over a generation.

        Both were library-wide scans on Qt's thread every time a room opened.
        The rows they produced never change within a generation, so they are
        derived here — on the same worker that builds the generation — and
        read back by key. Library order is preserved: this walks the songs in
        their published order, so the answer is byte-identical to the scan.
        """
        by_artist: dict[str, list[str]] = {}
        by_genre: dict[str, list[str]] = {}
        credit_keys: set[str] = set()
        for song in songs:
            file = song["file"]
            for name in song_credited_artists(song):
                by_artist.setdefault(artist_key(name), []).append(file)
            genres = song.get("genres") or ()
            for genre in ((genres,) if isinstance(genres, str) else genres):
                key = str(genre).casefold()
                if key:
                    by_genre.setdefault(key, []).append(file)
            values = song.get("creditNames") or ()
            if isinstance(values, str):
                values = (values,)
            for value in (*values, song.get("artist", ""),
                          song.get("albumartist", "")):
                name = " ".join(str(value or "").split()).strip()
                if name:
                    credit_keys.add(name.casefold())
        return (
            MappingProxyType({k: tuple(v) for k, v in by_artist.items()}),
            MappingProxyType({k: tuple(v) for k, v in by_genre.items()}),
            frozenset(credit_keys),
        )

    @staticmethod
    def _build_browse_snapshot(
            songs: Sequence[Mapping]) -> Mapping[str, tuple[dict, ...]]:
        """Derive every direct-child folder view from one library generation."""
        directories: dict[str, dict[str, dict]] = {}
        tracks: dict[str, list[dict]] = {}
        for song in songs:
            file = str(song.get("file", "")).strip("/")
            if not file:
                continue
            parts = file.split("/")
            parent = ""
            for segment in parts[:-1]:
                child = f"{parent}/{segment}" if parent else segment
                if not segment.startswith("."):
                    directories.setdefault(parent, {}).setdefault(
                        child, {"type": "dir", "path": child,
                                "name": segment, "cover": file})
                parent = child
            tracks.setdefault(parent, []).append(dict(song))

        paths = set(directories) | set(tracks)
        rows = {
            path: tuple((*directories.get(path, {}).values(),
                         *tracks.get(path, ())))
            for path in paths
        }
        return MappingProxyType(rows)

    @staticmethod
    def _build_folder_rows(
            songs: Sequence[Mapping]) -> Mapping[str, tuple[dict, ...]]:
        """Derive every folder's child rows from one generation, in one pass.

        `LibraryDirectory.folders` re-scanned the whole library for each
        folder the listener opened, on Qt's thread. The rows are identical
        for a given generation, so they are derived here instead — with the
        same order, cover, count and freshness rules, which
        `test_library_performance_contract` pins field for field.
        """
        rows: dict[str, dict[str, dict]] = {}
        for song in songs:
            file = str(song.get("file", ""))
            try:
                added = float(song.get("added", 0) or 0)
            except (TypeError, ValueError):
                added = 0.0
            parts = file.split("/")
            parent = ""
            # Every ancestor counts this track: "items" is what lies beneath.
            for segment in parts[:-1]:
                child = f"{parent}/{segment}" if parent else segment
                # A dotted folder is not offered as a destination, but it is
                # still a real path: what lies below it stays reachable.
                if not segment.startswith("."):
                    children = rows.setdefault(parent, {})
                    row = children.get(segment)
                    if row is None:
                        row = children[segment] = {
                            "name": segment, "path": child,
                            "cover": file, "items": 0, "modified": 0.0,
                        }
                    row["items"] += 1
                    if added > row["modified"]:
                        row["modified"] = added
                parent = child
        return MappingProxyType({
            path: tuple(children[name] for name
                        in sorted(children, key=str.casefold))
            for path, children in rows.items()
        })

    def folders(self, path: str) -> list[dict]:
        """Return the published child rows for one folder, in display order."""
        path = str(path or "").strip("/")
        return [dict(row) for row in self._snapshot.folder_rows.get(path, ())]

    def files_under(self, path: str) -> list[str]:
        """Return snapshot files at or below ``path`` in library order."""
        path = str(path or "").strip("/")
        if not path:
            return [song["file"] for song in self._snapshot.songs]
        prefix = path + "/"
        return [song["file"] for song in self._snapshot.songs
                if song["file"] == path or song["file"].startswith(prefix)]

    def browse(self, path: str) -> tuple[dict, ...]:
        """Return immutable direct children from the verified generation."""
        return self._snapshot.browse.get(str(path or "").strip("/"), ())

    def publish_path(self, path: str, entries) -> LibraryPathResult:
        path = str(path or "")
        if entries is None:
            return LibraryPathResult(
                False, self._path_snapshots.get(path, ()))
        try:
            files = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    raise TypeError("malformed listall row")
                if entry.get("file"):
                    files.append(str(entry["file"]))
        except Exception:
            return LibraryPathResult(
                False, self._path_snapshots.get(path, ()))
        snapshot = tuple(files)
        self._path_snapshots[path] = snapshot
        return LibraryPathResult(True, snapshot)

    def publish_stats(self, values) -> LibraryStatsResult:
        """Publish only a complete MPD stats snapshot, retaining prior truth."""
        try:
            if not isinstance(values, Mapping):
                raise TypeError("malformed stats snapshot")
            required = ("songs", "albums", "artists", "db_playtime")
            if any(key not in values for key in required):
                raise ValueError("incomplete stats snapshot")
            songs, albums, artists, playtime = (
                int(values[key]) for key in required)
            if min(songs, albums, artists, playtime) < 0:
                raise ValueError("negative stats value")
            snapshot = LibraryStatsResult(
                True, songs, albums, artists, round(playtime / 3600, 1))
        except (TypeError, ValueError, OverflowError):
            prior = self._stats_snapshot
            return LibraryStatsResult(
                False, prior.songs, prior.albums, prior.artists,
                prior.playtime_hours)
        self._stats_snapshot = snapshot
        return snapshot

    @staticmethod
    def artist_path(file: str, artist: str) -> str:
        artist_normal = (artist or "").lower().strip()
        parts = file.split("/")[:-1]
        loose = None
        for index, part in enumerate(parts, start=1):
            segment = part.lower().strip()
            if not segment or not artist_normal:
                continue
            if segment == artist_normal:
                return "/".join(parts[:index])
            if loose is None and (segment in artist_normal or artist_normal in segment):
                loose = "/".join(parts[:index])
        return loose or "/".join(parts)

    def artist_discography(self, files: Sequence[str],
                           playcounts: Mapping[str, int]) -> list[dict]:
        albums, order = {}, []
        for file in sorted(files):
            song = self._snapshot.by_file.get(file)
            if not song:
                continue
            album = song.get("album") or ""
            if album not in albums:
                albums[album] = {"album": album, "cover": file,
                                 "plays": 0, "tracks": []}
                order.append(album)
            albums[album]["tracks"].append(song)
            albums[album]["plays"] += int(playcounts.get(file, 0) or 0)
        result = [albums[album] for album in order]
        result.sort(key=lambda item: (item["album"] == "", -item["plays"]))
        return result

    def artist_files(self, artist: str) -> list[str]:
        """Return exact library-order membership for one canonical artist.

        Membership follows the normalized ARTIST and ALBUMARTIST credits rather
        than a directory path.  That makes aliases and collaborations visible
        on every credited artist page without duplicating a track.
        """
        # Direct navigation can hand us the original display credit.  Resolve
        # its first contributor rather than querying a fabricated combined
        # identity; the recording itself remains indexed beneath every credit.
        wanted = artist_key(primary_artist_credit(artist))
        if not wanted:
            return []
        return list(self._snapshot.by_artist.get(wanted, ()))

    def genre_files(self, genre: str) -> list[str]:
        """Return library-order membership for one exact embedded genre."""
        wanted = " ".join(str(genre or "").split()).strip().casefold()
        if not wanted:
            return []
        return list(self._snapshot.by_genre.get(wanted, ()))

    @property
    def credit_keys(self) -> frozenset[str]:
        """Creator identities that must never become genre rooms."""
        return self._snapshot.credit_keys

    def artist_discography_for(self, artist: str,
                               playcounts: Mapping[str, int]) -> list[dict]:
        """Group one canonical artist's exact credited tracks by release."""
        return self.artist_discography(self.artist_files(artist), playcounts)


class LibraryIndexer:
    """Read and atomically publish one complete MPD library generation."""

    def __init__(self, repository: LibraryRepository, search_catalog, *,
                 client_scope):
        self._repository = repository
        self._search_catalog = search_catalog
        self._client_scope = client_scope

    def rebuild(self) -> LibraryIndexResult:
        try:
            with self._client_scope() as client:
                songs = client.listallinfo()
            if songs is None:
                raise RuntimeError("MPD returned no library snapshot")
            generation = self._repository.replace(songs)
            search_index = self._repository.search_index
            self._search_catalog.replace_index(search_index)
            return LibraryIndexResult(
                True, generation=generation,
                total=len(self._repository.songs), search_index=search_index)
        except Exception as exc:
            return LibraryIndexResult(
                False, generation=self._repository.generation,
                error=type(exc).__name__)
