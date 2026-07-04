"""Launch/monitor a capture session as a subprocess (its own process = its own
main thread, safest for the global hotkey listener). Live status flows through
core.status (a shared file the web polls)."""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


class SessionManager:
    def __init__(self):
        self._proc = None

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        if self.running():
            return False
        from core import status
        status.clear()
        status.publish("Launching capture session...", "start")
        # default hotkey app = owned agent session
        self._proc = subprocess.Popen(
            [sys.executable, str(PROJECT / "hotkey_capture.py")],
            cwd=str(PROJECT),
        )
        return True

    def stop(self) -> bool:
        if not self.running():
            return False
        self._proc.terminate()
        return True
