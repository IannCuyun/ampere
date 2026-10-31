"""Track energy + BPM analysis for Ampere.

Decodes audio with ffmpeg to mono 11025 Hz s16 PCM and computes two
perceptual descriptors, intended to be stored as MPD stickers by the
integrator (this module never writes stickers itself):

  * ``energy`` -- perceptual intensity in 0..1.
  * ``bpm``    -- tempo estimate in 70..180 BPM, or 0 when confidence
                  is low (flat autocorrelation of the onset envelope).

Energy formula
--------------
Four components, each mapped linearly to 0..1 and blended.  All the
break-points below were calibrated against real library tracks
(quiet classical / orchestral / folk / synthwave / trap / deathcore):

  L  loudness    overall RMS in dBFS, -25 dB -> 0, -9 dB -> 1.
                 Quiet classical masters bottom out, brickwalled
                 metal/trap saturate.
  H  HF level    absolute high-frequency level in dB:
                 rms_db + 20*log10(RMS(diff(x)) / RMS(x)).  The first
                 difference is a ~6 dB/oct high-pass, so this is "how
                 loud are the cymbals / distortion / bright synths",
                 mapped -30 dB -> 0, -12 dB -> 1.  (Using the absolute
                 level, not the ratio, stops bright-but-quiet acoustic
                 picking from out-scoring a wall of distorted guitar.)
  D  density     inverse short-term dynamic range: 20*log10(p95/p20)
                 of per-hop frame RMS, mapped 15 dB -> 0, 3 dB -> 1.
                 Heavily compressed always-full mixes (metal, EDM)
                 score high; sparse or breathing mixes score low.
  O  busyness    onset density: spectral-flux peaks per second above
                 mean + 0.8*std, mapped 2/s -> 0, 7/s -> 1.

D and O are also published in their own right (``dyn``/``busy``), because
each answers a question energy cannot: how sparse a record is, and how
much it breathes. Folding them into one number threw both away.

  energy = clip(0.45*L + 0.25*H + 0.20*D + 0.10*O, 0, 1)

Observed anchors: quiet solo-keyboard classical ~0.2, orchestral /
atmospheric electronica ~0.4-0.45, dark folk ~0.6, synthwave ~0.7,
trap ~0.75, metal/deathcore ~0.8-0.95.

BPM method
----------
Onset-strength envelope = spectral flux (positive spectral difference,
FFT 256 / hop 128 at 11025 Hz => ~86 fps), lightly smoothed.  Its
autocorrelation is scanned over lags corresponding to 60..190 BPM; each
lag's score also credits its half-tempo harmonic (acf at 2*lag) to
stabilise octave choice.  The winning lag is refined by parabolic
interpolation and the BPM folded into 70..180.  If the normalised peak
is weak (flat autocorrelation, i.e. no periodicity), bpm = 0.

Long tracks are windowed to their middle: decode skips the first 30 s
and caps at 120 s; short tracks fall back to decoding from the start.
Analysis cost is well under 5 s per track at this sample rate.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np

# Sticker keys used by the integrator (MPD sticker names).
tag_key = "joi_energy"
bpm_tag_key = "joi_bpm"
bass_tag_key = "joi_bass"      # low-end weight 0..1 (Sound Profiles)
bright_tag_key = "joi_bright"  # spectral brightness 0..1 (Sound Profiles)
busy_tag_key = "joi_busy"      # onset peaks/sec: sparse <-> busy
dyn_tag_key = "joi_dyn"        # short-term dynamic range in dB: p95/p20

SR = 11025            # analysis sample rate (Hz)
N_FFT = 256
HOP = 128
FPS = SR / HOP        # onset-envelope frame rate, ~86.1 fps
FFMPEG_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------- decode

def _decode(abs_path: str, skip_intro: bool) -> np.ndarray | None:
    """Decode to mono float32 in [-1, 1] at SR, or None on failure."""
    # niced: background enrichment must never compete with playback decode
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "quiet"]
    if skip_intro:
        cmd += ["-ss", "30"]
    cmd += ["-i", abs_path, "-ac", "1", "-ar", str(SR),
            "-t", "120", "-f", "s16le", "-"]
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


def _load(abs_path: str) -> np.ndarray | None:
    """Middle-of-track window: skip 30 s, cap 120 s; fall back for
    short files (< ~15 s left after the skip)."""
    x = _decode(abs_path, skip_intro=True)
    if x is None or x.size < 15 * SR:
        x = _decode(abs_path, skip_intro=False)
    if x is None or x.size < 2 * SR:   # need at least ~2 s to say anything
        return None
    return x


# ---- several windows, because a song is not its first two minutes --------

WINDOW_SECONDS = 40
WINDOW_COUNT = 3
MULTI_WINDOW_MIN = 200.0   # seconds; below this one window IS the song


def duration_seconds(abs_path: str) -> float | None:
    """Container duration without decoding a sample."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", abs_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        value = float(proc.stdout.decode("ascii", "ignore").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _decode_at(abs_path: str, start: float, seconds: int) -> np.ndarray | None:
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "quiet",
           "-ss", f"{max(0.0, start):.2f}", "-i", abs_path,
           "-ac", "1", "-ar", str(SR), "-t", str(seconds),
           "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,
                              timeout=FFMPEG_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = proc.stdout
    if proc.returncode != 0 or len(raw) < 2 * SR:
        return None
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def windows(abs_path: str) -> list[np.ndarray]:
    """Up to three evenly spread windows of a long track.

    One 30 s - 2:30 window judged a whole song by its opening: Metallica's
    "One" measured as sparse ambient because the window sat entirely in the
    clean-guitar intro (found 2026-08-23).  Windows are analyzed separately
    and combined by median, never concatenated — a seam between two unrelated
    passages is a transient that would inflate onset density and destroy the
    tempo autocorrelation.
    """
    total = duration_seconds(abs_path)
    if total is None or total < MULTI_WINDOW_MIN:
        one = _load(abs_path)
        return [one] if one is not None else []
    span = total - WINDOW_SECONDS
    frames = []
    for index in range(WINDOW_COUNT):
        start = span * (index + 0.5) / WINDOW_COUNT
        frame = _decode_at(abs_path, start, WINDOW_SECONDS)
        if frame is not None and frame.size >= 2 * SR:
            frames.append(frame)
    if frames:
        return frames
    one = _load(abs_path)
    return [one] if one is not None else []


def tail_db(abs_path: str) -> float | None:
    """RMS level (dBFS) of the file's last ~1.5 s.

    A hot tail (≥ ~-21 dB) means the track runs straight into the next one
    on its album — a gapless segue that shuffle must not slice. Decoded
    separately with -sseof so it stays cheap regardless of track length."""
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "quiet", "-sseof", "-2.5",
           "-i", abs_path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = proc.stdout
    if proc.returncode != 0 or len(raw) < 2:
        return None
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    tail = x[-int(1.5 * SR):]
    if tail.size < int(0.4 * SR):
        return None
    rms = float(np.sqrt(np.mean(tail * tail)))
    if rms <= 1e-6:
        return -120.0
    return float(round(20.0 * np.log10(rms), 1))


# ---------------------------------------------------------------- features

def _onset_envelope(x: np.ndarray) -> np.ndarray:
    """Spectral-flux onset strength at FPS frames/sec."""
    n = (x.size - N_FFT) // HOP + 1
    if n < 8:
        return np.zeros(0, dtype=np.float32)
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(n, N_FFT),
        strides=(x.strides[0] * HOP, x.strides[0]))
    win = np.hanning(N_FFT).astype(np.float32)
    mag = np.abs(np.fft.rfft(frames * win, axis=1))
    flux = np.maximum(mag[1:] - mag[:-1], 0.0).sum(axis=1)
    # light 3-tap smoothing
    if flux.size >= 3:
        flux = np.convolve(flux, [0.25, 0.5, 0.25], mode="same")
    return flux.astype(np.float32)


