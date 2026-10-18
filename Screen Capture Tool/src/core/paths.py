"""Where CodeSnap keeps what it writes (capture scratch files, saved reports).

Run from the source tree, that is the project folder, as it always was. Run as the bundled macOS app it must never be the app
itself: the bundle is read-only to a normal install, writing into it breaks its code signature, and an update would replace
the folder and lose the data. The bundled app keeps everything next to the saved programs, in ~/CodeSnap. CODESNAP_HOME
overrides both (tests, a second install)."""
import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def data_root() -> Path:
    override = os.environ.get("CODESNAP_HOME")
    if override:
        return Path(override).expanduser()
    if frozen():
        return Path.home() / "CodeSnap"
    return Path(__file__).resolve().parents[2]


def captures_dir() -> Path:
    return data_root() / "captures"


def reports_dir() -> Path:
    return data_root() / "reports"
