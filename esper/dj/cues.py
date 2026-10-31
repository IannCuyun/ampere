"""DJ cue-point analysis for Ampere.

Finds the *musically strong* places to enter and leave a track, so the
player can transition like a live DJ: cut out of song A at the end of a
hot phrase and land on song B's drop, instead of always blending tail
into intro.

Per track this computes (full-file decode, mono 11025 Hz):

  * a beat grid — BPM (autocorrelation of the spectral-flux onset
    envelope, same method as ampere.energy) plus the beat PHASE and the
    downbeat (strongest-of-4 phase by bass-onset energy).  Every cue is
    snapped to a downbeat so cuts land on a bar line.
  * entry cues ("drops") — downbeats where bass + total energy jump
    sharply out of a quieter stretch (buildup -> slam).  Scored by the
    jump in dB, gated on the landing zone actually being loud.
  * exit cues — downbeats in the back of the track where a high-energy
    phrase ends (energy cliff / breakdown start): a cool place to cut out.
  * confidence 0..1 from the beat-grid strength.  Tracks without a firm
    pulse (ambient, rubato acoustic) get conf ~0 and are never DJ-cut.

The integrator stores the result as the ``joi_cues`` MPD sticker — a
compact JSON dict:

  {"v": 1, "bpm": 150.1, "b0": 0.31, "conf": 0.82, "dur": 193.2,
   "in": [[22.4, 0.9], ...], "out": [[161.2, 0.8], ...]}

``b0`` is the first downbeat (s); cue entries are [time_s, score 0..1],
best first, max 3 each.  ``v`` versions the heuristic so a smarter pass
can rescan only stale stickers.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np

CUES_VERSION = 2   # v2: cues onset-snapped — cuts land ON the local beat
sticker_key = "joi_cues"

SR = 11025
N_FFT = 256
HOP = 128
FPS = SR / HOP            # ~86.1 envelope frames per second
MAX_SECONDS = 720         # cap decode (DJ mixes / audiobooks)
FFMPEG_TIMEOUT = 300
BASS_BINS = slice(1, 4)   # 43..172 Hz at SR/N_FFT = 43 Hz per bin


# ---------------------------------------------------------------- decode

def _decode(abs_path: str) -> np.ndarray | None:
    """Whole file to mono float32 [-1, 1] at SR, or None on failure."""
    # niced: cue scans run for hours in the background — they must never
    # steal cycles from MPD's decode at a transition (audible stutter)
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "quiet", "-i", abs_path,
           "-ac", "1", "-ar", str(SR), "-t", str(MAX_SECONDS),
           "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,
                              timeout=FFMPEG_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = proc.stdout
    if proc.returncode != 0 or len(raw) < 2:
        return None
    pcm = np.frombuffer(raw, dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


# ---------------------------------------------------------------- features

def _spectrogram(x: np.ndarray) -> np.ndarray | None:
    """Magnitude spectrogram, frames x bins, float32."""
    n = (x.size - N_FFT) // HOP + 1
    if n < int(20 * FPS):     # need ~20 s to talk about structure
        return None
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(n, N_FFT),
        strides=(x.strides[0] * HOP, x.strides[0]))
    win = np.hanning(N_FFT).astype(np.float32)
    return np.abs(np.fft.rfft(frames * win, axis=1)).astype(np.float32)


def _flux(mag: np.ndarray) -> np.ndarray:
    """Spectral-flux onset envelope from a magnitude spectrogram."""
    fx = np.maximum(mag[1:] - mag[:-1], 0.0).sum(axis=1)
    fx = np.concatenate([[0.0], fx])
    if fx.size >= 3:
        fx = np.convolve(fx, [0.25, 0.5, 0.25], mode="same")
    return fx.astype(np.float32)


def _estimate_bpm(flux: np.ndarray, rms: float) -> tuple[float, float]:
    """(bpm, acf_peak).  bpm = 0 when the envelope has no firm pulse.

    Same autocorrelation method as ampere.energy._estimate_bpm, but also
    returns the normalised ACF peak as the beat-grid strength."""
    if flux.size < int(4 * FPS):
        return 0.0, 0.0
    if float(flux.mean()) < 1.0 * rms:
        return 0.0, 0.0
    env = flux - flux.mean()
    denom = float(np.dot(env, env))
    if denom <= 0:
        return 0.0, 0.0

    lag_min = max(2, int(round(FPS * 60.0 / 190.0)))
    lag_max = min(int(round(FPS * 60.0 / 60.0)), env.size // 2)
    if lag_max <= lag_min + 2:
        return 0.0, 0.0

    top = min(2 * lag_max + 2, env.size - 1)
    acf = np.array([np.dot(env[:-k], env[k:]) / denom
                    for k in range(1, top + 1)], dtype=np.float64)

    def a(k: int) -> float:
        return acf[k - 1] if 1 <= k <= acf.size else 0.0

    lags = np.arange(lag_min, lag_max + 1)
    score = np.array([a(k) + 0.5 * a(2 * k) for k in lags])
    best_i = int(np.argmax(score))
    best_lag = float(lags[best_i])
    peak = a(int(lags[best_i]))

    floor = float(np.median([a(int(k)) for k in lags]))
    if peak < 0.08 or peak - floor < 0.04:
        return 0.0, 0.0

    k = int(lags[best_i])
    y0, y1, y2 = a(k - 1), a(k), a(k + 1)
    d = (y0 - 2 * y1 + y2)
    if d < 0:
        best_lag = k + 0.5 * (y0 - y2) / d
    if not np.isfinite(best_lag) or best_lag <= 0:
        return 0.0, 0.0
    bpm = FPS * 60.0 / best_lag
    if not np.isfinite(bpm) or bpm <= 0:
        return 0.0, 0.0
    while bpm > 180.0:
        bpm /= 2.0
    while bpm < 70.0:
        bpm *= 2.0
    return float(round(bpm, 1)), float(peak)


def _comb_sum(env: np.ndarray, start: float, period: float) -> float:
    """Mean of env sampled at start, start+period, ... (linear interp)."""
    if period <= 0 or start >= env.size - 1:
        return 0.0
    pos = np.arange(start, env.size - 1, period)
    if pos.size == 0:
        return 0.0
    return float(np.interp(pos, np.arange(env.size), env).mean())


def _beat_grid(flux: np.ndarray, bass_flux: np.ndarray,
               bpm: float) -> tuple[float, float]:
    """(first_downbeat_frame, bar_frames).

    Beat phase = comb offset maximising onset energy; downbeat = the one
    of the 4 beat slots where the STRONGEST bass onsets concentrate.

    The downbeat used to be picked by an equal-weight comb sum of bass
    onsets across the whole file, which a sparse/ambiguous intro could
    drag 1-2 beats off (FE!N's first drop snapped a beat early). Now the
    loud kicks vote: every above-90th-percentile bass onset is folded to
    its nearest beat-of-4 slot, weighted by its strength, so the real
    drop kicks dominate and a quiet intro contributes almost nothing.
    The vote is blended with the old comb score for stability on
    four-on-the-floor material (where every slot gets a kick)."""
    beat = FPS * 60.0 / bpm
    phases = np.arange(0.0, beat, max(0.25, beat / 64.0))
    scores = [_comb_sum(flux, p, beat) for p in phases]
    phase = float(phases[int(np.argmax(scores))])
    bar = 4.0 * beat
    comb = np.array([_comb_sum(bass_flux, phase + k * beat, bar)
                     + 0.3 * _comb_sum(flux, phase + k * beat, bar)
                     for k in range(4)], dtype=np.float64)
    votes = np.zeros(4)
    if bass_flux.size > 2 and beat > 0:
        thr = float(np.percentile(bass_flux, 90))
        if thr > 0:
            idx = np.nonzero(bass_flux >= thr)[0]
            slots = np.round(((idx - phase) / beat) % 4.0).astype(int) % 4
            for s, i in zip(slots, idx):
                votes[s] += bass_flux[i]
    if votes.max() > 0 and comb.max() > 0:
        k = int(np.argmax(0.6 * (votes / votes.max())
                          + 0.4 * (comb / comb.max())))
    else:
        k = int(np.argmax(comb))
    return phase + k * beat, bar


_KEY_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KEY_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


KEY_FFT = 8192            # ~1.35 Hz/bin at 11025 — a semitone is resolvable
KEY_LO_HZ = 55.0          # A1 — low enough for bass fundamentals
KEY_HI_HZ = 2000.0        # ~5 octaves of harmonic content
KEY_MIN_R = 0.62          # K-S correlation below this = no confident key


def _chroma(x: np.ndarray, sr: int) -> np.ndarray | None:
    """12-bin pitch-class profile (index 0 = A, semitones up), high enough
    resolution to actually separate keys.

    A Welch-averaged 8192-pt magnitude spectrum (~1.3 Hz bins) over the
    whole file; every bin within a quarter-tone of a real semitone centre
    folds into its pitch class, everything between semitones is dropped as
    noise. The old detector chroma'd the 43 Hz/bin onset spectrogram —
    coarser than a semitone below ~700 Hz — so it collapsed most of the
    library onto one key. Returns None when there isn't enough signal."""
    if x.size < KEY_FFT:
        return None
    hop = KEY_FFT // 2
    win = np.hanning(KEY_FFT).astype(np.float32)
    acc = np.zeros(KEY_FFT // 2 + 1, dtype=np.float64)
    cnt = 0
    for start in range(0, x.size - KEY_FFT, hop):
        seg = x[start:start + KEY_FFT] * win
        acc += np.abs(np.fft.rfft(seg)) ** 2
        cnt += 1
    if cnt == 0:
        return None
    spec = np.sqrt(acc / cnt)
    freqs = np.arange(spec.size) * (sr / KEY_FFT)
    with np.errstate(divide="ignore"):
        midi = 12.0 * np.log2(np.where(freqs > 0, freqs, 1.0) / 440.0)
    sel = ((freqs >= KEY_LO_HZ) & (freqs <= KEY_HI_HZ)
           & (np.abs(midi - np.round(midi)) <= 0.35))
    if not sel.any():
        return None
    pcs = np.round(midi[sel]).astype(int) % 12
    chroma = np.bincount(pcs, weights=spec[sel], minlength=12).astype(np.float64)
    return chroma if chroma.sum() > 0 else None


def _estimate_key(x: np.ndarray, sr: int) -> int:
    """Rough musical key via the high-res chroma + Krumhansl-Schmuckler
    profile correlation. Returns tonic 0–11 (semitones above A) for major,
    12+tonic for minor, -1 when unconvincing. Used both as a set-ordering
    preference AND (now) a graded harmonic-mix quality input, so accuracy
    actually matters — but a wrong guess still only softens a transition,
    never breaks one."""
    chroma = _chroma(x, sr)
    if chroma is None:
        return -1
    c = chroma - chroma.mean()
    cn = float(np.linalg.norm(c))
    if cn <= 0:
        return -1
    best_key, best_r = -1, 0.0
    for prof, base in ((_KEY_MAJ, 0), (_KEY_MIN, 12)):
        p = prof - prof.mean()
        pn = float(np.linalg.norm(p)) or 1.0
        for rot in range(12):
            r = float(np.dot(np.roll(p, rot), c)) / (pn * cn)
            if r > best_r:
                best_key, best_r = base + rot, r
    return best_key if best_r >= KEY_MIN_R else -1


# ---------------------------------------------------------------- vocals
# Lightweight lead-vocal-presence detection (no separation models). The
# strongest cheap cue is the STEREO CENTRE channel: lead vocals sit dead
# centre, so a high mid-vs-side energy ratio in 300-4000 Hz marks a vocal —
# gated by the ~3-8 Hz syllabic flux modulation so centred bass/kick don't
# trip it. Mono material falls back to the syllabic + tonal cues. Output is
# a per-cue "is there a vocal in the overlap region" value used to duck the
# mids or reroute the mix point — a soft signal, never a hard veto.

VOC_SR = 22050
VOC_NFFT = 2048
VOC_HOP = 512
VOC_FPS = VOC_SR / VOC_HOP
VOC_LO_HZ = 300.0
VOC_HI_HZ = 4000.0


def _decode_stereo(abs_path: str, sr: int = VOC_SR):
    """(L, R) float32 at `sr`, or None. Separate from the mono BPM/key pass
    — vocal detection needs both channels and headroom to 4 kHz."""
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "quiet", "-i", abs_path,
           "-ac", "2", "-ar", str(sr), "-t", str(MAX_SECONDS),
           "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = proc.stdout
    if proc.returncode != 0 or len(raw) < 4:
        return None
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    pcm = pcm[: pcm.size // 2 * 2].reshape(-1, 2)
    if pcm.shape[0] < VOC_NFFT * 2:
        return None
    return pcm[:, 0], pcm[:, 1]


def _stft_mag(x: np.ndarray) -> np.ndarray | None:
    n = (x.size - VOC_NFFT) // VOC_HOP + 1
    if n < 4:
        return None
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(n, VOC_NFFT),
        strides=(x.strides[0] * VOC_HOP, x.strides[0]))
    win = np.hanning(VOC_NFFT).astype(np.float32)
    return np.abs(np.fft.rfft(frames * win, axis=1)).astype(np.float32)


def _bandpass_env(env: np.ndarray, fps: float, lo: float,
                  hi: float) -> np.ndarray:
    """Magnitude of an envelope band-limited to [lo,hi] Hz via FFT (pure
    numpy — no scipy). Isolates the syllabic-rate fluctuation of a voice."""
    n = env.size
    if n < 8:
        return np.zeros_like(env)
    E = np.fft.rfft(env - float(env.mean()))
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)
    E[(freqs < lo) | (freqs > hi)] = 0.0
    return np.abs(np.fft.irfft(E, n=n)).astype(np.float32)


def _znorm(a: np.ndarray) -> np.ndarray:
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med))) + 1e-9
    return (a - med) / (1.4826 * mad)


