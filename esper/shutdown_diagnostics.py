"""Opt-in, bounded attribution for interpreter-shutdown resource warnings."""

from __future__ import annotations

import os
import sys
import threading
import tracemalloc

ENV_NAME = "AMPERE_SHUTDOWN_DIAG"
_installed = False


def enabled() -> bool:
    return os.environ.get(ENV_NAME, "").strip() == "1"


def _safe(value) -> str:
    try:
        return repr(value)
    except Exception:
        return "<unrepresentable>"


def describe_object(obj) -> str:
    """Describe a wrapper chain without reading or mutating the resource."""
    parts = []
    seen = set()
    current = obj
    for label in ("object", "buffer", "raw", "socket"):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        closed = getattr(current, "closed", None)
        name = getattr(current, "name", None)
        parts.append(
            f"{label}={type(current).__module__}.{type(current).__name__}"
            f"(closed={closed!r},name={name!r})")
        if label == "object":
            current = (getattr(current, "buffer", None)
                       or getattr(current, "__self__", None))
        elif label == "buffer":
            current = getattr(current, "raw", None)
        else:
            current = getattr(current, "_sock", None)
    return " -> ".join(parts) or _safe(obj)


def format_snapshot(stage: str, clients, threads) -> str:
    client_states = []
    for client in clients:
        open_parts = [name for name in ("_rbfile", "_wfile", "_sock")
                      if getattr(client, name, None) is not None
                      and type(getattr(client, name)).__name__ != "_NotConnected"]
        client_states.append(
            f"{type(client).__name__}:{','.join(open_parts) or 'reset'}")
    thread_states = [f"{thread.name}:{'daemon' if thread.daemon else 'owned'}"
                     for thread in threads if thread.is_alive()]
    return (f"[shutdown-diag] {stage} clients="
            f"{client_states or ['none']} threads={thread_states or ['none']}")


def _emit(message: str) -> None:
    try:
        os.write(2, (message.rstrip() + "\n").encode("utf-8", "replace"))
    except Exception:
        pass


def snapshot(stage: str) -> None:
    if not enabled():
        return
    from .mpdgateway import tracked_mpd_clients
    _emit(format_snapshot(stage, tracked_mpd_clients(),
                          threading.enumerate()))


def install() -> bool:
    """Install one diagnostic hook only when explicitly enabled."""
    global _installed
    if not enabled() or _installed:
        return False
    _installed = True
    tracemalloc.start(12)
    original = sys.unraisablehook

    def hook(event):
        obj = event.object
        lines = [
            "[shutdown-diag] unraisable "
            f"error={type(event.exc_value).__name__}:{event.exc_value} "
            + describe_object(obj)
        ]
        trace = tracemalloc.get_object_traceback(obj)
        if trace is not None:
            lines.extend(f"[shutdown-diag] allocated {line.strip()}"
                         for line in trace.format())
        else:
            lines.append("[shutdown-diag] allocation unavailable")
        _emit("\n".join(lines))
        original(event)

    sys.unraisablehook = hook
    return True
