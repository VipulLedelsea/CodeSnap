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

    def start(self, single: bool = False) -> bool:
        if self.running():
            return False
        from core import status
        status.clear()
        status.publish("Launching capture session...", "start")
        # no flags -> hotkey app default mode (burst: auto-capture + phash dedup)
        # Frozen (bundled .app): the executable re-invokes itself with --capture.
        # Dev: run the dispatcher via python (main.py --capture).
        if getattr(sys, "frozen", False):
            argv = [sys.executable, "--capture"]
        else:
            argv = [sys.executable, str(PROJECT / "main.py"), "--capture"]
        if single:
            argv.append("--single")   # backup: single agent instead of the default team
        self._proc = subprocess.Popen(argv, cwd=str(PROJECT))
        return True

    def stop(self) -> bool:
        if not self.running():
            return False
        self._proc.terminate()
        return True
