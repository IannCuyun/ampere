"""Background energy-analysis policy and transport-independent execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import time

from . import energy as energylib


@dataclass(frozen=True)
class EnergyScanPlan:
    tail_backfill: tuple[str, ...]
    spectral_backfill: tuple[str, ...]
    texture_backfill: tuple[str, ...]
    full_analysis: tuple[str, ...]


@dataclass(frozen=True)
class EnergyScanResult:
    total: int
    done: int
    tail_backfilled: int
    spectral_backfilled: int
    texture_backfilled: int
    fully_analyzed: int
    failed: int
    cancelled: bool = False
    inventory_failed: bool = False


class EnergyScanPolicy:
    """Decide incremental work and encode analyzer results as MPD stickers."""

    @staticmethod
    def plan(files: Sequence[str], *, energy_files: Iterable[str] = (),
             tail_files: Iterable[str] = (),
             spectral_files: Iterable[str] = (),
             texture_files: Iterable[str] = ()) -> EnergyScanPlan:
        have = set(energy_files)
        tails = set(tail_files)
        spectra = set(spectral_files)
        textures = set(texture_files)
        ordered = tuple(dict.fromkeys(file for file in files if file))
        return EnergyScanPlan(
            tuple(file for file in ordered if file in have and file not in tails),
            tuple(file for file in ordered if file in have and file not in spectra),
            tuple(file for file in ordered if file in have and file not in textures),
            tuple(file for file in ordered if file not in have),
        )

    @staticmethod
    def full_stickers(result: Mapping | None) -> tuple[tuple[str, str], ...]:
        if not result:
            return ()
        values = [("joi_energy", f"{float(result['energy']):.3f}")]
        if result.get("bpm"):
            values.append(("joi_bpm", f"{float(result['bpm']):.1f}"))
        if result.get("tail_db") is not None:
            values.append(("joi_taildb", f"{float(result['tail_db']):.1f}"))
        values.extend((
            ("joi_bass", f"{float(result['bass']):.3f}"),
            ("joi_bright", f"{float(result['bright']):.3f}"),
        ))
        if result.get("busy") is not None:
            values.append(("joi_busy", f"{float(result['busy']):.2f}"))
        if result.get("dyn") is not None:
            values.append(("joi_dyn", f"{float(result['dyn']):.2f}"))
        return tuple(values)

    @staticmethod
    def tail_stickers(tail_db) -> tuple[tuple[str, str], ...]:
        return (() if tail_db is None else
                (("joi_taildb", f"{float(tail_db):.1f}"),))

    @staticmethod
    def spectral_stickers(spectral) -> tuple[tuple[str, str], ...]:
        if spectral is None:
            return ()
        return (("joi_bass", f"{float(spectral[0]):.3f}"),
                ("joi_bright", f"{float(spectral[1]):.3f}"))

    @staticmethod
    def texture_stickers(texture) -> tuple[tuple[str, str], ...]:
        """Onset density and dynamic range were computed and discarded until
        2026-08-22; existing tracks backfill them without a re-analysis."""
        if texture is None:
            return ()
        return (("joi_busy", f"{float(texture[0]):.2f}"),
                ("joi_dyn", f"{float(texture[1]):.2f}"))

    @staticmethod
    def cooldown(elapsed: float, *, lightweight: bool = False) -> float:
        if lightweight:
            return min(1.0, max(0.05, elapsed))
        return min(3.0, max(0.10, elapsed * 1.5))


class EnergyScanner:
    """Run one incremental energy pass behind an injected MPD client lease."""

    INVENTORY_KEYS = ("joi_energy", "joi_taildb", "joi_bass", "joi_busy")

    def __init__(self, music_root: str | Path, *, client_scope,
                 analyze=energylib.analyze, tail_db=energylib.tail_db,
                 texture=energylib.texture,
                 spectral=energylib.spectral, clock=time.monotonic,
                 sleep=time.sleep):
        self.music_root = Path(music_root)
        self._client_scope = client_scope
        self._analyze = analyze
        self._tail_db = tail_db
        self._spectral = spectral
        self._texture = texture
        self._clock = clock
        self._sleep = sleep

    @staticmethod
    def _inventory(client, key: str) -> set[str]:
        return {str(row.get("file", ""))
                for row in client.sticker_find("song", "", key)
                if row.get("file")}

    @staticmethod
    def _write(client, file: str, values) -> None:
        for name, value in values:
            client.sticker_set("song", file, name, value)

    def _cooldown(self, started: float, *, lightweight: bool,
                  should_stop) -> None:
        if not should_stop():
            self._sleep(EnergyScanPolicy.cooldown(
                self._clock() - started, lightweight=lightweight))

    def scan(self, files: Sequence[str], *, should_stop=lambda: False
             ) -> EnergyScanResult:
        files = tuple(dict.fromkeys(str(file) for file in files if file))
        with self._client_scope() as client:
            try:
                have, tails, spectra, textures = (
                    self._inventory(client, key) for key in self.INVENTORY_KEYS)
            except Exception:
                # Unknown coverage must never be interpreted as no coverage:
                # that would schedule an expensive full-library re-analysis.
                return EnergyScanResult(
                    len(files), 0, 0, 0, 0, 0, 1,
                    cancelled=bool(files), inventory_failed=True)

            plan = EnergyScanPolicy.plan(
                files, energy_files=have, tail_files=tails,
                spectral_files=spectra, texture_files=textures)
            total = (len(plan.tail_backfill) + len(plan.spectral_backfill) +
                     len(plan.texture_backfill) + len(plan.full_analysis))
            done = tail_done = spectral_done = full_done = failed = 0
            texture_done = 0

            jobs = (
                (plan.tail_backfill, self._tail_db,
                 EnergyScanPolicy.tail_stickers, "tail", True),
                (plan.spectral_backfill, self._spectral,
                 EnergyScanPolicy.spectral_stickers, "spectral", False),
                (plan.texture_backfill, self._texture,
                 EnergyScanPolicy.texture_stickers, "texture", False),
                (plan.full_analysis, self._analyze,
                 EnergyScanPolicy.full_stickers, "full", False),
            )
            for pending, analyze, encode, kind, lightweight in jobs:
                for file in pending:
                    if should_stop():
                        return EnergyScanResult(
                            total, done, tail_done, spectral_done,
                            texture_done, full_done, failed, cancelled=True)
                    started = self._clock()
                    try:
                        values = encode(analyze(str(self.music_root / file)))
                        self._write(client, file, values)
                    except Exception:
                        failed += 1
                    else:
                        if kind == "tail":
                            tail_done += 1
                        elif kind == "spectral":
                            spectral_done += 1
                        elif kind == "texture":
                            texture_done += 1
                        else:
                            full_done += 1
                    done += 1
                    self._cooldown(
                        started, lightweight=lightweight,
                        should_stop=should_stop)

        return EnergyScanResult(
            total, done, tail_done, spectral_done, texture_done, full_done,
            failed, cancelled=False)
