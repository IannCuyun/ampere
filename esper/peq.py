"""Per-device parametric EQ on PipeWire for Ampere.

Topology: ONE always-on filter-chain ("Ampere EQ") exposed as a sink. MPD
plays into it; its output stream follows the default sink, so audioswitch
keeps working untouched. The app watches default-sink changes and pushes
the matching device profile's band parameters into the chain live via
pw-cli — switching devices inherently switches EQ.

Fixed graph (so profiles never need a chain reload):
    preamp (mixer) -> lowshelf -> 8x peaking -> highshelf
Unused bands sit at 0 dB (transparent biquads).
"""

from ampere.compat import config_path
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _log(*args):
    print("[peq]", *args, file=sys.stderr, flush=True)

from PySide6.QtCore import QObject, Signal, Slot, Property, QProcess, QTimer

from .persistence import atomic_write_json, atomic_write_text

from .compat import audio_identity

CHAIN_NAME, CONF_PATH = audio_identity()
LEGACY_PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"
PROFILE_DIR = Path(config_path('eq-profiles'))
# genre auto-EQ toggle is global; the genre→variant assignments live inside
# each device profile (a variant name only means something on its device)
GENRE_CFG = Path(config_path('genre-eq.json'))
SR = 48000.0
FMIN, FMAX = 20.0, 20000.0

# the chain always carries MAX_PK peaking nodes (+ shelves) so profiles can
# grow/shrink bands without a chain reload — unused nodes just sit at 0 dB.
# tls/ths are the TONE shelves (bass/treble knobs), separate from the
# correction bands so a device profile and a quick tone tweak never collide.
MAX_PK = 14
CHAIN_NODES = (
    [("ls", "LS", 80.0)]
    + [(f"p{i}", "PK", 1000.0) for i in range(1, MAX_PK + 1)]
    + [("hs", "HS", 10000.0)]
    + [("tls", "LS", 100.0), ("ths", "HS", 9500.0)]
)
DEFAULT_PK_FREQS = (64, 125, 250, 500, 1000, 2000, 4000, 8000)

# flavor presets — loaded into the editor as a starting point, then tweakable.
# (name, [(type, freq, gain, q), ...]) — first LS and last HS map to the
# shelf nodes, the middle rows are peaking bands.
PRESETS = {
    "Flat": [("LS", 80, 0.0, 0.707), ("HS", 10000, 0.0, 0.707)],
    "Physical Records": [   # vinyl warmth: full lows, relaxed presence, soft top
        ("LS", 120, 2.5, 0.6), ("PK", 60, 1.0, 0.8), ("PK", 320, 1.2, 0.7),
        ("PK", 2800, -1.8, 1.2), ("PK", 5500, -1.0, 1.4), ("HS", 9500, -2.5, 0.7),
    ],
    "Bass Boost": [
        ("LS", 110, 5.0, 0.7), ("PK", 55, 2.0, 0.9), ("PK", 280, -1.2, 1.0),
        ("HS", 10000, 0.0, 0.707),
    ],
    "Sub Rumble": [
        ("LS", 65, 6.5, 0.8), ("PK", 35, 2.0, 1.0), ("PK", 150, -1.0, 1.0),
        ("HS", 10000, 0.0, 0.707),
    ],
    "V-Shape": [
        ("LS", 100, 4.0, 0.7), ("PK", 550, -2.0, 0.9), ("PK", 1200, -2.5, 1.1),
        ("PK", 3200, 1.0, 1.4), ("HS", 8500, 3.5, 0.7),
    ],
    "Vocal Focus": [
        ("LS", 130, -2.5, 0.7), ("PK", 1300, 1.5, 1.2), ("PK", 3000, 3.0, 1.3),
        ("PK", 6500, 1.0, 1.6), ("HS", 11000, 1.0, 0.7),
    ],
    "Warm Tube": [
        ("LS", 160, 2.0, 0.6), ("PK", 320, 1.5, 0.8), ("PK", 3600, -2.0, 1.2),
        ("HS", 8800, -1.5, 0.7),
    ],
    "Night Listening": [    # tame the lows through walls, keep speech clear
        ("LS", 90, -4.5, 0.7), ("PK", 220, -1.5, 0.9), ("PK", 2500, 1.0, 1.2),
        ("HS", 10000, -2.0, 0.7),
    ],
    "Crisp Air": [
        ("LS", 100, -0.5, 0.7), ("PK", 5000, 1.5, 1.4), ("HS", 9000, 3.5, 0.7),
    ],
    "Loudness (low volume)": [  # Fletcher-Munson tilt for quiet sessions
        ("LS", 100, 4.0, 0.7), ("PK", 2200, -1.0, 1.2), ("HS", 9500, 2.5, 0.7),
    ],
}


def default_bands():
    bands = [{"node": "ls", "type": "LS", "freq": 80.0, "q": 0.707, "gain": 0.0}]
    for i, f in enumerate(DEFAULT_PK_FREQS, 1):
        bands.append({"node": f"p{i}", "type": "PK", "freq": float(f), "q": 1.0, "gain": 0.0})
    bands.append({"node": "hs", "type": "HS", "freq": 10000.0, "q": 0.707, "gain": 0.0})
    return bands