def _min_dur(mask: np.ndarray, min_on: int, min_gap: int) -> np.ndarray:
    """Fill True-gaps shorter than min_gap, then drop True-runs shorter than
    min_on — the standard VAD duration filter that kills spurious slivers."""
    m = mask.copy()
    edges = np.flatnonzero(np.diff(np.r_[0, m.view(np.int8), 0]))
    runs = list(zip(edges[::2], edges[1::2]))       # True runs (start,end)
    # fill short OFF gaps between consecutive ON runs
    for (s0, e0), (s1, e1) in zip(runs, runs[1:]):
        if s1 - e0 < min_gap:
            m[e0:s1] = True
    edges = np.flatnonzero(np.diff(np.r_[0, m.view(np.int8), 0]))
    for s, e in zip(edges[::2], edges[1::2]):
        if e - s < min_on:
            m[s:e] = False
    return m


# calibration (from a labelled vocal/instrumental sweep 2026-07-18): the
# per-frame presence `pres` runs ~0.05 in instrumental beds, ~0.15-0.4 under
# a lead vocal. These map it to 0..1 and gate the voiced boolean.
VOC_PRES_LO = 0.09
VOC_PRES_HI = 0.34
VOC_ON = 0.40


def _vocal_env(abs_path: str):
    """(voc_env 0..1 per frame, fps, vocal_frac) or None.

    The discriminating feature (validated on labelled tracks): the ~3-8 Hz
    SYLLABIC MODULATION of the vocal-band (300-4 kHz) CENTRE-channel energy,
    scaled by how much of that energy is centre-exclusive (cancels in L-R).
    A steady centred pad/synth barely modulates; a lead vocal fluctuates at
    the syllable rate — that separates them where a plain centre-energy ratio
    (high for kick/bass/synths too) cannot. Mono tracks keep the modulation
    term and assume the centre fraction."""
    st = _decode_stereo(abs_path)
    if st is None:
        return None
    L, R = st
    Mmid = _stft_mag(L + R)
    Mside = _stft_mag(L - R)
    if Mmid is None or Mside is None or Mmid.shape[0] != Mside.shape[0]:
        return None
    nfrm = Mmid.shape[0]
    if nfrm < 16:
        return None
    freqs = np.arange(Mmid.shape[1]) * (VOC_SR / VOC_NFFT)
    vb = (freqs >= VOC_LO_HZ) & (freqs <= VOC_HI_HZ)
    if not vb.any():
        return None
    is_mono = float((Mside ** 2).sum()) / (float((Mmid ** 2).sum()) + 1e-9) \
        < 0.05
    mid = Mmid[:, vb].sum(1)
    side = Mside[:, vb].sum(1)
    voc_excl = np.maximum(0.0, mid - side)             # centre-exclusive
    # local syllabic-rate modulation of the vocal-band centre energy
    bp = _bandpass_env(mid / (float(mid.mean()) + 1e-9), VOC_FPS, 3.0, 8.0)
    w = max(3, int(VOC_FPS))                           # ~1 s local window
    mod = np.sqrt(np.convolve(bp ** 2, np.ones(w) / w, mode="same"))
    if is_mono:
        vf = np.full(nfrm, 0.6, dtype=np.float32)
    else:
        vf = voc_excl / (mid + 1e-9)
    sw = max(3, int(0.5 * VOC_FPS))
    vf = np.convolve(vf, np.ones(sw) / sw, mode="same")
    pres = mod * (0.5 + 0.5 * vf)
    voc = np.clip((pres - VOC_PRES_LO) / (VOC_PRES_HI - VOC_PRES_LO),
                  0.0, 1.0)
    voc = np.convolve(voc, np.ones(sw) / sw, mode="same")
    voiced = _min_dur(voc > VOC_ON, int(0.6 * VOC_FPS), int(0.4 * VOC_FPS))
    voc_env = np.where(voiced, np.maximum(VOC_ON, voc),
                       voc * 0.3).astype(np.float32)
    return voc_env.astype(np.float32), VOC_FPS, float(voiced.mean())