def _onset_rate(flux: np.ndarray) -> float:
    """Onset peaks per second above an adaptive threshold."""
    if flux.size < 3:
        return 0.0
    thr = flux.mean() + 0.8 * flux.std()
    mid = flux[1:-1]
    peaks = (mid > flux[:-2]) & (mid >= flux[2:]) & (mid > thr)
    return float(peaks.sum()) / (flux.size / FPS)


def _estimate_bpm(flux: np.ndarray, rms: float) -> float:
    """Autocorrelation tempo over 60-190 BPM, folded to 70-180.

    Returns 0.0 when the autocorrelation is flat (low confidence) or
    when the onset envelope is negligible relative to the signal level
    (steady drones/pads produce numerical-ripple flux that would
    otherwise yield a spurious tempo).
    """
    if flux.size < int(4 * FPS):          # need a few seconds of envelope
        return 0.0
    if float(flux.mean()) < 1.0 * rms:    # no real onsets in the mix
        return 0.0
    env = flux - flux.mean()
    denom = float(np.dot(env, env))
    if denom <= 0:
        return 0.0

    lag_min = max(2, int(round(FPS * 60.0 / 190.0)))   # ~27
    lag_max = int(round(FPS * 60.0 / 60.0))            # ~86
    lag_max = min(lag_max, env.size // 2)
    if lag_max <= lag_min + 2:
        return 0.0

    # normalised ACF out to 2*lag_max so harmonic credit stays in range
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

    # confidence: the raw ACF peak must clearly rise above the floor of
    # the search range, else the envelope is aperiodic -> return 0
    floor = float(np.median([a(int(k)) for k in lags]))
    if peak < 0.08 or peak - floor < 0.04:
        return 0.0

    # parabolic interpolation around the winning lag
    k = int(lags[best_i])
    y0, y1, y2 = a(k - 1), a(k), a(k + 1)
    d = (y0 - 2 * y1 + y2)
    if d < 0:
        best_lag = k + 0.5 * (y0 - y2) / d

    # a non-positive / non-finite lag (the parabolic interpolation can push
    # best_lag <= 0) yields bpm <= 0, and the octave-folding below would then
    # spin forever ( 0*2==0 ; negatives double toward -inf, never reaching 70 ).
    # That infinite loop pegged a core and froze the whole UI — guard it.
    if not np.isfinite(best_lag) or best_lag <= 0:
        return 0.0
    bpm = FPS * 60.0 / best_lag
    if not np.isfinite(bpm) or bpm <= 0:
        return 0.0
    while bpm > 180.0:
        bpm /= 2.0
    while bpm < 70.0:
        bpm *= 2.0
    return float(round(bpm, 1))


def _spectral(x: np.ndarray) -> tuple[float, float]:
    """(bass, bright) both 0..1 from the average power spectrum.

    A dedicated 2048-pt frame pass (5.4 Hz bins) — the onset pass's 256-pt
    frames are 43 Hz/bin, far too coarse to see the bass band. Raw measures:

      bass   = 10*log10( P(<90 Hz) / P(total) ) — the SUB share. Level-
               independent (RG leveling makes relative weight what you
               hear), and the <90 Hz cut is load-bearing: a <150 Hz band
               reads warm folk low-mids (guitar body, floor drums) as
               "bass-heavy"; 808s/club subs live below 90.
      bright = spectral centroid (Hz) of the >50 Hz power spectrum,
               log-mapped — "where the mix's weight sits": muffled/warm
               low-centroid vs airy/crisp high-centroid.

    Break-points calibrated 2026-07-20 on a 27-track genre spread of the
    real library: sub share -13 dB -> 0, -1.5 dB -> 1 (classical ~0.0-0.2,
    darkwave/metal/folk ~0.45-0.78, trap/hyperpop/club pop ~0.83-1.0);
    centroid 300 Hz -> 0, 1300 Hz -> 1 (log2 scale: dark trap ~0.2, pop
    ~0.3-0.45, metal walls ~0.73, opera/orchestral ~0.8+)."""
    n_fft, hop = 2048, 1024
    n = (x.size - n_fft) // hop + 1
    if n < 4:
        return 0.5, 0.5
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(n, n_fft),
        strides=(x.strides[0] * hop, x.strides[0]))
    win = np.hanning(n_fft).astype(np.float32)
    pw = (np.abs(np.fft.rfft(frames * win, axis=1)) ** 2).mean(axis=0)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / SR)
    total = float(pw.sum())
    if total <= 0:
        return 0.5, 0.5
    share = float(pw[freqs < 90.0].sum()) / total
    share_db = 10.0 * np.log10(max(share, 1e-9))
    bass = float(np.clip((share_db + 13.0) / 11.5, 0.0, 1.0))  # -13 .. -1.5 dB
    hi = freqs >= 50.0
    centroid = float((freqs[hi] * pw[hi]).sum() / (pw[hi].sum() + 1e-9))
    centroid = max(centroid, 120.0)
    bright = float(np.clip(np.log2(centroid / 300.0)
                           / np.log2(1300.0 / 300.0), 0.0, 1.0))
    return round(bass, 3), round(bright, 3)


