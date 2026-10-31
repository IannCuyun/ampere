"""ReplayGain enrichment policy independent of Qt and worker ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from mpd.base import CommandError, ConnectionError as MPDConnectionError

from . import rgain


@dataclass(frozen=True)
class ReplayGainScanResult:
    total: int
    done: int
    tagged: int
    cancelled: bool = False


@dataclass(frozen=True)
class ReplayGainModeResult:
    committed: bool
    mode: str
    rollback_complete: bool = True


class ReplayGainModeController:
    """Apply and verify MPD's runtime-only ReplayGain mode."""

    MODES = frozenset(("off", "track", "album", "auto"))

    def __init__(self, client, *, ensure_connected, mark_disconnected,
                 error=lambda _message: None):
        self.client = client
        self._ensure_connected = ensure_connected
        self._mark_disconnected = mark_disconnected
        self._error = error

    def _read(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                value = self.client.replay_gain_status()
                if isinstance(value, dict):
                    value = value.get("replay_gain_mode")
                value = str(value or "")
                return value if value in self.MODES else None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
            except CommandError:
                return None
        return None

    def _write(self, mode: str) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            self.client.replay_gain_mode(mode)
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def apply(self, mode: str) -> ReplayGainModeResult:
        mode = str(mode)
        if mode not in self.MODES:
            return ReplayGainModeResult(False, "off")
        baseline = self._read()
        if baseline is None:
            self._error("ReplayGain state could not be read — try again")
            return ReplayGainModeResult(False, mode)
        if baseline == mode:
            return ReplayGainModeResult(True, mode)
        self._write(mode)
        if self._read() == mode:
            return ReplayGainModeResult(True, mode)
        self._write(baseline)
        rollback_complete = self._read() == baseline
        detail = ("; playback leveling may need another try"
                  if not rollback_complete else "")
        self._error("ReplayGain mode could not be changed" + detail)
        return ReplayGainModeResult(
            False, baseline, rollback_complete=rollback_complete)


class ReplayGainScanner:
    """Find and tag missing loudness metadata with truthful progress."""

    def __init__(self, music_root: str | Path, *, has_rg=rgain.has_rg,
                 tag_file=rgain.tag_file, clock=time.monotonic,
                 sleep=time.sleep):
        self.music_root = Path(music_root)
        self._has_rg = has_rg
        self._tag_file = tag_file
        self._clock = clock
        self._sleep = sleep

    @staticmethod
    def cooldown(elapsed: float) -> float:
        return min(2.0, max(0.05, float(elapsed)))

    def scan(self, files, *, should_stop=lambda: False,
             progress=lambda _done, _total, _tagged: None
             ) -> ReplayGainScanResult:
        pending = [str(file) for file in files
                   if not self._has_rg(str(self.music_root / str(file)))]
        total = len(pending)
        if total == 0:
            progress(0, 0, 0)
            return ReplayGainScanResult(0, 0, 0)

        done = tagged = 0
        last_report = None
        for index, file in enumerate(pending, 1):
            if should_stop():
                break
            started = self._clock()
            if self._tag_file(str(self.music_root / file)) == "tagged":
                tagged += 1
            done = index
            report = (done, total, tagged)
            if index % 3 == 0 or index == total:
                progress(*report)
                last_report = report
            if not should_stop():
                self._sleep(self.cooldown(self._clock() - started))

        final_report = (done, total, tagged)
        if final_report != last_report:
            progress(*final_report)
        return ReplayGainScanResult(
            total=total, done=done, tagged=tagged, cancelled=done < total)
