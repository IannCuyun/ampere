"""Safe, focused ownership of Ampere-managed MPD configuration entries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .persistence import atomic_write_text


@dataclass(frozen=True)
class NormalizationResult:
    success: bool
    preamp: float
    missing_preamp: float
    rollback_complete: bool = True


class MpdConfigService:
    """Read and atomically update the MPD settings Ampere explicitly owns."""

    _PREAMP_KEYS = ("replaygain_preamp", "replaygain_missing_preamp")

    def __init__(self, path: str | Path, socket_path: str | Path):
        self.path = Path(path)
        self.socket_path = str(socket_path)

    def read_preamps(self) -> tuple[float, float]:
        try:
            text = self.path.read_text()
        except OSError:
            return 0.0, 0.0

        def value(key: str) -> float:
            match = re.search(
                rf'^\s*{re.escape(key)}\s+(?:"([^"]*)"|(\S+))',
                text, re.MULTILINE)
            if not match:
                return 0.0
            try:
                return float(match.group(1) or match.group(2))
            except (TypeError, ValueError):
                return 0.0

        return tuple(value(key) for key in self._PREAMP_KEYS)  # type: ignore[return-value]

    @staticmethod
    def _preamp(value) -> float:
        return max(-15.0, min(15.0, round(float(value))))

    def _render_preamps(self, text: str, preamp,
                         missing) -> tuple[str, tuple[float, float]]:
        values = self._preamp(preamp), self._preamp(missing)
        for key, value in zip(self._PREAMP_KEYS, values):
            line = f'{key} "{value:g}"'
            pattern = rf'^\s*{re.escape(key)}\s+(?:"[^"]*"|\S+).*$'
            if re.search(pattern, text, re.MULTILINE):
                text = re.sub(pattern, line, text, count=1, flags=re.MULTILINE)
                continue
            replaygain = r'^\s*replaygain\s+(?:"[^"]*"|\S+).*$'
            match = re.search(replaygain, text, re.MULTILINE)
            if match:
                text = text[:match.end()] + "\n" + line + text[match.end():]
            else:
                text = text.rstrip() + "\n" + line + "\n"
        return text, values

    def set_preamps(self, preamp, missing) -> tuple[float, float]:
        """Update both preamps together and return their normalized values."""
        text, values = self._render_preamps(
            self.path.read_text(), preamp, missing)
        atomic_write_text(self.path, text)
        return values

    def apply_preamps(self, preamp, missing, *, restart) -> NormalizationResult:
        """Write, activate, and roll back normalization as one operation."""
        original = self.path.read_text()
        updated, values = self._render_preamps(original, preamp, missing)
        atomic_write_text(self.path, updated)
        try:
            activated = bool(restart())
        except Exception:
            activated = False
        if activated:
            return NormalizationResult(True, *values)

        restored = False
        try:
            atomic_write_text(self.path, original)
            restored = bool(restart())
        except Exception:
            restored = False
        return NormalizationResult(
            False, *values, rollback_complete=restored)

    def ensure_socket_binding(self) -> bool:
        """Add the rendered-mix socket binding once, preserving a backup."""
        text = self.path.read_text()
        pattern = (r'^\s*bind_to_address\s+(?:"'
                   + re.escape(self.socket_path)
                   + r'"|'
                   + re.escape(self.socket_path)
                   + r')\s*(?:#.*)?$')
        if re.search(pattern, text, re.MULTILINE):
            return False
        backup = self.path.with_suffix(".conf.ampere-bak")
        if not backup.exists():
            atomic_write_text(backup, text)
        updated = text.rstrip() + f'\nbind_to_address     "{self.socket_path}"\n'
        atomic_write_text(self.path, updated)
        return True

    @staticmethod
    def socket_restart_safe(status) -> bool:
        """A config activation restart is safe only when MPD is stopped."""
        return isinstance(status, Mapping) and status.get("state") == "stop"
