"""Scoped maintenance for Ampere's regenerable media caches."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CacheClearResult:
    success: bool
    cleared: tuple[str, ...] = ()
    already_empty: tuple[str, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()


class CacheMaintenanceService:
    """Remove only the explicitly owned caches supplied at construction."""

    def __init__(self, caches: dict[str, str | Path], *, remove=shutil.rmtree):
        self._caches = {name: Path(path) for name, path in caches.items()}
        self._remove = remove

    def clear(self) -> CacheClearResult:
        cleared = []
        already_empty = []
        failures = []
        for name, path in self._caches.items():
            try:
                self._remove(path)
            except FileNotFoundError:
                already_empty.append(name)
            except OSError as exc:
                failures.append((name, str(exc)))
            else:
                cleared.append(name)
        return CacheClearResult(
            not failures, tuple(cleared), tuple(already_empty), tuple(failures))
