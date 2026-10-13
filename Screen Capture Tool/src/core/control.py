"""Live control of a running capture session (pause / resume / park), shared between the web server and the
capture worker through one small JSON file next to the session's other scratch files. Best-effort — never raises."""

import json
import os
import tempfile
from pathlib import Path

NAME = ".session_control.json"


def read(directory, pid: int | None = None) -> dict:
    """Current control flags; a file written for another worker's pid is stale and reads as empty."""
    try:
        data = json.loads((Path(directory) / NAME).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or (pid is not None and data.get("pid") != pid):
        return {}
    return data


def write(directory, pid: int, **changes) -> dict:
    data = {**read(directory, pid), **changes, "pid": pid}
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as f:
            json.dump(data, f)
        os.replace(f.name, directory / NAME)
    except OSError:
        pass
    return data


def reset(directory, pid: int) -> None:
    write(directory, pid, paused=False, park=False)
