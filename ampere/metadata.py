"""Safe FLAC metadata editing with one-time recovery snapshots."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from mutagen.flac import FLAC

from .persistence import atomic_write_json
from .tag_writes import tag_write_lock


EDITABLE_FIELDS = (
    "title", "artist", "album", "albumartist", "genre", "date",
    "tracknumber",
)


@dataclass(frozen=True)
class MetadataUpdate:
    parent: str
    backup_path: Path


class MetadataService:
    def __init__(self, library_root: str | Path, backup_dir: str | Path, *,
                 flac_factory=FLAC):
        self._library_root = Path(library_root).resolve()
        self._backup_dir = Path(backup_dir)
        self._flac_factory = flac_factory
        self._backup_lock = threading.Lock()

    def read(self, file: str) -> dict:
        try:
            path = self._path(file, require_flac=False)
            if path.suffix.casefold() != ".flac":
                return {"editable": False,
                        "error": "Metadata editing currently supports FLAC files"}
            audio = self._flac_factory(path)
            first = lambda key: str((audio.get(key) or [""])[0])
            return {"editable": True, "file": file,
                    **{key: first(key) for key in EDITABLE_FIELDS}}
        except Exception as exc:
            return {"editable": False, "error": str(exc)}

    def update(self, file: str, values: Mapping) -> MetadataUpdate:
        path = self._path(file, require_flac=True)
        backup_path = self._backup_path(file)
        desired = {key: str(values.get(key, "")).strip()
                   for key in EDITABLE_FIELDS}
        with tag_write_lock(path):
            audio = self._flac_factory(path)
            with self._backup_lock:
                if not backup_path.exists():
                    tags = audio.tags or {}
                    atomic_write_json(
                        backup_path,
                        {"file": file,
                         "tags": {str(key): list(value)
                                  for key, value in tags.items()}}, indent=2)
            for key, value in desired.items():
                if value:
                    audio[key] = [value]
                elif key in audio:
                    del audio[key]
            audio.save()
            verified = self._flac_factory(path)
            for key, expected in desired.items():
                actual = str((verified.get(key) or [""])[0])
                if actual != expected:
                    raise OSError(
                        f"Metadata save could not be verified ({key})")
        parent = str(PurePosixPath(file).parent)
        return MetadataUpdate("" if parent == "." else parent, backup_path)

    def _path(self, file: str, *, require_flac: bool) -> Path:
        relative = PurePosixPath(str(file or ""))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("Track is outside the library")
        path = (self._library_root / Path(*relative.parts)).resolve()
        if not path.is_relative_to(self._library_root) or not path.is_file():
            raise ValueError("Track is outside the library")
        if require_flac and path.suffix.casefold() != ".flac":
            raise ValueError("Only FLAC tracks inside the library are editable")
        return path

    def _backup_path(self, file: str) -> Path:
        digest = hashlib.sha1(str(file).encode(),
                              usedforsecurity=False).hexdigest()
        return self._backup_dir / f"{digest}.json"
