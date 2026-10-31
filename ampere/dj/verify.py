"""Live DJ transition quality: drop-accurate entry refinement + a post-render
acceptance gate.  Pure numpy + ffmpeg decode ONLY — no scipy/librosa/torch —
so it runs in-process on the app's Python-3.14 / numpy-2.5 stack and stays
cohesive with djcues/djbridge (same ffmpeg→numpy analysis pattern).

Two jobs:
  * refine_entry() — given a candidate entry cue, decode B around it and move
    the cut to the HARDEST drop (sustained bass+broadband energy jump) that
    sits on B's beat grid.  This is what makes a slam land on the real drop,
    anywhere in the song, not just "on beat".
  * verify_bridge() — decode the RENDERED bridge and measure whether the drop
    actually landed on the cut beat, hits hard, holds level across the seam,
    and doesn't clip.  The planner re-cuts until this passes (or falls back).
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import subprocess
import numpy as np

SR = 22050
HOP = 256
WIN = 1024
BASS_HZ = 150.0          # drops live in the sub/bass; weight it heavily
# Shared by the verifier and planner: a B with no jump this big has no drop to
# slam onto, so the planner soft-crossfades instead.
SLAM_HARD_MIN = 1.5      # dB energy jump a slam must clear to count as a HIT


@dataclass(frozen=True)
class BridgeFrontierResult:
    conclusive: bool
    valid: bool = False
    a_pos: int = -1
    b_pos: int = -1
    current_pos: int = -1
    reason: str = ""


@dataclass(frozen=True)
class CutSnapshotResult:
    conclusive: bool
    valid: bool = False
    elapsed: float = 0.0


@dataclass(frozen=True)
class PlayheadResult:
    conclusive: bool
    song_id: int = -1


def validate_playhead(status) -> PlayheadResult:
    """Resolve the playing queue identity before destructive DJ cleanup."""
    if not isinstance(status, Mapping):
        return PlayheadResult(False)
    state = str(status.get("state", ""))
    if state == "stop":
        return PlayheadResult(True)
    if state not in ("play", "pause"):
        return PlayheadResult(False)
    try:
        song_id = int(status["songid"])
    except (KeyError, TypeError, ValueError):
        return PlayheadResult(False)
    if song_id < 0:
        return PlayheadResult(False)
    return PlayheadResult(True, song_id)


def validate_cut_snapshot(status, expected_song_id: int) -> CutSnapshotResult:
    """Validate fresh MPD truth for a delayed manual DJ cut."""
    if not isinstance(status, Mapping):
        return CutSnapshotResult(False)
    try:
        song_id = int(status["songid"])
        elapsed = float(status["elapsed"])
    except (KeyError, TypeError, ValueError):
        return CutSnapshotResult(False)
    if not math.isfinite(elapsed) or elapsed < 0:
        return CutSnapshotResult(False)
    valid = str(status.get("state", "")) == "play" \
        and song_id == int(expected_song_id)
    return CutSnapshotResult(True, valid, elapsed)


def validate_bridge_frontier(queue, status, a_id: int,
                             b_id: int) -> BridgeFrontierResult:
    """Prove a rendered bridge still belongs ahead of the playhead."""
    if (not isinstance(queue, Sequence) or isinstance(queue, (str, bytes))
            or not isinstance(status, Mapping)):
        return BridgeFrontierResult(False, reason="snapshot unavailable")
    state = str(status.get("state", ""))
    if state not in ("play", "pause", "stop"):
        return BridgeFrontierResult(False, reason="status malformed")
    try:
        current = int(status.get("song", -1) or -1)
    except (TypeError, ValueError):
        return BridgeFrontierResult(False, reason="status position malformed")
    if state in ("play", "pause") and current < 0:
        return BridgeFrontierResult(False, reason="status position missing")

    positions = {}
    for item in queue:
        if not isinstance(item, Mapping):
            return BridgeFrontierResult(False, reason="queue malformed")
        try:
            song_id = int(item["id"])
            position = int(item["pos"])
        except (KeyError, TypeError, ValueError):
            return BridgeFrontierResult(False, reason="queue identity malformed")
        positions[song_id] = position
    a_pos = positions.get(int(a_id), -1)
    b_pos = positions.get(int(b_id), -1)
    valid = a_pos >= 0 and b_pos == a_pos + 1 and a_pos > current
    reason = "ready" if valid else "too late or reordered"
    return BridgeFrontierResult(
        True, valid, a_pos, b_pos, current, reason)


def slam_verdict_ok(verdict) -> bool:
    """Return whether a rendered slam is safe to put in the live queue.

    Keep this gate deliberately small and fail-closed.  Rendering and analysis
    happen on a worker thread, where malformed or incomplete results used to be
    treated as success by the planner.  A transition is only trustworthy when
    the verifier explicitly reports success and all of its safety fields agree.
    """
    if not isinstance(verdict, dict) or verdict.get("ok") is not True:
        return False
    try:
        offset_ms = abs(float(verdict["offset_ms"]))
        hardness = float(verdict["hardness"])
    except (KeyError, TypeError, ValueError):
        return False
    return (math.isfinite(offset_ms)
            and math.isfinite(hardness)
            and offset_ms <= 35.0
            and hardness >= SLAM_HARD_MIN
            and verdict.get("clip") is False
            and not verdict.get("why"))


_FREQS = np.fft.rfftfreq(WIN, 1.0 / SR)
_BASS = _FREQS < BASS_HZ
_HANN = np.hanning(WIN).astype(np.float32)


def _decode(path: str, t0: float, dur: float, sr: int = SR) -> np.ndarray:
    """Mono f32 PCM of [t0, t0+dur) via ffmpeg (nice'd, like every other
    analyzer here so a background gate can't starve MPD's decode)."""
    if dur <= 0:
        return np.zeros(0, dtype=np.float32)
    r = subprocess.run(
        ["nice", "-n", "15", "ffmpeg", "-v", "error",
         "-ss", f"{max(0.0, t0):.4f}", "-t", f"{dur:.4f}", "-i", path,
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


def _frames(x: np.ndarray, hop: int = HOP, win: int = WIN) -> np.ndarray:
    if len(x) < win:
        return np.zeros((0, win), dtype=np.float32)
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def _features(x: np.ndarray, hop: int = HOP, win: int = WIN):
    """(t, rms, bass, flux): per-frame time, broadband RMS, bass-band energy,
    and a positive-difference onset flux (log-energy, bass-weighted)."""
    fr = _frames(x, hop, win)
    if fr.shape[0] == 0:
        z = np.zeros(0, dtype=np.float32)
        return z, z, z, z
    rms = np.sqrt(np.mean(fr * fr, axis=1) + 1e-12)
    S = np.abs(np.fft.rfft(fr * _HANN, axis=1))
    bass = S[:, _BASS].sum(axis=1) + 1e-9
    energy = np.log(rms + 1e-9)
    lb = np.log(bass)
    flux = np.maximum(0.0, np.diff(energy)) + 1.5 * np.maximum(0.0, np.diff(lb))
    flux = np.concatenate([[0.0], flux]).astype(np.float32)
    t = np.arange(fr.shape[0], dtype=np.float32) * hop / SR
    return t, rms.astype(np.float32), bass.astype(np.float32), flux


def _drop_score(t, rms, bass, flux):
    """Per-frame 'is this a DROP' score: an onset whose bass+broadband energy
    JUMPS and then STAYS elevated (a drop, not a transient tick).  Sustain is
    the mean bass over the next ~0.4 s vs the previous ~0.4 s."""
    n = len(t)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    w = max(1, int(0.4 * SR / HOP))
    csum = np.concatenate([[0.0], np.cumsum(bass)])
    after = np.array([(csum[min(n, i + w)] - csum[i]) / max(1, min(n, i + w) - i)
                      for i in range(n)])
    before = np.array([(csum[i] - csum[max(0, i - w)]) / max(1, i - max(0, i - w))
                       for i in range(n)])
    sustain = np.clip(after / (before + 1e-9), 0.0, 6.0)
    return (flux * sustain).astype(np.float32)


def refine_entry(path: str, cand_t: float, bpm: float, b_len: float = 0.0,
                 search_beats: float = 3.0):
    """Move `cand_t` to the hardest on-grid drop within ±search_beats.

    Returns (refined_t, impact) — impact is the drop score at the chosen
    point, 0.0 if nothing usable (caller keeps the original cue).  Grid-
    locked: candidates are restricted to cand_t + k·beat so we relocate to a
    bigger drop WITHOUT breaking beat phase, then snap to the exact onset.
    """
    if bpm <= 0 or cand_t <= 0:
        return cand_t, 0.0
    beat = 60.0 / bpm
    pad = search_beats * beat + 0.6
    t0 = max(0.0, cand_t - pad)
    dur = 2 * pad + 0.5
    if b_len > 0:
        dur = min(dur, max(0.0, b_len - t0))
    x = _decode(path, t0, dur)
    if len(x) < WIN * 4:
        return cand_t, 0.0
    t, rms, bass, flux = _features(x)
    score = _drop_score(t, rms, bass, flux)
    if score.size == 0:
        return cand_t, 0.0
    rel = cand_t - t0                       # candidate position within the clip
    # test the cue's own grid AND a half-beat-shifted grid; keep whichever
    # grid's beat instants carry more onset energy (fixes half-beat phase slips)
    best = (cand_t, 0.0)
    for phase in (0.0, 0.5):
        anchor = rel + phase * beat
        grid_k = range(int(-search_beats), int(search_beats) + 1)
        cands = []
        for k in grid_k:
            gt = anchor + k * beat
            gi = int(round(gt * SR / HOP))
            if gi < 1 or gi >= len(score) - 1:
                continue
            # let the drop sit within ±0.1 beat of the grid instant, snap to it
            lo = max(0, gi - int(0.1 * beat * SR / HOP))
            hi = min(len(score), gi + int(0.1 * beat * SR / HOP) + 1)
            j = lo + int(np.argmax(score[lo:hi]))
            cands.append((j, score[j]))
        if not cands:
            continue
        gj, gs = max(cands, key=lambda c: c[1])
        # fine-snap to the sharp ATTACK (flux peak) of the chosen drop — the
        # cut lands on the transient itself, even when the drop sits a little
        # off the nominal grid (real drops often anticipate the downbeat)
        fw = int(0.15 * beat * SR / HOP)
        flo, fhi = max(0, gj - fw), min(len(flux), gj + fw + 1)
        fj = flo + int(np.argmax(flux[flo:fhi]))
        if gs > best[1]:
            best = (t0 + t[fj], float(gs))
    # require the winner to be a real improvement over just staying put, else
    # keep the original (a flat section has no drop to chase)
    ref_i = int(round(rel * SR / HOP))
    here = score[ref_i] if 0 <= ref_i < len(score) else 0.0
    if best[1] < max(here * 1.15, 1e-6):
        return cand_t, float(here)
    return round(best[0], 3), best[1]


def refine_exit(path: str, cand_t: float, bpm: float,
                search_beats: float = 1.5):
    """Snap A's exit to a strong on-grid beat near cand_t.

    The out-cue is chosen to mix OUT gently (a low-energy spot), which for a
    SLAM lands the cut on a dead beat — A gets chopped mid-groove. Here we
    move the cut to the strongest ONSET (a decisive hit) on A's beat grid
    within ±search_beats, so A leaves ON the beat. Uses raw onset flux (not
    the sustained drop-score — an exit wants a sharp hit, not a build) and a
    mild distance penalty so it snaps to the NEAREST decisive beat rather
    than wandering to a far louder one. Returns refined_t (or cand_t)."""
    if bpm <= 0 or cand_t <= 0:
        return cand_t
    beat = 60.0 / bpm
    pad = search_beats * beat + 0.5
    t0 = max(0.0, cand_t - pad)
    x = _decode(path, t0, 2 * pad + 0.3)
    if len(x) < WIN * 4:
        return cand_t
    t, rms, bass, flux = _features(x)
    if flux.size == 0:
        return cand_t
    rel = cand_t - t0
    ci = int(round(rel * SR / HOP))
    here = flux[ci] if 0 <= ci < len(flux) else 0.0
    best_t, best_score = cand_t, here
    for phase in (0.0, 0.5):                   # cue may sit a half-beat off
        anchor = rel + phase * beat
        for k in range(-int(search_beats), int(search_beats) + 1):
            gi = int(round((anchor + k * beat) * SR / HOP))
            if gi < 1 or gi >= len(flux) - 1:
                continue
            w = int(0.12 * beat * SR / HOP)
            lo, hi = max(0, gi - w), min(len(flux), gi + w + 1)
            j = lo + int(np.argmax(flux[lo:hi]))
            dist = abs(t[j] - rel) / beat
            score = flux[j] * (0.8 ** dist)    # prefer strong AND near
            if score > best_score and flux[j] > here * 1.3:
                best_t, best_score = t0 + t[j], score
    return round(best_t, 3)


def verify_bridge(path: str, seam_t: float, bpm: float,
                  is_slam: bool = True) -> dict:
    """Decode the RENDERED bridge and grade the hand-off.

    seam_t  — mix-time (s) where B's drop is SUPPOSED to land (the cut beat).
    Returns a verdict dict: {ok, offset_ms, hardness, level_db, clip, why}.
    Thresholds are deliberately stricter for slams (they expose the seam)."""
    beat = 60.0 / bpm if bpm > 0 else 0.5
    win = max(1.2, 2.5 * beat)
    x = _decode(path, max(0.0, seam_t - win), 2 * win)
    verdict = {"ok": False, "offset_ms": 999.0, "hardness": 0.0,
               "level_db": -99.0, "clip": False, "why": []}
    if len(x) < WIN * 4:
        verdict["why"].append("decode-too-short")
        return verdict
    local0 = max(0.0, seam_t - win)
    t, rms, bass, flux = _features(x)
    score = _drop_score(t, rms, bass, flux)
    seam_rel = seam_t - local0
    # 1) did the drop land on the cut beat? render_slam places B's refined
    #    entry EXACTLY at seam_rel (mix-time = pre), so B's incoming drop lives
    #    at/just-before the seam. The search is BIASED POST-SEAM — only a hair
    #    (0.10 beat) of anticipation is allowed — so A's fading tail transient
    #    can never win the argmax. A symmetric ±0.5-beat window used to let A's
    #    last kick hijack the offset whenever B's drop was weak (folk/singer-
    #    songwriter B with no real drop), producing a phantom, A-dependent
    #    off-beat reading identical across re-cuts (the -62/-236ms bug). Whether
    #    B actually HITS is judged separately by `hardness` at the seam below.
    lo = max(0, int((seam_rel - 0.10 * beat) * SR / HOP))
    hi = min(len(score), int((seam_rel + 0.5 * beat) * SR / HOP))
    if hi > lo:
        cj = lo + int(np.argmax(score[lo:hi]))
        fw = int(0.15 * beat * SR / HOP)
        flo, fhi = max(lo, cj - fw), min(hi, cj + fw + 1)
        j = flo + int(np.argmax(flux[flo:fhi]))
        offset_ms = (t[j] - seam_rel) * 1000.0
    else:
        offset_ms = 999.0
    verdict["offset_ms"] = round(float(offset_ms), 1)
    # 2) hardness: energy just AFTER the seam vs just before (a slam must
    #    JUMP, not ease in). Take the bigger of the bass jump and the
    #    broadband-power jump, so a vocal/synth drop counts too, not only sub.
    aw = max(1, int(0.25 * SR / HOP))
    si = int(seam_rel * SR / HOP)
    b_before, b_after = bass[max(0, si - aw):si], bass[si:si + aw]
    p_before = rms[max(0, si - aw):si] ** 2
    p_after = rms[si:si + aw] ** 2
    if b_before.size and b_after.size:
        hard_bass = np.log10((b_after.mean() + 1e-9) /
                             (b_before.mean() + 1e-9)) * 20.0
        hard_bb = np.log10((p_after.mean() + 1e-12) /
                           (p_before.mean() + 1e-12)) * 10.0
        hardness = float(max(hard_bass, hard_bb))
    else:
        hardness = 0.0
    verdict["hardness"] = round(hardness, 1)
    # 3) level continuity: overall seam RMS shouldn't crater
    verdict["level_db"] = round(float(20 * np.log10(rms.mean() + 1e-9)), 1)
    # 4) clip: near full-scale sample run
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    verdict["clip"] = peak >= 0.999
    # ---- gate ----
    hard_min = SLAM_HARD_MIN if is_slam else -1.0   # dB jump; slams must gain
    why = []
    # Off-beat tolerance: 35 ms strict for slams (on-beat cut law — his
    # mandate: cuts ONLY on the songs' beat; 150 ms at 140 BPM is a third
    # of a beat, plainly audible). A hardness-scaled looser gate was tried
    # 2026-07-22 but never auditioned (renders were broken at that commit)
    # — if the strict gate rejects slams his ear would accept, that is an
    # EAR-PICK between rendered candidates, not a blind constant change.
    off_tol = 35.0 if is_slam else 55.0      # ms
    if abs(offset_ms) > off_tol:
        why.append(f"off-beat {offset_ms:+.0f}ms")
    if is_slam and hardness < hard_min:
        why.append(f"soft-drop {hardness:+.1f}dB")
    if verdict["clip"]:
        why.append("clipping")
    verdict["why"] = why
    verdict["ok"] = not why
    return verdict
