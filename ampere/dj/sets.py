"""Read-only recovery policy for persisted DJ set history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..persistence import atomic_write_json


@dataclass(frozen=True)
class SavedSetCatalog:
    sets: tuple[dict, ...] = ()
    invalid: int = 0
    error: str = ""


@dataclass(frozen=True)
class ReplaySelection:
    data: dict | None = None
    songs: tuple[str, ...] = ()


def save_set_snapshot(directory: str | Path, snapshot: dict,
                      *, retain: int = 20) -> bool:
    """Durably replace one session record and best-effort prune old sets."""
    root = Path(directory)
    try:
        started = int(snapshot.get("started", 0))
        atomic_write_json(root / f"{started}.json", snapshot)
    except (OSError, TypeError, ValueError):
        return False
    try:
        paths = sorted(root.glob("*.json"), reverse=True)
        for path in paths[max(0, int(retain)):]:
            path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def load_saved_sets(directory: str | Path) -> SavedSetCatalog:
    """Return valid set documents newest-first, skipping damaged entries."""
    root = Path(directory)
    try:
        paths = [path for path in root.iterdir()
                 if path.is_file() and path.suffix == ".json"]
        paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except FileNotFoundError:
        return SavedSetCatalog()
    except OSError as exc:
        return SavedSetCatalog(error=str(exc))

    valid = []
    invalid = 0
    for path in paths:
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError, TypeError):
            invalid += 1
            continue
        songs = value.get("songs") if isinstance(value, dict) else None
        if (not isinstance(songs, list)
                or not any(isinstance(song, str) and song for song in songs)):
            invalid += 1
            continue
        valid.append(value)
    return SavedSetCatalog(tuple(valid), invalid)


def select_replayable_set(
        candidates: Iterable[dict], known_files: set[str] | frozenset[str],
        *, absolute_exists: Callable[[str], bool]) -> ReplaySelection:
    """Select the newest set with at least one song still available."""
    known = set(known_files)
    for data in candidates:
        songs = tuple(
            song for song in data.get("songs", ())
            if (isinstance(song, str) and song
                and (not known or song in known
                     or (song.startswith("/") and absolute_exists(song))))
        )
        if songs:
            return ReplaySelection(data, songs)
    return ReplaySelection()
