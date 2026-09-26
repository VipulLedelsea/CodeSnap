"""Transient-failure helpers: iCloud / network-drive file locks, busy SQLite, parser guards."""
import errno
import os
import shutil
import sqlite3
import time
from pathlib import Path

TRANSIENT = {errno.EAGAIN, errno.EBUSY, errno.EINTR, getattr(errno, "EDEADLK", 35), 35, errno.ETIMEDOUT}
TRIES = int(os.environ.get("CODESNAP_IO_TRIES", "8"))
DELAY = 0.15


def transient(exc) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        return "locked" in str(exc) or "busy" in str(exc)
    return isinstance(exc, OSError) and exc.errno in TRANSIENT


def retry(fn, *args, tries=None, delay=DELAY, **kw):
    tries = tries or TRIES
    for attempt in range(tries):
        try:
            return fn(*args, **kw)
        except Exception as exc:
            if not transient(exc) or attempt == tries - 1:
                raise
            time.sleep(delay * (attempt + 1))


def read_bytes(path) -> bytes:
    return retry(Path(path).read_bytes)


def read_text(path, **kw) -> str:
    return retry(Path(path).read_text, **kw)


def write_bytes(path, data) -> None:
    retry(Path(path).write_bytes, data)


def write_text(path, text) -> None:
    retry(Path(path).write_text, text)


def copyfile(src, dest) -> None:
    retry(shutil.copyfile, src, dest)