def _cue_vocal(voc_env: np.ndarray, fps: float, t: float,
               bar_s: float) -> float:
    """Vocal presence in the ~4 bars BEFORE a cue (the material that plays
    into the bridge), triangular-weighted toward the cue. 0..1."""
    if voc_env is None or fps <= 0:
        return 0.0
    win = max(1.0, 4.0 * bar_s)
    a = int(max(0, (t - win) * fps))
    b = int(min(voc_env.size, t * fps))
    if b - a < 2:
        return 0.0
    seg = voc_env[a:b]
    wts = np.linspace(0.3, 1.0, seg.size)          # weight toward the cue
    return float(np.clip((seg * wts).sum() / (wts.sum() + 1e-9), 0.0, 1.0))


def _snap_to_onset(f: float, onset: np.ndarray, half_beat_f: float,
                   floor: float) -> float:
    """Snap a grid boundary to the strongest LOCAL onset — the true beat.

    The global constant-tempo grid drifts over minutes (a 0.3% tempo
    error is ~0.5 s three minutes in — audibly off-beat), so a cue must
    anchor to the audible hit near the grid line, not the extrapolated
    line itself. Window is ±0.45 beat: wide enough to reach the real
    beat after drift, too narrow to hop to a different one. Sections
    with no distinct hit (breakdown silence, pads) keep the grid time."""
    w = max(2, int(half_beat_f * 0.9))
    a = max(0, int(f) - w)
    b = min(onset.size, int(f) + w + 1)
    if b - a < 3:
        return f
    win = onset[a:b]
    peak = int(np.argmax(win))
    if win[peak] < floor:
        return f
    return float(a + peak)


