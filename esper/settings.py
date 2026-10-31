"""Validated ownership of Ampere's user configuration document."""

from __future__ import annotations

import json
import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .persistence import atomic_write_json, atomic_write_text
from .beacon import clean_sessions


DEFAULTS = {
    "automix_on": False,
    "mix_style": "blend",
    "crossfade_base": 4,
    # Autoplay is independent from MPD repeat/single and from transient
    # recommendation sessions. Legacy `radio_on` documents migrate below.
    "autoplay_on": False,
    "radio_mood": "match",
    "remote_on": True,
    "remote_token": "",
    "delete_remote_host": "",
    "delete_remote_root": "",
    "smart_mix_on": False,
    "mix_arc": False,
    "trim_silence": True,
    "dj_level": "classic",
    "dj_range": "progressive",
    "dj_mix_len": "auto",
    "dj_slam_only": False,
    "dj_seed_label": "",
    "dj_shape": "flat",
    "dj_minutes": 0,
    "dj_b2b": "",
    "dj_sting": False,
    "rg_mode": "track",
    "rg_on_mode": "track",
    "rating_mode": "hearts",
    # The shuffle mode is a standing preference, not a per-session flag: the
    # listener's last choice survives a restart and every new selection
    # (Iann, 2026-08-22).
    "context_shuffle_mode": "off",
    "device_volumes": {},
    # Search: bounded recent-queries history, newest first (Iann verdict
    # 2026-08-20 #6). Ten entries, unique, whitespace-trimmed.
    "search_history": [],
    # Successful stored-playlist launches only. The collection wall uses this
    # to choose its most-played lead without inferring history from overlapping
    # track membership.
    "playlist_play_counts": {},
    "artist_aliases": {},
    "sound_mixes": [],
    "beacon_sessions": [],
}

SEARCH_HISTORY_LIMIT = 10
PLAYLIST_PLAY_COUNT_LIMIT = 500


def clean_search_history(values) -> list[str]:
    """Newest-first, unique (case-insensitive), trimmed, bounded list."""
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= SEARCH_HISTORY_LIMIT:
            break
    return out


def clean_playlist_play_counts(values) -> dict[str, int]:
    """Exact playlist names to bounded, non-negative successful launches."""
    if not isinstance(values, Mapping):
        return {}
    cleaned: dict[str, int] = {}
    for raw_name, raw_count in values.items():
        name = str(raw_name or "").strip()
        if not name or name in cleaned:
            continue
        try:
            count = max(0, min(2_147_483_647, int(raw_count)))
        except (TypeError, ValueError, OverflowError):
            continue
        if count:
            cleaned[name] = count
        if len(cleaned) >= PLAYLIST_PLAY_COUNT_LIMIT:
            break
    return cleaned

_CHOICES = {
    "mix_style": {"blend", "fade"},
    "radio_mood": {"match", "any", "calm", "heavy"},
    "dj_level": {"clean", "classic", "wild", "curated", "all_in"},
    "dj_range": {"room", "progressive", "free"},
    "dj_mix_len": {"auto", "8", "16"},
    "dj_shape": {"flat", "rise", "arc"},
    "rg_mode": {"off", "track", "album", "auto"},
    "rg_on_mode": {"track", "album", "auto"},
    "rating_mode": {"hearts", "stars"},
    "context_shuffle_mode": {"off", "standard", "smart"},
}
_BOOL_KEYS = {key for key, value in DEFAULTS.items() if isinstance(value, bool)}
_TEXT_KEYS = {"remote_token", "delete_remote_host", "delete_remote_root",
              "dj_seed_label", "dj_b2b"}


@dataclass(frozen=True)
class SettingsSaveResult:
    success: bool
    values: dict
    error: str = ""


ALIAS_LIMIT = 500
# A mix is a built selection kept so it can be replayed or turned into a
# playlist. Keeping every one forever would grow the config without bound.
MIX_LIMIT = 40
MIX_FILE_LIMIT = 200


def clean_sound_mixes(values) -> list:
    """Validate the built-mix history.

    A mix is {id, character, label, created, files}. It is evidence of
    something Iann actually built, so it is never inferred and never
    reordered here — newest first is the caller's contract.
    """
    if not isinstance(values, (list, tuple)):
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in values:
        if len(cleaned) >= MIX_LIMIT:
            break
        if not isinstance(raw, Mapping):
            continue
        mix_id = str(raw.get("id") or "").strip()
        character = str(raw.get("character") or "").strip()
        raw_files = raw.get("files")
        if not isinstance(raw_files, (list, tuple)):
            continue
        files = [str(f) for f in raw_files if str(f).strip()]
        if not mix_id or not character or not files or mix_id in seen:
            continue
        seen.add(mix_id)
        try:
            created = float(raw.get("created") or 0.0)
        except (TypeError, ValueError):
            created = 0.0
        cleaned.append({
            "id": mix_id,
            "character": character,
            "label": str(raw.get("label") or "").strip() or character,
            "created": created,
            "files": files[:MIX_FILE_LIMIT],
        })
    return cleaned[:MIX_LIMIT]


