"""Ownership boundary for backend background work and its live resources."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


class WorkerStopping(RuntimeError):
    """Raised when work tries to acquire a resource during shutdown."""


@dataclass(frozen=True)
class WorkerShutdownReport:
    """Immutable truth returned after the registry's bounded drain."""

    survivors: tuple[str, ...] = ()
    pending_durable_jobs: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.survivors and not self.pending_durable_jobs

    @property
    def failure_message(self) -> str:
        details = []
        if self.survivors:
            details.append("surviving workers: " + ", ".join(self.survivors))
        if self.pending_durable_jobs:
            details.append(
                "pending durable jobs: "
                + ", ".join(self.pending_durable_jobs))
        return "; ".join(details)

    def with_pending_durable_jobs(self, *jobs: str):
        pending = set(self.pending_durable_jobs)
        pending.update(str(job) for job in jobs if str(job))
        normalized = tuple(sorted(pending))
        if normalized == self.pending_durable_jobs:
            return self
        return WorkerShutdownReport(
            survivors=self.survivors,
            pending_durable_jobs=normalized,
        )


class WorkerRegistry:
    """Track daemon work, cooperative cancellation, and unblock callbacks."""

    def __init__(self):
        self.stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._threads: set[threading.Thread] = set()
        self._durable_jobs: dict[threading.Thread, str] = {}
        self._resources: dict[int, tuple[object, object]] = {}

    def start(self, target, *, args=(), name=None, durable=False) -> bool:
        """Start owned work unless teardown has begun."""
        with self._lock:
            if self.stop_requested.is_set():
                return False

            def run():
                try:
                    target(*args)
                finally:
                    with self._lock:
                        current = threading.current_thread()
                        self._threads.discard(current)
                        self._durable_jobs.pop(current, None)

            thread = threading.Thread(target=run, name=name, daemon=True)
            self._threads.add(thread)
            if durable:
                self._durable_jobs[thread] = str(
                    durable if isinstance(durable, str) else thread.name)
            thread.start()
        return True

    def acquire(self, resource, close) -> None:
        """Make a live resource interruptible by ``shutdown``."""
        with self._lock:
            if not self.stop_requested.is_set():
                self._resources[id(resource)] = (resource, close)
                return
        try:
            close(resource)
        finally:
            raise WorkerStopping("background services are stopping")

    def release(self, resource) -> None:
        with self._lock:
            self._resources.pop(id(resource), None)

    def shutdown(self, timeout=3.0) -> WorkerShutdownReport:
        """Reject new work, unblock resources, and join within one budget."""
        self.stop_requested.set()
        with self._lock:
            resources = list(self._resources.values())
            threads = list(self._threads)
        for resource, close in resources:
            try:
                close(resource)
            except Exception:
                pass
        deadline = time.monotonic() + max(0.0, timeout)
        current = threading.current_thread()
        for thread in threads:
            if thread is current:
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            survivors = tuple(sorted(
                thread.name for thread in self._threads
                if thread.is_alive()))
            survivor_threads = {
                thread for thread in self._threads if thread.is_alive()
            }
            pending_durable = tuple(sorted({
                label for thread, label in self._durable_jobs.items()
                if thread in survivor_threads
            }))
        return WorkerShutdownReport(survivors, pending_durable)
