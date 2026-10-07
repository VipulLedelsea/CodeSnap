import json
import os
import threading
import time
from pathlib import Path

FLAG = Path(__file__).resolve().parents[2] / "captures" / ".capturing"
CANCEL = FLAG.with_name(".cancel_analysis")
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


class AnalysisCancelled(RuntimeError):
    pass


def cancel_analysis(seconds=90):
    try:
        CANCEL.parent.mkdir(parents=True, exist_ok=True)
        CANCEL.write_text(json.dumps({"until": time.time() + seconds}))
    except OSError:
        pass


def clear_cancel():
    try:
        CANCEL.unlink()
    except OSError:
        pass


def cancelled():
    try:
        return json.loads(CANCEL.read_text())["until"] > time.time()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def check():
    if cancelled():
        raise AnalysisCancelled("Analysis was stopped.")


def wait(poll=0.5):
    check()
    if not capturing():
        return False
    while capturing():
        time.sleep(poll)
        check()
    return True