def clean_artist_aliases(values) -> dict:
    """Validate the user's explicit artist-alias table.

    Shape is {alias name -> canonical display name}. Every entry is an exact,
    user-made decision (SPEC UNDESIGNED #17): nothing here is inferred, an
    alias may never point at itself, and a chain is collapsed one step rather
    than followed, so a cycle can never hang a library projection.
    """
    if not isinstance(values, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    for alias, canonical in values.items():
        name = " ".join(str(alias or "").split()).strip()
        target = " ".join(str(canonical or "").split()).strip()
        if not name or not target or name.casefold() == target.casefold():
            continue
        if len(cleaned) >= ALIAS_LIMIT:
            break
        cleaned[name] = target
    # An alias whose TARGET is itself an alias would otherwise need a walk at
    # every lookup. Resolve one hop here and store the settled answer.
    lowered = {name.casefold(): target for name, target in cleaned.items()}
    settled = {}
    for name, target in cleaned.items():
        final = lowered.get(target.casefold(), target)
        if final.casefold() != name.casefold():
            settled[name] = final
    return settled


def _validated(raw: Mapping) -> dict:
    """Return all known settings in the stable shape expected by Backend."""
    result = dict(DEFAULTS)
    for key in _BOOL_KEYS:
        if key in raw and isinstance(raw[key], bool):
            result[key] = raw[key]
    for key, choices in _CHOICES.items():
        if isinstance(raw.get(key), str) and raw[key] in choices:
            result[key] = raw[key]
    for key in _TEXT_KEYS:
        if key in raw and raw[key] is not None:
            result[key] = str(raw[key])
    # 2026-08-23: the old "radio" preference was presented as a hidden fourth
    # loop state. Preserve the listener's saved choice while moving ownership
    # to the independent Autoplay setting. Once `autoplay_on` exists it wins.
    if ("autoplay_on" not in raw
            and isinstance(raw.get("radio_on"), bool)):
        result["autoplay_on"] = raw["radio_on"]
    try:
        result["crossfade_base"] = max(0, min(15, int(raw.get("crossfade_base", 4))))
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        minutes = int(raw.get("dj_minutes", 0))
        if minutes in (0, 30, 45, 60, 90):
            result["dj_minutes"] = minutes
    except (TypeError, ValueError, OverflowError):
        pass

    volumes = raw.get("device_volumes")
    if isinstance(volumes, Mapping):
        clean_volumes = {}
        for device, volume in volumes.items():
            try:
                clean_volumes[str(device)] = max(0, min(100, int(volume)))
            except (TypeError, ValueError, OverflowError):
                continue
        result["device_volumes"] = clean_volumes

    result["search_history"] = clean_search_history(raw.get("search_history"))
    result["playlist_play_counts"] = clean_playlist_play_counts(
        raw.get("playlist_play_counts"))
    result["artist_aliases"] = clean_artist_aliases(raw.get("artist_aliases"))
    result["sound_mixes"] = clean_sound_mixes(raw.get("sound_mixes"))
    result["beacon_sessions"] = clean_sessions(raw.get("beacon_sessions"))
    return result


class SettingsRepository:
    """Load, validate, and atomically update Ampere's JSON preferences."""

    def __init__(self, path: str | Path, *, write_json=atomic_write_json,
                 write_text=atomic_write_text):
        self.path = Path(path)
        self._write_json = write_json
        self._write_text = write_text
        self._document: dict = {}
        self._corrupt_text: str | None = None
        self._read_error = ""
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            return self._load()

    def _load(self) -> dict:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            self._document = {}
            self._corrupt_text = None
            self._read_error = ""
            return _validated(self._document)
        except (OSError, UnicodeError) as exc:
            self._document = {}
            self._corrupt_text = None
            self._read_error = str(exc) or "settings document is unavailable"
            return _validated(self._document)
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            value = None
        if isinstance(value, Mapping):
            self._document = dict(value)
            self._corrupt_text = None
            self._read_error = ""
        else:
            self._document = {}
            self._corrupt_text = text
            self._read_error = ""
        return _validated(self._document)

    def save(self, values: Mapping) -> dict:
        result = self.try_save(values)
        if not result.success:
            raise OSError(result.error)
        return result.values

    def try_save(self, values: Mapping) -> SettingsSaveResult:
        clean = _validated(values)
        with self._lock:
            document = dict(self._document)
            document.update(clean)
            return self._commit(clean, document)

    def try_patch(self, values: Mapping) -> SettingsSaveResult:
        """Atomically update only supplied known settings keys.

        Worker-owned feature transactions use this instead of carrying a full
        settings snapshot across threads, which could otherwise overwrite a
        newer preference saved while the worker was waiting for the disk.
        """
        patch = {key: value for key, value in dict(values or {}).items()
                 if key in DEFAULTS}
        with self._lock:
            merged = dict(self._document)
            merged.update(patch)
            validated = _validated(merged)
            clean_patch = {key: validated[key] for key in patch}
            document = dict(self._document)
            document.update(clean_patch)
            return self._commit(clean_patch, document)

    def _commit(self, values: dict, document: dict) -> SettingsSaveResult:
        if self._read_error:
            return SettingsSaveResult(
                False, values,
                "existing settings could not be read; refusing to overwrite: "
                + self._read_error)
        # Preserve keys written by newer Ampere versions or local extensions.
        try:
            if self._corrupt_text is not None:
                digest = hashlib.sha1(
                    self._corrupt_text.encode("utf-8"),
                    usedforsecurity=False).hexdigest()[:12]
                backup = self.path.with_name(
                    f"{self.path.name}.corrupt-{digest}.bak")
                if not backup.exists():
                    self._write_text(backup, self._corrupt_text)
            self._write_json(self.path, document)
        except OSError as exc:
            return SettingsSaveResult(False, values, str(exc))
        self._document = document
        self._corrupt_text = None
        self._read_error = ""
        return SettingsSaveResult(True, values)
