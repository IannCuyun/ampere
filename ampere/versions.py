"""Pure policy for alternate recordings and preferred song versions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


VersionKey = tuple[str, str]


class VersionPolicy:
    """Identify sibling versions and select one per generated session."""

    _STRIP = re.compile(
        r"\s*[\(\[][^)\]]*[\)\]]|\s*-\s*(radio edit|single version|"
        r"album version|live|remaster(ed)?( \d{4})?)\s*$", re.IGNORECASE)

    @classmethod
    def key(cls, song: Mapping) -> VersionKey | None:
        title = cls._STRIP.sub("", str(song.get("title") or "")).strip().casefold()
        artist = str(song.get("artist") or "").split(",", 1)[0].strip().casefold()
        return (artist, title) if artist and title else None

    @classmethod
    def groups(cls, songs: Sequence[Mapping]) -> dict[VersionKey, list[str]]:
        grouped: dict[VersionKey, list[str]] = {}
        for song in songs:
            file = str(song.get("file") or "")
            if file and (key := cls.key(song)):
                grouped.setdefault(key, []).append(file)
        return {key: files for key, files in grouped.items() if len(files) > 1}

    @staticmethod
    def collapse(files: Sequence[str], *, groups: Mapping[VersionKey, Sequence[str]],
                 playcounts: Mapping[str, int],
                 preferences: Mapping[str, object]) -> list[str]:
        """Keep a preferred, otherwise most-played, sibling in the input."""
        if not groups:
            return list(files)
        member = {file: key for key, siblings in groups.items()
                  for file in siblings}
        if not any(file in member for file in files):
            return list(files)
        candidates = set(files)
        winner: dict[VersionKey, str] = {}
        for key, siblings in groups.items():
            present = [file for file in siblings if file in candidates]
            if len(present) < 2:
                continue
            winner[key] = (next((file for file in present
                                 if preferences.get(file)), None)
                           or max(present, key=lambda file: playcounts.get(file, 0)))
        return [file for file in files
                if member.get(file) not in winner
                or file == winner[member[file]]]

    @classmethod
    def siblings(cls, file: str, *, songs: Sequence[Mapping]) -> list[str]:
        song = next((song for song in songs if song.get("file") == file), None)
        if not song or not (key := cls.key(song)):
            return []
        return cls.groups(songs).get(key, [])

    @staticmethod
    def doctor_groups(*, groups: Mapping[VersionKey, Sequence[str]],
                      playcounts: Mapping[str, int],
                      preferences: Mapping[str, object]) -> list[dict]:
        return [{
            "title": title.title(), "artist": artist.title(),
            "files": [{"file": file, "plays": playcounts.get(file, 0),
                       "pref": bool(preferences.get(file))}
                      for file in files],
        } for (artist, title), files in sorted(groups.items())]
