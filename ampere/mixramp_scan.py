"""MixRamp library-enrichment policy independent of Qt and workers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import mixramp


@dataclass(frozen=True)
class MixRampScanResult:
    total: int
    done: int
    tagged: int
    skipped: int
    failed: int
    cancelled: bool = False


class MixRampScanner:
    """Tag a supplied FLAC snapshot with truthful bounded progress."""

    def __init__(self, music_root: str | Path, *, tag_file=mixramp.tag_file):
        self.music_root = Path(music_root)
        self._tag_file = tag_file

    def scan(self, files, *, force: bool = False,
             should_stop=lambda: False,
             progress=lambda _done, _total, _tagged: None
             ) -> MixRampScanResult:
        files = [str(file) for file in files]
        total = len(files)
        if total == 0:
            progress(0, 0, 0)
            return MixRampScanResult(0, 0, 0, 0, 0)

        done = tagged = skipped = failed = 0
        last_report = None
        for index, file in enumerate(files, 1):
            if should_stop():
                break
            try:
                outcome = self._tag_file(
                    str(self.music_root / file), force=bool(force))
            except Exception:
                outcome = "failed"
            if outcome == "tagged":
                tagged += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
            done = index
            report = (done, total, tagged)
            if index % 5 == 0 or index == total:
                progress(*report)
                last_report = report

        final_report = (done, total, tagged)
        if final_report != last_report:
            progress(*final_report)
        return MixRampScanResult(
            total=total, done=done, tagged=tagged, skipped=skipped,
            failed=failed, cancelled=done < total)
