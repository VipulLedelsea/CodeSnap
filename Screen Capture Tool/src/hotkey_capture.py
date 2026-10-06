"""Milestone 3 + 5 — Hotkey capture with background per-image processing.

Runs in the background. You start a session and snap screenshots with a hotkey.
Each screenshot is read by Claude IN THE BACKGROUND the moment it is saved (a
small worker pool, a few at a time), with the per-image text cached by content
hash. When you stop, the tool just waits for any straggling reads, stitches the
cached text into one document, and makes a single cheap overview call — so stop
is fast even after many captures, and nothing is ever sent in one oversized
request. After analysis you're asked whether to save a Word report.

Hotkeys (global — work in any app):
  Cmd+Shift+1  start / stop session   (toggle: idle <-> running)
  Cmd+Shift+2  capture full screen    (while running; saves a PNG, reads it in bg)
  Cmd+Shift+8  capture a region       (while running; drag-select, Esc cancels)
  Cmd+Shift+9  quit                   (or Ctrl+C in the terminal)

Flow:
  start  -> a fresh folder captures/session_<timestamp>/ is created
  2 / 8  -> saves an ordered PNG (001.png, ...) and kicks off its read in the bg
  stop   -> waits for background reads, stitches text + overview; prints results,
            then asks whether to save reports/report_<timestamp>.docx
  quit   -> analyses a pending session first (no lost work); then deletes this
            run's session folders. Saved reports in reports/ are never touched.

macOS permissions (System Settings -> Privacy & Security), granted to your
terminal app (Terminal / iTerm):
  - Input Monitoring + Accessibility   (for the global hotkey listener)
  - Screen Recording                   (for screen capture)
First run may do nothing until these are granted; restart the terminal after.

Run it:  python hotkey_capture.py
"""

import concurrent.futures
import io
import os
import shutil
import sys
import textwrap
import threading
import time
import tempfile
from pathlib import Path

# Analysis engine: env loading, background per-image extraction + cache, the
# incremental analyser (cache hits + one overview call), and the docx builder.
from core.analysis import load_env, extract_to_cache, analyse_incremental, fix_source, fix_looks_complete
from core.validate import check_source
from core.capture import capture_full_png, capture_region_png, next_png_path
from agent import run_agent, run_session
from team import run_team, run_team_fast
from tools import ToolContext
from core.outputs import (
    safe_ext as _safe_ext,
    strip_code_fences as _strip_code_fences,
    save_source_file,
    save_docx,
)

# Hotkey config. Avoid Cmd+Shift+3/4/5/6 — macOS reserves those for screenshots.
HK_TOGGLE = "<cmd>+<shift>+1"
HK_FULL = "<cmd>+<shift>+2"
HK_REGION = "<cmd>+<shift>+8"
HK_QUIT = "<cmd>+<shift>+9"
HK_READY = "<cmd>+<shift>+7"   # owned session: "I scrolled, capture the next part"

CAPTURES_ROOT = Path("captures")  # scratch PNGs (gitignored); deleted on quit
REPORTS_ROOT = Path("reports")    # persistent .docx reports; survive quit
BG_WORKERS = int(os.environ.get("CODESNAP_WORKERS", "12" if os.environ.get("CODESNAP_BATCH", "0").lower() in ("1", "true", "on", "yes") else "3"))   # how many images to read concurrently
DUP_THRESHOLD = 3                 # perceptual-hash distance treated as a near-duplicate
MAX_FIX_ITERS = 3                 # max auto-fix passes when a code check fails
BURST_INTERVAL = 0.8              # seconds between burst captures
BURST_IDLE_STOP = 10.0            # stop after this many seconds with no new frame
BURST_KEEP_DIST = 6              # phash distance above which a frame counts as 'changed'
BURST_MAX_FRAMES = int(os.environ.get("CODESNAP_BURST_MAX_FRAMES", "5000"))   # effectively unlimited; the idle-stop and Esc end a burst
BURST_MAX_WAIT = 20              # stop if scrolling never starts (still 1 frame)

#Hashing of images for near-duplicate detection. If difference is below a threshold, the capture is skipped.
def _phash(data: bytes):
    try:
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(io.BytesIO(data)))
    except Exception:  # noqa: BLE001 - dedup is best-effort; never block a capture
        return None


def attach_budget(tracker, slug):
    from core import status
    from core.model import ProgramStore
    from core.usage import Budget, program_budget
    try:
        with ProgramStore.open(slug) as store:
            limit, spent = program_budget(store), store.usage()["cost"]
    except Exception:
        return None
    if not limit:
        return None
    tracker.budget = Budget(limit, spent, on_warn=lambda t, l: status.publish(
        f"API spend for this program is ${t:.2f} of the ${l:.2f} budget", "info"))
    return tracker.budget


