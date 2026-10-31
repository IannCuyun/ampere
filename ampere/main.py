import fcntl
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from .artprovider import ArtProvider
from .mpdclient import Backend
from .mpdgateway import close_all_mpd_clients
from .mpris import MprisService
from .peq import EqManager
from .shutdown_diagnostics import install as install_shutdown_diagnostics
from .shutdown_diagnostics import snapshot as shutdown_snapshot
from .workers import WorkerShutdownReport

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_QML_DIR = PROJECT_ROOT / "qml"
INSTALL_DATA_DIR = Path(sys.prefix) / "share" / "ampere"
QML_DIR = DEV_QML_DIR if DEV_QML_DIR.is_dir() else INSTALL_DATA_DIR / "qml"
BRANDING_DIR = (PROJECT_ROOT / "branding"
                if (PROJECT_ROOT / "branding").is_dir()
                else INSTALL_DATA_DIR / "branding")

# Held open for the process lifetime so the flock survives; released
# automatically by the kernel when the process exits (even on a crash),
# so there is never a stale lock to clean up.
_instance_lock = None


def _acquire_single_instance():
    """Take an exclusive lock so only one Ampere runs at a time.

    Returns True if we own the instance, False if another is already up.
    """
    global _instance_lock
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    # A private per-user directory prevents another local account from
    # pre-creating or replacing our fallback lock when XDG_RUNTIME_DIR is
    # unavailable (common in minimal/manual sessions).
    lock_dir = runtime / f"ampere-{os.getuid()}"
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        lock_dir.chmod(0o700)
    except OSError:
        return False
    lock_path = lock_dir / "instance.lock"
    _instance_lock = open(lock_path, "w")
    try:
        fcntl.flock(_instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _instance_lock.close()
        _instance_lock = None
        return False
    return True


# Ampere owns the engine's lifetime. MPD is no longer enabled at login: it
# exists only while the player is open, so nothing holds a PipeWire stream —
# or answers media keys — from a window that isn't on screen. mpd.conf keeps
# the queue and elapsed time in a state file and sets restore_paused, so a
# start/stop cycle resumes exactly where the last session left off.
MPD_UNIT = "mpd.service"


def _mpd_ready():
    """True once the daemon is up and talking (not merely spawned)."""
    try:
        with socket.create_connection(("127.0.0.1", 6600), timeout=0.5) as s:
            return s.recv(16).startswith(b"OK MPD")
    except OSError:
        return False


def _engine_up():
    """Start MPD and wait for it, before the Backend's first connect."""
    if _mpd_ready():
        return
    try:
        started = subprocess.run(["systemctl", "--user", "start", MPD_UNIT],
                                 check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Ampere: unable to start MPD: {exc}. Run ampere-setup --doctor.",
              file=sys.stderr)
        return
    if started.returncode != 0:
        print("Ampere: MPD service could not start. Run ampere-setup --doctor.",
              file=sys.stderr)
        return
    for _ in range(100):          # up to 10s — a cold start reads the db file
        if _mpd_ready():
            return
        time.sleep(0.1)
    print("Ampere: MPD did not come up; playback will be unavailable.",
          file=sys.stderr)


def _engine_down(backend=None):
    """Close MPD with the app — the other half of _engine_up.

    Pause first so the output closes on a silent frame: a bare SIGTERM
    mid-waveform clicks. MPD then writes its state file on the way down.
    """
    failures = []
    shutdown_snapshot("before-engine-close")
    if backend is not None:
        try:
            if backend._save_conf() is False:
                failures.append("settings: final save was not durable")
            if backend._state == "play":
                backend._call("pause", 1)
                time.sleep(0.15)
        except Exception as exc:
            failures.append(f"playback preparation: {exc}")
        # python-mpd2 owns socket-backed TextIO wrappers. Close them while MPD
        # is still alive; stopping the daemon first leaves their final flush to
        # hit a dead peer during interpreter teardown (sporadic BrokenPipe).
        gateway = getattr(backend, "_gateway", None)
        if gateway is not None:
            try:
                gateway.close()
            except Exception as exc:
                failures.append(f"MPD gateway close: {exc}")
    try:
        close_all_mpd_clients()
    except Exception as exc:
        failures.append(f"MPD client close: {exc}")
    shutdown_snapshot("after-engine-close")
    try:
        stopped = subprocess.run(
            ["systemctl", "--user", "stop", MPD_UNIT],
            check=False, timeout=30)
        if getattr(stopped, "returncode", 0) != 0:
            failures.append(
                f"MPD service stop: systemctl exited {stopped.returncode}")
    except Exception as exc:
        failures.append(f"MPD service stop: {exc}")
    if failures:
        raise RuntimeError("; ".join(failures))


def _destroy_qml(engine):
    """Destroy QML while its Python context objects are still strongly held.

    Leaving this to interpreter shutdown lets ``backend``/``eq`` disappear in
    arbitrary order. Every binding then reevaluates against null and floods the
    log, hiding genuine runtime warnings.
    """
    for root in engine.rootObjects():
        if hasattr(root, "setVisible"):
            root.setVisible(False)
        root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class ApplicationLifecycle:
    """One idempotent owner for every process-scoped Ampere service.

    ``aboutToQuit`` does not fire when QML fails before ``app.exec()``. The
    same explicit boundary therefore serves normal exits, early startup
    failures, and exception recovery without relying on QObject finalizers.
    """

    def __init__(self, backend, *, engine_down=_engine_down):
        self.backend = backend
        self.eq = None
        self.mpris = None
        self._engine_down = engine_down
        self._stopped = False
        self.failures = ()

    def attach_eq(self, eq):
        self.eq = eq

    def attach_mpris(self, mpris):
        self.mpris = mpris

    def shutdown(self):
        if self._stopped:
            return self.failures
        self._stopped = True
        failures = []

        def cleanup(stage, operation):
            try:
                outcome = operation()
                if (isinstance(outcome, WorkerShutdownReport)
                        and not outcome.clean):
                    failures.append((stage, outcome.failure_message))
            except Exception as exc:
                failures.append((stage, str(exc)))

        if self.mpris is not None:
            cleanup("MPRIS", self.mpris.shutdown)
        if self.eq is not None:
            cleanup("EQ", self.eq.stop)
        cleanup("Backend services", self.backend.shutdownServices)
        cleanup("MPD engine", lambda: self._engine_down(self.backend))
        self.failures = tuple(failures)
        for stage, detail in self.failures:
            print(f"Ampere shutdown warning [{stage}]: {detail}",
                  file=sys.stderr)
        return self.failures


def _configure_quick_runtime():
    """Choose the responsive Qt Quick runtime before the first window exists.

    Qt 6 selects its single-threaded ``basic`` scene-graph loop by default on
    this Wayland session.  Ampere's full-window shaders and exhibition-sized
    artwork then render on the GUI thread that must also acknowledge native
    resize configures, making fullscreen transitions take seconds.  The
    threaded loop is supported by the active OpenGL backend and keeps window
    protocol/input work independent from scene rendering.  ``setdefault``
    retains an explicit troubleshooting override from the launch environment.
    """
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    os.environ.setdefault("QSG_RENDER_LOOP", "threaded")


def main():
    install_shutdown_diagnostics()
    if not _acquire_single_instance():
        print("Ampere is already running — refusing to start a second instance.",
              file=sys.stderr)
        sys.exit(0)
    _configure_quick_runtime()
    app = QGuiApplication(sys.argv)
    from .compat import state_directory
    app.setApplicationName("Ampere")
    # Use the existing Qt settings owner without moving a live installation.
    app.setOrganizationName(state_directory("config").name)
    app.setDesktopFileName("ampere")   # Wayland app-id (niri rule matches it)
    app.setWindowIcon(QIcon(str(BRANDING_DIR / "icon-ampere.png")))

    _engine_up()
    try:
        backend = Backend()
    except BaseException:
        try:
            _engine_down()
        except Exception as exc:
            print(f"Ampere shutdown warning [MPD engine]: {exc}",
                  file=sys.stderr)
        raise
    lifecycle = ApplicationLifecycle(backend)
    app.aboutToQuit.connect(lifecycle.shutdown)
    # Closing the window quits Qt and fires aboutToQuit on its own; a signal
    # would otherwise kill the process outright and strand MPD, so route
    # SIGTERM/SIGINT (kill, logout, Ctrl-C) through the same teardown. The
    # timer gives the Python handler a chance to run while Qt owns the loop.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: app.quit())
    _wake = QTimer(app)
    _wake.start(500)
    _wake.timeout.connect(lambda: None)
    engine = None
    try:
        backend.start()
        eq = EqManager()
        lifecycle.attach_eq(eq)
        eq_healthy = eq.start()
        # genre auto-EQ follows the playing song's library folder
        backend.songChanged.connect(
            lambda: eq.noteGenre(backend._song.get("file", "")))
        # each output device remembers its own volume
        eq.deviceChanged.connect(
            lambda: backend.deviceSwitched(eq._sink))
        backend.deviceSwitched(eq._sink)

        engine = QQmlApplicationEngine()
        engine.addImageProvider("art", ArtProvider())
        engine.rootContext().setContextProperty("backend", backend)
        engine.rootContext().setContextProperty("eq", eq)
        engine.addImportPath(str(QML_DIR))
        engine.load(str(QML_DIR / "Main.qml"))
        if not engine.rootObjects():
            _destroy_qml(engine)
            lifecycle.shutdown()
            return 1
        if not eq_healthy:
            # EqManager starts before QML exists. Publish its retained degraded-
            # mode warning once the toast connection is live; a successful
            # recovery clears the retained message before this callback runs.
            QTimer.singleShot(0, eq.publishRuntimeFailure)

        # The bar widget and the phone talk to the player over MPRIS. Ampere
        # serves that itself — the old mpd-mpris daemon seeked MPD on every
        # position change, which chopped the front off every song (see mpris.py).
        def _raise():
            for win in engine.rootObjects():
                if hasattr(win, "requestActivate"):
                    win.show()
                    win.raise_()
                    win.requestActivate()
                break

        mpris = MprisService(backend, app, window_cb=_raise)
        lifecycle.attach_mpris(mpris)
        result = app.exec()
        _destroy_qml(engine)
        lifecycle.shutdown()  # fallback if a platform exits without aboutToQuit
        return result
    except BaseException:
        if engine is not None:
            _destroy_qml(engine)
        lifecycle.shutdown()
        raise


if __name__ == "__main__":
    sys.exit(main())
