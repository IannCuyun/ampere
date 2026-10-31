"""Small process-memory maintenance hooks for long-lived Ampere workers."""

import ctypes


def release_unused_heap() -> bool:
    """Ask glibc to return completely free arenas to the operating system.

    This is advisory and degrades to a no-op when the process allocator does
    not expose ``malloc_trim``. It never invalidates live Python or Qt data.
    """
    try:
        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        return bool(trim(0))
    except (AttributeError, OSError):
        return False
