"""DJ planner logic — the DJ engine's brain, extracted from Backend.

`DjPlannerMixin` holds all internal DJ LOGIC (planning, cue selection, set /
journey building, bridge prep, render/verify orchestration, votes/learning,
the 4 s heartbeat and the bridge-ready handler). It is a MIXIN: Backend is
`class Backend(DjPlannerMixin, QObject)`, so every `self.*` here resolves
against the live Backend instance at runtime (MPD client `self._cmd`, signals
`self.statusChanged`/`self._bridgeReady`, config, and DJ state initialised in
Backend.__init__).

Kept in Backend on purpose: the camelCase `dj*` @Property/@Slot methods — QML
binds to them and their notify signals (settingsChanged/statusChanged) live in
Backend. Those are thin; the ~2000 lines of logic that actually change during
DJ development now live HERE, isolated from the player.

⚠ Do not add Qt decorators (@Slot/@Property/Signal) in this file — it is a
plain-Python mixin, not a QObject. Qt-facing surface stays in Backend.
"""
from __future__ import annotations

from ampere.compat import cache_path
import copy
import json
import math
import os
import random
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QTimer

from . import bridge as djbridge
from . import verify as djverify
from .cues import CUES_VERSION as DJ_CUES_V
from ..intelligence import TrackFeatures, beam_sequence, transition_intent
from ..paths import HOST, PORT, MUSIC_ROOT
from ..mpdgateway import (close_mpd_client, open_temporary_mpd_client,
                          temporary_mpd_client)
from ..queue_mutations import QueueMutationResult
from .votes import DjVotesRepository
from .sets import save_set_snapshot


_READ_PLAYHEAD = object()