class App:
    """Run state + API client + background reader pool."""

    def __init__(self, client):
        from core.usage import TrackedClient, UsageTracker
        if isinstance(client, TrackedClient):
            self.tracker = client.tracker
        else:
            self.tracker = UsageTracker()
            client = self.tracker.wrap(client) if client is not None else None
        self.client = client
        self.running = False                      # idle until a session is started
        self.agent_mode = False                   # set from --agent in main
        self.auto_mode = False                    # set from --auto (agent owns the session)
        self.burst_mode = False                   # set from --burst (auto-capture while scrolling)
        self.idle_stop = BURST_IDLE_STOP          # secs of no on-screen change before auto-stop; <=0 = manual (end with Cmd+Shift+1)
        self.region = None                        # (L,T,W,H) fractions to capture only the code area; None = full screen
        self.spacing_profile = None
        self.project_mode = False                 # project mode: capture many files back-to-back (analysis runs in the background)
        self.program = None
        self.capture_kind = "code"
        self._analysing = False                   # True while a capture is being analysed (single-file gate)
        self.team_mode = True                     # DEFAULT: multi-agent team (A2A). --single flips to backup single-agent.
        self._ready_event = threading.Event()     # set by Cmd+Shift+7 to advance an owned session
        self.capture_enabled = False              # captures allowed (stays on during agent run)
        self.session_dir = None                   # current session's capture folder
        self.count = 0                            # captures taken this session
        self._last_phash = None                   # retained for older capture modes
        self._last_manual_frame = None
        self.sessions = []                        # every session folder this run
        self._unsaved_sessions = set()            # retain recoverable evidence after a failed registration
        self._inflight = set()                    # saved captures this worker is analysing right now
        self._state_lock = threading.Lock()       # guards _inflight / _kind_guess / _threads (touched from several threads)
        self._kind_guess = {}                     # session folder -> future of the code/screen guess
        self._threads = []                        # burst loops + background analyses, joined before shutdown deletes folders
        self._session_start_lock = threading.Lock()
        self.display = None                       # display for captures: index, or None = the one under the mouse
        self._capture_lock = threading.Lock()     # serialises the actual screen grab
        self._analysis_lock = threading.Lock()    # serialises stop/quit analysis
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=BG_WORKERS)
        self._futures = []                         # pending background reads
        self._fut_lock = threading.Lock()
        self.listener = None                       # set in main()

    _LAZY = {"_state_lock": threading.Lock, "_session_start_lock": threading.Lock, "_kind_guess": dict, "_threads": list}
    _lazy_guard = threading.Lock()

    def __getattr__(self, name):
        # Only reached for attributes missing from the instance: objects built without __init__ (tests, subclasses)
        # still get working locks and registries, created once.
        factory = type(self)._LAZY.get(name)
        if factory is None:
            raise AttributeError(name)
        with type(self)._lazy_guard:
            if name not in self.__dict__:
                self.__dict__[name] = factory()
            return self.__dict__[name]

    # --- hotkey handlers: run on the listener thread; keep them light ---
    def toggle(self):
        if self.burst_mode:
            if self.running:
                self._stop_burst()          # Cmd+Shift+1 again -> finish this capture and analyse
            else:
                self._begin_burst_session()
            return
        if self.auto_mode:
            self._begin_owned_session()
            return
        if not self.running:
            self._start_session()
        else:
            self._stop_session()

    def on_full(self):
        self._capture("full")

    def on_region(self):
        self._capture("region")

    def quit(self):
        threading.Thread(target=self._shutdown, daemon=True).start()

    def ready(self):
        self._ready_event.set()

    def _ensure_client(self):
        """Client is normally built at boot; load lazily if it isn't (safe no-op otherwise)."""
        if self.client is None:
            import anthropic
            self.client = self.tracker.wrap(
                anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
        self._attach_usage_persistence()
        return self.client

    # --- thread-safe bookkeeping ---
    def _track(self, artifact_id):
        with self._state_lock:
            self._inflight.add(artifact_id)

    def _untrack(self, artifact_id):
        with self._state_lock:
            self._inflight.discard(artifact_id)

    def _is_inflight(self, artifact_id):
        with self._state_lock:
            return artifact_id in self._inflight

    def _spawn(self, target, *args, **kwargs):
        """Start a daemon thread that shutdown can later join."""
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        with self._state_lock:
            self._threads = [x for x in self._threads if x.is_alive()]
            self._threads.append(t)
        t.start()
        return t

    def _join_threads(self):
        """Wait for every tracked burst/analysis thread (including ones they start meanwhile)."""
        me = threading.current_thread()
        while True:
            with self._state_lock:
                pending = [t for t in self._threads if t.is_alive() and t is not me]
                self._threads = list(pending)
            if not pending:
                return
            for t in pending:
                t.join()

    # --- burst mode: auto-capture while the user scrolls; phash drops near-dups ---
    def _stop_burst(self):
        """Manually end a running burst (Cmd+Shift+1 again). The burst loop sees
        running=False, exits, and its tail runs the analysis."""
        from core import status
        status.publish("Capture complete — analysing", "info")
        from core.notify import notify
        notify("CodeSnap", "Capture complete — analysing")
        print("[burst] stop requested (Cmd+Shift+1) — analysing.")
        self.running = False

    def _begin_burst_session(self):
        # check-and-set of `running` must be atomic: a double hotkey press must not start two bursts
        if not self._session_start_lock.acquire(blocking=False):
            print("(a session is already starting)")
            return
        try:
            self._begin_burst_session_locked()
        finally:
            self._session_start_lock.release()

    def _begin_burst_session_locked(self):
        if self.running:
            print("(a session is already running)")
            return
        if not self.project_mode and self._analysing:
            from core import status
            status.publish("Still analysing the previous file — single mode captures one at a time.", "info")
            from core.notify import notify
            notify("CodeSnap", "Still analysing the previous capture — one file at a time.")
            print("(single-file mode: still analysing the previous capture)")
            return
        self._load_capture_settings()
        self._ensure_client()
        try:
            kind = (CAPTURES_ROOT / ".capture_kind").read_text().strip()
            if kind in ("code", "screen", "auto"):
                self.capture_kind = kind   # switching Code / App screen no longer restarts the worker
        except OSError:
            pass
        from core import status
        status.clear()
        status.publish("Burst capture — scroll through the file steadily", "start")
        from core.notify import notify
        notify("CodeSnap", "Session started — start scrolling")
        ts = time.strftime("%Y%m%d_%H%M%S")
        CAPTURES_ROOT.mkdir(parents=True, exist_ok=True)
        self.session_dir = Path(tempfile.mkdtemp(prefix=f"session_{ts}_", dir=CAPTURES_ROOT))
        self.sessions.append(self.session_dir)
        try:
            from core.capture import pick_display
            print(f"[burst] capturing display {pick_display(self.display)}")
        except Exception as exc:  # noqa: BLE001
            print(f"(display selection skipped: {exc})", file=sys.stderr)
        self.running = True
        self.capture_enabled = True
        print("[burst] Scroll through the file steadily. It captures automatically and "
              "stops when you stop scrolling. Cmd+Shift+9 to quit.")
        self._spawn(self._burst_loop, self.session_dir)

    def _load_capture_settings(self):
        """Refresh only at a capture boundary, keeping each file on one selected area."""
        import os
        import json
        from webapp.session import capture_settings
        try:
            saved = json.loads((CAPTURES_ROOT / '.capture_settings.json').read_text())
            if saved.get('pid') != os.getpid():
                return
            settings = capture_settings(saved.get('region'), saved.get('display'))
        except (OSError, ValueError, TypeError):
            return
        self.region = tuple(settings['region']) if settings['region'] else None
        self.display = settings['display']
        from core.spacing import validate_profile
        try:
            self.spacing_profile = validate_profile(saved['spacing']) if saved.get('spacing') else None
        except ValueError:
            self.spacing_profile = None

    def _refresh_capture_area(self):
        path = CAPTURES_ROOT / '.capture_settings.json'
        try:
            stamp = path.read_text()
        except OSError:
            return False
        if stamp == getattr(self, '_settings_stamp', None):
            return False
        self._settings_stamp = stamp
        before = (getattr(self, 'region', None), getattr(self, 'display', None), getattr(self, 'spacing_profile', None))
        self._load_capture_settings()
        return before != (getattr(self, 'region', None), getattr(self, 'display', None), getattr(self, 'spacing_profile', None))

    def _attach_usage_persistence(self):
        if self.program:
            from core.usage import persist_record, SavedBudget
            self.tracker.on_record = lambda record: persist_record(self.program, record)
            self.tracker.budget = SavedBudget(self.program)

    def _safe_extract(self, path, cache_dir):
        try:
            from core.analysis import extract_to_cache
            self._attach_usage_persistence()
            self.tracker.set_thread_bucket(str(Path(path).parent))
            extract_to_cache(self.client, path, cache_dir)
            self._sync_text_cache(Path(path).parent, [Path(path)], load=False)   # keep the text even if the worker restarts
        except Exception as exc:  # noqa: BLE001
            from core.analysis import is_fatal_api_error
            if is_fatal_api_error(exc):   # a bad key / request will fail every frame: say so now, not at the end
                print(f"Frame read failed and will not recover by retrying: {type(exc).__name__}: {exc}", file=sys.stderr)
            # transient failures are retried when the file is analysed

    def _own_window_in_front(self) -> bool:
        """True while CodeSnap itself is the front window, so its own screen is never captured as a file."""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app.processIdentifier() in (os.getpid(), os.getppid()) or app.localizedName() == "CodeSnap":
                return True
        except Exception:  # noqa: BLE001 - not macOS / no AppKit: capture as before
            return False
        # CodeSnap opened in a browser tab: the front window's title is the page title ("Ledelsea — CodeSnap")
        try:
            import Quartz
            pid = app.processIdentifier()
            wins = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
            for w in wins or []:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer", 0) == 0:
                    return "CodeSnap" in str(w.get("kCGWindowName") or "")
        except Exception:  # noqa: BLE001
            pass
        return False

    def _burst_loop(self, session_dir):
        from core.capture import capture_full_png, capture_region_fixed, next_png_path, content_changed
        from core import status
        cache = session_dir / ".cache"
        last_frame = None
        kept = 0
        capture_error = None
        last_change = time.monotonic()
        started = time.monotonic()
        while self.running and kept < BURST_MAX_FRAMES:
            if self._own_window_in_front():
                time.sleep(BURST_INTERVAL)
                if kept == 0:
                    started = time.monotonic()
                continue
            if self._refresh_capture_area():
                last_frame = None
                status.publish("Capture area changed. It applies from the next frame.", "info")
            try:
                data = capture_region_fixed(self.region) if self.region else capture_full_png()
            except Exception as exc:  # noqa: BLE001
                print(f"Capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                capture_error = f"Screen capture stopped unexpectedly: {exc}. Recapture the file to confirm completeness."
                break
            changed = (last_frame is None) or content_changed(last_frame, data)
            if changed:
                try:
                    out = next_png_path(session_dir)
                    out.write_bytes(data)
                    from core.spacing import bind
                    bound=bind(out,getattr(self,'spacing_profile',None) if self.region else None)
                    if self.region and getattr(self,'spacing_profile',None) and not bound['confirmed']:
                        status.publish(bound.get('reason','Reset the source margin in Pick code area.'),'info')
                except OSError as exc:
                    capture_error = f"A screenshot could not be saved: {exc}. Recapture the file to confirm completeness."
                    break
                kept += 1
                last_frame = data
                last_change = time.monotonic()
                status.publish(f"Captured frame {kept}")
                if kept == 1:
                    from core.capture import clarity_warning
                    warn = clarity_warning()
                    if warn:
                        status.publish(warn, "info")
                print(f"  burst frame {kept}: {out.name}")
                if kept == 1 and self.capture_kind == "auto":
                    from core.analysis import detect_kind
                    with self._state_lock:
                        self._kind_guess[str(session_dir)] = self._pool.submit(detect_kind, self.client, out)
                with self._state_lock:
                    guess = self._kind_guess.get(str(session_dir))
                guessed_screen = False
                if guess is not None and guess.done():
                    try:
                        guessed_screen = guess.result() == "screen"
                    except Exception:
                        # Register the evidence first; analysis will expose a recoverable failure.
                        pass
                if not guessed_screen:
                    self._pool.submit(self._safe_extract, out, cache)
            if self.idle_stop > 0:
                idle = time.monotonic() - last_change
                if kept >= 2 and idle >= self.idle_stop:
                    break
                if kept < 2 and (time.monotonic() - started) >= BURST_MAX_WAIT:
                    break
            # manual mode (idle_stop <= 0): never auto-stop — ends via Cmd+Shift+1 or the frame cap
            time.sleep(BURST_INTERVAL)
        status.publish(
            "Only one screenshot saved. If you scrolled, check the selected display and code area, "
            "then recapture; choose manual stop for a long file." if kept == 1 else
            f"Scrolling stopped — {kept} unique frame(s), analysing", "info")
        from core.notify import notify
        notify("CodeSnap", f"Capture complete — {kept} frame(s), analysing")
        artifact_id = self._register_capture(session_dir)
        if capture_error:
            self.running = self.capture_enabled = False
            self._mark_failed(artifact_id, capture_error)
            if self.program and artifact_id:
                from core.model import ProgramStore
                with ProgramStore.open(self.program) as store:
                    store.update_pending(artifact_id, capture_incomplete=True)
            self._untrack(artifact_id)
            status.publish(capture_error, "error", stage="done")
            return
        if self.project_mode:
            print(f"[burst] done capturing: {kept} unique frame(s). Analysing in background — start the next file.")
            self.running = False        # project mode: free the session so the next file can be captured now
            self.capture_enabled = False
            self._spawn(self._analyse_burst, session_dir, artifact_id=artifact_id)
        else:
            print(f"[burst] done capturing: {kept} unique frame(s). Analysing...")
            self.running = False          # free run-state; the _analysing gate blocks a new capture until done
            self.capture_enabled = False
            self._analyse_burst(session_dir, artifact_id=artifact_id)   # inline (blocks this thread); one file at a time

    # --- every start/stop is a file: saved to the program before analysis, resumed if the worker stops ---
    def _register_capture(self, session_dir):
        if not self.program:
            return None
        imgs = sorted(Path(session_dir).glob("*.png"))
        if not imgs:
            return None
        from core import status
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store, store.transaction():
                target = store.get_meta("recapture_target") or {}
                if target.get("artifact_id"):
                    current = store.current_artifact(target.get("name"))
                    if not current or current["id"] != target["artifact_id"]:
                        raise ValueError("The recapture target changed. Choose the current file before retrying.")
                if target:
                    store.set_meta("recapture_target", None)
                session_id = store.add_session(mode="burst", region=",".join(map(str, self.region)) if self.region else None)
                append_to = target.get("artifact_id") if target.get("mode") == "append" else None
                artifact_id = store.add_pending_capture(imgs, kind=self.capture_kind, session_id=session_id,
                                                        recapture_of=target.get("name"), keep_frames_of=append_to)
                if append_to:   # analyse the file's earlier screenshots together with the new ones
                    for i, e in enumerate(store.artifact_evidence(append_to), 1):
                        shutil.copyfile(store.evidence(e["id"])["abs_path"], Path(session_dir) / f"0000_{i:03d}.png")
                store.claim_pending(artifact_id, self._owner)
                self._track(artifact_id)
                name = store.artifact(artifact_id)["name"]
            what = ((f"added screenshots to {target['name']}" if target.get("mode") == "append" else
                     f"new version of {target['name']}") if target.get("name") else name)
            status.publish(f"Saved capture as {what} — analysing", "info")
            return artifact_id
        except Exception as exc:  # noqa: BLE001
            print(f"Couldn't save the capture to the program: {exc}", file=sys.stderr)
            self._unsaved_sessions.add(Path(session_dir))
            status.publish(f"Capture could not be saved: {exc}. Screenshots retained in {session_dir}.", "error", stage="done")
            return None

    @property
    def _owner(self):
        return f"{os.getpid()}:{id(self)}"

    def _pending_work(self):
        from core.model import ProgramStore
        with ProgramStore.open(self.program) as store:
            pend = store.pending_captures()
            todo = []
            for aid, info in sorted(pend.items()):
                art = store.artifact(aid)
                if art is None:
                    store.clear_pending(aid)
                    continue
                if self._is_inflight(aid) or art["status"] != "captured" or not store.claim_pending(aid, self._owner):
                    continue
                self._track(aid)
                todo.append((aid, info.get("kind") or "code", [e["abs_path"] for e in
                            (store.evidence(x["id"]) for x in store.artifact_evidence(aid)) if e]))
        return todo

    def process_pending(self):
        """Analyse every saved capture still waiting (e.g. the worker was stopped mid-queue). Returns how many ran."""
        if not self.program:
            return 0
        done = 0
        for aid, kind, frames in self._pending_work():
            CAPTURES_ROOT.mkdir(parents=True, exist_ok=True)
            d = Path(tempfile.mkdtemp(prefix=f"resume_{aid}_", dir=CAPTURES_ROOT))
            self.sessions.append(d)
            for i, src in enumerate(frames, 1):
                shutil.copyfile(src, d / f"{i:03d}.png")
            print(f"[pending] analysing saved capture {aid} ({len(frames)} frame(s))")
            self._analyse_burst(d, artifact_id=aid, kind=kind)
            done += 1
        return done

    def _pending_loop(self, every: float = 10.0):
        while True:
            try:
                if not self.running:
                    self.process_pending()
            except Exception as exc:  # noqa: BLE001
                print(f"(pending captures: {exc})", file=sys.stderr)
            time.sleep(every)

    def _resolve_kind(self, kind, imgs, artifact_id=None):
        """An "auto" capture is read as code or as an app screen depending on what its first frame shows."""
        if kind != "auto" or not imgs:
            return kind if kind != "auto" else "code"
        from core import status
        from core.analysis import detect_kind
        with self._state_lock:
            fut = self._kind_guess.pop(str(imgs[0].parent), None)
        kind = fut.result() if fut is not None else detect_kind(self.client, imgs[0])
        status.publish("Looks like an application screen: reading it as one" if kind == "screen" else
                       "Looks like code: reading it as code", "info")
        if self.program and artifact_id:
            try:
                from core.model import ProgramStore
                with ProgramStore.open(self.program) as store:
                    store.update_pending(artifact_id, kind=kind)
            except Exception:  # noqa: BLE001
                pass
        return kind

    def _analyse_burst(self, session_dir, artifact_id=None, kind=None):
        if self.program and artifact_id is None:
            # Registration failed. Never bypass its target checks by importing a new file.
            self._unsaved_sessions.add(Path(session_dir))
            return
        kind = kind or self.capture_kind
        imgs = sorted(session_dir.glob("*.png"))
        try:
            kind = self._resolve_kind(kind, imgs, artifact_id)
        except Exception as exc:
            # a background analysis failing must not stop a capture the user has since started
            print(f"Capture classification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._mark_failed(artifact_id, f"Capture classification failed: {exc}")
            self._untrack(artifact_id)
            return
        if not imgs:
            print("[burst] no frames captured.")
            try:
                from core import status
                status.publish("No frames captured — scroll while the session runs so it can read the screen.", "info", stage="done")
                from core.notify import notify
                notify("CodeSnap", "No frames captured — scroll during the session, then it analyses.")
            except Exception:  # noqa: BLE001
                pass
            return
        ts = session_dir.name.replace("session_", "")
        ctx = ToolContext(
            client=self.client, images=list(imgs),
            cache_dir=session_dir / ".cache", out_dir=REPORTS_ROOT,
            out_name=f"report_{ts}", session_dir=session_dir, interactive=False, confirm_saves=False,
            program_mode=bool(self.program),
        )
        self._analysis_lock.acquire()   # serialise overlapping analyses (captures stay non-blocking)
        imgs = sorted(session_dir.glob("*.png"))   # listed under the lock: never a half-written frame set
        ctx.images = list(imgs)
        self._analysing = True
        self._sync_text_cache(session_dir, imgs, load=True)
        self._stage(artifact_id, "reading screenshots", cache_dir=ctx.cache_dir)
        bucket = str(session_dir)
        self.tracker.default_bucket = bucket
        self._attach_usage_persistence()
        try:
            if self.program:
                self._share_copybooks()
            audit = []
            goal = (f"There are {len(imgs)} screenshots of one scrolled document/code, in order "
                    f"(consecutive shots overlap). Produce the best verified output.")
            if kind == "screen":
                self._analyse_screen(imgs, ctx)
            else:
                if self.team_mode:
                    runner = run_team if getattr(self, "sequential_team", False) else run_team_fast
                else:
                    runner = run_agent
                final, _ = runner(self.client, ctx, goal=goal, verbose=True, audit=audit)
                print(f"\n{'=' * 60}\n{final}\n{'=' * 60}")
            records = self.tracker.take(bucket)
            self._report_usage(records)
            self._sync_text_cache(session_dir, imgs, load=False)
            if self.program:
                self._stage(artifact_id, "adding to the program")
                self._ingest_into_program(imgs, ctx, records, artifact_id=artifact_id)
                self._report_if_done()
            self.tracker.take(bucket)
        except Exception as exc:  # noqa: BLE001
            print(f"Analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if self.program:
                from core.usage import persist_record
                for record in self.tracker.take(bucket):
                    persist_record(self.program, record, artifact_id)
            self._mark_failed(artifact_id, f"{type(exc).__name__}: {exc}")
            try:
                from core import status
                status.publish("Analysis failed — the capture is saved; use Retry on it in the program.", "error", stage="done")
                from core.notify import notify
                notify("CodeSnap", "Analysis failed — please try again.")
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._analysing = False
            self._untrack(artifact_id)
            self._analysis_lock.release()
            print("\n[idle] Cmd+Shift+1 for a new burst, Cmd+Shift+9 to quit.")

    def _share_copybooks(self):
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store:
                os.environ["CODESNAP_COPYBOOK_DIRS"] = str(store.export_copybooks())
        except Exception as exc:  # noqa: BLE001
            print(f"Copybook export skipped: {exc}", file=sys.stderr)

    def _analyse_screen(self, imgs, ctx):
        import re as _re
        from core import status
        from core.extractors.ui import extract_ui_screen, screen_name, to_transcription
        status.publish("Reading the application screen", "tool", stage="read")
        screen = extract_ui_screen(self.client, imgs)
        title = screen_name(screen)
        stem = _re.sub(r"[^A-Za-z0-9_]+", "_", title).strip("_") or "Screen"
        ctx.last_report = {"is_code": True, "artifact_type": "ui_screen", "code": to_transcription(screen),
                           "extension": "screen", "language": "UI screen", "errors": "None", "code_name": stem,
                           "validation_tool": "n/a"}
        fields, actions = len(screen.get("fields") or []), len(screen.get("actions") or [])
        print(f"[screen] {title}: {fields} fields, {actions} actions, {len(screen.get('issues') or [])} issues")
        status.publish(f"Screen read: {title} ({fields} fields, {actions} actions)", "done", stage="done")

    def _report_usage(self, records):
        from core import status
        from core.usage import summarize
        total = summarize(records)
        steps = ", ".join(f"{k} ${v['cost']:.3f}" for k, v in sorted(total["by_step"].items(), key=lambda kv: -kv[1]["cost"]))
        print(f"[usage] {total['calls']} calls, {total['input_tokens']:,} in / {total['output_tokens']:,} out tokens, "
              f"${total['cost']:.3f} ({steps})")
        print(f"(cost for this file: ${total['cost']:.3f}, {total['calls']} calls)")

    def _stage(self, artifact_id, stage, cache_dir=None):
        if not (self.program and artifact_id):
            return
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store:
                changes = {"stage": stage}
                if cache_dir is not None:
                    changes["cache_dir"] = str(Path(cache_dir).resolve())
                store.update_pending(artifact_id, **changes)
        except Exception:  # noqa: BLE001
            pass

    def _report_if_done(self):
        """Build the program report once, when the last waiting capture has been analysed."""
        from core import status
        from core.model import ProgramStore
        from core.report import cached_package, waiting
        try:
            with ProgramStore.open(self.program) as store:
                if waiting(store) or any(a["status"] == "captured" for a in store.artifacts()):
                    return
                status.publish("All files analysed — building the report", "tool", stage="save")
                res = cached_package(store)
                n = len(store.artifacts())
            if res.get("built"):
                status.publish(f"Report ready — {n} files", "done", stage="done")
        except Exception as exc:  # noqa: BLE001
            print(f"(report build: {exc})", file=sys.stderr)

    def _sync_text_cache(self, session_dir, imgs, load: bool):
        """Share per-screenshot transcriptions with the program (load before analysis, save after)."""
        import json
        if not self.program:
            return
        from core.analysis import cache_path_for, _publish_cache
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store:
                shared = store.text_cache_dir
            local = Path(session_dir) / ".cache"
            local.mkdir(exist_ok=True)
            for img in imgs:
                name = cache_path_for(img, local).name
                for suffix in ("", ".corr.json", ".verify.json", '.ocr.md'):
                    fn = name if not suffix else name[:-3] + suffix
                    src, dst = (shared / fn, local / fn) if load else (local / fn, shared / fn)
                    refresh = not load and suffix in ('', '.verify.json')
                    if src.exists() and (not dst.exists() or refresh):
                        if suffix == '' and dst.exists():
                            original = dst.with_suffix('.ocr.md')
                            if not original.exists():
                                _publish_cache(original, dst.read_text())
                        _publish_cache(dst, src.read_text())
                image=Path(img)
                ev=shared.parent / (name[:-3]+image.suffix)
                source,target=(ev.with_suffix('.spacing.json'),image.with_suffix('.spacing.json')) if load else (image.with_suffix('.spacing.json'),ev.with_suffix('.spacing.json'))
                if source.exists() and (not target.exists() or not load):
                    from core.spacing import image_hash
                    metadata = json.loads(source.read_text())
                    if metadata.get('image_sha256') == image_hash(image):
                        _publish_cache(target, json.dumps(metadata))
        except Exception as exc:  # noqa: BLE001
            print(f"(screenshot text cache: {exc})", file=sys.stderr)

    def _mark_failed(self, artifact_id, error):
        if not (self.program and artifact_id):
            return
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store:
                if store.artifact(artifact_id) and artifact_id in store.pending_captures():
                    store.update_pending(artifact_id, error=error, claim=None)
                    store.set_status(artifact_id, "failed")
        except Exception:  # noqa: BLE001
            pass

    def _analyse_code(self, artifact_id, name):
        """The line-by-line code analysis, run as part of analysing every file (CODESNAP_DEEP=0 turns it off)."""
        import os
        if os.environ.get("CODESNAP_DEEP", "1") == "0" or not (self.program and artifact_id and self.client):
            return
        if os.environ.get("CODESNAP_PIPELINE", "").lower() == "staged":
            return
        from core import deepdive, status
        from core.model import ProgramStore
        try:
            status.publish(f"Reviewing {name} line by line", "tool", stage="save")
            with ProgramStore.open(self.program) as store:
                res = deepdive.run(store, self.client, artifact_ids=[artifact_id], program=False)
                q = deepdive.rescan_requests(store)
            if res["errors"]:
                print("Code analysis: " + "; ".join(res["errors"]), file=sys.stderr)
            bad = next((r for r in q if r["artifact_id"] == artifact_id), None)
            if bad:
                status.publish(f"{name} needs a rescan: " + "; ".join(i["reason"] for i in bad["issues"][:2]), "error", stage="done")
        except Exception as exc:  # noqa: BLE001
            print(f"Code analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    def _report_recapture(self, artifact_id):
        from core import deepdive, status
        from core.model import ProgramStore
        try:
            with ProgramStore.open(self.program) as store:
                a = store.artifact(artifact_id)
                o = a and deepdive.recapture_outcome(store, a, deepdive.capture_quality(store, a, deepdive.current_concerns(store, a)))
            if o and o["result"] == "fixed":
                status.publish(f"{a['name']} is fixed: the recapture (v{o['version']}) is complete", "info", stage="done")
            elif o and o["result"] == "still":
                status.publish(f"{a['name']} v{o['version']} still needs a recapture: " +
                               "; ".join(i["reason"] for i in o["remaining"][:2]), "error", stage="done")
        except Exception as exc:  # noqa: BLE001
            print(f"Recapture check failed: {exc}", file=sys.stderr)

    def _ingest_into_program(self, imgs, ctx, records=(), artifact_id=None):
        from core import status
        from core.model import ProgramStore, complete_capture, ingest_capture
        if artifact_id:
            try:
                with ProgramStore.open(self.program) as store:
                    if not store.artifact(artifact_id):
                        return
                    claim = (store.pending_captures().get(artifact_id) or {}).get("claim") or {}
                    if claim and claim.get("owner") != self._owner:
                        raise RuntimeError("Capture ownership changed; results were not applied.")
                    # Provider callbacks save usage through another connection; never
                    # hold a SQLite write transaction while calling the provider.
                    final_id = complete_capture(store, self.client, artifact_id, ctx.last_report)
                    for r in records:
                        store.log_usage_record(r, artifact_id=final_id)
                    art = store.artifact(final_id)
                ok = art["status"] != "failed"
                if ok:
                    self._analyse_code(final_id, art["name"])
                    self._report_recapture(final_id)
                status.publish(f"Added {art['name']} (v{art['version']}) to program {self.program}" if ok else
                               f"Couldn't read {art['name']} — it's saved; Retry or Recapture it", "info" if ok else "error",
                               stage="done")
            except Exception as exc:  # noqa: BLE001
                print(f"Program update failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                self._mark_failed(artifact_id, str(exc))
            return
        if not ctx.last_report:
            return
        try:
            with ProgramStore.open(self.program) as store:
                session_id = store.add_session(mode="burst", region=",".join(map(str, self.region)) if self.region else None)
                status.publish("Adding file to the program model", "tool", stage="save")
                artifact_id = ingest_capture(store, self.client, imgs, ctx.last_report, session_id=session_id)
                for r in records:
                    store.log_usage_record(r, artifact_id=artifact_id)
                name = store.artifact(artifact_id)["name"]
            self._analyse_code(artifact_id, name)
            status.publish(f"Added {name} to program {self.program}", "info", stage="done")
        except Exception as exc:  # noqa: BLE001
            print(f"Program update failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            status.publish(f"Couldn't add the file to the program: {exc}", "error", stage="done")

    # --- session lifecycle ---
    def _begin_owned_session(self):
        if self.running:
            print("(a session is already running)")
            return
        from core.capture import capture_full_png
        ts = time.strftime("%Y%m%d_%H%M%S")
        CAPTURES_ROOT.mkdir(parents=True, exist_ok=True)
        self.session_dir = Path(tempfile.mkdtemp(prefix=f"session_{ts}_", dir=CAPTURES_ROOT))
        self.sessions.append(self.session_dir)
        self.count = 1
        self._last_phash = None
        self._last_manual_frame = None
        self.running = True
        self.capture_enabled = True
        try:
            first = self.session_dir / "001.png"
            first.write_bytes(capture_full_png())
        except Exception as exc:  # noqa: BLE001
            print(f"First capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            self.running = False
            return
        from core.notify import notify
        notify("CodeSnap", "Captured — analysing...")
        print("  Captured the screen — analysing. The agent will notify you to scroll "
              "(press Cmd+Shift+7), and tell you when to return to the terminal. Cmd+Shift+9 to quit.")
        threading.Thread(target=self._run_owned_session, args=(self.session_dir, [first]), daemon=True).start()

    def _run_owned_session(self, session_dir, first_imgs):
        ts = session_dir.name.replace("session_", "")
        ctx = ToolContext(
            client=self.client, images=list(first_imgs),
            cache_dir=session_dir / ".cache", out_dir=REPORTS_ROOT,
            out_name=f"report_{ts}", session_dir=session_dir, interactive=True,
            ready_event=self._ready_event, confirm_saves=False,
        )
        try:
            audit = []
            final, _ = run_session(self.client, ctx, audit=audit)
            print(f"\n{'=' * 60}\n{final}\n{'=' * 60}")
            print(f"(agent session used {len(audit)} tool step(s))")
        except Exception as exc:  # noqa: BLE001
            print(f"Agent session failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            self.running = False
            self.capture_enabled = False
            print("\n[idle] Cmd+Shift+1 for a new session, Cmd+Shift+9 to quit.")

    def _start_session(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        CAPTURES_ROOT.mkdir(parents=True, exist_ok=True)
        self.session_dir = Path(tempfile.mkdtemp(prefix=f"session_{ts}_", dir=CAPTURES_ROOT))
        self.sessions.append(self.session_dir)
        self.count = 0
        self._last_phash = None
        self._last_manual_frame = None
        self.running = True
        self.capture_enabled = True
        print(f"\n[running] session: {self.session_dir.resolve()}")
        print("  Cmd+Shift+2 = full screen, Cmd+Shift+8 = region, Cmd+Shift+1 = stop & analyse.")

    def _stop_session(self):
        self.running = False
        if not self.agent_mode:
            self.capture_enabled = False
        session_dir = self.session_dir
        print("\n[stopped] wrapping up session...")
        threading.Thread(target=self._analyse_then_idle, args=(session_dir,), daemon=True).start()

    def _analyse_then_idle(self, session_dir):
        self._finish(session_dir)
        print("\n[idle] Cmd+Shift+1 to start a new session, Cmd+Shift+9 to quit.")

    def _capture(self, kind):
        if not self.capture_enabled:
            print("(idle — press Cmd+Shift+1 to start a session first)")
            return
        threading.Thread(target=self._do_capture, args=(kind, self.session_dir), daemon=True).start()

    # --- workers: run off the listener thread ---
    #One-liner hotkey handlers. Each just calls self._capture("full") or self._capture("region"). 
    # They exist as named methods so pynput can register them as hotkey callbacks.
    def _do_capture(self, kind, session_dir):
        # Only the grab itself is serialised (can't run two region selects at once).
        if not self._capture_lock.acquire(blocking=False):
            print("(busy — finish the current capture/selection first)")
            return
        out = None
        try:
            if kind == "full":
                print("Capturing full screen...")
                data = capture_full_png()
            else:
                print("Select a region (drag), or press Esc to cancel...")
                data = capture_region_png()
                if data is None:
                    print("(region selection cancelled)")
                    return
            # An explicit capture may contain a one-character correction.
            # Similar layout is not proof that the text is unchanged.
            if data == self._last_manual_frame:
                print("  identical to the previous capture — skipped")
                return
            out = next_png_path(session_dir)
            out.write_bytes(data)
            self._last_manual_frame = data
            self.count += 1
            print(f"  saved capture {self.count}: {out.name} — reading in background...")
        except Exception as exc:  # noqa: BLE001
            print(f"Capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            self._capture_lock.release()

        # Kick off the read in the background so it's ready by the time we stop.
        if out is not None:
            fut = self._pool.submit(self._read_in_background, out, session_dir / ".cache")
            with self._fut_lock:
                self._futures.append(fut)

    def _read_in_background(self, path, cache_dir):
        try:
            extract_to_cache(self.client, path, cache_dir)
            print(f"  read {path.name}")
        except Exception as exc:  # noqa: BLE001 - retried at stop via analyse_incremental
            print(f"  (background read of {path.name} failed: {type(exc).__name__} — will retry at stop)",
                  file=sys.stderr)

    def _wait_for_reads(self):
        with self._fut_lock:
            futs = [f for f in self._futures if not f.done()]
            self._futures.clear()
        if futs:
            print(f"  finishing {len(futs)} background read(s)...")
            concurrent.futures.wait(futs)

    def _finish(self, session_dir):
        self._wait_for_reads()
        with self._analysis_lock:
            imgs = sorted(session_dir.glob("*.png")) if session_dir else []
            if not imgs:
                print("[stopped] no captures in this session — nothing to analyse.")
                self.capture_enabled = False
                return
            if self.agent_mode:
                self._run_agent(session_dir, imgs)
                self.capture_enabled = False
                return
            print(f"Stitching {len(imgs)} capture(s) and writing the overview...")
            try:
                # Cache is already warm from background reads, so this is mostly
                # cache hits + a single overview call.
                result = analyse_incremental(self.client, imgs, cache_dir=session_dir / ".cache")
            except Exception as exc:  # noqa: BLE001
                print(f"Analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return

        print(f"\n{'=' * 60}\nOVERVIEW\n{'=' * 60}")
        print(result.get("explanation", "").strip())

        extracted = result.get("extracted_text", "").strip()
        if not extracted:
            print("\nNo text content detected — nothing to put in a report.")
            return

        print(f"\n{'-' * 60}\nEXTRACTED TEXT\n{'-' * 60}")
        print(extracted)

        # Route the output by content type.
        if result.get("is_code"):
            self._save_source(result, session_dir)
        else:
            self._save_docx(result, session_dir)

    def _run_agent(self, session_dir, imgs):
        """Agent mode: hand the session to the tool-use agent (it reads, classifies,
        checks, fixes, saves, and can ask for more captures)."""
        ts = session_dir.name.replace("session_", "")
        ctx = ToolContext(
            client=self.client, images=list(imgs),
            cache_dir=session_dir / ".cache", out_dir=REPORTS_ROOT,
            out_name=f"report_{ts}", session_dir=session_dir, interactive=True,
        )
        print("[agent] working over the session (it may ask for more captures)...")
        goal = (f"There are {len(imgs)} screenshot(s). Produce the best verified output, "
                f"following your instructions.")
        try:
            audit = []
            final, _ = run_agent(self.client, ctx, goal=goal, verbose=True, audit=audit)
            print(f"\n{'=' * 60}\n{final}\n{'=' * 60}")
            print(f"(agent used {len(audit)} tool step(s))")
        except Exception as exc:  # noqa: BLE001
            print(f"Agent failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    # --- output savers ---
    def _save_source(self, result, session_dir):
        lang = result.get("language") or "code"
        ext_guess = (result.get("extension") or "txt").lstrip(".").lower() or "txt"
        print(f"\nDetected: {lang} source code  ->  .{ext_guess}")
        if input("Save as a source file? [y/n]: ").strip().lower() != "y":
            print("No file saved.")
            return
        typed = input(f"File extension [{ext_guess}]: ").strip().lstrip(".").lower()
        ext = _safe_ext(typed or ext_guess)
        try:
            ts = session_dir.name.replace("session_", "")
            out = save_source_file(result.get("extracted_text", ""), REPORTS_ROOT, f"report_{ts}", ext)
            print(f"Saved source file: {out.resolve()}")
        except Exception as exc:  # noqa: BLE001
            print(f"(could not save source file: {type(exc).__name__}: {exc})", file=sys.stderr)
            return
        self._validate_and_fix(out, result.get("language") or "")

    def _validate_and_fix(self, path, language):
        """Syntax/compile-check the saved file; on failure, loop with Claude to
        fix transcription errors and re-check (check only — never runs the code)."""
        res = check_source(path)
        if not res["checked"]:
            print(f"  (not syntax-checked — {res['note']})")
            return
        if res["ok"]:
            print(f"  check passed ({res['tool']}) — no syntax errors found.")
            return

        print(f"  check FAILED ({res['tool']}):")
        print(textwrap.indent(res["errors"] or "(no detail)", "    "))
        if input("  Attempt auto-fix? [y/n]: ").strip().lower() != "y":
            print("  Left as-is.")
            return

        original = path.read_text()
        candidate = path.with_name(f"{path.stem}.fixed{path.suffix}")
        current = original
        for i in range(1, MAX_FIX_ITERS + 1):
            print(f"  fix attempt {i}/{MAX_FIX_ITERS}...")
            try:
                fixed = _strip_code_fences(fix_source(self.client, current, language, res["errors"]))
            except Exception as exc:  # noqa: BLE001
                print(f"  (fix call failed: {type(exc).__name__}: {exc}) — the captured original was kept", file=sys.stderr)
                break
            problem = fix_looks_complete(original, fixed)
            if problem:
                print(f"  (fix discarded: {problem}) — the captured original was kept", file=sys.stderr)
                break
            current = fixed
            candidate.write_text(fixed)   # never overwrite the captured original
            res = check_source(candidate)
            if res["ok"]:
                print(f"  fixed — check passed ({res['tool']}) after {i} attempt(s).")
                print(f"  corrected copy: {candidate}   (captured original untouched: {path})")
                return
            print("  still failing:")
            print(textwrap.indent(res["errors"] or "(no detail)", "    "))
        else:
            print(f"  Could not fully fix after {MAX_FIX_ITERS} attempt(s); the latest attempt is in {candidate}.")
            print(f"  The captured original is untouched: {path}")
            return
        candidate.unlink(missing_ok=True)

    def _save_docx(self, result, session_dir):
        if input("\nSave report to a Word document? [y/n]: ").strip().lower() != "y":
            print("No report saved.")
            return
        try:
            ts = session_dir.name.replace("session_", "")
            out = save_docx(result, REPORTS_ROOT, f"report_{ts}")
            print(f"Saved report: {out.resolve()}")
        except Exception as exc:  # noqa: BLE001
            print(f"(could not save docx: {type(exc).__name__}: {exc})", file=sys.stderr)

    # --- shutdown: analyse a pending session, delete this run's folders, exit ---
    def _shutdown(self):
        print("\n[quit] wrapping up...")
        if self.running:
            self.running = False
            if not self.burst_mode:
                self._finish(self.session_dir)
            # burst mode: the loop sees running=False and its own tail analyses the capture; joined below,
            # so the session is analysed once, not by both _finish() and _analyse_burst()

        # Burst loops and background analyses must be done before any folder is deleted.
        self._join_threads()

        # Stop accepting/await background reads before deleting anything.
        self._pool.shutdown(wait=True, cancel_futures=True)

        with self._analysis_lock:
            removed = 0
            for d in self.sessions:
                if d in self._unsaved_sessions:
                    print(f"Kept unsaved capture screenshots: {d}")
                    continue
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            try:
                if CAPTURES_ROOT.exists() and not any(CAPTURES_ROOT.iterdir()):
                    CAPTURES_ROOT.rmdir()
            except OSError:
                pass
        print(f"Deleted {removed} session folder(s); reports in {REPORTS_ROOT}/ kept. Bye.")

        if self.listener is not None:
            self.listener.stop()


def main() -> int:
    import argparse
    try:
        sys.stdout.reconfigure(line_buffering=True)  # ensure prints show live, not buffered
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--classic", action="store_true", help="Old fixed pipeline (you capture; it analyses at stop).")
    ap.add_argument("--agent", action="store_true", help="Agent analyses at stop (you still capture manually).")
    ap.add_argument("--auto", action="store_true", help="Agent-owned session: it captures and pages itself.")
    ap.add_argument("--burst", action="store_true", help="(default) Burst: auto-capture while you scroll; phash drops duplicates.")
    ap.add_argument("--single", action="store_true", help="Backup: analyse with the single agent instead of the multi-agent team (team is the default).")
    ap.add_argument("--sequential-team", action="store_true", dest="sequential_team", help="Run the team specialists one at a time (Coordinator loop) instead of the default parallel pipeline.")
    ap.add_argument("--idle-stop", type=float, default=BURST_IDLE_STOP, dest="idle_stop", help="Seconds of no on-screen change before a burst auto-stops; 0 = manual (end with Cmd+Shift+1).")
    ap.add_argument("--region", default=None, help="Capture only a screen sub-rectangle: \"L,T,W,H\" as fractions 0-1 (left,top,width,height).")
    ap.add_argument("--project-mode", action="store_true", dest="project_mode", help="Project mode: capture many files back-to-back; analysis runs in the background.")
    ap.add_argument("--program", default=None, help="Program slug: add each analysed file to that program's model.")
    ap.add_argument("--display", default=None, help="Display to capture: 1 = primary, 2 = second... (default: the one under the mouse).")
    ap.add_argument("--process-pending", action="store_true", dest="process_pending",
                    help="Analyse the program's saved-but-unanalysed captures, then exit (no hotkeys).")
    ap.add_argument("--capture-kind", default="code", choices=["code", "screen", "auto"], dest="capture_kind",
                    help="code (default) transcribes source; screen documents a running application screen.")
    args = ap.parse_args()
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (add it to .env).", file=sys.stderr)
        return 1

    try:
        import anthropic
        from pynput import keyboard
    except ImportError as exc:
        print(f"Missing dependency: {exc}.\nRun: pip install -r requirements.txt", file=sys.stderr)
        return 1

    app = App(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
    if args.classic:
        app.agent_mode = app.auto_mode = app.burst_mode = False
        mode = "CLASSIC (fixed pipeline)"
    elif args.agent:
        app.agent_mode = True; app.auto_mode = app.burst_mode = False
        mode = "AGENT (analyses at stop)"
    elif args.auto:
        app.auto_mode = True; app.agent_mode = app.burst_mode = False
        mode = "AUTO-AGENT (owned session)"
    else:  # default -> burst
        app.burst_mode = True; app.agent_mode = app.auto_mode = False
        mode = "BURST (auto-capture while scrolling)"
    app.team_mode = not args.single
    app.sequential_team = args.sequential_team
    app.idle_stop = args.idle_stop
    app.project_mode = args.project_mode or bool(args.program)
    app.program = args.program
    app.capture_kind = args.capture_kind
    app.display = args.display
    if app.program:
        attach_budget(app.tracker, app.program)
    if args.region:
        try:
            app.region = tuple(float(x) for x in args.region.split(","))
            assert len(app.region) == 4
        except Exception:
            print(f"Ignoring bad --region {args.region!r}", file=sys.stderr)
            app.region = None
    mode += " + SINGLE-AGENT (backup)" if args.single else " + TEAM (multi-agent, default)"
    if args.process_pending:
        n = app.process_pending() if app.program else 0
        print(f"[pending] analysed {n} saved capture(s).")
        return 0
    if app.program:
        threading.Thread(target=app._pending_loop, daemon=True).start()

    print(
        f"Screen Capture Tool — {mode}\n"
        "  Cmd+Shift+1  start a session\n"
        "  Cmd+Shift+7  next capture (after you scroll)   [owned session]\n"
        "  Cmd+Shift+2 / 8  capture full screen / region  [manual]\n"
        "  Cmd+Shift+9  quit\n"
        "[idle] Press Cmd+Shift+1 to start."
    )

    app.listener = keyboard.GlobalHotKeys({
        HK_TOGGLE: app.toggle,
        HK_FULL: app.on_full,
        HK_REGION: app.on_region,
        HK_QUIT: app.quit,
        HK_READY: app.ready,
    })
    app.listener.start()
    try:
        app.listener.join()  # block until quit stops the listener
    except KeyboardInterrupt:
        print("\n[quit] (Ctrl+C)")
        app._shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
