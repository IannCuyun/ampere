"""Compatibility with existing installations; new installations use Ampere.

Old storage and PipeWire identities are durable external contracts. Keep one
owner for existing data and audio routing instead of copying or resetting them.
Historical MPD ``joi_*`` sticker keys likewise remain an on-disk schema, not a
second product name.
"""
from pathlib import Path
import os


def state_directory(kind: str, home: Path | None = None) -> Path:
    root = (home or Path.home()) / f'.{kind}'
    legacy = root / 'esper'
    # Existing data wins even if an empty new-name directory was created.
    return legacy if legacy.is_dir() else root / 'ampere'


def config_path(relative: str = '') -> str:
    return str(state_directory('config') / relative)


def cache_path(relative: str = '') -> str:
    return str(state_directory('cache') / relative)


def environment(suffix: str, default=None):
    return os.environ.get('AMPERE_' + suffix,
                          os.environ.get('ESPER_' + suffix, default))


def audio_identity(home: Path | None = None) -> tuple[str, Path]:
    root = (home or Path.home()) / '.config/pipewire/filter-chain.conf.d'
    old = root / 'esper-eq.conf'
    if old.exists():
        return 'esper_eq', old
    return 'ampere_eq', root / 'ampere-eq.conf'
