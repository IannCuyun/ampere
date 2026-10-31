"""Per-song media enrichment outside the Qt application facade."""

from __future__ import annotations

import os
import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile

from .persistence import atomic_write_json


@dataclass(frozen=True)
class SongEnrichment:
    info: str = ""
    replay_gain_db: float | None = None
    lyrics: tuple[dict, ...] = ()
    lyrics_synced: bool = False
    tail_cut: float = 0.0
    mixramp_end: str = ""
    replay_gain_text: str = "0 dB"

    def as_mapping(self) -> dict:
        return {"info": self.info, "rg": self.replay_gain_db,
                "lyrics": list(self.lyrics), "synced": self.lyrics_synced,
                "tail": self.tail_cut, "mixramp_end": self.mixramp_end,
                "replay_gain_text": self.replay_gain_text}


class MediaEnrichmentService:
    """Read file-derived song details and reject superseded worker results."""

    def __init__(self, music_root: str | Path, *, read_lyrics, average_kbps,
                 tail_cut, compute_wave=None, wave_dir=None, art_colors=None,
                 mutagen_file=MutagenFile, write_json=atomic_write_json):
        self.music_root = Path(music_root)
        self._read_lyrics = read_lyrics
        self._average_kbps = average_kbps
        self._tail_cut = tail_cut
        self._mutagen_file = mutagen_file
        self._compute_wave = compute_wave
        self._wave_dir = Path(wave_dir) if wave_dir else None
        self._art_colors = art_colors
        self._write_json = write_json
        self._requests = {"metadata": (0, ""), "wave": (0, ""),
                          "colors": (0, "")}

    def begin(self, file: str, kind: str = "metadata") -> int:
        generation, _ = self._requests[kind]
        generation += 1
        self._requests[kind] = (generation, file)
        return generation

    def accepts(self, generation: int, file: str, current_file: str,
                kind: str = "metadata") -> bool:
        requested_generation, requested_file = self._requests[kind]
        return (generation == requested_generation and file == requested_file
                and file == current_file)

    def read_song(self, file: str, duration: float) -> SongEnrichment:
        info = Path(file).suffix.lstrip(".").upper()
        try:
            kbps = self._average_kbps(file, duration)
        except Exception:
            kbps = 0
        if kbps:
            info += (" · " if info else "") + f"{kbps} kbps"
        replay_gain = None
        replay_gain_text = "0 dB"
        mixramp_end = ""
        try:
            media = self._mutagen_file(self.music_root / file)
            rate = getattr(media.info, "sample_rate", 0)
            bits = getattr(media.info, "bits_per_sample", 0)
            if rate:
                rate_text = f"{rate / 1000:.1f}".rstrip("0").rstrip(".")
                info += (" · " if info else "") + f"{rate_text}k"
                if bits:
                    info += f"/{bits}"
            try:
                gain = (media.get("replaygain_track_gain")
                        or media.get("TXXX:replaygain_track_gain") or [""])[0]
                if hasattr(gain, "text"):
                    gain = (gain.text or [""])[0]
                replay_gain_text = str(gain or "0 dB")
                replay_gain = float(str(gain).split()[0])
            except (ValueError, IndexError, AttributeError, TypeError):
                pass
            try:
                mixramp_end = str(
                    (media.get("mixramp_end") or [""])[0] or "")
            except (IndexError, AttributeError, TypeError):
                pass
        except Exception:
            pass
        try:
            lyrics, synced = self._read_lyrics(os.fspath(self.music_root / file))
        except Exception:
            lyrics, synced = [], False
        try:
            tail = float(self._tail_cut(file, duration) or 0.0)
        except Exception:
            tail = 0.0
        try:
            duration = float(duration or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if (not math.isfinite(tail) or tail < 0.0
                or duration <= 0.0 or tail > duration):
            tail = 0.0
        return SongEnrichment(
            info, replay_gain, tuple(lyrics), bool(synced), tail,
            mixramp_end, replay_gain_text)

    def _waveform(self, file: str) -> tuple[bool, list[float]]:
        if not self._compute_wave or not self._wave_dir:
            return False, []
        key = hashlib.sha1(("v2:" + file).encode(),
                           usedforsecurity=False).hexdigest()
        cache = self._wave_dir / (key + ".json")
        try:
            if cache.exists():
                value = json.loads(cache.read_text())
                if isinstance(value, list):
                    return True, list(value)
            peaks = list(self._compute_wave(os.fspath(self.music_root / file)))
            self._write_json(cache, peaks)
            return True, peaks
        except Exception:
            return False, []

    def read_waveform(self, file: str) -> list[float]:
        return self._waveform(file)[1]

    def warm_waveform(self, file: str) -> bool:
        """Ensure a complete waveform cache entry exists for ``file``."""
        return self._waveform(file)[0]

    def read_cached_waveform(self, file: str) -> list[float]:
        """Read an existing waveform without decoding audio on the UI thread."""
        if not file or not self._wave_dir:
            return []
        key = hashlib.sha1(("v2:" + file).encode(),
                           usedforsecurity=False).hexdigest()
        try:
            value = json.loads((self._wave_dir / (key + ".json")).read_text())
        except (OSError, ValueError, TypeError):
            return []
        return list(value) if isinstance(value, list) else []

    def read_art_colors(self, file: str) -> list:
        if not self._art_colors:
            return []
        try:
            return list(self._art_colors(file))
        except Exception:
            return []


@dataclass(frozen=True)
class PrefetchResult:
    attempted: int
    failed: int
    completed: bool


class MediaPrefetcher:
    """Deduplicate and isolate cache warming launched by the heartbeat."""

    def __init__(self, *, warm_thumbnail, warm_waveform,
                 sleep=lambda _seconds: None):
        self._warm_thumbnail = warm_thumbnail
        self._warm_waveform = warm_waveform
        self._sleep = sleep
        self._lock = threading.Lock()
        self._busy = False
        self._completed_key = ""
        self.last_result = PrefetchResult(0, 0, False)

    @staticmethod
    def _snapshot(files) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(file) for file in files if file))[:15]

    def request(self, files, *, launch, should_stop=lambda: False) -> bool:
        snapshot = self._snapshot(files)
        if not snapshot:
            return False
        key = "|".join(snapshot)
        with self._lock:
            if self._busy or key == self._completed_key:
                return False
            self._busy = True

        def work():
            attempted = failed = 0
            try:
                for file in snapshot:
                    if should_stop():
                        break
                    attempted += 1
                    try:
                        self._warm_thumbnail(file)
                    except Exception:
                        failed += 1
                for file in snapshot[:3]:
                    if should_stop():
                        break
                    attempted += 1
                    try:
                        if not self._warm_waveform(file):
                            failed += 1
                    except Exception:
                        failed += 1
                    if not should_stop():
                        self._sleep(0.5)
            finally:
                completed = not should_stop() and failed == 0
                with self._lock:
                    if completed:
                        self._completed_key = key
                    self.last_result = PrefetchResult(
                        attempted, failed, completed)
                    self._busy = False

        if launch(work):
            return True
        with self._lock:
            self._busy = False
        return False
