"""Ampere — everything you want to hear.

A local-first music player: MPD engine, PySide6/QML face, per-device
parametric EQ on PipeWire. Ampere is the application and Python package name.
"""

# Pin every BLAS backend to a single thread BEFORE numpy is imported by any
# submodule (energy, spectrum). numpy here ships scipy-openblas built with
# MAX_THREADS=64, and OpenBLAS *busy-waits* its worker pool — so the tiny FFTs
# in the background energy/BPM scan spun up threads that pegged a whole core
# even while the scan slept between files, stuttering the UI. These analyses
# are sub-second single-threaded; the thread pool was pure overhead + spin.
import os as _os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_v, "1")

__version__ = "1.0.1"
