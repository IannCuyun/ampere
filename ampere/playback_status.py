"""Pure normalization for MPD's loosely typed playback status mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackStatus:
    state: str
    elapsed: float
    duration: float
    volume: int
    random: bool
    repeat: bool
    single: bool
    queue_pos: int
    song_id: int
    crossfade: int
    bitrate_kbps: int
    mixramp_db: float
    mixramp_delay_on: bool

    def queue_position_changed(self, previous: int) -> bool:
        return self.queue_pos != int(previous)

    @classmethod
    def from_mpd(cls, status: Mapping, *, current_volume: int = 100,
                 current_mixramp_db: float = 0.0) -> "PlaybackStatus":
        delay = status.get("mixrampdelay")
        return cls(
            state=str(status.get("state") or "stop"),
            elapsed=_float(status.get("elapsed")),
            duration=_float(status.get("duration")),
            volume=_int(status.get("volume"), current_volume),
            random=status.get("random") == "1",
            repeat=status.get("repeat") == "1",
            single=status.get("single") in ("1", "oneshot"),
            queue_pos=_int(status.get("song"), -1),
            song_id=_int(status.get("songid"), -1),
            crossfade=_int(status.get("xfade"), 0),
            bitrate_kbps=_int(_float(status.get("bitrate")), 0),
            mixramp_db=_float(status.get("mixrampdb"), current_mixramp_db),
            mixramp_delay_on=delay is not None and delay != "nan",
        )


@dataclass(frozen=True)
class PlaybackHeartbeat:
    """One verified, internally consistent MPD status/current-song pair."""

    status: PlaybackStatus
    song: dict

    @classmethod
    def from_mpd(cls, status, song, *, normalize_song,
                 current_volume: int = 100,
                 current_mixramp_db: float = 0.0) -> "PlaybackHeartbeat | None":
        if not isinstance(status, Mapping) or not isinstance(song, Mapping):
            return None
        try:
            snapshot = PlaybackStatus.from_mpd(
                status, current_volume=current_volume,
                current_mixramp_db=current_mixramp_db)
            normalized_song = normalize_song(song) if song else {}
        except Exception:
            return None
        return cls(snapshot, normalized_song)


@dataclass(frozen=True)
class MixRampReconciliation:
    """Local auto-mix state and the one daemon correction it may require."""

    mixramp_on: bool
    automix_on: bool
    disable_daemon_delay: bool = False


def reconcile_mixramp(*, delay_on: bool, mix_style: str, dj_active: bool,
                      automix_on: bool) -> MixRampReconciliation:
    """Resolve ownership of MPD's global ``mixrampdelay`` switch.

    Fade mode and an active DJ transition retain local ownership. Otherwise
    the daemon switch is authoritative, including changes made outside Ampere.
    """
    if mix_style == "fade":
        return MixRampReconciliation(
            mixramp_on=bool(automix_on), automix_on=bool(automix_on),
            disable_daemon_delay=bool(delay_on))
    if dj_active:
        return MixRampReconciliation(
            mixramp_on=bool(automix_on), automix_on=bool(automix_on))
    return MixRampReconciliation(
        mixramp_on=bool(delay_on), automix_on=bool(delay_on))


def _float(value, default=0.0) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _int(value, default=0) -> int:
    try:
        return int(value) if value not in (None, "") else int(default)
    except (TypeError, ValueError, OverflowError):
        return int(default)