def default_profile():
    return {"active": "Default", "variants": {"Default": {"preamp": 0.0, "bands": default_bands()}}}


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _migrate_profiles(source: Path, destination: Path) -> int:
    """Copy legacy checkout-local profiles into writable user state once."""
    destination.mkdir(parents=True, exist_ok=True)
    if not source.is_dir() or source.resolve() == destination.resolve():
        return 0
    moved = 0
    for old in source.glob("*.json"):
        new = destination / old.name
        if new.exists():
            continue
        try:
            # Parse before migration so a corrupt legacy file cannot become
            # the installed app's authoritative profile.
            value = json.loads(old.read_text())
            if not isinstance(value, dict):
                continue
            atomic_write_json(new, value, indent=2)
            moved += 1
        except (OSError, ValueError):
            continue
    return moved


def _validated_profile(value) -> dict:
    """Return a usable profile even when persisted JSON is partially corrupt."""
    if not isinstance(value, dict):
        return default_profile()
    variants = value.get("variants")
    if not isinstance(variants, dict):
        return default_profile()
    clean = {}
    for name, variant in variants.items():
        if (not isinstance(name, str) or not isinstance(variant, dict)
                or not isinstance(variant.get("bands"), list)):
            continue
        try:
            preamp = float(variant.get("preamp", 0.0))
        except (TypeError, ValueError):
            preamp = 0.0
        clean_variant = dict(variant)
        clean_variant.update(preamp=preamp, bands=variant["bands"])
        clean[name] = clean_variant
    if not clean:
        return default_profile()
    active = value.get("active")
    if active not in clean:
        active = next(iter(clean))
    # Preserve fields written by a newer Ampere version or local extensions.
    profile = dict(value)
    profile.update(active=active, variants=clean)
    if isinstance(value.get("tone"), dict):
        tone = {}
        for key in ("bass", "treble", "balance"):
            try:
                tone[key] = float(value["tone"].get(key, 0.0))
            except (TypeError, ValueError):
                tone[key] = 0.0
        profile["tone"] = tone
    if isinstance(value.get("genres"), dict):
        profile["genres"] = value["genres"]
    return profile


@dataclass(frozen=True)
class ProfileLoad:
    profile: dict
    corrupt_text: str | None = None
    error: str = ""


@dataclass(frozen=True)
class GenreConfigLoad:
    value: dict
    corrupt_text: str | None = None
    error: str = ""


def _read_genre_config(path: Path) -> GenreConfigLoad:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return GenreConfigLoad({})
    except OSError as exc:
        return GenreConfigLoad({}, error=str(exc))
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return GenreConfigLoad({}, corrupt_text=text)
    if not isinstance(value, dict):
        return GenreConfigLoad({}, corrupt_text=text)
    return GenreConfigLoad(value)


def _read_profile(path: Path) -> ProfileLoad:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return ProfileLoad(default_profile())
    except OSError as exc:
        return ProfileLoad(default_profile(), error=str(exc))
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return ProfileLoad(default_profile(), corrupt_text=text)
    profile = _validated_profile(value)
    if not isinstance(value, dict) or (
            profile == default_profile() and value != profile):
        return ProfileLoad(profile, corrupt_text=text)
    return ProfileLoad(profile)


CHAIN_CONF = """# Generated by Ampere — do not edit by hand (regenerated on band-layout changes).
context.modules = [
    { name = libpipewire-module-filter-chain
        args = {
            node.description = "Ampere EQ"
            media.name       = "Ampere EQ"
            filter.graph = {
                nodes = [
%NODES%
                ]
                links = [
%LINKS%
                ]
                inputs  = [ "ls:In" ]
                outputs = [ "ths:Out" ]
            }
            audio.channels = 2
            audio.position = [ FL FR ]
            capture.props = {
                node.name    = "%NAME%"
                media.class  = Audio/Sink
            }
            playback.props = {
                node.name    = "%NAME%_out"
                node.passive = true
            }
        }
    }
]
"""


def _chain_conf_text() -> str:
    label = {"LS": "bq_lowshelf", "PK": "bq_peaking", "HS": "bq_highshelf"}
    nodes, links = [], []
    prev = None
    for name, typ, f in CHAIN_NODES:
        nodes.append(
            f'                    {{ type = builtin label = {label[typ]:12s} name = {name:6s} '
            f'control = {{ Freq = {float(f)} Q = {"0.707" if typ != "PK" else "1.0"} Gain = 0.0 }} }}'
        )
        if prev is not None:
            links.append(f'                    {{ output = "{prev}:Out" input = "{name}:In" }}')
        prev = name
    return (
        CHAIN_CONF.replace("%NODES%", "\n".join(nodes))
        .replace("%LINKS%", "\n".join(links))
        .replace("%NAME%", CHAIN_NAME)
    )


