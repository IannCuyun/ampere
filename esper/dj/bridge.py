"""Rendered DJ transitions ("bridges") for Ampere.

MPD can't mix like a DJ at playback time — no per-track volume, a linear
crossfade capped by the audio buffer, no time-stretch.  So the mix is
rendered OFFLINE instead: for a qualifying pair A→B, ffmpeg produces a
short standalone track containing

  * A's last N bars (8/16), ending at A's exit cue (a phrase-end downbeat)
  * B's N bars of build — the bars *preceding* B's entry cue — time-
    stretched with ``atempo`` to A's tempo so the beats stay locked
  * an equal-power volume cross (A rides down on a cosine, B up on a sine)
  * each part's ReplayGain baked in (the bridge itself is tagged 0 dB so
    MPD's leveling stays continuous across the seams)
  * 20 ms edge fades so the sample seams against the range-sliced
    originals can never tick

The queue then plays  A(range …:cut−N·bar) → bridge → B(range entry:…)
gapless with crossfade 0.  B's main range starts AT the entry cue — the
drop lands exactly where A dies, and B's ≤4 % tempo step back to native
is masked by the drop impact.

Bridges are cached in ~/.cache/ampere/djbridge keyed by the pair + cuts,
LRU-pruned.  CLI for by-ear tuning:

    python -m ampere.djbridge FILE_A FILE_B     (cues read from MPD stickers)
"""

from __future__ import annotations

from ampere.compat import cache_path as storage_cache_path, environment
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

BRIDGE_DIR = Path(storage_cache_path('djbridge'))
BRIDGE_V = 10              # v10: resume offset (LIMITER_ATTACK 5→120ms), slam
                           # suddenness (SLAM_CROSS 50→30ms), edge declick
                           # (EDGE_FADE 20→4ms). v9: slam geometry fixed — drop
                           # lands DRY and ON the cut beat (was 90 ms early + faded),
                           # tempo-clashing echo tail removed.
MAX_CACHED = 96            # bridges are small FLACs; keep more so a track you
                           # loop back to doesn't re-render from scratch
FFMPEG_TIMEOUT = 120
EDGE_FADE = 0.004         # seconds; declick ONLY. The old 20ms fade-to-zero
                          # on continuous audio guaranteed a −28/−34 dB silence
                          # dip at every seam (measured on real pairs); on slams
                          # it landed mid-groove 2 bars after the drop. 4ms kills
                          # the tick without an audible hole — never raise it.
SLAM_CROSS = 0.030        # A's declick fade-out INTO the drop; the drop itself
                          # lands dry (B pre-roll fades under A, drop at full).
                          # Shorter = harder, more sudden slam hit. 50ms was
                          # mushy; 30ms lands punchy without a tick.
LIMITER_ATTACK_MS = 5.0   # alimiter lookahead (pinned, not left to ffmpeg's
                          # ⚠⚠ ffmpeg's LEGAL RANGE for alimiter attack is
                          # 0.1–80 ms — the 2026-07-22 "fix" to 120 ms was OUT
                          # OF RANGE, ffmpeg rejected the whole filter graph,
                          # and EVERY bridge render failed (DJ silently fell
                          # back to raw crossfades). The real delay is the
                          # lookahead: click-train probe measures 4.98 ms at
                          # attack=5, re-confirming the 2026-07-19 dead-constant
                          # 4.9–5.0 ms measurement. A "124–126 ms skip" cannot
                          # be measured off a render that never happened.
                          # (original rationale below, still true:
                          # default): the limiter DELAYS the signal by this much,
                          # so `atrim=0:total` clips the last LIMITER_ATTACK_MS of
                          # real B content off the bridge tail. The B-resume must
                          # be pulled back by exactly this, or B replays/skips a
                          # ~120 ms sliver right after the drop = the post-cut
                          # stutter (measured constant 124-126 ms, 2026-07-22
                          # via debug/dj_bench on multiple pairs). The 5ms attack
                          # was insufficient; ffmpeg's lookahead+rendering delay
                          # totals ~120ms. Pinning it keeps the compensation
                          # correct across ffmpeg versions.
LIMITER_LATENCY = LIMITER_ATTACK_MS / 1000.0
MAX_TEMPO_RATIO = 1.03    # ≤3% earns a cheap atempo; above that, rubberband
RIDE_MAX = 1.08           # up to 8% tempo match via a single formant-preserved
                          # rubberband stretch (clean well past atempo's limit);
                          # bigger gaps still fall to a clean slam