class DjPlannerMixin:
    def _dj_queue_mutation(self, owner, operation):
        """Run one structural DJ transaction through the shared owner."""
        coordinator = getattr(self, "_queue_mutations", None)
        if coordinator is None:  # focused domain adapters
            return QueueMutationResult(True, operation())
        result = coordinator.run(owner, operation)
        if not result.accepted:
            self._dj_log(
                f"{owner} deferred — queue owned by {result.active_owner}")
        return result

    def _dj_sticker(self, file, name, default=""):
        """Read planning evidence without conflating outage with absence."""
        result = self._stickers.raw_observed(file, name, default=default)
        self._dj_last_sticker_available = result.available
        if not result.available:
            self._dj_evidence_unavailable = True
        return result.value

    def _on_dj_tick(self):
        if self._dj_on and self._state == "play":
            self.refreshStatus()

    @classmethod
    def _dj_key_label(cls, k):
        """joi_cues key int (0–11 major, 12+ minor, -1 none) →
        (musical name, Camelot code) — e.g. (Am, 8A).

        djcues.camelot indexes the tonic in semitones above A (its chroma
        bin 0 is 440 Hz = A), so convert to the C-based table + Camelot
        formula with +9. (This was off by 3 semitones before — every key
        chip and code the deck showed was wrong; _key_compat was immune
        because it only compares keys relatively.)"""
        if k is None or k < 0:
            return "", ""
        minor = int(k) >= 12
        tonic = (int(k) % 12 + 9) % 12          # semitones above A → above C
        name = cls._KEY_NAMES[tonic] + ("m" if minor else "")
        num = ((tonic * 7) % 12 + (4 if minor else 7)) % 12 + 1
        return name, f"{num}{'A' if minor else 'B'}"

    def _dj_votes(self):
        v = getattr(self, "_dj_votes_cache", None)
        if v is None:
            repository = DjVotesRepository(self.VOTES_PATH)
            self._dj_votes_repository = repository
            v = repository.load()
            self._dj_votes_cache = v
        return v

    def _dj_bars(self, a_bpm: float) -> int:
        """Bars for a mix bridge. AUTO targets ~DJ_MIX_TARGET_S seconds of
        ride at A's tempo, phrase-aligned to a multiple of 4 — a fixed 16
        bars is 51 s at 75 BPM (measured on his real sets; the 'fade out
        is too long' complaint) but only 22 s at 170. Duration is the
        experience, bars are just the phrasing."""
        if self._dj_mix_len == "8":
            return 8
        if self._dj_mix_len == "16":
            return 16
        bar_a = 4 * 60.0 / a_bpm if a_bpm > 0 else 2.0
        return min((4, 8, 12, 16),
                   key=lambda n: abs(n * bar_a - self.DJ_MIX_TARGET_S))

    def _dj_style_count(self, style_word):
        """Instrumentation (#5): tally how often each transition style
        actually fires, so double-drop/tempo-ride/mix/slam can be judged on
        real listening data instead of guesses. Persisted with the votes."""
        v = self._dj_votes()
        v["style_fires"][style_word] = v["style_fires"].get(style_word, 0) + 1
        self._dj_save_votes()

    def _dj_seam_sample(self, delta):
        """Record a seam loudness delta (incoming landing minus outgoing
        exit, RG-adjusted). The rolling distribution is what DJ_SEAM_DB
        should be tuned from (#16), not a round guess."""
        try:
            s = self._dj_votes()["seam_samples"]
            s.append(round(float(delta), 1))
            del s[:-200]
            self._dj_save_votes()
        except (ValueError, TypeError):
            pass

    def _dj_skip(self, k, reason):
        """Mark a pair as non-cutting AND remember why, so the deck can tell
        the user (#13) instead of DJ mode silently 'doing nothing'."""
        self._dj_bridge_done[k] = "skip"
        self._dj_last_skip = reason
        self._dj_log(f"prep {k} skip: {reason}")

    def _dj_save_votes(self):
        votes = self._dj_votes()
        repository = getattr(self, "_dj_votes_repository", None)
        if repository is None:
            repository = DjVotesRepository(self.VOTES_PATH)
            self._dj_votes_repository = repository
        if not repository.save(votes):
            if not getattr(self, "_dj_votes_save_failed", False):
                self.errorOccurred.emit(
                    "DJ feedback could not be saved — learning applies only "
                    "until Ampere closes; check storage permissions")
            self._dj_votes_save_failed = True
            return False
        self._dj_votes_save_failed = False
        return True

    @staticmethod
    def _dj_style_word(label):
        for w in ("tempo-ride", "mix", "slam", "cut"):
            if w in (label or ""):
                return w
        return "other"

    def _dj_style_penalty(self, style_word):
        """Repeated downvotes on a style raise its bar: +0.05 per down
        past two, capped at +0.2 on the cue-score thresholds. The grudge
        FADES: one down is forgiven per week since the style's last
        downvote, so a bad afternoon can't mute a style forever (the
        2026-07 sessions left slam+mix pinned at max penalty for good)."""
        v = self._dj_votes()
        downs = v["style_downs"].get(style_word, 0)
        ts = v["style_down_ts"].get(style_word, 0)
        if downs and ts:
            downs = max(0, downs - int((time.time() - ts) / (7 * 86400)))
        # Exact pair strikes and banned cue points already learn concrete
        # failures. Global feedback should be a nudge, not a style veto.
        return min(0.06, 0.02 * max(0, downs - 3))

    def _dj_vote_blocked(self, f1, f2):
        return self._dj_votes()["pairs"].get(f"{f1}|{f2}", 0) < 0

    def _dj_queue_title(self, file):
        for s in self._queue:
            if s.get("file") == file:
                return s.get("title") or os.path.basename(file)
        return os.path.basename(file) if file else ""

    def _dj_gain(self, rel):
        """ReplayGain track gain for a library-relative file (cached tag
        read) — makes stored cue levels comparable across songs."""
        g = self._dj_gain_cache.get(rel)
        if g is None:
            g = djbridge._track_gain(os.path.join(MUSIC_ROOT, rel))
            if len(self._dj_gain_cache) > 512:
                self._dj_gain_cache.clear()
            self._dj_gain_cache[rel] = g
        return g

    def _dj_ban_cue(self, file, side, t):
        """Carve a failed cut moment out of a song's cue table — the next
        plan re-reads the song and picks its next-best cue instead."""
        if not file or not t or t <= 0:
            return
        lst = (self._dj_votes()["cue_bans"]
               .setdefault(file, {}).setdefault(side, []))
        if all(abs(t - x) > 0.5 for x in lst):
            lst.append(round(float(t), 2))
            del lst[:-8]
        self._dj_cue_cache.pop(file, None)

    def _dj_nudge_cue(self, file, side):
        """Persist an explicit request to avoid the current cue point."""
        if side not in ("in", "out") or not file:
            return False
        cues = self._dj_cues(file)
        if not cues:
            return False
        cue_time = self._dj_pick(cues, side)
        if cue_time is None:
            self.errorOccurred.emit(
                "No other strong point in that song — it'll crossfade there")
            return False
        self._dj_ban_cue(file, side, cue_time)
        saved = self._dj_save_votes()
        # Re-plan the upcoming transitions with the new cue in play even when
        # storage is temporarily unavailable; the save warning explains that
        # the learning then lasts only for this session.
        self._dj_plan_key = None
        self._dj_bridge_done.clear()
        self.refreshStatus()
        self.statusChanged.emit()
        if saved:
            self.errorOccurred.emit(
                "Shifted — the set now uses this song's "
                + ("next drop" if side == "in" else "next exit"))
        return saved

    def _dj_reset(self):
        """Acquire reset authority off Qt's thread before cleanup."""
        if getattr(self, "_dj_reset_busy", False):
            self._dj_reset_request_pending = True
            self._dj_reset_generation += 1
            return True
        self._dj_reset_busy = True
        self._dj_reset_request_pending = False
        self._dj_reset_generation = \
            getattr(self, "_dj_reset_generation", 0) + 1
        generation = self._dj_reset_generation

        def work():
            status = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=5,
                        registry=self._workers) as cli:
                    status = cli.status()
            except Exception:
                status = None
            self._djResetReady.emit({
                "generation": generation, "status": status,
            })

        if self._start_worker(work, name="ampere-dj-reset"):
            return True
        self._on_dj_reset_ready({
            "generation": generation, "status": None,
        })
        return False

    def _on_dj_reset_ready(self, payload):
        if not isinstance(payload, dict):
            return False
        if payload.get("generation") != self._dj_reset_generation:
            self._dj_reset_busy = False
            return self._launch_pending_dj_reset()
        self._dj_reset_busy = False
        playhead = djverify.validate_playhead(payload.get("status"))
        if not playhead.conclusive:
            self._dj_reset_pending = True
            self._dj_log("reset deferred — playhead unavailable")
            return False
        result = self._apply_dj_reset(playhead)
        self._launch_pending_dj_reset()
        return result

    def _launch_pending_dj_reset(self):
        pending = getattr(self, "_dj_reset_request_pending", False)
        self._dj_reset_request_pending = False
        if not pending:
            return False
        return self._dj_reset()

    def _apply_dj_reset(self, playhead):
        """Leave no trace after worker-verified playhead publication."""
        def cleanup():
            cur_sid = playhead.song_id
            keep_b = (self._dj_bridges[cur_sid][1]
                      if cur_sid in self._dj_bridges else -1)
            complete = True
            for bid in list(self._dj_bridges):
                complete = bool(
                    self._write_once("deleteid", bid, quiet=True)) and complete
            for sid in list(self._dj_ranged):
                if sid == keep_b:
                    continue
                complete = bool(
                    self._write("rangeid", sid, ":", quiet=True)) and complete
            return complete, keep_b

        mutation = self._dj_queue_mutation("dj-reset", cleanup)
        if not mutation.accepted:
            self._dj_reset_pending = True
            self._dj_schedule_reset_retry()
            return False
        complete, keep_b = mutation.value
        if not complete:
            self._dj_reset_pending = True
            self._dj_log("reset cleanup incomplete — retaining state for retry")
            self._dj_schedule_reset_retry()
            return False
        self._dj_reset_pending = False
        self._dj_gen += 1
        self._dj_cut_at = 0.0
        self._dj_plan_key = None
        self._dj_render_key = None   # never leave the pipeline wedged
        self._dj_active = False
        self._dj_next_style = ""
        self._dj_next_reason = ""
        # ending mid-mix: the playing bridge can't be deleted, and it ends
        # on B's build — B's range must SURVIVE or B restarts from 0:00
        # right after its own build played (audible double-intro)
        self._dj_bridges.clear()
        self._dj_bridge_done.clear()
        self._dj_ranged.clear()
        self._apply_automix()
        return True

    def _dj_schedule_reset_retry(self):
        if (not getattr(self, "_dj_reset_pending", False)
                or getattr(self, "_dj_reset_busy", False)
                or getattr(self, "_dj_reset_retry_armed", False)):
            return
        self._dj_reset_retry_armed = True

        def retry():
            self._dj_reset_retry_armed = False
            if getattr(self, "_dj_reset_pending", False):
                self._dj_reset()

        QTimer.singleShot(0, retry)

    def _dj_sweep_stale(self, status=_READ_PLAYHEAD):
        """One-time on connect: clear ranges on every queued song except the
        playing one. A crash with DJ mode on can strand entry:exit slices in
        MPD's saved state — songs would mysteriously start mid-way."""
        if self._dj_swept:
            return
        first_attempt = not getattr(self, "_dj_sweep_attempted", False)
        self._dj_sweep_attempted = True
        if self._dj_on and first_attempt:
            # the first plan after a cold start can decide on half-warmed
            # caches and lock the in-flight pair unplanned — one forced
            # replan once everything has settled closes that window
            def _replan():
                self._dj_plan_key = None
                self._dj_cue_cache.clear()
                self.refreshStatus()
            QTimer.singleShot(8000, _replan)
        if status is _READ_PLAYHEAD:
            # Queue mutations reconcile synchronously, but playhead reads do
            # not belong on Qt's thread. Ask the existing paired queue/status
            # worker to return authoritative evidence on its next publication.
            self._dj_log("stale-range sweep deferred — awaiting worker playhead")
            request = getattr(self, "_request_queue_refresh", None)
            if callable(request):
                request()
            return
        playhead = djverify.validate_playhead(status)
        if not playhead.conclusive:
            self._dj_log("stale-range sweep deferred — playhead unavailable")
            return
        cur_id = playhead.song_id
        def cleanup():
            complete = True
            for s in self._queue:
                sid = s.get("id", -1)
                if sid < 0 or sid == cur_id:
                    continue
                if s.get("file", "").startswith("/"):
                    # Stranded bridge deletion is relative queue mutation:
                    # never replay an ambiguous reply.
                    ok = self._write_once("deleteid", sid, quiet=True)
                else:
                    # Range clearing is an absolute setter and may retry.
                    ok = self._write("rangeid", sid, ":", quiet=True)
                complete = bool(ok) and complete
            return complete

        mutation = self._dj_queue_mutation("dj-stale-sweep", cleanup)
        if not mutation.accepted:
            return
        complete = bool(mutation.value)
        self._dj_swept = complete
        if not complete:
            self._dj_log("stale-range sweep incomplete — retrying on next queue refresh")

    def _dj_log(self, msg):
        """Append one line to the DJ decision log (~/.cache/ampere/dj.log).
        The planner runs silent and headless — when a set refuses to slice
        or mix, this file is the only witness. Rotates at ~512 KB."""
        try:
            p = cache_path('dj.log')
            if os.path.exists(p) and os.path.getsize(p) > 512 * 1024:
                os.replace(p, p + ".1")
            with open(p, "a") as fh:
                fh.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _dj_cues(self, file):
        """Parsed joi_cues for a file (memoized). None = not scored yet —
        the file joins the scanner's priority lane and the miss is cached
        briefly so a busy status loop doesn't hammer stickers."""
        if not file:
            return None
        hit = self._dj_cue_cache.get(file)
        if hit is not None:
            val, ts = hit
            if val is not None or time.monotonic() - ts < 20:
                return val
        if file.startswith("/"):
            return None            # bridges/absolute paths carry no cues
        val = None
        available = True
        try:
            raw = self._dj_sticker(file, "joi_cues")
            available = self._dj_last_sticker_available
            d = json.loads(raw)
            if d.get("v") == DJ_CUES_V:
                val = self._dj_censor_cues(file, d)
        except Exception:
            pass
        if not available:
            return None
        if len(self._dj_cue_cache) > 512:
            self._dj_cue_cache.clear()
        self._dj_cue_cache[file] = (val, time.monotonic())
        if val is None and self._dj_on:
            if file not in self._dj_prio:
                self._dj_prio.append(file)
            self._start_dj_scan(sweep=False)
        return val

    def _dj_censor_cues(self, file, d):
        """Downvoted cuts are carved out of the cue table at read time —
        every consumer (planner, bridge prep, timed cuts, auditions) then
        naturally falls to the song's next-best cue. A song that runs out
        of cues on a side simply stops cutting there (soft crossfade)."""
        bans = self._dj_votes()["cue_bans"].get(file)
        if not bans:
            return d
        out = dict(d)
        for side in ("in", "out"):
            ts = bans.get(side)
            if ts:
                out[side] = [c for c in d.get(side, [])
                             if all(abs(c[0] - t) > self.DJ_CUE_BAN_WIN
                                    for t in ts)]
        return out

    def _dj_soft_pair(self, f1, f2):
        """Cross-top-genre hand-offs go the soft way (phrase-end exit +
        normal crossfade, never a slam or mix) on progressive journeys
        and B2B sets — deathcore does not hard-cut into a trap drop."""
        if self._dj_top(f1) == self._dj_top(f2):
            return False
        return self._dj_range == "progressive" or self._dj_b2b_active

    def _dj_transition_intent(self, f1, c1, f2, c2):
        """Musical policy for a pair, independent of rendering mechanics."""
        songs = {e["song"]["file"]: e["song"] for e in self._search_index
                 if e["song"].get("file") in (f1, f2)}

        def energy(f):
            # This runs in the status/planning hot path.  _energies() is a
            # whole-library sticker_find (4k+ rows in the live library), so
            # using it here froze the GUI merely to obtain two values.
            try:
                return float(self._dj_sticker(f, "joi_energy"))
            except Exception:
                return None

        def feature(f, d):
            s = songs.get(f, {})
            vocal = max((c[3] for side in ("in", "out")
                         for c in (d or {}).get(side, []) if len(c) > 3),
                        default=float((d or {}).get("voc", 0.0) or 0.0))
            q = max((c[1] for side in ("in", "out")
                     for c in (d or {}).get(side, [])), default=0.0)
            return TrackFeatures(f, artist=s.get("artist", ""),
                                 title=s.get("title", ""),
                                 album=s.get("album", ""),
                                 bpm=float((d or {}).get("bpm", 0) or 0),
                                 energy=energy(f),
                                 key=int((d or {}).get("key", -1)),
                                 cue_quality=q, vocal=vocal)
        a, b = feature(f1, c1), feature(f2, c2)
        kc = self._key_compat01(a.key, b.key) \
            if a.key >= 0 and b.key >= 0 else .5
        return transition_intent(a, b, kc)

    def _dj_album_segue(self, cur, nxt):
        """Never slice a gapless album pair — a hot tail (joi_taildb) runs
        straight into the album-next track."""
        if not cur.get("album") or cur.get("album") != nxt.get("album"):
            return False
        try:
            raw = self._dj_sticker(
                cur.get("file", ""), "joi_taildb")
            return float(raw) >= -21.0
        except Exception:
            return False

    def _dj_pick(self, cues, kind, after=0.0):
        """Choose a cue time, or None. Entries take the EARLIEST of the
        near-best (land on THE drop, not a later re-drop). Curated exits
        take the LATEST strong one — play the song properly, cut before the
        outro; all-in exits take the hottest moment."""
        conf_min, in_min, out_min = self.DJ_GATES[self._dj_level]
        if not cues or cues.get("conf", 0) < conf_min:
            return None
        thr = in_min if kind == "in" else out_min
        valid = [(c[0], c[1]) for c in (cues.get(kind) or [])
                 if c[1] >= thr and c[0] > after]
        if not valid:
            return None
        if kind == "in":
            best = max(s for _, s in valid)
            return min(t for t, s in valid if s >= 0.85 * best)
        if self._dj_level != "wild":
            return max(t for t, _ in valid)   # play the song properly
        return max(valid, key=lambda c: c[1])[0]  # wild: hottest moment

    def _dj_slam_entries(self, c2, entry2, bpm2, abs2, b_len):
        """Ordered entry candidates for a SLAM, best first. A slam must land
        on the hardest drop (his mandate), so lead with djverify's drop-
        refined point, then the original cue, then other strong in-cues as
        fallbacks. The prep loop renders+verifies each and takes the first
        that lands. Every value is a real entry time in B."""
        cands = []
        try:
            ref, _imp = djverify.refine_entry(abs2, entry2, bpm2, b_len)
            cands.append(round(float(ref), 3))
        except Exception:
            pass
        cands.append(round(float(entry2), 3))
        for c in sorted((c for c in (c2.get("in") or []) if len(c) >= 2),
                        key=lambda c: -c[1])[:3]:
            cands.append(round(float(c[0]), 3))
        out = []
        for e in cands:                       # dedupe within ~50 ms, keep order
            if e > 0 and not any(abs(e - x) < 0.05 for x in out):
                out.append(e)
        return out or [round(float(entry2), 3)]

    def _dj_plan(self):
        """(Re)decide the upcoming transition. Runs on every status refresh,
        keyed by (current id, next id) so it's a no-op until something
        actually changes (skip, reorder, new song)."""
        if not self._dj_on:
            return
        pos = self._queue_pos
        cur = self._queue[pos] if 0 <= pos < len(self._queue) else None
        if not cur:
            return
        # coherence guard: the queue CACHE can lag MPD during churn
        # (startup sweep deletions, splices) — planning against a
        # misindexed list burned a whole song's lead time once. If the
        # cached row at MPD's position isn't MPD's current song id,
        # resync and plan on the next pass.
        if (self._cur_songid >= 0 and cur.get("id", -1) != self._cur_songid
                and time.monotonic() - self._dj_resync_ts > 1.0):
            self._dj_resync_ts = time.monotonic()
            self._dj_plan_key = None
            self._dj_log(f"queue cache behind MPD (cached id "
                         f"{cur.get('id')} != songid {self._cur_songid}) "
                         f"— resyncing")
            self._request_queue_refresh()
            return
        nxt = self._queue[pos + 1] if pos + 1 < len(self._queue) else None
        cur_id = cur.get("id", -1)
        nxt_id = nxt.get("id", -1) if nxt else -1

        # ---- bridge lifecycle -------------------------------------------
        qids = {s.get("id", -1) for s in self._queue}
        for bid in list(self._dj_bridges):
            if bid not in qids:
                self._dj_bridges.pop(bid, None)
                continue
            bpos = next((s.get("pos", -1) for s in self._queue
                         if s.get("id") == bid), -1)
            if 0 <= bpos < pos:
                # the mix played out (or was skipped past) — drop it, and
                # free the pair so repeat-all laps can mix again
                mutation = self._dj_queue_mutation(
                    "dj-lifecycle",
                    lambda bid=bid: self._write_once(
                        "deleteid", bid, quiet=True))
                if not mutation.accepted or not mutation.value:
                    continue
                a_id, b_id, _lbl = self._dj_bridges.pop(bid)
                self._dj_bridge_done.pop((a_id, b_id), None)
                fa, fb, ca, cb = self._dj_pair_files.pop(
                    (a_id, b_id), ("", "", 0.0, 0.0))
                self._dj_last_trans = {"label": _lbl, "a": fa, "b": fb,
                                       "ca": ca, "cb": cb,
                                       "aT": self._dj_queue_title(fa),
                                       "bT": self._dj_queue_title(fb)}
                self._dj_log_transition(_lbl, a=fa, b=fb)
            elif bpos > pos:
                # bridges are invisible in the queue UI — a drag/insert can
                # cross one unknowingly. A mix only makes sense flanked by
                # the exact pair it was rendered for; if a queue edit broke
                # that, drop it and let the planner re-decide the new
                # neighbors. (The playing bridge is left alone — deleting
                # it mid-transition would hard-skip.)
                a_id, b_id, _lbl = self._dj_bridges[bid]
                left = (self._queue[bpos - 1].get("id", -1)
                        if bpos > 0 else -1)
                right = (self._queue[bpos + 1].get("id", -1)
                         if bpos + 1 < len(self._queue) else -1)
                if left != a_id or right != b_id:
                    mutation = self._dj_queue_mutation(
                        "dj-lifecycle",
                        lambda bid=bid: self._write_once(
                            "deleteid", bid, quiet=True))
                    if not mutation.accepted or not mutation.value:
                        continue
                    self._dj_bridges.pop(bid, None)
                    self._dj_bridge_done.pop((a_id, b_id), None)
                    self._dj_log(f"bridge {(a_id, b_id)} orphaned by "
                                 f"queue edit — dropped")
        for k in [k for k in self._dj_bridge_done
                  if k[0] not in qids or k[1] not in qids]:
            self._dj_bridge_done.pop(k, None)

        # ranges must not linger on songs that already played (repeat-all
        # loops them back around sliced) or that got reordered away —
        # but a planned mix protects its pair (B sits past the bridge)
        protected = {cur_id, nxt_id}
        for a_id, b_id, _lbl in self._dj_bridges.values():
            protected |= {a_id, b_id}
        for sid in [s for s in self._dj_ranged if s not in protected]:
            mutation = self._dj_queue_mutation(
                "dj-lifecycle",
                lambda sid=sid: self._write(
                    "rangeid", sid, ":", quiet=True))
            if mutation.accepted and mutation.value:
                self._dj_ranged.pop(sid, None)

        key = (cur_id, nxt_id)
        # a mix two steps out still needs prepping even when the pair is
        # unchanged, so prep runs before the plan-key short-circuit
        self._dj_prepare_bridge()
        if key == self._dj_plan_key:
            return
        self._dj_gen += 1          # cancel any armed exit timer

        # the mix itself is playing: B is pre-arranged, knobs stay ours
        if cur_id in self._dj_bridges:
            self._dj_cut_at = 0.0
            self._dj_next_style = ""
            self._dj_plan_key = key
            self._dj_configure_transition(True, 0)
            return
        # the mix is next: hand-off into it is a pre-cut seam
        if nxt_id in self._dj_bridges:
            c_end = cur.get("rangeEnd", 0.0)
            self._dj_cut_at = (c_end - cur.get("rangeStart", 0.0)
                               if c_end else 0.0)
            self._dj_next_style = self._dj_bridges[nxt_id][2]
            self._dj_plan_key = key
            self._dj_configure_transition(True, 0)
            return

        self._dj_evidence_unavailable = False
        cur_cues = self._dj_cues(cur.get("file", ""))
        nxt_cues = self._dj_cues(nxt.get("file", "")) if nxt else None
        if self._dj_evidence_unavailable:
            self._dj_plan_key = None
            self._dj_log("plan deferred — musical evidence unavailable")
            return
        # a side still waiting on the scanner keeps the plan open — replan
        # every refresh until its cues land (the miss-cache keeps it cheap)
        pending = ((cur_cues is None
                    and not cur.get("file", "").startswith("/"))
                   or (nxt is not None and nxt_cues is None
                       and not nxt.get("file", "").startswith("/")))
        self._dj_plan_key = None if pending else key

        # incoming side: slice the queued next song to entry:exit while MPD
        # still allows it. Its exit is fixed HERE, while it's still queued —
        # once it plays, the range can't be touched.
        entry = exit_t = None
        mixed_after = any(a == nxt_id
                          for a, _b, _l in self._dj_bridges.values())
        if nxt is not None and mixed_after:
            # a planned mix owns this song's exit — don't re-slice it
            entry = self._dj_ranged.get(nxt_id, (0.0, 0.0))[0] or None
            exit_t = self._dj_ranged.get(nxt_id, (0.0, 0.0))[1] or None
        album_segue = False
        if nxt is not None and not mixed_after and not self._single:
            album_segue = self._dj_album_segue(cur, nxt)
        if self._dj_evidence_unavailable:
            self._dj_plan_key = None
            self._dj_log("plan deferred — album evidence unavailable")
            return
        if (nxt is not None and not mixed_after and not self._single
                and not album_segue):
            entry = self._dj_pick(nxt_cues, "in")
            intent = self._dj_transition_intent(
                cur.get("file", ""), cur_cues,
                nxt.get("file", ""), nxt_cues)
            if self._dj_evidence_unavailable:
                self._dj_plan_key = None
                self._dj_log("plan deferred — energy evidence unavailable")
                return
            self._dj_next_reason = intent.reason
            if intent.style == "soft":
                entry = None
            # cross-genre hand-offs (progressive journeys, B2B) are never
            # a slam — they go the soft way
            if entry is not None and self._dj_soft_pair(
                    cur.get("file", ""), nxt.get("file", "")):
                entry = None
            # its own exit: never leave less than 25 s of actual song —
            # and an ANTHEM is never cut short at all
            if nxt.get("file", "") in self._dj_anthems:
                exit_t = None
            else:
                exit_t = self._dj_pick(nxt_cues, "out",
                                       after=(entry or 0.0) + 25.0)
            if entry is not None or exit_t is not None:
                spec = (f"{entry or 0:.2f}:"
                        + (f"{exit_t:.2f}" if exit_t else ""))
                try:
                    mutation = self._dj_queue_mutation(
                        "dj-plan-range",
                        lambda: self._write("rangeid", nxt_id, spec))
                    if not mutation.accepted or not mutation.value:
                        raise RuntimeError("range update failed")
                    self._dj_ranged[nxt_id] = (entry or 0.0, exit_t or 0.0)
                except Exception:
                    entry = exit_t = None
        if nxt is not None:
            t2 = nxt.get("title", "") or os.path.basename(nxt.get("file", ""))
            self._dj_next_style = (f"slam into {t2}" if entry is not None
                                   else f"cut + fade into {t2}" if exit_t
                                   else "")
        else:
            self._dj_next_style = ""
            self._dj_next_reason = ""
        self._dj_log(f"plan {key} pend={pending} "
                     f"cues={cur_cues is not None}/{nxt_cues is not None} "
                     f"entry={entry} exit={exit_t}")

        # outgoing side: the current song's range end was fixed when IT was
        # queued; the first song after enabling gets a timed cut instead —
        # but only into a real entry (no truncating into a plain intro).
        # CLOCK RULE: a sliced song reports elapsed/duration relative to
        # its slice, while cues are absolute file seconds — everything
        # user-facing here (djCutAt, timers) lives in the PLAYED timeline,
        # so subtract the slice start (taken from MPD's own range report,
        # which survives app restarts; our bookkeeping doesn't).
        cur_start = cur.get("rangeStart", 0.0)
        cur_end = cur.get("rangeEnd", 0.0)
        if cur_end:
            self._dj_cut_at = cur_end - cur_start
        elif entry is not None and self._state == "play":
            t = self._dj_pick(cur_cues, "out",
                              after=cur_start + self._elapsed + 8.0)
            self._dj_cut_at = (t - cur_start) if t else 0.0
            if t:
                gen = self._dj_gen
                # the fader ride needs ~150 ms to reach silence — lead the
                # timer by that much so the audible cut lands ON the cue's
                # beat, not a sixteenth after it
                QTimer.singleShot(
                    max(0, int((t - cur_start - self._elapsed) * 1000) - 150),
                    lambda: self._dj_fire(gen, cur.get("id", -1)))
        else:
            self._dj_cut_at = 0.0
        self._dj_arm_redrop(cur, cur_cues, cur_start, cur_end)

        # transition knobs: a DJ hand-off owns them (MixRamp would overlap
        # against the file's REAL intro/outro, not the sliced one). Slam
        # cuts run crossfade 0; close BPMs earn a one-bar blend; an exit
        # into a plain intro keeps the normal crossfade (a range end counts
        # as a natural track end, so it still fades).
        active = entry is not None or self._dj_cut_at > 0
        if active:
            if entry is not None:
                # raw (unrendered) slam fallback: never a zero-crossfade
                # seam — one second of cross keeps even the fallback clean
                xf = 1
                a = (cur_cues or {}).get("bpm", 0)
                b = (nxt_cues or {}).get("bpm", 0)
                if a > 0 and b > 0 and max(a, b) / min(a, b) <= 1.042:
                    xf = max(2, min(6, round(4 * 60.0 / b)))
            else:
                xf = self._xfade_base
            self._dj_configure_transition(True, xf)
        elif self._dj_active:
            self._dj_configure_transition(False, self._xfade_base)

    def _dj_configure_transition(self, active, crossfade):
        """Schedule DJ ownership; Backend publishes it after verification."""
        accepted = (self._configure_transitions(
            mixramp_delay=None, crossfade=crossfade, dj_active=active)
            if active else self._apply_automix(dj_active=active))
        if not accepted:
            # The queue/range plan may still be valid, but its daemon knobs
            # must be retried on the next planner refresh.
            self._dj_plan_key = None
        return accepted

    def _dj_fire(self, gen, song_id):
        if gen != self._dj_gen:
            return
        self._request_delayed_status("dj-timed-cut", gen, song_id)

    def _dj_apply_delayed_status(self, kind, generation, snapshot, context):
        """Apply a fresh delayed-action verification on Qt's thread."""
        if kind == "dj-cut-now-arm":
            if (generation != self._dj_gen or snapshot is None
                    or not snapshot.valid):
                self._dj_cutnow_armed = False
                if snapshot is None or not snapshot.conclusive:
                    self.errorOccurred.emit(
                        "Cut Now could not confirm the current song — try again")
                return
            try:
                bpm = float(context.get("bpm", 0.0))
                beat_zero = float(context.get("beatZero", 0.0))
                cur_start = float(context.get("rangeStart", 0.0))
                song_id = int(context.get("songId", -1))
            except (TypeError, ValueError):
                bpm = beat_zero = 0.0
                cur_start, song_id = 0.0, -1
            if (not math.isfinite(bpm) or bpm <= 0
                    or not math.isfinite(beat_zero)
                    or not math.isfinite(cur_start)):
                self._dj_cutnow_armed = False
                self._dj_log_transition(
                    "cut now", a=str(context.get("title", "")))
                self._dj_fader_next()
                return
            bar = 4 * 60.0 / bpm
            abs_t = cur_start + snapshot.elapsed
            k = math.ceil((abs_t - beat_zero) / bar + 0.02)
            target = beat_zero + k * bar
            delay = (target - abs_t) * 1000.0
            if delay < 120:
                delay += bar * 1000.0

            def fire():
                if generation != self._dj_gen or self._state != "play":
                    self._dj_cutnow_armed = False
                    return
                self._request_delayed_status(
                    "dj-cut-now", generation, song_id, {
                        "expectedElapsed": (
                            snapshot.elapsed + delay / 1000.0),
                        "tolerance": max(0.75, min(2.0, bar * 0.5)),
                        "title": str(context.get("title", "")),
                    })

            QTimer.singleShot(max(0, int(delay) - 150), fire)
            return
        if kind == "dj-cut-now":
            self._dj_cutnow_armed = False
        if (generation != self._dj_gen or snapshot is None
                or not snapshot.valid):
            return
        if kind == "dj-timed-cut":
            if (self._dj_on and self._dj_cut_at > 0
                    and snapshot.elapsed >= self._dj_cut_at - 2.0):
                self._dj_log_transition(
                    "timed cut", a=self._song.get("title", ""))
                self._dj_fader_next()
            return
        if kind == "dj-cut-now":
            try:
                expected = float(context.get("expectedElapsed", -1.0))
                tolerance = float(context.get("tolerance", 0.0))
            except (TypeError, ValueError):
                return
            if abs(snapshot.elapsed - expected) <= tolerance:
                self._dj_log_transition(
                    "cut now", a=str(context.get("title", "")))
                self._dj_fader_next()
            return
        if kind == "dj-redrop":
            try:
                song_id = int(context.get("songId", -1))
                expected = float(context.get("expectedElapsed", -1.0))
                seek_to = float(context.get("seekTo", 0.0))
                entry = float(context.get("entry", 0.0))
            except (TypeError, ValueError):
                return
            if (not self._dj_on or self._state != "play"
                    or song_id in self._dj_redropped):
                return
            if abs(snapshot.elapsed - expected) > 2.0:
                return
            self._dj_redropped.add(song_id)
            self._dj_log(f"re-drop {song_id} -> {entry:.1f}s")
            self._dj_fader_next(
                action=lambda: self._seek_current_once(seek_to))

    def _dj_fader_next(self, action=None):
        """Move at a cue with the same mix-time fade as every manual skip.

        This must use PipeWire stream volume.  MPD volume is applied before
        its output buffer, so a skip flushes the down-ramp and can mute the
        beginning of B—the measured source of the DJ transition stutter.
        """
        move = action if action is not None else (
            lambda: self._write_once("next"))
        self._dj_log(f"output-faded cut at vol {max(0, self._volume)}")
        self._transition_fader.move(
            move,
            smooth=self._volume > 0 and self._state == "play",
        )

    def _dj_arm_redrop(self, cur, cur_cues, cur_start, cur_end):
        """WILD only: occasionally replay the current song's own drop —
        at a strong exit cue well past the drop, ride the fader and seek
        back to the entry cue, once per song. Deterministic per song id
        so replans don't re-roll the dice."""
        cur_id = cur.get("id", -1)
        if (self._dj_level != "wild" or cur_id < 0
                or cur_id in self._dj_redropped or not cur_cues):
            return
        if cur_id % 5 >= 2:            # ~40% of songs earn one
            return
        ins = [c[0] for c in (cur_cues.get("in") or []) if c[1] >= 0.6]
        outs = [c[0] for c in (cur_cues.get("out") or []) if c[1] >= 0.5]
        if not ins or not outs:
            return
        e = min(ins)
        end_abs = cur_end if cur_end else cur_cues.get("dur", 0.0)
        rd = min((t for t in outs
                  if t >= e + 45.0 and t <= end_abs - 40.0), default=None)
        if rd is None:
            return
        delay = (rd - cur_start - self._elapsed) * 1000
        if delay < 500:
            return
        gen = self._dj_gen
        seek_to = max(0.0, e - cur_start)   # CLOCK RULE: slice-relative

        def fire():
            if (gen != self._dj_gen or not self._dj_on
                    or self._state != "play"
                    or cur_id in self._dj_redropped):
                return
            self._request_delayed_status("dj-redrop", gen, cur_id, {
                "songId": cur_id,
                "expectedElapsed": rd - cur_start,
                "seekTo": seek_to,
                "entry": e,
            })

        QTimer.singleShot(max(0, int(delay) - 150), fire)

    def _dj_log_transition(self, style, a="", b=""):
        """Append one hand-off to the session's set history (crash-safe:
        rewritten to disk on every transition)."""
        if not self._dj_set_log:
            return
        self._dj_set_log["transitions"].append(
            {"style": style, "a": a, "b": b, "t": round(time.time(), 1)})
        self._dj_save_set()

    def _dj_save_set(self):
        if not self._dj_set_log:
            return True
        snapshot = copy.deepcopy(self._dj_set_log)
        snapshot.setdefault("started", time.time())
        request = {
            "snapshot": snapshot,
            "directory": Path(cache_path('sets')),
        }
        lock = self._dj_set_save_lock
        with lock:
            if self._dj_set_save_busy:
                self._dj_set_save_pending = request
                return True
            self._dj_set_save_busy = True
        if self._start_worker(
                self._dj_set_save_worker, args=(request,),
                name="ampere-dj-set-save", durable=True):
            return True
        with lock:
            self._dj_set_save_busy = False
        self._on_dj_set_save_ready(False)
        return False

    def _dj_set_save_worker(self, request):
        """Drain latest snapshots so shutdown cannot strand a pending save."""
        success = False
        while request is not None:
            success = save_set_snapshot(
                request["directory"], request["snapshot"])
            with self._dj_set_save_lock:
                request, self._dj_set_save_pending = (
                    self._dj_set_save_pending, None)
                if request is None:
                    self._dj_set_save_busy = False
        self._djSetSaveReady.emit(success)

    def _dj_prepare_bridge(self):
        self._dj_evidence_unavailable = False
        if self._dj_render_key is not None:
            # watchdog (#1): a render worker MUST emit _bridgeReady, which
            # clears this slot in _on_bridge_ready. If the process was killed
            # mid-render or the signal never fired, the slot would wedge
            # EVERY future transition into soft crossfade with no visible
            # symptom. Force it open once the render has plainly overrun the
            # ffmpeg timeout (renders are single-slot, so nothing races here).
            started = getattr(self, "_dj_render_started", 0.0)
            if time.monotonic() - started > djbridge.FFMPEG_TIMEOUT + 30:
                self._dj_log(f"render slot {self._dj_render_key} wedged "
                             f">{djbridge.FFMPEG_TIMEOUT + 30:.0f}s — "
                             f"forcing it open")
                self._dj_render_key = None
            else:
                return
        if not self._dj_bridge_ok or not self._dj_on or self._single:
            return
        pos = self._queue_pos
        upcoming = [s for s in self._queue[pos + 1: pos + 6]
                    if s.get("id", -1) not in self._dj_bridges]
        if len(upcoming) < 2:
            return
        n1, n2 = upcoming[0], upcoming[1]
        k = (n1.get("id", -1), n2.get("id", -1))
        if k in self._dj_bridge_done:
            return
        f1, f2 = n1.get("file", ""), n2.get("file", "")
        c1, c2 = self._dj_cues(f1), self._dj_cues(f2)
        if self._dj_evidence_unavailable:
            return
        if c1 is None or c2 is None:
            return                 # cues still scoring; retry next refresh
        # gates shared by both transition kinds — plus: progressive
        # journeys never cut across top-level genres, and gapless album
        # pairs stay untouched
        album_segue = self._dj_album_segue(n1, n2)
        if self._dj_evidence_unavailable:
            return
        if album_segue:
            self._dj_skip(k, "gapless album pair — left whole")
            return
        if self._dj_soft_pair(f1, f2):
            self._dj_skip(k, "cross-genre hand-off goes the soft way")
            return
        if f1 in self._dj_anthems:
            self._dj_skip(k, "this song is an anthem — played out, never cut")
            return
        if self._dj_vote_blocked(f1, f2):
            self._dj_skip(k, "you downvoted this pair three times")
            return
        n1_entry = self._dj_ranged.get(k[0], (0.0, 0.0))[0]
        exit1 = self._dj_pick(c1, "out", after=n1_entry + 25.0)
        entry2 = self._dj_pick(c2, "in")
        if exit1 is None or entry2 is None:
            side = ("no strong exit in the outgoing song" if exit1 is None
                    else "no strong drop in the incoming song")
            self._dj_skip(k, f"soft crossfade — {side}")
            return
        # loudness seam gate: B must LAND with comparable heat to A's exit
        # (RG-adjusted absolute cue levels — cue scores only rank moments
        # within one song). A much quieter landing dies on the floor no
        # matter how good both cues are: re-pick a hotter entry, else hand
        # off soft. Levels exist on lv-era stickers only — older ones pass.
        lv_a = next((c[2] for c in c1.get("out", [])
                     if len(c) > 2 and abs(c[0] - exit1) < 0.05), None)
        lv_b = next((c[2] for c in c2.get("in", [])
                     if len(c) > 2 and abs(c[0] - entry2) < 0.05), None)
        if lv_a is not None and lv_b is not None:
            ref = lv_a + self._dj_gain(f1)
            rg_b = self._dj_gain(f2)
            self._dj_seam_sample((lv_b + rg_b) - ref)   # tune DJ_SEAM_DB (#16)
            if (lv_b + rg_b) - ref < -self.DJ_SEAM_DB:
                _, in_min, _ = self.DJ_GATES[self._dj_level]
                ok = [c for c in c2.get("in", [])
                      if len(c) > 2 and c[1] >= in_min
                      and (c[2] + rg_b) - ref >= -self.DJ_SEAM_DB]
                if ok:
                    best = max(c[1] for c in ok)
                    entry2 = min(c[0] for c in ok if c[1] >= 0.85 * best)
                    self._dj_log(f"prep {k} seam-level repick: "
                                 f"entry -> {entry2}")
                else:
                    self._dj_skip(
                        k, f"incoming lands {(lv_b + rg_b) - ref:+.0f} dB "
                        f"below the outgoing — would die on the floor")
                    return
        bpm1, bpm2 = c1.get("bpm", 0), c2.get("bpm", 0)
        # per-track bass hand-off crossover (djcues' bcut): split each
        # pair below the region where BOTH tracks' low ends live
        bass_hz = min(c1.get("bcut", djbridge.BASS_SWAP_HZ),
                      c2.get("bcut", djbridge.BASS_SWAP_HZ))
        # the ladder: tempo-compatible earns the long mix; everything else
        # earns a rendered CLEAN slam (fader cross + loudness-matched
        # hand-off) — a raw seam is never the plan, only the fallback
        intent = self._dj_transition_intent(f1, c1, f2, c2)
        self._dj_next_reason = intent.reason
        if intent.style == "soft":
            self._dj_skip(k, intent.reason)
            return
        if intent.style == "blend" and not djbridge.mixable(bpm1, bpm2):
            self._dj_skip(k, intent.reason + " — tempos need a soft hand-off")
            return
        if intent.style == "blend" and self._dj_slam_only:
            self._dj_skip(k, intent.reason + " — punchy mode avoids long blends")
            return
        kind = ("slam" if intent.style == "slam" else "mix")
        bars = 0
        key_shift = 0            # kept 0 — never pitch B (see harmonic gate)
        k1, k2 = c1.get("key", -1), c2.get("key", -1)
        kc = self._key_compat01(k1, k2) if (k1 >= 0 and k2 >= 0) else None
        if kind == "mix":
            bars = self._dj_bars(bpm1)
            used, overlap = djbridge.plan_overlap(exit1, bpm1, entry2, bpm2,
                                                  bars)
            if used < 4 or overlap >= exit1 - n1_entry - 10.0:
                self._dj_skip(k, intent.reason + " — not enough phrase room")
                return
            elif kc is not None:
                # graded harmonic gate: a bass-swap mix overlaps the two
                # songs' tonal content for bars on end. A hard key CLASH
                # grates the whole way → slam; a MILD difference → shorter
                # blend. We do NOT pitch B into key: the bridge would carry
                # the shift but the real B song plays NATIVE at the drop, so
                # the key snaps back mid-phrase — audibly sudden, and the
                # rubberband pass also thins/quiets the seam. Rejected in
                # NOTES.md; harmonic mixing here is key-AWARENESS only.
                lbl = (f"{self._dj_key_label(k1)[1]}/"
                       f"{self._dj_key_label(k2)[1]}")
                if kc < 0.30:
                    self._dj_skip(k, f"{intent.reason} — key clash {lbl} "
                                  "needs a soft reset")
                    return
                elif kc < 0.55 and used > 8:
                    bars = 8
                    used, overlap = djbridge.plan_overlap(
                        exit1, bpm1, entry2, bpm2, bars)
                    if used < 4:
                        self._dj_skip(k, intent.reason
                                      + " — short blend has no phrase room")
                        return
                    else:
                        self._dj_log(f"prep {k} mild key diff {lbl} "
                                     f"(compat {kc:.2f}) — short 8-bar blend")
        # learned taste: a style he's downvoted repeatedly needs stronger
        # cues to run at all (pair-level vetoes were handled above)
        fold_p = djbridge.fold_bpm(bpm2, bpm1)
        style_w = ("slam" if kind == "slam" else
                   "tempo-ride" if djbridge._needs_ride(bpm1, fold_p)
                   else "mix")
        # slam-only means he ASKED for slams — the style penalty must not
        # veto the only style allowed, or the whole set silently degrades
        # to soft crossfades (this exact state shipped: slam_only on +
        # slam downvoted past the cap = every prep skipped)
        pen = self._dj_style_penalty(style_w)
        if self._dj_slam_only and style_w == "slam":
            pen = 0.0
        if pen > 0:
            sc_out_p = next((c[1] for c in c1.get("out", [])
                             if abs(c[0] - exit1) < 0.05), 0.0)
            sc_in_p = next((c[1] for c in c2.get("in", [])
                            if abs(c[0] - entry2) < 0.05), 0.0)
            _, in_min, out_min = self.DJ_GATES[self._dj_level]
            if sc_in_p < in_min + pen or sc_out_p < out_min + pen:
                self._dj_skip(k, f"you keep downvoting {style_w}s — "
                              f"this one wasn't strong enough to risk")
                return
        # vocal collision: two SIMULTANEOUS lead vocals sound like two radio
        # stations. The cue's 4th field is the vocal presence in the material
        # that plays into the bridge; only a mix where BOTH sides carry a
        # vocal can clash. Keep the stronger cut's vocal, duck the OTHER
        # deck's MID band (the vocal band) so one lead stays forward. A
        # heuristic detector, so it only ducks — never vetoes a transition.
        duck_a = duck_b = 0.0
        if kind == "mix":
            a_voc = next((c[3] for c in c1.get("out", [])
                          if len(c) > 3 and abs(c[0] - exit1) < 0.05), 0.0)
            b_voc = next((c[3] for c in c2.get("in", [])
                          if len(c) > 3 and abs(c[0] - entry2) < 0.05), 0.0)
            if a_voc > 0.35 and b_voc > 0.35:
                clash = min(a_voc, b_voc)
                amt = round(3.5 + 4.5 * clash, 1)          # ~5-7 dB
                a_sc = next((c[1] for c in c1.get("out", [])
                             if abs(c[0] - exit1) < 0.05), 0.0)
                b_sc = next((c[1] for c in c2.get("in", [])
                             if abs(c[0] - entry2) < 0.05), 0.0)
                if a_sc >= b_sc:
                    duck_b = amt
                else:
                    duck_a = amt
                self._dj_log(f"prep {k} two vocals (A {a_voc:.2f}/B {b_voc:.2f})"
                             f" — duck {'B' if duck_b else 'A'} mids {amt}dB")
        # slam exits: snap A's cut to a strong on-grid beat. The out-cue is
        # chosen to mix OUT gently (a low-energy spot) — for a slam that lands
        # the cut on a dead beat and A gets chopped mid-groove. Done AFTER the
        # cue-based lookups above (they need the original cue-aligned exit1).
        if kind == "slam":
            try:
                exit1 = djverify.refine_exit(os.path.join(MUSIC_ROOT, f1),
                                             exit1, bpm1)
            except Exception:
                pass
        variant = f"p{key_shift}" if key_shift else ""
        if duck_a or duck_b:
            variant += f"d{int(round(duck_a))}_{int(round(duck_b))}"
        out = djbridge.cache_path(f1, exit1, f2, entry2, bars, variant=variant)
        t1 = n1.get("title", "") or os.path.basename(f1)
        t2 = n2.get("title", "") or os.path.basename(f2)
        self._dj_render_key = k
        if len(self._dj_pair_files) > 64:
            # evict the oldest half (insertion order) — never the fresh key
            for kk in list(self._dj_pair_files)[:32]:
                self._dj_pair_files.pop(kk, None)
        # cut moments ride along so a downvote can ban this exact cut
        self._dj_pair_files[k] = (f1, f2, exit1, entry2)
        a_id, b_id = k
        abs1, abs2 = (os.path.join(MUSIC_ROOT, f1),
                      os.path.join(MUSIC_ROOT, f2))
        # instrumentation (#5): count how often each style actually fires,
        # so the exotic paths can be judged on real data, not guesses
        self._dj_style_count(style_w)
        self._dj_render_started = time.monotonic()   # watchdog clock (#1)
        if kind == "mix":
            ride = djbridge._needs_ride(bpm1, fold_p)
            keytag = f" (B {key_shift:+d} st into key)" if key_shift else ""
            if duck_a or duck_b:
                keytag += " (vocal duck)"
            self._dj_render_meta = (
                f"{used}-bar stretched mix into {t2}{keytag}" if ride
                else f"{used}-bar mix into {t2}{keytag}")

            def work():
                # any exception MUST still emit — the single-slot pipeline
                # (_dj_render_key) only unlocks in _on_bridge_ready, and a
                # silently dead worker would wedge every future transition
                try:
                    if out.exists():
                        ov = overlap
                    else:
                        ov, _ = djbridge.render(
                            abs1, exit1, bpm1, abs2, entry2, bpm2, bars,
                            out, t1, t2, bass_hz=bass_hz,
                            pitch_semitones=key_shift,
                            duck_a=duck_a, duck_b=duck_b)
                except Exception:
                    ov = 0.0
                # resume B a hair before its entry cue: the render's alimiter
                # lookahead + atrim clip ~LIMITER_LATENCY of real B off the
                # bridge tail (same mechanism the slam fix corrected), so
                # resuming at exactly entry2 skips that sliver = a seam tick.
                b_resume = (max(0.0, entry2 - djbridge.LIMITER_LATENCY)
                            if ov > 0 else entry2)
                self._bridgeReady.emit(a_id, b_id, str(out),
                                       exit1 - ov, b_resume,
                                       1.0 if ov > 0 else 0.0)
        else:
            b_len2 = float(n2.get("duration", 0) or 0)
            # aggression dial -> pre-drop hole (silence before the drop)
            hole = {"wild": 0.5, "classic": 0.25}.get(self._dj_level, 0.0)
            svar = variant + (f"h{int(hole * 100)}" if hole else "")
            self._dj_render_meta = (
                f"{'aggressive ' if hole else ''}slam into {t2}")

            def work():
                # A slam must hit the DROP, hard and on the beat. Build entry
                # candidates (hardest on-grid drop first, then the cue, then
                # other strong in-cues), render each, and VERIFY the actual
                # rendered audio — take the first that lands; if none do,
                # defer to the normal soft crossfade. This is the live
                # self-checking loop.
                try:
                    cands = self._dj_slam_entries(c2, entry2, bpm2, abs2,
                                                  b_len2)
                except Exception:
                    cands = [entry2]
                # Gate on the PLAIN slam (hole=0) to choose the entry — the
                # hole only adds leading silence, it never moves the drop
                # (render_slam returns identical pre/post), so it needs no
                # re-gating. Winner then gets the aggression hole applied.
                best = None                 # (o0, a_end, b_start, entry, passed)
                fb_hard = -99.0
                for e in cands[:3]:
                    o0 = djbridge.cache_path(f1, exit1, f2, e, bars,
                                             variant=variant)
                    try:
                        pre, post = djbridge.render_slam(
                            abs1, exit1, bpm1, abs2, e, bpm2, o0, t1, t2)
                    except Exception:
                        pre = post = 0.0
                    if pre <= 0:
                        continue
                    try:
                        v = djverify.verify_bridge(str(o0), pre, bpm2,
                                                   is_slam=True)
                    except Exception:
                        # Verification is the safety gate, not optional
                        # telemetry.  An analyzer failure must never promote
                        # ungraded audio into the live queue.
                        v = {"ok": False, "why": ["verify-error"],
                             "offset_ms": None, "hardness": None,
                             "clip": None}
                    self._dj_log(
                        f"verify {k} slam entry={e:.2f} off={v.get('offset_ms')}"
                        f"ms hard={v.get('hardness')}dB ok={v.get('ok')} "
                        f"{v.get('why')}")
                    passed = djverify.slam_verdict_ok(v)
                    cand = (o0, exit1 - pre, e + post, e, passed)
                    if passed:
                        best = cand
                        break
                    try:
                        fb_hard = max(fb_hard, float(v.get("hardness", -99.0)))
                    except (TypeError, ValueError):
                        pass
                if best is None:
                    # Rejected means rejected. A loud off-beat cut is still a
                    # bad cut, and silently splicing it destroyed trust in DJ
                    # mode. Fall back to the player's proven transition path.
                    self._dj_log(f"prep {k} no verified slam "
                                 f"(best hard={fb_hard:.1f}dB) -> soft "
                                 f"crossfade")
                    self._bridgeReady.emit(a_id, b_id, str(out),
                                           exit1, entry2, -1.0)
                    return
                o0, a_end, b_start, e, passed = best
                final = o0
                # only dramatize a slam that actually LANDED a hard drop — a
                # pre-drop hole before a weak fallback would sound broken
                if hole > 0 and passed:
                    of = djbridge.cache_path(f1, exit1, f2, e, bars,
                                             variant=svar)
                    try:
                        p2, _ = djbridge.render_slam(
                            abs1, exit1, bpm1, abs2, e, bpm2, of, t1, t2,
                            hole_beats=hole)
                        if p2 > 0:
                            final = of
                    except Exception:
                        pass
                # record the ACTUAL cut moment so a downvote bans it
                self._dj_pair_files[k] = (f1, f2, exit1, e)
                self._bridgeReady.emit(a_id, b_id, str(final),
                                       a_end, b_start, 1.0)

        self._dj_log(f"prep {k} render {kind} "
                     f"({self._dj_render_meta})")
        self._start_worker(work, name="ampere-dj-render")

    def _on_bridge_ready(self, a_id, b_id, path, a_end, b_start, ok):
        label = getattr(self, "_dj_render_meta", "")
        self._dj_render_key = None
        k = (a_id, b_id)
        if ok <= 0:
            self._dj_bridge_done[k] = "skip"
            if ok < 0:
                self._dj_log(f"bridge {k} verification rejected — soft crossfade")
            else:
                self._dj_log(f"bridge {k} render FAILED")
            return
        if not self._dj_on:
            self._dj_bridge_done[k] = "skip"
            return
        prior_a = self._dj_ranged.get(a_id)
        prior_b = self._dj_ranged.get(b_id)
        lease, rejected = self._queue_mutations.acquire("dj-bridge-splice")
        if lease is None:
            self._dj_bridge_done.pop(k, None)
            self._dj_plan_key = None
            self._dj_log(
                f"dj-bridge-splice deferred — queue owned by "
                f"{rejected.active_owner}")
            return

        args = (lease, a_id, b_id, path, a_end, b_start,
                prior_a, prior_b, label)
        if not self._start_worker(
                self._bridge_splice_worker, args=args,
                name="ampere-dj-bridge-splice"):
            lease.release()
            self._dj_bridge_done.pop(k, None)
            self._dj_plan_key = None
            self._dj_log(f"bridge {k} splice deferred — Ampere is closing")

    def _bridge_splice_worker(self, lease, a_id, b_id, path, a_end,
                              b_start, prior_a, prior_b, label):
        from .splice import splice_bridge

        payload = {
            "lease": lease, "aId": a_id, "bId": b_id, "label": label,
            "aEnd": a_end, "bStart": b_start,
            "priorA": prior_a, "priorB": prior_b,
            "state": "deferred", "frontier": None, "result": None,
        }
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15, registry=self._workers) as cli:
                def reconnect():
                    try:
                        close_mpd_client(cli)
                        cli.connect(HOST, PORT)
                        return True
                    except Exception:
                        return False

                def read_queue():
                    for attempt in (0, 1):
                        try:
                            return cli.playlistinfo()
                        except Exception:
                            if attempt or not reconnect():
                                return None

                def add_once(file, position):
                    try:
                        cli.addid(file, position)
                        return True
                    except Exception:
                        reconnect()
                        return False

                def set_range(song_id, spec):
                    for attempt in (0, 1):
                        try:
                            cli.rangeid(song_id, spec)
                            return True
                        except Exception:
                            if attempt or not reconnect():
                                return False

                def delete_once(song_id):
                    try:
                        cli.deleteid(song_id)
                        return True
                    except Exception:
                        reconnect()
                        return False

                info = read_queue()
                try:
                    status = cli.status()
                except Exception:
                    status = None
                frontier = djverify.validate_bridge_frontier(
                    info, status, a_id, b_id)
                payload["frontier"] = frontier
                if not frontier.conclusive:
                    payload["state"] = "deferred"
                elif not frontier.valid:
                    payload["state"] = "invalid"
                else:
                    result = splice_bridge(
                        initial_queue=info, a_id=a_id, b_id=b_id, path=path,
                        a_end=a_end, b_start=b_start, prior_a=prior_a,
                        prior_b=prior_b, add_once=add_once,
                        set_range=set_range, delete_once=delete_once,
                        read_queue=read_queue)
                    payload["result"] = result
                    payload["state"] = (
                        "committed" if result.committed else "failed")
        except Exception:
            payload["state"] = "deferred"
        self._bridgeSpliceReady.emit(payload)

    def _on_bridge_splice_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        lease = payload.get("lease")
        a_id = payload.get("aId", -1)
        b_id = payload.get("bId", -1)
        k = (a_id, b_id)
        try:
            state = payload.get("state")
            frontier = payload.get("frontier")
            if state == "deferred":
                self._dj_bridge_done.pop(k, None)
                self._dj_plan_key = None
                reason = getattr(frontier, "reason", "worker unavailable")
                self._dj_log(f"bridge {k} validation deferred ({reason})")
                return
            if state == "invalid":
                self._dj_bridge_done[k] = "skip"
                self._dj_log(
                    f"bridge {k} too late/reordered "
                    f"(a={frontier.a_pos} b={frontier.b_pos} "
                    f"cur={frontier.current_pos})")
                return
            result = payload.get("result")
            if state != "committed" or not getattr(result, "committed", False):
                self._dj_bridge_done[k] = "skip"
                self._dj_log(f"bridge {k} splice ROLLED BACK")
                return
            bid = result.bridge_id
            prior_b = payload.get("priorB")
            prior_a = payload.get("priorA")
            b_start = payload.get("bStart", 0.0)
            a_end = payload.get("aEnd", 0.0)
            b_end = (prior_b or (0.0, 0.0))[1]
            self._dj_ranged[b_id] = (b_start, b_end)
            a_entry = (prior_a or (0.0, 0.0))[0]
            self._dj_ranged[a_id] = (a_entry, a_end)
            self._dj_bridges[bid] = (a_id, b_id, payload.get("label", ""))
            self._dj_bridge_done[k] = "mix"
            self._dj_plan_key = None
            self._dj_log(f"bridge {k} SPLICED ({payload.get('label', '')})")
        finally:
            if lease is not None:
                lease.release()
            if getattr(self, "_dj_reset_pending", False):
                self._dj_reset()

        # Reconcile presentation asynchronously after ownership publication.
        self._request_queue_refresh()

    def _dj_scan_worker(self, files):
        """Worker with its OWN MPD client (stickers are not thread-safe on
        the GUI client). Drains the priority lane between library files."""
        from .dj import cues as cueslib
        cli = None
        done = scored = 0
        total = 0
        try:
            cli = open_temporary_mpd_client(HOST, PORT, timeout=10)
            self._workers.acquire(cli, close_mpd_client)
            have = set()
            try:
                for e in cli.sticker_find("song", "", "joi_cues"):
                    s = e.get("sticker", "")
                    # current version AND carries a key estimate — stickers
                    # scored before the key field existed re-scan lazily so
                    # harmonic chaining reaches the whole library without a
                    # version bump (a bump would blind the planner for hours)
                    # ...AND carries key + cue levels — older same-version
                    # stickers re-scan lazily, no version bump needed
                    if (f'"v": {DJ_CUES_V}' in s and '"key":' in s
                            and '"lv":' in s and '"bcut":' in s
                            and '"voc":' in s):
                        have.add(e.get("file", ""))
            except Exception:
                pass
            todo = [f for f in files if f not in have]
            total = len(todo)
            seen = set()
            while True:
                if self._workers.stop_requested.is_set():
                    break
                prio = bool(self._dj_prio)
                if prio:
                    try:
                        f = self._dj_prio.popleft()
                    except IndexError:
                        continue
                elif todo:
                    f = todo.pop(0)
                else:
                    break
                if not f or f in seen or (prio and f in have):
                    continue
                seen.add(f)
                t0 = time.monotonic()
                res = cueslib.analyze(os.path.join(MUSIC_ROOT, f))
                if res is None:
                    # undecodable is a RESULT — store conf 0 so neither the
                    # planner nor a future scan retries it forever
                    res = {"v": DJ_CUES_V, "bpm": 0.0, "b0": 0.0,
                           "conf": 0.0, "dur": 0.0, "key": -1, "lv": 1,
                           "bcut": 120.0, "voc": 0.0, "in": [], "out": []}
                done += 1
                if res is not None:
                    try:
                        cli.sticker_set("song", f, "joi_cues", json.dumps(res))
                        scored += 1
                        have.add(f)
                    except Exception:
                        if self._workers.stop_requested.is_set():
                            break
                        close_mpd_client(cli)
                        try:
                            cli.connect(HOST, PORT)
                        except Exception:
                            break
                if done % 5 == 0:
                    self.djProgress.emit(done, max(total, done), scored)
                # queue-lane files go brisk; the library sweep breathes
                dt = time.monotonic() - t0
                time.sleep(0.05 if self._dj_prio else min(1.0, max(0.05, dt)))
        finally:
            if cli is not None:
                self._workers.release(cli)
                close_mpd_client(cli)
        self.djProgress.emit(done, max(total, done), scored)

    @staticmethod
    def _dj_top(file):
        """Top-level genre folder of a file."""
        return file.split("/", 1)[0] if "/" in file else ""

    @staticmethod
    def _dj_room_of(file):
        """A file's room: genre/subgenre when the tree is deep enough,
        else the top folder (matches _dj_pool's file-seed logic)."""
        parts = file.split("/")
        return "/".join(parts[:2]) if len(parts) > 3 else parts[0]

    def _dj_rooms(self):
        """{room prefix: [files]} across the whole library (disliked
        songs never enter a set)."""
        rooms = {}
        hidden = set(self._disliked)
        for e in self._search_index:
            f = e["song"]["file"]
            if f not in hidden:
                rooms.setdefault(self._dj_room_of(f), []).append(f)
        return rooms

    def _dj_pool(self, seed, is_file):
        """(candidate files, room label) for a seed. A song seeds from its
        subgenre folder (genre/subgenre/artist/album taxonomy), widening to
        the whole genre when the room is small."""
        files = self._drop_disliked(
            [e["song"]["file"] for e in self._search_index], keep=seed)
        if is_file:
            parts = seed.split("/")
            prefix = "/".join(parts[:2]) if len(parts) > 3 else parts[0]
            pool = [f for f in files if f.startswith(prefix + "/")]
            if len(pool) < 40 and parts[0] != prefix:
                prefix = parts[0]
                pool = [f for f in files if f.startswith(prefix + "/")]
            return pool, os.path.basename(prefix)
        seed = seed.rstrip("/")
        return ([f for f in files if f.startswith(seed + "/")],
                os.path.basename(seed) or seed)

    def _dj_usable(self, cues):
        """A song earns a set slot when its cues clear the session gates."""
        conf_min, in_min, out_min = self.DJ_GATES[self._dj_level]
        if not cues or cues.get("conf", 0) < conf_min:
            return 0.0, 0.0, 0.0
        bi = max((c[1] for c in (cues.get("in") or [])), default=0.0)
        bo = max((c[1] for c in (cues.get("out") or [])), default=0.0)
        if bi < in_min and bo < out_min:
            return 0.0, bi, bo
        return cues.get("conf", 0) * (bi + bo), bi, bo

    def _dj_cue_map(self, pool, cli=None):
        """{file: parsed joi_cues} for a candidate pool (one sticker sweep)."""
        raw = self._sticker_map("joi_cues", cli)
        out = {}
        for f in pool:
            r = raw.get(f)
            if not r:
                continue
            try:
                d = json.loads(r)
            except ValueError:
                continue
            if d.get("v") == DJ_CUES_V:
                out[f] = d
        return out

    @staticmethod
    def _dj_est_len(d):
        """A song's planned playing length inside a set: its entry→exit
        window where the cues are strong, else its full duration."""
        dur = float(d.get("dur", 0.0) or 0.0)
        start = min((c[0] for c in (d.get("in") or []) if c[1] >= 0.6),
                    default=0.0)
        end = max((c[0] for c in (d.get("out") or []) if c[1] >= 0.45),
                  default=dur) or dur
        return max(30.0, end - start)

    def _dj_shape_fn(self):
        """Target-energy curve of the set (position fraction → 0..1),
        or None for FLAT (pure tempo/cue chaining, today's behavior)."""
        if self._dj_shape == "rise":
            return lambda x: 0.35 + 0.55 * min(1.0, x)
        if self._dj_shape == "arc":
            return lambda x: (0.4 + 0.5 * (x / 0.6) if x < 0.6
                              else 0.9 - 0.4 * ((x - 0.6) / 0.4))
        return None

    def _dj_chain(self, cand, cur_bpm=0.0, recent=None, cur_key=-1,
                  shape=None, pos0=0, total=0):
        """Whole-set beam search over possible futures.

        The old greedy walk optimized only the next pair and frequently spent
        the best bridge too early, leaving an incoherent tail.  A bounded beam
        keeps several complete arcs alive and gives the DJ the aggressive
        ordering authority expected of it.
        """
        features = [TrackFeatures(
            file=c["f"], artist=c.get("artist", ""), title=c.get("title", ""),
            album=c.get("album", ""), bpm=c.get("bpm", 0.0),
            energy=c.get("en"), key=c.get("key", -1),
            cue_quality=min(1.0, c.get("mix", 0.0) / 2.0),
            vocal=c.get("vocal", 0.0)) for c in cand]
        start = None
        if cur_bpm > 0 or cur_key >= 0:
            start = TrackFeatures("__anchor__", bpm=cur_bpm, key=cur_key,
                                  energy=shape(0) if shape else None,
                                  cue_quality=.65, anchor=True)
        seq = beam_sequence(features, count=len(features), shape=shape,
                            start=start, beam_width=14)
        ordered = [t.file for t in seq]
        for t in seq:
            if t.bpm > 0:
                cur_bpm = t.bpm
            if t.key >= 0:
                cur_key = t.key
            if recent is not None:
                recent.append(os.path.dirname(t.file))
        return ordered, cur_bpm, cur_key

    def _dj_cand(self, cues, energies=None, exclude=()):
        """Gate-passing candidate dicts from a cue map. Interludes —
        skits, intros, ambient beds under 75 s — never earn a set slot;
        they'd poison the tempo chain and die mid-transition anyway."""
        energies = energies if energies is not None else {}
        out = []
        metadata = {e["song"]["file"]: e["song"] for e in self._search_index}
        for f, d in cues.items():
            if f in exclude:
                continue
            if 0 < float(d.get("dur", 0.0) or 0.0) < 75.0:
                continue
            mix, _, _ = self._dj_usable(d)
            if mix > 0:
                song = metadata.get(f, {})
                vocal = max((c[3] for side in ("in", "out")
                             for c in d.get(side, []) if len(c) > 3),
                            default=float(d.get("voc", 0.0) or 0.0))
                out.append({"f": f, "mix": mix, "bpm": d.get("bpm", 0.0),
                            "key": d.get("key", -1),
                            "en": energies.get(f), "vocal": vocal,
                            "artist": song.get("artist", ""),
                            "title": song.get("title", ""),
                            "album": song.get("album", "")})
        out.sort(key=lambda c: -c["mix"])
        return out

    def _dj_find_anthems(self, pool, cli=None):
        """Top-decile songs of the pool by plays+hearts: the ones a set
        must respect — never sliced short, always played out."""
        counts = self._sticker_map("playCount", cli)
        ratings = self._sticker_map("rating", cli)
        scored = []
        for f in pool:
            try:
                pc = int(counts.get(f, 0))
            except (TypeError, ValueError):
                pc = 0
            try:
                rv = int(ratings.get(f, 0))
            except (TypeError, ValueError):
                rv = 0
            if pc >= 3:
                scored.append((f, pc + (5 if rv >= 9 else 0)))
        if len(scored) < 5:
            return set()
        scored.sort(key=lambda x: -x[1])
        return {f for f, _ in scored[:max(1, len(scored) // 10)]}

    def _dj_apply_time(self, ordered, cue_map, cli=None):
        """Trim a set to the timed-set target, ending on the most
        energetic song of the final stretch ("end high")."""
        if not self._dj_minutes or not ordered:
            return ordered
        target = self._dj_minutes * 60.0
        acc, out = 0.0, []
        for f in ordered:
            out.append(f)
            d = cue_map.get(f)
            acc += self._dj_est_len(d) if d else 240.0
            if acc >= target:
                break
        en = self._energies(cli)
        tail = out[-5:]
        if len(tail) >= 2:
            best = max(tail, key=lambda f: en.get(f, 0.0))
            if best != out[-1]:
                # move the LAST occurrence (B2B sets can carry duplicates)
                idx = len(out) - 1 - out[::-1].index(best)
                out.append(out.pop(idx))
        return out

    def _dj_build_set(self, pool, seed_file="", cli=None):
        """One-room / free-for-all set: cut-ready songs ranked by
        mixability, tempo/key-chained, optionally shaped. Thin pools are
        topped up with unscored songs — they transition normally."""
        pool = [f for f in pool if f not in self._disliked]
        cues = self._dj_cue_map(pool, cli)
        energies = self._energies(cli)
        cand = self._dj_cand(cues, energies, exclude=(seed_file,))[:60]
        ordered = [seed_file] if seed_file else []
        sd = cues.get(seed_file, {}) if seed_file else {}
        chained, _, _ = self._dj_chain(
            cand, sd.get("bpm", 0.0), cur_key=sd.get("key", -1),
            shape=self._dj_shape_fn(), pos0=len(ordered),
            total=len(ordered) + len(cand))
        ordered += chained
        if len(ordered) < 25:
            dur_of = {e["song"]["file"]: e["song"].get("duration", 0)
                      for e in self._search_index}
            extra = [f for f in pool if f not in set(ordered)
                     and not (0 < float(dur_of.get(f, 0) or 0) < 75.0)]
            random.shuffle(extra)
            ordered += extra[:25 - len(ordered)]
        return ordered[:60]

    def _dj_journey_route(self, start, usable_rooms, cent):
        """Room order for a progressive set: a greedy walk to the nearest-
        sounding unvisited room (energy + tempo centroids), with a tax on
        leaving the current top-level genre — so sibling subgenres tour
        first and foreign genres enter only when they're the closest thing
        left. That's what makes the journey progressive."""
        route = [start]
        visited = {start}
        cur = start
        while len(route) < self.DJ_HOPS:
            cand = [r for r in usable_rooms
                    if r not in visited and r in cent
                    and self._dj_top(r) not in self.DJ_ROUTE_EXCLUDE]
            if not cand or cur not in cent:
                break

            def dist(r, current=cur):
                e1, b1 = cent[current]
                e2, b2 = cent[r]
                d = 2.0 * abs(e1 - e2)
                if b1 > 0 and b2 > 0:
                    d += abs(math.log2(b1 / b2))
                if self._dj_top(r) != self._dj_top(current):
                    d += 0.8   # foreign-genre hop tax
                return d + random.random() * 0.05

            nxt = min(cand, key=dist)
            route.append(nxt)
            visited.add(nxt)
            cur = nxt
        return route

    def _dj_build_journey(self, seed_room, seed_file="", cli=None):
        """Progressive set: segments of DJ_SEG songs per room, touring
        rooms by sonic nearness from the seed. Tempo continuity carries
        across segment boundaries (the bridge pair is BPM-matched)."""
        rooms = self._dj_rooms()
        all_files = [f for fl in rooms.values() for f in fl
                     if f not in self._disliked]
        cues = self._dj_cue_map(all_files, cli)
        energies = self._energies(cli)
        bpm_raw = self._sticker_map("joi_bpm", cli)

        by_room = {}
        cent = {}
        for r, fl in rooms.items():
            cand = self._dj_cand({f: cues[f] for f in fl if f in cues},
                                 energies, exclude=(seed_file,))
            if cand:
                by_room[r] = cand
            es = [energies[f] for f in fl if f in energies]
            bs = sorted(float(bpm_raw[f]) for f in fl
                        if f in bpm_raw and float(bpm_raw[f]) > 0)
            if len(es) >= 3:
                cent[r] = (sum(es) / len(es), bs[len(bs) // 2] if bs else 0.0)

        usable_rooms = [r for r, c in by_room.items() if len(c) >= 3]
        # The Deck's room buttons are top-level MPD folders, while deep
        # libraries are partitioned above into their leaf genre rooms.  A
        # top-level seed therefore may not itself be a key in ``rooms``.
        # Resolve it to a real child room before routing; otherwise the route
        # contains only the nonexistent parent and the builder returns an
        # empty set despite a fully scored library.
        if seed_room not in rooms:
            children = [r for r in usable_rooms
                        if r.startswith(seed_room.rstrip("/") + "/")]
            if not children:
                children = [r for r in rooms
                            if r.startswith(seed_room.rstrip("/") + "/")]
            if children:
                seed_room = random.choice(children)
        route = self._dj_journey_route(seed_room, usable_rooms, cent)

        ordered = [seed_file] if seed_file else []
        used = set(ordered)
        sd = cues.get(seed_file, {}) if seed_file else {}
        cur_bpm = sd.get("bpm", 0.0)
        cur_key = sd.get("key", -1)
        recent = deque(maxlen=3)
        shape = self._dj_shape_fn()
        total_est = len(route) * self.DJ_SEG
        for r in route:
            seg_cand = [c for c in by_room.get(r, [])
                        if c["f"] not in used][:int(self.DJ_SEG * 1.5)]
            seg, cur_bpm, cur_key = self._dj_chain(
                seg_cand, cur_bpm, recent, cur_key,
                shape=shape, pos0=len(ordered), total=total_est)
            seg = seg[:self.DJ_SEG]
            ordered += seg
            used.update(seg)
        if len(ordered) < 25:
            dur_of = {e["song"]["file"]: e["song"].get("duration", 0)
                      for e in self._search_index}
            extra = [f for f in rooms.get(seed_room, []) if f not in used
                     and not (0 < float(dur_of.get(f, 0) or 0) < 75.0)]
            random.shuffle(extra)
            ordered += extra[:25 - len(ordered)]
        return ordered[:60]

    def _dj_ensure_sting(self):
        """Render the (tiny, tasteful) session-opening riser once."""
        p = Path(cache_path('sting.flac'))
        if p.exists():
            return str(p)
        fc = ("aformat=channel_layouts=stereo,highpass=f=300,"
              "lowpass=f=6000,afade=t=in:d=1.05:curve=exp,"
              "afade=t=out:st=1.05:d=0.25,volume=-10dB")
        r = subprocess.run(
            ["nice", "-n", "10", "ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", "anoisesrc=color=pink:d=1.3:a=0.3",
             "-af", fc, "-ar", "48000", "-sample_fmt", "s16", str(p)],
            capture_output=True, timeout=30)
        if r.returncode != 0 or not p.exists():
            return ""
        try:
            from mutagen.flac import FLAC
            f = FLAC(str(p))
            f["title"] = "AMPERE"
            f["artist"] = "AMPERE DJ"
            f["replaygain_track_gain"] = "0.00 dB"
            f["replaygain_track_peak"] = "1.0"
            f["replaygain_album_gain"] = "0.00 dB"
            f["replaygain_album_peak"] = "1.0"
            f.save()
        except Exception:
            pass
        return str(p)
