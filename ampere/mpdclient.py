"""MPD backend for Ampere.

Two connections: a command client used from the GUI thread, and a dedicated
idle connection on a daemon thread that turns MPD's push notifications into
Qt signals. All playback state lives in MPD — the app is a pure view, so it
survives restarts mid-song and never disagrees with `mpc`.
"""

from ampere.compat import cache_path, config_path, environment
import hashlib
import json
import math
import os
import random
import re
import secrets
import socket
import subprocess
import threading
import uuid
import time
from collections import Counter, deque
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from PySide6.QtGui import QImage

from mpd.base import ConnectionError as MPDConnectionError, CommandError, FailureResponseCode
from PySide6.QtCore import QObject, QTimer, Signal, Slot, Property

from . import __version__
from .albums import AlbumPresenter, ChapterDetector, LibraryDirectory
from .artist_profiles import ArtistPortraitCoordinator
from .biographies import BiographyService
from .cache_maintenance import CacheClearResult, CacheMaintenanceService
from .automix import (AutoMixDaemonController, TransitionOptionsResult,
                      TransitionThresholdResult, energy_fade_factor,
                      fade_duration)
from .dj import bridge as djbridge
from .dj import verify as djverify
from .dj.planner import DjPlannerMixin
from .dj.sets import load_saved_sets, select_replayable_set
from .energy_scan import EnergyScanner
from .enrichment import EnrichmentCoordinator
from .transitions import StreamTransitionController
from .versions import VersionPolicy
from .workers import WorkerRegistry, WorkerShutdownReport
from . import search as searchlib
from .library import (LibraryIndexer, LibraryIndexResult, LibraryPathResult,
                      LibraryRepository, LibraryUpdateController,
                      LibraryUpdateResult,
                      normalize_song)
from .library_deletion import DeletionReconciliation, LibraryDeletionService
from .listening_progress import ListeningProgressService
from .home import HomeProjection, listening_recommendations
from .discover import DiscoverProjection
from .loudness import (ReplayGainModeController, ReplayGainModeResult,
                       ReplayGainScanner)
from .media import MediaEnrichmentService, MediaPrefetcher
from .metadata import MetadataService
from .memory import release_unused_heap
from .mixtapes import MixtapePlanner
from .mixramp_scan import MixRampScanner
from .mpdgateway import (MpdGateway, MpdReadResult, close_mpd_client,
                         create_mpd_client,
                         retire_mpd_writer,
                         temporary_mpd_client)
from .mpd_config import MpdConfigService, NormalizationResult
from .playlists import (DISLIKED_PLAYLIST, LIKED_PLAYLIST,
                        PlaylistRepository)
from .playlist_service import (PlaylistReadResult, PlaylistService,
                               plan_queue_save)
from .playback import (PlaybackBooleanResult, PlaybackController,
                       PlaybackOptionsResult, PlaybackStateResult,
                       PlaybackVolumeResult, QueuePlayResult, QueueSnapshotResult,
                       QueueSnapshotStore)
from .playback_status import PlaybackHeartbeat, reconcile_mixramp
from .playhistory import PlayHistoryRepository
from .queue_sequencing import QueueSequencer
from .queue_mutations import QueueMutationCoordinator
from .rewind import RewindService
from .remote import RemoteControlService
from .settings import (SettingsRepository, SettingsSaveResult,
                       clean_artist_aliases, clean_playlist_play_counts,
                       clean_search_history,
                       clean_sound_mixes)
from .sessions import SessionService
from .beacon_controller import BeaconController
from . import characters as characterlib
from .shelves import ShelfService
from .artist_aliases import suggest as suggest_artist_aliases
from .artists import set_aliases as set_artist_aliases
from .artists import (artist_key, canonical_artist_name,
                      song_credited_artists)
from .smartmix import SmartMixPlanner
from .stored_playlists import GeneratedPlaylistWriter
from .stickers import (ExclusiveStickerResult, PlayRecordResult,
                       StickerRepository)
from .taste import TasteService, TasteUpdate

# MPD host/port/socket + library root live in ampere.paths (dependency-free)
# so the extracted DJ planner can import them without a circular dep.
from .paths import MPD_SOCKET, HOST, PORT, MUSIC_ROOT  # noqa: E402,F401

AUDIO_EXT = (".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".aiff", ".wv", ".ape")
PREVIOUS_RESTART_SECONDS = 4.0


def _read_optional_playlist(client, name):
    """An uncreated taste playlist is empty; other MPD failures stay failures."""
    try:
        return client.listplaylist(name)
    except CommandError as exc:
        if exc.errno == FailureResponseCode.NO_EXIST:
            return []
        raise


class PlanningEvidenceUnavailable(RuntimeError):
    pass


# Mood radio — the six emotions the quickstart tile offers. Each mood scores
# the library three ways: membership in his curated mood playlists (exemplars,
# trusted over everything), genre folder (weights; a "Genre/Subgenre" key
# overrides its parent genre, negative = excluded), and the analyzed
# joi_energy band. Genres absent from a mood's table are excluded outright
# unless the track is an exemplar — that hard rule is what keeps Metal out of
# CALM. Playlists that don't exist resolve to empty and just contribute nothing.
MOODS = {
    "hyped": dict(label="HYPED",
                  playlists=("Hype",),
                  genres={"Rap Hip-Hop": 1.0, "Electronic": 0.8, "ElectroPop": 0.7},
                  energy=(0.55, 1.0)),
    "happy": dict(label="HAPPY",
                  playlists=(),
                  genres={"Pop": 1.0, "ElectroPop": 0.9, "Latin": 0.8,
                          "Americana": 0.5, "Folk": 0.4,
                          "Rap Hip-Hop/Pop-Rap & Party": 0.6,
                          "ElectroPop/Dark & Hyperpop": -1.0},
                  energy=(0.40, 0.85)),
    "angry": dict(label="ANGRY",
                  playlists=("Warpath", "Seismic"),
                  genres={"Metal & Rock": 1.0, "Rap Hip-Hop": 0.4,
                          "Rap Hip-Hop/Pop-Rap & Party": -1.0},
                  energy=(0.50, 1.0)),
    "calm":  dict(label="CALM",
                  playlists=("Sanctum", "Night Drive", "Rust"),
                  genres={"Classical": 1.0, "Folk": 0.8, "Americana": 0.7},
                  energy=(0.0, 0.45)),
    "sad":   dict(label="SAD",
                  playlists=("Melancholic", "Tears in Rain", "Gallows"),
                  genres={"Post-Punk & Doomer Wave": 0.8, "Folk": 0.6, "Classical": 0.5},
                  energy=(0.0, 0.50)),
    "dark":  dict(label="DARK",
                  playlists=("Dark Opera", "Ritual", "Gallows"),
                  genres={"Post-Punk & Doomer Wave": 1.0, "Metal & Rock": 0.5,
                          "Electronic": 0.4,
                          "ElectroPop/Dark & Hyperpop": 0.7},
                  energy=(0.2, 0.7)),
}


WAVE_DIR = Path(cache_path('waves'))
WAVE_BUCKETS = 400

# joi_cues sticker schema version — must match ampere.djcues.CUES_VERSION
# (kept as a plain constant so the GUI path never imports numpy)
DJ_CUES_V = 2   # must match djcues.CUES_VERSION (v2: onset-snapped cues)

# normalization preamps are mpd.conf-only options (no protocol command) —
# Ampere owns this file, so Settings edits it and restarts the daemon
MPD_CONF = Path(os.path.expanduser("~/.config/mpd/mpd.conf"))

# client-side settings MPD can't hold for us (auto-mix style lives here:
# "fade" needs mixrampdelay=nan + per-song crossfade, so MPD state alone
# can't express whether auto-mix is on)
CONF_PATH = Path(config_path('config.json'))

# append-only play log — stickers only keep LAST-played, this is what makes
# time-sliced stats (Rewind) possible going forward
PLAYLOG = Path(config_path('playlog.jsonl'))

# tracks longer than this remember their position (DJ mixes, ambient sets)
RESUME_MIN_SECONDS = 20 * 60


def _compute_wave(abs_path: str) -> list:
    """Loudness envelope of a track, WAVE_BUCKETS values normalized 0..1.
    RMS per bucket, not peak — modern masters peak near max constantly, so a
    peak envelope reads as a flat slab; RMS is where the dynamics live.
    Decodes via ffmpeg to 8 kHz mono s16 — plenty for a seek-bar silhouette.
    numpy-vectorized: the old pure-Python sample loop held the GIL ~0.2 s
    per track, hitching the whole UI right at every song change. ffmpeg
    runs niced so it never competes with MPD's own decode at a transition."""
    r = subprocess.run(
        ["nice", "-n", "10", "ffmpeg", "-v", "quiet", "-i", abs_path,
         "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True)
    raw = r.stdout[: len(r.stdout) // 2 * 2]
    if not raw:
        return []
    import numpy as np
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    n = data.size
    if n == 0:
        return []
    per = max(1, n // WAVE_BUCKETS)
    m = (n // per) * per
    rms = np.sqrt(np.mean(data[:m].reshape(-1, per) ** 2,
                          axis=1))[:WAVE_BUCKETS] / 32768.0
    if rms.size == 0:
        return []
    mx = float(rms.max())
    if mx <= 0:
        mx = 1.0
    # gamma > 1 deepens the quiet parts for extra visual contrast
    return [round(float(v), 3) for v in (rms / mx) ** 1.25]


# hues nobody wants their walls painted in: olive/chartreuse "bile band"
# (the Pantone 448C family). Dominant colors here get penalized, and if one
# still wins, its hue is nudged to the nearest pleasant neighbor.
_UGLY_LO, _UGLY_HI = 0.13, 0.27


def _art_colors(file: str) -> list:
    """[primary, average] hex colors from the track's album art.
    Primary = the DOMINANT chromatic color (hue-bucket mass, not the single
    most vivid pixel — a lime speck must not repaint the app)."""
    import colorsys
    from .artprovider import _art_bytes_for, CACHE_DIR
    fallback = ["#8f8f97", "#5a5a62"]  # no art -> neutral grey theme
    try:
        # the prefetch-warmed thumbnail is plenty for a 32×32 palette read —
        # skip re-decoding the full-size art at the transition moment
        img = QImage()
        thumb = CACHE_DIR / (hashlib.sha1(file.encode(), usedforsecurity=False).hexdigest() + ".jpg")
        if thumb.exists():
            img.load(str(thumb))
        if img.isNull() or img.width() <= 1:   # miss or no-art marker
            data = _art_bytes_for(Path(os.path.join(MUSIC_ROOT, file)))
            if not data:
                return fallback
            img = QImage()
            if not img.loadFromData(data):
                return fallback
        img = img.scaled(32, 32)
        BINS = 24
        mass = [0.0] * BINS
        acc = [[0.0, 0.0, 0.0] for _ in range(BINS)]   # weighted rgb per bin
        r_sum = g_sum = b_sum = count = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r, g, b = c.redF(), c.greenF(), c.blueF()
                r_sum += c.red(); g_sum += c.green(); b_sum += c.blue()
                count += 1
                h, s, v = colorsys.rgb_to_hsv(r, g, b)
                if s < 0.12 or v < 0.05:
                    continue                       # grey/near-black: no hue vote
                w = (s ** 1.3) * (v ** 0.6)        # dark-but-saturated still votes
                if _UGLY_LO <= h <= _UGLY_HI:
                    w *= 0.35                      # bile band: uphill battle
                bin_i = int(h * BINS) % BINS
                mass[bin_i] += w
                acc[bin_i][0] += r * w
                acc[bin_i][1] += g * w
                acc[bin_i][2] += b * w
        if count == 0:
            return fallback
        avg = f"#{r_sum // count:02x}{g_sum // count:02x}{b_sum // count:02x}"
        total = sum(mass)
        if total < 0.5:                            # essentially achromatic art
            return [avg, avg]
        # dominant bin + its neighbors (hues straddle bin edges)
        best = max(range(BINS), key=lambda i: mass[i] + 0.5 * (mass[i - 1] + mass[(i + 1) % BINS]))
        w = mass[best] or 1.0
        pr, pg, pb = (acc[best][0] / w, acc[best][1] / w, acc[best][2] / w)
        h, s, v = colorsys.rgb_to_hsv(pr, pg, pb)
        if _UGLY_LO <= h <= _UGLY_HI:              # still bile: remap the hue
            h = 0.105 if h < 0.20 else 0.31        # -> warm amber | clean green
            s = min(s, 0.6)
        v = max(v, 0.35)
        pr, pg, pb = colorsys.hsv_to_rgb(h, s, v)
        primary = f"#{int(pr * 255):02x}{int(pg * 255):02x}{int(pb * 255):02x}"
        return [primary, avg]
    except Exception:
        return fallback


_LRC_STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _read_lyrics(abs_path: str) -> tuple[list, bool]:
    """Extract embedded lyrics. Returns ([{t, line}], synced) — t=-1 if unsynced."""
    text = ""
    try:
        ext = os.path.splitext(abs_path)[1].lower()
        if ext == ".flac":
            f = FLAC(abs_path)
            for key in ("lyrics", "unsyncedlyrics"):
                vals = f.tags.get(key) if f.tags else None
                if vals:
                    text = vals[0]
                    break
        elif ext == ".mp3":
            tags = ID3(abs_path)
            uslt = tags.getall("USLT")
            if uslt:
                text = uslt[0].text
        else:
            f = MutagenFile(abs_path)
            if f and f.tags:
                for key in ("lyrics", "LYRICS", "\xa9lyr"):
                    vals = f.tags.get(key)
                    if vals:
                        text = vals[0] if isinstance(vals, list) else str(vals)
                        break
    except Exception:
        return [], False
    if not text:
        return [], False
    timed, plain = [], []
    for raw in text.splitlines():
        stamps = _LRC_STAMP.findall(raw)
        line = _LRC_STAMP.sub("", raw).strip()
        if stamps:
            for m, s in stamps:
                timed.append({"t": int(m) * 60 + float(s), "line": line})
        elif line:
            plain.append({"t": -1.0, "line": line})
    if timed:
        timed.sort(key=lambda e: e["t"])
        return timed, True
    return plain, False


def _avg_kbps(file: str, duration: float) -> int:
    """Whole-file average bitrate — steadier than MPD's live counter."""
    try:
        if duration > 0:
            size = os.path.getsize(os.path.join(MUSIC_ROOT, file))
            return round(size * 8 / duration / 1000)
    except OSError:
        pass
    return 0


_song_map = normalize_song  # compatibility name while Backend remains the Qt facade


class Backend(DjPlannerMixin, QObject):
    # state
    statusChanged = Signal()
    songChanged = Signal()
    queueChanged = Signal()
    # queuePos changes only when the playing row moves (song change / queue edit),
    # NOT every second like statusChanged. Bindings that read the (large) queue
    # keyed off the current position MUST notify off this, or they re-marshal the
    # whole queue on every 1 Hz status tick (froze the GUI thread ~750ms/s).
    queuePosChanged = Signal()
    # Small queue projections used by always-alive shell/Now Playing views.
    # This fires for either membership/order or playhead movement so QML never
    # has to read and marshal the complete queue merely to show a count/window.
    queueWindowChanged = Signal()
    playlistsChanged = Signal()
    playlistUsageChanged = Signal()
    playlistTracksReady = Signal(str, "QVariantList", bool)
    playlistCoversChanged = Signal()
    _playlistCoversArrived = Signal(object)
    databaseUpdated = Signal()
    librarySummaryChanged = Signal()
    libraryReadyChanged = Signal()
    libraryStatsChanged = Signal()
    # Rewind's Sonic DNA (SPEC row 33, one of three LOCKED modes) — NOT the
    # retired Saved Sound Profiles. Commented out with them in 6157232, which
    # left its own emitters raising; restored 2026-08-23.
    soundProfileChanged = Signal()
    connectedChanged = Signal()
    errorOccurred = Signal(str)
    notice = Signal(str)                     # confirmation copy for the toast
    waveformChanged = Signal()
    lyricsChanged = Signal()
    lyricsIndexChanged = Signal()
    settingsChanged = Signal()
#     soundProfileStartFinished = Signal(str, int, bool)
#     soundProfileSaveFinished = Signal(str, bool)
#     soundProfileDeleteFinished = Signal(str, bool)
#     soundProfilePlaylistFinished = Signal(str, str, int, bool)
    recapSaveFinished = Signal(str, bool)
    moodRadioStartFinished = Signal(str, int, bool)
    mixtapeBusyChanged = Signal()
    mixtapeFinished = Signal(str, int, bool)  # saved name, track count, started
    artColorsChanged = Signal()
    artistBioReady = Signal(str, "QVariantMap")
    artistPortraitsReady = Signal("QVariantMap")
    quickSearchReady = Signal(str, "QVariantMap")
    librarySongsReady = Signal(int, "QVariantList")
    artistDiscographyReady = Signal(str, int, "QVariantList")
    quickSearchFailed = Signal(str, int, str)   # query, serial, reason
    searchHistoryChanged = Signal()
    artistAliasesChanged = Signal()
    soundMixesChanged = Signal()
    mixrampProgress = Signal(int, int, int)   # done, total, newly tagged
    rgProgress = Signal(int, int, int)        # loudness scan: done, total, tagged
    likedChanged = Signal()
    dislikedChanged = Signal()
    dislikedDeleted = Signal(str)             # human-readable outcome for the toast
    deletionStateChanged = Signal()
    smartMixChanged = Signal()
    djProgress = Signal(int, int, int)        # DJ cue scan: done, total, scored
    spotSyncDone = Signal(str)
    spectrumFrame = Signal("QVariantList")
    navRequested = Signal(str, str)           # remote /api/nav: mode, arg
    moveRequested = Signal(str)               # remote /api/next|prev -> faded skip
    volumeRequested = Signal(int)              # remote volume -> device memory
    remotePlayRequested = Signal(object)       # remote target -> session policy
    transportRequested = Signal(str)           # hosted remote -> verified state
    remoteCommandRequested = Signal(object)    # hosted remote -> owned intent
    # internal: worker threads -> GUI thread handoff (queued because of thread affinity)
    _idleEvent = Signal(list)
    _deleteDone = Signal(list, list)   # worker -> main thread: deleted, failed
    _deleteQueueReady = Signal(object)  # queue verification worker -> main
    _bridgeReady = Signal(int, int, str, float, float, float)
    _bridgeSpliceReady = Signal(object)
    # render worker -> main thread: a_id, b_id, path, a_end, b_start, ok(>0)
    _waveReady = Signal(int, str, "QVariantList")
    _songMetaReady = Signal(int, str, object) # generation, file, media result
    _radioReady = Signal(object)               # continuation scan worker → GUI
    _mixMapsReady = Signal(object)             # smart-mix scan worker → GUI
    _doctorReady = Signal("QVariantMap")      # library-doctor worker → GUI
    doctorChanged = Signal()
    _colorsReady = Signal(int, str, "QVariantList")
    _indexReady = Signal(object)  # verified library publication result
    _librarySummaryReady = Signal(object)
    _soundProfileReady = Signal(object)
    _mixtapeReady = Signal(object)
    _curatedPlanReady = Signal(object)
    _playlistTracksReady = Signal(object)
    _collectionRefreshReady = Signal(object)
    _queueRefreshReady = Signal(object)
    _queueReorderReady = Signal(object)
    _queueIntentReady = Signal(object)
    _contextShuffleReady = Signal(object)
    contextShuffleModeChanged = Signal()
    _playbackIntentReady = Signal(object)
    _spectrumPrepared = Signal(bool)
    _statusRefreshReady = Signal(object)
    _delayedStatusReady = Signal(object)
    _pathActionReady = Signal(object)
    _playlistActionReady = Signal(object)
    _remotePlayReady = Signal(object)
    _djResetReady = Signal(object)
    _djSessionReady = Signal(object)
    _djReplayReady = Signal(object)
    _djSetSaveReady = Signal(bool)
    _cacheClearReady = Signal(object)
    _streamIoReady = Signal(object)
    _metadataReadReady = Signal(object)
    _metadataUpdateReady = Signal(object)
    beaconChanged = Signal()
    _generatedPlaylistReady = Signal(object)
    _tasteMutationReady = Signal(object)
    _listeningProgressReady = Signal(object)
    _preferredVersionReady = Signal(object)
    _databaseUpdateReady = Signal(object)
    _replayGainReady = Signal(object)
    _transitionSettingsReady = Signal(object)
    _normalizationReady = Signal(object)
    _remoteLifecycleReady = Signal(object)
    trackMetadataReady = Signal(str, "QVariantMap")
    trackMetadataUpdateFinished = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmd = create_mpd_client()
        # GUI-thread client: keep the timeout SHORT. Every op on this client
        # runs on the UI thread (per-second status poll + user commands), so a
        # stalled socket blocks the whole UI for the timeout duration. All the
        # heavy whole-library scans now run on worker clients (radio/smart-mix),
        # so 3s is ample for the small ops that remain (status/currentsong/
        # stickers) and bounds any freeze to 3s instead of 10.
        self._cmd.timeout = 3
        self._connected = False
        self._gateway = MpdGateway(
            self._cmd, HOST, PORT, state_changed=self._on_gateway_state,
            connected=self._refresh_all,
            error=self.errorOccurred.emit)
        self._queue_mutations = QueueMutationCoordinator()
        self.queueChanged.connect(self.queueWindowChanged.emit)
        self.queuePosChanged.connect(self.queueWindowChanged.emit)
        self._playback = PlaybackController(
            self._cmd, ensure_connected=self._ensure_connected,
            mark_disconnected=self._gateway.mark_disconnected,
            error=self.errorOccurred.emit,
            queue_mutations=self._queue_mutations)
        self._transition_settings_busy = False
        self._transition_settings_active = None
        self._transition_settings_pending = None
        self._transition_internal_pending = None
        self._transition_settings_generation = 0
        self._transition_internal_failed = False
        self._replay_gain_busy = False
        self._replay_gain_active = None
        self._replay_gain_pending = None
        self._replay_gain_generation = 0
        self._queue_sequencer = QueueSequencer()
        self._queue_snapshots = QueueSnapshotStore(normalize=_song_map)
        self._queue_refresh_busy = False
        self._queue_refresh_pending = False
        self._queue_refresh_generation = 0
        self._queue_refresh_failed = False
        self._queue_reorder_busy = False
        self._queue_reorder_generation = 0
        self._queue_intent_generation = 0
        self._pending_disliked_cleanup = []
        self._context_shuffle_generation = 0
        self._context_shuffle_mode = "off"
        self._context_shuffle_cancel_event = None
        # Queue provenance is intentionally ephemeral. MPD cannot tell us
        # whether a restored queue came from an album or from hand-picked
        # Play Next actions, so an unknown queue fails closed as manual until
        # Ampere admits a new multi-song replacement itself.
        self._defined_queue_active = False
        self._defined_queue_kind = "unknown"
        self._defined_queue_files = ()
        self._context_shuffle_restore_pending = False
        # Smart retains its taste anchor only while augmenting that admitted
        # queue; it no longer grows a replacement session past its end.
        self._context_shuffle_seed = {}
        self._smart_refill_busy = False
        self._smart_refill_retry_at = 0.0
        # Interactive playback commands use short-lived worker clients. Each
        # intent family is serialized and retains only its newest pending
        # value, so a slider drag or rapid toggle cannot queue an unbounded
        # number of verified MPD transactions on Qt's input thread.
        self._playback_intent_active = set()
        self._playback_intent_pending = {}
        self._transport_intent_target = None
        self._repeat_intent_target = None
        self._status_refresh_busy = False
        self._status_refresh_pending = False
        self._status_refresh_generation = 0
        self._path_action_busy = False
        self._path_action_pending = None
        self._path_action_generation = 0
        self._playlist_action_busy = False
        self._playlist_action_pending = None
        self._playlist_action_generation = 0
        self._remote_play_busy = False
        self._remote_play_pending = None
        self._remote_play_generation = 0
        self._dj_reset_busy = False
        self._dj_reset_request_pending = False
        self._dj_reset_generation = 0
        self._dj_session_busy = False
        self._dj_session_generation = 0
        self._dj_replay_busy = False
        self._dj_replay_generation = 0
        self._dj_set_save_lock = threading.Lock()
        self._dj_set_save_busy = False
        self._dj_set_save_pending = None
        self._cache_clear_busy = False
        self._preferred_version_busy = False
        self._stickers = StickerRepository(
            read=self._call, write=self._write, client=self._cmd,
            error=self.errorOccurred.emit, observe=self._gateway.observe)
        self._listening_progress = ListeningProgressService(
            resume_min_seconds=RESUME_MIN_SECONDS)
        self._listening_progress_jobs = deque()
        self._listening_progress_busy = False
        self._listening_progress_generation = 0
        self._state = "stop"
        self._elapsed = 0.0
        self._duration = 0.0
        self._volume = 100
        self._random = False
        self._repeat = False
        self._queue = []
        self._queue_pos = -1
        self._song = {}
        self._mixrampdb = -17.0
        self._mixramp_on = False
        self._settings = SettingsRepository(CONF_PATH)
        self._mpd_config = MpdConfigService(MPD_CONF, MPD_SOCKET)
        conf = self._settings.load()
        self._beacon = BeaconController(self, conf.get("beacon_sessions", []),
                                        Path(CONF_PATH).parent / "beacon-musicbrainz.json")
        # "blend" = MPD MixRamp full-level overlap; "fade" = tag-timed linear
        # crossfade so the next song fades IN (MixRamp always adds at full
        # volume — a real fade-in only exists on MPD's plain crossfade path)
        self._mix_style = conf.get("mix_style", "blend")
        self._automix_on = bool(conf.get("automix_on", False))
        self._xfade_base = int(conf["crossfade_base"])
        # Autoplay is a standing preference, independent from both MPD's
        # repeat/single pair and transient curated-session state. The existing
        # verified library-radio planner is its continuation engine.
        self._autoplay_on = bool(conf.get("autoplay_on", False))
        self._autoplay_generation = 0
        self._sessions = SessionService()
        self._radio_mood = conf.get("radio_mood", "match")
        self._radio_busy = False
        self._radio_retry_at = 0.0
        self._radio_failure_reported = False
        # mood radio session (MOODS key, "" = off) — deliberately NOT persisted,
        # same law as dj_mode: it's a live-session flag, not a preference. A
        # restart falls back to ordinary playback (Autoplay persists
        # independently and can continue that queue near its end).
        self._mood_on = ""
        # sound-profile session (profile id, "" = off) — ephemeral, same law
        # his saved Sound Profiles: [{id, name, traits: {trait: band key}}]
        self._search_history = clean_search_history(conf.get("search_history"))
        self._playlist_play_counts = clean_playlist_play_counts(
            conf.get("playlist_play_counts"))
        # Standard remains a standing preference. Smart cannot be restored
        # across process death because MPD does not preserve whether the queue
        # came from an authored context or from Play Next; fail closed to OFF
        # rather than claiming an unknown queue.
        restored = str(conf.get("context_shuffle_mode", "off") or "off")
        self._context_shuffle_mode = (
            restored if restored in ("off", "standard", "smart") else "off")
        if self._context_shuffle_mode == "smart":
            self._context_shuffle_mode = "off"
        # Sync smart shuffle to SessionService as a mutually-exclusive session type.
        # Smart shuffle is a "session" just like radio/mood/sonic-profile.
        if self._context_shuffle_mode == "smart":
            self._sessions.set_smart_shuffle({})
        # Explicit artist aliases are catalog identity and must be in force
        # BEFORE the first projection resolves a credit (SPEC UNDESIGNED #17,
        # Iann's alias-manager direction 2026-08-21).
        self._artist_aliases = clean_artist_aliases(conf.get("artist_aliases"))
        self._sound_mixes = clean_sound_mixes(conf.get("sound_mixes"))
        set_artist_aliases(self._artist_aliases)
        # audition (cue preview) — worker threads start pw-play, the GUI thread
        # stops it; a lock + generation token stops a stop/newer-audition from
        # orphaning an in-flight process
        self._audition_proc = None
        self._audition_lock = threading.Lock()
        self._audition_gen = 0
        self._remote_on = bool(conf.get("remote_on", True))
        self._remote_token = str(conf.get("remote_token", "")).strip()
        self._remote_token_new = not self._remote_token
        if not self._remote_token:
            self._remote_token = secrets.token_urlsafe(24)
        self._remote_control = RemoteControlService(
            auth_token=self._remote_token,
            nav_cb=self.navRequested.emit,
            command_cb=self.remoteCommandRequested.emit,
            error=self.errorOccurred.emit)
        self._remote_lifecycle_busy = False
        self._remote_lifecycle_active = None
        self._remote_lifecycle_pending = None
        self._remote_lifecycle_generation = 0
        # rating system: "hearts" = like/dislike; "stars" = 1-5 rating (future)
        self._rating_mode = conf.get("rating_mode", "hearts")
        # disliked-song deletion: with a remote host+root configured the
        # delete happens on the library MASTER over ssh (sync + Plex then
        # propagate the removal everywhere); without, plain local delete.
        self._delete_remote_host = str(conf.get("delete_remote_host", ""))
        self._delete_remote_root = str(conf.get("delete_remote_root", ""))
        # smart mix (the mixtape engine) — survives restarts; the curated
        # order itself lives in MPD's queue, only the mode+shape are ours
        self._mix_on = bool(conf.get("smart_mix_on", False))
        self._mix_arc = bool(conf.get("mix_arc", False))
        self._mix_frontier = -1
        self._mix_busy = False
        self._mix_retry_at = 0.0
        self._mix_failure_reported = False
        self._mix_fp = ""
        # trim silent endings (default ON): skip a track's dead-air tail.
        # Active when auto-mix is off — auto-mix's overlap already covers
        # the outro, and its per-song fades own that window.
        self._trim_on = bool(conf.get("trim_silence", True))
        self._tail_cut = 0.0
        self._trim_gen = 0
        # DJ mode (default off — experimental): live-set transitions that
        # cut out of a hot phrase and land on the next song's drop, driven
        # by joi_cues stickers (ampere.djcues) + MPD rangeid slices.
        # LIVE-ONLY, never persisted: a DJ session exists only while it's
        # running from the deck. Restoring it from conf would let a set that
        # was interrupted by an app restart (or that simply played out) keep
        # slamming/bridging the *regular* queue — DJ leaking outside DJ mode.
        # A restart is always a fresh regular-listening session.
        self._dj_on = False
        self._dj_seed_label = conf.get("dj_seed_label", "")
        self._dj_level = conf.get("dj_level", "curated")
        # set range: "room" = never leave the seed room; "progressive" =
        # genre journey (segments tour nearby rooms, cross-genre hand-offs
        # never slam); "free" = anything mixes into anything
        self._dj_range = conf.get("dj_range", "progressive")
        if self._dj_range not in ("room", "progressive", "free"):
            self._dj_range = "progressive"
        self._dj_level = self.DJ_LEVEL_MIGRATE.get(self._dj_level,
                                                   self._dj_level)
        if self._dj_level not in self.DJ_GATES:
            self._dj_level = "classic"
        # set intelligence: energy shape, timed sets, B2B second room
        self._dj_shape = conf.get("dj_shape", "flat")
        if self._dj_shape not in ("flat", "rise", "arc"):
            self._dj_shape = "flat"
        try:
            self._dj_minutes = int(conf.get("dj_minutes", 0))
        except (TypeError, ValueError):
            self._dj_minutes = 0
        if self._dj_minutes not in (0, 30, 45, 60, 90):
            self._dj_minutes = 0
        self._dj_b2b = str(conf.get("dj_b2b", ""))
        self._dj_b2b_active = False   # THIS session is B2B (not just conf)
        self._dj_anthems = set()   # per-session: songs never cut short
        self._dj_redropped = set() # song ids already re-dropped (WILD)
        self._dj_sting = bool(conf.get("dj_sting", False))
        self._dj_set_log = {}      # this session's set + transition history
        self._dj_active = False    # the upcoming transition is DJ-owned
        self._dj_cut_at = 0.0      # planned exit (s) of the current song
        self._dj_gen = 0
        self._dj_plan_key = None
        self._dj_ranged = {}       # songid -> (entry, exit) range we set
        self._dj_cue_cache = {}
        self._dj_prio = deque()    # files the scanner should score first
        self._dj_swept = False
        # rendered mixed transitions (bridges): the "hard" DJ default —
        # 8/16-bar beatmatched volume rides, produced offline per pair
        self._dj_mix_len = str(conf.get("dj_mix_len", "auto"))
        if self._dj_mix_len not in ("auto", "8", "16"):
            self._dj_mix_len = "auto"
        # Punchy mode: prefer energy-serving slams and avoid long blends.
        # Song-sensitive policy still protects emotional/cooling tracks.
        self._dj_slam_only = bool(conf.get("dj_slam_only", False))
        self._dj_bridges = {}      # bridge songid -> (a_id, b_id, label)
        self._dj_bridge_done = {}  # (a_id, b_id) -> "mix" | "skip"
        self._dj_pair_files = {}   # (a_id, b_id) -> (fa, fb, exit, entry)
        self._dj_gain_cache = {}   # file -> RG track gain dB (tag read)
        self._dj_last_trans = {}   # the hand-off awaiting a 👍/👎
        self._dj_render_key = None
        self._dj_render_started = 0.0   # watchdog clock for the render slot
        self._dj_last_skip = ""         # why the last pair didn't cut (UI)
        self._dj_next_style = ""
        self._dj_next_reason = ""
        # absolute-path playback needs the socket connection
        self._dj_bridge_ok = HOST.startswith("/")
        self._workers = WorkerRegistry()
        self._enrichment = EnrichmentCoordinator(self._workers)
        self._ensure_mpd_socket()
        self._idle_stop = threading.Event()
        self._idle_client = None
        self._idle_thread = None
        self._spec = None
        self._spec_owners = set()
        self._spectrum_module_ready = False
        self._spectrum_module_warming = False
        self._spectrum_frame_lock = threading.Lock()
        self._spectrum_latest = None
        self._spectrum_frame_timer = QTimer(self)
        self._spectrum_frame_timer.setInterval(67)
        self._spectrum_frame_timer.timeout.connect(
            self._publish_spectrum_frame)
        self._liked = []
        self._disliked = []
        self._deleting = False
        self._deletion_generation = 0
        self._playlists = []
        self._playlist_track_snapshots = {}
        self._playlist_track_generation = 0
        self._playlist_track_request = None
        self._playlist_read_failed = False
        self._generated_playlist_busy = False
        self._collection_refresh_busy = False
        self._collection_refresh_pending = False
        self._collection_refresh_generation = 0
        self._collection_refresh_failed = False
        self._playlist_repository = PlaylistRepository()
        self._library = LibraryRepository()
        self._library_directory = {}
        self._library_read_failed = False
        self._database_update_busy = False
        self._normalization_busy = False
        self._summary_shelves = ShelfService()
        self._home = HomeProjection()
        self._home_recommendations = []
        self._discover_overview = DiscoverProjection().build({})
        self._library_summary = {"shelves": [], "artists": []}
        self._library_ready = False   # first successful index not yet live
        self._library_playcounts: dict[str, int] = {}
        self._library_last_played: dict[str, str] = {}
        self._library_planning_ratings: dict[str, str] = {}
        self._library_preferences: dict[str, str] = {}
        self._library_planning_ready = False
        self._library_energies: dict[str, float] = {}
        self._library_bpms: dict[str, float] = {}
        self._smart_shelves: dict[str, list[dict]] = {}
        self._library_summary_failed = False
        self._rewind = RewindService()
        self._play_history = PlayHistoryRepository(PLAYLOG)
        self._rewind_overview = {
            "ready": False, "stats": {}, "history": {}, "chapters": [],
        }
        self._sound_profile_snapshot = {"ready": False, "data": {}}
        self._sound_profile_failed = False
        self._play_record_failed = False
        self._taste_mutation_failed = False
        self._taste_mutation_busy = False
        self._mixtapes = MixtapePlanner()
        self._mixtape_busy = False
        self._curated_plan_busy = False
        self._curated_plan_key = None
        self._smart_mix = SmartMixPlanner()
        self._search_index = []
        self._search_catalog = searchlib.SearchCatalog(
            artist_path=self.artistPath)
        self._library_indexer = LibraryIndexer(
            self._library, self._search_catalog,
            client_scope=lambda: temporary_mpd_client(
                HOST, PORT, timeout=30, registry=self._workers))
        self._index_result = LibraryIndexResult(False)
        self._lyric_indexer = searchlib.LyricIndexer(
            self._search_catalog, MUSIC_ROOT, read_lyrics=_read_lyrics)
        self._lyrics_index_ready = False
        self._lyrics_index_result = None
        self._xfade = 0
        self._audio_info = ""
        self._rg_track_db = None   # current file's ReplayGain track gain (dB)
        self._live_kbps = 0
        self._waveform = []
        self._lyrics = []
        self._lyrics_synced = False
        self._media = MediaEnrichmentService(
            MUSIC_ROOT, read_lyrics=_read_lyrics, average_kbps=_avg_kbps,
            tail_cut=self._compute_tail_cut, compute_wave=_compute_wave,
            wave_dir=WAVE_DIR, art_colors=_art_colors)
        self._prefetcher = MediaPrefetcher(
            warm_thumbnail=self._warm_thumbnail,
            warm_waveform=self._media.warm_waveform, sleep=time.sleep)
        self._biographies = BiographyService(
            Path(cache_path('bios')))
        self._artist_profiles = ArtistPortraitCoordinator(
            self._biographies, self._workers,
            canonicalize=canonical_artist_name,
            on_result=self.artistBioReady.emit,
            on_batch=self.artistPortraitsReady.emit)
        self._cache_maintenance = CacheMaintenanceService({
            "art": Path(cache_path('art')),
            "waveform": WAVE_DIR,
            "biographies": Path(cache_path('bios')),
        })
        self._metadata = MetadataService(
            MUSIC_ROOT, Path.home() / ".local/state/ampere/tag-backups")
        self._metadata_read_generation = 0
        self._metadata_update_busy = False
        self._energy_scanner = EnergyScanner(
            MUSIC_ROOT,
            client_scope=lambda: temporary_mpd_client(
                HOST, PORT, timeout=10, registry=self._workers))
        self._loudness_scanner = ReplayGainScanner(MUSIC_ROOT)
        self._mixramp_scanner = MixRampScanner(MUSIC_ROOT)
        self._library_deletion = LibraryDeletionService(MUSIC_ROOT)
        self._single = False
        # Leveling mode is OURS, persisted in config.json and pushed to MPD
        # on every connect — MPD's runtime replay_gain_mode resets to
        # mpd.conf on daemon restart, which silently flipped sessions back
        # to "auto" (= ALBUM gain on sequential play; up to 8 dB off the
        # track gain the DJ bridges bake in — the "hard volume jump").
        # Default "track": every song settles at the same perceived volume,
        # which is the app's leveling promise and what DJ math assumes.
        self._replay_gain = str(conf.get("rg_mode", "track"))
        if self._replay_gain not in ("off", "track", "album", "auto"):
            self._replay_gain = "track"
        self._rg_on_mode = (self._replay_gain if self._replay_gain != "off"
                            else str(conf.get("rg_on_mode", "track")))
        self._rg_preamp, self._rg_missing_preamp = self._read_preamps()
        self._art_colors = ["#8f8f97", "#5a5a62"]
        self._transition_fader = StreamTransitionController(
            resolve_stream=self._pw_mpd_stream,
            set_stream_volume=self._pw_set_stream_vol,
            schedule=QTimer.singleShot,
            run_io=self._run_stream_io,
        )
        self._idleEvent.connect(self._on_idle)
        self.moveRequested.connect(self._on_move_requested)
        self.volumeRequested.connect(self.requestVolume)
        self.remotePlayRequested.connect(self._on_remote_play_requested)
        self.transportRequested.connect(self.requestTransport)
        self.remoteCommandRequested.connect(self._on_remote_command_requested)
        self._deleteDone.connect(self._on_delete_done)
        self._deleteQueueReady.connect(self._on_delete_queue_ready)
        self._waveReady.connect(self._on_wave)
        self._songMetaReady.connect(self._on_song_meta)
        self._radioReady.connect(self._on_radio_ready)
        self._mixMapsReady.connect(self._on_mix_maps)
        self._doctorReady.connect(self._on_doctor)
        self._doctor = {}
        self._doctor_verified = {}
        self._doctor_busy = False
        # per-device volume memory (feature: outputs want different levels)
        self._vol_device = ""
        try:
            self._device_vols = {str(k): int(v) for k, v in
                                 (conf.get("device_volumes") or {}).items()}
        except (TypeError, ValueError):
            self._device_vols = {}
        self._colorsReady.connect(self._on_colors)
        self._bridgeReady.connect(self._on_bridge_ready)
        self._bridgeSpliceReady.connect(self._on_bridge_splice_ready)
        self._indexReady.connect(self._on_index_ready)
        self._librarySummaryReady.connect(self._on_library_summary_ready)
        self._soundProfileReady.connect(self._on_sound_profile_ready)
        self._mixtapeReady.connect(self._on_mixtape_ready)
        self._curatedPlanReady.connect(self._on_curated_plan_ready)
        self._playlistTracksReady.connect(self._on_playlist_tracks_ready)
        self._playlistCoversArrived.connect(self._on_playlist_covers)
        self._playlist_covers = {}
        self._collectionRefreshReady.connect(self._on_collection_refresh_ready)
        self._queueRefreshReady.connect(self._on_queue_refresh_ready)
        self._queueReorderReady.connect(self._on_queue_reorder_ready)
        self._queueIntentReady.connect(self._on_queue_intent_ready)
        self._contextShuffleReady.connect(self._on_context_shuffle_ready)
        self._playbackIntentReady.connect(self._on_playback_intent_ready)
        self._spectrumPrepared.connect(self._on_spectrum_prepared)
        self._statusRefreshReady.connect(self._on_status_refresh_ready)
        self._delayedStatusReady.connect(self._on_delayed_status_ready)
        self._pathActionReady.connect(self._on_path_action_ready)
        self._playlistActionReady.connect(self._on_playlist_action_ready)
        self._remotePlayReady.connect(self._on_remote_play_ready)
        self._djResetReady.connect(self._on_dj_reset_ready)
        self._djSessionReady.connect(self._on_dj_session_ready)
        self._djReplayReady.connect(self._on_dj_replay_ready)
        self._djSetSaveReady.connect(self._on_dj_set_save_ready)
        self._cacheClearReady.connect(self._on_cache_clear_ready)
        self._streamIoReady.connect(self._on_stream_io_ready)
        self._metadataReadReady.connect(self._on_metadata_read_ready)
        self._metadataUpdateReady.connect(self._on_metadata_update_ready)
        self._generatedPlaylistReady.connect(self._on_generated_playlist_ready)
        self._tasteMutationReady.connect(self._on_taste_mutation_ready)
        self._listeningProgressReady.connect(
            self._on_listening_progress_ready)
        self._preferredVersionReady.connect(
            self._on_preferred_version_ready)
        self._databaseUpdateReady.connect(self._on_database_update_ready)
        self._replayGainReady.connect(self._on_replay_gain_ready)
        self._transitionSettingsReady.connect(
            self._on_transition_settings_ready)
        self._normalizationReady.connect(self._on_normalization_ready)
        self._remoteLifecycleReady.connect(self._on_remote_lifecycle_ready)
        # tag-writing passes (loudness, energy) fire one database event per
        # file — debounce so the index rebuilds once per burst, not 400×
        self._db_timer = QTimer(self)
        self._db_timer.setSingleShot(True)
        self._db_timer.setInterval(4000)
        self._db_timer.timeout.connect(self._on_database_settled)
        self._conf_save_timer = QTimer(self)
        self._conf_save_timer.setSingleShot(True)
        self._conf_save_timer.setInterval(350)
        self._conf_save_timer.timeout.connect(self._save_conf)

        # DJ heartbeat: the planner must run MID-SONG (renders need lead
        # time to splice before the pair starts playing), but refreshStatus
        # is otherwise driven by MPD idle events and QML view timers —
        # neither is guaranteed while a song simply plays. Backend-owned,
        # so a hidden window can never starve a live set.
        self._dj_tick = QTimer(self)
        self._dj_tick.setInterval(4000)
        self._dj_tick.timeout.connect(self._on_dj_tick)
        self._dj_tick.start()
        self._status_tick = QTimer(self)
        self._status_tick.setInterval(1000)
        self._status_tick.timeout.connect(self.requestStatusRefresh)
        self._cur_songid = -1
        self._dj_resync_ts = 0.0

        # Stream-volume guard: _soft_move rides MPD's PipeWire stream volume
        # down and back up.  A kill mid-ride, or a stream that stays
        # unresolvable on the way back up, strands it at zero — MPD reports
        # playing, the UI looks normal, nothing comes out, and WirePlumber
        # saves that zero so the next session starts silent too.  Cheap poll;
        # only ever raises a stranded zero.
        self._stream_guard = QTimer(self)
        self._stream_guard.setInterval(5000)
        self._stream_guard.timeout.connect(self._heal_stream_volume)
        self._stream_guard.start()


    # ---- connection ----------------------------------------------------

    def _on_gateway_state(self, connected):
        connected = bool(connected)
        if connected != self._connected:
            self._connected = connected
            self.connectedChanged.emit()

    def _mark_disconnected(self):
        gateway = getattr(self, "_gateway", None)
        if gateway is not None:
            gateway.mark_disconnected()
        else:  # lightweight characterization-test adapters
            self._connected = False

    def start(self):
        self._persist_remote_token()
        self._ensure_connected(silent=True)
        self._idle_stop.clear()
        self._idle_thread = threading.Thread(
            target=self._idle_loop, name="ampere-mpd-idle", daemon=True)
        self._idle_thread.start()

    def _start_worker(self, target, *, args=(), name=None, durable=False):
        """Launch backend work through the process-owned lifecycle boundary."""
        return self._workers.start(
            target, args=args, name=name, durable=durable)

    def _lyrics_worker(self):
        self._lyrics_index_result = self._lyric_indexer.scan(
            should_stop=self._workers.stop_requested.is_set)

    def _start_lyrics_index(self):
        return self._enrichment.launch(
            "lyrics", self._lyrics_worker, coalesce=False,
            thread_name="ampere-lyrics",
            on_finished=self._on_lyrics_finished)

    def _on_lyrics_finished(self):
        result = self._lyrics_index_result
        self._lyrics_index_ready = bool(
            result is not None and result.published and not result.cancelled)
        # Ready and cancelled scans both change what the search surface should
        # do: publish results in the first case, retry the current generation
        # in the second.
        self.lyricsIndexChanged.emit()
        # Mutagen parses every file's tag block. Releasing its completed
        # arenas here prevents one on-demand lyric search from permanently
        # retaining the scan's multi-gigabyte high-water mark.
        release_unused_heap()
        if self._enrichment.consume_pending("lyrics"):
            self._lyrics_index_ready = False
            self._start_lyrics_index()

    @Slot(str, result="QVariantList")
    def searchLyrics(self, text):
        """Songs whose embedded lyrics contain the query, with a snippet."""
        if not self._lyrics_index_ready:
            self._start_lyrics_index()
        return self._search_catalog.lyric_query(text)

    def _ensure_connected(self, silent=False) -> bool:
        return self._gateway.ensure_connected(silent=silent)

    def _call(self, name, *args, default=None, quiet=False):
        """Run one MPD command with a single reconnect retry."""
        return self._gateway.call(name, *args, default=default, quiet=quiet)

    def _write(self, name, *args, quiet=False):
        """Run a MUTATING MPD command with the same single reconnect retry as
        the read path. Discrete user writes (like/dislike/rating) otherwise
        bypassed `_call` and silently dropped on a transient MPD blip. Returns
        True on success; emits on a hard CommandError unless quiet=True (e.g.
        clearing a sticker that may not exist). NOT for multi-command sequences
        (clear+add+play) — a per-command retry there would half-build the queue;
        those keep their own guards."""
        return self._gateway.write(name, *args, quiet=quiet)

    def _write_once(self, name, *args, quiet=False):
        """Run a relative/non-idempotent mutation without replaying it."""
        return self._gateway.write_once(name, *args, quiet=quiet)

    def _seek_current_once(self, seconds) -> bool:
        """Seek the current song without risking replay onto its successor.

        ``seekcur`` is position-relative to whichever song is current when MPD
        receives it.  If the reply is lost, reconnecting and retrying after a
        transition could therefore seek the next song.  Treat the dispatch as
        at-most-once and let the next heartbeat reconcile an ambiguous result.
        """
        try:
            target = float(seconds)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(target):
            return False
        target = max(0.0, target)
        if self._duration > 0:
            target = min(target, self._duration)
        return self._write_once("seekcur", round(target, 1))

    def _replace_queue(self, files, start_index=0) -> bool:
        """Stage a complete replacement before retiring the current queue.

        The controller appends and verifies every new entry first, then commits
        by stable MPD song ID. A rejected path or lost reply therefore cannot
        turn a valid queue into an empty or partially rebuilt one.
        """
        return self._playback.replace_queue(files, start_index)

    def _append_files(self, files, *, error_prefix="") -> bool:
        """Append one command-list after validating the shared GUI client.

        Unlike queue replacement this operation is not safe to retry: if MPD
        applied the list but the reply was lost, a retry would duplicate every
        track.  A preflight reconnect fixes the common stale-client case while
        preserving at-most-once append semantics.
        """
        return self._playback.append_files(files, error_prefix=error_prefix)

    def _request_generated_playlist_save(self, purpose, name, files, **context):
        """Persist one generated export without blocking Qt's thread."""
        name = str(name or "").strip()
        files = tuple(str(file) for file in files if file)
        if self._generated_playlist_busy or not name or not files:
            return False
        self._generated_playlist_busy = True
        payload = {
            "purpose": str(purpose), "name": name, "files": files,
            "context": dict(context), "success": False,
        }
        def work():
            success = False
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    def ensure_connected(silent=True):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            close_mpd_client(cli)
                            try:
                                cli.connect(HOST, PORT)
                                return True
                            except Exception:
                                return False

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except Exception:
                            return False

                    writer = GeneratedPlaylistWriter(
                        cli, ensure_connected=ensure_connected,
                        list_playlists=cli.listplaylists, write=write,
                        refresh=lambda: None)
                    rows = cli.listplaylists()
                    existing = tuple(
                        str(row.get("playlist") or "") for row in rows
                        if isinstance(row, dict) and row.get("playlist"))
                    success = writer.save(name, files, existing=existing)
            except Exception:
                success = False
            result = dict(payload)
            result["success"] = success
            self._generatedPlaylistReady.emit(result)

        if self._start_worker(
                work, name="ampere-generated-playlist", durable=True):
            return True
        self._generated_playlist_busy = False
        return False

    def _on_generated_playlist_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        self._generated_playlist_busy = False
        success = bool(payload.get("success"))
        name = str(payload.get("name") or "")
        files = tuple(payload.get("files") or ())
        context = payload.get("context") or {}
        if success:
            self._request_collection_refresh()
        purpose = payload.get("purpose")
        # The "profile" purpose retired with Saved Sound Profiles (6157232).
        if purpose == "beacon":
            self._beacon.save_finished(success)
        elif purpose == "recap":
            self.recapSaveFinished.emit(name, success)
        elif purpose == "mixtape":
            started = bool(success and self.playFiles(files, 0))
            self.mixtapeFinished.emit(
                name if success else "", len(files) if success else 0,
                started)
        elif purpose == "queue-save":
            message = str(context.get("message") or "")
            self.errorOccurred.emit(
                message if success else
                "Playlist could not be saved — the previous copy is intact")

    def _idle_loop(self):
        client = create_mpd_client()
        client.timeout = None
        self._idle_client = client
        try:
            while not self._idle_stop.is_set():
                try:
                    client.connect(HOST, PORT)
                    while not self._idle_stop.is_set():
                        subsystems = client.idle()
                        if not self._idle_stop.is_set():
                            self._idleEvent.emit(list(subsystems))
                except (MPDConnectionError, OSError):
                    close_mpd_client(client)
                    self._idle_stop.wait(2)
        finally:
            close_mpd_client(client)
            if self._idle_client is client:
                self._idle_client = None

    def _stop_idle_listener(self):
        """Wake and reap the blocking MPD-idle worker before daemon stop."""
        stop = getattr(self, "_idle_stop", None)
        if stop is not None:
            stop.set()
        client = getattr(self, "_idle_client", None)
        if client is not None:
            retire_mpd_writer(client)
        sock = getattr(client, "_sock", None) if client is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        thread = getattr(self, "_idle_thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._idle_thread = None

    def _on_idle(self, subsystems):
        if {"player", "mixer", "options"} & set(subsystems):
            self.requestStatusRefresh()
        if "playlist" in subsystems:
            self._request_queue_refresh()
        if "stored_playlist" in subsystems:
            self._request_collection_refresh()
        if "database" in subsystems:
            self._db_timer.start()

    def _on_database_settled(self):
        # rebuild runs on a worker; scans + lyrics + databaseUpdated fire
        # from _on_index_ready once the fresh index is live
        self._build_search_index()

    def _refresh_all(self):
        self.requestStatusRefresh()
        self._request_queue_refresh()
        self._request_collection_refresh()
        self._refresh_replay_gain()
        self._build_search_index()   # async; scans kick off on index-ready
        if self._remote_on:
            self._request_remote_lifecycle(True)

    def _build_search_index(self):
        """Rebuild the search index OFF the GUI thread.

        `listallinfo` over the whole library plus the parse is heavy, and
        the leveling/energy passes fire a database event per file — doing
        this inline froze the UI on every rebuild. A worker with its own
        short-lived connection builds the list and swaps the reference
        atomically; follow-up work runs in _on_index_ready on the GUI thread.
        Concurrent requests coalesce into a single trailing rebuild."""
        self._enrichment.launch(
            "index", self._index_worker, thread_name="ampere-library-index",
            coalesce=True, on_finished=self._emit_index_result)

    def _index_worker(self):
        result = self._library_indexer.rebuild()
        if result.success:
            songs = self._library.songs
            directory = {
                "albums": tuple(LibraryDirectory.albums(songs)),
                "artists": tuple(LibraryDirectory.artists(
                    songs, LibraryRepository.artist_path)),
                "genres": tuple(LibraryDirectory.genres(songs)),
                # Every folder's child rows are already derived with the
                # generation; the root is just one of them.
                "folders": tuple(self._library.folders("")),
                "songs": tuple(dict(song) for song in songs),
            }
            result = LibraryIndexResult(
                success=result.success,
                generation=result.generation,
                total=result.total,
                search_index=result.search_index,
                error=result.error,
                directory=directory,
            )
        self._index_result = result

    def _emit_index_result(self):
        self._indexReady.emit(self._index_result)

    def _on_index_ready(self, result):
        if result.success:
            # Compatibility snapshot for domains still awaiting extraction.
            self._search_index = list(result.search_index)
            if isinstance(result.directory, dict):
                self._library_directory = result.directory
            if not self._library_ready:
                self._library_ready = True
                self.libraryReadyChanged.emit()
            self.databaseUpdated.emit()
            # Energy inventory is cheap and incremental. ReplayGain is not:
            # verifying coverage opens every audio file, so it belongs to the
            # explicit leveling-enable path rather than every application
            # launch.
            self._start_energy_scan()
            if self._dj_on:
                self._start_dj_scan()
            # Embedded-lyric extraction reads every audio file's tag block.
            # Keep startup bounded and build that optional index only when a
            # lyric search actually asks for it.
            self._lyrics_index_ready = False
            self._lyrics_index_result = None
            self.lyricsIndexChanged.emit()
        if self._enrichment.consume_pending("index"):
            self._build_search_index()

    # ---- status --------------------------------------------------------

    @Slot()
    def refreshStatus(self):
        """Compatibility facade for a fresh, coalesced owned-client read."""
        Backend._invalidate_status_refresh(self)
        return self.requestStatusRefresh()

    def _read_heartbeat(self, cli, *, current_volume=None,
                        current_mixramp_db=None):
        status = cli.status()
        if status is None:
            return None
        song = cli.currentsong()
        return PlaybackHeartbeat.from_mpd(
            status, song, normalize_song=_song_map,
            current_volume=(self._volume if current_volume is None
                            else current_volume),
            current_mixramp_db=(self._mixrampdb
                                if current_mixramp_db is None
                                else current_mixramp_db))

    @Slot()
    def requestStatusRefresh(self):
        if self._status_refresh_busy:
            self._status_refresh_pending = True
            return False
        self._status_refresh_busy = True
        self._status_refresh_pending = False
        self._status_refresh_generation += 1
        generation = self._status_refresh_generation
        current_volume = self._volume
        current_mixramp_db = self._mixrampdb

        def work():
            heartbeat = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=5,
                        registry=self._workers) as cli:
                    heartbeat = self._read_heartbeat(
                        cli, current_volume=current_volume,
                        current_mixramp_db=current_mixramp_db)
            except Exception:
                heartbeat = None
            self._statusRefreshReady.emit({
                "generation": generation, "heartbeat": heartbeat,
            })

        if self._start_worker(work, name="ampere-status-refresh"):
            return True
        self._on_status_refresh_ready({
            "generation": generation, "heartbeat": None,
        })
        return False

    def _invalidate_status_refresh(self):
        self._status_refresh_generation = (
            getattr(self, "_status_refresh_generation", 0) + 1)
        if getattr(self, "_status_refresh_busy", False):
            self._status_refresh_pending = True

    def _on_status_refresh_ready(self, payload):
        if not isinstance(payload, dict):
            return
        generation = payload.get("generation")
        if generation != self._status_refresh_generation:
            self._status_refresh_busy = False
            if self._status_refresh_pending:
                self.requestStatusRefresh()
            return
        self._status_refresh_busy = False
        self._publish_heartbeat(payload.get("heartbeat"))
        if self._status_refresh_pending:
            self.requestStatusRefresh()

    def _sync_status_tick(self):
        tick = getattr(self, "_status_tick", None)
        if tick is None:
            return
        if self._state == "play":
            if not tick.isActive():
                tick.start()
        else:
            tick.stop()

    def _publish_heartbeat(self, heartbeat):
        if heartbeat is None:
            return False
        snapshot = heartbeat.status
        new_song = heartbeat.song
        self._state = snapshot.state
        self._elapsed = snapshot.elapsed
        self._duration = snapshot.duration
        self._volume = snapshot.volume
        self._random = snapshot.random
        self._repeat = snapshot.repeat
        self._single = snapshot.single
        _old_qpos = self._queue_pos
        self._queue_pos = snapshot.queue_pos
        if snapshot.queue_position_changed(_old_qpos):
            self.queuePosChanged.emit()
        self._cur_songid = snapshot.song_id
        self._xfade = snapshot.crossfade
        self._live_kbps = snapshot.bitrate_kbps
        self._mixrampdb = snapshot.mixramp_db
        mixramp = reconcile_mixramp(
            delay_on=snapshot.mixramp_delay_on,
            mix_style=self._mix_style, dj_active=self._dj_active,
            automix_on=self._automix_on)
        self._mixramp_on = mixramp.mixramp_on
        self._automix_on = mixramp.automix_on
        if mixramp.disable_daemon_delay:
            # Fade mode owns the switch: MPD's full-level add-mix must stay
            # disabled while Ampere applies the per-song crossfade.
            self._configure_transitions(
                mixramp_delay=None, crossfade=snapshot.crossfade,
                refresh=False)
        song_changed = new_song.get("file") != self._song.get("file")
        observation = self._listening_progress.observe(
            current_file=new_song.get("file", ""), elapsed=self._elapsed,
            duration=self._duration, song_changed=song_changed,
            dj_on=self._dj_on)
        if song_changed:
            self._enqueue_listening_progress(observation)
        if observation.update.backward_seek:
            # Backward seeks invalidate armed cuts and locked DJ plans; the
            # service detects the transition while Backend owns DJ state.
            self._dj_gen += 1
            self._dj_plan_key = None
        self._song = new_song
        if song_changed:
            self._apply_fade_xfade()
            self.songChanged.emit()
            self._start_wave(new_song.get("file", ""))
            self._start_colors(new_song.get("file", ""))
        if song_changed or not self._audio_info:
            # codec/kbps/rate + ReplayGain, lyrics, and the silent-tail cut ALL
            # open the file's header on disk — previously 2–3 synchronous opens
            # on the GUI thread per song change (a hitch every transition, far
            # worse on a network library). Do them on a worker; results apply
            # via _on_song_meta, guarded by the current file.
            self._start_song_meta(new_song.get("file", ""), self._duration)
        self._maybe_radio_refill()
        self._maybe_smart_refill()
        self._maybe_mix_extend()
        # DJ is FIREWALLED from playback: a bug anywhere in the planner (it's
        # under active development in ampere/dj/) must never stop the player's
        # status from updating. Swallow + log; never let it reach the UI.
        try:
            self._dj_plan()
        except Exception as exc:
            try:
                self._dj_log(f"plan CRASH — isolated from playback: {exc!r}")
            except Exception:
                pass
        self.statusChanged.emit()
        self._prefetch_upcoming()
        self._arm_trim()
        self._dj_schedule_reset_retry()
        self._sync_status_tick()
        return True

    # ---- trim silent endings -------------------------------------------------
    # Recordings with dead air at the end (hidden-track gaps, sloppy rips)
    # would otherwise play silence to the "real" end — or worse, crossfade
    # FROM silence. The MixRamp analysis already wrote each outro's
    # level-vs-time curve into the file; its deepest threshold marks where
    # the audio actually dies, and we advance there. Cutting inside pure
    # silence means the hard next() is inaudible by definition.

    @Property(bool, notify=settingsChanged)
    def trimSilence(self):
        return self._trim_on

    @Slot(bool)
    def setTrimSilence(self, on):
        self._trim_on = bool(on)
        self._save_conf()
        self.settingsChanged.emit()
        self._arm_trim()

    def _compute_tail_cut(self, file, duration=None):
        """Seconds into the track after which only silence remains, +pad.
        0 = no meaningful silent tail (or no analysis yet). `duration` is
        captured by the caller (the meta worker) so a later song change can't
        skew the math; falls back to self._duration for direct callers."""
        dur = self._duration if duration is None else duration
        if not file or dur <= 0:
            return 0.0
        try:
            mf = MutagenFile(os.path.join(MUSIC_ROOT, file))
            end = (mf.get("mixramp_end") or [""])[0]
        except Exception:
            return 0.0
        pairs = []
        for part in str(end).split(";"):
            try:
                db_s, t_s = part.split()
                pairs.append((float(db_s), float(t_s)))
            except ValueError:
                continue
        if not pairs:
            return 0.0
        pairs.sort()
        db, t = pairs[0]          # deepest threshold: last time above it
        if db > -55.0:            # outro never got near-silent — no tail
            return 0.0
        if dur - t < 1.5:
            return 0.0            # sub-1.5s tails aren't worth a cut
        return t + 0.6

    def _arm_trim(self):
        """(Re)schedule the silence cut for the playing song. A generation
        counter invalidates stale timers on every status change (seek,
        pause, song change)."""
        self._trim_gen += 1
        if (not self._trim_on or self._automix_on or self._single
                or self._state != "play" or self._tail_cut <= 0
                or (self._dj_on and self._dj_cut_at > 0)):
            return
        remain = self._tail_cut - self._elapsed
        gen = self._trim_gen
        song_id = self._cur_songid
        if remain <= 0:
            self._fire_trim(gen, song_id, immediate=True)
            return
        QTimer.singleShot(
            int(remain * 1000) + 60,
            lambda: self._fire_trim(gen, song_id))

    def _fire_trim(self, gen, song_id, immediate=False):
        if gen != self._trim_gen and not immediate:
            return
        self._request_delayed_status("trim", gen, song_id)

    def _request_delayed_status(self, kind, generation, song_id, context=None):
        """Verify a delayed transport action without blocking Qt's thread."""
        payload = {
            "kind": str(kind), "generation": int(generation),
            "songId": int(song_id), "context": dict(context or {}),
            "snapshot": None,
        }

        def work():
            snapshot = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=5,
                        registry=self._workers) as cli:
                    snapshot = djverify.validate_cut_snapshot(
                        cli.status(), payload["songId"])
            except Exception:
                snapshot = None
            result = dict(payload)
            result["snapshot"] = snapshot
            self._delayedStatusReady.emit(result)

        if self._start_worker(work, name="ampere-delayed-status"):
            return True
        self._delayedStatusReady.emit(payload)
        return False

    def _on_delayed_status_ready(self, payload):
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        snapshot = payload.get("snapshot")
        generation = payload.get("generation")
        if kind == "trim":
            if generation != self._trim_gen or snapshot is None:
                return
            if (self._trim_on and not self._automix_on and not self._single
                    and snapshot.valid and self._tail_cut > 0
                    and snapshot.elapsed >= self._tail_cut - 1.5):
                self._write_once("next")
            return
        self._dj_apply_delayed_status(kind, generation, snapshot,
                                      payload.get("context") or {})

    # ---- DJ mode (live-set transitions) --------------------------------------
    # Cut out of the current song at the end of a hot phrase and land on the
    # next song's drop, like a DJ slamming into the next record. Cue points
    # come from the joi_cues sticker (ampere.djcues). The transition itself is
    # pure MPD: `rangeid` slices the queued next song to entry:exit, and a
    # range end counts as a natural track end, so crossfade still applies —
    # sample-accurate, no audio processing at playback. MPD refuses rangeid
    # on the *playing* song, so only the first cut after enabling needs a
    # timer (same generation pattern as trim-silence).

    # the aggression dial: one knob instead of explaining gate thresholds.
    # CLEAN mixes only when everything is certain; CLASSIC is the house
    # default; WILD drops the gates, cuts earlier and may re-drop.
    DJ_GATES = {"clean":   (0.60, 0.70, 0.55),  # min conf, entry, exit score
                "classic": (0.50, 0.60, 0.45),
                "wild":    (0.35, 0.35, 0.28)}
    DJ_LEVEL_MIGRATE = {"curated": "classic", "all_in": "wild"}

    @Property(bool, notify=settingsChanged)
    def djOn(self):
        return self._dj_on

    @Slot(bool)
    def setDjMode(self, on):
        on = bool(on)
        if on == self._dj_on:
            return
        self._dj_on = on
        self._save_conf()
        if on:
            self._start_dj_scan()
            nxt = (self._queue[self._queue_pos + 1]
                   if 0 <= self._queue_pos < len(self._queue) - 1 else None)
            if nxt is not None and self._dj_cues(nxt.get("file", "")) is None:
                self.errorOccurred.emit(
                    "DJ mode: scoring your queue — cuts begin as songs are analyzed")
        else:
            self._dj_reset()
        self.settingsChanged.emit()
        self.requestStatusRefresh()

    @Property(str, notify=settingsChanged)
    def djLevel(self):
        return self._dj_level

    @Slot(str)
    def setDjLevel(self, level):
        level = self.DJ_LEVEL_MIGRATE.get(level, level)
        if level in self.DJ_GATES and level != self._dj_level:
            self._dj_level = level
            self._dj_plan_key = None   # re-gate the upcoming transition
            self._save_conf()
            self.settingsChanged.emit()
            self.refreshStatus()

    @Property(str, notify=settingsChanged)
    def djShape(self):
        return self._dj_shape

    @Slot(str)
    def setDjShape(self, shape):
        if shape in ("flat", "rise", "arc") and shape != self._dj_shape:
            self._dj_shape = shape
            self._save_conf()
            self.settingsChanged.emit()

    @Property(int, notify=settingsChanged)
    def djMinutes(self):
        return self._dj_minutes

    @Slot(int)
    def setDjMinutes(self, minutes):
        minutes = int(minutes)
        if minutes in (0, 30, 45, 60, 90) and minutes != self._dj_minutes:
            self._dj_minutes = minutes
            self._save_conf()
            self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def djB2b(self):
        return self._dj_b2b

    @Slot(str)
    def setDjB2b(self, room):
        room = (room or "").rstrip("/")
        if room != self._dj_b2b:
            self._dj_b2b = room
            self._save_conf()
            self.settingsChanged.emit()

    @Property(float, notify=statusChanged)
    def djCutAt(self):
        """Planned exit time (s) of the current song; 0 = no cut planned."""
        return self._dj_cut_at

    @Property(str, notify=statusChanged)
    def djNextReason(self):
        """The musical reason behind the upcoming hand-off."""
        return getattr(self, "_dj_next_reason", "")

    _KEY_NAMES = ("C", "D♭", "D", "E♭", "E", "F",
                  "F♯", "G", "A♭", "A", "B♭", "B")


    @Property("QVariantList", notify=statusChanged)
    def djTimeline(self):
        """The remaining set with the transition planned AFTER each song —
        the Deck's big set list. Per row: title/artist/file/dur plus the
        cue facts (bpm, key) when that song is scored."""
        if not self._dj_on:
            return []
        out = []
        q, pos = self._queue, self._queue_pos
        # while a bridge itself plays, the song it lands ON reads as "now"
        now_pos = pos
        if (0 <= pos < len(q)
                and q[pos].get("file", "").startswith("/")):
            now_pos = pos + 1
        i = max(0, pos)
        while i < len(q) and len(out) < 40:
            s = q[i]
            f = s.get("file", "")
            if f.startswith("/"):
                i += 1
                continue
            style = ""
            nxt = q[i + 1] if i + 1 < len(q) else None
            if nxt is not None and nxt.get("file", "").startswith("/"):
                style = self._dj_bridges.get(
                    nxt.get("id", -1), (0, 0, ""))[2] or "mix"
            elif i == pos:
                style = self._dj_next_style
            d = self._dj_cues(f)
            key_name, camelot = self._dj_key_label(
                d.get("key", -1) if d else -1)
            try:
                dur = float(s.get("duration", 0) or 0)
            except (TypeError, ValueError):
                dur = 0.0
            out.append({"title": s.get("title", "") or os.path.basename(f),
                        "artist": s.get("artist", ""),
                        "file": f, "style": style,
                        "dur": dur,
                        "bpm": int(round(float(d.get("bpm", 0)))) if d else 0,
                        "keyName": key_name, "camelot": camelot,
                        "reason": (self._dj_next_reason if i == now_pos else ""),
                        "scored": d is not None,
                        "now": i == now_pos})
            i += 1
        return out

    @Slot()
    def djCutNow(self):
        """The live-performance button: cut to the next song at the NEXT
        BAR boundary — quantized, so even a manual interrupt lands on
        beat — with the fader hand, never a raw skip."""
        if self._state != "play" or getattr(self, "_dj_cutnow_armed", False):
            return
        cur = self._song
        expected_song_id = self._cur_songid
        d = self._dj_cues(cur.get("file", ""))
        try:
            bpm = float((d or {}).get("bpm", 0) or 0)
            beat_zero = float((d or {}).get("b0", 0) or 0)
        except (TypeError, ValueError):
            bpm = beat_zero = 0.0
        gen = self._dj_gen
        self._dj_cutnow_armed = True
        return self._request_delayed_status(
            "dj-cut-now-arm", gen, expected_song_id, {
                "bpm": bpm, "beatZero": beat_zero,
                "rangeStart": cur.get("rangeStart", 0.0),
                "title": cur.get("title", ""),
                "songId": expected_song_id,
            })

    # ---- cue audition: preview a song's planned entry ----------------------

    @Slot(str)
    def djAudition(self, file):
        """Play ~6 s around a song's planned entry cue (over the music —
        a preview ear, not a deck switch)."""
        self.djAuditionStop()
        d = self._dj_cues(file)
        dur_full = float((d or {}).get("dur", 0.0) or 0.0)
        entry = None
        if d and d.get("in"):
            best = max(c[1] for c in d["in"])
            entry = min(c[0] for c in d["in"] if c[1] >= 0.85 * best)
        if entry is None:
            entry = dur_full * 0.3 if dur_full else 30.0
        start = max(0.0, entry - 1.5)
        src = os.path.join(MUSIC_ROOT, file)
        from .dj import bridge as _db
        gain = _db._track_gain(src)
        tmp = cache_path('audition.wav')
        gen = self._audition_begin()

        def work():
            try:
                r = subprocess.run(
                    ["nice", "-n", "10", "ffmpeg", "-y", "-v", "quiet",
                     "-ss", f"{start:.2f}", "-t", "6.0", "-i", src,
                     "-af", (f"volume={gain:.2f}dB,volume=-6dB,"
                             f"afade=t=in:d=0.15,afade=t=out:st=5.7:d=0.3"),
                     "-ar", "48000", tmp],
                    capture_output=True, timeout=30)
                if r.returncode == 0 and os.path.exists(tmp):
                    self._audition_play(gen, ["pw-play", tmp])
                else:
                    self._audition_failed(
                        gen, "Cue preview could not be rendered — try again")
            except (OSError, subprocess.TimeoutExpired):
                self._audition_failed(
                    gen, "Cue preview could not be rendered — try again")

        self._start_worker(work, name="ampere-cue-audition")

    def _audition_begin(self):
        """Cancel any running/in-flight audition and return a generation token.
        A worker MUST pass this token to _audition_play so a stop or a newer
        audition that raced ahead cancels it instead of orphaning a pw-play."""
        with self._audition_lock:
            self._audition_gen += 1
            p, self._audition_proc = self._audition_proc, None
        if p is not None and p.poll() is None:
            try:
                p.kill()
                p.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return self._audition_gen

    def _audition_play(self, gen, argv):
        """Start pw-play from a worker thread ONLY if `gen` is still current
        (no stop / newer audition raced in) — else do nothing, never orphan."""
        failed = False
        with self._audition_lock:
            if gen != self._audition_gen:
                return
            try:
                self._audition_proc = subprocess.Popen(
                    argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self._audition_proc = None
                failed = True
        if failed:
            self._audition_failed(
                gen, "Preview audio could not start — check the audio service")

    def _audition_failed(self, gen, message):
        """Publish failure only while the originating preview is current."""
        with self._audition_lock:
            if gen != self._audition_gen:
                return False
        self.errorOccurred.emit(message)
        return True

    @Slot()
    def djAuditionStop(self):
        self._audition_begin()   # bumps the generation + kills the current proc

    @Slot(str, str)
    def djAuditionSeam(self, a_file, b_file):
        """Audition the ACTUAL A→B transition before it plays (#12): render
        the same bridge the engine would use (mix or clean slam) and play a
        ~14 s window centred on its seam — the hand-off itself, not just 6 s
        of B's entry. A cut can be judged, and re-cut, before it goes live."""
        gen = self._audition_begin()   # cancels any prior audition, returns token
        if not a_file or not b_file or a_file.startswith("/") \
                or b_file.startswith("/"):
            return
        ca, cb = self._dj_cues(a_file), self._dj_cues(b_file)
        if not ca or not cb:
            self.errorOccurred.emit("Preview: those songs aren't scored yet")
            return
        intent = self._dj_transition_intent(a_file, ca, b_file, cb)
        if intent.style == "soft":
            self.errorOccurred.emit("Preview: " + intent.reason
                                    + " — the DJ will use a soft hand-off")
            return
        exit1 = self._dj_pick(ca, "out")
        entry2 = self._dj_pick(cb, "in")
        if exit1 is None or entry2 is None:
            self.errorOccurred.emit("Preview: no strong cut between these two "
                                    "— they'd crossfade")
            return
        bpm1, bpm2 = ca.get("bpm", 0), cb.get("bpm", 0)
        bass = min(ca.get("bcut", djbridge.BASS_SWAP_HZ),
                   cb.get("bcut", djbridge.BASS_SWAP_HZ))
        abs1 = os.path.join(MUSIC_ROOT, a_file)
        abs2 = os.path.join(MUSIC_ROOT, b_file)
        ta = self._dj_queue_title(a_file)
        tb = self._dj_queue_title(b_file)
        preview = Path(cache_path('seam-preview.flac'))
        win = cache_path('audition.wav')

        def work():
            try:
                from mutagen import File as MutagenFile
                if intent.style == "blend" and not self._dj_slam_only:
                    bars = self._dj_bars(bpm1)
                    ov, _ = djbridge.render(abs1, exit1, bpm1, abs2, entry2,
                                            bpm2, bars, preview, ta, tb,
                                            bass_hz=bass)
                else:
                    ov, _ = djbridge.render_slam(abs1, exit1, bpm1, abs2,
                                                 entry2, bpm2, preview, ta, tb)
                if ov <= 0 or not preview.exists():
                    self._audition_failed(
                        gen, "Transition preview could not be rendered — "
                        "try another cut")
                    return
                dur = float(getattr(MutagenFile(str(preview)).info,
                                    "length", 0.0))
                span = min(14.0, dur)
                start = max(0.0, dur * 0.5 - span * 0.45)
                r = subprocess.run(
                    ["nice", "-n", "10", "ffmpeg", "-y", "-v", "quiet",
                     "-ss", f"{start:.2f}", "-t", f"{span:.2f}",
                     "-i", str(preview), "-af",
                     f"afade=t=in:d=0.2,afade=t=out:st={span - 0.4:.2f}:d=0.4",
                     "-ar", "48000", win],
                    capture_output=True, timeout=45)
                if r.returncode == 0 and os.path.exists(win):
                    self._audition_play(gen, ["pw-play", win])
                else:
                    self._audition_failed(
                        gen, "Transition preview could not be rendered — "
                        "try another cut")
            except Exception:
                self._audition_failed(
                    gen, "Transition preview could not be rendered — "
                    "try another cut")

        self._start_worker(work, name="ampere-transition-audition")

    @Slot(str, str)
    def djNudgeCue(self, file, side):
        """Reject the drop/exit the planner is currently using for a song and
        fall to its next-strongest cue (#11) — a per-song 'use another drop'
        from the set list. Same machinery as a downvote's cue-ban (persisted,
        censored at read), but user-driven and non-punitive."""
        self._dj_nudge_cue(file, side)

    # ---- transition rating: the Deck learns his taste in cuts --------------

    VOTES_PATH = Path(cache_path('dj-votes.json'))





    @Property(str, notify=statusChanged)
    def djLastSkip(self):
        """Human reason the most recent candidate pair won't hard-cut."""
        return getattr(self, "_dj_last_skip", "")

    @Property("QVariantMap", notify=statusChanged)
    def djStyleStats(self):
        """Firing counts per style + recent seam-dB range — the deck's
        'what is the engine actually doing' readout (#5, #16)."""
        v = self._dj_votes()
        s = list(v.get("seam_samples", []))
        seam = {}
        if s:
            seam = {"n": len(s), "min": min(s), "max": max(s),
                    "avg": round(sum(s) / len(s), 1)}
        return {"fires": dict(v.get("style_fires", {})), "seam": seam}





    @Property(str, notify=statusChanged)
    def djLastTransition(self):
        """Label of the most recent completed hand-off ('' = none yet)."""
        return getattr(self, "_dj_last_trans", {}).get("label", "")


    @Property("QVariantMap", notify=statusChanged)
    def djLastTransitionInfo(self):
        """The hand-off awaiting a vote, with pretty titles for the pair
        and how many cuts this pair has already missed."""
        lt = getattr(self, "_dj_last_trans", {})
        key = f"{lt.get('a', '')}|{lt.get('b', '')}"
        return {"label": lt.get("label", ""),
                "a": lt.get("aT", ""), "b": lt.get("bT", ""),
                "strikes": self._dj_votes()["strikes"].get(key, 0)}

    DJ_MIX_TARGET_S = 20.0  # AUTO mix length aims for this many seconds of
                            # ride (phrase-aligned bars, see _dj_bars)
    DJ_CUE_BAN_WIN = 2.5    # s — a banned cut poisons its musical moment
    DJ_PAIR_STRIKES = 3     # failed re-cuts before a pair is done for good
    DJ_SEAM_DB = 6.0        # max dB the incoming landing may sit BELOW
                            # the outgoing exit (RG-adjusted)



    @Slot(bool)
    def voteTransition(self, up):
        lt = getattr(self, "_dj_last_trans", {})
        if not lt.get("label"):
            return
        v = self._dj_votes()
        key = f"{lt.get('a', '')}|{lt.get('b', '')}"
        if up:
            v["pairs"][key] = 1
            v["strikes"].pop(key, None)   # the re-cut redeemed the pair
            # a good hand-off also redeems its STYLE: one downvote comes
            # off the style's tally, so likes and dislikes balance instead
            # of penalties only ever accumulating
            w = self._dj_style_word(lt["label"])
            if v["style_downs"].get(w, 0) > 0:
                v["style_downs"][w] -= 1
        else:
            # a downvote means THAT CUT was wrong, not (yet) the pair:
            # ban the exact cut moments used so the next attempt re-cuts
            # both songs; three failed cuts and the pair never mixes again
            n = v["strikes"].get(key, 0) + 1
            v["strikes"][key] = n
            if n >= self.DJ_PAIR_STRIKES:
                v["pairs"][key] = -1
            self._dj_ban_cue(lt.get("a", ""), "out", lt.get("ca", 0.0))
            self._dj_ban_cue(lt.get("b", ""), "in", lt.get("cb", 0.0))
            w = self._dj_style_word(lt["label"])
            v["style_downs"][w] = v["style_downs"].get(w, 0) + 1
            v["style_down_ts"][w] = time.time()   # decay clock (planner)
        self._dj_save_votes()
        self._dj_last_trans = {}
        self.statusChanged.emit()

    def _ensure_mpd_socket(self):
        """Self-heal for fresh installs: rendered mixes need the unix
        socket (absolute-path playback). Adds the bind to mpd.conf, then
        restarts the daemon only when nothing is playing — otherwise the
        bind simply lands on MPD's next natural restart and mixes wake up
        on the following app launch."""
        if os.path.exists(MPD_SOCKET) or environment("MPD_HOST"):
            return
        try:
            self._mpd_config.ensure_socket_binding()
        except OSError:
            return
        def activate():
            try:
                with temporary_mpd_client(
                        "127.0.0.1", PORT, timeout=3,
                        registry=self._workers) as probe:
                    status = probe.status()
            except Exception:
                return
            if self._mpd_config.socket_restart_safe(status):
                subprocess.run(
                    ["systemctl", "--user", "restart", "mpd"],
                    check=False)

        # The config write is local and atomic; daemon I/O and systemd can
        # each stall. Own both through the worker registry so Backend
        # construction never waits and shutdown still accounts for the task.
        self._start_worker(
            activate, name="ampere-mpd-socket-activation", durable=True)
















    # ---- rendered mixes (bridges) --------------------------------------------
    # The heavy default: for the NEXT upcoming pair (both still queued, both
    # still rangeable), render a 16/8-bar beatmatched transition offline and
    # splice it between them. The playing pair can't be re-sliced (MPD
    # refuses rangeid on the current song), so mixes are always prepared one
    # transition ahead — the first hand-off of a fresh session slams, the
    # rest mix.



    @Slot()
    def analyzeDjCues(self):
        """Score the whole library for DJ cue points (background)."""
        self._start_dj_scan(quiet=False)

    def _start_dj_scan(self, sweep=True, quiet=True):
        if self._enrichment.running("dj"):
            if not quiet:
                self.errorOccurred.emit("DJ cue analysis already running")
            return
        # the upcoming queue jumps the line so cuts start within minutes,
        # not after a full library pass
        for s in self._queue[self._queue_pos + 1: self._queue_pos + 21]:
            f = s.get("file", "")
            if f and f not in self._dj_prio and f not in self._disliked:
                self._dj_prio.append(f)
        files = ([e["song"]["file"] for e in self._search_index
                  if e["song"]["file"] not in self._disliked]
                 if sweep else [])
        if not files and not self._dj_prio:
            return
        self._enrichment.launch(
            "dj", self._dj_scan_worker, args=(files,),
            thread_name="ampere-dj-scan")


    # ---- DJ sessions ---------------------------------------------------------
    # The DJ Deck page: pick a room (genre) or start from the playing song,
    # and a SET is built — cut-ready songs ranked by cue confidence, chained
    # by tempo — then DJ transitions run for the length of the session.
    # This is the only place DJ mode lives: no session, no cuts.

    @Property(str, notify=settingsChanged)
    def djSeed(self):
        """Label of the live session's seed room ('' = no session)."""
        return self._dj_seed_label

    @Property(str, notify=settingsChanged)
    def djRange(self):
        return self._dj_range

    @Slot(str)
    def setDjRange(self, r):
        if r in ("room", "progressive", "free") and r != self._dj_range:
            self._dj_range = r
            self._dj_plan_key = None   # re-gate the upcoming hand-off
            self._save_conf()
            self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def djMixLen(self):
        return self._dj_mix_len

    @Slot(str)
    def setDjMixLen(self, v):
        if v in ("auto", "8", "16") and v != self._dj_mix_len:
            self._dj_mix_len = v
            self._dj_bridge_done = {k: s for k, s in
                                    self._dj_bridge_done.items()
                                    if s == "mix"}   # re-judge skipped pairs
            self._save_conf()
            self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def djSlamOnly(self):
        return self._dj_slam_only

    @Slot(bool)
    def setDjSlamOnly(self, on):
        on = bool(on)
        if on != self._dj_slam_only:
            self._dj_slam_only = on
            # re-decide the upcoming transition and re-judge already-planned
            # pairs so the switch takes effect on the very next cut
            self._dj_plan_key = None
            self._dj_bridge_done = {}
            self._save_conf()
            self.settingsChanged.emit()
            self.refreshStatus()

    @Property(str, notify=statusChanged)
    def djNextStyle(self):
        """Human description of the upcoming transition ('' = plain)."""
        return self._dj_next_style







    @Slot(str, bool, result="QVariantMap")
    def djPoolStats(self, seed, is_file):
        """Room readiness for the Deck page: how many songs, how many
        scored, how many would actually earn a cut at the current level."""
        pool, label = self._dj_pool(seed, is_file)
        cues = self._dj_cue_map(pool)
        usable = sum(1 for d in cues.values() if self._dj_usable(d)[0] > 0)
        out = {"total": len(pool), "scored": len(cues),
               "usable": usable, "label": label, "rooms": 0}
        if self._dj_range == "progressive":
            # how many rooms the journey could tour from here
            rooms = self._dj_rooms()
            all_cues = self._dj_cue_map(
                [f for fl in rooms.values() for f in fl])
            n = 0
            for r, fl in rooms.items():
                if self._dj_top(r) in self.DJ_ROUTE_EXCLUDE:
                    continue
                ok = sum(1 for f in fl
                         if f in all_cues
                         and self._dj_usable(all_cues[f])[0] > 0)
                if ok >= 3:
                    n += 1
            out["rooms"] = n
        return out

    @staticmethod
    def _camelot_nl(k):
        """key int (0-11 major, 12+ minor) → (Camelot number 1-12, letter
        L where 0=A/minor, 1=B/major), or None when the key is unknown."""
        if k is None or k < 0:
            return None
        minor = int(k) >= 12
        tonic = (int(k) % 12 + 9) % 12          # semitones above A → above C
        num = ((tonic * 7) % 12 + (4 if minor else 7)) % 12 + 1
        return num, (0 if minor else 1)

    # Camelot compatibility, same letter, keyed by number delta mod 12 —
    # a direct encode of the harmonic-mixing ruleset (Mixed In Key / DJ
    # TechTools / Digital DJ Tips, researched 2026-07-18):
    #   0 same · ±1 perfect fifth/fourth (adjacent) · +2/-2 whole-tone
    #   energy boost/drop · +7=up a semitone (harsh) · 6 = tritone (avoid).
    _KEY_COMPAT_SAME = {0: 1.00, 1: 0.90, 11: 0.90, 2: 0.60, 10: 0.50,
                        7: 0.40, 5: 0.40, 3: 0.20, 9: 0.20, 4: 0.20,
                        8: 0.20, 6: 0.05}

    @classmethod
    def _key_compat01(cls, k1, k2):
        """Graded harmonic compatibility of two keys in [0,1]. 1.0 = same
        key; 0.90 = adjacent fifth; 0.85 = relative major/minor; 0.75/0.55 =
        the two diagonal moves; 0.60 = +2-semitone energy boost; down to
        0.05 for a tritone. An UNKNOWN key on either side returns 0.5 —
        deliberately neutral, so it neither rewards nor penalises."""
        a = cls._camelot_nl(k1)
        b = cls._camelot_nl(k2)
        if a is None or b is None:
            return 0.5
        (na, la), (nb, lb) = a, b
        d = (nb - na) % 12
        if la == lb:
            return cls._KEY_COMPAT_SAME.get(d, 0.2)
        if d == 0:
            return 0.85                      # relative major/minor
        if (la == 0 and d == 11) or (la == 1 and d == 1):
            return 0.75                      # canonical diagonal
        if (la == 0 and d == 1) or (la == 1 and d == 11):
            return 0.55                      # reverse diagonal
        return 0.25                          # cross-mode gamble

    @classmethod
    def _key_compat(cls, k1, k2):
        """Legacy 0..2 closeness (kept for the set-order chain). Derived
        from the graded score so there is one source of truth."""
        if k1 is None or k2 is None or k1 < 0 or k2 < 0:
            return 0
        return 2.0 * cls._key_compat01(k1, k2)

    # NOTE: mid-bridge pitch-shift (a `_dj_key_shift` that pitched B into A's
    # key) was removed 2026-07-19 — it snapped the key back at the drop and
    # thinned the seam. Harmonic mixing here is key-AWARENESS only: clashes
    # route to slam / short blend in _dj_prep. Do NOT re-add pitch-shift
    # without a full-song-shift design (see NOTES.md).








    DJ_SEG = 7        # songs per room segment on a journey
    DJ_HOPS = 9       # max rooms a journey tours
    # staging dirs are grab-bags, not genres — their centroid averages the
    # whole library and would route into every journey. Seedable, and fair
    # game in free-for-all, but never a journey hop.
    DJ_ROUTE_EXCLUDE = ("Incoming",)



    def _dj_session_request_key(self, seed, is_file):
        return (str(seed), bool(is_file), self._dj_range, self._dj_b2b,
                bool(self._dj_sting), int(self._dj_minutes), self._dj_level,
                self._dj_shape)

    @Slot(str, bool, result=bool)
    def startDjSession(self, seed, is_file):
        if getattr(self, "_beacon", None):
            self._beacon.cancel()
        if self._dj_session_busy:
            self.errorOccurred.emit("A DJ set is already being planned")
            return False
        key = self._dj_session_request_key(seed, is_file)
        self._dj_session_busy = True
        self._dj_session_generation += 1
        generation = self._dj_session_generation
        coordinator = getattr(self, "_queue_mutations", None)
        queue_generation = coordinator.generation if coordinator else 0

        def work():
            payload = {
                "generation": generation, "key": key,
                "queueGeneration": queue_generation, "ordered": (),
                "queueFiles": (), "pool": (), "label": "",
                "anthems": (), "b2bActive": False, "error": "",
            }
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=30,
                        registry=self._workers) as cli:
                    pool, label = self._dj_pool(seed, is_file)
                    if not pool:
                        payload["error"] = "No songs found in that room"
                    else:
                        seed_file = seed if is_file else ""
                        b2b_active = bool(self._dj_b2b and not is_file)
                        if b2b_active:
                            pool_b, label_b = self._dj_pool(
                                self._dj_b2b, False)
                            set_a = self._dj_build_set(
                                pool, seed_file, cli)
                            set_b = (self._dj_build_set(pool_b, "", cli)
                                     if pool_b else [])
                            ordered = []
                            for a, b in zip(set_a, set_b):
                                ordered += [a, b]
                            ordered += set_a[len(set_b):] or set_b[len(set_a):]
                            if label_b:
                                label = f"{label} ⇄ {label_b}"
                        elif self._dj_range == "progressive":
                            seed_room = (self._dj_room_of(seed) if is_file
                                         else seed.rstrip("/"))
                            ordered = self._dj_build_journey(
                                seed_room, seed_file, cli)
                        elif self._dj_range == "free":
                            files = [
                                e["song"]["file"] for e in self._search_index
                                if e["song"]["file"] not in self._disliked]
                            ordered = self._dj_build_set(
                                files, seed_file, cli)
                        else:
                            ordered = self._dj_build_set(
                                pool, seed_file, cli)
                        if not ordered:
                            payload["error"] = (
                                "Nothing cue-scored there yet — let the "
                                "analysis run and try again")
                        else:
                            ordered = self._dj_apply_time(
                                ordered, self._dj_cue_map(ordered, cli), cli)
                            queue_files = list(ordered)
                            if self._dj_sting:
                                try:
                                    sting = self._dj_ensure_sting()
                                    if sting:
                                        queue_files.insert(0, sting)
                                except Exception:
                                    pass
                            payload.update({
                                "ordered": tuple(ordered),
                                "queueFiles": tuple(queue_files),
                                "pool": tuple(pool), "label": label,
                                "anthems": tuple(
                                    self._dj_find_anthems(ordered, cli)),
                                "b2bActive": b2b_active,
                            })
            except Exception:
                payload["error"] = "DJ planning data is unavailable — try again"
            self._djSessionReady.emit(payload)

        if self._start_worker(work, name="ampere-dj-session-plan"):
            return True
        self._dj_session_busy = False
        self.errorOccurred.emit("DJ planning could not start while Ampere is closing")
        return False

    def _on_dj_session_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("generation") != self._dj_session_generation:
            return False
        self._dj_session_busy = False
        key = payload.get("key")
        if (not key
                or key != self._dj_session_request_key(key[0], key[1])):
            self.errorOccurred.emit(
                "DJ settings changed while the set was planning — start it again")
            return False
        coordinator = getattr(self, "_queue_mutations", None)
        if (coordinator and payload.get("queueGeneration")
                != coordinator.generation):
            self.errorOccurred.emit(
                "The queue changed while the DJ set was planning — try again")
            return False
        error = str(payload.get("error") or "")
        ordered = list(payload.get("ordered") or ())
        if error or not ordered:
            self.errorOccurred.emit(error or "DJ planning did not produce a set")
            return False
        request = {
            "files": tuple(payload.get("queueFiles") or ()),
            "startIndex": 0,
        }
        return self._request_queue_intent(
            "replace", request,
            on_finished=lambda success: self._finish_dj_session_start(
                payload, success))

    def _finish_dj_session_start(self, payload, success):
        if not success:
            return False
        ordered = list(payload.get("ordered") or ())
        if self._mix_on:
            self.smartMixOff()   # the set has its own order
        self._dj_b2b_active = bool(payload.get("b2bActive"))
        self._dj_anthems = set(payload.get("anthems") or ())
        self._dj_redropped = set()
        label = str(payload.get("label") or "")
        self._dj_set_log = {"songs": list(ordered), "label": label,
                            "started": time.time(), "transitions": []}
        self._dj_seed_label = label
        self._dj_on = True
        self._dj_plan_key = None
        self._save_conf()
        # deepen the scan behind the set: the set itself, then the room
        for f in ordered + list(payload.get("pool") or ())[:200]:
            if f not in self._dj_prio:
                self._dj_prio.append(f)
        self._start_dj_scan()
        self.settingsChanged.emit()
        self.refreshStatus()
        return True


    @Slot()
    def replayLastSet(self):
        """Re-queue the most recent saved set exactly — bridges come from
        cache, so the same show plays again."""
        if self._dj_replay_busy:
            self.errorOccurred.emit(
                "The last DJ set is already being prepared")
            return False
        self._dj_replay_busy = True
        self._dj_replay_generation += 1
        generation = self._dj_replay_generation
        coordinator = getattr(self, "_queue_mutations", None)
        queue_generation = coordinator.generation if coordinator else 0
        known = frozenset(self._library.by_file)
        directory = Path(cache_path('sets'))

        def work():
            catalog = load_saved_sets(directory)
            selection = select_replayable_set(
                catalog.sets, known,
                absolute_exists=lambda file: Path(file).is_file())
            self._djReplayReady.emit({
                "generation": generation,
                "queueGeneration": queue_generation,
                "catalog": catalog,
                "selection": selection,
            })

        if self._start_worker(work, name="ampere-dj-set-replay"):
            return True
        self._dj_replay_busy = False
        self.errorOccurred.emit(
            "Saved set replay could not start while Ampere is closing")
        return False

    def _on_dj_replay_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("generation") != self._dj_replay_generation:
            return False
        self._dj_replay_busy = False
        coordinator = getattr(self, "_queue_mutations", None)
        if (coordinator and payload.get("queueGeneration")
                != coordinator.generation):
            self.errorOccurred.emit(
                "The queue changed while the saved set was loading — try again")
            return False
        catalog = payload.get("catalog")
        selection = payload.get("selection")
        if catalog is None or selection is None:
            self.errorOccurred.emit("Saved set history is unavailable")
            return False
        if catalog.error:
            self.errorOccurred.emit("Saved set history is unavailable")
            return False
        if not catalog.sets:
            if catalog.invalid:
                self.errorOccurred.emit("Saved set history is unreadable")
                return False
            self.errorOccurred.emit("No saved sets yet")
            return False
        if not selection.data:
            self.errorOccurred.emit("Every song from that set has left the library")
            return False
        data = selection.data
        available = list(selection.songs)
        return self._request_queue_intent(
            "replace", {"files": tuple(available), "startIndex": 0},
            on_finished=lambda success: self._finish_dj_replay_start(
                data, available, success))

    def _finish_dj_replay_start(self, data, available, success):
        if not success:
            return False
        if self._mix_on:
            self.smartMixOff()
        self._dj_seed_label = data.get("label", "replay")
        self._dj_on = True
        self._dj_plan_key = None
        self._dj_anthems = set()
        self._dj_redropped = set()
        self._dj_set_log = {"songs": available, "label": self._dj_seed_label,
                            "started": time.time(), "transitions": []}
        self._save_conf()
        for f in available:
            if f not in self._dj_prio:
                self._dj_prio.append(f)
        self._start_dj_scan()
        self.settingsChanged.emit()
        self.refreshStatus()
        return True

    def _on_dj_set_save_ready(self, success):
        if success:
            self._dj_set_save_failed = False
            return True
        if not getattr(self, "_dj_set_save_failed", False):
            self.errorOccurred.emit(
                "DJ set history could not be saved — Replay Last Set may "
                "miss this session; check storage permissions")
        self._dj_set_save_failed = True
        return False

    @Property(bool, notify=settingsChanged)
    def djSting(self):
        return self._dj_sting

    @Slot(bool)
    def setDjSting(self, on):
        self._dj_sting = bool(on)
        self._save_conf()
        self.settingsChanged.emit()

    @Slot()
    def endDjSession(self):
        if not self._dj_on:
            return
        self._dj_on = False
        self._dj_seed_label = ""
        if self._dj_set_log:
            self._dj_save_set()
        self._dj_anthems = set()
        self._dj_b2b_active = False
        self._save_conf()
        self._dj_reset()
        self.settingsChanged.emit()
        self.refreshStatus()

    def _prefetch_upcoming(self):
        """Warm the caches for what's about to play so transitions never
        hitch: art thumbnails for the next 15 songs, waveforms for the
        next 3 (waveforms decode the whole file — 3 ahead is plenty, and
        MPD itself pre-buffers the next track's audio). Skip-existing
        makes repeat passes free."""
        if self._queue_pos < 0:
            return
        upcoming = [s.get("file", "")
                    for s in self._queue[self._queue_pos + 1: self._queue_pos + 16]]
        upcoming = [f for f in upcoming if f]
        self._prefetcher.request(
            upcoming,
            launch=lambda work: self._start_worker(
                work, name="ampere-prefetch"),
            should_stop=self._workers.stop_requested.is_set)

    @staticmethod
    def _warm_thumbnail(file):
        from .artprovider import warm_thumb
        warm_thumb(file)

    def _start_colors(self, file):
        if not file:
            return
        generation = self._media.begin(file, "colors")
        self._start_worker(
            lambda: self._colorsReady.emit(
                generation, file, self._media.read_art_colors(file)),
            name="ampere-art-colors")

    def _on_colors(self, generation, file, colors):
        if self._media.accepts(
                generation, file, self._song.get("file", ""), "colors"):
            self._art_colors = list(colors)
            self.artColorsChanged.emit()

    @Property("QVariantList", notify=artColorsChanged)
    def artColors(self):
        return self._art_colors

    def _load_lyrics(self, file):
        if file:
            self._lyrics, self._lyrics_synced = _read_lyrics(os.path.join(MUSIC_ROOT, file))
        else:
            self._lyrics, self._lyrics_synced = [], False
        self.lyricsChanged.emit()

    @Property("QVariantList", notify=lyricsChanged)
    def lyrics(self):
        return self._lyrics

    @Property(bool, notify=lyricsChanged)
    def lyricsSynced(self):
        return self._lyrics_synced

    # ---- waveform (peak envelope for the seek bar) -----------------------

    def _start_wave(self, file):
        self._waveform = []
        self.waveformChanged.emit()
        if not file:
            return
        generation = self._media.begin(file, "wave")

        def work():
            self._waveReady.emit(
                generation, file, self._media.read_waveform(file))

        self._start_worker(work, name="ampere-waveform")

    def _on_wave(self, generation, file, peaks):
        if self._media.accepts(
                generation, file, self._song.get("file", ""), "wave"):
            self._waveform = list(peaks)
            self.waveformChanged.emit()

    def _start_song_meta(self, file, duration):
        """Read codec/kbps/rate + ReplayGain, lyrics, and the silent-tail cut
        on a WORKER thread — every one opens the file header, and doing them
        synchronously on song change hitched the GUI (3 opens; far worse on a
        network library). Results apply in _on_song_meta, guarded by file."""
        # Invalidate the previous track synchronously. In particular, a stale
        # tail cut must never remain armed while network-backed metadata for a
        # new song is loading or if worker launch is rejected during shutdown.
        self._audio_info = Path(file).suffix.lstrip(".").upper() if file else ""
        self._rg_track_db = None
        self._lyrics, self._lyrics_synced = [], False
        self._tail_cut = 0.0
        self.statusChanged.emit()
        self.lyricsChanged.emit()
        self._arm_trim()
        generation = self._media.begin(file, "metadata")
        if not file:
            return

        def work():
            result = self._media.read_song(file, duration)
            self._songMetaReady.emit(generation, file, result.as_mapping())

        self._start_worker(work, name="ampere-song-metadata")

    def _on_song_meta(self, generation, file, m):
        if not self._media.accepts(
                generation, file, self._song.get("file", "")):
            return
        self._audio_info = m["info"]
        self._rg_track_db = m["rg"]
        self._lyrics = m["lyrics"]
        self._lyrics_synced = m["synced"]
        self._tail_cut = m["tail"]
        self._apply_fade_xfade(
            m.get("mixramp_end", ""), m.get("replay_gain_text", "0 dB"))
        self.statusChanged.emit()
        self.lyricsChanged.emit()
        self._arm_trim()   # tail_cut just arrived — (re)arm the silent-tail trim

    @Property("QVariantList", notify=waveformChanged)
    def waveform(self):
        return self._waveform

    @Property("QVariantList", notify=waveformChanged)
    def waveTrim(self):
        """[start_frac, end_frac] of the played slice within the FULL-file
        waveform (#18). A DJ-ranged song reports slice-relative
        elapsed/duration but its cached envelope is the whole file, so the
        seek bar used to show the played region in the wrong place. WaveSeek
        clips the silhouette to this window. [0.0, 1.0] = unsliced."""
        cur = self._song
        rs = float(cur.get("rangeStart", 0.0) or 0.0)
        re_ = float(cur.get("rangeEnd", 0.0) or 0.0)
        if rs <= 0.0 and re_ <= 0.0:
            return [0.0, 1.0]
        d = self._dj_cues(cur.get("file", ""))
        full = float((d or {}).get("dur", 0.0) or 0.0)
        if full <= 0.0:
            return [0.0, 1.0]
        a = max(0.0, min(1.0, rs / full))
        b = min(1.0, (re_ / full) if re_ > 0 else 1.0)
        if b - a < 0.02:
            return [0.0, 1.0]
        return [round(a, 4), round(b, 4)]

    def _invalidate_queue_refresh(self):
        self._queue_refresh_generation = (
            getattr(self, "_queue_refresh_generation", 0) + 1)
        if getattr(self, "_queue_refresh_busy", False):
            self._queue_refresh_pending = True

    def _request_queue_refresh(self):
        if self._queue_refresh_busy:
            self._queue_refresh_pending = True
            return False
        self._queue_refresh_busy = True
        self._queue_refresh_pending = False
        self._queue_refresh_generation += 1
        generation = self._queue_refresh_generation

        def work():
            result = None
            playhead_status = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    staged = QueueSnapshotStore(normalize=_song_map)
                    result = staged.publish(cli.playlistinfo())
                    try:
                        playhead_status = cli.status()
                    except Exception:
                        playhead_status = None
            except Exception:
                result = None
            self._queueRefreshReady.emit({
                "generation": generation, "result": result,
                "playheadStatus": playhead_status,
            })

        if self._start_worker(work, name="ampere-queue-refresh"):
            return True
        self._on_queue_refresh_ready({
            "generation": generation, "result": None,
        })
        return False

    def _on_queue_refresh_ready(self, payload):
        if not isinstance(payload, dict):
            return
        generation = payload.get("generation")
        if generation != self._queue_refresh_generation:
            self._queue_refresh_busy = False
            if self._queue_refresh_pending:
                self._request_queue_refresh()
            return
        if self._queue_refresh_pending:
            self._queue_refresh_busy = False
            self._request_queue_refresh()
            return
        self._queue_refresh_busy = False
        result = payload.get("result")
        if not isinstance(result, QueueSnapshotResult) or not result.success:
            if not self._queue_refresh_failed:
                self._queue_refresh_failed = True
                self.errorOccurred.emit(
                    "Queue could not be refreshed — keeping the last "
                    "verified order")
            return
        published = self._queue_snapshots.publish_normalized(result.songs)
        if not published.success:
            return Backend._on_queue_refresh_ready(self, {
                "generation": generation, "result": None,
            })
        self._queue = list(published.songs)
        self._queue_refresh_failed = False
        try:
            self._dj_sweep_stale(payload.get("playheadStatus"))
        except Exception as exc:
            try:
                self._dj_log(f"sweep CRASH — isolated from playback: {exc!r}")
            except Exception:
                pass
        self.queueChanged.emit()
        self.requestStatusRefresh()

    def refreshQueue(self):
        """Compatibility entry point for explicit authoritative reconciliation."""
        return self._request_queue_refresh()

    def _invalidate_collection_refresh(self):
        self._collection_refresh_generation = (
            getattr(self, "_collection_refresh_generation", 0) + 1)
        if getattr(self, "_collection_refresh_busy", False):
            self._collection_refresh_pending = True

    def _request_collection_refresh(self):
        if self._collection_refresh_busy:
            self._collection_refresh_pending = True
            return False
        self._collection_refresh_busy = True
        self._collection_refresh_pending = False
        self._collection_refresh_generation += 1
        generation = self._collection_refresh_generation

        def work():
            result = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    catalog = cli.listplaylists()
                    liked = _read_optional_playlist(cli, LIKED_PLAYLIST)
                    disliked = _read_optional_playlist(cli, DISLIKED_PLAYLIST)
                staged = PlaylistRepository()
                published = staged.publish_playlists(catalog)
                if not published.success:
                    raise ValueError("invalid playlist catalog")
                staged.replace_liked(liked)
                staged.replace_disliked(disliked)
                snapshot = staged.snapshot
                result = {
                    "playlists": snapshot.playlists,
                    "liked": snapshot.liked,
                    "disliked": snapshot.disliked,
                }
            except Exception:
                result = None
            self._collectionRefreshReady.emit({
                "generation": generation, "result": result,
            })

        if self._start_worker(work, name="ampere-collection-refresh"):
            return True
        self._on_collection_refresh_ready({
            "generation": generation, "result": None,
        })
        return False

    def _on_collection_refresh_ready(self, payload):
        if not isinstance(payload, dict):
            return
        generation = payload.get("generation")
        current = self._collection_refresh_generation
        if generation != current:
            self._collection_refresh_busy = False
            if self._collection_refresh_pending:
                self._request_collection_refresh()
            return
        self._collection_refresh_busy = False
        result = payload.get("result")
        valid = (isinstance(result, dict)
                 and isinstance(result.get("playlists"), (list, tuple))
                 and isinstance(result.get("liked"), (list, tuple))
                 and isinstance(result.get("disliked"), (list, tuple))
                 and all(isinstance(value, str) for name in (
                     "playlists", "liked", "disliked")
                         for value in result[name]))
        if not valid:
            if not self._collection_refresh_failed:
                self._collection_refresh_failed = True
                self.errorOccurred.emit(
                    "Collections could not be refreshed — keeping the last "
                    "verified Playlists, Liked, and Disliked state")
        else:
            changed = self._playlist_repository.replace_snapshot(
                playlists=result["playlists"], liked=result["liked"],
                disliked=result["disliked"])
            self._playlists = list(self._playlist_repository.snapshot.playlists)
            self._liked = list(self._playlist_repository.snapshot.liked)
            self._disliked = list(self._playlist_repository.snapshot.disliked)
            self._collection_refresh_failed = False
            if changed[0]:
                self.playlistsChanged.emit()
            if changed[1]:
                self.likedChanged.emit()
            if changed[2]:
                self.dislikedChanged.emit()
        if self._collection_refresh_pending:
            self._request_collection_refresh()

    # ---- likes (the "Liked" playlist IS the store) ---------------------------

    @Property("QVariantList", notify=likedChanged)
    def likedFiles(self):
        return self._liked

    def _report_taste_mutation(self, success, message):
        """Surface one warning per failed taste-persistence episode."""
        if success:
            self._taste_mutation_failed = False
            return
        if not getattr(self, "_taste_mutation_failed", False):
            self._taste_mutation_failed = True
            self.errorOccurred.emit(message)

    def _request_taste_mutation(self, kind, file):
        file = str(file or "")
        if not file:
            return False
        if self._taste_mutation_busy:
            self.errorOccurred.emit("Still saving your last rating")
            return False
        self._taste_mutation_busy = True
        self._invalidate_collection_refresh()
        current_file = str(self._song.get("file") or "")

        def work():
            payload = {"kind": kind, "file": file, "update": None,
                       "liked": (), "disliked": (), "retired": ()}
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    repository = PlaylistRepository()
                    raw_liked = tuple(str(value) for value in
                                      (_read_optional_playlist(cli, LIKED_PLAYLIST) or ()))
                    raw_disliked = tuple(
                        str(value) for value in
                        (_read_optional_playlist(cli, DISLIKED_PLAYLIST) or ()))
                    library_files = {
                        str(row.get("file") or "")
                        for row in (cli.listall() or ())
                        if isinstance(row, dict) and row.get("file")
                    }
                    active = (raw_liked if kind == "like"
                              else raw_disliked)
                    restoring = file in active
                    if file not in library_files and not restoring:
                        raise ValueError(
                            "Taste target is not present in the MPD library")

                    # MPD permits stored playlists to retain paths that have
                    # since left its database, but rejects those paths when a
                    # playlist is transactionally rebuilt. Clean only the
                    # collection(s) this action will actually rewrite. A
                    # missing clicked item remains long enough to be restored
                    # from its active taste collection.
                    def current_files(values, *, preserve_target=False):
                        return tuple(
                            value for value in values
                            if value in library_files
                            or (preserve_target and value == file))

                    adding = not restoring
                    if kind == "like":
                        liked = current_files(
                            raw_liked, preserve_target=restoring)
                        disliked = (current_files(raw_disliked)
                                     if adding and file in raw_disliked
                                     else raw_disliked)
                    else:
                        disliked = current_files(
                            raw_disliked, preserve_target=restoring)
                        liked = (current_files(raw_liked)
                                 if adding and file in raw_liked
                                 else raw_liked)
                    payload["retired"] = tuple(dict.fromkeys(
                        value for source, prepared in (
                            (raw_liked, liked),
                            (raw_disliked, disliked),
                        ) for value in source if value not in prepared))
                    repository.replace_snapshot(
                        playlists=(), liked=liked, disliked=disliked)

                    def read(command, *args, default=None, **_kwargs):
                        try:
                            return getattr(cli, command)(*args)
                        except Exception:
                            return default

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except Exception:
                            return False

                    def ensure_connected(silent=True):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            close_mpd_client(cli)
                            try:
                                cli.connect(HOST, PORT)
                                return True
                            except Exception:
                                return False

                    def replace(name, files):
                        files = tuple(str(value) for value in files if value)
                        if not files:
                            return write("playlistclear", name)
                        writer = GeneratedPlaylistWriter(
                            cli, ensure_connected=ensure_connected,
                            list_playlists=cli.listplaylists, write=write,
                            refresh=lambda: None)
                        return writer.save(name, files, existing=(name,))

                    service = TasteService(
                        repository, read=read, write=write,
                        replace_files=replace)
                    update = (service.toggle_like(file) if kind == "like"
                              else service.toggle_dislike(
                                  file, current_file=current_file))
                    payload.update({
                        "update": update, "liked": service.liked,
                        "disliked": service.disliked,
                    })
            except Exception:
                pass
            self._tasteMutationReady.emit(payload)

        if self._start_worker(
                work, name="ampere-taste-mutation", durable=True):
            return True
        self._taste_mutation_busy = False
        return False

    def _on_taste_mutation_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        self._taste_mutation_busy = False
        update = payload.get("update")
        if not isinstance(update, TasteUpdate):
            self._report_taste_mutation(
                False, "Taste change could not be saved — your previous "
                "collections are still active")
            return False
        kind = payload.get("kind")
        action = "Like" if kind == "like" else "Dislike"
        message = (
            f"{action} could not be saved and recovery was incomplete — "
            "refresh Library Doctor before editing taste again"
            if not update.rollback_complete else
            f"{action} could not be saved — "
            "your previous taste collections are still active")
        self._report_taste_mutation(update.success, message)
        if update.success:
            playlists = self._playlist_repository.snapshot.playlists
            liked = tuple(payload.get("liked") or ())
            disliked = tuple(payload.get("disliked") or ())
            liked_changed, disliked_changed = (
                liked != tuple(self._liked), disliked != tuple(self._disliked))
            self._playlist_repository.replace_snapshot(
                playlists=playlists, liked=liked, disliked=disliked)
            self._liked, self._disliked = list(liked), list(disliked)
            if liked_changed:
                self.likedChanged.emit()
            if disliked_changed:
                self.dislikedChanged.emit()
            file = str(payload.get("file") or "")
            if file and file in disliked:
                self._request_disliked_queue_cleanup(file)
        elif not update.rollback_complete:
            self._request_collection_refresh()
        return update.success

    @Slot(str, result=bool)
    def toggleLike(self, file):
        return self._request_taste_mutation("like", file)

    # ---- dislikes (the "Disliked" playlist IS the store) ---------------------
    # Disliking skips the song and benches it from radio/smart picks; the
    # Disliked page can then purge the files from the library for real.

    def _drop_disliked(self, files, keep=""):
        """Disliked songs cannot cross any selector or queue boundary.

        ``keep`` remains as a compatibility argument for older callers, but a
        newly disliked file must be restored before it can be queued again.
        """
        del keep
        return self._playlist_repository.filter_allowed(files)

    def _drop_unavailable_library_files(self, files):
        """Keep only members present in the last verified MPD generation.

        Stored playlists can outlive files removed from the music database.
        Once a complete library generation exists, that immutable snapshot is
        the authority for whether an explicit selection can be staged.  Before
        the first generation lands we preserve the prior behavior rather than
        treating an unknown library as an empty one.
        """
        files = [str(file) for file in files if file]
        library = getattr(self, "_library", None)
        if library is None or not getattr(library, "generation", 0):
            return files
        by_file = getattr(library, "by_file", {})
        available = [file for file in files if file in by_file]
        skipped = len(files) - len(available)
        if skipped:
            print(
                f"Ampere playlist: skipped {skipped} unavailable "
                f"track{'s' if skipped != 1 else ''}",
                flush=True,
            )
        return available

    def _request_disliked_queue_cleanup(self, file):
        """Serialize post-persistence queue cleanup behind any active intent."""
        file = str(file or "")
        if not file:
            return False
        pending = getattr(self, "_pending_disliked_cleanup", None)
        if pending is None:
            pending = self._pending_disliked_cleanup = []
        if file not in pending:
            pending.append(file)
        return self._drain_disliked_queue_cleanup()

    def _drain_disliked_queue_cleanup(self):
        pending = getattr(self, "_pending_disliked_cleanup", [])
        coordinator = getattr(self, "_queue_mutations", None)
        if not pending or (coordinator and coordinator.active_owner):
            return bool(pending)
        file = pending[0]
        accepted = self._request_queue_intent(
            "bench-disliked", {"file": file})
        if accepted:
            pending.pop(0)
        return bool(accepted)

    @Property("QVariantList", notify=dislikedChanged)
    def dislikedFiles(self):
        return self._disliked

    @Property("QVariantList", notify=dislikedChanged)
    def dislikedSongs(self):
        """Full song maps for the Disliked page (title/artist/duration)."""
        return [self.songInfo(f) for f in self._disliked]

    @Slot(str, result="QVariantMap")
    def songInfo(self, file):
        """Song map for any library file (title/artist/album/duration)."""
        for e in self._search_index:
            if e["song"]["file"] == file:
                return e["song"]
        return {"file": file, "title": file.rsplit("/", 1)[-1],
                "artist": "", "album": "", "duration": 0}

    @Slot(str, result=bool)
    def toggleDislike(self, file):
        return self._request_taste_mutation("dislike", file)

    @Property(str, notify=settingsChanged)
    def deleteMode(self):
        """"server" when deletes go to the library master over ssh."""
        return "server" if (self._delete_remote_host and self._delete_remote_root) else "local"

    @Property(bool, notify=deletionStateChanged)
    def deletingDisliked(self):
        return self._deleting

    @Slot("QVariantList")
    def deleteDislikedSongs(self, files):
        """Permanently delete the given disliked songs from the library
        (the Disliked page confirms first). Server mode removes the files
        from the library MASTER over ssh — sync and Plex propagate the
        removal to every device; local mode removes the files here."""
        files = [f for f in files if f in self._disliked]
        if self._deleting or not files:
            return
        self._deleting = True
        self.deletionStateChanged.emit()
        if not self._start_worker(
                self._delete_worker, args=(files,),
                name="ampere-library-delete", durable=True):
            self._deleting = False
            self.deletionStateChanged.emit()
            self.errorOccurred.emit("Deletion could not start while Ampere is closing")

    def _delete_worker(self, files):
        service = getattr(self, "_library_deletion", None) or \
            LibraryDeletionService(MUSIC_ROOT)
        deleted, failed = service.delete(
            files, remote_host=self._delete_remote_host,
            remote_root=self._delete_remote_root)
        # Queue cleanup is admitted by the shared asynchronous intent boundary
        # after this filesystem worker publishes its result.
        self._deleteDone.emit(deleted, failed)

    def _on_delete_done(self, deleted, failed):
        gone = set(deleted)
        try:
            survivors = [f for f in self._disliked if f not in gone]
            matching = [song for song in self._queue
                        if song.get("file") in gone]
            stable_ids = []
            for song in matching:
                try:
                    song_id = int(song.get("id", -1))
                except (TypeError, ValueError):
                    continue
                if song_id >= 0:
                    stable_ids.append(song_id)
            ids_complete = len(stable_ids) == len(matching)
            self._invalidate_queue_refresh()
            self._invalidate_collection_refresh()
            self._deletion_generation += 1
            context = {
                "generation": self._deletion_generation,
                "deleted": tuple(deleted), "failed": tuple(failed),
                "survivors": tuple(survivors), "gone": tuple(gone),
            }
            if not ids_complete:
                return self._continue_delete_queue_reconciliation(
                    context, False)
            if not stable_ids:
                return self._continue_delete_queue_reconciliation(
                    context, True)
            return self._request_queue_intent(
                "remove", {"songIds": tuple(stable_ids)},
                on_finished=lambda success:
                    self._continue_delete_queue_reconciliation(
                        context, success))
        except Exception as exc:
            self.errorOccurred.emit(f"Library cleanup was interrupted: {exc}")
            self._finish_delete_reconciliation(
                deleted, failed, False, False)
            return False

    def _continue_delete_queue_reconciliation(self, context, removal_ok):
        context = dict(context)
        context["removalOk"] = bool(removal_ok)
        return self._start_delete_queue_reconciliation(context)

    def _start_delete_queue_reconciliation(self, context):
        def work():
            result = None
            update = None
            disliked = None
            disliked_verified = False
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    survivors = tuple(context.get("survivors") or ())

                    def ensure_connected(silent=True):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            close_mpd_client(cli)
                            try:
                                cli.connect(HOST, PORT)
                                return True
                            except Exception:
                                return False

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except Exception:
                            return False

                    def read(command, *args, default=None, **_kwargs):
                        try:
                            return getattr(cli, command)(*args)
                        except Exception:
                            return default

                    update = LibraryUpdateController(
                        read=read, write_once=write).request()

                    if survivors:
                        rows = cli.listplaylists()
                        existing = tuple(
                            str(row.get("playlist") or "") for row in rows
                            if isinstance(row, dict) and row.get("playlist"))
                        writer = GeneratedPlaylistWriter(
                            cli, ensure_connected=ensure_connected,
                            list_playlists=cli.listplaylists, write=write,
                            refresh=lambda: None)
                        wrote = writer.save(
                            DISLIKED_PLAYLIST, survivors,
                            existing=existing)
                    else:
                        wrote = write("playlistclear", DISLIKED_PLAYLIST)
                    try:
                        disliked = tuple(str(file) for file in
                                          cli.listplaylist(DISLIKED_PLAYLIST))
                    except Exception:
                        disliked = None
                    disliked_verified = bool(
                        wrote and disliked == survivors
                        and set(context.get("gone", ())).isdisjoint(disliked))
                    staged = QueueSnapshotStore(normalize=_song_map)
                    result = staged.publish(cli.playlistinfo())
            except Exception:
                result = None
            payload = dict(context)
            payload["result"] = result
            payload["disliked"] = disliked
            payload["dislikedVerified"] = disliked_verified
            payload["libraryUpdate"] = update
            self._deleteQueueReady.emit(payload)

        if self._start_worker(
                work, name="ampere-delete-queue-reconcile", durable=True):
            return True
        payload = dict(context)
        payload["result"] = None
        self._on_delete_queue_ready(payload)
        return False

    def _on_delete_queue_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("generation") != self._deletion_generation:
            return False
        result = payload.get("result")
        published = None
        if isinstance(result, QueueSnapshotResult) and result.success:
            published = self._queue_snapshots.publish_normalized(result.songs)
        queue_verified = bool(
            payload.get("removalOk") and published and published.success
            and all(song.get("file") not in set(payload.get("gone", ()))
                    for song in published.songs))
        disliked_verified = bool(payload.get("dislikedVerified"))
        update = payload.get("libraryUpdate")
        if isinstance(update, LibraryUpdateResult) and not update.success:
            detail = ("could not be confirmed" if not update.confirmed
                      else "could not start")
            self.errorOccurred.emit(
                f"Library files were deleted, but index refresh {detail}")
        if disliked_verified:
            disliked = tuple(payload.get("disliked") or ())
            changed = disliked != tuple(self._disliked)
            snapshot = self._playlist_repository.snapshot
            self._playlist_repository.replace_snapshot(
                playlists=snapshot.playlists, liked=snapshot.liked,
                disliked=disliked)
            self._disliked = list(disliked)
            if changed:
                self.dislikedChanged.emit()
        if published and published.success:
            self._queue = list(published.songs)
            self.queueChanged.emit()
            self.requestStatusRefresh()
        self._finish_delete_reconciliation(
            payload.get("deleted", ()), payload.get("failed", ()),
            disliked_verified, queue_verified)
        return queue_verified

    def _finish_delete_reconciliation(self, deleted, failed,
                                      disliked_verified, queue_verified):
        self._deleting = False
        self.deletionStateChanged.emit()
        outcome = DeletionReconciliation(
            deleted=len(deleted), failed=len(failed),
            disliked_verified=disliked_verified,
            queue_verified=queue_verified)
        self.dislikedDeleted.emit(outcome.message())

    # ---- properties for QML ---------------------------------------------

    @Property(bool, notify=connectedChanged)
    def connected(self):
        return self._connected

    @Property(str, notify=statusChanged)
    def state(self):
        return self._state

    @Property(float, notify=statusChanged)
    def elapsed(self):
        return self._elapsed

    @Property(float, notify=statusChanged)
    def duration(self):
        return self._duration

    @Property(int, notify=statusChanged)
    def volume(self):
        return self._volume

    @Property(bool, notify=statusChanged)
    def random(self):
        return self._random

    @Property(bool, notify=statusChanged)
    def repeat(self):
        return self._repeat

    @Property(int, notify=queuePosChanged)
    def queuePos(self):
        return self._queue_pos

    @Property(int, notify=statusChanged)
    def crossfade(self):
        # in fade mode MPD's xfade is retuned per song — the slider shows
        # (and edits) the base value, which fades untagged files
        return self._xfade_base if self._fade_active() else self._xfade

    @Property(str, notify=statusChanged)
    def mixStyle(self):
        return self._mix_style

    @Property(float, notify=statusChanged)
    def mixRampDb(self):
        return self._mixrampdb

    @Property(bool, notify=statusChanged)
    def mixRampOn(self):
        return self._mixramp_on

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Property(str, notify=statusChanged)
    def audioInfo(self):
        return self._audio_info

    @Property(str, notify=statusChanged)
    def gainText(self):
        """The leveling meter: what ReplayGain is doing to THIS track.
        "" when leveling is off; "untagged" flags files the loudness scan
        hasn't reached (those are WHY volumes jump)."""
        if self._replay_gain == "off":
            return ""
        if self._rg_track_db is None:
            if not self._song.get("file"):
                return ""
            return f"untagged · {self._rg_missing_preamp:+.0f} dB"
        total = self._rg_track_db + self._rg_preamp
        return f"{total:+.1f} dB"

    @Property(int, notify=statusChanged)
    def liveKbps(self):
        return self._live_kbps

    @Property(str, notify=songChanged)
    def currentGenre(self):
        file = self._song.get("file", "")
        return file.split("/")[0] if "/" in file else ""

    @Property("QVariantMap", notify=songChanged)
    def currentSong(self):
        return self._song

    @Property("QVariantList", notify=queueChanged)
    def queue(self):
        return self._queue

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return len(self._queue)

    @Property(int, notify=queueWindowChanged)
    def queueRemainingCount(self):
        return max(0, len(self._queue) - max(0, self._queue_pos) - 1)

    @Property(float, notify=queueWindowChanged)
    def queueRemainingSeconds(self):
        start = max(0, self._queue_pos + 1)
        return sum(float(song.get("duration") or 0)
                   for song in self._queue[start:])

    @Property("QVariantList", notify=queueWindowChanged)
    def upcomingQueue(self):
        start = max(0, self._queue_pos + 1)
        return self._queue[start:start + 12]

    @Property(int, notify=queueWindowChanged)
    def visibleQueuePlayPos(self):
        position = self._queue_pos
        if not 0 <= position < len(self._queue):
            return position
        file = str(self._queue[position].get("file") or "")
        return position + 1 if file.startswith("/") else position

    @Property("QVariantList", notify=playlistsChanged)
    def playlists(self):
        return self._playlists

    @Property("QVariantMap", notify=playlistUsageChanged)
    def playlistPlayCounts(self):
        return dict(self._playlist_play_counts)

    # ---- transport -------------------------------------------------------

    def _run_playback_intent(self, key, request):
        """Execute one bounded interactive intent on an owned MPD client."""
        messages = []
        result = None
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=5, registry=self._workers) as cli:
                controller = PlaybackController(
                    cli, ensure_connected=lambda silent=False: True,
                    mark_disconnected=lambda: None, error=messages.append)
                if key == "transport":
                    result = controller.set_state(request["state"])
                elif key == "volume":
                    result = controller.set_volume(request["value"])
                elif key == "repeat":
                    result = controller.set_repeat_mode(
                        request["repeat"], request["single"])
                elif key == "random":
                    result = controller.set_random_mode(request["enabled"])
                elif key == "seek":
                    cli.seekcur(request["seconds"])
                    result = True
                elif key == "move":
                    getattr(cli, request["command"])()
                    result = True
        except Exception as exc:
            messages.append(str(exc))
        self._playbackIntentReady.emit({
            "key": key, "request": dict(request), "result": result,
            "messages": tuple(messages),
        })

    def _start_playback_intent(self, key, request):
        self._playback_intent_active.add(key)

        def work():
            self._run_playback_intent(key, request)

        if self._start_worker(work, name=f"ampere-playback-{key}"):
            return True
        self._playback_intent_active.discard(key)
        self._playback_intent_pending.pop(key, None)
        if key == "transport":
            self._transport_intent_target = None
        elif key == "repeat":
            self._repeat_intent_target = None
        self.errorOccurred.emit(
            "Playback command could not start while Ampere is closing")
        callback = request.get("onFinished")
        if callable(callback):
            callback(False, "Playback command could not start while Ampere is closing")
        return False

    def _request_playback_intent(self, key, request, *, on_finished=None):
        request = dict(request)
        if key in ("repeat", "random") and getattr(self, "_beacon", None):
            self._beacon.cancel()
        if on_finished is not None:
            request["onFinished"] = on_finished
        if key in self._playback_intent_active:
            superseded = self._playback_intent_pending.get(key)
            callback = (superseded or {}).get("onFinished")
            if callable(callback):
                callback(False, "Superseded by a newer phone command")
            self._playback_intent_pending[key] = request
            return True
        return self._start_playback_intent(key, request)

    def _publish_volume_result(self, result):
        if not isinstance(result, PlaybackVolumeResult):
            return False
        Backend._invalidate_status_refresh(self)
        if result.committed and self._vol_device:
            self._device_vols[self._vol_device] = result.value
            self._conf_save_timer.start()
        if result.value is not None and self._volume != result.value:
            self._volume = result.value
            self.statusChanged.emit()
        return result.committed

    def _on_playback_intent_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        key = str(payload.get("key") or "")
        request = dict(payload.get("request") or {})
        result = payload.get("result")
        self._playback_intent_active.discard(key)

        committed = False
        if key == "transport" and isinstance(result, PlaybackStateResult):
            committed = self._publish_playback_state(result)
        elif key == "volume":
            committed = self._publish_volume_result(result)
        elif key == "repeat" and isinstance(result, PlaybackOptionsResult):
            self._repeat, self._single = result.repeat, result.single
            self.statusChanged.emit()
            committed = result.committed
        elif key == "random" and isinstance(result, PlaybackBooleanResult):
            if self._random != result.value:
                self._random = result.value
                self.statusChanged.emit()
            committed = result.committed
        elif key in ("seek", "move") and result is True:
            committed = True
            Backend._invalidate_status_refresh(self)
            self.requestStatusRefresh()
            if key == "move":
                self._request_queue_refresh()

        if not committed:
            messages = tuple(payload.get("messages") or ())
            if messages:
                self.errorOccurred.emit(str(messages[-1]))

        callback = request.get("onFinished")
        if callable(callback):
            messages = tuple(payload.get("messages") or ())
            detail = str(messages[-1]) if messages else (
                "Playback command could not be verified" if not committed else "")
            callback(committed, detail)

        pending = self._playback_intent_pending.pop(key, None)
        if pending is not None:
            self._start_playback_intent(key, pending)
        elif key == "transport":
            self._transport_intent_target = None
        elif key == "repeat":
            self._repeat_intent_target = None
        return committed

    @Slot()
    def requestPlayPause(self):
        state = self._transport_intent_target or self._state
        desired = "pause" if state == "play" else "play"
        self._transport_intent_target = desired
        return self._request_playback_intent(
            "transport", {"state": desired})

    @Slot(str)
    def requestTransport(self, action):
        action = str(action or "")
        if action == "toggle":
            return self.requestPlayPause()
        if action not in ("play", "pause", "stop"):
            return False
        self._transport_intent_target = action
        return self._request_playback_intent(
            "transport", {"state": action})

    @Slot(int)
    def requestVolume(self, vol):
        value = max(0, min(100, int(vol)))
        return self._request_playback_intent("volume", {"value": value})

    @Slot(float)
    def requestSeek(self, seconds):
        try:
            target = float(seconds)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(target):
            return False
        target = max(0.0, target)
        if self._duration > 0:
            target = min(target, self._duration)
        return self._request_playback_intent(
            "seek", {"seconds": round(target, 1)})

    def _request_move(self, command):
        if command not in ("next", "previous"):
            return False
        return self._request_playback_intent(
            "move", {"command": command})

    def _request_previous_action(self, on_finished=None):
        """Restart a settled track; otherwise move to the prior queue item.

        This is the single Previous-button policy for QML, MPRIS, media keys,
        and the phone remote.  Seeking does not need the transition fade; an
        actual queue move keeps the existing soft-switch treatment.
        """
        if self._elapsed >= PREVIOUS_RESTART_SECONDS:
            return self._request_playback_intent(
                "seek", {"seconds": 0.0}, on_finished=on_finished)
        self._soft_move(lambda: self._request_playback_intent(
            "move", {"command": "previous"}, on_finished=on_finished))
        return True

    @Slot()
    def requestNext(self):
        self._soft_move(lambda: self._request_move("next"))
        return True

    @Slot()
    def requestPrevious(self):
        return self._request_previous_action()

    @Slot()
    def requestCycleRepeat(self):
        repeat, single = self._repeat_intent_target or (
            self._repeat, self._single)
        if not repeat:
            request = {"repeat": True, "single": False}
        elif not single:
            request = {"repeat": True, "single": True}
        else:
            request = {"repeat": False, "single": False}
        self._repeat_intent_target = (
            request["repeat"], request["single"])
        return self._request_playback_intent("repeat", request)

    @Slot(bool)
    def requestRandom(self, enabled):
        return self._request_playback_intent(
            "random", {"enabled": bool(enabled)})

    @Slot(str)
    def requestLoopStatus(self, mode):
        desired = {
            "None": (False, False),
            "Playlist": (True, False),
            "Track": (True, True),
        }.get(str(mode))
        if desired is None:
            return False
        self._repeat_intent_target = desired
        return self._request_playback_intent(
            "repeat", {"repeat": desired[0], "single": desired[1]})

    @Slot()
    def playPause(self):
        return self._publish_playback_state(self._playback.toggle_state())

    def _publish_playback_state(self, result):
        Backend._invalidate_status_refresh(self)
        if result.state != self._state:
            self._state = result.state
            self.statusChanged.emit()
        self._sync_status_tick()
        return result.committed

    @Slot()
    def play(self):
        return self._publish_playback_state(self._playback.set_state("play"))

    @Slot()
    def pause(self):
        return self._publish_playback_state(self._playback.set_state("pause"))

    @Slot(str)
    def _on_transport_requested(self, action):
        if action == "toggle":
            return self.playPause()
        if action in ("play", "pause", "stop"):
            return self._publish_playback_state(
                self._playback.set_state(action))
        return False

    def _pw_mpd_stream(self):
        """(pulse sink-input index, raw volume) of MPD's PipeWire stream,
        or (None, 0). Resolved fresh per skip — the index changes whenever
        MPD reopens its output."""
        try:
            out = subprocess.run(
                ["pactl", "--format=json", "list", "sink-inputs"],
                capture_output=True, text=True, timeout=1)
            for si in json.loads(out.stdout or "[]"):
                props = si.get("properties", {})
                if props.get("application.name") == "Music Player Daemon":
                    vols = [v.get("value", 65536)
                            for v in si.get("volume", {}).values()
                            if isinstance(v, dict)]
                    return si["index"], (vols[0] if vols else 65536)
        except Exception:
            pass
        return None, 0

    def _pw_set_stream_vol(self, idx, value):
        subprocess.run(
            ["pactl", "set-sink-input-volume", str(idx), str(max(0, value))],
            capture_output=True, timeout=1)

    def _run_stream_io(self, operation, done):
        """Run one PipeWire discovery/write away from Qt's thread."""
        def work():
            try:
                result = operation()
            except Exception:
                result = None
            self._streamIoReady.emit((done, result))

        if self._start_worker(work, name="ampere-stream-transition"):
            return True
        done(None)
        return False

    def _on_stream_io_ready(self, payload):
        if (not isinstance(payload, tuple) or len(payload) != 2
                or not callable(payload[0])):
            return False
        callback, result = payload
        callback(result)
        return True

    def _heal_stream_volume(self):
        if self._state != "play":
            return
        self._transition_fader.heal(
            on_result=lambda healed: print(
                "stream guard: MPD stream stranded at 0, restored to full",
                flush=True) if healed else None)

    @staticmethod
    def _finish_remote_command(command, success, message=""):
        if success is None:
            mark = getattr(command, "mark_indeterminate", None)
            return bool(callable(mark) and mark(str(
                message or "Command outcome could not be verified")))
        finish = getattr(command, "finish", None)
        return bool(callable(finish) and finish(bool(success), str(message or "")))

    def _on_remote_command_requested(self, command):
        """Admit every phone mutation into a desktop-owned intent boundary."""
        action = str(getattr(command, "action", "") or "")
        payload = dict(getattr(command, "payload", {}) or {})
        admit = getattr(command, "admit", None)
        if action not in {
                "play-target", "play-now", "queue-append", "transport",
                "move", "volume", "seek", "jump"} or not callable(admit):
            Backend._finish_remote_command(
                command, False, "Unsupported phone command")
            return False
        if not admit():
            return False

        def done(success, message=""):
            detail = message or (
                "" if success else "Phone command could not be verified")
            return Backend._finish_remote_command(command, success, detail)

        if action == "play-target":
            payload["_remoteCommand"] = command
            if self._on_remote_play_requested(payload):
                return True
            done(False, "Playable target could not be admitted")
            return False
        if action == "play-now":
            file = str(payload.get("file") or "")
            if not file:
                done(False, "No track was supplied")
                return False
            accepted = self._request_queue_intent(
                "play-now", {"file": file, "session": "manual"},
                on_finished=lambda success: done(success))
            if not accepted:
                done(False, "Queue is finishing another change")
            return bool(accepted)
        if action == "queue-append":
            file = str(payload.get("file") or "")
            if not file:
                done(False, "No track was supplied")
                return False
            accepted = self._request_queue_intent(
                "append", {"files": (file,)},
                on_finished=lambda success: done(success))
            if not accepted:
                done(False, "Queue is finishing another change")
            return bool(accepted)
        if action == "jump":
            try:
                song_id = int(payload.get("songId", -1))
            except (TypeError, ValueError):
                song_id = -1
            if song_id < 0:
                done(False, "Queue target is invalid")
                return False
            accepted = self._request_soft_queue_intent(
                "jump", {"songId": song_id},
                on_finished=lambda success: done(success))
            if not accepted:
                done(False, "Queue is finishing another change")
            return bool(accepted)
        if action == "transport":
            desired = str(payload.get("action") or "")
            if desired == "toggle":
                state = self._transport_intent_target or self._state
                desired = "pause" if state == "play" else "play"
            if desired not in ("play", "pause", "stop"):
                done(False, "Playback action is invalid")
                return False
            self._transport_intent_target = desired
            return self._request_playback_intent(
                "transport", {"state": desired}, on_finished=done)
        if action == "volume":
            try:
                value = max(0, min(100, int(payload.get("value"))))
            except (TypeError, ValueError):
                done(False, "Volume is invalid")
                return False
            return self._request_playback_intent(
                "volume", {"value": value}, on_finished=done)
        if action == "seek":
            try:
                target = float(payload.get("seconds"))
            except (TypeError, ValueError):
                target = math.nan
            if not math.isfinite(target):
                done(False, "Seek position is invalid")
                return False
            target = max(0.0, target)
            if self._duration > 0:
                target = min(target, self._duration)
            return self._request_playback_intent(
                "seek", {"seconds": round(target, 1)}, on_finished=done)

        move = str(payload.get("command") or "")
        if move not in ("next", "previous"):
            done(False, "Queue move is invalid")
            return False
        try:
            if move == "previous":
                return self._request_previous_action(on_finished=done)
            self._soft_move(lambda: self._request_playback_intent(
                "move", {"command": move}, on_finished=done))
        except Exception:
            done(False, "Queue move could not start")
            return False
        return True

    def _soft_move(self, action):
        """User-initiated hard switches (skip, pick, new queue) stop MPD
        mid-waveform: digital silence with click edges, audible as a
        stutter on every manual transition — MPD only crossfades natural
        song ends. Ride the volume down first, make the move, ride back
        up — on MPD's PIPEWIRE STREAM, never MPD setvol: the software
        mixer scales samples entering MPD's output buffer, several hundred
        ms ahead of the DAC, so a setvol ride is flushed unheard by the
        skip and then mutes the first ~700 ms of the next song (measured
        2026-07-23: 850 ms dropouts vs 115 ms raw). Stream volume acts at
        mix time. Settles at EXACTLY the starting stream volume; MPD's own
        volume/ReplayGain are untouched. Nested or rapid calls, and any
        failure to find the stream, fall through to the raw action — a
        115 ms hard cut beats a broken ride."""
        smooth = (not self._dj_on and self._volume > 0
                  and self._state == "play")
        self._transition_fader.move(action, smooth=smooth)

    def _on_move_requested(self, action):
        # media keys + phone remote land here (queued to the GUI thread via
        # the signal) so out-of-app skips ride the same fade as in-app ones
        if action == "next":
            self.requestNext()
        elif action == "previous":
            self.requestPrevious()

    def _on_remote_play_requested(self, request):
        """Resolve phone targets through the same session laws as QML."""
        request = dict(request or {})
        if not (request.get("playlist") or request.get("file")
                or request.get("path")):
            return False
        return self._request_remote_play(request)

    def _request_remote_play(self, request):
        """Resolve the latest phone play target on an owned MPD client."""
        request = dict(request or {})
        if self._remote_play_busy:
            superseded = self._remote_play_pending or {}
            Backend._finish_remote_command(
                superseded.get("_remoteCommand"), False,
                "Superseded by a newer phone command")
            self._remote_play_pending = request
            self._remote_play_generation += 1
            return True
        self._remote_play_busy = True
        self._remote_play_pending = None
        self._remote_play_generation += 1
        generation = self._remote_play_generation

        def work():
            success = False
            files = ()
            degraded = False
            resolved_path = ""
            kind = "playlist" if request.get("playlist") else "path"
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    playlist = str(request.get("playlist") or "")
                    target_file = str(request.get("file") or "")
                    target_path = str(request.get("path") or "")
                    if playlist:
                        result = PlaylistService.client_files_result(
                            cli, playlist)
                        success, files = result.success, result.files
                    else:
                        parent = os.path.dirname(target_file) \
                            if target_file else target_path
                        resolved_path = parent
                        if target_file and not parent:
                            success, files = True, (target_file,)
                        else:
                            result = LibraryRepository().publish_path(
                                parent, cli.listall(parent))
                            success, files = result.success, result.files
                            if target_file and not success:
                                success, files, degraded = \
                                    True, (target_file,), True
            except Exception:
                success = False
            self._remotePlayReady.emit({
                "generation": generation, "request": request,
                "kind": kind, "success": success, "files": files,
                "path": resolved_path, "degraded": degraded,
            })

        if self._start_worker(work, name="ampere-remote-play"):
            return True
        self._on_remote_play_ready({
            "generation": generation, "request": request,
            "kind": "playlist" if request.get("playlist") else "path",
            "success": False, "files": (), "path": "", "degraded": False,
        })
        return False

    def _on_remote_play_ready(self, payload):
        if not isinstance(payload, dict):
            return
        if payload.get("generation") != self._remote_play_generation:
            Backend._finish_remote_command(
                (payload.get("request") or {}).get("_remoteCommand"), False,
                "Superseded by a newer phone command")
            self._remote_play_busy = False
            return self._launch_pending_remote_play()
        self._remote_play_busy = False
        if not payload.get("success"):
            Backend._finish_remote_command(
                (payload.get("request") or {}).get("_remoteCommand"), False,
                "Playable target could not be resolved")
            if payload.get("kind") == "playlist":
                self._report_playlist_read(False)
            else:
                self._report_library_read(False)
            return self._launch_pending_remote_play()
        request = dict(payload.get("request") or {})
        if payload.get("kind") == "path":
            if payload.get("degraded"):
                self._report_library_read(False)
            else:
                path = str(payload.get("path") or "")
                self._library.publish_path(
                    path, ({"file": file}
                           for file in (payload.get("files") or ())))
                self._report_library_read(True)
        self._apply_remote_play(request, list(payload.get("files") or ()))
        return self._launch_pending_remote_play()

    def _launch_pending_remote_play(self):
        pending, self._remote_play_pending = self._remote_play_pending, None
        if pending is None:
            return False
        return self._request_remote_play(pending)

    def _apply_remote_play(self, request, files):
        """Apply verified membership through the existing session boundary."""
        request = dict(request or {})
        target_file = str(request.get("file") or "")
        if target_file:
            if target_file not in files:
                files = [target_file]
        files = self._drop_disliked(files, keep=target_file)
        command = request.get("_remoteCommand")
        if not files:
            self.errorOccurred.emit("Nothing playable was found")
            Backend._finish_remote_command(
                command, False, "Nothing playable was found")
            return False
        if request.get("shuffle"):
            files = self._shuffle_order(files)
            if files is None:
                Backend._finish_remote_command(
                    command, False, "Shuffle could not be prepared")
                return False
        start = files.index(target_file) if target_file in files else 0
        queue_request = self._explicit_queue_request(
            files, start, keep_disliked=False, session="manual")
        if queue_request is None:
            Backend._finish_remote_command(
                command, False, "Nothing playable was found")
            return False
        accepted = self._request_soft_queue_intent(
            "replace", queue_request,
            on_finished=lambda success: Backend._finish_remote_command(
                command, success,
                "" if success else "Queue replacement could not be verified"))
        if not accepted:
            Backend._finish_remote_command(
                command, False, "Queue is finishing another change")
        return bool(accepted)

    @Slot()
    def next(self):
        return self.requestNext()

    @Slot()
    def previous(self):
        return self.requestPrevious()

    @Slot()
    def stop(self):
        return self._publish_playback_state(self._playback.set_state("stop"))

    @Slot(float)
    def seek(self, seconds):
        self._seek_current_once(seconds)

    @Slot(int)
    def setVolume(self, vol):
        vol = max(0, min(100, int(vol)))
        return Backend._publish_volume_result(
            self, self._playback.set_volume(vol))

    @Slot(bool)
    def setRandom(self, on):
        return self._set_random_mode(bool(on))

    def _set_random_mode_result(self, enabled):
        result = self._playback.set_random_mode(bool(enabled))
        changed = self._random != result.value
        self._random = result.value
        if changed:
            self.statusChanged.emit()
        return result

    def _set_random_mode(self, enabled):
        return self._set_random_mode_result(enabled).committed

    def _restore_ordered_random(self, result):
        previous = result.previous
        if previous is None or previous == self._random:
            return previous is not None
        return self._set_random_mode(previous)

    @Slot(str, result=bool)
    def setLoopStatus(self, mode):
        desired = {
            "None": (False, False),
            "Playlist": (True, False),
            "Track": (True, True),
        }.get(str(mode))
        if desired is None:
            return False
        result = self._playback.set_repeat_mode(*desired)
        self._repeat, self._single = result.repeat, result.single
        self.statusChanged.emit()
        return result.committed

    @Property(bool, notify=statusChanged)
    def single(self):
        return self._single

    @Slot()
    def cycleRepeat(self):
        """The loop cycle: off -> current queue -> current song -> off."""
        if not self._repeat:
            self.setLoopStatus("Playlist")
        elif not self._single:
            self.setLoopStatus("Track")
        else:
            self.setLoopStatus("None")

    # ---- settings surface

    @Property(str, notify=settingsChanged)
    def replayGain(self):
        return self._replay_gain

    @Slot(str, result=bool)
    def setReplayGain(self, mode):
        return self._request_replay_gain(mode, persist=True)

    def _refresh_replay_gain(self):
        """ENFORCE the app's persisted leveling mode onto MPD (never adopt
        MPD's). replay_gain_mode is runtime-only in MPD — a daemon restart
        resets it to mpd.conf, and any drift from our mode makes songs
        settle at different volumes than the DJ bridges/slam math baked in."""
        return self._request_replay_gain(
            self._replay_gain, persist=False, enforce=True)

    def _request_replay_gain(self, mode, *, persist, scan=False,
                             enforce=False):
        mode = str(mode)
        if mode not in ReplayGainModeController.MODES:
            return False
        if enforce and self._replay_gain_busy:
            return False
        self._replay_gain_generation += 1
        request = {
            "generation": self._replay_gain_generation,
            "mode": mode, "persist": bool(persist), "scan": bool(scan),
        }
        if self._replay_gain_busy:
            self._replay_gain_pending = request
            return True
        return self._start_replay_gain_request(request)

    def _start_replay_gain_request(self, request):
        self._replay_gain_busy = True
        self._replay_gain_active = request
        self._replay_gain_pending = None

        def work():
            result = None
            messages = []
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    def connected(silent=True):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            return False

                    controller = ReplayGainModeController(
                        cli, ensure_connected=connected,
                        mark_disconnected=lambda: None,
                        error=messages.append)
                    result = controller.apply(request["mode"])
            except Exception:
                result = None
            payload = dict(request)
            payload.update({"result": result, "messages": tuple(messages)})
            self._replayGainReady.emit(payload)

        if self._start_worker(
                work, name="ampere-replay-gain-mode", durable=True):
            return True
        self._replay_gain_busy = False
        self._replay_gain_active = None
        if request["generation"] == self._replay_gain_generation:
            self.errorOccurred.emit(
                "ReplayGain mode change could not start while Ampere is closing")
        return False

    def _on_replay_gain_ready(self, payload):
        self._replay_gain_busy = False
        self._replay_gain_active = None
        payload = payload if isinstance(payload, dict) else {}
        current = payload.get("generation") == self._replay_gain_generation
        result = payload.get("result")
        if current:
            if isinstance(result, ReplayGainModeResult) and result.committed:
                mode = str(payload.get("mode") or "off")
                if payload.get("persist"):
                    self._replay_gain = mode
                    if mode != "off":
                        self._rg_on_mode = mode
                    self._save_conf()
                self.settingsChanged.emit()
                if payload.get("scan") and mode != "off":
                    self._start_rg_scan()
            else:
                messages = tuple(payload.get("messages") or ())
                self.errorOccurred.emit(
                    str(messages[-1]) if messages else
                    "ReplayGain mode could not be changed")
        pending = self._replay_gain_pending
        if pending is not None:
            self._start_replay_gain_request(pending)
        return bool(current and isinstance(result, ReplayGainModeResult)
                    and result.committed)

    # ---- loudness leveling (the Plexamp toggle) ------------------------------

    @Property(bool, notify=settingsChanged)
    def loudnessOn(self):
        return self._replay_gain != "off"

    @Slot(bool)
    def setLoudnessLeveling(self, on):
        """ONE switch: every song at the same perceived volume. ON = MPD
        replay-gain (track mode by default — per-song leveling is the only
        mode where every transition settles at the same volume) + a
        background pass that writes ReplayGain tags into any file that
        lacks them (untagged files are WHY volumes jump); OFF = native."""
        return self._request_replay_gain(
            self._rg_on_mode if on else "off", persist=True, scan=bool(on))

    def _start_rg_scan(self):
        if self._enrichment.running("replaygain"):
            return
        files = [e["song"]["file"] for e in self._search_index]
        if not files:
            return
        self._enrichment.launch(
            "replaygain", self._rg_worker, args=(files,),
            thread_name="ampere-replaygain-scan")

    def _rg_worker(self, files):
        try:
            self._loudness_scanner.scan(
                files, should_stop=self._workers.stop_requested.is_set,
                progress=self.rgProgress.emit)
        finally:
            release_unused_heap()

    # ---- energy/BPM analysis (radio moods + beat-aligned fades) --------------

    def _start_energy_scan(self):
        if self._enrichment.running("energy"):
            return
        files = [e["song"]["file"] for e in self._search_index]
        if not files:
            return
        self._enrichment.launch(
            "energy", self._energy_worker, args=(files,),
            thread_name="ampere-energy-scan")

    def _energy_worker(self, files):
        try:
            self._energy_scanner.scan(
                files, should_stop=self._workers.stop_requested.is_set)
        finally:
            release_unused_heap()

    # ---- phone remote ---------------------------------------------------------

    @Property(bool, notify=settingsChanged)
    def remoteOn(self):
        control = getattr(self, "_remote_control", None)
        return bool(control is not None and control.running)

    @Slot(bool)
    def setRemoteOn(self, on):
        return self._request_remote_lifecycle(bool(on))

    def _persist_remote_token(self):
        if not self._remote_token_new:
            return True
        # Persist pairing before opening any listener, so a crash cannot
        # silently invalidate a URL already shared with the phone. A failed
        # save leaves the token pending and every later start retries it.
        if not self._save_conf():
            return False
        self._remote_token_new = False
        return True

    def _start_remote(self):
        return self._request_remote_lifecycle(True)

    def _request_remote_lifecycle(self, on):
        on = bool(on)
        if on and not self._persist_remote_token():
            return False
        self._remote_lifecycle_generation += 1
        request = {
            "generation": self._remote_lifecycle_generation,
            "on": on,
        }
        if self._remote_lifecycle_busy:
            self._remote_lifecycle_pending = request
            return True
        if bool(self._remote_control.running) == on:
            self._remote_on = on
            self._save_conf()
            self.settingsChanged.emit()
            return True
        return self._start_remote_lifecycle_request(request)

    def _start_remote_lifecycle_request(self, request):
        self._remote_lifecycle_busy = True
        self._remote_lifecycle_active = request

        def work():
            on = request["on"]
            success = True
            if on:
                success = bool(self._remote_control.start())
            else:
                self._remote_control.stop()
            self._remoteLifecycleReady.emit({
                "generation": request["generation"],
                "on": on,
                "success": success,
            })

        if self._start_worker(
                work, name="ampere-remote-lifecycle", durable=True):
            return True
        self._remote_lifecycle_busy = False
        self._remote_lifecycle_active = None
        self.errorOccurred.emit("Phone remote could not change state")
        return False

    def _on_remote_lifecycle_ready(self, payload):
        self._remote_lifecycle_busy = False
        self._remote_lifecycle_active = None
        pending, self._remote_lifecycle_pending = (
            self._remote_lifecycle_pending, None)
        if pending is not None:
            self._start_remote_lifecycle_request(pending)
            return
        if payload.get("generation") != self._remote_lifecycle_generation:
            return
        requested = bool(payload.get("on"))
        success = bool(payload.get("success"))
        self._remote_on = requested if success else False
        self._save_conf()
        self.settingsChanged.emit()

    def _resolve_remote_ip(self):
        return self._remote_control.resolve_address()

    def _pending_durable_shutdown_jobs(self):
        """Name admitted persistence work not represented by a live thread."""
        pending = []
        listening_jobs = getattr(self, "_listening_progress_jobs", ())
        if listening_jobs:
            pending.append(
                f"ampere-listening-progress ({len(listening_jobs)} queued)")
        if getattr(self, "_replay_gain_pending", None) is not None:
            pending.append("ampere-replay-gain-mode (queued)")
        replay_active = getattr(self, "_replay_gain_active", None)
        if (isinstance(replay_active, dict)
                and replay_active.get("persist")):
            pending.append("ampere-replay-gain-mode")
        if getattr(self, "_remote_lifecycle_pending", None) is not None:
            pending.append("ampere-remote-lifecycle (queued)")
        if getattr(self, "_remote_lifecycle_active", None) is not None:
            pending.append("ampere-remote-lifecycle")
        if (getattr(self, "_transition_settings_pending", None) is not None
                or getattr(self, "_transition_internal_pending", None)
                is not None):
            pending.append("ampere-transition-settings (queued)")
        transition_active = getattr(self, "_transition_settings_active", None)
        if (isinstance(transition_active, dict)
                and not transition_active.get("internal")):
            pending.append("ampere-transition-settings")
        # File deletion is a multi-stage durable workflow: a completed worker
        # still needs Qt-side queue/playlist reconciliation before it is done.
        if getattr(self, "_deleting", False):
            pending.append("ampere-library-delete-workflow")
        # This is an observation after the bounded join, not a new wait: a
        # surviving writer may own its internal lock, and diagnostics must not
        # silently turn the three-second shutdown budget into an unbounded one.
        if getattr(self, "_dj_set_save_pending", None) is not None:
            pending.append("ampere-dj-set-save (queued)")
        return tuple(sorted(pending))

    def shutdownServices(self):
        """Release process-owned adapters before Qt/Python teardown."""
        self._conf_save_timer.stop()
        if getattr(self, "_beacon", None):
            self._beacon.cancel(preserve=True)
        workers = getattr(self, "_workers", None)
        worker_report = WorkerShutdownReport()
        if workers is not None:
            worker_report = workers.shutdown(timeout=3)
        worker_report = worker_report.with_pending_durable_jobs(
            *Backend._pending_durable_shutdown_jobs(self))
        Backend._stop_idle_listener(self)
        try:
            self._save_conf()
        except Exception:
            pass
        remote_control = getattr(self, "_remote_control", None)
        self._remote_control = None
        if remote_control is not None:
            remote_control.stop()
        spectrum, self._spec = self._spec, None
        self._spec_owners.clear()
        spectrum_timer = getattr(self, "_spectrum_frame_timer", None)
        if spectrum_timer is not None:
            spectrum_timer.stop()
        spectrum_lock = getattr(self, "_spectrum_frame_lock", None)
        if spectrum_lock is not None:
            with spectrum_lock:
                self._spectrum_latest = None
        if spectrum is not None:
            try:
                spectrum.stop()
            except Exception:
                pass
        return worker_report

    @Property(str, notify=settingsChanged)
    def remoteUrl(self):
        return self._remote_control.cached_url

    # ---- Spotify bridge (Crate playlists → local M3U) ------------------------

    @Slot(result="QVariantList")
    def spotifyPlaylists(self):
        try:
            from . import spotbridge
            return [{"name": p["name"], "count": p["count"]}
                    for p in spotbridge.list_playlists()]
        except Exception as e:
            self.errorOccurred.emit(f"Spotify: {e}")
            return []

    @Slot(str)
    def syncSpotifyPlaylist(self, name):
        name = str(name or "").strip()
        if not name:
            self.spotSyncDone.emit("Spotify sync needs a playlist name")
            return
        index = [{"file": e["song"]["file"], "title": e["song"]["title"],
                  "artist": e["song"]["artist"]} for e in self._search_index]
        outcome = self._enrichment.launch(
            "spotify", self._spot_worker, args=(name, index),
            thread_name="ampere-spotify-sync")
        if outcome == "busy":
            self.spotSyncDone.emit("Spotify sync is already running")
        elif outcome == "stopping":
            self.spotSyncDone.emit(
                "Spotify sync could not start while Ampere is closing")

    def _spot_worker(self, name, index):
        try:
            from . import spotbridge
            rep = spotbridge.sync(name, index)
            self.spotSyncDone.emit(
                f"{rep['name']}: {rep['matched']} of {rep['total']} matched")
        except Exception as e:
            self.spotSyncDone.emit(f"Spotify sync failed: {e}")

    # ---- spectrum tap (visualizer) --------------------------------------------

    def _capture_spectrum_frame(self, bands):
        """Retain only the newest capture frame from the reader thread.

        Emitting QVariantList directly from the 15 fps capture thread queued
        an independently marshalled Python/Qt payload for every frame.  When
        the scene graph was busy those queued conversions retained gigabytes
        and delayed ordinary input.  One tiny latest-value slot provides
        explicit backpressure; the GUI timer publishes at most one frame per
        turn and stale frames are simply superseded.
        """
        try:
            latest = tuple(float(value) for value in bands)
        except (TypeError, ValueError):
            return
        with self._spectrum_frame_lock:
            self._spectrum_latest = latest

    def _publish_spectrum_frame(self):
        with self._spectrum_frame_lock:
            latest, self._spectrum_latest = self._spectrum_latest, None
        if latest is not None:
            self.spectrumFrame.emit(list(latest))

    @Slot()
    @Slot(str)
    def startSpectrum(self, owner="default"):
        owner = str(owner or "default")
        self._spec_owners.add(owner)
        if self._spec is not None:
            return
        # Never contend with a cold NumPy import from Qt's input thread. The
        # owner remains registered and the prepared signal starts capture once
        # the worker has completed the import.
        if not self._spectrum_module_ready:
            self.prepareSpectrum()
            return
        self._start_prepared_spectrum()

    def _start_prepared_spectrum(self):
        if self._spec is not None or not self._spec_owners:
            return
        try:
            from .spectrum import SpectrumTap
            self._spec = SpectrumTap()
            self._spectrum_frame_timer.start()
            self._spec.start(self._capture_spectrum_frame)
        except Exception as e:
            self._spectrum_frame_timer.stop()
            self._spec = None
            self._spec_owners.clear()
            self.errorOccurred.emit(f"Visualizer failed: {e}")

    @Slot()
    def prepareSpectrum(self):
        """Import the FFT stack before Ambient's first interaction.

        NumPy and the spectrum module take several frames to import on this
        machine. Loading them through the process-owned worker boundary keeps
        that one-time cost off Qt's GUI thread and out of fullscreen entry.
        """
        if (self._spec is not None or self._spectrum_module_ready
                or self._spectrum_module_warming):
            return
        self._spectrum_module_warming = True

        def work():
            prepared = False
            try:
                from .spectrum import SpectrumTap  # noqa: F401
                prepared = True
            except Exception:
                prepared = False
            self._spectrumPrepared.emit(prepared)

        if not self._start_worker(work, name="ampere-spectrum-prepare"):
            self._spectrum_module_warming = False

    def _on_spectrum_prepared(self, prepared):
        self._spectrum_module_warming = False
        self._spectrum_module_ready = bool(prepared)
        if not prepared:
            owners = tuple(self._spec_owners)
            self._spec_owners.clear()
            if owners:
                self.errorOccurred.emit("Visualizer could not be prepared")
            return False
        self._start_prepared_spectrum()
        return True

    @Slot()
    @Slot(str)
    def stopSpectrum(self, owner="default"):
        self._spec_owners.discard(str(owner or "default"))
        if self._spec_owners:
            return
        if self._spec is not None:
            try:
                self._spec.stop()
            except Exception:
                pass
            self._spec = None
        timer = getattr(self, "_spectrum_frame_timer", None)
        if timer is not None:
            timer.stop()
        lock = getattr(self, "_spectrum_frame_lock", None)
        if lock is not None:
            with lock:
                self._spectrum_latest = None

    # ---- normalization level (replaygain_preamp — mpd.conf only) -----------

    def _read_preamps(self):
        return self._mpd_config.read_preamps()

    @Property(float, notify=settingsChanged)
    def rgPreamp(self):
        return self._rg_preamp

    @Property(float, notify=settingsChanged)
    def rgMissingPreamp(self):
        return self._rg_missing_preamp

    @Slot(float, float)
    def applyNormalization(self, preamp, missing):
        """Write both preamps into mpd.conf and restart the daemon — MPD has
        no protocol command for these. restore_paused means it comes back
        paused at the same spot, so the cost is a pause, not a lost queue."""
        if self._normalization_busy:
            return False
        self._normalization_busy = True

        def work():
            result = None
            error = ""
            try:
                result = self._mpd_config.apply_preamps(
                    preamp, missing,
                    restart=lambda: subprocess.run(
                        ["systemctl", "--user", "restart", "mpd"],
                        check=False).returncode == 0)
            except (OSError, TypeError, ValueError) as exc:
                error = str(exc)
            self._normalizationReady.emit({
                "result": result, "error": error,
            })

        if self._start_worker(
                work, name="ampere-normalization-apply", durable=True):
            return True
        self._normalization_busy = False
        self.errorOccurred.emit(
            "Normalization could not start while Ampere is closing")
        return False

    def _on_normalization_ready(self, payload):
        self._normalization_busy = False
        payload = payload if isinstance(payload, dict) else {}
        result = payload.get("result")
        if not isinstance(result, NormalizationResult):
            detail = str(payload.get("error") or "unknown storage failure")
            self.errorOccurred.emit(f"mpd.conf write failed: {detail}")
            return False
        if not result.success:
            detail = ("; prior configuration may need manual recovery"
                      if not result.rollback_complete else
                      "; prior configuration was restored")
            self.errorOccurred.emit("MPD could not apply normalization" + detail)
            return False
        self._rg_preamp = result.preamp
        self._rg_missing_preamp = result.missing_preamp
        self.settingsChanged.emit()
        # A successful activation replaced the daemon process. Retire the
        # stale Qt transport and reacquire every runtime surface through the
        # existing owned workers; ReplayGain itself is runtime-only in MPD.
        self._mark_disconnected()
        self.requestStatusRefresh()
        self._request_queue_refresh()
        self._refresh_replay_gain()
        return True

    @Slot(result="QVariantMap")
    def stats(self):
        """Return the last worker-verified library totals without MPD I/O."""
        result = self._library.stats
        directory = getattr(self, "_library_directory", {})
        artist_rows = directory.get("artists") if isinstance(directory, dict) else None
        return {
            "songs": result.songs,
            "albums": result.albums,
            # MPD counts raw ARTIST display strings, including aliases and
            # combined credits.  Once Ampere's canonical projection exists,
            # its row count is the honest Library number.
            "artists": (len(artist_rows) if artist_rows is not None
                        else result.artists),
            "genres": len(directory.get("genres") or ()),
            "playtimeHours": result.playtime_hours,
        }

    # ---- safe library metadata editing -------------------------------------

    @Slot(str, result=bool)
    def requestTrackMetadata(self, file):
        """Read editable tags without putting filesystem I/O on Qt's thread."""
        file = str(file or "")
        self._metadata_read_generation += 1
        generation = self._metadata_read_generation
        return self._start_worker(
            self._metadata_read_worker, args=(generation, file),
            name="ampere-metadata-read")

    def _metadata_read_worker(self, generation, file):
        try:
            metadata = self._metadata.read(file)
        except Exception as exc:
            metadata = {"editable": False, "error": str(exc)}
        self._metadataReadReady.emit({
            "generation": generation, "file": file, "metadata": metadata,
        })

    def _on_metadata_read_ready(self, result):
        if (not isinstance(result, dict)
                or result.get("generation") != self._metadata_read_generation):
            return
        self.trackMetadataReady.emit(
            str(result.get("file", "")), dict(result.get("metadata") or {}))

    @Slot(str, "QVariantMap", result=bool)
    def updateTrackMetadata(self, file, values):
        """Start one duplicate-safe tag update and narrow MPD refresh."""
        if self._metadata_update_busy:
            self.errorOccurred.emit("Metadata save is already running")
            return False
        self._metadata_update_busy = True
        file = str(file or "")
        values = dict(values or {})
        if self._start_worker(
                self._metadata_update_worker, args=(file, values),
                name="ampere-metadata-update", durable=True):
            return True
        self._metadata_update_busy = False
        self.errorOccurred.emit("Metadata save could not start while Ampere is closing")
        return False

    @staticmethod
    def _metadata_refresh(parent, registry):
        def read(operation, *args, default=None, **_kwargs):
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15, registry=registry) as cli:
                    return getattr(cli, operation)(*args)
            except Exception:
                return default

        def write_once(operation, *args, **_kwargs):
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15, registry=registry) as cli:
                    getattr(cli, operation)(*args)
                return True
            except Exception:
                return False

        return LibraryUpdateController(
            read=read, write_once=write_once).request(parent)

    def _metadata_update_worker(self, file, values):
        try:
            update = self._metadata.update(file, values)
            refresh = self._metadata_refresh(update.parent, self._workers)
            self._metadataUpdateReady.emit({
                "file": file, "success": True, "refresh": refresh,
            })
        except Exception as exc:
            self._metadataUpdateReady.emit({
                "file": file, "success": False, "error": str(exc),
            })

    def _on_metadata_update_ready(self, result):
        self._metadata_update_busy = False
        result = result if isinstance(result, dict) else {}
        file = str(result.get("file", ""))
        success = bool(result.get("success"))
        if success:
            refresh = result.get("refresh")
            if not getattr(refresh, "success", False):
                detail = ("could not be confirmed"
                          if not getattr(refresh, "confirmed", True)
                          else "could not start")
                message = ("Saved metadata · recovery snapshot kept · "
                           f"library refresh {detail}")
            elif getattr(refresh, "already_running", False):
                message = ("Saved metadata · recovery snapshot kept · "
                           "library refresh already running")
            else:
                message = "Saved metadata · recovery snapshot kept"
        else:
            message = f"Metadata save failed: {result.get('error', 'unknown error')}"
        self.errorOccurred.emit(message)
        self.trackMetadataUpdateFinished.emit(file, success)

    @Slot(result=bool)
    def clearCaches(self):
        if self._cache_clear_busy:
            self.errorOccurred.emit("Cache clear is already running")
            return False
        self._cache_clear_busy = True

        def work():
            try:
                result = self._cache_maintenance.clear()
            except Exception:
                result = None
            self._cacheClearReady.emit(result)

        if self._start_worker(work, name="ampere-cache-clear"):
            return True
        Backend._on_cache_clear_ready(self, None)
        return False

    def _on_cache_clear_ready(self, result):
        self._cache_clear_busy = False
        if not isinstance(result, CacheClearResult):
            self.errorOccurred.emit(
                "Cache clear could not finish · retry from Settings")
            return False
        if result.success:
            self.errorOccurred.emit(
                "Art + waveform + artist biography caches cleared")
            return True
        failed = ", ".join(name for name, _error in result.failures)
        self.errorOccurred.emit(
            f"Cache clear incomplete · could not remove {failed}")
        return False

    @Property("QVariantList", notify=beaconChanged)
    def beaconSessions(self):
        return [dict(s) for s in self._beacon.sessions]

    @Property("QVariantMap", notify=beaconChanged)
    def beaconSession(self):
        return self._beacon.selected

    @Property(bool, notify=beaconChanged)
    def beaconBusy(self):
        return self._beacon.busy

    @Property(bool, notify=beaconChanged)
    def beaconRestoring(self):
        return self._beacon.restoring

    @Slot()
    def exitBeaconRadio(self):
        return self._beacon.exit()

    @Property(str, notify=beaconChanged)
    def beaconStatus(self):
        return self._beacon.status

    @Property(bool, notify=beaconChanged)
    def beaconActive(self):
        return self._beacon.active

    @Slot()
    def startBeaconRadio(self):
        return self._beacon.start()

    @Slot(str)
    def openBeaconRadio(self, identity):
        return self._beacon.open(identity)

    @Slot(str)
    def resumeBeaconRadio(self, identity):
        return self._beacon.resume(identity)

    @Slot(int)
    def playBeaconPosition(self, pos):
        pos = int(pos)
        if (not self._beacon.active or self._beacon.restoring
                or not 0 <= pos < len(self._queue)):
            return False
        song_id = self._queue[pos].get('id', -1)
        if int(song_id) < 0:
            return False
        return self._request_soft_queue_intent(
            'jump', {'songId': song_id, 'beaconOwner': True})

    @Slot(str)
    def saveBeaconPlaylist(self, name):
        return self._beacon.save(name)

    @Slot(int)
    def playBeaconTrack(self, index):
        return self._beacon.play(index)

    # ---- queue -----------------------------------------------------------

    def _execute_queue_intent(self, kind, request):
        """Run one active-queue transaction on a worker-owned MPD client.

        The caller has already acquired the process-wide desktop queue lease.
        This method owns all daemon I/O; the Qt thread only publishes the
        result after ``_queueIntentReady`` crosses the queued signal boundary.
        """
        request = dict(request or {})
        messages = []
        success = False
        random_result = None
        final_random = None
        play_now_result = None
        cancel_event = request.get("cancelEvent")
        if (isinstance(cancel_event, threading.Event)
                and cancel_event.is_set()):
            return {
                "success": False,
                "messages": ("Shuffle publication was cancelled",),
                "randomResult": None,
                "finalRandom": None,
                "playNowResult": None,
            }
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15,
                    registry=self._workers) as cli:
                def connected(silent=True):
                    try:
                        cli.ping()
                        return True
                    except Exception:
                        close_mpd_client(cli)
                        try:
                            cli.connect(HOST, PORT)
                            return True
                        except Exception:
                            return False

                playback = PlaybackController(
                    cli, ensure_connected=connected,
                    mark_disconnected=lambda: close_mpd_client(cli),
                    error=messages.append)
                recovery = request.get('radioRecovery')
                if kind == 'restore-radio':
                    if recovery is None or recovery.data is None:
                        raise RuntimeError('Pre-Radio queue is unavailable')
                    recovery.rebind(playback)
                    expected = tuple(tuple(row) for row in recovery.data['expected'])
                    allowed = list(expected)
                    original = recovery.data['original']
                    if any(file in self._disliked for file in original['files']):
                        raise RuntimeError('Pre-Radio queue contains disliked songs')
                    ownership_lost = False
                    def restore_guard(staged_ids=()):
                        nonlocal ownership_lost
                        if cancel_event.is_set():
                            ownership_lost = True
                            return False
                        actual = tuple((str(row['id']), row['file']) for row in cli.playlistinfo()
                                       if str(row['id']) not in staged_ids)
                        if actual != expected:
                            ownership_lost = True
                            return False
                        return True
                    success = playback.restore_queue(original, guard=restore_guard,
                        on_staged=lambda rows: allowed.extend((str(r['id']), r['file']) for r in rows))
                    if success:
                        # Persist the verified restored identity before clearing.
                        # If clear fails, retry still has a valid queue guard.
                        recovery.reconcile(cli, allowed=allowed)
                        recovery.clear()
                        final_random = original['random']
                    elif not ownership_lost:
                        recovery.reconcile(cli, allowed=allowed)
                    if not success:
                        messages.append('Pre-Radio restoration could not be verified; recovery retained')
                    return {'success': success, 'messages': tuple(messages),
                            'randomResult': None, 'finalRandom': final_random,
                            'playNowResult': None}
                guard = request.get("beaconGuard")
                if guard is not None:
                    guard_rejected = False
                    def valid_beacon(staged_ids=(), *, require_order=False):
                        nonlocal guard_rejected
                        if cancel_event.is_set():
                            guard_rejected = True
                            return False
                        status = cli.status()
                        if require_order and status.get("random") == "1":
                            return False
                        if status.get("repeat") == "1" or status.get("single") in ("1", "oneshot"):
                            return False
                        queue = cli.playlistinfo()
                        actual = tuple((str(row.get("id")), row.get("file")) for row in queue
                                       if str(row.get("id")) not in staged_ids)
                        if actual != tuple(guard.get("queue", ())):
                            guard_rejected = True
                            return False
                        if "songId" in guard:
                            current = cli.currentsong()
                            if (str(status.get("songid")) != guard["songId"]
                                    or current.get("file") != guard["file"]):
                                return False
                        return True
                    if not valid_beacon():
                        raise RuntimeError("Radio publication cancelled because playback changed")
                if guard is not None and kind in ("append", "replace", "replace-upcoming"):
                    if recovery is not None:
                        recovery.capture(playback)
                    allowed = list(guard.get("queue", ()))
                    random_result = playback.set_random_mode(False)
                    if random_result.committed:
                        final_random = False
                        success = playback.beacon_queue(kind, request.get("files") or (),
                            guard=lambda staged_ids=(): valid_beacon(staged_ids, require_order=True),
                            current_id=request.get("currentId"),
                            start_index=request.get("startIndex", 0),
                            on_staged=lambda rows: allowed.extend((str(r["id"]), r["file"]) for r in rows))
                        if recovery is not None and not guard_rejected:
                            recovery.reconcile(cli, allowed=allowed)
                        if not success and random_result.previous:
                            restored = playback.set_random_mode(True)
                            final_random = restored.value
                elif kind == "jump":
                    cli.playid(str(request["songId"]))
                    success = True
                elif kind == "play-now":
                    play_now_result = playback.append_and_play(
                        request.get("file"))
                    stop_requested = self._workers.stop_requested
                    while (isinstance(play_now_result, QueuePlayResult)
                           and play_now_result.indeterminate
                           and not stop_requested.wait(0.25)):
                        play_now_result = playback.reconcile_append_and_play(
                            play_now_result)
                    if isinstance(play_now_result, QueuePlayResult):
                        success = (True if play_now_result.committed else
                                   False if play_now_result.rolled_back else None)
                        if play_now_result.message:
                            messages.append(play_now_result.message)
                elif kind == "insert-next":
                    args = (request["file"], "+0") \
                        if request.get("afterCurrent") else (request["file"],)
                    cli.addid(*args)
                    success = True
                elif kind == "append":
                    success = playback.append_files(
                        request.get("files") or (),
                        error_prefix=str(request.get("errorPrefix") or ""))
                elif kind == "remove":
                    success = playback.remove_ids(
                        request.get("songIds") or ())
                elif kind == "bench-disliked":
                    success = playback.bench_disliked(request.get("file"))
                elif kind == "reorder":
                    success = playback.reorder_window(
                        request.get("songIds") or (),
                        int(request.get("start", 0)))
                elif kind in ("replace", "replace-upcoming"):
                    if (isinstance(cancel_event, threading.Event)
                            and cancel_event.is_set()):
                        messages.append("Shuffle publication was cancelled")
                    else:
                        random_result = playback.set_random_mode(False)
                        if (random_result.committed
                                or random_result.previous is not None):
                            final_random = random_result.value
                        if (random_result.committed
                                and isinstance(cancel_event, threading.Event)
                                and cancel_event.is_set()):
                            messages.append(
                                "Shuffle publication was cancelled")
                        elif random_result.committed:
                            if kind == "replace":
                                success = playback.replace_queue(
                                    request.get("files") or (),
                                    int(request.get("startIndex", 0)))
                            else:
                                success = playback.replace_upcoming(
                                    request.get("files") or (),
                                    request.get("currentId", -1))
                    if (not success
                            and isinstance(
                                random_result, PlaybackBooleanResult)
                            and random_result.committed
                            and random_result.previous is not None
                            and random_result.previous != final_random):
                        restored = playback.set_random_mode(
                            random_result.previous)
                        if (restored.committed
                                or restored.previous is not None):
                            final_random = restored.value
                else:
                    messages.append(f"Unknown queue intent: {kind}")
        except Exception as exc:
            success = False
            messages.append(str(exc))
        return {
            "success": success if success is None else bool(success),
            "messages": tuple(messages),
            "randomResult": random_result,
            "finalRandom": final_random,
            "playNowResult": play_now_result,
        }

    def _admit_queue_intent(self, kind, request=None, *, on_finished=None):
        """Reserve queue ownership synchronously without performing I/O."""
        kind = str(kind or "queue")
        request = dict(request or {})
        beacon = getattr(self, "_beacon", None)
        if beacon and not request.get("beaconOwner"):
            beacon.cancel()
        allow_disliked = (
            bool(request.pop("allowDisliked", False))
            and str(request.get("source") or "") == "album")
        disliked = set(str(file) for file in
                        getattr(self, "_disliked", ()) if file)
        if kind in ("play-now", "insert-next"):
            file = str(request.get("file") or "")
            if file and file in disliked:
                self.errorOccurred.emit(
                    "Restore this song from Disliked before queueing it")
                if on_finished is not None:
                    on_finished(False)
                return None
        elif kind in ("append", "replace", "replace-upcoming"):
            supplied = tuple(str(file) for file in
                             (request.get("files") or ()) if file)
            if request.get("beaconOwner") and any(file in disliked for file in supplied):
                if on_finished is not None:
                    on_finished(False)
                return None
            requested_index = min(
                max(0, int(request.get("startIndex", 0))),
                max(0, len(supplied) - 1))
            requested_file = (supplied[requested_index]
                              if supplied else "")
            allowed = (supplied if allow_disliked else
                       tuple(file for file in supplied
                             if file not in disliked))
            if supplied and not allowed:
                self.errorOccurred.emit(
                    "Restore this song from Disliked before queueing it")
                if on_finished is not None:
                    on_finished(False)
                return None
            request["files"] = allowed
            if kind == "replace" and allowed:
                request["startIndex"] = (
                    allowed.index(requested_file)
                    if requested_file in allowed else 0)
        lease, _rejected = self._queue_mutations.acquire(
            f"queue-intent:{kind}")
        if lease is None:
            self.errorOccurred.emit(
                "Queue is finishing another change — try again in a moment")
            if on_finished is not None:
                on_finished(False)
            return None
        self._queue_intent_generation = (
            getattr(self, "_queue_intent_generation", 0) + 1)
        return {
            "generation": self._queue_intent_generation,
            "kind": kind,
            "request": request,
            "lease": lease,
            "onFinished": on_finished,
        }

    def _launch_queue_intent(self, admission):
        """Launch one previously admitted intent on an owned worker."""
        if not isinstance(admission, dict) or admission.get("launched"):
            return False
        admission["launched"] = True
        generation = admission.get("generation")
        kind = str(admission.get("kind") or "queue")
        request = dict(admission.get("request") or {})
        lease = admission.get("lease")
        on_finished = admission.get("onFinished")
        if lease is None:
            return False

        def work():
            payload = self._execute_queue_intent(kind, request)
            completion_published = False
            if payload.get("success") is None and callable(on_finished):
                # Shutdown can join this worker on Qt's thread and close the
                # remote registry before the queued signal is delivered. The
                # remote command callback is thread-safe; publish only this
                # indeterminate truth here so registry close cannot relabel it
                # as failure. Normal success/failure stays on Qt's thread.
                on_finished(None)
                completion_published = True
            payload.update({
                "generation": generation,
                "kind": kind,
                "request": request,
                "lease": lease,
                "onFinished": on_finished,
                "completionPublished": completion_published,
            })
            self._queueIntentReady.emit(payload)

        if self._start_worker(
                work, name=f"ampere-queue-intent-{kind}"):
            return True
        lease.release()
        self.errorOccurred.emit(
            "Queue change could not start while Ampere is closing")
        if on_finished is not None:
            on_finished(False)
        return False

    def _request_queue_intent(self, kind, request=None, *, on_finished=None):
        """Admit and immediately launch one nonblocking queue mutation."""
        admission = self._admit_queue_intent(
            kind, request, on_finished=on_finished)
        return bool(admission) and self._launch_queue_intent(admission)

    def _request_soft_queue_intent(
            self, kind, request=None, *, on_finished=None):
        """Admit now, then launch when the audible transition reaches its cut."""
        admission = self._admit_queue_intent(
            kind, request, on_finished=on_finished)
        if admission is None:
            return False
        try:
            self._soft_move(lambda: self._launch_queue_intent(admission))
        except Exception:
            if not admission.get("launched"):
                admission["lease"].release()
                self.errorOccurred.emit("Queue transition could not start")
                if on_finished is not None:
                    on_finished(False)
            return False
        return True

    def _on_queue_intent_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        lease = payload.get("lease")
        callback = payload.get("onFinished")
        raw_success = payload.get("success")
        success = raw_success is True
        indeterminate = raw_success is None
        try:
            if payload.get("generation") != self._queue_intent_generation:
                return False
            final_random = payload.get("finalRandom")
            if isinstance(final_random, bool) and self._random != final_random:
                self._random = final_random
                self.statusChanged.emit()
            if success:
                Backend._record_queue_context(
                    self, str(payload.get("kind") or ""),
                    dict(payload.get("request") or {}))
                session = str(
                    (payload.get("request") or {}).get("session") or "")
                if session == "manual":
                    self._end_mood_session()
                elif session == "curated":
                    request = dict(payload.get("request") or {})
                    self._sessions.commit_curated(
                        mood=str(request.get("mood") or ""),
                        sonic_profile=str(request.get("sonic") or ""))
                    self._sync_session_state()
                    self._save_conf()
                    self.settingsChanged.emit()
            elif not indeterminate:
                messages = tuple(payload.get("messages") or ())
                self.errorOccurred.emit(
                    str(messages[-1] if messages
                        else "Queue change could not be verified"))
            # A lost reply can make failure ambiguous. Always reconcile both
            # queue membership and playhead after a worker reached MPD.
            self._invalidate_queue_refresh()
            self._request_queue_refresh()
            Backend._invalidate_status_refresh(self)
            self.requestStatusRefresh()
            if callable(callback) and not payload.get("completionPublished"):
                callback(None if indeterminate else success)
            return None if indeterminate else success
        finally:
            if lease is not None:
                lease.release()
            Backend._drain_disliked_queue_cleanup(self)
            Backend._drain_context_shuffle_restore(self)

    @Slot(int)
    def playPosition(self, pos):
        pos = int(pos)
        if not 0 <= pos < len(self._queue):
            return False
        song_id = self._queue[pos].get("id", -1)
        if song_id >= 0:
            return self._request_soft_queue_intent(
                "jump", {"songId": song_id})
        return False

    @Slot(int)
    def removePosition(self, pos):
        pos = int(pos)
        if not 0 <= pos < len(self._queue):
            return False
        song_id = self._queue[pos].get("id", -1)
        if song_id >= 0:
            return self._request_queue_intent(
                "remove", {
                    "songIds": (song_id,), "manualQueueEdit": True,
                })
        return False

    @Slot()
    def clearQueue(self):
        song_ids = tuple(
            song.get("id", -1) for song in self._queue
            if song.get("id", -1) >= 0)
        if not song_ids:
            return False
        return self._request_queue_intent(
            "remove", {"songIds": song_ids, "manualQueueEdit": True})

    @Slot()
    def trimPlayed(self):
        """Remove history before the current song without interrupting it.

        A long-lived MPD queue otherwise becomes both session history and the
        future plan. Session tools need a clean boundary: the playing song is
        retained and shifts to position zero; everything upcoming is untouched.
        """
        pos = self._queue_pos
        if pos <= 0:
            return False
        song_ids = tuple(
            song["id"] for song in self._queue[:pos]
            if song.get("id", -1) >= 0)
        return bool(song_ids) and self._request_queue_intent(
            "remove", {"songIds": song_ids, "manualQueueEdit": True})

    @Slot(int)
    def keepNext(self, count):
        """Cap the future session while preserving playback and history."""
        count = max(0, min(2000, int(count)))
        pos = self._queue_pos
        n = len(self._queue)
        if pos < 0:
            if count < n:
                song_ids = tuple(
                    song["id"] for song in self._queue[count:]
                    if song.get("id", -1) >= 0)
                return bool(song_ids) and self._request_queue_intent(
                    "remove", {
                        "songIds": song_ids, "manualQueueEdit": True,
                    })
            return False
        end = pos + 1 + count
        if end < n:
            song_ids = tuple(
                song["id"] for song in self._queue[end:]
                if song.get("id", -1) >= 0)
            return bool(song_ids) and self._request_queue_intent(
                "remove", {
                    "songIds": song_ids, "manualQueueEdit": True,
                })
        return False

    @Slot(str)
    def queuePath(self, path):
        return self._request_path_action("queue", path)

    @Slot("QVariantList", result=bool)
    def queueFiles(self, files):
        """Append one explicit album/selection without widening to its folder."""
        files = tuple(str(file) for file in files if file)
        if not files:
            self.errorOccurred.emit("Nothing to queue")
            return False
        return self._request_queue_intent(
            "append", {"files": files, "manualQueueEdit": True},
            on_finished=self._queued_notice(len(files)))

    @Slot("QVariantList", result=bool)
    def queueAlbum(self, files):
        """Append an intentionally selected parent album, in full."""
        files = tuple(str(file) for file in files if file)
        if not files:
            self.errorOccurred.emit("Nothing to queue")
            return False
        return self._request_queue_intent(
            "append", {
                "files": files,
                "source": "album",
                "allowDisliked": True,
                "manualQueueEdit": True,
            }, on_finished=self._queued_notice(len(files)))

    @Slot(str)
    def playPath(self, path):
        """Replace the queue with a folder/file after taste filtering."""
        return self._request_path_action("play", path)

    # ---- shuffle (PowerAmp-style: a real shuffled queue, not the random flag)

    def _queue_after_current(
            self, files, *, on_finished=None, cancel_event=None):
        """Replace everything after the playing song — never interrupts it.
        If nothing is playing, replaces the queue and starts."""
        files = tuple(self._drop_disliked(files))[:2000]
        if not files:
            return False
        pos = self._queue_pos
        playing = (0 <= pos < len(self._queue)
                   and getattr(self, "_state", "stop") in ("play", "pause"))
        if playing:
            current_id = self._queue[pos].get("id", -1)
            if current_id < 0:
                return False
            kind = "replace-upcoming"
            request = {
                "files": files,
                "currentId": current_id,
                "session": "manual",
                "preserveQueueContext": True,
            }
        else:
            kind = "replace"
            request = {
                "files": files,
                "startIndex": 0,
                "session": "manual",
                "queueContext": "defined" if len(files) > 1 else "manual",
            }
        if cancel_event is not None:
            request["cancelEvent"] = cancel_event
        if on_finished is None:
            return self._request_queue_intent(kind, request)
        return self._request_queue_intent(
            kind, request, on_finished=on_finished)

    @staticmethod
    def _artist_spread(files, window=1, artist_keys=None):
        return QueueSequencer.artist_spread(
            files, window, artist_keys=artist_keys)

    # ---- gapless awareness ----------------------------------------------------

    def _album_next_map(self) -> dict:
        return self._queue_sequencer.album_successors(self._search_index)

    def _gapless_extend(self, files, cli=None):
        """Re-attach gapless segues after a shuffle: a track whose audio ends
        HOT (joi_taildb sticker) runs straight into its album-next track —
        playing it alone slices the segue mid-note. Pull the next track(s)
        in behind it, chain-capped, skipping ones already placed later.
        `cli` lets a worker pass its own MPD client (Autoplay refill runs off
        the GUI thread)."""
        evidence = self._stickers.values_result("joi_taildb", cli)
        if not evidence.available and not evidence.retained:
            raise PlanningEvidenceUnavailable(
                "gapless tail snapshot unavailable")
        tails = {}
        for f, v in evidence.values.items():
            try:
                tails[f] = float(v)
            except ValueError:
                pass
        if not tails:
            return files
        out = self._queue_sequencer.extend_gapless(
            files, tail_levels=tails, successors=self._album_next_map())
        # a segue chain must never pull a disliked album-next back in
        return self._drop_disliked(out)

    def _report_library_read(self, success):
        if success:
            self._library_read_failed = False
            return
        if not getattr(self, "_library_read_failed", False):
            self._library_read_failed = True
            self.errorOccurred.emit(
                "Library path is unavailable — reconnect and try again")

    def _request_path_action(self, action, path):
        """Plan one folder action off Qt's thread; the latest click wins."""
        request = (str(action), str(path or ""))
        if self._path_action_busy:
            self._path_action_pending = request
            self._path_action_generation += 1
            return True
        self._path_action_busy = True
        self._path_action_pending = None
        self._path_action_generation += 1
        generation = self._path_action_generation
        action, path = request

        def work():
            result = LibraryPathResult(False)
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    repository = LibraryRepository()
                    result = repository.publish_path(path, cli.listall(path))
            except Exception:
                result = LibraryPathResult(False)
            self._pathActionReady.emit({
                "generation": generation, "action": action,
                "path": path, "result": result,
            })

        if self._start_worker(work, name="ampere-path-action"):
            return True
        self._on_path_action_ready({
            "generation": generation, "action": action,
            "path": path, "result": LibraryPathResult(False),
        })
        return False

    def _on_path_action_ready(self, payload):
        if not isinstance(payload, dict):
            return
        generation = payload.get("generation")
        if generation != self._path_action_generation:
            self._path_action_busy = False
            return self._launch_pending_path_action()
        self._path_action_busy = False
        result = payload.get("result")
        if not isinstance(result, LibraryPathResult) or not result.success:
            self._report_library_read(False)
            return self._launch_pending_path_action()
        path = str(payload.get("path") or "")
        files = list(result.files)
        self._library.publish_path(
            path, ({"file": file} for file in files))
        self._report_library_read(True)
        self._apply_path_action(str(payload.get("action") or ""), path, files)
        return self._launch_pending_path_action()

    def _launch_pending_path_action(self):
        pending, self._path_action_pending = self._path_action_pending, None
        if pending is None:
            return False
        return self._request_path_action(*pending)

    def _apply_path_action(self, action, path, files):
        if action == "queue":
            kept = tuple(self._drop_disliked(files, keep=path))
            return bool(kept) and self._request_queue_intent(
                "append", {"files": kept},
                on_finished=self._queued_notice(len(kept)))
        if action == "play":
            kept = self._drop_disliked(files, keep=path)
            if not kept:
                self.errorOccurred.emit("Everything in there is disliked")
                return False
            return self.playFiles(kept, 0)
        if action in ("shuffle", "shuffle-now"):
            if not files:
                self.errorOccurred.emit("Nothing to shuffle there")
                return False
            if action == "shuffle-now":
                return self._shuffle_now(files)
            ordered = self._shuffle_order(files)
            return (False if ordered is None
                    else self._queue_after_current(ordered))
        return False

    def _request_playlist_action(self, action, name):
        """Acquire one stored playlist off Qt's thread; latest click wins."""
        request = (str(action), str(name or ""))
        if self._playlist_action_busy:
            self._playlist_action_pending = request
            self._playlist_action_generation += 1
            return True
        self._playlist_action_busy = True
        self._playlist_action_pending = None
        self._playlist_action_generation += 1
        generation = self._playlist_action_generation
        action, name = request

        def work():
            result = PlaylistReadResult(False)
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    result = PlaylistService.client_files_result(cli, name)
            except Exception:
                result = PlaylistReadResult(False)
            self._playlistActionReady.emit({
                "generation": generation, "action": action,
                "name": name, "result": result,
            })

        if self._start_worker(work, name="ampere-playlist-action"):
            return True
        self._on_playlist_action_ready({
            "generation": generation, "action": action,
            "name": name, "result": PlaylistReadResult(False),
        })
        return False

    def _on_playlist_action_ready(self, payload):
        if not isinstance(payload, dict):
            return
        if payload.get("generation") != self._playlist_action_generation:
            self._playlist_action_busy = False
            return self._launch_pending_playlist_action()
        self._playlist_action_busy = False
        result = payload.get("result")
        if not isinstance(result, PlaylistReadResult) or not result.success:
            self._report_playlist_read(False)
            return self._launch_pending_playlist_action()
        self._report_playlist_read(True)
        self._apply_playlist_action(
            str(payload.get("action") or ""),
            str(payload.get("name") or ""), list(result.files))
        return self._launch_pending_playlist_action()

    def _launch_pending_playlist_action(self):
        pending, self._playlist_action_pending = \
            self._playlist_action_pending, None
        if pending is None:
            return False
        return self._request_playlist_action(*pending)

    def _apply_playlist_action(self, action, name, files):
        source_files = list(files)
        files = self._drop_disliked(source_files)
        if not files:
            self.errorOccurred.emit(
                "Playlist is empty" if not source_files
                else "Everything in there is disliked")
            return False
        if action == "play":
            return self._play_explicit(
                files, 0, keep_disliked=False,
                on_finished=lambda success:
                    self._finish_playlist_launch(name, success))
        if action == "queue":
            return self._request_queue_intent(
                "append", {"files": tuple(files)})
        if action == "shuffle":
            ordered = self._shuffle_order(files)
            return (False if ordered is None
                    else self._queue_after_current(ordered))
        if action == "shuffle-now":
            return self._shuffle_now(
                files, on_finished=lambda success:
                    self._finish_playlist_launch(name, success))
        return False

    def _finish_playlist_launch(self, name, success):
        """Persist one exact stored-playlist launch after queue confirmation."""
        name = str(name or "").strip()
        if not success or not name:
            return False
        counts = dict(self._playlist_play_counts)
        counts[name] = min(2_147_483_647, int(counts.get(name, 0)) + 1)
        cleaned = clean_playlist_play_counts(counts)
        result = self._settings.try_patch({"playlist_play_counts": cleaned})
        if not Backend._handle_settings_save_result(
                self, result,
                failure_message="Playlist play count was not saved"):
            return False
        self._playlist_play_counts = cleaned
        self.playlistUsageChanged.emit()
        return True

    def _shuffle_order(self, files):
        """The house shuffle: random order, artists spread, gapless segues
        re-attached. Every shuffle entry point goes through this."""
        try:
            files = self._collapse_versions(self._drop_disliked(files))
            artists = {
                str(song.get("file", "")): str(song.get("artist", ""))
                for entry in self._search_index
                for song in [entry.get("song", {})]
                if isinstance(song, dict) and song.get("file")
            }
            return self._gapless_extend(self._queue_sequencer.shuffle_order(
                files, artist_keys=artists))
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "Shuffle could not verify its library planning data — the queue "
                "was not changed")
            return None

    def _shuffle_now(self, files, *, on_finished=None):
        """Replace the whole queue with a shuffled list and start playing
        immediately — for the shuffle buttons that sit ON a collection
        (a genre tile, a folder, a playlist). Pressing them means 'play
        this, shuffled, now.'"""
        if not files:
            self.errorOccurred.emit("Nothing to shuffle there")
            if on_finished is not None:
                on_finished(False)
            return False
        ordered = self._shuffle_order(files)
        if ordered is None:
            if on_finished is not None:
                on_finished(False)
            return False
        return self._play_explicit(
            ordered, 0, keep_disliked=False, on_finished=on_finished)

    @Slot(str)
    def shufflePath(self, path):
        """Shuffle a folder in AFTER the current song (bottom-bar behavior)."""
        return self._request_path_action("shuffle", path)

    @Slot()
    def shuffleAll(self):
        self.shufflePath("")

    @Slot(str)
    def shufflePlaylist(self, name):
        """Shuffle a playlist in AFTER the current song (bottom-bar behavior)."""
        return self._request_playlist_action("shuffle", name)

    @Slot("QVariantList")
    def playFilesShuffled(self, files):
        """Shuffle an explicit track list and play it NOW — the backend home
        for what shelf tiles used to do with hand-rolled JS Fisher-Yates
        (which got neither artist-spread nor gapless segues)."""
        self._shuffle_now([str(f) for f in files])

    # ---- shuffle-and-play-NOW: the buttons that sit on a collection ----------

    @Slot(str)
    def shufflePathNow(self, path):
        """Play a folder shuffled, starting right now."""
        return self._request_path_action("shuffle-now", path)

    @Slot()
    def shuffleAllNow(self):
        self.shufflePathNow("")

    @Slot(str)
    def shufflePlaylistNow(self, name):
        """Play a playlist shuffled, starting right now."""
        return self._request_playlist_action("shuffle-now", name)

    @Slot()
    def requestReshuffleQueue(self):
        """Reshuffle without any MPD read/write on Qt's input thread."""
        if self._dj_on:
            self.errorOccurred.emit(
                "End the DJ set before reshuffling its transition plan")
            return False
        plan = self._queue_sequencer.reshuffle_upcoming(
            self._queue, self._queue_pos)
        if plan.blocked_reason:
            self.errorOccurred.emit(plan.blocked_reason)
            return False
        if len(plan.song_ids) < 2:
            self.errorOccurred.emit("Nothing up next to reshuffle")
            return False
        if self._queue_reorder_busy:
            self.errorOccurred.emit("The queue is already being reshuffled")
            return False
        lease, _rejected = self._queue_mutations.acquire("reshuffle")
        if lease is None:
            self.errorOccurred.emit(
                "Queue is finishing another change — try again in a moment")
            return False

        self._queue_reorder_busy = True
        self._queue_reorder_generation += 1
        generation = self._queue_reorder_generation
        initial_random = bool(getattr(self, "_random", False))

        def work():
            errors = []
            success = False
            random_result = None
            final_random = initial_random
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    playback = PlaybackController(
                        cli, ensure_connected=lambda silent=False: True,
                        mark_disconnected=lambda: None,
                        error=errors.append)
                    random_result = playback.set_random_mode(False)
                    final_random = random_result.value
                    if random_result.committed:
                        success = playback.reorder_window(
                            plan.song_ids, plan.start)
                    if (not success and random_result.committed
                            and random_result.previous is not None
                            and random_result.previous != final_random):
                        restored = playback.set_random_mode(
                            random_result.previous)
                        final_random = restored.value
            except Exception as exc:
                errors.append(str(exc))
            self._queueReorderReady.emit({
                "generation": generation, "success": bool(success),
                "error": errors[-1] if errors else "", "lease": lease,
                "randomResult": random_result, "finalRandom": final_random,
                "workerOwnedRandom": True,
            })

        if self._start_worker(work, name="ampere-queue-reshuffle"):
            return True
        self._queue_reorder_busy = False
        lease.release()
        self.errorOccurred.emit(
            "Queue reshuffle could not start while Ampere is closing")
        return False

    @Slot()
    def reshuffleQueue(self):
        if self._dj_on:
            self.errorOccurred.emit(
                "End the DJ set before reshuffling its transition plan")
            return False
        plan = self._queue_sequencer.reshuffle_upcoming(
            self._queue, self._queue_pos)
        if plan.blocked_reason:
            self.errorOccurred.emit(plan.blocked_reason)
            return False
        if len(plan.song_ids) < 2:
            self.errorOccurred.emit("Nothing up next to reshuffle")
            return False
        if self._queue_reorder_busy:
            self.errorOccurred.emit(
                "The queue is already being reshuffled")
            return False
        lease, rejected = self._queue_mutations.acquire("reshuffle")
        if lease is None:
            self.errorOccurred.emit(
                "Queue is finishing another change — try again in a moment")
            return False
        random_result = self._set_random_mode_result(False)
        if not random_result.committed:
            lease.release()
            return False

        self._queue_reorder_busy = True
        self._queue_reorder_generation += 1
        generation = self._queue_reorder_generation

        def work():
            errors = []
            success = False
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    playback = PlaybackController(
                        cli,
                        ensure_connected=lambda silent=False: True,
                        mark_disconnected=lambda: None,
                        error=errors.append)
                    success = playback.reorder_window(
                        plan.song_ids, plan.start)
            except Exception as exc:
                errors.append(str(exc))
            self._queueReorderReady.emit({
                "generation": generation,
                "success": bool(success),
                "error": errors[-1] if errors else "",
                "lease": lease,
                "randomResult": random_result,
            })

        if self._start_worker(work, name="ampere-queue-reshuffle"):
            return True

        self._queue_reorder_busy = False
        lease.release()
        self._restore_ordered_random(random_result)
        self.errorOccurred.emit(
            "Queue reshuffle could not start while Ampere is closing")
        return False

    def _on_queue_reorder_ready(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        lease = payload.get("lease")
        if lease is not None:
            lease.release()
        if payload.get("generation") != self._queue_reorder_generation:
            return False
        self._queue_reorder_busy = False
        random_result = payload.get("randomResult")
        if payload.get("workerOwnedRandom"):
            final_random = bool(payload.get("finalRandom", self._random))
            if self._random != final_random:
                self._random = final_random
                self.statusChanged.emit()
        if not payload.get("success"):
            if (not payload.get("workerOwnedRandom")
                    and isinstance(random_result, PlaybackBooleanResult)):
                self._restore_ordered_random(random_result)
            self.errorOccurred.emit(
                str(payload.get("error") or "Queue order could not be verified"))
            return False
        self.refreshQueue()
        return True

    @Slot(str, "QVariantMap", result=bool)
    def requestContextShuffle(self, mode, context, *, seed=None, append=False,
                              automatic=False):
        """Plan an explicit context shuffle away from Qt's input thread.

        ``context`` is a route snapshot, not a UI object.  Its files are
        immutable at admission; a late route change therefore cannot publish
        a different collection than the listener selected.

        ``append`` is retained only as an internal compatibility argument and
        is rejected: Smart now ends with its admitted authored queue.
        """
        mode = str(mode or "").lower()
        context = dict(context or {})
        if mode not in ("standard", "smart"):
            return False
        if append and mode != "smart":
            return False
        # Smart augments only an authored queue admitted by Ampere. An MPD
        # queue restored at startup or edited by the listener is deliberately
        # unknown/manual and must never be reinterpreted as recommendation
        # consent. Standard remains valid for either kind.
        if mode == "smart" and (append
                or not self._smart_shuffle_available()):
            return False
        if self._dj_on:
            self.errorOccurred.emit(
                "End the DJ set before replacing its transition plan")
            return False
        generation = getattr(self, "_context_shuffle_generation", 0) + 1
        self._context_shuffle_generation = generation
        previous_cancel = getattr(
            self, "_context_shuffle_cancel_event", None)
        if isinstance(previous_cancel, threading.Event):
            previous_cancel.set()
        cancel_event = threading.Event()
        self._context_shuffle_cancel_event = cancel_event
        queue = tuple(dict(song) for song in self._queue)
        queue_pos = int(self._queue_pos)
        defined_files = tuple(getattr(self, "_defined_queue_files", ()) or ())
        freshness = self._context_shuffle_freshness()
        songs = tuple(dict(song) for song in self._library.songs)
        search_index = tuple(dict(entry) for entry in self._search_index)
        evidence = (dict(self._library_playcounts),
                    dict(self._library_planning_ratings),
                    dict(self._library_last_played),
                    dict(self._library_energies), dict(self._library_bpms))
        planning_ready = bool(self._library_planning_ready)
        preferences = dict(self._library_preferences)
        current = dict(self._song)
        if not current and 0 <= self._queue_pos < len(queue):
            current = dict(queue[self._queue_pos])
        disliked, liked = tuple(self._disliked), tuple(self._liked)
        seed_override = dict(seed) if seed else {}
        if mode == "smart" and not append:
            anchor = current or next(
                (dict(song) for song in queue if song.get("file")), {})
            if anchor:
                self._context_shuffle_seed = anchor

        def work():
            payload = {"generation": generation,
                       "cancelEvent": cancel_event,
                       "freshness": freshness, "append": append,
                       "automatic": automatic,
                       "files": (), "error": ""}
            try:
                has_explicit = "files" in context
                explicit = [str(file) for file in context.get("files", []) if file]
                kind = str(context.get("kind") or "queue")
                path = str(context.get("path") or "")
                album = str(context.get("album") or "")
                playlist_name = str(context.get("name") or "")
                path_prefix = path.rstrip("/") + "/" if path else ""
                playlist_result, tails = None, {}
                if mode == "standard":
                    # Standard alone owns verified gapless joins. Smart's
                    # Fit + Flow recommendations must not depend on or reopen
                    # that unrelated evidence path.
                    with temporary_mpd_client(
                            HOST, PORT, timeout=15,
                            registry=self._workers) as cli:
                        playlist_result = (
                            PlaylistService.client_files_result(
                                cli, playlist_name)
                            if kind == "playlist" else None)
                        tail_evidence = self._stickers.values_result(
                            "joi_taildb", cli)
                    if not (getattr(tail_evidence, "available", False)
                            or getattr(tail_evidence, "retained", False)):
                        raise PlanningEvidenceUnavailable(
                            "gapless tail snapshot unavailable")
                    tails = tail_evidence.values
                if kind == "queue" or mode == "smart":
                    # Queue membership is resolved from the admitted backend
                    # snapshot, never from a caller-provided full queue.  This
                    # keeps already-heard songs behind the playhead even when
                    # an older frontend sends an explicit queue projection.
                    start = queue_pos + 1 if 0 <= queue_pos < len(queue) else 0
                    pool = [str(song.get("file") or "")
                            for song in queue[start:]]
                    if mode == "smart":
                        authored = set(defined_files)
                        pool = [file for file in pool if file in authored]
                elif has_explicit:
                    # An explicitly empty visible collection is empty.  It
                    # must fail honestly instead of broadening to the library.
                    pool = explicit
                elif kind == "playlist":
                    if not playlist_name:
                        raise ValueError("Playlist membership is unavailable")
                    if not playlist_result.success:
                        raise ValueError("Playlist membership is unavailable")
                    pool = list(playlist_result.files)
                else:
                    pool = [str(song.get("file") or "") for song in songs
                            if (not path_prefix or str(song.get("file") or "").startswith(path_prefix))
                            and (kind != "album" or not album
                                 or str(song.get("album") or "") == album)]
                library_files = {str(song.get("file") or "") for song in songs}
                pool = [file for file in pool
                        if file and file in library_files
                        and file not in disliked]
                playing_file = str(current.get("file") or "")
                pool = [file for file in pool if file != playing_file]
                artists = {str(song.get("file") or ""): str(song.get("artist") or "")
                           for song in songs}
                sequencer = self._queue_sequencer
                if mode == "standard":
                    if not pool:
                        raise ValueError("Nothing eligible in this context")
                    # Version policy is evidence-dependent; do not guess when
                    # that snapshot is absent.
                    if not planning_ready:
                        raise PlanningEvidenceUnavailable("planning snapshot unavailable")
                    pool = VersionPolicy.collapse(
                        pool, groups=VersionPolicy.groups(songs),
                        playcounts=evidence[0], preferences=preferences)
                    ordered = sequencer.shuffle_order(pool, artist_keys=artists)
                    # Standard is strictly exact-context: a hot tail may
                    # influence ordering only when its successor was already
                    # selected from this context.
                    final_eligible = set(pool)
                else:
                    seed = seed_override or current or next(
                        (song for song in queue if song.get("file")), {})
                    if not seed:
                        raise ValueError("Start a song before Smart Shuffle")
                    if not planning_ready:
                        raise PlanningEvidenceUnavailable("planning snapshot unavailable")
                    # Every authored queue member is protected from duplicate
                    # recommendation, including sibling versions. Smart adds
                    # to that queue; it never substitutes for it.
                    rested = queue
                    heard_files = {
                        str(song.get("file") or "")
                        for song in rested
                        if song.get("file")
                    }
                    groups = VersionPolicy.groups(songs)
                    # If one version was just heard, every sibling version is
                    # rested too. Otherwise Smart can follow a recording with
                    # its live/remastered duplicate a few tracks later.
                    heard_version_files = {
                        sibling
                        for siblings in groups.values()
                        if heard_files.intersection(siblings)
                        for sibling in siblings
                    }
                    smart_source_files = [
                        str(song.get("file") or "") for song in songs
                        if song.get("file")
                        and str(song.get("file")) not in disliked
                        and str(song.get("file")) not in heard_files
                        and str(song.get("file")) not in heard_version_files
                    ]
                    smart_files = VersionPolicy.collapse(
                        smart_source_files, groups=groups,
                        playcounts=evidence[0], preferences=preferences)
                    smart_eligible = set(smart_files)
                    smart_songs = [
                        song for song in songs
                        if str(song.get("file") or "") in smart_eligible]
                    pick_limit = max(1, len(pool) // 2)
                    picks = self._smart_mix.select(
                        seed, smart_songs,
                        counts=evidence[0], ratings=evidence[1],
                        last_played=evidence[2], energies=evidence[3],
                        bpms=evidence[4], disliked=disliked, liked=liked,
                        limit=pick_limit)
                    plan = self._smart_mix.order_window(
                        [seed] + picks, queue_pos=0, frontier=0,
                        window_size=len(picks), energies=evidence[3],
                        bpms=evidence[4], fresh=True)
                    recommendations = [
                        str(song.get("file") or "") for song in
                        (plan.songs if plan.songs else picks)]
                    ordered = Backend._sprinkle_smart_recommendations(
                        pool, recommendations)
                    # Smart may add only verified library picks to the exact
                    # admitted queue. The final filter therefore covers both
                    # sets without widening either.
                    final_eligible = set(pool) | smart_eligible
                    final_eligible.discard(playing_file)
                if mode == "standard":
                    tail_levels = {
                        file: float(value) for file, value in tails.items()
                        if str(value).replace(".", "", 1).replace(
                            "-", "", 1).isdigit()
                    }
                    successors = sequencer.album_successors(search_index)
                    # Never traverse an excluded album track as an invisible
                    # bridge to another eligible song. Every edge in a
                    # preserved gapless chain must remain inside the exact
                    # Standard context.
                    successors = {
                        file: following
                        for file, following in successors.items()
                        if file in final_eligible
                        and following in final_eligible
                    }
                    expanded = sequencer.extend_gapless(
                        ordered, tail_levels=tail_levels,
                        successors=successors)
                else:
                    # Smart's order is already the result of its Fit + Flow
                    # planner.  A later gapless pass used to inject unselected
                    # album successors and undo that curation.
                    expanded = ordered
                payload["files"] = tuple(
                    file for file in expanded if file in final_eligible)
                if not payload["files"]:
                    raise ValueError("Nothing eligible in this context")
            except Exception as exc:
                payload["error"] = str(exc) or "Shuffle planning failed"
            self._contextShuffleReady.emit(payload)

        if self._start_worker(work, name="ampere-context-shuffle"):
            return True
        self.errorOccurred.emit("Shuffle planning could not start while Ampere is closing")
        return False

    SMART_SPRINKLE_EVERY = 2

    @staticmethod
    def _sprinkle_smart_recommendations(authored, recommendations):
        """Preserve authored order and add a restrained recommendation lane."""
        authored = [str(file) for file in authored if file]
        recommendations = [str(file) for file in recommendations if file]
        if not authored or not recommendations:
            return authored
        result = []
        pick = 0
        for index, file in enumerate(authored, start=1):
            result.append(file)
            if (index % Backend.SMART_SPRINKLE_EVERY == 0
                    and pick < len(recommendations)):
                result.append(recommendations[pick])
                pick += 1
        return result

    def _smart_shuffle_available(self):
        """Smart belongs only to an admitted, non-album authored queue."""
        return (bool(getattr(self, "_defined_queue_active", False))
                and str(getattr(
                    self, "_defined_queue_kind", "unknown")) != "album")

    @staticmethod
    def _remaining_authored_in_source_order(authored, queue, queue_pos):
        """Return the unplayed source-order tail after the latest anchor.

        Standard may have played authored tracks out of order and Smart may
        place a recommendation at the playhead. The latest authored track at
        or before the playhead anchors the normal source-order continuation;
        any other authored occurrences already heard are removed from that
        tail so OFF never replays them. Duplicate files remain occurrence-
        counted rather than being collapsed by membership.
        """
        authored = tuple(str(file) for file in authored if file)
        if not authored:
            return ()
        try:
            end = min(max(int(queue_pos), -1) + 1, len(queue))
        except (TypeError, ValueError):
            end = 0
        prefix = [str(song.get("file") or "")
                  for song in tuple(queue)[:end]]
        authored_counts = Counter(authored)
        heard_counts = Counter()
        for file in prefix:
            if heard_counts[file] < authored_counts[file]:
                heard_counts[file] += 1

        anchor_file = next(
            (file for file in reversed(prefix) if file in authored_counts), "")
        if not anchor_file:
            return authored
        anchor_occurrence = max(1, heard_counts[anchor_file])
        seen = 0
        anchor_index = -1
        for index, file in enumerate(authored):
            if file == anchor_file:
                seen += 1
                if seen == anchor_occurrence:
                    anchor_index = index
                    break
        if anchor_index < 0:
            return authored

        source_prefix_counts = Counter(authored[:anchor_index + 1])
        extra_heard = heard_counts - source_prefix_counts
        remaining = []
        for file in authored[anchor_index + 1:]:
            if extra_heard[file] > 0:
                extra_heard[file] -= 1
            else:
                remaining.append(file)
        return tuple(remaining)

    def _restore_authored_queue_order(self):
        """Keep the current song and replace shuffle output with source order."""
        if not getattr(self, "_defined_queue_active", False):
            return True
        authored = tuple(getattr(self, "_defined_queue_files", ()) or ())
        files = Backend._remaining_authored_in_source_order(
            authored, tuple(self._queue), self._queue_pos)
        pos = int(self._queue_pos)
        playing = (0 <= pos < len(self._queue)
                   and self._state in ("play", "pause"))
        request = {
            "files": files,
            "session": "manual",
            "preserveQueueContext": True,
        }
        if playing:
            current_id = self._queue[pos].get("id", -1)
            if current_id < 0:
                return False
            request["currentId"] = current_id
            return self._request_queue_intent("replace-upcoming", request)
        request.update({
            "startIndex": 0,
            "queueContext": str(getattr(
                self, "_defined_queue_kind", "defined")),
        })
        return self._request_queue_intent("replace", request)

    def _drain_context_shuffle_restore(self):
        if not getattr(self, "_context_shuffle_restore_pending", False):
            return False
        coordinator = getattr(self, "_queue_mutations", None)
        if coordinator and coordinator.active_owner:
            return True
        self._context_shuffle_restore_pending = False
        if self._restore_authored_queue_order():
            return True
        self._context_shuffle_restore_pending = True
        return False

    def _record_queue_context(self, kind, request):
        """Publish queue provenance only after the MPD mutation succeeds."""
        request = dict(request or {})
        if request.get("preserveQueueContext"):
            return
        if request.get("manualQueueEdit"):
            self._defined_queue_active = False
            self._defined_queue_kind = "manual"
            self._defined_queue_files = ()
            if getattr(self, "_context_shuffle_mode", "off") == "smart":
                self._set_context_shuffle_mode("off")
            return
        if kind != "replace":
            return
        context = str(request.get("queueContext") or "manual")
        files = tuple(str(file) for file in request.get("files", ()) if file)
        self._defined_queue_active = (
            context not in ("", "manual", "unknown") and len(files) > 1)
        self._defined_queue_kind = (
            context if self._defined_queue_active else "manual")
        self._defined_queue_files = (
            files if self._defined_queue_active else ())
        if ((not self._defined_queue_active
                or not self._smart_shuffle_available())
                and getattr(self, "_context_shuffle_mode", "off") == "smart"):
            self._set_context_shuffle_mode("off")

    @Property(str, notify=contextShuffleModeChanged)
    def contextShuffleMode(self):
        return self._context_shuffle_mode

    def _set_context_shuffle_mode(self, mode):
        if mode != "off" and getattr(self, "_beacon", None):
            self._beacon.cancel()
        mode = mode if mode in ("off", "standard", "smart") else "off"
        if self._context_shuffle_mode != mode:
            self._context_shuffle_mode = mode
            self.contextShuffleModeChanged.emit()
            # Sync to SessionService: smart shuffle is a session type,
            # mutually exclusive with radio/mood/sonic-profile.
            sessions = getattr(self, "_sessions", None)
            if sessions:
                if mode == "smart":
                    seed = dict(getattr(self, "_context_shuffle_seed", {})) or {}
                    sessions.set_smart_shuffle(seed)
                elif mode == "off":
                    # Turning off context shuffle clears smart-shuffle session only,
                    # leaving radio/mood/sonic-profile active if they were running.
                    session = sessions.state
                    if session.smart_shuffle_active:
                        sessions.end_smart_shuffle()
            result = self._settings.try_patch({"context_shuffle_mode": mode})
            Backend._handle_settings_save_result(
                self, result,
                failure_message="Shuffle mode was not saved")

    @Slot("QVariantMap", result=bool)
    def cycleContextShuffle(self, context):
        """Advance the one shared player shuffle mode in the activation frame."""
        current = self._context_shuffle_mode
        next_mode = ("standard" if current == "off" else
                     "smart" if (current == "standard"
                                  and self._smart_shuffle_available())
                     else "off")
        self._set_context_shuffle_mode(next_mode)
        if next_mode == "off":
            # Invalidate a planning payload before it can publish, then replace
            # any already-published shuffle output with the authored source
            # order. If publication still owns the queue lease, its completion
            # drains this pending restore after releasing that lease.
            self._context_shuffle_generation += 1
            cancel_event = getattr(
                self, "_context_shuffle_cancel_event", None)
            if isinstance(cancel_event, threading.Event):
                cancel_event.set()
            self._context_shuffle_cancel_event = None
            if getattr(self, "_defined_queue_active", False):
                self._context_shuffle_restore_pending = True
                self._drain_context_shuffle_restore()
            return True
        if self.requestContextShuffle(next_mode, context):
            return True
        self._set_context_shuffle_mode("off")
        return False

    def _on_context_shuffle_ready(self, payload):
        if not isinstance(payload, dict) or payload.get("generation") != \
                getattr(self, "_context_shuffle_generation", 0):
            if payload.get("append") if isinstance(payload, dict) else False:
                self._finish_smart_refill(False, quiet=True)
            return False
        files = tuple(payload.get("files") or ())
        if payload.get("append"):
            return self._publish_smart_refill(payload, files)
        # SPEC row 197 returns the indicator to OFF when a plan fails, so it
        # can never claim an order it did not publish. That still holds for a
        # plan the listener ASKED for. It must not hold for the automatic
        # re-application of a standing preference (Iann, 2026-08-22): one
        # stale snapshot would silently erase a choice that is now persisted,
        # and the next selection would quietly play in order forever.
        automatic = bool(payload.get("automatic"))
        if payload.get("freshness") != self._context_shuffle_freshness():
            self.errorOccurred.emit(
                "Shuffle plan became stale — the queue was not changed")
            if not automatic:
                self._set_context_shuffle_mode("off")
            return False
        if payload.get("error") or not files:
            self.errorOccurred.emit(
                "Shuffle could not be prepared — the queue was not changed")
            if not automatic:
                self._set_context_shuffle_mode("off")
            return False
        generation = payload.get("generation")
        cancel_event = payload.get("cancelEvent")
        if (isinstance(cancel_event, threading.Event)
                and cancel_event.is_set()):
            return False
        accepted = self._queue_after_current(
            files, on_finished=lambda success: (
                self._set_context_shuffle_mode("off")
                if (not success and not automatic
                    and generation == self._context_shuffle_generation)
                else None), cancel_event=cancel_event)
        if not accepted and not automatic:
            self._set_context_shuffle_mode("off")
        return accepted

    # ---- smart shuffle refill (disabled by the current product contract) ---
    REFILL_AT = 2         # upcoming songs left before ANY session grows
    SMART_REFILL_AT = REFILL_AT   # compatibility name for shared threshold

    def _session_kind(self):
        """The single answer to 'which session owns the queue right now'.

        SessionService is the owner (ampere/sessions.py); its state already
        makes the transient kinds mutually exclusive. Autoplay is a persisted
        preference outside that service, and ranks below curated sessions and
        Smart Shuffle. Each refill used to re-derive this for
        itself, with its own legacy fallback, which is exactly how the four
        transition layers drifted apart (ROADMAP 3.1, 2026-08-22).  The
        fallback below exists only for test doubles that build a Backend
        without running __init__; it lives here once instead of at every
        caller."""
        beacon = getattr(self, "_beacon", None)
        if beacon and (beacon.active_id or beacon.busy
                       or getattr(getattr(beacon, "recovery", None), "data", None) is not None):
            return "beacon"
        sessions = getattr(self, "_sessions", None)
        if sessions is not None:
            kind = sessions.state.kind
            if kind in ("mood", "sound-profile", "smart-shuffle"):
                return kind
        if getattr(self, "_mood_on", ""):
            return "mood"
        if getattr(self, "_context_shuffle_mode", "off") == "smart":
            return "smart-shuffle"
        if getattr(self, "_autoplay_on", False):
            return "autoplay"
        return "manual"

    # A session refills only while nothing more deliberate owns the queue:
    # repeat is a chosen loop, and DJ owns its own plan (the four-layer
    # ownership contract below).
    def _refill_blocked(self):
        return (bool(getattr(self, "_repeat", False))
                or bool(getattr(self, "_dj_on", False))
                or self._state != "play" or self._queue_pos < 0)

    def _queue_is_dry(self):
        return len(self._queue) - 1 - self._queue_pos <= Backend.REFILL_AT

    def _maybe_smart_refill(self):
        """Smart ends with its authored queue; it is not an endless session."""
        return False

    def _publish_smart_refill(self, payload, files):
        if payload.get("freshness") != self._context_shuffle_freshness():
            self._finish_smart_refill(False, quiet=True, delay=2.0)
            return False
        if payload.get("error") or not files:
            self._finish_smart_refill(False)
            return False
        cancel_event = payload.get("cancelEvent")
        if (isinstance(cancel_event, threading.Event)
                and cancel_event.is_set()):
            self._finish_smart_refill(False, quiet=True)
            return False
        request = {"files": tuple(self._drop_disliked(files))[:200],
                   "errorPrefix": "Smart shuffle refill failed: "}
        if cancel_event is not None:
            request["cancelEvent"] = cancel_event
        if not request["files"]:
            self._finish_smart_refill(False)
            return False
        return self._request_queue_intent(
            "append", request, on_finished=self._finish_smart_refill)

    def _finish_smart_refill(self, success, *, quiet=False, delay=30.0):
        self._smart_refill_busy = False
        if success:
            self._smart_refill_retry_at = 0.0
            self._smart_refill_failure_reported = False
            return True
        self._smart_refill_retry_at = time.monotonic() + delay
        if not quiet and not getattr(
                self, "_smart_refill_failure_reported", False):
            self._smart_refill_failure_reported = True
            self.errorOccurred.emit(
                "Smart shuffle could not find more songs; Ampere will retry shortly")
        return False

    def _context_shuffle_freshness(self):
        """Stable admission token: playhead plus queue membership/order."""
        queue = tuple(getattr(self, "_queue", ()) or ())
        pos = int(getattr(self, "_queue_pos", -1))
        song = dict(getattr(self, "_song", {}) or {})
        if not song and 0 <= pos < len(queue):
            song = dict(queue[pos] or {})
        return (pos, str(song.get("id") or ""), str(song.get("file") or ""),
                tuple((str(item.get("id") or ""),
                       str(item.get("file") or ""))
                      for item in queue if isinstance(item, dict)))

    # ---- smart mix (the mixtape engine) ----------------------------------
    # OWNERSHIP CONTRACT (audit #9 — the four transition layers, resolved):
    #   1. SELECT  — smart shuffle (_smart_picks/shuffleSmart/moreLikeThis):
    #                picks WHICH songs by taste (subgenre/artist/history).
    #                No BPM, no transitions. Owns the pool.
    #   2. ORDER   — smart mix (this engine, _mix_extend): arranges songs
    #                ALREADY chosen so neighbours join smoothly (energy arc,
    #                BPM tiebreak, artist spread). Does NOT select — it is
    #                the ordering ARM OF AUTO-MIX, not a shuffle. This is the
    #                "blend-by-BPM" that never belonged in shuffle.
    #   3. JOIN    — auto-mix (_apply_automix, mix_style blend|fade): the
    #                actual audio hand-off (crossfade / MixRamp fade-in)
    #                between two ordered neighbours.
    #   4. PERFORM — DJ mode (the deck): beatmatched CUTS, drops, rendered
    #                bridges, key/tempo gates. The performance tier; owns the
    #                transition knobs while live (auto-mix's JOIN steps aside).
    # Redundancy dissolves because each owns a different layer: shuffle =
    # which songs, smart-mix = their order, auto-mix = how they join, DJ =
    # the show. Stage 2+3 UI merge SHIPPED 0.21.0: Settings presents this
    # engine as Auto-mix's "Ordering" row (OFF/SMOOTH/WAVE ARC) — no more
    # standalone "Smart mix" language anywhere user-facing.
    #
    # Reorders the UPCOMING queue so consecutive songs bridge by energy
    # (BPM as tiebreak, artists spread), like a hand-sequenced mixtape.
    # Windowed so a 2000-song queue never costs a big gulp: MIX_WINDOW
    # songs are curated past the playhead, and the frontier extends itself
    # as playback approaches it. The mix is fingerprinted by the SET of
    # queued songs — re-toggling on the same queue restores instead of
    # recomputing (accidental-click armor); a fresh order only happens via
    # smartMixReshuffle (right-click → RESHUFFLE MIX).

    MIX_WINDOW = 80
    MIX_EXTEND_AT = 15

    def _mix_fingerprint(self):
        return hashlib.sha1("\n".join(sorted(
            s.get("file", "") for s in self._queue)).encode(),
            usedforsecurity=False).hexdigest()

    @Property(bool, notify=smartMixChanged)
    def smartMixOn(self):
        return self._mix_on

    @Property(bool, notify=settingsChanged)
    def mixArc(self):
        return self._mix_arc

    @Slot(bool)
    def setMixArc(self, on):
        """Wave-arc mode: the mix rises to a peak and cools down instead of
        holding a flat bridge. Applies from the next curation pass."""
        self._mix_arc = bool(on)
        self._save_conf()
        self.settingsChanged.emit()

    @Slot()
    def smartMixStart(self):
        """Turn the mixtape on. Same queue as the cached mix -> the curated
        order is already in place, so this is a pure no-op re-enable."""
        self._mix_on = True
        fp = self._mix_fingerprint()
        if fp != self._mix_fp:
            self._mix_fp = fp
            self._mix_frontier = self._queue_pos
            self._mix_extend()
        self._save_conf()
        self.smartMixChanged.emit()

    @Slot()
    def smartMixOff(self):
        """Off = stop curating. The already-ordered queue stays as it is."""
        self._mix_on = False
        self._save_conf()
        self.smartMixChanged.emit()

    @Slot()
    def smartMixReshuffle(self):
        """Deliberate rebuild: re-curate from the playhead with fresh
        randomness (the only way to get a different mix on purpose)."""
        self._mix_on = True
        self._mix_frontier = self._queue_pos
        self._mix_extend(fresh=True)
        self._mix_fp = self._mix_fingerprint()
        self._save_conf()
        self.smartMixChanged.emit()

    def _maybe_mix_extend(self):
        if not self._mix_on or self._queue_pos < 0:
            return
        if self._mix_frontier - self._queue_pos > self.MIX_EXTEND_AT \
                or self._mix_frontier >= len(self._queue) - 1:
            return
        self._mix_frontier = max(self._mix_frontier, self._queue_pos)
        self._mix_extend()

    def _mix_extend(self, fresh=False):
        """Curate the next MIX_WINDOW songs after the frontier in place
        (moveid — nothing is added or removed, only reordered). The two
        library sticker scans (energy + bpm) run on a worker; publication
        captures stable IDs and the shared queue-intent worker owns the MPD
        reorder. Guarded by _mix_busy so refreshStatus cannot stack work."""
        if self._mix_busy or (not fresh and time.monotonic()
                              < getattr(self, "_mix_retry_at", 0.0)):
            return
        self._mix_busy = True

        def work():
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as c:
                    energies = self._planning_energies(c)
                    bpms = {}
                    for f, v in self._planning_sticker_map(
                            "joi_bpm", c).items():
                        try:
                            bpms[f] = float(v)
                        except ValueError:
                            pass
            except Exception:
                self._mixMapsReady.emit({"error": "scan_failed"})
                return
            self._mixMapsReady.emit(
                {"fresh": fresh, "energies": energies, "bpms": bpms})

        if not self._start_worker(work, name="ampere-smart-mix"):
            self._finish_mix_maps_failure(
                "Smart mix analysis could not start while Ampere is closing")

    def _on_mix_maps(self, m):
        """Reorder the upcoming window from the worker's energy/bpm maps and
        submit its stable-ID plan through the queue-intent boundary."""
        if m.get("error") == "scan_failed":
            self._finish_mix_maps_failure()
            return
        try:
            plan = self._smart_mix.order_window(
                self._queue, queue_pos=self._queue_pos,
                frontier=self._mix_frontier, window_size=self.MIX_WINDOW,
                energies=m["energies"], bpms=m["bpms"],
                arc=self._mix_arc, fresh=m["fresh"])
        except Exception:
            self._finish_mix_maps_failure()
            return
        if not plan.reorderable:
            self._mix_frontier = plan.frontier
            self._finish_mix_maps_success()
            return
        song_ids = [song.get("id") for song in plan.songs]
        if any(song_id is None for song_id in song_ids):
            self._finish_mix_maps_failure(
                "Smart mix failed: queue snapshot has no stable IDs")
            return
        return self._request_queue_intent(
            "reorder", {
                "songIds": tuple(song_ids),
                "start": plan.start + 1,
            },
            on_finished=lambda success:
                self._finish_mix_reorder(plan.frontier, success))

    def _finish_mix_reorder(self, frontier, success):
        if not success:
            self._finish_mix_maps_failure(
                "Smart mix reorder could not be confirmed; the queue was "
                "left unchanged")
            return False
        self._mix_frontier = frontier
        self._finish_mix_maps_success()
        return True

    def _finish_mix_maps_success(self):
        self._mix_busy = False
        self._mix_retry_at = 0.0
        self._mix_failure_reported = False

    def _finish_mix_maps_failure(
            self, message="Smart mix analysis failed; the queue was not changed"):
        self._mix_busy = False
        self._mix_retry_at = time.monotonic() + 30.0
        if not getattr(self, "_mix_failure_reported", False):
            self._mix_failure_reported = True
            self.errorOccurred.emit(message)

    def _smart_picks(self, seed):
        """Discovery-forward picks with a familiar compatibility spine."""
        counts, ratings, last, energies, bpms = \
            self._cached_listening_evidence()
        return self._smart_mix.select(
            seed, self._library.songs, counts=counts, ratings=ratings,
            last_played=last, energies=energies, bpms=bpms,
            disliked=self._disliked, liked=self._liked, limit=50)

    @Slot()
    def shuffleSmart(self):
        """"Recommended next": a smart session seeded by the playing song.
        Keeps the current song playing and replaces everything after it.
        Nothing playing → seeds from the last thing he actually listened to."""
        try:
            seed = self._song or self._last_played_song()
            picks = self._smart_picks(seed)
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "Smart Shuffle could not verify listening data — the queue "
                "was not changed")
            return
        if not picks:
            self.shuffleAll()
            return
        try:
            files = self._gapless_extend([s["file"] for s in picks])
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "Smart Shuffle could not verify gapless album data — the "
                "queue was not changed")
            return
        self._queue_after_current(files)

    @Slot(str)
    def moreLikeThis(self, file):
        """Right-click on any track → that track plays NOW with a smart
        session built behind it (same picks engine as shuffleSmart, seeded
        by the chosen track instead of the playing one)."""
        idx = self._library.by_file
        seed = idx.get(file)
        if not seed:
            self.errorOccurred.emit("Track not in the index yet")
            return
        try:
            picks = self._smart_picks(seed)
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "More Like This could not verify listening data — the queue "
                "was not changed")
            return
        try:
            files = [file] + self._gapless_extend(
                [s["file"] for s in picks if s["file"] != file])
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "More Like This could not verify gapless album data — the "
                "queue was not changed")
            return
        self.notice.emit("Finding more like this…")
        self.playFiles(files, 0)

    # ---- Autoplay (verified library continuation) ----------------------------

    @Property(bool, notify=settingsChanged)
    def autoplayOn(self):
        return self._autoplay_on

    @Slot(bool)
    def setAutoplayOn(self, on):
        on = bool(on)
        if on == self._autoplay_on:
            return
        self._autoplay_on = on
        self._autoplay_generation += 1
        if on:
            self._radio_retry_at = 0.0
        self._save_conf()
        self.settingsChanged.emit()
        if self._autoplay_on:
            self._maybe_radio_refill()

    @Property(str, notify=settingsChanged)
    def radioMood(self):
        return self._radio_mood

    @Slot(str)
    def setRadioMood(self, mood):
        if mood in ("match", "any", "calm", "heavy"):
            self._radio_mood = mood
            self._save_conf()
            self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def ratingMode(self):
        """"hearts" = like/dislike hearts; "stars" = 1-5 star ratings (future)."""
        return self._rating_mode

    @Slot(str)
    def setRatingMode(self, mode):
        if mode in ("hearts", "stars"):
            self._rating_mode = mode
            self._save_conf()
            self.settingsChanged.emit()

    def _energies(self, cli=None) -> dict:
        out = {}
        for f, v in self._sticker_map("joi_energy", cli).items():
            try:
                out[f] = float(v)
            except ValueError:
                pass
        return out

    def _maybe_radio_refill(self):
        """Queue nearly dry → quietly append a verified continuation.
        Skipped under repeat (a loop is a deliberate choice). The ranking does
        3-4 whole-library sticker scans, so it runs on a WORKER thread (own MPD
        client) — the append happens back on the GUI thread in _on_radio_ready."""
        beacon = getattr(self, "_beacon", None)
        if beacon:
            beacon.tick()
        owner = Backend._session_kind(self)
        if (owner not in ("autoplay", "mood", "sound-profile")
                or self._radio_busy
                or Backend._refill_blocked(self)
                or time.monotonic()
                < getattr(self, "_radio_retry_at", 0.0)):
            return
        if not Backend._queue_is_dry(self):
            return
        self._radio_busy = True
        generation = getattr(self, "_autoplay_generation", 0)
        freshness = Backend._context_shuffle_freshness(self)

        def work():
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as c:
                    files = self._radio_picks(cli=c)
            except Exception:
                self._radioReady.emit({
                    "error": "scan_failed",
                    "generation": generation,
                    "owner": owner,
                    "freshness": freshness,
                })
                return
            self._radioReady.emit({
                "files": files,
                "generation": generation,
                "owner": owner,
                "freshness": freshness,
            })

        if not self._start_worker(work, name="ampere-radio-refill"):
            self._finish_radio_failure(
                "Autoplay could not start while Ampere is closing")

    def _on_radio_ready(self, result):
        """Submit the worker's picks to the shared queue-intent boundary."""
        generation = result.get("generation")
        owner = str(result.get("owner") or "")
        freshness = result.get("freshness")
        # Production workers always carry both tokens. Tokenless payloads are
        # retained only for narrow unit harnesses and older internal callers.
        if generation is not None or owner:
            current_owner = Backend._session_kind(self)
            stale = (
                generation != getattr(self, "_autoplay_generation", 0)
                or owner != current_owner
                or (freshness is not None
                    and freshness != Backend._context_shuffle_freshness(self))
                or current_owner not in (
                    "autoplay", "mood", "sound-profile")
                or Backend._refill_blocked(self)
                or not Backend._queue_is_dry(self)
            )
            if stale:
                self._radio_busy = False
                return False
        if result.get("error") == "scan_failed":
            self._finish_radio_failure()
            return
        files = result.get("files", [])
        if not files:
            self._finish_radio_failure(
                "Autoplay found no new tracks; Ampere will retry shortly")
            return
        return self._request_queue_intent(
            "append", {
                "files": tuple(files),
                "errorPrefix": "Autoplay failed: ",
            }, on_finished=self._finish_radio_append)

    def _finish_radio_append(self, success):
        if not success:
            self._finish_radio_failure(
                "Autoplay could not update the queue; Ampere will retry shortly")
            return False
        self._radio_busy = False
        self._radio_retry_at = 0.0
        self._radio_failure_reported = False
        return True

    def _finish_radio_failure(
            self, message="Autoplay failed; Ampere will retry shortly"):
        self._radio_busy = False
        self._radio_retry_at = time.monotonic() + 30.0
        if not getattr(self, "_radio_failure_reported", False):
            self._radio_failure_reported = True
            self.errorOccurred.emit(message)

    def _radio_picks(self, count=15, cli=None, *, plain=False, cached=False):
        """Rank the session genre's tracks: ratings, likes and play counts
        float up, very-recently-played sits out, artists spread. The mood
        setting shapes picks by analyzed energy (joi_energy stickers). `cli`
        lets this run on a WORKER thread (the 3-4 full-library sticker scans
        below were the GUI-thread stutter when the queue ran dry)."""
        if self._mood_on and not plain:   # mood session steers its refill
            return self._mood_picks(self._mood_on, count=count, cli=cli)
        if cached:
            counts, ratings, last, energies, _bpms = \
                self._cached_listening_evidence()
        else:
            counts = self._planning_counts(cli)
            ratings = self._planning_sticker_map("rating", cli)
            last = self._planning_sticker_map("lastPlayed", cli)
            energies = self._planning_energies(cli)
        if self._radio_mood == "any":
            energies = {}
        picks = self._sessions.radio_picks(
            self._library.songs, seed=self._song,
            queued=(song["file"] for song in self._queue), counts=counts,
            ratings=ratings, last_played=last, liked=self._liked,
            disliked=self._disliked, energies=energies,
            mood=self._radio_mood, count=count)
        return self._gapless_extend(picks, cli)

    # ---- mood radio (the quickstart emotion tile) ----------------------------

    @Property(str, notify=settingsChanged)
    def moodRadioOn(self):
        """Active mood-radio session's MOODS key ("" = off)."""
        return self._mood_on

    @Slot(result="QVariantList")
    def moodList(self):
        return [{"key": k, "label": v["label"]} for k, v in MOODS.items()]

    def _end_mood_session(self):
        """Any deliberate new session (explicit play or a shuffle)
        ends the mood session — the refill must not keep dragging the old
        emotion into whatever he started instead. Sound-profile sessions live
        by the same law, from the same call sites. Autoplay is independent and
        never starts or ends a curated session."""
        if self._sessions.end_curated():
            self._sync_session_state()
            self.settingsChanged.emit()

    def _sync_session_state(self):
        state = self._sessions.state
        self._mood_on = state.mood

    def _mood_picks(self, mood, count=25, cli=None):
        """Rank the WHOLE library against one MOODS emotion: his curated mood
        playlists are trusted exemplars (+ energy-skip exemption), genre
        weights shape the pool (unlisted genres are out entirely), the
        joi_energy band tunes within it, and the usual taste signals
        (likes/ratings/play counts, recently-played rest) ride on top. Same
        worker-thread `cli` convention as _radio_picks."""
        spec = MOODS.get(mood)
        if not spec:
            return []
        c = cli or self._cmd
        exemplars = set()
        for name in spec["playlists"]:
            result = PlaylistService.client_files_result(c, name)
            if not result.success:
                raise RuntimeError("mood exemplar snapshot unavailable")
            exemplars.update(result.files)
        counts = self._planning_counts(cli)
        ratings = self._planning_sticker_map("rating", cli)
        last = self._planning_sticker_map("lastPlayed", cli)
        energies = self._planning_energies(cli)
        picks = self._sessions.mood_picks(
            self._library.songs, spec, exemplars=exemplars,
            queued=(song["file"] for song in self._queue), counts=counts,
            ratings=ratings, last_played=last, liked=self._liked,
            disliked=self._disliked, energies=energies, count=count)
        return self._gapless_extend(picks, cli)

    def _start_curated_plan(self, kind, key, *, profile=None):
        if self._curated_plan_busy:
            self.errorOccurred.emit(
                "Another listening session is already being planned")
            return False
        self._curated_plan_busy = True
        self._curated_plan_key = (str(kind), str(key))
        profile = dict(profile) if isinstance(profile, dict) else None

        def work():
            result = {
                "kind": kind, "key": key, "files": None,
                "name": str((profile or {}).get("name") or ""),
            }
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    if kind == "mood":
                        result["files"] = self._mood_picks(
                            key, count=25, cli=cli)

            except Exception:
                result["error"] = "planning_failed"
            self._curatedPlanReady.emit(result)

        if self._start_worker(
                work, name=f"ampere-{kind}-session-plan"):
            return True
        self._curated_plan_busy = False
        self._curated_plan_key = None
        self.errorOccurred.emit(
            "Listening-session planning could not start while Ampere is closing")
        return False

    def _on_curated_plan_ready(self, result):
        """Mood is the only curated kind left: Saved Sound Profiles were
        retired in 6157232, and the profile branches here still emitted
        signals that had been commented out with them (found 2026-08-23)."""
        if not isinstance(result, dict):
            active = self._curated_plan_key
            self._curated_plan_busy = False
            self._curated_plan_key = None
            self.errorOccurred.emit(
                "Listening-session planning returned an invalid result — "
                "the queue was not changed")
            if active:
                self.moodRadioStartFinished.emit(active[1], 0, False)
            return
        kind = str(result.get("kind") or "")
        key = str(result.get("key") or "")
        if (kind, key) != self._curated_plan_key:
            return
        self._curated_plan_busy = False
        self._curated_plan_key = None
        files = result.get("files")
        if result.get("error") or not isinstance(files, list):
            self.errorOccurred.emit(
                "Mood Radio could not verify its planning data — "
                "the queue was not changed")
            self.moodRadioStartFinished.emit(key, 0, False)
            return
        if not files:
            self.errorOccurred.emit("No tracks match that mood yet")
            self.moodRadioStartFinished.emit(key, 0, False)
            return
        self._play_curated_session(
            files, mood=key,
            on_finished=lambda committed: self.moodRadioStartFinished.emit(
                key, len(files) if committed else 0, committed))

    @Slot(str, result=bool)
    def startMoodRadio(self, mood):
        """The quickstart emotion chips: build a queue tuned to the mood, play
        it, and leave radio ON in a mood session so the refill stays on
        emotion until he starts something else."""
        if mood not in MOODS:
            return False
        return self._start_curated_plan("mood", mood)

    # Saved Sound Profiles were retired in 6157232 and their module deleted;
    # the block that lived here still called SoundProfileService and would
    # have raised on any call. The Character vocabulary replaced it
    # (ampere/characters.py, Iann 2026-08-22).

    def _character_features(self, cli=None) -> dict:
        """file -> the four measurements a character selects on.

        A track with no measurement is left out of its own entry rather than
        defaulted: an unmeasured file must never be guessed into a character
        (design/DECISIONS.md 2026-08-22)."""
        maps = {}
        for axis, sticker in (("energy", "joi_energy"), ("bass", "joi_bass"),
                              ("bright", "joi_bright"), ("dyn", "joi_dyn")):
            values = {}
            for file, raw in self._planning_sticker_map(sticker, cli).items():
                try:
                    values[file] = float(raw)
                except (TypeError, ValueError):
                    pass
            maps[axis] = values
        features = {}
        for axis, values in maps.items():
            for file, value in values.items():
                features.setdefault(file, {})[axis] = value
        return features

    def _character_picks(self, key, count=25, cli=None, exclude_queued=True):
        """Rank the whole library against one audited character."""
        if key not in characterlib.BY_KEY:
            return []
        features = self._character_features(cli)
        songs = self._library.songs
        durations = {song.get("file", ""): song.get("duration", 0.0)
                     for song in songs}
        queued = ({s["file"] for s in self._queue}
                  if exclude_queued else set())
        picks = characterlib.select(
            songs, features, character=key, count=count * 2,
            disliked=self._disliked, queued=queued, durations=durations)
        # One version of a song per selection, same policy every other
        # selector obeys.
        picks = self._collapse_versions(picks)[:count]
        return self._gapless_extend(picks, cli)

    @Property("QVariantList", constant=True)
    def soundCharacters(self):
        """The audited vocabulary, for the surface to render."""
        return [{"key": entry["key"], "label": entry["label"],
                 "blurb": entry["blurb"]}
                for entry in characterlib.CHARACTERS]

    @Property("QVariantList", notify=soundMixesChanged)
    def soundMixes(self):
        """Every mix he has built, newest first, with its membership."""
        return [dict(mix) for mix in self._sound_mixes]

    def _remember_mix(self, character, files):
        """A built mix is evidence of a real choice, so it is kept until it
        falls off the end — he can replay it or turn it into a playlist long
        after the queue moved on (Iann, 2026-08-22)."""
        files = [str(f) for f in files if f]
        if not files or character not in characterlib.BY_KEY:
            return ""
        mix_id = uuid.uuid4().hex[:12]
        entry = {"id": mix_id, "character": character,
                 "label": characterlib.label(character),
                 "created": time.time(), "files": files}
        self._sound_mixes = clean_sound_mixes([entry] + self._sound_mixes)
        self.soundMixesChanged.emit()
        result = self._settings.try_patch({"sound_mixes": self._sound_mixes})
        Backend._handle_settings_save_result(
            self, result, failure_message="Mix history could not be saved")
        return mix_id

    @Slot(str, int, result=str)
    def buildCharacterMix(self, key, count):
        """Build one character, play it now, and keep it in the history.

        Returns the new mix id, or "" when nothing could be built."""
        key = str(key)
        try:
            files = self._character_picks(key, count=max(1, int(count or 25)))
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "Ampere could not verify its listening data — nothing was built")
            return ""
        if not files:
            self.errorOccurred.emit(
                f"No tracks match {characterlib.label(key) or key}")
            return ""
        mix_id = Backend._remember_mix(self, key, files)
        self.playFiles(files, 0)
        return mix_id

    @Slot(str, result=bool)
    def playSoundMix(self, mix_id):
        """Replay a kept mix exactly as it was built."""
        for mix in self._sound_mixes:
            if mix.get("id") == str(mix_id):
                files = [f for f in mix.get("files", ()) if f]
                if not files:
                    return False
                self.playFiles(files, 0)
                return True
        return False

    @Slot(str, str, result=bool)
    def saveSoundMixAs(self, mix_id, name):
        """Port a kept mix into a real playlist, unchanged."""
        playlist = str(name or "").strip()
        if not playlist:
            return False
        for mix in self._sound_mixes:
            if mix.get("id") == str(mix_id):
                files = [f for f in mix.get("files", ()) if f]
                if not files:
                    return False
                self.addToPlaylist(playlist, files)
                return True
        return False

    @Slot(str, result=bool)
    def forgetSoundMix(self, mix_id):
        remaining = [m for m in self._sound_mixes if m.get("id") != str(mix_id)]
        if len(remaining) == len(self._sound_mixes):
            return False
        self._sound_mixes = remaining
        self.soundMixesChanged.emit()
        result = self._settings.try_patch({"sound_mixes": self._sound_mixes})
        Backend._handle_settings_save_result(
            self, result, failure_message="Mix history could not be saved")
        return True

    @Slot(str, int, result="QVariantList")
    def characterFiles(self, key, count):
        """The files one character selects, newest evidence each call."""
        try:
            return list(self._character_picks(
                str(key), count=max(1, int(count or 25))))
        except PlanningEvidenceUnavailable:
            self.errorOccurred.emit(
                "Ampere could not verify its listening data — nothing was built")
            return []

    # ---- play counting (MPD stickers) ---------------------------------------

    def _sticker_map(self, name, cli=None) -> dict:
        """All stickers of one name as {file: raw string value}. `cli` lets a
        WORKER thread pass its OWN MPD client so a whole-library sticker scan
        (Autoplay refill / smart-mix) never runs on the GUI thread's self._cmd."""
        return self._stickers.values(name, cli)

    def _planning_sticker_map(self, name, cli=None) -> dict:
        """Require a verified source generation for queue-planning inputs."""
        result = self._stickers.values_result(name, cli)
        if not result.available and not result.retained:
            raise PlanningEvidenceUnavailable(
                f"{name} sticker snapshot unavailable")
        return result.values

    def _planning_counts(self, cli=None) -> dict:
        out = {}
        for file, value in self._planning_sticker_map(
                "playCount", cli).items():
            try:
                out[file] = int(value)
            except (TypeError, ValueError):
                pass
        return out

    def _planning_energies(self, cli=None) -> dict:
        out = {}
        for file, value in self._planning_sticker_map(
                "joi_energy", cli).items():
            try:
                out[file] = float(value)
            except (TypeError, ValueError):
                pass
        return out

    def _playcounts(self, cli=None) -> dict:
        """All playCount stickers as {file: count}."""
        return self._stickers.integers("playCount", cli)

    def _cached_listening_evidence(self):
        """Return one worker-verified generation for interactive planners."""
        if not self._library_planning_ready:
            raise PlanningEvidenceUnavailable(
                "listening-planning snapshot unavailable")
        return (self._library_playcounts, self._library_planning_ratings,
                self._library_last_played, self._library_energies,
                self._library_bpms)

    def _enqueue_listening_progress(self, observation):
        self._listening_progress_generation += 1
        update = observation.update
        if not (update.count_previous or update.resume_action
                or observation.resume_lookup_file):
            return
        self._listening_progress_jobs.append({
            "generation": self._listening_progress_generation,
            "current_file": observation.resume_lookup_file,
            "duration": float(observation.update.duration),
            "update": observation.update,
        })
        self._start_next_listening_progress_job()

    def _start_next_listening_progress_job(self):
        if self._listening_progress_busy or not self._listening_progress_jobs:
            return
        job = self._listening_progress_jobs.popleft()
        self._listening_progress_busy = True

        def work():
            payload = dict(job)
            payload.update(play_record=None, history_saved=True,
                           resume_saved=True, resume_available=True,
                           resume_position=None)
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=10,
                        registry=self._workers) as cli:
                    def read(name, *args, default=None, **_kwargs):
                        try:
                            return getattr(cli, name)(*args)
                        except Exception:
                            return default

                    def write(name, *args, **_kwargs):
                        try:
                            getattr(cli, name)(*args)
                            return True
                        except CommandError:
                            # Clearing a sticker that is already absent is the
                            # requested end state, not a persistence failure.
                            return name == "sticker_delete"
                        except Exception:
                            return False

                    def observe(name, *args, default=None,
                                missing_ok=False, **_kwargs):
                        try:
                            return MpdReadResult(
                                True, getattr(cli, name)(*args))
                        except CommandError:
                            return MpdReadResult(bool(missing_ok), default)
                        except (MPDConnectionError, OSError):
                            return MpdReadResult(False, default)

                    stickers = StickerRepository(
                        read=read, write=write, client=cli, observe=observe)
                    update = job["update"]
                    if update.count_previous:
                        record = stickers.record_play(update.resume_file)
                        payload["play_record"] = record
                        if record.recorded:
                            payload["history_saved"] = (
                                self._play_history.append(
                                    update.resume_file,
                                    played_at=record.played_at))
                    if update.resume_action == "set":
                        payload["resume_saved"] = stickers.set(
                            update.resume_file, "resumePos",
                            update.resume_position)
                    elif update.resume_action == "delete":
                        payload["resume_saved"] = stickers.delete(
                            update.resume_file, "resumePos")
                    if job["current_file"]:
                        observed = stickers.raw_observed(
                            job["current_file"], "resumePos", default=None)
                        payload["resume_available"] = observed.available
                        if observed.available:
                            try:
                                position = int(observed.value)
                            except (TypeError, ValueError, OverflowError):
                                position = 0
                            if 60 < position < job["duration"] - 60:
                                payload["resume_position"] = position
            except (MPDConnectionError, OSError):
                payload["resume_available"] = False
                payload["resume_saved"] = not bool(
                    job["update"].resume_action)
                if job["update"].count_previous:
                    played_at = int(time.time())
                    payload["play_record"] = PlayRecordResult(
                        True, played_at, False)
                    payload["history_saved"] = self._play_history.append(
                        job["update"].resume_file, played_at=played_at)
            self._listeningProgressReady.emit(payload)

        if not self._start_worker(
                work, name="ampere-listening-progress", durable=True):
            self._listening_progress_busy = False
            self._report_listening_progress_failure()
            self._start_next_listening_progress_job()

    def _publish_play_record(self, file, result):
        if result is None or not result.recorded:
            return
        if result.play_count is not None:
            counts = dict(self._library_playcounts)
            counts[str(file)] = int(result.play_count)
            self._library_playcounts = counts
            self._search_catalog.replace_playcounts(counts)
            self.requestLibrarySummary()

    def _report_listening_progress_failure(self):
        if not getattr(self, "_play_record_failed", False):
            self.errorOccurred.emit(
                "Listening progress could not be fully saved — Rewind, play "
                "counts, or long-track resume may be incomplete; check "
                "storage and the playback connection")
            self._play_record_failed = True

    def _on_listening_progress_ready(self, payload):
        self._listening_progress_busy = False
        update = payload["update"]
        record = payload.get("play_record")
        self._publish_play_record(update.resume_file, record)
        complete = (payload.get("resume_saved", True)
                    and payload.get("history_saved", True)
                    and (record is None or record.stickers_saved))
        if complete:
            self._play_record_failed = False
        else:
            self._report_listening_progress_failure()

        position = payload.get("resume_position")
        current_file = payload.get("current_file", "")
        if (position is not None and payload.get("resume_available", False)
                and payload.get("generation")
                == self._listening_progress_generation
                and current_file
                and current_file == self._song.get("file", "")
                and self._elapsed < 5
                and self._duration >= RESUME_MIN_SECONDS
                and 60 < position < self._duration - 60):
            if self._seek_current_once(position):
                self._listening_progress.accept_resume(position)
        self._start_next_listening_progress_job()

    # ---- smart shelves + history ---------------------------------------------

    @Property(bool, notify=libraryReadyChanged)
    def libraryReady(self):
        """True once the first successful library index is live."""
        return self._library_ready

    @Property(int, notify=databaseUpdated)
    def libraryTotalSongs(self):
        """Indexed song count (0 until the first index is live)."""
        return len(self._search_index)

    @Slot(result="QVariantMap")
    def librarySummary(self):
        """Return the last worker-verified Library/Discover digest."""
        return {
            "shelves": [dict(row) for row in self._library_summary["shelves"]],
            "artists": [dict(row) for row in self._library_summary["artists"]],
        }

    @Slot()
    def requestLibrarySummary(self):
        """Refresh whole-library presentation evidence away from Qt's thread."""
        return self._enrichment.launch(
            "library-summary", self._library_summary_worker,
            thread_name="ampere-library-summary", coalesce=True,
            on_finished=self._on_library_summary_finished)

    def _library_summary_worker(self):
        result = None
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15, registry=self._workers) as cli:
                last = self._stickers.values_result("lastPlayed", cli)
                counts = self._stickers.values_result("playCount", cli)
                ratings = self._stickers.values_result("rating", cli)
                resumes = self._stickers.values_result("resumePos", cli)
                energies = self._stickers.values_result("joi_energy", cli)
                bpms = self._stickers.values_result("joi_bpm", cli)
                preferences = self._stickers.values_result("joi_pref", cli)
                now = time.time()
                since = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 21 * 86400))
                try:
                    arrivals_raw = cli.search(
                        f"(modified-since '{since}')")
                except Exception:
                    arrivals_raw = None
                try:
                    stats_raw = cli.stats()
                except Exception:
                    stats_raw = None
                arrivals = self._summary_shelves.publish_arrivals(arrivals_raw)
                evidence = (
                    last, counts, ratings, resumes, energies, bpms, preferences)
                if (all(item.available or item.retained for item in evidence)
                        and (arrivals.success or arrivals.retained)):
                    library = self._library.by_file
                    search_index = self._library.search_index
                    disliked = tuple(self._disliked)
                    liked = tuple(self._liked)
                    count_values = {}
                    for file, value in counts.values.items():
                        try:
                            count_values[file] = int(value)
                        except (TypeError, ValueError):
                            pass
                    energy_values = {}
                    for file, value in energies.values.items():
                        try:
                            parsed = float(value)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(parsed) and 0.0 <= parsed <= 1.0:
                            energy_values[str(file)] = parsed
                    bpm_values = {}
                    for file, value in bpms.values.items():
                        try:
                            parsed = float(value)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(parsed) and 0.0 < parsed <= 400.0:
                            bpm_values[str(file)] = parsed
                    maps = {
                        "last": last.values,
                        "counts": count_values,
                        "ratings": ratings.values,
                    }

                    def select(name):
                        return self._summary_shelves.select(
                            name, library=library,
                            search_index=search_index,
                            disliked=disliked, liked=liked,
                            last_raw=maps["last"], counts=maps["counts"],
                            ratings=maps["ratings"], arrivals=arrivals.rows)

                    shelf_rows = {
                        name: select(name) for name in ShelfService.NAMES
                    }
                    shelf_rows["unfinished"] = self._home.unfinished(
                        library=library, resume_positions=resumes.values,
                        last_played=maps["last"])
                    history_snapshot = self._play_history.snapshot()
                    entries = history_snapshot.entries
                    result = {
                        "shelves": self._summary_shelves.summaries(
                            lambda name: shelf_rows[name]),
                        "artists": self._rewind.top_artists(
                            counts=count_values, library=library, limit=10,
                            artist_path=self.artistPath),
                        "tracks": shelf_rows,
                        "homeRecommendations": listening_recommendations(
                            library=library, counts=count_values,
                            last_played=last.values, liked=liked,
                            disliked=disliked, entries=entries,
                            arrivals=arrivals.rows, now=now),
                        "discover": DiscoverProjection().build(
                            shelf_rows, library=library),
                        "playcounts": count_values,
                        "lastPlayed": {
                            str(file): str(value)
                            for file, value in last.values.items()
                        },
                        "planningRatings": {
                            str(file): str(value)
                            for file, value in ratings.values.items()
                        },
                        "energies": energy_values,
                        "bpms": bpm_values,
                        "preferences": {
                            str(file): str(value)
                            for file, value in preferences.values.items()
                        },
                        "libraryStats": stats_raw,
                        "rewind": {
                            "stats": self._rewind.stats(
                                counts=count_values, library=library,
                                entries=entries, artist_path=self.artistPath),
                            "history": self._rewind.history(
                                entries=entries, library=library),
                            "chapters": self._rewind.chapters(
                                entries=entries,
                                first_played=history_snapshot.first_played,
                                library=library),
                        },
                    }
        except Exception:
            result = None
        self._librarySummaryReady.emit(result)

    def _on_library_summary_ready(self, result):
        if not isinstance(result, dict):
            if not self._library_summary_failed:
                self.errorOccurred.emit(
                    "Library highlights could not be refreshed — keeping "
                    "the last verified summary; try again after playback "
                    "reconnects")
                self._library_summary_failed = True
            return
        shelves = result.get("shelves")
        artists = result.get("artists")
        tracks = result.get("tracks")
        discover = result.get("discover")
        rewind = result.get("rewind")
        playcounts = result.get("playcounts")
        last_played = result.get("lastPlayed")
        planning_ratings = result.get("planningRatings")
        energies = result.get("energies")
        bpms = result.get("bpms")
        preferences = result.get("preferences")
        library_stats = result.get("libraryStats")
        if (not isinstance(shelves, list) or not isinstance(artists, list)
                or not isinstance(tracks, dict)
                or not isinstance(discover, dict)
                or not isinstance(discover.get("ready"), bool)
                or not isinstance(discover.get("lanes"), list)
                or not isinstance(playcounts, dict)
                or not isinstance(last_played, dict)
                or not isinstance(planning_ratings, dict)
                or not isinstance(energies, dict)
                or not isinstance(bpms, dict)
                or not isinstance(preferences, dict)
                or not isinstance(rewind, dict)
                or not isinstance(rewind.get("stats"), dict)
                or not isinstance(rewind.get("history"), dict)
                or not isinstance(rewind.get("chapters"), list)
                or any(name not in tracks or not isinstance(tracks[name], list)
                       for name in (*ShelfService.NAMES, "unfinished"))):
            return Backend._on_library_summary_ready(self, None)
        try:
            normalized_playcounts = {
                str(file): int(value) for file, value in playcounts.items()
            }
            normalized_last_played = {
                str(file): str(value)
                for file, value in last_played.items()
            }
            normalized_planning_ratings = {
                str(file): str(value)
                for file, value in planning_ratings.items()
            }
            normalized_energies = {}
            for file, value in energies.items():
                parsed = float(value)
                if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
                    raise ValueError("invalid energy")
                normalized_energies[str(file)] = parsed
            normalized_bpms = {}
            for file, value in bpms.items():
                parsed = float(value)
                if not math.isfinite(parsed) or not 0.0 < parsed <= 400.0:
                    raise ValueError("invalid BPM")
                normalized_bpms[str(file)] = parsed
            normalized_preferences = {
                str(file): str(value)
                for file, value in preferences.items()
            }
        except (TypeError, ValueError, OverflowError):
            return Backend._on_library_summary_ready(self, None)
        discover_lanes = []
        expected_keys = tuple(spec["key"] for spec in DiscoverProjection.LANES)
        if len(discover["lanes"]) != len(expected_keys):
            return Backend._on_library_summary_ready(self, None)
        for expected_key, lane in zip(expected_keys, discover["lanes"]):
            if not isinstance(lane, dict) or lane.get("key") != expected_key:
                return Backend._on_library_summary_ready(self, None)
            entry = lane.get("entry") or {}
            if not isinstance(entry, dict):
                return Backend._on_library_summary_ready(self, None)
            files = entry.get("files", [])
            if not isinstance(files, list):
                return Backend._on_library_summary_ready(self, None)
            copied_entry = dict(entry)
            copied_entry["files"] = [str(file) for file in files if file]
            copied_lane = dict(lane)
            copied_lane["entry"] = copied_entry
            discover_lanes.append(copied_lane)
        self._library_summary = {
            "shelves": [dict(row) for row in shelves],
            "artists": [dict(row) for row in artists],
        }
        self._smart_shelves = {
            name: [dict(row) for row in tracks[name]]
            for name in (*ShelfService.NAMES, "unfinished")
        }
        self._discover_overview = {
            "ready": discover.get("ready") is True,
            "lanes": discover_lanes,
        }
        self._library_playcounts = normalized_playcounts
        self._library_last_played = normalized_last_played
        self._library_planning_ratings = normalized_planning_ratings
        self._library_energies = normalized_energies
        self._library_bpms = normalized_bpms
        self._library_preferences = normalized_preferences
        self._library_planning_ready = True
        stats = self._library.publish_stats(library_stats)
        if stats.success:
            self._library_stats_read_failed = False
            self.libraryStatsChanged.emit()
        elif not getattr(self, "_library_stats_read_failed", False):
            self._library_stats_read_failed = True
            self.errorOccurred.emit(
                "Library totals could not be refreshed — keeping the last "
                "verified counts")
        self._search_catalog.replace_playcounts(normalized_playcounts)
        self._rewind_overview = {
            "ready": True,
            "stats": dict(rewind["stats"]),
            "history": dict(rewind["history"]),
            "chapters": [dict(row) for row in rewind["chapters"]],
        }
        self._home_recommendations = result.get("homeRecommendations", [])
        self._library_summary_failed = False
        self.librarySummaryChanged.emit()

    def _on_library_summary_finished(self):
        if self._enrichment.consume_pending("library-summary"):
            self.requestLibrarySummary()

    @Slot(str, result="QVariantList")
    def cachedSmartShelf(self, name):
        """Return one ordered shelf from the last atomic worker digest."""
        return [dict(row) for row in self._smart_shelves.get(str(name), ())]

    @Slot(result="QVariantMap")
    def cachedRediscovery(self):
        """Return Ampy's stable Deep Cuts + Loved union without MPD I/O."""
        ready = all(name in self._smart_shelves for name in ("deep", "loved"))
        files = []
        seen = set()
        if ready:
            for name in ("deep", "loved"):
                for row in self._smart_shelves[name]:
                    file = str(row.get("file", ""))
                    if file and file not in seen:
                        seen.add(file)
                        files.append(file)
        return {"ready": ready, "files": files}

    @Slot(result="QVariantMap")
    def homeOverview(self):
        """Return Home's small immutable view of verified cached evidence."""
        result = self._home.build(
            smart_shelves=self._smart_shelves,
            rewind=self._rewind_overview)
        result["sections"] = [
            {"title": section["title"],
             "cards": [dict(card) for card in section["cards"]]}
            for section in getattr(self, "_home_recommendations", [])]
        return result

    @Slot(result="QVariantMap")
    def discoverOverview(self):
        """Return Discover's bounded view of verified cached shelf evidence."""
        return {
            "ready": bool(self._discover_overview["ready"]),
            "lanes": [
                {
                    **dict(lane),
                    "entry": {
                        **dict(lane.get("entry") or {}),
                        "files": list(
                            (lane.get("entry") or {}).get("files", ())),
                    },
                }
                for lane in self._discover_overview["lanes"]
            ],
        }

    @Slot(result="QVariantMap")
    def rewindOverview(self):
        """Return the last atomic worker-built Rewind presentation model."""
        return {
            "ready": bool(self._rewind_overview["ready"]),
            "stats": dict(self._rewind_overview["stats"]),
            "history": dict(self._rewind_overview["history"]),
            "chapters": [dict(row) for row in
                         self._rewind_overview["chapters"]],
        }

    # ---- 0.19.0: library intelligence batch ------------------------------

    # -- (4) version groups: radio edits / album cuts of the same song --

    def _version_groups(self):
        """{key: [files]} for songs present in 2+ versions."""
        return VersionPolicy.groups(self._library.songs)

    def _collapse_versions(self, files):
        """Shuffle hygiene: one version of a song per session. The
        joi_pref sticker wins, else his most-played, else first seen."""
        if not self._library_planning_ready:
            raise PlanningEvidenceUnavailable(
                "version-selection snapshot unavailable")
        return VersionPolicy.collapse(
            files, groups=self._version_groups(),
            playcounts=self._library_playcounts,
            preferences=self._library_preferences)

    @Slot(str)
    def preferVersion(self, file):
        """Mark this file as THE version of its song (shuffles play only
        it); clears the mark from its siblings."""
        if self._preferred_version_busy:
            return False
        siblings = VersionPolicy.siblings(file, songs=self._library.songs)
        if not siblings:
            return False
        file = str(file)
        siblings = tuple(str(value) for value in siblings)
        self._preferred_version_busy = True

        def work():
            result = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    def read(command, *args, default=None, **_kwargs):
                        try:
                            return getattr(cli, command)(*args)
                        except Exception:
                            return default

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except CommandError:
                            return command == "sticker_delete"
                        except Exception:
                            return False

                    repository = StickerRepository(
                        read=read, write=write, client=cli)
                    result = repository.set_exclusive(
                        siblings, file, "joi_pref")
            except Exception:
                pass
            self._preferredVersionReady.emit({
                "file": file, "siblings": siblings, "result": result,
            })

        if self._start_worker(
                work, name="ampere-preferred-version", durable=True):
            return True
        self._preferred_version_busy = False
        return False

    def _on_preferred_version_ready(self, payload):
        self._preferred_version_busy = False
        payload = payload if isinstance(payload, dict) else {}
        result = payload.get("result")
        file = str(payload.get("file") or "")
        siblings = tuple(payload.get("siblings") or ())
        if not isinstance(result, ExclusiveStickerResult):
            self.errorOccurred.emit(
                "Preferred version could not be saved — the previous "
                "preference is still active")
            return False
        if result.committed:
            preferences = dict(self._library_preferences)
            for sibling in siblings:
                preferences.pop(str(sibling), None)
            preferences[str(file)] = "1"
            self._library_preferences = preferences
            self.doctorChanged.emit()
            return True
        else:
            detail = ("; previous preferences may need repair in Library Doctor"
                      if not result.rollback_complete else "")
            self.errorOccurred.emit(
                "Preferred version could not be saved" + detail)
            return False

    # -- (6) monthly + yearly chapters from the play log --

    def _playlog_entries(self):
        """[(t, file)] from the repository's coherent cached snapshot."""
        return self._play_history.snapshot().entries

    @Slot(str, result=bool)
    def saveRecap(self, key):
        """Start saving a chapter's top tracks without blocking Qt."""
        entries = self._playlog_entries()
        label, files = self._rewind.recap_files(entries, key)
        if not files:
            return False
        name = f"Rewind — {label}"
        return self._request_generated_playlist_save(
            "recap", name, files, key=key)

    # -- (7) the sound profile: what his listening actually is --

    @Slot(result="QVariantMap")
    def soundProfile(self):
        data = dict(self._sound_profile_snapshot["data"])
        data["ready"] = bool(self._sound_profile_snapshot["ready"])
        return data

    @Slot()
    def requestSoundProfile(self):
        return self._enrichment.launch(
            "sound-profile", self._sound_profile_worker,
            thread_name="ampere-sound-profile", coalesce=True,
            on_finished=self._on_sound_profile_finished)

    def _sound_profile_worker(self):
        result = None
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15, registry=self._workers) as cli:
                families = {
                    name: self._stickers.values_result(name, cli)
                    for name in ("playCount", "joi_energy", "joi_bpm",
                                 "joi_cues")
                }
                if all(item.available or item.retained
                       for item in families.values()):
                    counts = {}
                    for file, value in families["playCount"].values.items():
                        try:
                            counts[file] = int(value)
                        except (TypeError, ValueError):
                            pass
                    energies, bpms = {}, {}
                    for target, name in ((energies, "joi_energy"),
                                         (bpms, "joi_bpm")):
                        for file, value in families[name].values.items():
                            try:
                                target[file] = float(value)
                            except (TypeError, ValueError):
                                pass
                    keys = {}
                    for file, raw in families["joi_cues"].values.items():
                        try:
                            keys[file] = int(json.loads(raw).get("key", -1))
                        except (AttributeError, TypeError, ValueError):
                            pass
                    result = self._rewind.sound_profile(
                        counts=counts, energies=energies, bpms=bpms,
                        keys=keys, entries=self._play_history.snapshot().entries,
                        key_label=self._dj_key_label)
        except Exception:
            result = None
        self._soundProfileReady.emit(result)

    def _on_sound_profile_ready(self, result):
        if not isinstance(result, dict):
            if not self._sound_profile_failed:
                self.errorOccurred.emit(
                    "Sonic DNA could not be refreshed — keeping the last "
                    "verified profile; try again after playback reconnects")
                self._sound_profile_failed = True
            return
        self._sound_profile_snapshot = {"ready": True, "data": dict(result)}
        self._sound_profile_failed = False
        self.soundProfileChanged.emit()

    def _on_sound_profile_finished(self):
        if self._enrichment.consume_pending("sound-profile"):
            self.requestSoundProfile()

    # -- (10) the album ritual --

    @Slot(str, result="QVariantMap")
    @Slot(str, str, result="QVariantMap")
    def albumInfo(self, path, album=""):
        """Everything one selected album shows, from the verified snapshot."""
        files = self._library.files_under(path)
        album = str(album or "").strip()
        if album:
            files = [file for file in files
                     if str(self._library.by_file.get(file, {}).get(
                         "album", "")).strip() == album]
        first = self._library.by_file.get(files[0], {}) if files else {}
        return AlbumPresenter.present(
            path, files=files, library=self._library.by_file,
            year=first.get("year", ""))

    # -- (13) mixtape generator: exact-length, arc-shaped --

    @Property(bool, notify=mixtapeBusyChanged)
    def mixtapeBusy(self):
        return self._mixtape_busy

    @Slot(int, str, result=bool)
    def startMixtape(self, minutes, path):
        """Plan a clock-fitted listening arc away from Qt's GUI thread."""
        return self._start_mixtape_plan(minutes, path, mood="")

    @Slot(int, str, result=bool)
    def startAmpySession(self, minutes, mood):
        """Plan one clock-fitted arc from the selected Mood Radio pool.

        Mood constrains selection and the mixtape planner owns duration fitting
        plus warm-up/peak/landing sequencing. Queue publication remains behind
        the existing generated-playlist commit boundary.
        """
        mood = str(mood or "")
        if mood not in MOODS:
            return False
        return self._start_mixtape_plan(minutes, "", mood=mood)

    def _start_mixtape_plan(self, minutes, path, *, mood):
        if self._mixtape_busy:
            return False
        try:
            minutes = max(1, int(minutes))
        except (TypeError, ValueError):
            return False
        path = str(path or "")
        snapshot = {
            "library": {file: dict(song)
                        for file, song in self._library.by_file.items()},
            "disliked": tuple(self._disliked),
            "liked": tuple(self._liked),
            "queued": tuple(
                song.get("file", "")
                for song in getattr(self, "_queue", ())),
            "version_groups": self._version_groups(),
        }
        self._mixtape_busy = True
        self.mixtapeBusyChanged.emit()
        if not self._start_worker(
                self._mixtape_worker,
                args=(minutes, path, snapshot, mood), name="ampere-mixtape"):
            self._mixtape_busy = False
            self.mixtapeBusyChanged.emit()
            self.errorOccurred.emit(
                "Mixtape could not start while Ampere is closing")
            self.mixtapeFinished.emit("", 0, False)
            return False
        return True

    def _mixtape_worker(self, minutes, path, snapshot, mood=""):
        result = None
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15, registry=self._workers) as cli:
                counts = self._planning_counts(cli)
                energies = self._planning_energies(cli)
                bpms = self._planning_sticker_map("joi_bpm", cli)
                preferences = self._planning_sticker_map("joi_pref", cli)
                library = snapshot["library"]
                if mood:
                    spec = MOODS.get(mood)
                    if not spec:
                        raise ValueError("unknown Ampy mood")
                    exemplars = set()
                    for playlist in spec["playlists"]:
                        playlist_result = PlaylistService.client_files_result(
                            cli, playlist)
                        if not playlist_result.success:
                            raise RuntimeError(
                                "mood exemplar snapshot unavailable")
                        exemplars.update(playlist_result.files)
                    ratings = self._planning_sticker_map("rating", cli)
                    last_played = self._planning_sticker_map(
                        "lastPlayed", cli)
                    candidates = self._sessions.mood_picks(
                        list(library.values()), spec,
                        exemplars=exemplars,
                        queued=snapshot.get("queued", ()), counts=counts,
                        ratings=ratings, last_played=last_played,
                        liked=snapshot["liked"],
                        disliked=snapshot["disliked"], energies=energies,
                        count=240)
                    library = {
                        file: library[file]
                        for file in candidates if file in library
                    }
            plan = self._mixtapes.plan(
                minutes, path, library=library,
                disliked=snapshot["disliked"], liked=snapshot["liked"],
                counts=counts, energies=energies, bpms=bpms,
                version_groups=snapshot["version_groups"],
                preferences=preferences)
            result = {"minutes": minutes, "path": path,
                      "mood": mood,
                      "files": tuple(plan.files) if plan.viable else ()}
        except Exception:
            result = None
        self._mixtapeReady.emit(result)

    def _on_mixtape_ready(self, result):
        self._mixtape_busy = False
        self.mixtapeBusyChanged.emit()
        if not isinstance(result, dict):
            self.errorOccurred.emit(
                "Mixtape could not verify its planning data — no playlist "
                "was saved")
            self.mixtapeFinished.emit("", 0, False)
            return
        files = tuple(str(file) for file in result.get("files", ()) if file)
        if not files:
            self.errorOccurred.emit("Not enough songs there for a mixtape")
            self.mixtapeFinished.emit("", 0, False)
            return
        minutes = int(result.get("minutes", 0))
        path = str(result.get("path", ""))
        mood = str(result.get("mood", ""))
        if mood in MOODS:
            label = str(MOODS[mood]["label"]).title()
            name = f"Ampy · {label} · {int(minutes)}m"
        else:
            room = os.path.basename(path.rstrip("/")) if path else "library"
            name = f"Mixtape · {room} · {int(minutes)}m"
        if not self._request_generated_playlist_save(
                "mixtape", name, files):
            self.mixtapeFinished.emit("", 0, False)
            return False
        return True

    # -- (14) library doctor --

    @Slot()
    def runDoctor(self):
        if self._doctor_busy:
            return
        self._doctor_busy = True
        if "lowBitrate" in self._doctor:
            self._doctor_verified = dict(self._doctor)
        self._doctor = {"scanning": 0,
                        "total": len(self._search_index)}
        self.doctorChanged.emit()
        files = tuple(e["song"]["file"] for e in self._search_index)
        library = {file: dict(song)
                   for file, song in self._library.by_file.items()}
        version_groups = self._version_groups()
        if not self._start_worker(
                self._doctor_worker,
                args=(files, library, version_groups),
                name="ampere-library-doctor"):
            self._finish_doctor_failure("Library scan could not start while Ampere is closing")

    def _doctor_worker(self, files, library, version_groups):
        try:
            with temporary_mpd_client(
                    HOST, PORT, timeout=15, registry=self._workers) as cli:
                counts = self._planning_counts(cli)
                preferences = self._planning_sticker_map("joi_pref", cli)
            groups = VersionPolicy.doctor_groups(
                groups=version_groups, playcounts=counts,
                preferences=preferences)
            from . import doctor

            def progress(done, total):
                self._doctorReady.emit({"scanning": done, "total": total})

            report = doctor.scan(
                MUSIC_ROOT, files, library, progress=progress)
            report["versionGroups"] = groups
            report["ts"] = time.time()
            self._doctorReady.emit(report)
        except Exception:
            self._doctorReady.emit({"error": "scan_failed"})

    def _on_doctor(self, rep):
        if rep.get("error") == "scan_failed":
            self._finish_doctor_failure()
            return
        self._doctor = dict(rep)
        if "lowBitrate" in rep:
            self._doctor_busy = False
            self._doctor_verified = dict(rep)
        self.doctorChanged.emit()

    def _finish_doctor_failure(self, message="Library scan failed; the last verified report was kept"):
        self._doctor_busy = False
        self._doctor = dict(getattr(self, "_doctor_verified", {}))
        self.doctorChanged.emit()
        self.errorOccurred.emit(message)

    @Property("QVariantMap", notify=doctorChanged)
    def doctorReport(self):
        return self._doctor

    # -- (15) chapters for long tracks (from the wave cache) --

    @Slot(str, result="QVariantList")
    def trackChapters(self, file):
        """Section start times (s) for 20+ minute files — valleys in the
        cached RMS envelope. [] until the waveform has been computed."""
        idx = self._library.by_file
        dur = float(idx.get(file, {}).get("duration", 0) or 0)
        if dur < 1200.0 or not file:
            return []
        return ChapterDetector.detect(
            dur, self._media.read_cached_waveform(file))

    # -- (16) the song's personal story --

    @Slot(str, result="QVariantMap")
    def songStory(self, file):
        snapshot = self._play_history.snapshot()
        return self._rewind.song_story(
            file, entries=snapshot.entries,
            first_played=snapshot.first_played,
            play_count=self._library_playcounts.get(str(file), 0))

    # -- (19) per-device volume memory --

    @Slot(str)
    def deviceSwitched(self, sink):
        """Wired from the EQ's default-sink watcher: each output device
        remembers its own volume."""
        if not sink or sink == self._vol_device:
            return
        if self._vol_device:
            self._device_vols[self._vol_device] = self._volume
        self._vol_device = sink
        v = self._device_vols.get(sink)
        if v is not None and v != self._volume:
            self.setVolume(max(0, min(100, int(v))))
        self._save_conf()

    def _last_played_song(self):
        """Most recent song from the verified Library planning generation."""
        if not self._library_planning_ready:
            raise PlanningEvidenceUnavailable(
                "last-played snapshot unavailable")
        best_f, best_t = "", -1
        for f, v in self._library_last_played.items():
            try:
                t = int(v)
            except ValueError:
                continue
            if t > best_t:
                best_f, best_t = f, t
        idx = self._library.by_file
        return idx.get(best_f, {})

    @Slot()
    def startRadio(self):
        """Compatibility entry: enable Autoplay, or seed it from cold."""
        if self._state == "play":
            self.setAutoplayOn(True)
            return
        old_song = self._song
        try:
            try:
                seed = self._song or self._last_played_song()
                self._song = seed
                files = self._radio_picks(
                    count=20, plain=True, cached=True)
            except Exception:
                self.errorOccurred.emit(
                    "Radio could not verify planning data — the queue was "
                    "not changed")
                return
        finally:
            self._song = old_song
        if not files:
            self.errorOccurred.emit(
                "Radio could not find a session from the current library")
            return
        self._play_curated_session(files)

    @Slot(str, str, result=str)
    def artistPath(self, file, artist):
        """The artist's FOLDER in the file's path. Exact name match wins;
        otherwise the SHALLOWEST folder containing the artist name — album
        dirs like "Behemoth - The Satanist" also contain it, and picking the
        deepest match used to hand the artist page a single album."""
        return self._library.artist_path(file, artist)

    # ---- queue surgery

    @Slot(str)
    def playNext(self, file):
        """Insert a track right after the playing song ("+0" = relative pos)."""
        file = str(file or "")
        if not file:
            self.errorOccurred.emit("Nothing to play next")
            return False
        return self._request_queue_intent("insert-next", {
            "file": file,
            "afterCurrent": self._queue_pos >= 0,
            "manualQueueEdit": True,
        }, on_finished=self._queued_notice(1, "Playing next"))

    def _queued_notice(self, count, text=""):
        """Completion callback that confirms a successful queue append."""
        text = text or (
            "Added to queue" if count == 1 else f"Queued {count} tracks")
        return lambda ok: self.notice.emit(text) if ok is True else None

    @Slot(int, int)
    def moveInQueue(self, from_pos, to_pos):
        n = len(self._queue)
        if not 0 <= from_pos < n:
            return
        target = max(0, min(n - 1, int(to_pos)))
        if target == from_pos:
            return
        song_ids = [song.get("id", -1) for song in self._queue]
        if any(song_id < 0 for song_id in song_ids):
            self.errorOccurred.emit(
                "Queue changed before the track could be moved")
            return False
        song_id = song_ids.pop(from_pos)
        song_ids.insert(target, song_id)
        return self._request_queue_intent(
            "reorder", {
                "songIds": tuple(song_ids), "start": 0,
                "manualQueueEdit": True,
            })

    @Slot(int)
    def setCrossfade(self, seconds):
        value = max(0, min(15, int(seconds)))
        desired = self._transition_settings_desired()
        desired["xfade_base"] = value
        delay, crossfade = self._transition_target(**desired)
        return self._request_transition_settings({
            "delay": delay, "crossfade": crossfade,
            "publish": desired,
        })

    # ---- MixRamp (musical auto-mix) -----------------------------------------

    @Slot(float)
    def setMixRampDb(self, db):
        try:
            value = max(-40.0, min(-6.0, float(db)))
        except (TypeError, ValueError):
            return False
        desired = self._transition_settings_desired()
        desired["mixrampdb"] = value
        return self._request_transition_settings(
            {"threshold": value, "publish": desired})

    @Slot(bool)
    def setMixRampOn(self, on):
        # mixrampdelay is the master switch: a number enables MixRamp, "nan"
        # disables it (crossfade fallback). Keep the delay near zero — it's
        # SUBTRACTED from every overlap, and cold-ending tracks often have
        # under a second of overlap total. (Exactly 0 is invisible in MPD's
        # status output, so the toggle couldn't display its own state — 0.1
        # reports properly and trims nothing audible.)
        # MPD's default threshold is 0 dB — a level music never sustains, so
        # nothing would ever overlap; land on a sane -17 the first time.
        # taste-tuned 2026-07-12: 1.5s trim (full overlaps entered too early),
        # -30 first-enable threshold. NOTE ReplayGain shifts the effective
        # level by ~+10 dB on loud masters — -17 became near-full-scale, so
        # songs entered at real volume ("Jail started too loud"). -30 means
        # entries only happen during genuinely quiet material.
        desired = bool(on)
        settings = self._transition_settings_desired()
        settings["automix_on"] = desired
        delay, crossfade = self._transition_target(**settings)
        request = {
            "delay": delay, "crossfade": crossfade,
            "publish": settings, "scan": desired,
        }
        if desired and settings["mixrampdb"] > -5.0:
            request["threshold"] = -30.0
            settings["mixrampdb"] = -30.0
        return self._request_transition_settings(request)

    @Slot(str)
    def setMixStyle(self, style):
        """"blend" = MixRamp full-level overlap; "fade" = the next song fades
        in from silence (tag-timed linear crossfade)."""
        settings = self._transition_settings_desired()
        if style not in ("blend", "fade") or style == settings["mix_style"]:
            return
        base = self._xfade if style == "fade" and self._xfade \
            else settings["xfade_base"]
        settings.update({"mix_style": style, "xfade_base": base})
        delay, crossfade = self._transition_target(
            **settings)
        return self._request_transition_settings({
            "delay": delay, "crossfade": crossfade,
            "publish": settings,
        })

    def _transition_settings_desired(self):
        desired = {
            "automix_on": self._automix_on,
            "mix_style": self._mix_style,
            "xfade_base": self._xfade_base,
            "mixrampdb": self._mixrampdb,
        }
        for request in (self._transition_settings_active,
                        self._transition_settings_pending):
            if isinstance(request, dict):
                desired.update(request.get("publish") or {})
        return desired

    def _transition_target(self, *, automix_on=None, mix_style=None,
                           xfade_base=None, **_ignored):
        automix_on = (self._automix_on if automix_on is None
                      else bool(automix_on))
        mix_style = self._mix_style if mix_style is None else str(mix_style)
        xfade_base = (self._xfade_base if xfade_base is None
                      else int(xfade_base))
        if automix_on and mix_style == "blend":
            return 1.5, xfade_base
        if automix_on and mix_style == "fade":
            if self._dj_active:
                return None, self._xfade
            nxt = ""
            if 0 <= self._queue_pos < len(self._queue) - 1:
                nxt = self._queue[self._queue_pos + 1].get("file", "")
            return None, self._fade_duration(
                self._song.get("file", ""), nxt)
        return None, xfade_base

    def _request_transition_settings(self, request):
        self._transition_settings_generation += 1
        request = dict(request)
        request["generation"] = self._transition_settings_generation
        request["internal"] = False
        if self._transition_settings_busy:
            self._transition_settings_pending = request
            self._transition_internal_pending = None
            return True
        return self._start_transition_settings_request(request)

    def _request_internal_transition(self, *, mixramp_delay, crossfade,
                                     dj_active=None):
        active = self._transition_settings_active
        if self._transition_settings_busy and (
                self._transition_settings_pending is not None
                or not (isinstance(active, dict)
                        and active.get("internal"))):
            return False
        self._transition_settings_generation += 1
        request = {
            "generation": self._transition_settings_generation,
            "internal": True, "delay": mixramp_delay,
            "crossfade": max(0, int(crossfade)),
            "djActive": dj_active,
        }
        if self._transition_settings_busy:
            self._transition_internal_pending = request
            return True
        return self._start_transition_settings_request(request)

    def _start_transition_settings_request(self, request):
        self._transition_settings_busy = True
        self._transition_settings_active = request
        self._transition_settings_pending = None
        self._transition_internal_pending = None
        if not request.get("internal"):
            self._transition_internal_failed = False

        def work():
            threshold_result = None
            options_result = None
            messages = []
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    def connected(silent=True):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            return False

                    controller = AutoMixDaemonController(
                        cli, ensure_connected=connected,
                        mark_disconnected=lambda: None,
                        error=messages.append)
                    threshold = request.get("threshold")
                    if threshold is not None:
                        threshold_result = controller.set_threshold(threshold)
                    if (threshold_result is None
                            or threshold_result.committed):
                        if "crossfade" in request:
                            options_result = controller.configure(
                                mixramp_delay=request.get("delay"),
                                crossfade=request["crossfade"])
            except Exception:
                pass
            payload = dict(request)
            payload.update({
                "thresholdResult": threshold_result,
                "optionsResult": options_result,
                "messages": tuple(messages),
            })
            self._transitionSettingsReady.emit(payload)

        if self._start_worker(
                work, name="ampere-transition-settings", durable=True):
            return True
        self._transition_settings_busy = False
        self._transition_settings_active = None
        self.errorOccurred.emit(
            "Transition setting could not start while Ampere is closing")
        return False

    def _on_transition_settings_ready(self, payload):
        self._transition_settings_busy = False
        self._transition_settings_active = None
        payload = payload if isinstance(payload, dict) else {}
        threshold = payload.get("thresholdResult")
        options = payload.get("optionsResult")
        threshold_ok = (threshold is None or (
            isinstance(threshold, TransitionThresholdResult)
            and threshold.committed))
        options_ok = (options is None or (
            isinstance(options, TransitionOptionsResult)
            and options.committed))
        current = (payload.get("generation")
                   == self._transition_settings_generation)
        if current and threshold_ok and options_ok:
            if payload.get("internal"):
                self._transition_internal_failed = False
                if payload.get("djActive") is not None:
                    self._dj_active = bool(payload["djActive"])
            else:
                published = dict(payload.get("publish") or {})
                if "xfade_base" in published:
                    self._xfade_base = int(published["xfade_base"])
                if "automix_on" in published:
                    self._automix_on = bool(published["automix_on"])
                if "mix_style" in published:
                    self._mix_style = str(published["mix_style"])
                if "mixrampdb" in published:
                    self._mixrampdb = float(published["mixrampdb"])
                self._save_conf()
                self.settingsChanged.emit()
                self.statusChanged.emit()
                if payload.get("scan") and self._automix_on:
                    self._start_mixramp_scan()
            self.requestStatusRefresh()
        elif current:
            messages = tuple(payload.get("messages") or ())
            if payload.get("internal"):
                if payload.get("djActive") is not None:
                    self._dj_plan_key = None
                if not self._transition_internal_failed:
                    self._transition_internal_failed = True
                    self.errorOccurred.emit(
                        str(messages[-1]) if messages else
                        "Playback transition could not be configured")
            else:
                self.errorOccurred.emit(
                    str(messages[-1]) if messages else
                    "Transition setting could not be changed")
        pending = self._transition_settings_pending
        if pending is None:
            pending = self._transition_internal_pending
        if pending is not None:
            self._start_transition_settings_request(pending)
        return bool(current and threshold_ok and options_ok)

    def _fade_active(self):
        return self._automix_on and self._mix_style == "fade"

    def _apply_automix(self, *, dj_active=None):
        if self._automix_on and self._mix_style == "blend":
            delay, crossfade = 1.5, self._xfade_base
        else:
            if self._fade_active():
                if self._dj_active:
                    crossfade = self._xfade
                else:
                    nxt = ""
                    if 0 <= self._queue_pos < len(self._queue) - 1:
                        nxt = self._queue[self._queue_pos + 1].get("file", "")
                    crossfade = self._fade_duration(
                        self._song.get("file", ""), nxt)
            else:
                crossfade = self._xfade_base
            delay = None
        return self._configure_transitions(
            mixramp_delay=delay, crossfade=crossfade,
            dj_active=dj_active)

    def _configure_transitions(self, *, mixramp_delay, crossfade,
                               refresh=True, dj_active=None):
        """Schedule one verified coupled transition state off Qt's thread."""
        return self._request_internal_transition(
            mixramp_delay=mixramp_delay, crossfade=crossfade,
            dj_active=dj_active)

    def _apply_fade_xfade(self, mixramp_end="", replaygain="0 dB"):
        """Fade mode: retune MPD's crossfade for the transition OUT of the
        song that just started, so the fade spans its outro's quiet tail."""
        if not self._fade_active() or self._dj_active:
            return
        nxt = ""
        if 0 <= self._queue_pos < len(self._queue) - 1:
            nxt = self._queue[self._queue_pos + 1].get("file", "")
        dur = self._fade_duration(
            self._song.get("file", ""), nxt,
            mixramp_end=mixramp_end, replaygain=replaygain)
        if dur != self._xfade:
            self._configure_transitions(
                mixramp_delay=None, crossfade=dur)

    def _energy_fade_factor(self, out_file, in_file):
        """Crossfade length scaled by how heavy the hand-off is: calm→calm
        drifts long, heavy→heavy cuts tight (long fades on metal smear the
        attack). Uses joi_energy stickers; unknown pairs stay neutral."""
        vals = []
        for f in (out_file, in_file):
            if not f:
                continue
            value = self._library_energies.get(str(f), float("nan"))
            if math.isfinite(value):
                vals.append(value)
        return energy_fade_factor(vals)

    def _fade_duration(self, file, next_file="", *, mixramp_end="",
                       replaygain="0 dB"):
        """Seconds of linear crossfade for `file`'s outro: its MIXRAMP_END
        tag interpolated at the current threshold (ReplayGain-corrected,
        same as MPD applies it), scaled by the pair's energy. Untagged
        files get the energy-scaled base crossfade."""
        if not file:
            return self._xfade_base
        factor = self._energy_fade_factor(file, next_file)
        bpm = self._library_bpms.get(str(file), 0.0)
        return fade_duration(
            base=self._xfade_base, factor=factor, mixramp_end=mixramp_end,
            mixramp_db=self._mixrampdb, replaygain=replaygain, bpm=bpm)

    def _settings_values(self):
        return {
                "automix_on": self._automix_on,
                "mix_style": self._mix_style,
                "crossfade_base": self._xfade_base,
                "autoplay_on": self._autoplay_on,
                "radio_mood": self._radio_mood,
                "remote_on": self._remote_on,
                "remote_token": self._remote_token,
                "delete_remote_host": self._delete_remote_host,
                "delete_remote_root": self._delete_remote_root,
                "smart_mix_on": self._mix_on,
                "mix_arc": self._mix_arc,
                "trim_silence": self._trim_on,
                # dj_mode is deliberately NOT persisted — it's a live-session
                # flag, not a preference (see __init__). Persisting it leaked
                # DJ transitions into the regular queue after a restart.
                "dj_level": self._dj_level,
                "dj_range": self._dj_range,
                "dj_mix_len": self._dj_mix_len,
                "dj_slam_only": self._dj_slam_only,
                "dj_seed_label": self._dj_seed_label,
                "dj_shape": self._dj_shape,
                "dj_minutes": self._dj_minutes,
                "dj_b2b": self._dj_b2b,
                "dj_sting": self._dj_sting,
                "rg_mode": self._replay_gain,
                "rg_on_mode": self._rg_on_mode,
                "rating_mode": self._rating_mode,
                "context_shuffle_mode": self._context_shuffle_mode,
                "device_volumes": self._device_vols,
                # Saved Sound Profiles were retired in 6157232; the settings
                # key is retained for old configs but nothing writes it now.
                "search_history": list(self._search_history),
                # These use narrow transactional patches while the app runs,
                # but must also survive the complete snapshot written during
                # clean shutdown. Omitting them makes validation substitute
                # empty defaults and silently erase user-owned state.
                "artist_aliases": dict(self._artist_aliases),
                "sound_mixes": list(self._sound_mixes),
                "beacon_sessions": list(self._beacon.sessions) if getattr(self, "_beacon", None) else [],
                "playlist_play_counts": dict(self._playlist_play_counts),
            }

    def _save_conf(self, *, failure_message=None):
        result = self._settings.try_save(self._settings_values())
        return Backend._handle_settings_save_result(
            self, result, failure_message=failure_message)

    def _handle_settings_save_result(self, result, *, failure_message=None):
        """Publish one settings durability outcome on Qt's thread."""
        if result.success:
            self._settings_save_failed = False
            self._settings_save_failure_message = ""
            return True
        message = failure_message or (
            "Settings could not be saved — changes apply only until "
            "Ampere closes")
        if getattr(self, "_settings_save_failure_message", "") != message:
            self.errorOccurred.emit(message)
        self._settings_save_failed = True
        self._settings_save_failure_message = message
        return False

    @Slot(bool)
    def analyzeMixRamp(self, force):
        """Tag every FLAC in the library with MIXRAMP_START/END (background).
        Idempotent — already-tagged files are skipped unless force."""
        self._start_mixramp_scan(force, quiet=False)

    def _start_mixramp_scan(self, force=False, quiet=True):
        """quiet=True is the auto path (the Auto-mix toggle) — it must not
        toast errors the user didn't ask about."""
        if self._enrichment.running("mixramp"):
            if not quiet:
                self.errorOccurred.emit("MixRamp analysis already running")
            return
        files = [e["song"]["file"] for e in self._search_index
                 if e["song"]["file"].lower().endswith(".flac")]
        if not files:
            if not quiet:
                self.errorOccurred.emit("No FLACs in the index yet")
            return
        self._enrichment.launch(
            "mixramp", self._mixramp_worker, args=(files, force),
            thread_name="ampere-mixramp-scan")

    def _mixramp_worker(self, files, force):
        self._mixramp_scanner.scan(
            files, force=force,
            should_stop=self._workers.stop_requested.is_set,
            progress=self.mixrampProgress.emit)

    @Slot("QVariantList", int)
    def playFiles(self, files, start_index):
        """Replace the queue with an explicit taste-filtered track list."""
        return self._play_explicit(files, start_index, keep_disliked=False)

    @Slot(str, "QVariantList", int, result=bool)
    def playPlaylistFiles(self, name, files, start_index):
        """Play one visible playlist projection and count verified success."""
        name = str(name or "").strip()
        if not name:
            return False
        return self._play_explicit(
            files, start_index, keep_disliked=False,
            on_finished=lambda success:
                self._finish_playlist_launch(name, success))

    @Slot("QVariantList", int, result=bool)
    def playAlbum(self, files, start_index):
        """Play an intentionally selected parent album, in full."""
        return self._play_explicit(files, start_index, keep_disliked=True)

    def _play_explicit(
            self, files, start_index, *, keep_disliked, on_finished=None):
        supplied = [str(file) for file in files if file]
        requested_index = min(
            max(0, int(start_index)), max(0, len(supplied) - 1))
        requested_file = supplied[requested_index] if supplied else ""
        files = Backend._drop_unavailable_library_files(self, supplied)
        if supplied and not files:
            self.errorOccurred.emit(
                "Nothing playable here — these tracks are no longer in the library")
            return False
        start_index = files.index(requested_file) \
            if requested_file in files else 0
        request = self._explicit_queue_request(
            files, start_index, keep_disliked=keep_disliked,
            session="manual")
        if request is None:
            self.errorOccurred.emit(
                "Nothing playable here — every track is out of rotation")
            return False

        # The shuffle mode is a standing choice, so a NEW selection inherits
        # it instead of silently reverting to play-in-order (Iann,
        # 2026-08-22). The shuffle publishes through _queue_after_current, a
        # different path, so this cannot re-enter itself.
        return self._request_soft_queue_intent(
            "replace", request,
            on_finished=lambda success:
                self._complete_explicit_play(success, on_finished))

    def _complete_explicit_play(self, success, on_finished=None):
        self._reapply_context_shuffle(success)
        if on_finished is not None:
            return on_finished(success)
        return bool(success)

    def _reapply_context_shuffle(self, success):
        if not success:
            return False
        mode = getattr(self, "_context_shuffle_mode", "off")
        if mode in ("standard", "smart"):
            # The new queue IS the context; a failed plan leaves it in order
            # rather than disturbing what was just asked for.
            self.requestContextShuffle(mode, {"kind": "queue"},
                                       automatic=True)
        return True

    def _play_curated_session(
            self, files, *, mood="", sonic="", on_finished=None):
        """Start a refillable recommendation session after the fade lands.

        ``_soft_move`` is asynchronous while music is playing.  Setting the
        session flag immediately after calling ``playFiles`` races with the
        delayed action: ``_play_files_now`` ends the previous session and used
        to erase the brand-new mood/profile flag.  Commit session state only
        after queue replacement succeeds inside the scheduled action.
        """
        request = self._explicit_queue_request(
            files, 0, keep_disliked=False, session="curated",
            mood=mood, sonic=sonic)
        if request is None:
            if on_finished is not None:
                on_finished(False)
            return False

        return self._request_soft_queue_intent(
            "replace", request, on_finished=on_finished)

    def _explicit_queue_request(
            self, files, start_index, *, keep_disliked=False,
            session="manual", mood="", sonic=""):
        """Capture an immutable, policy-filtered replacement without I/O."""
        files = [str(f) for f in files]
        i = max(0, int(start_index))
        keep = files[i] if i < len(files) else ""
        if not keep_disliked:
            files = self._drop_disliked(files)
        if not files:
            return None
        i = files.index(keep) if keep in files else 0
        request = {
            "files": tuple(files),
            "startIndex": i,
            "session": str(session or "manual"),
            "mood": str(mood or ""),
            "sonic": str(sonic or ""),
            "queueContext": (
                "album" if keep_disliked else
                "defined" if len(files) > 1 else "manual"),
        }
        if keep_disliked:
            request.update({
                "source": "album",
                "allowDisliked": True,
            })
        return request

    # ---- browse / search ---------------------------------------------------

    @Slot(str, result="QVariantList")
    def browse(self, path):
        return [dict(entry) for entry in self._library.browse(path)]

    # ---- Library directory (L.01 Open Shelves read models) -------------------
    # All of these read the verified in-memory directory — no MPD or disk I/O
    # happens on Qt's thread here.  Before the first index generation lands
    # the directory is empty; recomputing it inline used to stall the GUI for
    # the whole library, so cold reads answer [] and the page reloads on
    # ``databaseUpdated`` once ``_index_worker`` has published every model.

    def _directory_rows(self, key):
        rows = self._library_directory.get(key)
        return [dict(row) for row in rows] if rows is not None else []

    # ---- add to a stored playlist ------------------------------------------
    # Iann, 2026-08-22: adding a song to a playlist must be available wherever
    # the track menu is. Appending never rewrites the listener's ordering — the
    # existing membership is read, the new files go on the end, and anything
    # already in the playlist is skipped rather than duplicated.

    playlistAddFinished = Signal(str, int, bool)

    @Slot(str, "QVariantList", result=bool)
    def addToPlaylist(self, name, files):
        playlist = str(name or "").strip()
        wanted = tuple(str(f) for f in (files or []) if f)
        if not playlist or not wanted:
            return False

        def work():
            added, ok = 0, False
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15, registry=self._workers) as cli:
                    def ensure_connected(silent=False):
                        try:
                            cli.ping()
                            return True
                        except Exception:
                            try:
                                cli.connect(HOST, PORT)
                                return True
                            except Exception:
                                return False

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except Exception:
                            return False

                    rows = cli.listplaylists()
                    existing = tuple(
                        str(row.get("playlist") or "") for row in rows
                        if isinstance(row, dict) and row.get("playlist"))
                    current = ()
                    if playlist in set(existing):
                        result = PlaylistService.client_files_result(
                            cli, playlist)
                        if not result.success:
                            raise ValueError("playlist membership unavailable")
                        current = tuple(result.files)
                    have = set(current)
                    fresh = tuple(f for f in wanted if f not in have)
                    added = len(fresh)
                    if not fresh:
                        ok = True
                    else:
                        writer = GeneratedPlaylistWriter(
                            cli, ensure_connected=ensure_connected,
                            list_playlists=cli.listplaylists, write=write,
                            refresh=lambda: None)
                        ok = bool(writer.save(playlist, current + fresh,
                                              existing=existing))
            except Exception:
                ok = False
            self.playlistAddFinished.emit(playlist, added, ok)

        if self._start_worker(work, name="ampere-playlist-add"):
            return True
        return False

    # ---- version comparison ------------------------------------------------
    # A duplicate finding says two recordings share an identity. Deciding
    # whether they are actually the SAME performance needs the facts side by
    # side (Iann, 2026-08-21): container, bitrate, sample rate, bit depth,
    # size and duration, beside the tags. Read on a worker; nothing is written.

    versionDetailsReady = Signal("QVariantMap")

    @Slot("QVariantList", result=bool)
    def requestVersionDetails(self, files):
        wanted = [str(f) for f in (files or []) if f]
        if not wanted:
            return False
        library = {file: dict(song)
                   for file, song in self._library.by_file.items()
                   if file in wanted}
        playcounts = dict(self._library_playcounts)

        def work():
            from mutagen import File as MutagenFile
            rows = []
            for file in wanted:
                song = dict(library.get(file) or {})
                row = {
                    "file": file,
                    "title": str(song.get("title") or ""),
                    "artist": str(song.get("artist") or ""),
                    "albumartist": str(song.get("albumartist") or ""),
                    "album": str(song.get("album") or ""),
                    "genre": str(song.get("genre") or ""),
                    "year": str(song.get("year") or ""),
                    "duration": float(song.get("duration") or 0.0),
                    "plays": int(playcounts.get(file, 0)),
                    "format": os.path.splitext(file)[1].lstrip(".").upper(),
                    "kbps": 0, "sampleRate": 0, "bitDepth": 0, "channels": 0,
                    "bytes": 0, "readable": True,
                }
                try:
                    path = os.path.join(MUSIC_ROOT, file)
                    row["bytes"] = int(os.path.getsize(path))
                    info = getattr(MutagenFile(path), "info", None)
                    if info is not None:
                        row["kbps"] = int(getattr(info, "bitrate", 0) or 0) // 1000
                        row["sampleRate"] = int(getattr(info, "sample_rate", 0) or 0)
                        row["bitDepth"] = int(getattr(info, "bits_per_sample", 0) or 0)
                        row["channels"] = int(getattr(info, "channels", 0) or 0)
                    else:
                        row["readable"] = False
                except Exception:
                    row["readable"] = False
                rows.append(row)
            # Plain list/dict: a tuple nested in the payload does not survive
            # the QML bridge and arrives as an empty array.
            self.versionDetailsReady.emit({"files": list(wanted),
                                           "rows": [dict(row) for row in rows]})

        if self._start_worker(work, name="ampere-version-details"):
            return True
        return False

    # ---- tag repair: complete a field from what the library already holds ---
    # Iann, 2026-08-21: typing "Kan" in ARTIST should reach "Kanye West". The
    # candidates are ONLY names his own library already uses, so completion can
    # never invent a spelling that exists nowhere in his catalog.
    TAG_SUGGESTION_LIMIT = 8

    @Slot(str, str, result="QVariantList")
    def tagSuggestions(self, field, prefix):
        text = str(prefix or "").strip().casefold()
        if len(text) < 1:
            return []
        key = str(field or "").casefold()
        if key in ("artist", "albumartist"):
            names = [row.get("name", "") for row in self._directory_rows("artists")]
        elif key == "album":
            names = [row.get("album", "") or row.get("name", "")
                     for row in self._directory_rows("albums")]
        elif key == "genre":
            names = [row.get("name", "") or row.get("genre", "")
                     for row in self._directory_rows("genres")]
        else:
            return []
        starts, contains, seen = [], [], set()
        for name in names:
            name = str(name or "").strip()
            folded = name.casefold()
            if not name or folded in seen:
                continue
            seen.add(folded)
            if folded.startswith(text):
                starts.append(name)
            elif text in folded:
                contains.append(name)
        starts.sort(key=str.casefold)
        contains.sort(key=str.casefold)
        return (starts + contains)[:self.TAG_SUGGESTION_LIMIT]

    @Slot(result="QVariantList")
    def libraryAlbums(self):
        return self._directory_rows("albums")

    @Slot(result="QVariantList")
    def libraryArtists(self):
        return self._directory_rows("artists")

    # Membership for a WHOLE visible room in one pass (Iann, 2026-08-22).
    #
    # The first version of this let QML loop the visible rows and ask for each
    # one's files, which is O(rows x library): playing the Artists room meant
    # 1,346 requests, each walking 3,929 songs and recomputing every credit —
    # roughly five million credit resolutions on the GUI thread. It froze the
    # application hard enough that it could not be closed (2026-08-22). One
    # pass builds the index; the selection is then a lookup.
    ROOM_FILE_LIMIT = 20000

    @Slot(str, "QVariantList", result="QVariantList")
    def libraryRoomFiles(self, kind, keys):
        kind = str(kind or "")
        wanted = [str(k) for k in (keys or []) if str(k)]
        if not wanted:
            return []
        songs = self._library.songs
        index: dict[str, list[str]] = {}
        if kind == "artists":
            for song in songs:
                file = str(song.get("file") or "")
                if not file:
                    continue
                for name in song_credited_artists(song):
                    index.setdefault(artist_key(name), []).append(file)
            order = [artist_key(name) for name in wanted]
        elif kind == "genres":
            for song in songs:
                file = str(song.get("file") or "")
                if not file:
                    continue
                for genre in (song.get("genres") or ()):
                    index.setdefault(str(genre).casefold(), []).append(file)
            order = [name.casefold() for name in wanted]
        elif kind == "folders":
            order = [path.strip("/") for path in wanted]
            selected = set(order)
            for song in songs:
                file = str(song.get("file") or "")
                if not file:
                    continue
                # Folder tiles represent all descendants, not only tracks
                # immediately beneath the tile. Index only requested ancestors
                # in one library pass, preserving the visible room's order.
                parent = file.rpartition("/")[0]
                while parent:
                    if parent in selected:
                        index.setdefault(parent, []).append(file)
                    parent = parent.rpartition("/")[0]
        else:
            return []
        files: list[str] = []
        seen: set[str] = set()
        for key in order:
            for file in index.get(key, ()):
                if file not in seen:
                    seen.add(file)
                    files.append(file)
                    if len(files) >= self.ROOM_FILE_LIMIT:
                        return files
        return files

    @Slot(str, result="QVariantList")
    def artistFiles(self, name):
        return self._library.artist_files(str(name or ""))

    @Slot(str, result="QVariantList")
    def genreFiles(self, name):
        return self._library.genre_files(name)

    @Slot(str, result="QVariantList")
    def folderFiles(self, path):
        return self._library.files_under(str(path or ""))

    @Slot(result="QVariantList")
    def libraryGenres(self):
        return self._directory_rows("genres")

    @Slot(str, result="QVariantMap")
    def libraryGenreDetail(self, name):
        library = self._library
        by_file = library.by_file
        members = [by_file[file] for file in library.genre_files(name)
                   if file in by_file]
        return LibraryDirectory.genre_detail(
            library.songs, name, credit_keys=library.credit_keys,
            members=members)

    @Slot(str, result="QVariantList")
    def libraryFolders(self, path):
        if not str(path or "").strip("/"):
            return self._directory_rows("folders")
        return self._library.folders(path)

    @Slot(result="QVariantList")
    def librarySongs(self):
        return self._directory_rows("songs")

    @Slot(int)
    def requestLibrarySongs(self, serial=0):
        """Materialize the Songs shelf off Qt's thread.

        Copies the immutable directory snapshot on a worker and answers with
        ``librarySongsReady(serial, rows)``; the page drops any response
        older than its newest request (same idiom as ``requestQuickSearch``).
        """
        rows = self._library_directory.get("songs")
        serial = int(serial)

        def work():
            self.librarySongsReady.emit(
                serial, [dict(row) for row in rows] if rows is not None else [])

        self._start_worker(work, name="ampere-library-songs")

    @Slot(str, int)
    def requestArtistDiscography(self, artist, serial=0):
        """Resolve one artist's discography off Qt's thread.

        Reads the immutable library generation plus a play-count copy taken
        here, then answers ``artistDiscographyReady(artist, serial, rows)``.
        """
        artist = str(artist or "")
        serial = int(serial)
        library = self._library
        playcounts = dict(self._library_playcounts)

        def work():
            self.artistDiscographyReady.emit(
                artist, serial,
                library.artist_discography_for(artist, playcounts))

        self._start_worker(work, name="ampere-artist-discography")

    # ---- artist bio (Wikipedia, cached) -------------------------------------

    @Slot(str)
    def requestArtistBio(self, artist):
        artist = (artist or "").strip()
        if not artist:
            return
        self._artist_profiles.request(artist)

    @Slot("QVariantList")
    def primeArtistPortraits(self, artists):
        """Publish cached portraits in one batch and seed bounded idle fill."""
        self._artist_profiles.prime(artists or ())

    @Slot("QVariantList", "QVariantList")
    def prioritizeArtistPortraits(self, visible, nearby):
        """Promote the viewport and its directional look-ahead."""
        self._artist_profiles.prioritize(visible or (), nearby or ())

    @Slot(bool)
    def setArtistPortraitPrefetchActive(self, active):
        """Allow idle fill only while the Library Artists room is active."""
        self._artist_profiles.set_active(active)

    def _bio_worker(self, artist):
        """Look a biography and portrait up under the CANONICAL identity.

        An alias is not its own artist (SPEC UNDESIGNED #17). Querying the
        alias text was why combining `Tech N9ne Collabos` into `Tech N9ne`
        left the wrong portrait in place: membership resolved through the
        alias table but the provider chain did not. The reply is still emitted
        under the name that was asked for, so a surface keeps matching its own
        request.
        """
        canonical = canonical_artist_name(artist) or artist
        self.artistBioReady.emit(artist, self._biographies.get(canonical))

    @Slot(str, int)
    def requestQuickSearch(self, text, serial=0):
        """Resolve the Search room away from Qt's render/input thread.

        ``serial`` is echoed inside the result so the room can discard any
        response older than its newest request (audit S-08). Failures reach
        the UI through ``quickSearchFailed`` instead of vanishing (S-06).
        Lyric hits ride along once the optional lyric index exists; the
        first query starts that index and reports ``lyricsPending`` (S-19).
        """
        query = (text or "").strip()
        if len(query) < 2:
            return
        lyrics_pending = not self._lyrics_index_ready
        if lyrics_pending and len(query) >= 3:
            self._start_lyrics_index()

        def work():
            searchlib.run_quick_search(
                self._search_catalog, query, serial=int(serial),
                lyrics_pending=lyrics_pending,
                on_ready=self.quickSearchReady.emit,
                on_failed=self.quickSearchFailed.emit)

        self._start_worker(work, name="ampere-quick-search")

    # ---- search history (Iann verdict 2026-08-20 #6) -----------------------

    @Property("QVariantList", notify=searchHistoryChanged)
    def searchHistory(self):
        return list(self._search_history)

    def _publish_search_history(self, values):
        cleaned = clean_search_history(values)
        if cleaned == self._search_history:
            return
        self._search_history = cleaned
        self.searchHistoryChanged.emit()
        result = self._settings.try_patch({"search_history": cleaned})
        Backend._handle_settings_save_result(
            self, result, failure_message="Search history was not saved")

    @Slot(str)
    def rememberSearch(self, text):
        query = (text or "").strip()
        if len(query) < 2:
            return
        self._publish_search_history([query] + list(self._search_history))

    # ---- explicit artist aliases (Library Doctor) -------------------------
    # Nothing here infers an identity. Every entry is a decision Iann made;
    # `aliasSuggestions` only PROPOSES candidates for him to confirm.

    @Property("QVariantMap", notify=artistAliasesChanged)
    def artistAliases(self):
        return dict(self._artist_aliases)

    @Slot(str, result="QVariantList")
    def aliasSuggestions(self, artist):
        """Candidates that may be the same identity as `artist`.

        Already-aliased names are withheld: they are settled, not candidates."""
        known = {name.casefold() for name in self._artist_aliases}
        names = []
        for song in self._library.songs:
            for credit in song_credited_artists(song):
                if credit and credit.casefold() not in known:
                    names.append(credit)
        return suggest_artist_aliases(artist, names)

    @Slot(str, str, result=bool)
    def setArtistAlias(self, alias, canonical):
        """Point `alias` at `canonical`. Reversible; never rewrites a tag."""
        table = dict(self._artist_aliases)
        table[str(alias or "")] = str(canonical or "")
        return self._publish_artist_aliases(table)

    @Slot(str, result=bool)
    def removeArtistAlias(self, alias):
        """Undo one alias. The credit returns to its own identity."""
        key = str(alias or "").strip().casefold()
        return self._publish_artist_aliases(
            {name: target for name, target in self._artist_aliases.items()
             if name.casefold() != key})

    def _publish_artist_aliases(self, values):
        cleaned = clean_artist_aliases(values)
        if cleaned == self._artist_aliases:
            return True
        self._artist_aliases = cleaned
        set_artist_aliases(cleaned)
        self.artistAliasesChanged.emit()
        result = self._settings.try_patch({"artist_aliases": cleaned})
        saved = Backend._handle_settings_save_result(
            self, result, failure_message="Artist aliases were not saved")
        # Artist rows, discography membership and album attribution are all
        # resolved through artist_key at projection time, so the cached
        # directory must be rebuilt before any surface reads it again.
        self._build_search_index()
        return saved is not False

    @Slot(str)
    def forgetSearch(self, text):
        key = (text or "").strip().casefold()
        self._publish_search_history(
            [item for item in self._search_history if item.casefold() != key])

    @Slot()
    def clearSearchHistory(self):
        self._publish_search_history([])

    @Slot(str, result=str)
    def canonicalArtistName(self, artist):
        """Return the single canonical Artist-page destination for a credit."""
        from .artists import primary_artist_credit
        return primary_artist_credit(artist)

    @Slot(str, result="QVariantList")
    def artistDiscography(self, artist):
        """Exact credited catalog for one canonical artist, ordered by plays.

        ARTIST and ALBUMARTIST membership replaces the former folder lookup so
        aliases and joint releases belong to every credited artist.  The
        repository performs no I/O here; this reads one immutable generation.
        """
        return self._library.artist_discography_for(
            artist, self._library_playcounts)

    # ---- playlists -----------------------------------------------------------

    def _report_playlist_read(self, success):
        if success:
            self._playlist_read_failed = False
            return
        if not getattr(self, "_playlist_read_failed", False):
            self._playlist_read_failed = True
            self.errorOccurred.emit(
                "Playlist is unavailable — reconnect and try again")

    # ---- playlist cover mosaics (Sequence Shelves wall) ---------------------
    # Worker-owned: one coalesce-by-name pass reads each playlist's first four
    # entries away from Qt's thread; the wall consumes the retained digest.

    @Slot(result="QVariantMap")
    def playlistCovers(self):
        return {name: list(files)
                for name, files in self._playlist_covers.items()}

    @Slot()
    def requestPlaylistCovers(self):
        names = [str(n) for n in self._playlists]
        self._start_worker(self._playlist_covers_worker, args=(names,),
                           name="ampere-playlist-covers")

    def _playlist_covers_worker(self, names):
        covers = {}
        try:
            with temporary_mpd_client(HOST, PORT, timeout=15,
                                      registry=self._workers) as cli:
                for name in names:
                    try:
                        rows = cli.listplaylist(name)
                    except Exception:
                        continue
                    covers[name] = [str(row) for row in rows[:4]]
        except Exception:
            return
        self._playlistCoversArrived.emit(covers)

    def _on_playlist_covers(self, covers):
        if not isinstance(covers, dict):
            return
        self._playlist_covers = {str(k): [str(f) for f in v]
                                 for k, v in covers.items()}
        self.playlistCoversChanged.emit()

    @Slot(str, result="QVariantList")
    def playlistTracks(self, name):
        """Return cached display rows and refresh them away from Qt's thread."""
        name = str(name or "")
        cached = [dict(track) for track in
                  self._playlist_track_snapshots.get(name, ())]
        if not name:
            return cached
        self._playlist_track_generation += 1
        generation = self._playlist_track_generation
        self._playlist_track_request = (generation, name)

        def work():
            result = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    result = PlaylistService.client_tracks_result(
                        cli, name, _song_map)
            except Exception:
                result = None
            self._playlistTracksReady.emit({
                "generation": generation, "name": name, "result": result,
            })

        if not self._start_worker(
                work, name="ampere-playlist-tracks"):
            self._on_playlist_tracks_ready({
                "generation": generation, "name": name, "result": None,
            })
        return cached

    def _on_playlist_tracks_ready(self, payload):
        if not isinstance(payload, dict):
            return
        generation = payload.get("generation")
        name = str(payload.get("name") or "")
        if (generation, name) != self._playlist_track_request:
            return
        self._playlist_track_request = None
        result = payload.get("result")
        if not isinstance(result, PlaylistReadResult) or not result.success:
            self._report_playlist_read(False)
            cached = [dict(track) for track in
                      self._playlist_track_snapshots.get(name, ())]
            self.playlistTracksReady.emit(name, cached, False)
            return
        rows = [dict(track) for track in result.tracks]
        self._playlist_track_snapshots[name] = rows
        self._report_playlist_read(True)
        self.playlistTracksReady.emit(name, rows, True)

    @Slot(str, bool)
    def loadPlaylist(self, name, replace):
        return self._request_playlist_action(
            "play" if replace else "queue", name)

    @Slot(str, result=bool)
    @Slot(str, int, result=bool)
    def saveQueueAs(self, name, count=0):
        """Save the queue as a playlist; count > 0 keeps only the first
        count tracks (for saving the good part of a mix)."""
        result = plan_queue_save(
            name, self._queue, count,
            existing=self._playlist_repository.snapshot.playlists)
        if not result.ok:
            if result.message:
                self.errorOccurred.emit(result.message)
            return False
        return self._request_generated_playlist_save(
            "queue-save", name, result.files, message=result.message)

    @Slot()
    def updateDatabase(self):
        if self._database_update_busy:
            return False
        self._database_update_busy = True

        def work():
            result = None
            try:
                with temporary_mpd_client(
                        HOST, PORT, timeout=15,
                        registry=self._workers) as cli:
                    def read(command, *args, default=None, **_kwargs):
                        try:
                            return getattr(cli, command)(*args)
                        except Exception:
                            return default

                    def write(command, *args, **_kwargs):
                        try:
                            getattr(cli, command)(*args)
                            return True
                        except Exception:
                            return False

                    result = LibraryUpdateController(
                        read=read, write_once=write).request()
            except Exception:
                result = None
            self._databaseUpdateReady.emit(result)

        if self._start_worker(
                work, name="ampere-database-update", durable=True):
            return True
        self._database_update_busy = False
        return False

    def _on_database_update_ready(self, result):
        self._database_update_busy = False
        if not isinstance(result, LibraryUpdateResult):
            self.errorOccurred.emit(
                "Library update could not be confirmed")
            return False
        if not result.success:
            detail = ("could not be confirmed" if not result.confirmed
                      else "could not start")
            self.errorOccurred.emit(f"Library update {detail}")
        elif result.already_running:
            self.errorOccurred.emit("Library update is already running")
        return result.success
