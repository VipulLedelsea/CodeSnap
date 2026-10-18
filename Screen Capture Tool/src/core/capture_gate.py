"""Holds a program's analysis back while that program is being captured, and lets "Stop analysis" cancel it.

Both are per program, so capturing or stopping one program never pauses or cancels another. A process learns its
program from CODESNAP_PROGRAM (set when the web app launches a capture session or worker); a caller can also pass the
program explicitly (the web server does, for the per-program client it analyses with). With no program the shared
flags are used."""
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from core.paths import captures_dir  # noqa: E402

FLAG = captures_dir() / ".capturing"
CANCEL = FLAG.with_name(".cancel_analysis")
STALE = 15.0
_state = {"stop": None, "flag": None}
_guard = threading.Lock()
_ctx = threading.local()


@contextmanager
def bound(program):
    """Make `program` the default for gate calls made on this thread (e.g. inside a batch wait)."""
    before = getattr(_ctx, "program", None)
    _ctx.program = program
    try:
        yield
    finally:
        _ctx.program = before


def _key(program=None):
    if program is None:
        program = getattr(_ctx, "program", None)
    if program is None:
        program = os.environ.get("CODESNAP_PROGRAM", "")
    return re.sub(r"[^A-Za-z0-9._-]", "_", program or "")[:80]


def _path(base: Path, program=None) -> Path:
    key = _key(program)
    return base.with_name(f"{base.name}_{key}") if key else base


def _touch(flag):
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(os.getpid()))
    except OSError:
        pass


def begin(program=None):
    with _guard:
        end_locked()
        flag = _path(FLAG, program)
        stop = threading.Event()
        _state["stop"], _state["flag"] = stop, flag
        _touch(flag)

        def beat():
            while not stop.wait(2.0):
                _touch(flag)

        threading.Thread(target=beat, daemon=True).start()


def end_locked():
    stop, flag = _state["stop"], _state["flag"]
    if stop is not None:
        stop.set()
        _state["stop"] = _state["flag"] = None
    try:
        (flag or FLAG).unlink()
    except OSError:
        pass


def end():
    with _guard:
        end_locked()


def capturing(program=None):
    try:
        return time.time() - _path(FLAG, program).stat().st_mtime < STALE
    except OSError:
        return False


class AnalysisCancelled(RuntimeError):
    pass


def cancel_analysis(seconds=90, program=None):
    path = _path(CANCEL, program)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"until": time.time() + seconds}))
    except OSError:
        pass


def clear_cancel(program=None):
    try:
        _path(CANCEL, program).unlink()
    except OSError:
        pass


def cancelled(program=None):
    try:
        return json.loads(_path(CANCEL, program).read_text())["until"] > time.time()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def check(program=None):
    if cancelled(program):
        raise AnalysisCancelled("Analysis was stopped.")


def wait(poll=0.5, program=None):
    check(program)
    if not capturing(program):
        return False
    while capturing(program):
        time.sleep(poll)
        check(program)
    return True
