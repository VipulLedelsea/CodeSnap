"""User settings that outlive a launch, kept in <data folder>/settings.json (see core.paths).

Batch processing sends every model call through the Batch API: half the price, results take longer. It is what CodeSnap.command always
turned on, but an app opened from Finder or the Dock has no such environment, so the setting lives here and is applied to the
environment when the app starts (workers started later inherit it). An environment variable set by hand still wins.
"""
import json
import os

from . import paths

_FILE = "settings.json"


def _path():
    return paths.data_root() / _FILE


def load() -> dict:
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - mirrors dict.get/set naming for a tiny key-value store
    data = load()
    data[key] = value
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(target)


def batch_default() -> bool:
    """On for the bundled app (the way it is meant to be run), off from source unless asked for."""
    return bool(get("batch", paths.frozen()))


def apply_defaults() -> None:
    """Put the saved choices into the environment the rest of the program reads, unless a variable is already set."""
    if "CODESNAP_BATCH" not in os.environ:
        os.environ["CODESNAP_BATCH"] = "1" if batch_default() else "0"
    if "CODESNAP_PIPELINE" not in os.environ and paths.frozen():
        os.environ["CODESNAP_PIPELINE"] = "staged"           # draft review, then the full review and the final report


def set_batch(on: bool) -> None:
    set("batch", bool(on))
    os.environ["CODESNAP_BATCH"] = "1" if on else "0"        # the server's own calls; a running capture worker keeps its start-up value