# ---- biquad math (RBJ cookbook) — for the UI's response curve -----------

def _coeffs(typ, freq, q, gain):
    A = 10.0 ** (gain / 40.0)
    w0 = 2.0 * math.pi * min(freq, SR / 2 * 0.999) / SR
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * max(q, 0.05))
    if typ == "PK":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif typ == "LS":
        s = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + s), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - s)]
        a = [(A + 1) + (A - 1) * cw + s, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - s]
    else:  # HS
        s = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + s), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - s)]
        a = [(A + 1) - (A - 1) * cw + s, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - s]
    return b, a


def _mag_db(b, a, f):
    w = 2.0 * math.pi * f / SR
    def h(c):
        re_ = c[0] + c[1] * math.cos(w) + c[2] * math.cos(2 * w)
        im_ = -c[1] * math.sin(w) - c[2] * math.sin(2 * w)
        return re_, im_
    br, bi = h(b)
    ar, ai = h(a)
    num = math.hypot(br, bi)
    den = math.hypot(ar, ai) or 1e-12
    return 20.0 * math.log10(max(num / den, 1e-12))


# ---- AutoEq parametric import --------------------------------------------

_AUTOEQ_FILTER = re.compile(
    r"Filter\s*\d+\s*:\s*ON\s+(PK|LSC?|HSC?)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB(?:\s+Q\s+([\d.]+))?",
    re.IGNORECASE,
)
_AUTOEQ_PREAMP = re.compile(r"Preamp\s*:\s*(-?[\d.]+)\s*dB", re.IGNORECASE)


def parse_autoeq(text: str):
    preamp = 0.0
    m = _AUTOEQ_PREAMP.search(text)
    if m:
        preamp = float(m.group(1))
    found = {"LS": [], "PK": [], "HS": []}
    for typ, fc, gain, q in _AUTOEQ_FILTER.findall(text):
        t = {"PK": "PK", "LS": "LS", "LSC": "LS", "HS": "HS", "HSC": "HS"}[typ.upper()]
        found[t].append({"freq": float(fc), "gain": float(gain), "q": float(q) if q else 0.707})
    ls = found["LS"][0] if found["LS"] else {"freq": 80.0, "gain": 0.0, "q": 0.707}
    hs = found["HS"][0] if found["HS"] else {"freq": 10000.0, "gain": 0.0, "q": 0.707}
    pks = (found["PK"] + found["LS"][1:] + found["HS"][1:])[:MAX_PK]
    if not pks:
        pks = [{"freq": float(f), "gain": 0.0, "q": 1.0} for f in DEFAULT_PK_FREQS]
    bands = [{"node": "ls", "type": "LS", **ls}]
    for i, f in enumerate(pks, 1):
        bands.append({"node": f"p{i}", "type": "PK", **f})
    bands.append({"node": "hs", "type": "HS", **hs})
    return preamp, bands


# ---- the manager ----------------------------------------------------------

