"""Recovery-safe persistence for DJ feedback and learned transition state."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..persistence import atomic_write_json, atomic_write_text


_MAPPING_FIELDS = (
    "pairs", "style_downs", "strikes", "cue_bans", "style_fires",
    "style_down_ts",
)


def _defaults() -> dict:
    return {
        "pairs": {},
        "style_downs": {},
        "strikes": {},
        "cue_bans": {},
        "style_fires": {},
        "seam_samples": [],
        "style_down_ts": {},
    }


class DjVotesRepository:
    """Load mutable DJ learning state without risking destructive fallback."""

    def __init__(self, path: str | Path, *, now=time.time,
                 write_json=atomic_write_json, write_text=atomic_write_text):
        self.path = Path(path)
        self._now = now
        self._write_json = write_json
        self._write_text = write_text
        self._corrupt_text: str | None = None
        self._read_error = ""

    def load(self) -> dict:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            value = {}
        except OSError as exc:
            self._read_error = str(exc)
            return _defaults()
        else:
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                self._corrupt_text = text
                return _defaults()
            if (not isinstance(value, dict)
                    or any(field in value and not isinstance(value[field], dict)
                           for field in _MAPPING_FIELDS)
                    or ("seam_samples" in value
                        and not isinstance(value["seam_samples"], list))):
                self._corrupt_text = text
                return _defaults()

        result = dict(value)
        defaults = _defaults()
        for key, default in defaults.items():
            result.setdefault(key, default)

        try:
            modified = self.path.stat().st_mtime
        except OSError:
            modified = self._now()
        for style in result["style_downs"]:
            result["style_down_ts"].setdefault(style, modified)
        return result

    def save(self, value: dict) -> bool:
        if self._read_error:
            return False
        try:
            if self._corrupt_text is not None:
                digest = hashlib.sha1(
                    self._corrupt_text.encode("utf-8"),
                    usedforsecurity=False).hexdigest()[:12]
                backup = self.path.with_name(
                    f"{self.path.name}.corrupt-{digest}.bak")
                if not backup.exists():
                    self._write_text(backup, self._corrupt_text)
            self._write_json(self.path, value)
        except OSError:
            return False
        self._corrupt_text = None
        self._read_error = ""
        return True
