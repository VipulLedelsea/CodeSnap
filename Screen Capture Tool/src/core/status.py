"""Cross-process session status stream (a shared JSONL file in the temp dir).

The capture session runs as its own process; the web server reads these events
to show live status. Best-effort — never raises.

Each program has its own stream so several programs can run side by side without
overwriting each other's progress. A worker process learns its program from the
CODESNAP_PROGRAM environment variable (set when the web app launches it);
events with no program go to the shared stream.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path

_DIR = Path(tempfile.gettempdir())
STATUS_FILE = _DIR / "ledelsea_session_status.jsonl"


def status_file(program: str | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", program or "")[:80]
    return _DIR / f"ledelsea_session_status_{slug}.jsonl" if slug else STATUS_FILE


def _program(program):
    return program if program is not None else os.environ.get("CODESNAP_PROGRAM")


def publish(msg: str, kind: str = "info", stage: str = None, program: str = None) -> None:
    rec = {"t": time.time(), "kind": kind, "msg": msg}
    if stage:
        rec["stage"] = stage
    try:
        with open(status_file(_program(program)), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


def recent(limit: int = 60, program: str = None) -> list:
    try:
        lines = status_file(_program(program)).read_text().splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:  # noqa: BLE001
        return []


def clear(program: str = None) -> None:
    try:
        status_file(_program(program)).unlink()
    except Exception:  # noqa: BLE001
        pass
