"""Ampere DJ engine — the beatmatched-transition subsystem, decoupled.

Iann's call (2026-07-19): develop the DJ engine as its own unit, integrate
into the live player through ONE seam, so experiments never risk playback and
parallel sessions can't collide inside the giant Backend in mpdclient.py.

Layout
------
  cues.py    — per-track beat grid + entry/exit cue analysis (`joi_cues`
               sticker). Pure ffmpeg+numpy. Owns CUES_VERSION.
  bridge.py  — offline transition RENDERER (render / render_slam). ffmpeg
               filter graphs; RG-baked, tag-clean. Owns BRIDGE_V.
  verify.py  — drop-accurate entry refinement + post-render acceptance gate
               (refine_entry / refine_exit / verify_bridge). Pure numpy.

These three are already fully decoupled from the app (no Qt, no MPD, no
Backend) — they are imported by the planner and by debug/dj_bench.py.

PHASE 2 (planned, not yet done): extract the PLANNER out of Backend.
-----------------------------------------------------------------------
Today the planner (~70 `_dj_*` methods, ~85 `_dj_*` state vars) lives inside
`Backend` in mpdclient.py. It is woven into three things it must be freed from:

  1. MPD access      — self._cmd / self._call / self._refresh_queue /
                       self._song_map / playlistinfo / status / rangeid …
  2. Qt plumbing     — self._bridgeReady + errorOccurred signals, the QTimer
                       heartbeat (_dj_tick), background render threads.
  3. QML surface     — djTimeline/djOn/djLevel/… are @Property, and
                       startDjSession/djCutNow/… are @Slot. QML binds to these
                       ON Backend, so they CANNOT become plain Python.

Target design:
  * `engine.DjEngine` — a plain-Python object owning ALL `_dj_*` state and
    logic (planning, cue selection, set/journey building, bridge prep,
    verify orchestration, votes/learning). It reaches MPD + config + signals
    ONLY through an injected `Host` (see engine.py) — never touches Qt.
  * Backend keeps the QML-facing @Property/@Slot shims, each a one-line
    delegate to `self._dj` (the DjEngine), and passes itself (adapted) as the
    Host so notify signals still fire from Backend.

The move is done in cohesive SLICES (votes/learning first — most self-
contained — then cue selection, then set building, then the live splice
planner last), each slice bench-verified (debug/dj_bench.py seam err ≈ 0)
and live-verified before the next. No big-bang: mpdclient.py is load-bearing
and has a history of parallel-session corruption.
"""