def spectral(abs_path: str) -> tuple[float, float] | None:
    """Standalone (bass, bright) for the lazy backfill pass — files analyzed
    before these traits existed get just this decode, not a re-analysis."""
    x = _load(abs_path)
    if x is None:
        return None
    return _spectral(x)


def dynamic_range(x: np.ndarray) -> float:
    """Short-term dynamic range in dB: p95 vs p20 of per-hop frame RMS.

    High = the record breathes (sparse or dynamic mastering); low = an
    always-full compressed mix.  Published on its own because "intense"
    and "loud" are not the same question.
    """
    n = (x.size // HOP) * HOP
    if n < HOP * 10:
        return 15.0
    fr = np.sqrt(np.mean(x[:n].reshape(-1, HOP) ** 2, axis=1))
    fr = fr[fr > 1e-5]
    if fr.size < 10:
        return 15.0
    p20, p95 = np.percentile(fr, [20, 95])
    return float(round(20.0 * np.log10(p95 / (p20 + 1e-9)), 2))


def _energy(x: np.ndarray, onset_rate: float) -> float:
    """Blend loudness, HF level, density and busyness into 0..1
    (formula and calibration anchors in the module docstring)."""
    rms = float(np.sqrt(np.mean(x * x)))
    if rms <= 1e-6:
        return 0.0
    db = 20.0 * np.log10(rms)
    L = np.clip((db + 25.0) / 16.0, 0.0, 1.0)            # -25 .. -9 dB

    hf_ratio = float(np.sqrt(np.mean(np.diff(x) ** 2))) / (rms + 1e-9)
    hf_db = db + 20.0 * np.log10(max(hf_ratio, 1e-6))
    H = np.clip((hf_db + 30.0) / 18.0, 0.0, 1.0)         # -30 .. -12 dB

    dyn_db = dynamic_range(x)
    D = np.clip((15.0 - dyn_db) / 12.0, 0.0, 1.0)        # 15 .. 3 dB

    O = np.clip((onset_rate - 2.0) / 5.0, 0.0, 1.0)      # 2/s .. 7/s

    e = 0.45 * L + 0.25 * H + 0.20 * D + 0.10 * O
    return float(round(np.clip(e, 0.0, 1.0), 3))


# ---------------------------------------------------------------- public

def _describe(x: np.ndarray) -> dict:
    """Every descriptor for one window."""
    flux = _onset_envelope(x)
    rate = _onset_rate(flux)
    bass, bright = _spectral(x)
    return {"energy": _energy(x, rate), "bass": bass, "bright": bright,
            "busy": float(round(rate, 2)), "dyn": dynamic_range(x),
            "_flux": flux, "_rms": float(np.sqrt(np.mean(x * x)))}


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


def analyze(abs_path: str) -> dict | None:
    """Analyze one audio file.

    Returns {"bpm": float (0 if low confidence), "energy": float 0..1,
    "tail_db": float dBFS of the last 1.5 s (or None if undecodable),
    "bass", "bright", "busy" (onsets/sec), "dyn" (dB)} or None if the
    file cannot be decoded at all.
    """
    frames = windows(abs_path)
    if not frames:
        return None
    described = [_describe(frame) for frame in frames]
    # Tempo needs a contiguous passage, so it comes from the single most
    # rhythmic window rather than from a statistic across all of them.
    rhythmic = max(described, key=lambda d: float(np.sum(d["_flux"]))
                   if d["_flux"].size else 0.0)
    return {"bpm": _estimate_bpm(rhythmic["_flux"], rhythmic["_rms"]),
            "energy": round(_median([d["energy"] for d in described]), 3),
            "tail_db": tail_db(abs_path),
            "bass": round(_median([d["bass"] for d in described]), 3),
            "bright": round(_median([d["bright"] for d in described]), 3),
            "busy": round(_median([d["busy"] for d in described]), 2),
            "dyn": round(_median([d["dyn"] for d in described]), 2)}


def texture(abs_path: str) -> tuple[float, float] | None:
    """(busy, dyn) for one file — the backfill path for tracks that were
    analyzed before these two were published."""
    frames = windows(abs_path)
    if not frames:
        return None
    described = [_describe(frame) for frame in frames]
    return (round(_median([d["busy"] for d in described]), 2),
            round(_median([d["dyn"] for d in described]), 2))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m ampere.energy FILE...", file=sys.stderr)
        return 2
    status = 0
    for path in args:
        res = analyze(path)
        if res is None:
            print(f"{path}\tDECODE-FAILED")
            status = 1
        else:
            tail = res["tail_db"]
            print(f"{path}\tbpm={res['bpm']:g}\tenergy={res['energy']:.3f}"
                  f"\tbass={res['bass']:.3f}\tbright={res['bright']:.3f}"
                  f"\ttail={'?' if tail is None else f'{tail:g} dB'}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