RIDE_CHUNKS = 4           # (legacy — the stepped ride is retired; kept so old
                          # callers/imports don't break)
BASS_SWAP_HZ = 120        # default bass hand-off crossover (per-track bcut
                          # from djcues overrides it; this is the fallback)
BASS_HZ_MIN = 70.0
BASS_HZ_MAX = 190.0
MID_HI_HZ = 4000.0        # mid/high split — mids (bass_hz..4 kHz) are the
                          # vocal band, ducked when two vocals would collide
ANALYZE_SR = 11025


def fold_bpm(bpm: float, ref: float) -> float:
    """Fold bpm by octaves (×2/÷2) to the value nearest ref — 74 BPM mixes
    against 148 in 2:1 bars."""
    if bpm <= 0 or ref <= 0:
        return bpm
    best = bpm
    for k in (0.25, 0.5, 1.0, 2.0, 4.0):
        v = bpm * k
        if abs(math.log2(v / ref)) < abs(math.log2(best / ref)):
            best = v
    return best


def mixable(bpm_a: float, bpm_b: float) -> bool:
    """True when the pair can hold a locked beat for a long overlap —
    directly (≤4.2%) or via a stepped tempo ride (≤8.5%)."""
    if bpm_a <= 0 or bpm_b <= 0:
        return False
    f = fold_bpm(bpm_b, bpm_a)
    return max(f, bpm_a) / min(f, bpm_a) <= RIDE_MAX


def _needs_ride(bpm_a: float, bpm_b_folded: float) -> bool:
    r = max(bpm_b_folded, bpm_a) / min(bpm_b_folded, bpm_a)
    return r > MAX_TEMPO_RATIO


def _track_gain(path: str) -> float:
    """ReplayGain track gain (dB) from the file's tags, 0.0 if untagged."""
    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(path)
        g = (mf.get("replaygain_track_gain")
             or mf.get("TXXX:replaygain_track_gain") or [""])[0]
        if hasattr(g, "text"):
            g = (g.text or [""])[0]
        return float(str(g).split()[0])
    except Exception:
        return 0.0


def plan_overlap(a_cut: float, a_bpm: float, b_entry: float, b_bpm: float,
                 bars: int) -> tuple[int, float]:
    """(bars_used, overlap_seconds) the renderer would produce for this
    pair — same degradation math, no ffmpeg. (0, 0.0) when unmixable.

    overlap is A-INPUT seconds consumed, which equals bars·bar_a whether
    or not a tempo ride runs (input beats consumed == beats played). The
    mix uses only real audio on both sides — a build too short for the
    requested bars simply shortens the mix (down to a 4-bar floor); below
    that the pair falls to a clean slam instead."""
    if a_bpm <= 0 or b_bpm <= 0 or a_cut <= 0 or b_entry <= 0:
        return 0, 0.0
    bpm_b = fold_bpm(b_bpm, a_bpm)
    if max(bpm_b, a_bpm) / min(bpm_b, a_bpm) > RIDE_MAX:
        return 0, 0.0
    bar_a = 4 * 60.0 / a_bpm
    bar_b = 4 * 60.0 / bpm_b
    avail_b = int(b_entry / bar_b)
    bars = min(bars, int(a_cut / bar_a), avail_b)
    if bars < 4:
        return 0, 0.0
    return bars, bars * bar_a


def cache_path(rel_a: str, cut: float, rel_b: str, entry: float,
               bars: int, variant: str = "") -> Path:
    """bars > 0 = mix bridge, bars == 0 = slam bridge; variant is reserved
    to key any future special render apart in the cache (unused today)."""
    key = hashlib.sha1(
        f"v{BRIDGE_V}|{rel_a}|{cut:.2f}|{rel_b}|{entry:.2f}|{bars}|{variant}"
        .encode(), usedforsecurity=False).hexdigest()
    return BRIDGE_DIR / (key + ".flac")


