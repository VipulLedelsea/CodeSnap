"""Launch/monitor a capture session as a subprocess (its own process = its own
main thread, safest for the global hotkey listener). Live status flows through
core.status (a shared file the web polls)."""

import subprocess
import sys
import json
import math
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
_UNSET = object()


def capture_settings(region=None, display=None):
    values = None
    if region not in (None, ''):
        values = [float(x) for x in region.split(',')] if isinstance(region, str) else list(region)
        if (len(values) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values)
                or min(values[:2]) < 0 or min(values[2:]) <= 0
                or values[0]+values[2] > 1 or values[1]+values[3] > 1):
            raise ValueError('Pick a valid area inside the selected screen.')
    if display not in (None, '', 'auto'):
        display = int(display)
        if display < 1:
            raise ValueError('Pick a valid screen.')
    else:
        display = None
    return {'region': values, 'display': display}


class SessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._proc = None
        self._pending = None
        self.program = None
        self._mode = (False, False, None)
        self._settings = capture_settings()

    def configure(self, region=None, display=None, spacing=_UNSET):
        settings = capture_settings(region, display)
        same = all(settings[k] == self._settings.get(k) for k in ('region','display'))
        if spacing is _UNSET:
            spacing = self._settings.get('spacing') if same else None
        if spacing is not None:
            if not settings['region']:
                raise ValueError('Select the source-only area before confirming the margin.')
            from core.spacing import validate_profile
            settings['spacing']=validate_profile(spacing)
        self._settings = settings
        if self.running():
            directory = PROJECT / 'captures'
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as file:
                json.dump({'pid': self._proc.pid, **self._settings}, file)
                temporary = Path(file.name)
            temporary.replace(directory / '.capture_settings.json')
        return self._settings

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, single: bool = False, idle_stop=None, region=None, project_mode=False, program=None, capture_kind="code",
              display=None) -> bool:
        with self._lock:   # two near-simultaneous starts must not spawn two capture processes
            return self._start_locked(single, idle_stop, region, project_mode, program, capture_kind, display)

    def _start_locked(self, single, idle_stop, region, project_mode, program, capture_kind, display) -> bool:
        mode = (bool(single), bool(project_mode), idle_stop)
        if self.running() and (self.program != program or self._mode != mode):
            raise RuntimeError("Stop the current capture session before switching programs or capture modes.")
        self.configure(region, display)
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
            argv = [sys.executable, str(PROJECT / "src" / "main.py"), "--capture"]
        if idle_stop is not None:
            argv += ["--idle-stop", str(idle_stop)]   # pause tolerance from the slider (0 = manual)
        if region:
            argv += ["--region", region]              # capture only the picked code rectangle
        if project_mode:
            argv += ["--project-mode"]                # allow back-to-back multi-file capture
        if program:
            argv += ["--program", program]
        if capture_kind and capture_kind != "code":
            argv += ["--capture-kind", capture_kind]
        if display not in (None, "", "auto"):
            argv += ["--display", str(display)]
        if single:
            argv.append("--single")   # backup: single agent instead of the default team
        self._proc = subprocess.Popen(argv, cwd=str(PROJECT))
        self.program, self._mode = program, mode
        self.configure(region, display)
        return True

    def process_pending(self, program: str) -> bool:
        """Analyse a program's saved-but-unanalysed captures in a background worker (no hotkeys, exits when done)."""
        with self._lock:
            return self._process_pending_locked(program)

    def _process_pending_locked(self, program: str) -> bool:
        if self._pending is not None and self._pending.poll() is None:
            return False
        base = [sys.executable, "--capture"] if getattr(sys, "frozen", False) else \
            [sys.executable, str(PROJECT / "src" / "main.py"), "--capture"]
        self._pending = subprocess.Popen(base + ["--program", program, "--process-pending"], cwd=str(PROJECT))
        return True

    def stop(self) -> bool:
        """Terminate the capture session and any background pending-analysis worker."""
        with self._lock:
            stopped = False
            for attr in ("_proc", "_pending"):
                proc = getattr(self, attr)
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()
                        stopped = True
                    except OSError:
                        pass
            return stopped
