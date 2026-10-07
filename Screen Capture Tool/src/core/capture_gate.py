import os
import threading
import time
from pathlib import Path

FLAG = Path(__file__).resolve().parents[2] / "captures" / ".capturing"
STALE = 15.0
_state = {"stop": None}
_guard = threading.Lock()


def _touch():
    try:
        FLAG.parent.mkdir(parents=True, exist_ok=True)
        FLAG.write_text(str(os.getpid()))
    except OSError:
        pass


def begin():
    with _guard:
        end_locked()
        stop = threading.Event()
        _state["stop"] = stop
        _touch()

        def beat():
            while not stop.wait(2.0):
                _touch()

        threading.Thread(target=beat, daemon=True).start()


def end_locked():
    stop = _state["stop"]
    if stop is not None:
        stop.set()
        _state["stop"] = None
    try:
        FLAG.unlink()
    except OSError:
        pass


def end():
    with _guard:
        end_locked()


def capturing():
    try:
        return time.time() - FLAG.stat().st_mtime < STALE
    except OSError:
        return False


def wait(poll=0.5):
    if not capturing():
        return False
    while capturing():
        time.sleep(poll)
    return True
