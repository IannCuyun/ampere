"""Viewport-first scheduling for artist biographies and portraits."""

from __future__ import annotations

from collections import OrderedDict, deque
import threading
from typing import Callable, Iterable


URGENT = 0
NEARBY = 1
IDLE = 2


class ArtistPortraitCoordinator:
    """Coalesce portrait work and spend remote slots on what can be seen.

    The coordinator is deliberately independent of Qt.  QML reports visible
    intent; this object owns cache hydration, priority, concurrency, retries,
    and process-lifetime work through ``WorkerRegistry``.
    """

    def __init__(self, service, workers, *, canonicalize: Callable[[str], str],
                 on_result: Callable[[str, dict], None],
                 on_batch: Callable[[dict], None], max_workers: int = 4,
                 max_idle: int = 2, retry_delay: float = 1.4,
                 memory_limit: int = 2048):
        self._service = service
        self._workers = workers
        self._canonicalize = canonicalize
        self._on_result = on_result
        self._on_batch = on_batch
        self._max_workers = max(1, int(max_workers))
        self._max_idle = max(0, min(int(max_idle), self._max_workers))
        self._retry_delay = max(0.0, float(retry_delay))
        self._memory_limit = max(32, int(memory_limit))
        self._lock = threading.RLock()
        self._active = False
        self._generation = 0
        self._current: set[str] = set()
        self._names: dict[str, str] = {}
        self._subscribers: dict[str, OrderedDict[str, None]] = {}
        self._queues = (deque(), deque(), deque())
        self._queued_priority: dict[str, int] = {}
        self._inflight: dict[str, int] = {}
        self._attempts: dict[str, int] = {}
        self._retry_waiting: set[str] = set()
        self._retry_priorities: dict[str, int] = {}
        self._results: OrderedDict[str, dict] = OrderedDict()

    @staticmethod
    def _clean(value) -> str:
        return " ".join(str(value or "").split()).strip()

    def _identity(self, value) -> tuple[str, str, str]:
        requested = self._clean(value)
        canonical = self._clean(self._canonicalize(requested)) or requested
        return canonical.casefold(), canonical, requested

    def _subscribe_locked(self, key: str, canonical: str,
                          requested: str) -> None:
        self._names[key] = canonical
        aliases = self._subscribers.setdefault(key, OrderedDict())
        if requested:
            aliases[requested] = None

    def _enqueue_locked(self, key: str, priority: int) -> bool:
        priority = max(URGENT, min(IDLE, int(priority)))
        if key in self._results:
            return False
        if key in self._retry_waiting:
            previous = self._retry_priorities.get(key, IDLE)
            self._retry_priorities[key] = min(previous, priority)
            return False
        if key in self._inflight:
            if priority < self._inflight[key]:
                self._inflight[key] = priority
            return False
        previous = self._queued_priority.get(key)
        if previous is not None and previous <= priority:
            return False
        self._queued_priority[key] = priority
        self._queues[priority].append(key)
        return True

    def _remember_locked(self, key: str, result: dict) -> None:
        self._results[key] = dict(result or {})
        self._results.move_to_end(key)
        while len(self._results) > self._memory_limit:
            candidate = next(iter(self._results))
            if candidate in self._current:
                self._results.move_to_end(candidate)
                if all(item in self._current for item in self._results):
                    break
                continue
            self._results.popitem(last=False)

    def prime(self, names: Iterable[str]) -> None:
        """Hydrate every valid portrait from disk, then seed idle misses."""
        identities = []
        seen = set()
        for value in names or ():
            key, canonical, requested = self._identity(value)
            if not key:
                continue
            identities.append((key, canonical, requested))
            seen.add(key)
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._current = seen
            for key, priority in tuple(self._queued_priority.items()):
                if priority == IDLE and key not in seen:
                    self._queued_priority.pop(key, None)
            for key, canonical, requested in identities:
                self._subscribe_locked(key, canonical, requested)

        def scan():
            maintain = getattr(
                self._service, "maintain_portrait_cache", None)
            if callable(maintain):
                maintain()
            cached: dict[str, dict] = {}
            for key, canonical, _requested in identities:
                if self._workers.stop_requested.is_set():
                    return
                if key in cached:
                    continue
                result = self._service.peek_cached(canonical)
                if result and result.get("portrait"):
                    cached[key] = dict(result)

            batch = {}
            with self._lock:
                if generation != self._generation:
                    return
                for key, result in cached.items():
                    self._remember_locked(key, result)
                    self._queued_priority.pop(key, None)
                    for alias in self._subscribers.get(key, {}):
                        batch[alias] = str(result.get("portrait") or "")
                seeded = set()
                for key, _canonical, _requested in identities:
                    if key not in cached and key not in seeded:
                        seeded.add(key)
                        self._enqueue_locked(key, IDLE)
            if batch:
                self._on_batch(batch)
            self._dispatch()

        self._workers.start(
            scan, name=f"ampere-artist-portrait-cache-{generation}")

    def prioritize(self, visible: Iterable[str], nearby: Iterable[str]) -> None:
        emits = []
        with self._lock:
            for values, priority in ((visible or (), URGENT),
                                     (nearby or (), NEARBY)):
                for value in values:
                    key, canonical, requested = self._identity(value)
                    if not key:
                        continue
                    self._subscribe_locked(key, canonical, requested)
                    result = self._results.get(key)
                    if result is not None:
                        self._results.move_to_end(key)
                        emits.append((requested, dict(result)))
                    else:
                        self._enqueue_locked(key, priority)
        for name, result in emits:
            self._on_result(name, result)
        self._dispatch()

    def request(self, name: str) -> None:
        """Request one full profile urgently for Search or Artist detail."""
        self.prioritize((name,), ())

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = bool(active)
        if active:
            self._dispatch()

    def _pop_locked(self, priority: int) -> str | None:
        queue = self._queues[priority]
        while queue:
            key = queue.popleft()
            if self._queued_priority.get(key) != priority:
                continue
            self._queued_priority.pop(key, None)
            if key in self._results or key in self._inflight:
                continue
            return key
        return None

    def _next_locked(self) -> tuple[str, int] | None:
        for priority in (URGENT, NEARBY):
            key = self._pop_locked(priority)
            if key is not None:
                return key, priority
        if not self._active or self._max_idle <= 0:
            return None
        idle_inflight = sum(
            1 for priority in self._inflight.values() if priority == IDLE)
        if idle_inflight >= self._max_idle:
            return None
        key = self._pop_locked(IDLE)
        return (key, IDLE) if key is not None else None

    def _dispatch(self) -> None:
        tasks = []
        with self._lock:
            if self._workers.stop_requested.is_set():
                return
            while len(self._inflight) < self._max_workers:
                next_item = self._next_locked()
                if next_item is None:
                    break
                key, priority = next_item
                self._inflight[key] = priority
                self._attempts[key] = self._attempts.get(key, 0) + 1
                tasks.append((key, self._names[key]))
        for key, canonical in tasks:
            started = self._workers.start(
                self._fetch, args=(key, canonical),
                name="ampere-artist-profile")
            if not started:
                with self._lock:
                    self._inflight.pop(key, None)

    def _fetch(self, key: str, canonical: str) -> None:
        try:
            result = dict(self._service.get(canonical) or {})
        except Exception:
            result = {"found": False, "portrait": "",
                      "portraitRetryable": True}
        emits = []
        retry = False
        retry_priority = URGENT
        with self._lock:
            retry_priority = self._inflight.pop(key, URGENT)
            attempts = self._attempts.get(key, 0)
            retry = (not result.get("portrait")
                     and result.get("portraitRetryable") is True
                     and attempts < 2
                     and not self._workers.stop_requested.is_set())
            if retry:
                self._retry_waiting.add(key)
                self._retry_priorities[key] = retry_priority
            else:
                self._remember_locked(key, result)
                for alias in self._subscribers.get(key, {}):
                    emits.append((alias, dict(result)))
        for name, value in emits:
            self._on_result(name, value)
        if retry:
            self._start_retry(key, retry_priority)
        self._dispatch()

    def _start_retry(self, key: str, priority: int) -> None:
        def wait_and_requeue():
            if self._workers.stop_requested.wait(self._retry_delay):
                return
            with self._lock:
                self._retry_waiting.discard(key)
                promoted = self._retry_priorities.pop(key, priority)
                if key not in self._results:
                    self._enqueue_locked(key, promoted)
            self._dispatch()

        if not self._workers.start(
                wait_and_requeue, name="ampere-artist-profile-retry"):
            with self._lock:
                self._retry_waiting.discard(key)
                self._retry_priorities.pop(key, None)
