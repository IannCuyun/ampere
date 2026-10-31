"""Typed access to Ampere's durable MPD song stickers."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayRecordResult:
    recorded: bool
    played_at: int | None = None
    stickers_saved: bool = True
    play_count: int | None = None


@dataclass(frozen=True)
class ExclusiveStickerResult:
    committed: bool
    rollback_complete: bool = True


@dataclass(frozen=True)
class StickerReadResult:
    available: bool
    value: object = None


@dataclass(frozen=True)
class StickerFamilyResult:
    available: bool
    values: dict[str, str]
    retained: bool = False


def sticker_value(value, default=""):
    if value is None:
        return default
    value = str(value)
    return value.split("=", 1)[1] if "=" in value else value


class StickerRepository:
    def __init__(self, *, read, write, client, clock=time.time,
                 error=lambda _message: None, observe=None):
        self._read = read
        self._write = write
        self._client = client
        self._clock = clock
        self._error = error
        self._observe = observe
        self._snapshots: dict[str, dict[str, str]] = {}
        self._failed_snapshots: set[str] = set()
        self._snapshot_warning_active = False
        self._snapshot_lock = threading.Lock()

    def raw(self, file: str, name: str, *, default="", quiet=True):
        if not file:
            return default
        value = self._read(
            "sticker_get", "song", file, name, default=None, quiet=quiet)
        return default if value is None else sticker_value(value, default)

    def raw_observed(self, file: str, name: str, *, default="") \
            -> StickerReadResult:
        if not file:
            return StickerReadResult(True, default)
        if self._observe is None:
            return StickerReadResult(True, self.raw(file, name, default=default))
        result = self._observe(
            "sticker_get", "song", file, name, default=None,
            missing_ok=True, quiet=True)
        if not result.available:
            return StickerReadResult(False, default)
        value = default if result.value is None else sticker_value(
            result.value, default)
        return StickerReadResult(True, value)

    def integer(self, file: str, name: str, *, default=0) -> int:
        try:
            return int(self.raw(file, name, default=str(default)))
        except (TypeError, ValueError):
            return default

    def number(self, file: str, name: str, *, default=0.0) -> float:
        try:
            return float(self.raw(file, name, default=str(default)))
        except (TypeError, ValueError):
            return default

    def values_result(self, name: str, client=None) -> StickerFamilyResult:
        """Return the latest verified whole-family snapshot.

        A failed or malformed ``sticker_find`` is not an empty family. Keep
        the last verified values so recommendations and history do not vanish
        during a transient MPD outage.
        """
        client = client or self._client
        if client is self._client:
            rows = self._read(
                "sticker_find", "song", "", name, default=None, quiet=True)
        else:
            try:
                rows = client.sticker_find("song", "", name)
            except Exception:
                rows = None
        out = {}
        valid = isinstance(rows, (list, tuple))
        if valid:
            for row in rows:
                if not isinstance(row, dict):
                    valid = False
                    break
                file = str(row.get("file", ""))
                raw = row.get("sticker", "")
                if not file or "=" not in str(raw):
                    valid = False
                    break
                out[file] = sticker_value(raw)
        with self._snapshot_lock:
            if valid:
                self._snapshots[str(name)] = dict(out)
                self._failed_snapshots.discard(str(name))
                if not self._failed_snapshots:
                    self._snapshot_warning_active = False
                return StickerFamilyResult(True, dict(out))
            self._failed_snapshots.add(str(name))
            if not self._snapshot_warning_active:
                self._error(
                    "Listening data could not be refreshed — keeping the "
                    "last verified recommendations and history; try again "
                    "after the playback connection recovers")
                self._snapshot_warning_active = True
            retained = str(name) in self._snapshots
            return StickerFamilyResult(
                False, dict(self._snapshots.get(str(name), {})), retained)

    def values(self, name: str, client=None) -> dict[str, str]:
        return self.values_result(name, client).values

    def integers(self, name: str, client=None) -> dict[str, int]:
        out = {}
        for file, value in self.values(name, client).items():
            try:
                out[file] = int(value)
            except (TypeError, ValueError):
                pass
        return out

    def set(self, file: str, name: str, value, *, quiet=True) -> bool:
        return bool(file and self._write(
            "sticker_set", "song", file, name, str(value), quiet=quiet))

    def delete(self, file: str, name: str, *, quiet=True) -> bool:
        return bool(file and self._write(
            "sticker_delete", "song", file, name, quiet=quiet))

    def record_play(self, file: str) -> PlayRecordResult:
        if not file or file.startswith("/"):
            return PlayRecordResult(False)
        played_at = int(self._clock())
        observed = self.raw_observed(file, "playCount", default="0")
        if not observed.available:
            # Preserve the append-only play log, but never replace an unknown
            # durable count with a fallback 1 after the connection recovers.
            return PlayRecordResult(
                True, played_at, stickers_saved=False)
        try:
            count = int(observed.value)
        except (TypeError, ValueError):
            count = 0
        count_saved = self.set(file, "playCount", count + 1)
        last_saved = self.set(file, "lastPlayed", played_at)
        return PlayRecordResult(
            True, played_at, count_saved and last_saved,
            count + 1 if count_saved else None)

    def set_exclusive(self, files, selected: str, name: str,
                      value="1") -> ExclusiveStickerResult:
        """Make one file the sole sticker owner, rolling back partial writes.

        MPD has no multi-song sticker transaction. Capture the prior values,
        write the selected value first, then remove only existing sibling
        values. If any mutation fails, restore every touched file so a partial
        preference cannot silently become durable.
        """
        files = list(dict.fromkeys(str(file) for file in files if file))
        selected = str(selected or "")
        if selected not in files:
            return ExclusiveStickerResult(False)
        before = {file: self.raw(file, name, default=None) for file in files}
        touched = []

        def mutate(file, old):
            if file == selected:
                if old == str(value):
                    return True
                ok = self.set(file, name, value)
            elif old is None:
                return True
            else:
                ok = self.delete(file, name)
            if ok:
                touched.append(file)
            return ok

        if all(mutate(file, before[file]) for file in files):
            return ExclusiveStickerResult(True)

        rollback_complete = True
        for file in reversed(touched):
            old = before[file]
            if old is None:
                rollback_complete = self.delete(file, name) and rollback_complete
            else:
                rollback_complete = self.set(file, name, old) and rollback_complete
        return ExclusiveStickerResult(False, rollback_complete)
