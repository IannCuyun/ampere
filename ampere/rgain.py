"""ReplayGain 2.0 analysis for Ampere's loudness leveling.

One job: give every file a REPLAYGAIN_TRACK_GAIN/PEAK tag so MPD's
replay-gain mode can play the whole library at the same perceived volume
(Plexamp-style). Loudness measured with ffmpeg's ebur128 (EBU R128,
reference -18 LUFS per the ReplayGain 2.0 spec).
"""

import os
import re
import subprocess

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX

from .tag_writes import tag_write_lock

_I_RE = re.compile(r"I:\s*(-?[\d.]+)\s*LUFS")
_TP_RE = re.compile(r"Peak:\s*(-?[\d.]+)\s*dBFS")


def has_rg(path: str) -> bool:
    try:
        mf = MutagenFile(path)
        keys = [str(k).lower() for k in (mf.tags or {}).keys()]
        return any("replaygain_track_gain" in k for k in keys)
    except Exception:
        return True   # unreadable → don't try to tag it either


def analyze(path: str):
    """(track_gain_db, track_peak_linear) or None."""
    try:
        r = subprocess.run(
            ["nice", "-n", "15", "ffmpeg", "-v", "info", "-nostats", "-i", path,
             "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    i_all = _I_RE.findall(r.stderr)
    tp_all = _TP_RE.findall(r.stderr)
    if not i_all:
        return None
    loudness = float(i_all[-1])          # the summary block comes last
    peak_db = float(tp_all[-1]) if tp_all else 0.0
    return -18.0 - loudness, 10 ** (peak_db / 20.0)


def tag_file(path: str, force: bool = False) -> str:
    """Returns 'tagged' | 'skipped' | 'failed'."""
    if not force and has_rg(path):
        return "skipped"
    res = analyze(path)
    if res is None:
        return "failed"
    gain, peak = res
    gain_s, peak_s = f"{gain:.2f} dB", f"{peak:.6f}"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".flac":
            with tag_write_lock(path):
                if not force and has_rg(path):
                    return "skipped"
                f = FLAC(path)
                f["REPLAYGAIN_TRACK_GAIN"] = gain_s
                f["REPLAYGAIN_TRACK_PEAK"] = peak_s
                f.save()
        elif ext == ".mp3":
            tags = ID3(path)
            tags.setall("TXXX:REPLAYGAIN_TRACK_GAIN",
                        [TXXX(encoding=1, desc="REPLAYGAIN_TRACK_GAIN", text=[gain_s])])
            tags.setall("TXXX:REPLAYGAIN_TRACK_PEAK",
                        [TXXX(encoding=1, desc="REPLAYGAIN_TRACK_PEAK", text=[peak_s])])
            tags.save()
        else:
            mf = MutagenFile(path)
            if mf is None or mf.tags is None:
                return "failed"
            mf["REPLAYGAIN_TRACK_GAIN"] = gain_s
            mf["REPLAYGAIN_TRACK_PEAK"] = peak_s
            mf.save()
        return "tagged"
    except Exception:
        return "failed"