def _smooth_db(env: np.ndarray, win_frames: int) -> np.ndarray:
    """Envelope -> smoothed dB curve (floored at -80)."""
    db = 20.0 * np.log10(np.maximum(env, 1e-6))
    db = np.maximum(db, -80.0)
    w = max(3, win_frames | 1)
    kernel = np.ones(w, dtype=np.float32) / w
    return np.convolve(db, kernel, mode="same")


def _pick(cands: list[tuple[float, float, float]], min_gap: float,
          limit: int = 3) -> list[list[float]]:
    """Greedy top-N by score with a minimum time separation. Each cue is
    stored [t, score, level_db, voc]: the absolute envelope level around the
    cue (so the planner can loudness-match seams ACROSS songs) and the
    vocal presence in the material that plays into the bridge (0..1, for
    the mid-duck / two-vocal gate). Cue scores only rank moments within one
    song."""
    out: list[list[float]] = []
    for c in sorted(cands, key=lambda c: -c[1]):
        if c[1] <= 0.05:
            break
        if all(abs(c[0] - o[0]) >= min_gap for o in out):
            voc = round(c[3], 2) if len(c) > 3 else 0.0
            out.append([round(c[0], 2), round(c[1], 2), round(c[2], 1), voc])
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------- public

def analyze(abs_path: str) -> dict | None:
    """Analyze one file.  Returns the joi_cues dict (see module docstring)
    or None if the file cannot be decoded.  Undanceable tracks return a
    valid dict with conf 0.0 and no cues — that is a *result*, and gets
    stored so the scanner does not retry forever."""
    x = _decode(abs_path)
    if x is None:
        return None
    dur = x.size / SR
    flat = {"v": CUES_VERSION, "bpm": 0.0, "b0": 0.0, "conf": 0.0,
            "dur": round(dur, 1), "key": -1, "lv": 1, "bcut": 120.0,
            "voc": 0.0, "in": [], "out": []}
    mag = _spectrogram(x)
    if mag is None:
        return flat
    flux = _flux(mag)
    bass = mag[:, BASS_BINS].sum(axis=1)
    bass_flux = np.maximum(np.diff(bass, prepend=bass[0]), 0.0)
    rms = float(np.sqrt(np.mean(x * x)))
    key = _estimate_key(x, SR)   # high-res chroma — needs the raw signal
    del x

    bpm, peak = _estimate_bpm(flux, rms)
    if bpm <= 0:
        return flat
    conf = float(np.clip((peak - 0.06) / 0.30, 0.0, 1.0))

    b0_f, bar_f = _beat_grid(flux, bass_flux, bpm)
    n = flux.size
    bar_s = bar_f / FPS

    # lead-vocal presence timeline (separate stereo decode) — feeds the
    # per-cue vocal value for the mid-duck / two-vocal gate. Best-effort:
    # None on failure just means "no vocal info" (cues get voc 0.0).
    _vres = _vocal_env(abs_path)
    voc_env = _vres[0] if _vres else None
    voc_fps = _vres[1] if _vres else 0.0
    voc_frac = round(_vres[2], 2) if _vres else 0.0

    # structure envelopes: total + bass loudness, ~0.35 s smoothing
    tot_db = _smooth_db(mag.sum(axis=1), int(FPS * 0.35))
    bass_db = _smooth_db(bass, int(FPS * 0.35))
    # bass crossover (bcut): the frequency the renderer's bass hand-off
    # should split at for THIS track, instead of a fixed 120 Hz. It's the
    # energy centroid of the low band over the loud sections (the drop's
    # kick/sub), clamped to a sane DJ range. Coarse — 43 Hz bins — but
    # directionally right: sub-heavy trap lands low so the incoming sub
    # isn't gutted; kick-forward house lands high so two kicks don't stack.
    low_bins = slice(1, 6)                       # ~43..215 Hz
    freqs_low = np.arange(1, 6) * (SR / N_FFT)
    loud = tot_db > np.percentile(tot_db, 70)
    lb = mag[loud, low_bins] if loud.any() else mag[:, low_bins]
    w = lb.sum(axis=0)
    bcut = (float(np.dot(w, freqs_low) / w.sum())
            if float(w.sum()) > 0 else 120.0)
    bcut = float(np.clip(bcut, 90.0, 150.0))
    del mag
    p90 = float(np.percentile(tot_db, 90))
    b90 = float(np.percentile(bass_db, 90))

    def near_peak(v: float, ref: float, span: float) -> float:
        """1.0 at the track's loud ceiling, 0.0 span dB below it.
        (Median-relative tests fail both ways: brickwalled masters have
        no total-loudness span, and bass-heavy genres have a bass median
        as high as their drops.)"""
        return float(np.clip(1.0 - (ref - v) / span, 0.0, 1.0))

    def seg(env: np.ndarray, a: float, b: float) -> float:
        i, j = int(max(0, a)), int(min(n, b))
        return float(env[i:j].mean()) if j - i >= 3 else -80.0

    # candidates every half-bar: drops don't always land on OUR bar-1
    # (the downbeat phase can be off by two beats on sparse intros)
    half = bar_f / 2.0
    gap = 0.3 * FPS   # skip the smearing around the boundary itself

    # onset envelope for beat snapping: total flux + kick-weighted bass
    # flux, each scaled by its own loud ceiling so neither dominates
    fx90 = float(np.percentile(flux, 90)) or 1.0
    bx90 = float(np.percentile(bass_flux, 90)) or 1.0
    onset = flux / fx90 + 1.5 * (bass_flux / bx90)
    snap_floor = 0.35   # a real hit, not noise in a quiet stretch
    half_beat_f = bar_f / 8.0

    def phrase_align(f: float) -> float:
        """How well a cue lands on a musical PHRASE line (multiple of 8/16
        bars from the first downbeat) — what makes a mix read 'intentional'
        instead of sloppy. 1.0 on a 16-bar line, 0.75 on 8, 0.45 on a bar,
        0 mid-phrase. Dance music's drops/breakdowns sit on these lines, so
        this reinforces the energy cues rather than fighting them."""
        if bar_f <= 0:
            return 0.0
        bars_from = (f - b0_f) / bar_f
        for m, v in ((16.0, 1.0), (8.0, 0.75), (4.0, 0.45)):
            if abs(bars_from - round(bars_from / m) * m) < 0.5:
                return v
        return 0.0

    entries: list[tuple[float, float]] = []
    exits: list[tuple[float, float]] = []
    for fg in np.arange(b0_f, n - 1, half):
        # every cue lands ON the local beat: the audible hit nearest the
        # grid line, not the (drift-prone) extrapolated line itself
        f = _snap_to_onset(fg, onset, half_beat_f, snap_floor)
        t = f / FPS
        # phrase bonus: reward cues on 8/16-bar lines, gently penalise
        # mid-phrase ones — ranking nudge only (capped at 1.0), so a strong
        # energy cue that's slightly off-phrase still wins over a weak one
        ph = 0.9 + 0.15 * phrase_align(f)
        # --- entry: quiet/building 4 bars -> loud 2 bars (the drop)
        if 3.0 <= t <= 0.65 * dur and f + 2 * bar_f < n:
            before_b = seg(bass_db, f - 4 * bar_f, f - gap)
            before_t = seg(tot_db, f - 4 * bar_f, f - gap)
            after_b = seg(bass_db, f + gap, f + 2 * bar_f)
            after_t = seg(tot_db, f + gap, f + 2 * bar_f)
            jump = 0.6 * (after_b - before_b) + 0.4 * (after_t - before_t)
            landing = max(near_peak(after_t, p90, 6.0),
                          near_peak(after_b, b90, 12.0))
            score = float(np.clip(jump / 10.0, 0.0, 1.0)
                          * (0.25 + 0.75 * landing))
            score = min(1.0, score * ph)
            if score > 0:
                entries.append((t, score, after_t,
                                _cue_vocal(voc_env, voc_fps, t, bar_s)))
        # --- exit: hot 2 bars ending here, ideally into an energy cliff
        if t >= 0.35 * dur and f - 2 * bar_f >= 0:
            before_t = seg(tot_db, f - 2 * bar_f, f - gap)
            before_b = seg(bass_db, f - 2 * bar_f, f - gap)
            hot = max(near_peak(before_t, p90, 6.0),
                      0.85 * near_peak(before_b, b90, 12.0))
            if f + bar_f < n:
                cliff = np.clip((before_t - seg(tot_db, f + gap, f + bar_f))
                                / 10.0, 0.0, 1.0)
            else:
                cliff = 0.3
            score = float(hot * (0.35 + 0.65 * cliff))
            score = min(1.0, score * ph)
            if score > 0.2:
                exits.append((t, score, before_t,
                              _cue_vocal(voc_env, voc_fps, t, bar_s)))

    return {"v": CUES_VERSION, "bpm": bpm, "b0": round(b0_f / FPS, 2),
            "conf": round(conf, 2), "dur": round(dur, 1), "key": key,
            "lv": 1, "bcut": round(bcut, 1), "voc": voc_frac,
            "in": _pick(entries, max(8.0, 2 * bar_s)),
            "out": _pick(exits, max(8.0, 2 * bar_s))}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m ampere.djcues FILE...", file=sys.stderr)
        return 2
    status = 0
    for path in args:
        res = analyze(path)
        if res is None:
            print(f"{path}\tDECODE-FAILED")
            status = 1
            continue
        ins = " ".join(f"{c[0]:g}s({c[1]:g} @{c[2]:g}dB)"
                       for c in res["in"]) or "-"
        outs = " ".join(f"{c[0]:g}s({c[1]:g} @{c[2]:g}dB)"
                        for c in res["out"]) or "-"
        print(f"{path}\n  bpm={res['bpm']:g} b0={res['b0']:g} "
              f"conf={res['conf']:g} dur={res['dur']:g}\n"
              f"  in : {ins}\n  out: {outs}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