def _seg_rms_db(path: str, start: float, dur: float) -> float | None:
    """RMS (dBFS) of a segment — the ear the loudness-matching uses."""
    if dur <= 0.05:
        return None
    cmd = ["nice", "-n", "10", "ffmpeg", "-v", "quiet",
           "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}", "-i", path,
           "-ac", "1", "-ar", str(ANALYZE_SR), "-f", "s16le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = r.stdout
    if r.returncode != 0 or len(raw) < 2000:
        return None
    import numpy as np
    x = np.frombuffer(raw[: len(raw) // 2 * 2],
                      dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x)))
    if rms <= 1e-6:
        return -80.0
    return 20.0 * math.log10(rms)


def prune_cache(keep: int = MAX_CACHED):
    try:
        files = sorted(BRIDGE_DIR.glob("*.flac"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            p.unlink(missing_ok=True)
    except OSError:
        pass


_HAS_RUBBERBAND = None


def has_rubberband() -> bool:
    """True if this ffmpeg was built with librubberband (the high-quality,
    formant-preserving pitch shifter). Cached — probed once."""
    global _HAS_RUBBERBAND
    if _HAS_RUBBERBAND is None:
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                               capture_output=True, timeout=10)
            _HAS_RUBBERBAND = b"rubberband" in r.stdout
        except (OSError, subprocess.TimeoutExpired):
            _HAS_RUBBERBAND = False
    return _HAS_RUBBERBAND


def tempo_pitch(tag_in: str, tag_out: str, tempo: float,
                semitones: int) -> str:
    """Filter chain that stretches [tag_in] by `tempo` (output/input speed;
    <1 slows) AND pitches it `semitones` up/down (0 = tempo only), leaving
    [tag_out].

    A key shift, OR any tempo stretch past a few percent, goes through ONE
    rubberband pass (pitch + tempo together, formant-preserved) — the
    artifact-minimal route the research consensus prefers, and clean well
    past atempo's limit, which is what lets the mix ceiling reach 8%.
    Falls back to a single asetrate+atempo term when librubberband is
    absent. Never stack two time-domain passes; that compounds the smear.

    ⚠ ALL stretches route through rubberband when it's present — atempo's
    internal rate quantization drifts the output DURATION (measured:
    atempo=1.0177 ran +8.9 ms long over 51 s), which shifts where B's
    source content ends inside the bridge → a ~9 ms REPEAT at every
    small-stretch mix→B resume (the seam flam). rubberband is
    sample-exact (measured 0.0 ms at 5% both ways)."""
    if semitones == 0 and abs(tempo - 1.0) < 1e-4:
        return f"[{tag_in}]acopy[{tag_out}];"
    ratio = 2.0 ** (semitones / 12.0)
    if has_rubberband():
        return (f"[{tag_in}]rubberband=pitch={ratio:.6f}:tempo={tempo:.6f}"
                f":formant=preserved:transients=crisp:pitchq=quality"
                f":channels=together[{tag_out}];")
    if semitones == 0:
        return f"[{tag_in}]atempo={tempo:.6f}[{tag_out}];"
    # fallback: asetrate raises BOTH pitch and tempo by `ratio`; one atempo
    # then reconciles to the target stretch — net atempo = tempo / ratio
    net = max(0.5, min(2.0, tempo / ratio))
    return (f"[{tag_in}]asetrate=48000*{ratio:.6f},aresample=48000,"
            f"atempo={net:.6f}[{tag_out}];")


def render(a_path: str, a_cut: float, a_bpm: float,
           b_path: str, b_entry: float, b_bpm: float,
           bars: int, out_path: Path,
           a_title: str = "", b_title: str = "",
           bass_hz: float = BASS_SWAP_HZ,
           pitch_semitones: int = 0,
           duck_a: float = 0.0, duck_b: float = 0.0) -> tuple[float, float]:
    """Render the A→B bridge.  Returns (overlap_seconds, 0.0): overlap =
    A-input seconds consumed (the planner ends A's range at cut−overlap).
    (0.0, 0.0) on failure — below 4 bars the pair isn't worth a mix. The
    second element is always 0.0 (kept for the caller's tuple unpack).

    The craft in the graph, all offline and on REAL audio only:
      * A plays at its native tempo; B is stretched to A's (and optionally
        pitch-shifted into key) in ONE formant-preserved rubberband pass —
        clean up to the 8% mix ceiling, no stepped ride needed.
      * 4-band hand-off (mixes ≥6 bars): the LOW band hard-swaps on the
        drop (one bassline at a time, split at the per-track bass_hz); MID
        (bass_hz–4 kHz) and HIGH (>4 kHz) equal-power crossfade. When the
        two tracks' vocals would collide, duck_a/duck_b cut the yielding
        deck's MID band (the vocal band) by that many dB, so only one lead
        stays forward."""
    bars, overlap = plan_overlap(a_cut, a_bpm, b_entry, b_bpm, bars)
    if bars < 4:
        return 0.0, 0.0
    bpm_b = fold_bpm(b_bpm, a_bpm)
    bar_a = 4 * 60.0 / a_bpm
    bar_b = 4 * 60.0 / bpm_b
    a_in = overlap
    b_in = bars * bar_b
    a_start = a_cut - overlap
    b_start = b_entry - bars * bar_b
    g_a = _track_gain(a_path)
    g_b = _track_gain(b_path)
    t_out = total = overlap        # A native; B stretched to fill the overlap

    swap = bars >= 6               # the bass hand-off needs room to breathe
    bass_hz = max(BASS_HZ_MIN, min(BASS_HZ_MAX,
                                   float(bass_hz or BASS_SWAP_HZ)))
    duck_a = max(0.0, min(12.0, float(duck_a)))
    duck_b = max(0.0, min(12.0, float(duck_b)))
    # ---- 4-band hand-off envelopes (the core pro move, researched) -------
    # LOW band is a HARD swap on the downbeat, not a slow blend: A keeps its
    # bass until ~2 beats before the end — the moment B's drop (its entry
    # cue) lands — then A's low drops out and B's low comes up over ~1.5
    # beats. Only ONE bassline plays at a time. MID (bass_hz-4 kHz, the vocal
    # band) and HIGH (>4 kHz) equal-power crossfade; a vocal collision ducks
    # the yielding deck's MID via duck_a/duck_b. Split at the per-track bass_hz.
    beat_a = bar_a / 4.0
    t_sw = max(0.0, t_out - 2.0 * beat_a)
    swap_dur = max(0.15, min(1.5 * beat_a, t_out - t_sw)) or 0.15
    a_low = (f"if(lt(t,{t_sw:.4f}),1,"
             f"max(0,1-(t-{t_sw:.4f})/{swap_dur:.4f}))")
    b_low = (f"if(lt(t,{t_sw:.4f}),0,"
             f"min(1,(t-{t_sw:.4f})/{swap_dur:.4f}))")
    a_up = f"cos(min(t/{t_out:.4f},1)*PI/2)"     # equal-power crossfade down
    b_up = f"sin(min(t/{t_out:.4f},1)*PI/2)"     # equal-power crossfade up

    def bands(tag: str, low_expr: str, up_expr: str, out: str,
              duck_db: float = 0.0) -> str:
        """Split a deck into LOW (hard bass swap), MID (bass_hz-4 kHz) and
        HIGH (>4 kHz). MID/HIGH equal-power crossfade; MID is cut by duck_db
        (the vocal duck). Emits [out+'L'/'M'/'H'] for the master mix."""
        mid_expr = up_expr
        if duck_db > 0:
            mid_expr = f"({up_expr})*{10.0 ** (-duck_db / 20.0):.4f}"
        # Linkwitz-Riley 4th-order split: the three bands are phase-
        # complementary and sum back FLAT. The old asplit + naive
        # lowpass/highpass sum notched ~6.6 dB at bass_hz and ~6.7 dB at
        # MID_HI_HZ (measured against pink noise), gutting kick/bass body
        # and presence through the whole bridge — that was the "thin /
        # compressed / low-quality" bridge sound. acrossover outputs low→
        # high, so the pads map straight to L/M/H.
        return (f"[{tag}]acrossover=split={bass_hz:.1f} {MID_HI_HZ:.0f}:"
                f"order=4th[{tag}sl][{tag}sm][{tag}sh];"
                f"[{tag}sl]volume='{low_expr}':eval=frame[{out}L];"
                f"[{tag}sm]volume='{mid_expr}':eval=frame[{out}M];"
                f"[{tag}sh]volume='{up_expr}':eval=frame[{out}H];")

    fc = []
    # ---- A: gain (native tempo)
    fc.append(f"[0:a]asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,"
              f"aresample=48000,volume={g_a:.2f}dB[a0];")
    a_tag = "a0"
    # ---- B: gain → tempo (+ optional key shift) in one pass
    fc.append(f"[1:a]asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,"
              f"aresample=48000,volume={g_b:.2f}dB[b0];")
    fc.append(tempo_pitch("b0", "bt", bar_b / bar_a, pitch_semitones))
    b_tag = "bt"
    # ---- combine: 4-band swap on long mixes, plain equal-power on short ones
    if swap:
        fc.append(bands(a_tag, a_low, a_up, "aB", duck_a))
        fc.append(bands(b_tag, b_low, b_up, "bB", duck_b))
        mix_in, n_in = "[aBL][aBM][aBH][bBL][bBM][bBH]", 6
    else:
        fc.append(f"[{a_tag}]volume='{a_up}':eval=frame[aBU];")
        fc.append(f"[{b_tag}]volume='{b_up}':eval=frame[bBU];")
        mix_in, n_in = "[aBU][bBU]", 2
    fc.append(f"{mix_in}amix=inputs={n_in}:duration=longest:normalize=0,"
              f"alimiter=limit=0.984:level=false:attack={LIMITER_ATTACK_MS},"
              f"afade=t=in:d={EDGE_FADE},"
              f"afade=t=out:st={total - EDGE_FADE:.4f}:d={EDGE_FADE},"
              f"atrim=0:{total:.4f}[out]")
    fc = "".join(fc)
    # render to a temp path and move into place atomically — a killed or
    # timed-out ffmpeg must never leave a truncated file at the cache key
    # (a later cache hit would trust it and play a fraction of the mix)
    tmp = out_path.with_name(out_path.stem + ".tmp.flac")
    cmd = ["nice", "-n", "10", "ffmpeg", "-y", "-v", "error",
           "-ss", f"{a_start:.4f}", "-t", f"{a_in:.4f}", "-i", a_path,
           "-ss", f"{b_start:.4f}", "-t", f"{b_in:.4f}", "-i", b_path,
           "-filter_complex", fc, "-map", "[out]",
           # tag-clean render: ffmpeg otherwise copies input A's metadata
           # wholesale — including its REPLAYGAIN_ALBUM_GAIN, which made
           # album/auto leveling play whole bridges up to ~12 dB off
           "-map_metadata", "-1",
           "-ar", "48000", "-sample_fmt", "s16", str(tmp)]
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    # tag it: honest queue row + neutral RG so leveling stays continuous
    try:
        from mutagen.flac import FLAC
        f = FLAC(str(tmp))
        f["title"] = f"{a_title or Path(a_path).stem} ⇄ {b_title or Path(b_path).stem}"
        f["artist"] = "AMPERE DJ"
        f["replaygain_track_gain"] = "0.00 dB"
        f["replaygain_track_peak"] = "1.0"
        # album tags too: bridges must read 0 dB under ANY leveling mode
        f["replaygain_album_gain"] = "0.00 dB"
        f["replaygain_album_peak"] = "1.0"
        f.save()
    except Exception:
        pass
    try:
        os.replace(tmp, out_path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    prune_cache()
    return overlap, 0.0


def render_slam(a_path: str, a_cut: float, a_bpm: float,
                b_path: str, b_entry: float, b_bpm: float,
                out_path: Path,
                a_title: str = "", b_title: str = "",
                hole_beats: float = 0.0) -> tuple[float, float]:
    """Clean slam: a rendered micro-bridge instead of a raw seam.

    A's last ~2 bars cut into B's first ~2 bars (from its drop) with a
    fast equal-power fader cross (SLAM_CROSS) — the impact of a slam,
    never the click or the level step of one. Loudness-matched: if B
    lands hotter than A ended, B opens pre-ducked by the difference and
    rides back to unity across its 2 bars; if B lands quieter, A eases
    down toward B's level over its last bar first. ReplayGain baked both
    sides; bridge tagged 0 dB.

    Returns (a_part, b_part): seconds consumed from A's tail and B's
    head — the planner ends A's range at cut−a_part and starts B's range
    at entry+b_part. (0, 0) on failure."""
    if a_bpm <= 0 or b_bpm <= 0 or a_cut <= 0 or b_entry <= 0:
        return 0.0, 0.0
    bar_a = 4 * 60.0 / a_bpm
    bar_b = 4 * 60.0 / b_bpm
    pre = min(2 * bar_a, a_cut)
    # clamp B's side to the audio it actually has — an entry cue near the
    # end of the track must not push B's resume point past its own end
    try:
        from mutagen import File as MutagenFile
        b_len = float(getattr(MutagenFile(b_path).info, "length", 0.0))
    except Exception:
        b_len = 0.0
    post = 2 * bar_b
    if b_len > 0:
        post = min(post, max(0.0, b_len - b_entry - 0.5))
    if pre < 0.8 or post < 0.8:
        return 0.0, 0.0
    g_a = _track_gain(a_path)
    g_b = _track_gain(b_path)
    # what the ear hears at the hand-off (post-ReplayGain levels)
    ra = _seg_rms_db(a_path, a_cut - min(bar_a, pre), min(bar_a, pre))
    rb = _seg_rms_db(b_path, b_entry, bar_b)
    delta = ((rb + g_b) - (ra + g_a)) if ra is not None and rb is not None \
        else 0.0
    duck = min(8.0, max(0.0, delta - 1.5))    # B hotter -> pre-duck B
    ease = min(6.0, max(0.0, -delta - 1.5))   # B quieter -> ease A down
    beat_a = bar_a / 4.0
    # Geometry (fixed 2026-07-19): B's DROP must land exactly on A's cut beat
    # (mix-time = pre) and hit DRY. We grab a hair of B BEFORE its drop
    # (pre_roll) and cross A's tail with that pre-roll, so the fade-in lands
    # on pre-drop material and the drop transient itself is at full level.
    # Old code put the drop at pre-SLAM_CROSS (90 ms early) AND faded the
    # drop in — it arrived early and limp. No tempo-locked echo tail: slams
    # are tempo-INcompatible by definition, so A's echoed kicks (A's BPM)
    # flammed against B's groove (B's BPM), drifting 46→92→138 ms = the
    # "stutter". A clean cut into a dry drop is the slam.
    pre_roll = min(SLAM_CROSS, max(0.0, b_entry))
    total = pre + post
    # aggression: a pre-drop HOLE — A cuts to silence hole_beats before the
    # drop, so B slams into a gap (the classic "silence before the drop").
    # When a hole is active there is NO A tail to crossfade against, so B
    # slams DRY and cold (no pre-roll fade) straight onto the cut beat — a
    # harder hit, and unambiguous to the verifier. Without a hole we keep the
    # short pre-roll crossfade so the seam is gapless. The drop always lands
    # dead on mix-time = pre.
    hole_sec = max(0.0, hole_beats) * beat_a
    if hole_sec > pre_roll + 0.02:
        a_cut_at = pre - hole_sec             # A gone this long before the drop
        b_roll = 0.0                          # cold dry slam into the hole
    else:
        a_cut_at = pre
        b_roll = pre_roll
    b_at = pre - b_roll                        # drop (B-time b_roll) -> mix pre

    a_base = (f"[0:a]asetpts=PTS-STARTPTS,"
              f"aformat=channel_layouts=stereo,volume={g_a:.2f}dB")
    ease_part = ""
    if ease > 0:
        # ride A down by `ease` dB across its final bar
        ease_part = (f",volume='pow(10,-({ease:.2f}"
                     f"*min(1,max(0,(t-{pre - bar_a:.4f})/{bar_a:.4f})))/20)'"
                     f":eval=frame")
    # A rides out over the last SLAM_CROSS, ending at a_cut_at (= the drop,
    # or hole_sec before it when a hole is requested)
    fade_part = (f",afade=t=out:st={a_cut_at - SLAM_CROSS:.4f}:d={SLAM_CROSS}"
                 f":curve=hsin")
    a_chain = a_base + ease_part + fade_part + "[a]"

    b_chain = (f"[1:a]asetpts=PTS-STARTPTS,"
               f"aformat=channel_layouts=stereo,volume={g_b:.2f}dB")
    if b_roll > 0.005:
        # fade in ONLY the pre-roll — the drop at B-time b_roll stays full
        b_chain += f",afade=t=in:d={b_roll:.4f}:curve=hsin"
    if duck > 0:
        # open ducked at the DROP, recover to unity across B's 2 bars
        b_chain += (f",volume='pow(10,-({duck:.2f}"
                    f"*max(0,1-(t-{b_roll:.4f})/{post:.4f}))/20)':eval=frame")
    b_chain += f",adelay={int(b_at * 1000)}|{int(b_at * 1000)}[b]"
    mix_in = "[a][b]"
    n_in = 2

    fc = (a_chain + ";" + b_chain + ";"
          f"{mix_in}amix=inputs={n_in}:duration=longest:normalize=0,"
          f"alimiter=limit=0.984:level=false:attack={LIMITER_ATTACK_MS},"
          f"afade=t=in:d={EDGE_FADE},"
          f"afade=t=out:st={total - EDGE_FADE:.4f}:d={EDGE_FADE},"
          f"atrim=0:{total:.4f}[out]")
    tmp = out_path.with_name(out_path.stem + ".tmp.flac")
    cmd = ["nice", "-n", "10", "ffmpeg", "-y", "-v", "error",
           "-ss", f"{a_cut - pre:.4f}", "-t", f"{pre:.4f}", "-i", a_path,
           # grab b_roll seconds of B BEFORE its drop so the drop lands dry
           # (b_roll=0 under a hole: B slams in cold)
           "-ss", f"{b_entry - b_roll:.4f}", "-t", f"{post + b_roll:.4f}",
           "-i", b_path,
           "-filter_complex", fc, "-map", "[out]",
           # tag-clean render: ffmpeg otherwise copies input A's metadata
           # wholesale — including its REPLAYGAIN_ALBUM_GAIN, which made
           # album/auto leveling play whole bridges up to ~12 dB off
           "-map_metadata", "-1",
           "-ar", "48000", "-sample_fmt", "s16", str(tmp)]
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    try:
        from mutagen.flac import FLAC
        f = FLAC(str(tmp))
        f["title"] = (f"{a_title or Path(a_path).stem} ✂ "
                      f"{b_title or Path(b_path).stem}")
        f["artist"] = "AMPERE DJ"
        f["replaygain_track_gain"] = "0.00 dB"
        f["replaygain_track_peak"] = "1.0"
        # album tags too: bridges must read 0 dB under ANY leveling mode
        f["replaygain_album_gain"] = "0.00 dB"
        f["replaygain_album_peak"] = "1.0"
        f.save()
    except Exception:
        pass
    try:
        os.replace(tmp, out_path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return 0.0, 0.0
    prune_cache()
    # Resume B `LIMITER_LATENCY` earlier than the nominal entry+post: the
    # limiter delayed the mix and atrim clipped that much real B off the tail,
    # so the bridge's LAST audible B sample is at (b_entry+post−latency). B must
    # resume there or it skips/replays a ~5 ms sliver right after the drop (the
    # post-cut stutter). The rendered file itself is unchanged — only the
    # returned resume point moves.
    return pre, max(0.0, post - LIMITER_LATENCY)


def main(argv: list[str] | None = None) -> int:
    """By-ear tuning CLI: cues pulled from the MPD stickers."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print("usage: python -m ampere.djbridge FILE_A FILE_B [BARS]",
              file=sys.stderr)
        return 2
    from ..mpdgateway import close_mpd_client, create_mpd_client
    root = os.path.expanduser(environment("MUSIC_ROOT",
                                             "~/MusicLibrary"))
    cli = create_mpd_client()
    cli.connect(environment("MPD_HOST", "127.0.0.1"),
                int(environment("MPD_PORT", "6600")))

    def cues(rel):
        raw = cli.sticker_get("song", rel, "joi_cues")
        raw = raw.split("=", 1)[1] if "=" in raw else raw
        return json.loads(raw)

    rel_a, rel_b = args[0], args[1]
    bars = int(args[2]) if len(args) > 2 else 16
    ca, cb = cues(rel_a), cues(rel_b)
    a_cut = max(c[0] for c in ca["out"]) if ca["out"] else 0
    b_entry = min(c[0] for c in cb["in"]
                  if c[1] >= 0.85 * max(x[1] for x in cb["in"])) if cb["in"] else 0
    out = cache_path(rel_a, a_cut, rel_b, b_entry, bars)
    bass_hz = min(ca.get("bcut", BASS_SWAP_HZ), cb.get("bcut", BASS_SWAP_HZ))
    ov, _ = render(os.path.join(root, rel_a), a_cut, ca["bpm"],
                   os.path.join(root, rel_b), b_entry, cb["bpm"],
                   bars, out,
                   Path(rel_a).stem, Path(rel_b).stem, bass_hz=bass_hz)
    print(f"{out}  (overlap {ov:.2f}s, bass_hz {bass_hz:.0f})" if ov > 0
          else "RENDER-FAILED")
    close_mpd_client(cli)
    return 0 if ov > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
