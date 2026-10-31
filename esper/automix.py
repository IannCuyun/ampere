"""Pure fade-duration policy for Ampere's automatic transitions."""

from __future__ import annotations

from dataclasses import dataclass

from mpd.base import CommandError, ConnectionError as MPDConnectionError


@dataclass(frozen=True)
class TransitionOptionsResult:
    committed: bool
    rollback_complete: bool = True


@dataclass(frozen=True)
class TransitionThresholdResult:
    committed: bool
    value: float | None
    rollback_complete: bool = True


class AutoMixDaemonController:
    """Reconcile MPD's coupled MixRamp and crossfade transition options."""

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
                status = self.client.status() or {}
                raw_delay = status.get("mixrampdelay")
                delay = None
                if raw_delay not in (None, "", "nan"):
                    delay = float(raw_delay)
                return delay, int(status.get("xfade", 0))
            except (TypeError, ValueError, CommandError):
                return None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
        return None

    def _read_threshold(self):
        for _attempt in (0, 1):
            if not self._ensure_connected(silent=True):
                continue
            try:
                value = float((self.client.status() or {})["mixrampdb"])
                return value if -100.0 <= value <= 0.0 else None
            except (KeyError, TypeError, ValueError, CommandError):
                return None
            except (MPDConnectionError, OSError):
                self._mark_disconnected()
        return None

    def _write_threshold(self, value: float) -> None:
        if not self._ensure_connected(silent=True):
            return
        try:
            self.client.mixrampdb(str(float(value)))
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def set_threshold(self, value: float) -> TransitionThresholdResult:
        """Apply and verify MPD's MixRamp level threshold with rollback."""
        desired = max(-40.0, min(-6.0, float(value)))
        baseline = self._read_threshold()
        if baseline is None:
            self._error("MixRamp threshold could not be read — try again")
            return TransitionThresholdResult(False, None)
        if abs(baseline - desired) < 0.01:
            return TransitionThresholdResult(True, baseline)
        self._write_threshold(desired)
        current = self._read_threshold()
        if current is not None and abs(current - desired) < 0.01:
            return TransitionThresholdResult(True, current)
        self._write_threshold(baseline)
        restored = self._read_threshold()
        rollback_complete = (restored is not None
                             and abs(restored - baseline) < 0.01)
        detail = ("; transition threshold may need another try"
                  if not rollback_complete else "")
        self._error("MixRamp threshold could not be changed" + detail)
        return TransitionThresholdResult(
            False, restored if restored is not None else baseline,
            rollback_complete)

    @staticmethod
    def _matches(actual, desired) -> bool:
        if actual is None:
            return False
        actual_delay, actual_crossfade = actual
        desired_delay, desired_crossfade = desired
        delay_matches = (actual_delay is None and desired_delay is None) or (
            actual_delay is not None and desired_delay is not None
            and abs(actual_delay - desired_delay) < 0.01)
        return delay_matches and actual_crossfade == desired_crossfade

    def _write(self, state) -> None:
        if not self._ensure_connected(silent=True):
            return
        delay, crossfade = state
        try:
            self.client.command_list_ok_begin()
            self.client.mixrampdelay("nan" if delay is None else str(delay))
            self.client.crossfade(int(crossfade))
            self.client.command_list_end()
        except (MPDConnectionError, OSError):
            self._mark_disconnected()
        except CommandError:
            pass

    def configure(self, *, mixramp_delay,
                  crossfade: int) -> TransitionOptionsResult:
        desired = (None if mixramp_delay is None else float(mixramp_delay),
                   max(0, int(crossfade)))
        baseline = self._read()
        if baseline is None:
            self._error("Auto-mix state could not be read — try again")
            return TransitionOptionsResult(False)
        if self._matches(baseline, desired):
            return TransitionOptionsResult(True)
        self._write(desired)
        if self._matches(self._read(), desired):
            return TransitionOptionsResult(True)
        self._write(baseline)
        rollback_complete = self._matches(self._read(), baseline)
        detail = ("; playback transitions may need another try"
                  if not rollback_complete else "")
        self._error("Auto-mix could not be changed" + detail)
        return TransitionOptionsResult(False, rollback_complete)


def energy_fade_factor(energies) -> float:
    values = []
    for value in energies:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            pass
    if not values:
        return 1.0
    mean = sum(values) / len(values)
    return max(.55, min(1.45, 1.55 - 1.1 * mean))


def fade_duration(*, base: float, factor: float, mixramp_end="",
                  mixramp_db: float = 0.0, replaygain="0 dB",
                  bpm=0) -> int:
    fallback = _clamp(round(base * factor))
    pairs = _pairs(mixramp_end)
    if not pairs:
        return fallback
    effective = float(mixramp_db)
    try:
        effective -= float(str(replaygain).split()[0])
    except (TypeError, ValueError, IndexError):
        pass
    pairs.sort()
    if effective <= pairs[0][0]:
        seconds = pairs[0][1]
    elif effective >= pairs[-1][0]:
        seconds = pairs[-1][1]
    else:
        seconds = pairs[-1][1]
        for (low_db, low_t), (high_db, high_t) in zip(pairs, pairs[1:]):
            if low_db <= effective <= high_db:
                fraction = ((effective - low_db) / (high_db - low_db)
                            if high_db > low_db else 0.0)
                seconds = low_t + fraction * (high_t - low_t)
                break
    seconds *= factor
    try:
        tempo = float(bpm)
        if tempo > 0:
            bar = 4 * 60.0 / tempo
            seconds = max(1, round(seconds / bar)) * bar
    except (TypeError, ValueError):
        pass
    return _clamp(round(seconds))


def _pairs(value) -> list[tuple[float, float]]:
    pairs = []
    for part in str(value or "").split(";"):
        try:
            db_string, time_string = part.split()
            pairs.append((float(db_string), float(time_string)))
        except (TypeError, ValueError):
            continue
    return pairs


def _clamp(seconds) -> int:
    return max(2, min(10, int(seconds)))
