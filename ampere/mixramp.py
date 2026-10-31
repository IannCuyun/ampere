"""MixRamp analysis for Ampere.

MPD can overlap songs *musically* (start the next track while the outro is
still above a loudness threshold) — but only if files carry MIXRAMP_START /
MIXRAMP_END tags. Nothing ships those for you; this module computes them:
an RMS envelope per track, then for each threshold the first/last time the
track crosses it, encoded as "dB time;" pairs the way MPD expects.

Tags are written as FLAC vorbis comments (mutagen). MPD's auto_update picks
the change up; syncthing sees a small header rewrite, not a re-encode.
"""

import array
import math
import subprocess

from mutagen.flac import FLAC

from .tag_writes import tag_write_lock

WIN = 0.1        # envelope window, seconds
RATE = 8000
THRESHOLDS = range(-90, -5, 6)   # -90 .. -6 dB


def envelope_db(abs_path):
    r = subprocess.run(
        ["nice", "-n", "15", "ffmpeg", "-v", "quiet", "-i", abs_path,
         "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        capture_output=True)
    raw = r.stdout[: len(r.stdout) // 2 * 2]
    data = array.array("h")
    data.frombytes(raw)
    if not data:
        return []
    per = max(1, int(RATE * WIN))
    env = []
    for i in range(0, len(data), per):
        seg = data[i:i + per]
        if not seg:
            break
        acc = 0
        for v in seg:
            acc += v * v
        rms = math.sqrt(acc / len(seg)) / 32768.0
        env.append(20.0 * math.log10(rms) if rms > 0 else -120.0)
    return env


def mixramp_tags(abs_path):
    """(MIXRAMP_START, MIXRAMP_END) strings, or (None, None) if undecodable.

    MPD (player/CrossFade.cxx) uses the parsed time DIRECTLY as an overlap
    duration: START times are seconds from the song's start until the level
    first exceeds each dB, END times are seconds from the song's END that the
    level stays below each dB. Both lists must be monotonically increasing
    in dB. (v1 of this analyzer wrote END as absolute positions — MPD then
    computed absurd overlaps and mixed the next song at ~0%.)"""
    env = envelope_db(abs_path)
    if not env:
        return None, None
    total = len(env) * WIN
    start_pairs, end_pairs = [], []
    for t in THRESHOLDS:
        si = next((i for i, v in enumerate(env) if v >= t), None)
        if si is None:
            continue
        ei = next(i for i in range(len(env) - 1, -1, -1) if env[i] >= t)
        start_pairs.append(f"{float(t):.2f} {si * WIN:.2f}")
        end_pairs.append(f"{float(t):.2f} {max(0.0, total - (ei + 1) * WIN):.2f}")
    if not start_pairs:
        return None, None
    return ";".join(start_pairs) + ";", ";".join(end_pairs) + ";"


def tag_file(abs_path, force=False):
    """Analyze one FLAC and write its mixramp tags.
    Returns 'tagged', 'skipped' (already has tags), or 'failed'."""
    try:
        f = FLAC(abs_path)
    except Exception:
        return "failed"
    if not force and "mixramp_start" in f and "mixramp_end" in f:
        return "skipped"
    start, end = mixramp_tags(abs_path)
    if start is None:
        return "failed"
    try:
        with tag_write_lock(abs_path):
            f = FLAC(abs_path)
            if not force and "mixramp_start" in f and "mixramp_end" in f:
                return "skipped"
            f["MIXRAMP_START"] = start
            f["MIXRAMP_END"] = end
            f.save()
    except Exception:
        return "failed"
    return "tagged"
