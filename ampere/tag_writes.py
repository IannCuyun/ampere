"""Process-wide serialization for audio-tag read/modify/write transactions."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path


_registry_lock = threading.Lock()
_path_locks: dict[str, threading.RLock] = {}


def _key(path: str | Path) -> str:
    return str(Path(path).resolve())


@contextmanager
def tag_write_lock(path: str | Path):
    """Hold the shared lock for one canonical audio-file path.

    The registry intentionally lives for the process lifetime. Its upper bound
    is the number of files tagged in a session, and retaining locks avoids a
    lock-removal race while another writer is waiting to acquire one.
    """
    key = _key(path)
    with _registry_lock:
        lock = _path_locks.setdefault(key, threading.RLock())
    with lock:
        yield
