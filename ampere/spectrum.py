"""Realtime spectrum bands for the Ampere visualizer.

Taps the ampere_eq filter-chain sink monitor with parec, FFTs the stream,
and folds it into 28 log-spaced bands (40 Hz - 16 kHz) normalized 0..1
with auto-gain and attack/release smoothing.

CLI test: python -m ampere.spectrum  (ascii bars for 5 seconds)
"""

import math
import shutil
import subprocess
import threading
import time

import numpy as np

from .compat import audio_identity

DEVICE = audio_identity()[0] + ".monitor"
RATE = 44100
# The visualizer is decorative, and 15 fps is fluid after the QML canvas
# interpolates its own phase.  The old 30 fps producer combined with the QML
# animation timer to enqueue as many as 54 full-window paints per second on
# the GUI thread.  On a long Now Playing session that could starve input and
# make the application appear frozen.
CHUNK = 2940            # samples per frame  (~15 fps at 44100 Hz)
BANDS = 28
F_LO = 40.0
F_HI = 16000.0
ATTACK = 0.6            # smoothing coefficient when a band rises
RELEASE = 0.15          # smoothing coefficient when a band falls
DB_FLOOR = -65.0        # dB below the ceiling that maps to 0
CEIL_DECAY = 0.9985     # per-frame decay of the auto-gain ceiling (slow)
CEIL_MIN = -50.0        # dBFS floor for the ceiling (silence doesn't animate)
RETRY_S = 3.0           # seconds between capture restarts


def _band_edges():
    """FFT-bin index edges for BANDS log-spaced bands over F_LO..F_HI."""
    freqs = np.fft.rfftfreq(CHUNK, 1.0 / RATE)
    edges_hz = np.geomspace(F_LO, F_HI, BANDS + 1)
    edges = np.searchsorted(freqs, edges_hz)
    # guarantee at least one bin per band (low bands are narrower than a bin)
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1
    return np.clip(edges, 0, len(freqs))


class SpectrumTap:
    """Captures ampere_eq.monitor and streams 28 normalized band values.

    tap = SpectrumTap()
    tap.start(lambda bands: ...)   # bands: list of 28 floats in 0..1,
                                   # called ~30x/s from the capture thread
    tap.stop()
    """

    def __init__(self, device=DEVICE):
        self._device = device
        self._callback = None
        self._thread = None
        self._proc = None
        self._running = threading.Event()
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------

    def start(self, callback):
        """Begin capture; callback(list_of_28_floats) fires per frame."""
        with self._lock:
            if self._running.is_set():
                return
            self._callback = callback
            self._running.set()
            self._thread = threading.Thread(
                target=self._run, name="SpectrumTap", daemon=True)
            self._thread.start()

    def stop(self):
        """Request capture shutdown without ever waiting on the GUI thread.

        SpectrumTap is owned from a Qt slot.  Waiting for parec and then
        joining its reader thread here used to block navigation for up to
        four seconds when the capture process was slow to exit.  Clearing the
        event and terminating the child is sufficient: the daemon reader owns
        final process cleanup and cannot hold application shutdown open.
        """
        with self._lock:
            if not self._running.is_set():
                return
            self._running.clear()
            proc = self._proc
            self._thread = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    # -- internals ----------------------------------------------------------

    def _kill_proc(self):
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            pass

    def _spawn(self):
        cmd = [
            "parec",
            "--device=" + self._device,
            "--format=s16le",
            "--rate=%d" % RATE,
            "--channels=1",
            "--latency-msec=30",
        ]
        if shutil.which("parec") is None:  # fallback, parec is the norm here
            cmd = [
                "pw-record",
                "--target", self._device,
                "--format", "s16",
                "--rate", str(RATE),
                "--channels", "1",
                "-",
            ]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=CHUNK * 2)

    def _run(self):
        window = np.hanning(CHUNK).astype(np.float32)
        # normalize FFT so a full-scale sine ~ 0 dBFS in its band
        fft_scale = 2.0 / np.sum(window)
        edges = _band_edges()
        smoothed = np.zeros(BANDS, dtype=np.float32)
        ceiling = CEIL_MIN  # slow-adapting max band dB (auto-gain)
        nbytes = CHUNK * 2  # s16le mono

        while self._running.is_set():
            try:
                self._proc = self._spawn()
            except Exception:
                self._proc = None
            if self._proc is None or self._proc.stdout is None:
                self._sleep_retry()
                continue
            stdout = self._proc.stdout
            try:
                buf = b""
                while self._running.is_set():
                    data = stdout.read(nbytes - len(buf))
                    if not data:            # parec died / device gone
                        break
                    buf += data
                    if len(buf) < nbytes:
                        continue
                    samples = np.frombuffer(buf, dtype=np.int16)
                    buf = b""

                    x = samples.astype(np.float32) * (1.0 / 32768.0)
                    spec = np.abs(np.fft.rfft(x * window)) * fft_scale
                    power = spec * spec
                    # fold bins into log bands (mean power per band)
                    bands_db = np.empty(BANDS, dtype=np.float32)
                    for i in range(BANDS):
                        seg = power[edges[i]:edges[i + 1]]
                        p = float(seg.mean()) if seg.size else 0.0
                        bands_db[i] = 10.0 * math.log10(p + 1e-12)

                    # auto-gain: ceiling rises instantly, decays slowly
                    peak = float(bands_db.max())
                    ceiling = max(peak, ceiling * CEIL_DECAY +
                                  CEIL_MIN * (1.0 - CEIL_DECAY), CEIL_MIN)
                    norm = np.clip(
                        (bands_db - (ceiling + DB_FLOOR)) / -DB_FLOOR,
                        0.0, 1.0)

                    # per-band attack/release smoothing
                    rising = norm > smoothed
                    coeff = np.where(rising, ATTACK, RELEASE)
                    smoothed += coeff * (norm - smoothed)

                    cb = self._callback
                    if cb is not None:
                        try:
                            cb([float(v) for v in smoothed])
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                self._kill_proc()
                self._proc = None
            if self._running.is_set():
                smoothed[:] = 0.0
                self._sleep_retry()

    def _sleep_retry(self):
        deadline = time.monotonic() + RETRY_S
        while self._running.is_set() and time.monotonic() < deadline:
            time.sleep(0.1)


# -- CLI test mode ------------------------------------------------------------

def _cli():
    blocks = " ▁▂▃▄▅▆▇█"

    def render(bands):
        line = "".join(
            blocks[min(int(v * (len(blocks) - 1) + 0.5), len(blocks) - 1)]
            for v in bands)
        print("|%s|" % line, flush=True)

    tap = SpectrumTap()
    tap.start(render)
    try:
        time.sleep(5.0)
    except KeyboardInterrupt:
        pass
    tap.stop()
    print("stopped.")


if __name__ == "__main__":
    _cli()
