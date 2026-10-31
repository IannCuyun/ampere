"""Append-only persistence for Ampere's listening history."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


_UNAVAILABLE = object()


@dataclass(frozen=True)
class PlayHistorySnapshot:
    entries: tuple[tuple[int, str], ...]
    first_played: Mapping[str, int]


class PlayHistoryRepository:
    """Own tolerant JSONL reads, appends, and coherent cached snapshots.

    The on-disk schema stays exactly ``{"f": <file>, "t": <epoch>}``; existing
    history is read in place and never migrated or rewritten.
    """

    def __init__(self, path: Path, *, clock=time.time):
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._signature: tuple[int, int] | None = None
        self._snapshot = PlayHistorySnapshot((), MappingProxyType({}))

    def append(self, file: str, *, played_at: int | None = None) -> bool:
        if not file:
            return False
        played = int(self._clock() if played_at is None else played_at)
        record = json.dumps({"f": file, "t": played}, ensure_ascii=False,
                            separators=(",", ":"))
        with self._lock:
            descriptor = None
            directory_descriptor = None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                existed = self._path.exists()
                payload = (record + "\n").encode("utf-8")
                descriptor = os.open(
                    self._path,
                    os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC,
                    0o600)
                # A crash can leave a partial final record. Separate the next
                # append so it cannot be swallowed by that damaged JSON line.
                if os.fstat(descriptor).st_size:
                    os.lseek(descriptor, -1, os.SEEK_END)
                    if os.read(descriptor, 1) != b"\n":
                        payload = b"\n" + payload
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("history append made no progress")
                    view = view[written:]
                os.fsync(descriptor)
                if not existed:
                    directory_descriptor = os.open(
                        self._path.parent,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                    os.fsync(directory_descriptor)
            except OSError:
                return False
            finally:
                if directory_descriptor is not None:
                    try:
                        os.close(directory_descriptor)
                    except OSError:
                        pass
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            # Invalidate instead of mutating the cached snapshot: the next read
            # re-opens the authoritative file and also incorporates any other
            # process that appended between our reads.
            self._signature = None
        return True

    def snapshot(self) -> PlayHistorySnapshot:
        with self._lock:
            signature = self._file_signature()
            if signature is _UNAVAILABLE:
                return self._snapshot
            if signature is not None and signature == self._signature:
                return self._snapshot
            if signature is None:
                self._signature = None
                self._snapshot = PlayHistorySnapshot((), MappingProxyType({}))
                return self._snapshot
            entries: list[tuple[int, str]] = []
            try:
                with self._path.open("rb") as stream:
                    for line in stream:
                        try:
                            entry = self._parse(line.decode("utf-8"))
                        except UnicodeDecodeError:
                            continue
                        if entry:
                            entries.append(entry)
            except OSError:
                return self._snapshot
            first: dict[str, int] = {}
            for played, file in entries:
                if file not in first or played < first[file]:
                    first[file] = played
            self._signature = signature
            self._snapshot = PlayHistorySnapshot(
                tuple(entries), MappingProxyType(first))
            return self._snapshot

    def _file_signature(self) -> tuple[int, int] | None | object:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            return None
        except OSError:
            return _UNAVAILABLE
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _parse(line: str) -> tuple[int, str] | None:
        try:
            value = json.loads(line)
            played = int(value.get("t", 0))
            file = value.get("f", "")
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError,
                OverflowError):
            return None
        return (played, file) if played > 0 and isinstance(file, str) and file else None
