"""Cross-process session status stream (a shared JSONL file in the temp dir).

The capture session runs as its own process; the web server reads these events
to show live status. Best-effort — never raises.
"""

import json
import tempfile
import time
from pathlib import Path

STATUS_FILE = Path(tempfile.gettempdir()) / "ledelsea_session_status.jsonl"


def publish(msg: str, kind: str = "info") -> None:
    try:
        with open(STATUS_FILE, "a") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, "msg": msg}) + "\n")
    except Exception:  # noqa: BLE001
        pass


def recent(limit: int = 60) -> list:
    try:
        lines = STATUS_FILE.read_text().splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:  # noqa: BLE001
        return []


def clear() -> None:
    try:
        STATUS_FILE.unlink()
    except Exception:  # noqa: BLE001
        pass
