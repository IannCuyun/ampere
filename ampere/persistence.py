"""Crash-safe writes for Ampere's small state and configuration files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _sync_directory(path: Path) -> None:
    """Persist directory-entry changes before a write reports success."""
    descriptor = os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_parent(path: Path) -> None:
    """Create and durably link every missing parent directory."""
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    # mkdir -p may create several directory entries. Persist each edge from
    # the pre-existing ancestor down toward the target directory.
    for directory in reversed(missing):
        _sync_directory(directory.parent)


def atomic_write_text(path: str | Path, text: str, *, encoding="utf-8") -> None:
    """Durably replace ``path`` after a complete same-directory write."""
    target = Path(path)
    _ensure_parent(target.parent)
    # These files contain private listening state and, for config.json, the
    # phone-remote bearer token. Preserve the owner's existing access while
    # refusing to carry legacy group/other bits into the replacement.
    mode = target.stat().st_mode & 0o700 if target.exists() else 0o600
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding=encoding, dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False) as fh:
            temp_name = fh.name
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, target)
        # fsync(file) makes the bytes durable; fsync(parent) makes the rename
        # durable. Without the latter, a power loss can resurrect the previous
        # name or lose a newly created file after callers were told it saved.
        _sync_directory(target.parent)
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def atomic_write_bytes(path: str | Path, value: bytes) -> None:
    """Durably replace ``path`` with opaque bytes in its own directory."""
    target = Path(path)
    _ensure_parent(target.parent)
    mode = target.stat().st_mode & 0o700 if target.exists() else 0o600
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=f".{target.name}.",
                suffix=".tmp", delete=False) as fh:
            temp_name = fh.name
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, target)
        _sync_directory(target.parent)
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(path: str | Path, value, *, indent=None) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=indent))