class EqManager(QObject):
    changed = Signal()          # bands/preamp/enabled/variant changed
    deviceChanged = Signal()    # default sink changed
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        _migrate_profiles(LEGACY_PROFILE_DIR, PROFILE_DIR)
        self._sink = ""
        self._sink_desc = ""
        self._node_id = None
        self._enabled = True
        self._profile = default_profile()
        self._bands = self._profile["variants"]["Default"]["bands"]
        self._preamp = 0.0
        self._tone = {"bass": 0.0, "treble": 0.0, "balance": 0.0}
        self._dirty = False
        self._persistence_failed = False
        self._profile_source_path = None
        self._profile_corrupt_text = None
        self._profile_read_error = ""
        self._runtime_failed = False
        self._runtime_message = ""
        # genre auto-EQ: _editing = the variant whose bands are loaded (and
        # where SAVE lands); _genre_override = set when the playing genre
        # picked it; _last_genre_key gates re-resolution to genre CHANGES so
        # a manual variant pick sticks for the rest of a same-genre run
        genre_config = _read_genre_config(GENRE_CFG)
        self._genre_config = genre_config.value
        self._genre_config_corrupt_text = genre_config.corrupt_text
        self._genre_config_read_error = genre_config.error
        self._auto_genre = bool(self._genre_config.get("enabled"))
        self._editing = "Default"
        self._genre_override = None
        self._last_file = ""
        self._last_genre_key = None
        self._push_timer = QTimer(self)
        self._push_timer.setSingleShot(True)
        self._push_timer.setInterval(40)
        self._push_timer.timeout.connect(self._push_now)
        # route reassertion is debounced: a device switch fires a burst of
        # sink-input events and one pw-dump after the burst is enough
        self._heal_timer = QTimer(self)
        self._heal_timer.setSingleShot(True)
        self._heal_timer.setInterval(800)
        self._heal_timer.timeout.connect(self._heal_mpd_route)
        self._watcher = None

    # -- lifecycle --

    def start(self):
        healthy = True
        try:
            self.ensure_chain()
        except Exception as exc:
            healthy = False
            self._report_runtime_failure(
                f"EQ setup failed — playback will continue without EQ: {exc}")
        try:
            self._refresh_default_sink(initial=True)
        except Exception as exc:
            healthy = False
            self._report_runtime_failure(
                f"Audio-device discovery failed — playback will continue: {exc}")
        try:
            self._start_watcher()
        except Exception as exc:
            healthy = False
            self._report_runtime_failure(
                f"Audio-device monitoring failed — playback will continue: {exc}")
        return healthy

    def _start_watcher(self):
        self._watcher = QProcess(self)
        self._watcher.setProgram("pactl")
        self._watcher.setArguments(["subscribe"])
        self._watcher.readyReadStandardOutput.connect(self._on_pactl)
        self._watcher.start()

    def _report_runtime_failure(self, message):
        if not getattr(self, "_runtime_failed", False):
            self.errorOccurred.emit(message)
            self._runtime_message = message
        self._runtime_failed = True

    def _mark_runtime_recovered(self):
        self._runtime_failed = False
        self._runtime_message = ""

    @Slot()
    def publishRuntimeFailure(self):
        """Re-emit a startup failure after QML has attached its toast sink."""
        if self._runtime_message:
            self.errorOccurred.emit(self._runtime_message)

    def stop(self):
        """Stop the long-lived pactl subscription before QObject teardown."""
        self._push_timer.stop()
        self._heal_timer.stop()
        watcher, self._watcher = self._watcher, None
        if watcher is None:
            return
        try:
            watcher.readyReadStandardOutput.disconnect(self._on_pactl)
        except (RuntimeError, TypeError):
            pass
        if watcher.state() != QProcess.ProcessState.NotRunning:
            watcher.terminate()
            if not watcher.waitForFinished(500):
                watcher.kill()
                watcher.waitForFinished(500)
        watcher.deleteLater()

    def ensure_chain(self):
        text = _chain_conf_text()
        if not CONF_PATH.exists() or CONF_PATH.read_text() != text:
            atomic_write_text(CONF_PATH, text)
            subprocess.run(["systemctl", "--user", "restart", "filter-chain.service"],
                           check=True, timeout=10)
            _log("chain topology changed -> filter-chain restarted")
        subprocess.run(["systemctl", "--user", "enable", "--now", "filter-chain.service"],
                       check=True, capture_output=True, timeout=10)
        # a chain restart can strand MPD's stream on the raw sink — heal it
        QTimer.singleShot(2500, self._heal_mpd_route)

    def _heal_mpd_route(self):
        """Keep MPD on the EQ chain — and ONLY that.

            MPD stream  ->  ampere_eq (chain sink)  ->  default sink

        The FIRST hop is enforced: a "move all streams" tool would otherwise
        drag MPD straight onto the raw sink and silently bypass the EQ.

        The SECOND hop is deliberately NOT enforced. mpd.conf's own note says
        the chain's output follows the default sink so device switching keeps
        working untouched, and pinning it broke exactly that: `target.object`
        metadata outranks the default, so after a switch the chain stayed
        bolted to the previous device and Ampere "refused" to move to the
        headphones (Iann, 2026-08-22). This now CLEARS any such pin instead of
        writing one, and moves the chain output to whatever the current
        default is — read fresh here, never from a cached value that a
        concurrent switch may not have updated yet.
        """
        try:
            dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                             text=True, timeout=5).stdout)
        except Exception:
            return
        try:
            default_name = subprocess.run(
                ["pactl", "get-default-sink"], capture_output=True,
                text=True, timeout=5).stdout.strip()
        except Exception:
            default_name = ""
        if default_name == CHAIN_NAME:
            # The chain itself is the default; it must not feed itself.
            return

        nodes, mpd_id, chain_id, chain_out_id = {}, None, None, None
        for o in dump:
            if not o.get("type", "").endswith("Node"):
                continue
            props = ((o.get("info") or {}).get("props") or {})
            name = props.get("node.name", "")
            nodes[o["id"]] = name
            if name.startswith("mpd") and props.get("media.class") == "Stream/Output/Audio":
                mpd_id = o["id"]
            elif name == CHAIN_NAME and props.get("media.class") == "Audio/Sink":
                chain_id = o["id"]
            elif name == CHAIN_NAME + "_out":
                chain_out_id = o["id"]
        linked = {}
        for o in dump:
            if o.get("type", "").endswith("Link"):
                i = o["info"]
                linked.setdefault(i.get("output-node-id"), set()).add(
                    nodes.get(i.get("input-node-id"), ""))

        fixed = []
        # The chain output follows the default. Release any pin first, then
        # move it with the ordinary stream mechanism if it lagged behind.
        if chain_out_id is not None:
            self._release_target(chain_out_id)
            if default_name and linked.get(chain_out_id, set()) not in (
                    set(), {default_name}):
                if self._move_stream(CHAIN_NAME + "_out", default_name):
                    fixed.append(
                        f"{CHAIN_NAME}_out -> {default_name.split('.')[-1]}")

        if mpd_id is not None and chain_id is not None \
                and linked.get(mpd_id, set()) != {CHAIN_NAME}:
            if self._set_target(mpd_id, chain_id):
                fixed.append(f"mpd -> {CHAIN_NAME}")
            else:
                _log("MPD stream off the chain -> bouncing MPD output")
                subprocess.run(["mpc", "-q", "disable", "1"], capture_output=True)
                subprocess.run(["mpc", "-q", "enable", "1"], capture_output=True)
        if fixed:
            _log("route healed: " + ", ".join(fixed))

    @staticmethod
    def _release_target(node_id):
        """Drop a target pin so the node follows the default sink again."""
        for key in ("target.object", "target.node"):
            try:
                subprocess.run(["pw-metadata", str(node_id), key, "-1"],
                               capture_output=True, text=True, timeout=5)
            except Exception:
                return False
        return True

    @staticmethod
    def _move_stream(node_name, sink_name):
        """Move one stream with the ordinary mechanism, leaving no pin."""
        try:
            listing = subprocess.run(["pactl", "list", "sink-inputs"],
                                     capture_output=True, text=True, timeout=5)
            index = None
            current = None
            for line in listing.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("Sink Input #"):
                    current = stripped.split("#", 1)[1]
                elif f'node.name = "{node_name}"' in stripped:
                    index = current
                    break
            if index is None:
                return False
            done = subprocess.run(
                ["pactl", "move-sink-input", index, sink_name],
                capture_output=True, text=True, timeout=5)
            return done.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _set_target(node_id, target_id):
        try:
            r = subprocess.run(
                ["pw-metadata", str(node_id), "target.object", str(target_id)],
                capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    # -- default sink watching --

    def _on_pactl(self):
        data = bytes(self._watcher.readAllStandardOutput()).decode(errors="ignore")
        if "on server" in data:
            _log("server event -> rechecking default sink")
            self._refresh_default_sink()
        if "on sink-input" in data or "on server" in data:
            # a stream was created/moved (audioswitch, pavucontrol, MPD
            # restart) — reassert the route once the churn settles
            self._heal_timer.start()

    def _refresh_default_sink(self, initial=False):
        try:
            out = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except Exception:
            return
        if not out or out == CHAIN_NAME:
            return
        if out == self._sink and not initial:
            return
        self._sink = out
        self._sink_desc = self._sink_description(out)
        self._load_profile()
        _log(f"device -> {out} (variant '{self._profile.get('active')}')")
        self.deviceChanged.emit()
        self._schedule_push()
        self._heal_timer.start()

    def _sink_description(self, node_name):
        try:
            dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                             text=True, timeout=5).stdout)
            for o in dump:
                p = (o.get("info") or {}).get("props") or {}
                if p.get("node.name") == node_name:
                    return p.get("node.description", node_name)
        except Exception:
            pass
        return node_name

    # -- profiles --

    def _profile_path(self) -> Path:
        return PROFILE_DIR / (_sanitize(self._sink or "unknown") + ".json")

    def _persist_json(self, path, value) -> bool:
        try:
            path = Path(path)
            source = getattr(self, "_profile_source_path", None)
            is_profile = source is not None and path == Path(source)
            is_genre_config = path == GENRE_CFG
            if is_profile and getattr(self, "_profile_read_error", ""):
                raise OSError(
                    "existing EQ profile could not be read; refusing to overwrite: "
                    + self._profile_read_error)
            if is_genre_config and getattr(self, "_genre_config_read_error", ""):
                raise OSError(
                    "existing Auto Genre settings could not be read; refusing "
                    "to overwrite: " + self._genre_config_read_error)
            corrupt = None
            if is_profile:
                corrupt = getattr(self, "_profile_corrupt_text", None)
            elif is_genre_config:
                corrupt = getattr(self, "_genre_config_corrupt_text", None)
            if corrupt is not None:
                digest = hashlib.sha1(
                    corrupt.encode("utf-8"),
                    usedforsecurity=False).hexdigest()[:12]
                backup = Path(path).with_name(
                    f"{Path(path).name}.corrupt-{digest}.bak")
                if not backup.exists():
                    atomic_write_text(backup, corrupt)
            atomic_write_json(path, value, indent=2)
        except OSError:
            if not getattr(self, "_persistence_failed", False):
                self.errorOccurred.emit(
                    "EQ settings could not be saved — changes apply only "
                    "until Ampere closes; check storage permissions")
            self._persistence_failed = True
            return False
        if is_profile:
            self._profile_corrupt_text = None
            self._profile_read_error = ""
        elif is_genre_config:
            self._genre_config_corrupt_text = None
            self._genre_config_read_error = ""
        self._persistence_failed = False
        return True

    def _load_profile(self):
        path = self._profile_path()
        loaded = _read_profile(path)
        self._profile = loaded.profile
        self._profile_source_path = path
        self._profile_corrupt_text = loaded.corrupt_text
        self._profile_read_error = loaded.error
        variant = self._profile["variants"].get(self._profile.get("active", "Default"))
        if variant is None:
            self._profile["active"] = next(iter(self._profile["variants"]))
            variant = self._profile["variants"][self._profile["active"]]
        self._bands = variant["bands"]
        self._preamp = float(variant.get("preamp", 0.0))
        t = self._profile.get("tone", {})
        self._tone = {"bass": float(t.get("bass", 0.0)),
                      "treble": float(t.get("treble", 0.0)),
                      "balance": float(t.get("balance", 0.0))}
        self._dirty = False
        self._editing = self._profile["active"]
        self._genre_override = None
        self._last_genre_key = None
        self.changed.emit()
        if self._auto_genre and self._last_file:
            self.noteGenre(self._last_file)

    @Slot()
    def saveProfile(self):
        # SAVE lands on the variant being edited — under a genre override
        # that's the override variant, not the base
        self._profile["variants"][self._editing] = {
            "preamp": self._preamp, "bands": self._bands,
        }
        self._profile["tone"] = dict(self._tone)
        if self._persist_json(self._profile_path(), self._profile):
            self._dirty = False
        self.changed.emit()

    def _load_variant(self, name, override=False):
        v = self._profile["variants"].get(name)
        if v is None:
            return
        self._genre_override = name if override else None
        self._editing = name
        self._bands = v["bands"]
        self._preamp = float(v.get("preamp", 0.0))
        self._dirty = False
        self.changed.emit()
        self._schedule_push()

    @Slot(str)
    def selectVariant(self, name):
        if name not in self._profile["variants"]:
            return
        # a manual pick becomes the base and clears any genre override; the
        # override won't reassert until the playing GENRE changes
        self._profile["active"] = name
        self._persist_json(self._profile_path(), self._profile)
        self._load_variant(name)

    @Slot(str)
    def newVariant(self, name):
        name = name.strip()
        if not name or name in self._profile["variants"]:
            return
        self._profile["variants"][name] = {"preamp": 0.0, "bands": default_bands()}
        self.selectVariant(name)

    @Slot(str)
    def deleteVariant(self, name):
        if name not in self._profile["variants"] or len(self._profile["variants"]) == 1:
            return
        del self._profile["variants"][name]
        g = self._profile.get("genres", {})
        for k in [k for k, v in g.items() if v == name]:
            del g[k]
        self.selectVariant(next(iter(self._profile["variants"])))

    @Slot(str)
    def importAutoEq(self, text):
        try:
            preamp, bands = parse_autoeq(text)
        except Exception as e:
            self.errorOccurred.emit(f"AutoEq parse failed: {e}")
            return
        if all(b["gain"] == 0 for b in bands):
            self.errorOccurred.emit("AutoEq import: no filters found in pasted text")
            return
        self._preamp = preamp
        self._bands = bands
        self._dirty = True
        self._enabled = True
        self.changed.emit()
        self._schedule_push()

    # -- live parameter push --

    def _find_node_id(self):
        try:
            dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                             text=True, timeout=5).stdout)
            for o in dump:
                p = (o.get("info") or {}).get("props") or {}
                if p.get("node.name") == CHAIN_NAME and p.get("media.class") == "Audio/Sink":
                    return o.get("id")
        except Exception:
            pass
        return None

    def _schedule_push(self):
        self._push_timer.start()

    def _push_now(self):
        if self._node_id is None:
            self._node_id = self._find_node_id()
            if self._node_id is None:
                self._report_runtime_failure(
                    "EQ chain is unavailable — playback will continue without EQ")
                return
        # preamp + balance ride the chain sink's channelVolumes, written RAW
        # (linear). NEVER via `wpctl set-volume` — wpctl applies the cubic
        # volume law, so 0.5 lands as 0.125 (-18 dB instead of -6 dB).
        preamp_lin = 10.0 ** (self._preamp / 20.0) if self._enabled else 1.0
        bal = max(-1.0, min(1.0, self._tone["balance"])) if self._enabled else 0.0
        vol_l = preamp_lin * (1.0 - max(0.0, bal))
        vol_r = preamp_lin * (1.0 + min(0.0, bal))
        # map profile bands onto chain nodes: shelves fixed, PK bands in order,
        # leftover chain nodes zeroed so removed bands actually go silent
        parts = []

        def emit(node, freq, q, gain):
            parts.append(f'"{node}:Freq" {float(freq):.1f}')
            parts.append(f'"{node}:Q" {float(q):.4f}')
            parts.append(f'"{node}:Gain" {float(gain if self._enabled else 0.0):.2f}')

        ls, hs = self._bands[0], self._bands[-1]
        emit("ls", ls["freq"], ls["q"], ls["gain"])
        emit("hs", hs["freq"], hs["q"], hs["gain"])
        pks = self._bands[1:-1]
        for i in range(1, MAX_PK + 1):
            if i <= len(pks):
                b = pks[i - 1]
                emit(f"p{i}", b["freq"], b["q"], b["gain"])
            else:
                emit(f"p{i}", 1000.0, 1.0, 0.0)
        # tone knobs on their own shelf nodes, layered over the correction
        emit("tls", 100.0, 0.707, self._tone["bass"])
        emit("ths", 9500.0, 0.707, self._tone["treble"])
        spa = ("{ channelVolumes = [ " + f"{vol_l:.6f} {vol_r:.6f}" + " ] "
               "params = [ " + " ".join(parts) + " ] }")
        try:
            r = subprocess.run(
                ["pw-cli", "set-param", str(self._node_id), "Props", spa],
                capture_output=True, text=True, timeout=5)
        except Exception as exc:
            self._node_id = None
            self._report_runtime_failure(
                f"EQ update failed — playback will continue: {exc}")
            return
        _log(f"push -> node {self._node_id} rc={r.returncode} "
             f"(sink={self._sink.split('.')[-1]}, enabled={self._enabled})")
        if r.returncode != 0:
            self._node_id = None  # stale id (service restarted) — retry once next push
            detail = r.stderr.strip()[:120] or f"exit status {r.returncode}"
            self._report_runtime_failure(
                f"EQ update failed — playback will continue: {detail}")
            return
        self._mark_runtime_recovered()

    # -- QML surface --

    @Property(str, notify=deviceChanged)
    def sinkName(self):
        return self._sink

    @Property(str, notify=deviceChanged)
    def sinkLabel(self):
        return self._sink_desc

    @Property(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @Slot(bool)
    def setEnabled(self, on):
        if on != self._enabled:
            self._enabled = on
            self.changed.emit()
            self._schedule_push()

    @Property(bool, notify=changed)
    def dirty(self):
        return self._dirty

    @Property(float, notify=changed)
    def preamp(self):
        return self._preamp

    @Slot(float)
    def setPreamp(self, db):
        self._preamp = max(-24.0, min(12.0, db))
        self._dirty = True
        self._enabled = True
        self.changed.emit()
        self._schedule_push()

    @Property("QVariantList", notify=changed)
    def bands(self):
        return self._bands

    @Property("QVariantList", notify=changed)
    def variants(self):
        return list(self._profile["variants"].keys())

    @Property(str, notify=changed)
    def activeVariant(self):
        return self._profile.get("active", "Default")

    @Slot(int, float, float, float)
    def setBand(self, index, freq, gain, q):
        if not (0 <= index < len(self._bands)):
            return
        b = dict(self._bands[index])
        b["freq"] = max(FMIN, min(FMAX, freq))
        b["gain"] = max(-18.0, min(18.0, gain))
        b["q"] = max(0.1, min(12.0, q))
        self._bands = self._bands[:index] + [b] + self._bands[index + 1:]
        self._dirty = True
        self._enabled = True   # editing while bypassed is never what anyone means
        self.changed.emit()
        self._schedule_push()

    @Slot()
    def addBand(self):
        pks = len(self._bands) - 2
        if pks >= MAX_PK:
            self.errorOccurred.emit(f"Band limit reached ({MAX_PK} peaking bands)")
            return
        new = {"node": f"p{pks + 1}", "type": "PK", "freq": 1000.0, "q": 1.0, "gain": 0.0}
        self._bands = self._bands[:-1] + [new, self._bands[-1]]
        self._dirty = True
        self.changed.emit()
        self._schedule_push()

    @Slot(int)
    def removeBand(self, index):
        # only peaking bands are removable; shelves are structural
        if not (0 < index < len(self._bands) - 1) or len(self._bands) <= 3:
            return
        self._bands = self._bands[:index] + self._bands[index + 1:]
        self._dirty = True
        self.changed.emit()
        self._schedule_push()

    # -- genre auto-EQ --

    @Property(bool, notify=changed)
    def autoGenre(self):
        return self._auto_genre

    @Slot(bool)
    def setAutoGenre(self, on):
        if on == self._auto_genre:
            return
        self._auto_genre = on
        self._genre_config["enabled"] = on
        self._persist_json(GENRE_CFG, self._genre_config)
        if on:
            self._last_genre_key = None
            if self._last_file:
                self.noteGenre(self._last_file)
        elif self._genre_override and not self._dirty:
            self._load_variant(self._profile.get("active", "Default"))
        else:
            self._genre_override = None
        self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def genreAssignments(self):
        return dict(self._profile.get("genres", {}))

    @Property(str, notify=changed)
    def effectiveVariant(self):
        return self._editing

    @Slot(str, str)
    def assignGenre(self, genre, variant):
        if variant not in self._profile["variants"] or not genre:
            return
        self._profile.setdefault("genres", {})[genre] = variant
        self._persist_json(self._profile_path(), self._profile)
        self._last_genre_key = None
        if self._last_file:
            self.noteGenre(self._last_file)
        self.changed.emit()

    @Slot(str)
    def unassignGenre(self, genre):
        if self._profile.get("genres", {}).pop(genre, None) is None:
            return
        self._persist_json(self._profile_path(), self._profile)
        self._last_genre_key = None
        if self._last_file:
            self.noteGenre(self._last_file)
        self.changed.emit()

    @Slot(str)
    def noteGenre(self, file):
        """Song changed — resolve the genre's assigned variant, if any.

        Candidates: the two-level subgenre folder, then the top-level genre
        (library layout is Genre/Subgenre/Artist/track). Only a genre CHANGE
        re-resolves, so a manual variant pick or an unsaved edit survives the
        rest of a same-genre run.
        """
        self._last_file = file or ""
        if not self._auto_genre or not file:
            return
        parts = file.split("/")
        cands = ["/".join(parts[:2]), parts[0]] if len(parts) > 2 else [parts[0]]
        assigns = self._profile.get("genres", {})
        key = parts[0]
        target = None
        for c in cands:
            if assigns.get(c) in self._profile["variants"]:
                key, target = c, assigns[c]
                break
        if key == self._last_genre_key:
            return
        self._last_genre_key = key
        if self._dirty:
            return  # never discard unsaved edits under him
        if target is not None:
            _log(f"genre EQ: {key} -> variant '{target}'")
            self._load_variant(target, override=True)
        elif self._genre_override:
            _log(f"genre EQ: {key} unassigned -> base '{self._profile.get('active')}'")
            self._load_variant(self._profile.get("active", "Default"))

    # -- tone strip (bass/treble shelves + balance) --

    @Property(float, notify=changed)
    def toneBass(self):
        return self._tone["bass"]

    @Property(float, notify=changed)
    def toneTreble(self):
        return self._tone["treble"]

    @Property(float, notify=changed)
    def balance(self):
        return self._tone["balance"]

    def _set_tone(self, key, value, lo, hi):
        self._tone[key] = max(lo, min(hi, float(value)))
        self._enabled = True
        self._profile["tone"] = dict(self._tone)
        self._persist_json(self._profile_path(), self._profile)
        self.changed.emit()
        self._schedule_push()

    @Slot(float)
    def setToneBass(self, db):
        self._set_tone("bass", db, -8.0, 8.0)

    @Slot(float)
    def setToneTreble(self, db):
        self._set_tone("treble", db, -8.0, 8.0)

    @Slot(float)
    def setBalance(self, b):
        self._set_tone("balance", b, -1.0, 1.0)

    # -- flavor presets --

    @Property("QVariantList", constant=True)
    def presetNames(self):
        return list(PRESETS.keys())

    @Slot(str)
    def applyPreset(self, name):
        spec = PRESETS.get(name)
        if not spec:
            return
        ls = next((r for r in spec if r[0] == "LS"), ("LS", 80, 0.0, 0.707))
        hs = next((r for r in reversed(spec) if r[0] == "HS"), ("HS", 10000, 0.0, 0.707))
        pks = [r for r in spec if r[0] == "PK"][:MAX_PK]
        bands = [{"node": "ls", "type": "LS", "freq": float(ls[1]), "gain": float(ls[2]), "q": float(ls[3])}]
        for i, r in enumerate(pks, 1):
            bands.append({"node": f"p{i}", "type": "PK", "freq": float(r[1]), "gain": float(r[2]), "q": float(r[3])})
        bands.append({"node": "hs", "type": "HS", "freq": float(hs[1]), "gain": float(hs[2]), "q": float(hs[3])})
        self._bands = bands
        # auto-preamp: pull the whole curve down by its highest peak so hot
        # masters can't clip through a boost preset
        coeffs = [_coeffs(b["type"], b["freq"], b["q"], b["gain"])
                  for b in bands if abs(b["gain"]) > 0.01]
        peak = 0.0
        for i in range(80):
            f = 10 ** (math.log10(FMIN) + (math.log10(FMAX) - math.log10(FMIN)) * i / 79)
            peak = max(peak, sum(_mag_db(b, a, f) for b, a in coeffs))
        self._preamp = -round(peak, 1)
        self._dirty = True
        self._enabled = True
        self.changed.emit()
        self._schedule_push()

    @Slot(int, result="QVariantList")
    def responseCurve(self, n):
        """n points of composite response, log-spaced FMIN..FMAX, in dB."""
        coeffs = [_coeffs(b["type"], b["freq"], b["q"], b["gain"])
                  for b in self._bands if abs(b["gain"]) > 0.01]
        if abs(self._tone["bass"]) > 0.01:
            coeffs.append(_coeffs("LS", 100.0, 0.707, self._tone["bass"]))
        if abs(self._tone["treble"]) > 0.01:
            coeffs.append(_coeffs("HS", 9500.0, 0.707, self._tone["treble"]))
        lf0, lf1 = math.log10(FMIN), math.log10(FMAX)
        pts = []
        for i in range(max(2, n)):
            f = 10 ** (lf0 + (lf1 - lf0) * i / (n - 1))
            db = self._preamp + sum(_mag_db(b, a, f) for b, a in coeffs)
            pts.append(db)
        return pts
