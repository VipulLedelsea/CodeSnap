"""Cross-process limit on how many programs analyse at once.

Capture sessions, background workers and deep reviews are separate processes/threads
that all call the same API. A small pool of lock files (flock) caps how many run at
the same moment so parallel programs don't trip the API rate limit; the rest queue.

CODESNAP_MAX_PARALLEL sets the pool size (default 4, 0 = unlimited). The OS releases
a lock when its process dies, so a crashed worker never holds a slot.
"""

import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no cap
    fcntl = None

DEFAULT_LIMIT = 4


def limit() -> int:
    try:
        return max(0, int(os.environ.get("CODESNAP_MAX_PARALLEL", DEFAULT_LIMIT)))
    except ValueError:
        return DEFAULT_LIMIT


def _try_acquire(n: int):
    for i in range(n):
        try:
            fh = open(Path(tempfile.gettempdir()) / f"ledelsea_slot_{i}.lock", "a+")
        except OSError:
            return None
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            fh.close()
    return None


_held = {}                    # key -> [open lock file, users]; one slot per program however many of its jobs run
_guard = threading.Lock()


def _acquire(key, on_wait, poll):
    n = limit()
    if not n or fcntl is None:
        return
    while True:
        with _guard:
            held = _held.get(key)
            if held:
                held[1] += 1
                return
            fh = _try_acquire(n)
            if fh is not None:
                _held[key] = [fh, 1]
                return
        if on_wait:
            try:
                on_wait()
            except Exception:  # noqa: BLE001
                pass
            on_wait = None
        time.sleep(poll)


def _release(key):
    with _guard:
        held = _held.get(key)
        if not held:
            return
        held[1] -= 1
        if held[1] <= 0:
            del _held[key]
            try:
                fcntl.flock(held[0], fcntl.LOCK_UN)
            finally:
                held[0].close()


@contextmanager
def slot(key="", on_wait=None, poll: float = 2.0):
    """Hold an analysis slot for the block. Jobs with the same key (one program) share a single slot; on_wait()
    fires once if we have to queue behind other programs."""
    _acquire(key, on_wait, poll)
    try:
        yield
    finally:
        _release(key)
