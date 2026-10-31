"""Single-owner admission for structural MPD queue transactions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class QueueMutationResult(Generic[T]):
    accepted: bool
    value: T | None = None
    generation: int = 0
    active_owner: str = ""


class QueueMutationLease:
    """One explicitly released coordinator admission."""

    def __init__(self, coordinator, owner: str, generation: int):
        self._coordinator = coordinator
        self.owner = owner
        self.generation = generation
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._coordinator._release(self.owner, self.generation)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.release()


class QueueMutationCoordinator:
    """Admit one structural queue transaction without blocking its caller.

    The operation itself may run on Qt or on an owned worker. Contenders are
    rejected immediately instead of waiting on a lock and freezing the UI.
    Generation advances at admission, so evidence captured before a mutation
    can be recognized as stale by later asynchronous boundaries.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._owner = ""

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def active_owner(self) -> str:
        with self._lock:
            return self._owner

    def run(self, owner: str, operation: Callable[[], T]) -> QueueMutationResult[T]:
        lease, rejected = self.acquire(owner)
        if lease is None:
            return rejected
        try:
            return QueueMutationResult(
                True, operation(), generation=lease.generation,
                active_owner=lease.owner)
        finally:
            lease.release()

    def acquire(self, owner: str):
        """Return ``(lease, result)``; rejected acquisition never waits."""
        owner = str(owner or "queue")
        with self._lock:
            if self._owner:
                return None, QueueMutationResult(
                    False, generation=self._generation,
                    active_owner=self._owner)
            self._generation += 1
            generation = self._generation
            self._owner = owner
        return QueueMutationLease(self, owner, generation), None

    def _release(self, owner: str, generation: int) -> None:
        with self._lock:
            if self._owner == owner and self._generation == generation:
                self._owner = ""
