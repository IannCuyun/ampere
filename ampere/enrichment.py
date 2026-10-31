"""Scheduling state for independent background library enrichment jobs."""

from __future__ import annotations

import threading


class EnrichmentCoordinator:
    """Own named-job exclusivity and coalesced rerun requests."""

    def __init__(self, workers):
        self._workers = workers
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._pending: set[str] = set()

    def running(self, key: str) -> bool:
        with self._lock:
            return key in self._active

    def launch(self, key: str, target, *, args=(), thread_name=None,
               coalesce=False, on_finished=None) -> str:
        """Launch one named job, returning started/busy/pending/stopping."""
        with self._lock:
            if key in self._active:
                if coalesce:
                    self._pending.add(key)
                    return "pending"
                return "busy"
            self._active.add(key)

        def run():
            try:
                target(*args)
            finally:
                with self._lock:
                    self._active.discard(key)
                if on_finished is not None:
                    on_finished()

        if self._workers.start(run, name=thread_name):
            return "started"
        with self._lock:
            self._active.discard(key)
        return "stopping"

    def consume_pending(self, key: str) -> bool:
        """Consume one coalesced rerun request after its completion callback."""
        with self._lock:
            if key not in self._pending:
                return False
            self._pending.remove(key)
            return True

