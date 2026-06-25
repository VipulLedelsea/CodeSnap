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
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Analysis engine: env loading, background per-image extraction + cache, the
# incremental analyser (cache hits + one overview call), and the docx builder.
from analysis import load_env, extract_to_cache, analyse_incremental, build_docx

# Hotkey config. Avoid Cmd+Shift+3/4/5/6 — macOS reserves those for screenshots.
HK_TOGGLE = "<cmd>+<shift>+1"
HK_FULL = "<cmd>+<shift>+2"
HK_REGION = "<cmd>+<shift>+8"
HK_QUIT = "<cmd>+<shift>+9"

CAPTURES_ROOT = Path("captures")  # scratch PNGs (gitignored); deleted on quit
REPORTS_ROOT = Path("reports")    # persistent .docx reports; survive quit
BG_WORKERS = 3                    # how many images to read concurrently
DUP_THRESHOLD = 3                 # perceptual-hash distance treated as a near-duplicate

# Uses the MSS library for full-screen capture (cross-platform) and macOS's native
# screencapture for region capture (native crosshair). Both return PNG bytes.
def capture_full_png() -> bytes:
    """Full primary-screen capture via mss -> PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1]) 
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# Uses macOS's native screencapture for region capture (crosshair). Returns PNG bytes or None if cancelled.
def capture_region_png() -> "bytes | None":

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    subprocess.run(["screencapture", "-i", "-x", path])  # -i interactive, -x silent
    try:
        if os.path.getsize(path) == 0:
            return None  # cancelled — screencapture wrote nothing
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


#Hashing of images for near-duplicate detection. If difference is below a threshold, the capture is skipped.
def _phash(data: bytes):
    try:
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(io.BytesIO(data)))
    except Exception:  # noqa: BLE001 - dedup is best-effort; never block a capture
        return None


class App:
    """Run state + API client + background reader pool."""

    def __init__(self, client):
        self.client = client
        self.running = False                      # idle until a session is started
        self.session_dir = None                   # current session's capture folder
        self.count = 0                            # captures taken this session
        self._last_phash = None                   # for near-duplicate detection
        self.sessions = []                        # every session folder this run
        self._capture_lock = threading.Lock()     # serialises the actual screen grab
        self._analysis_lock = threading.Lock()    # serialises stop/quit analysis
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=BG_WORKERS)
        self._futures = []                         # pending background reads
        self._fut_lock = threading.Lock()
        self.listener = None                       # set in main()

    # --- hotkey handlers: run on the listener thread; keep them light ---
    def toggle(self):
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

    # --- session lifecycle ---
    def _start_session(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = CAPTURES_ROOT / f"session_{ts}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.sessions.append(self.session_dir)
        self.count = 0
        self._last_phash = None
        self.running = True
        print(f"\n[running] session: {self.session_dir.resolve()}")
        print("  Cmd+Shift+2 = full screen, Cmd+Shift+8 = region, Cmd+Shift+1 = stop & analyse.")

    def _stop_session(self):
        self.running = False
        session_dir = self.session_dir
        print("\n[stopped] wrapping up session...")
        threading.Thread(target=self._analyse_then_idle, args=(session_dir,), daemon=True).start()

    def _analyse_then_idle(self, session_dir):
        self._finish(session_dir)
        print("\n[idle] Cmd+Shift+1 to start a new session, Cmd+Shift+9 to quit.")

    def _capture(self, kind):
        if not self.running:
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
            ph = _phash(data)
            if ph is not None and self._last_phash is not None and (ph - self._last_phash) <= DUP_THRESHOLD:
                print("  near-duplicate of the previous capture — skipped")
                return
            if ph is not None:
                self._last_phash = ph
            self.count += 1
            out = session_dir / f"{self.count:03d}.png"
            out.write_bytes(data)
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

        answer = input("\nSave report to a Word document? [y/n]: ").strip().lower()
        if answer != "y":
            print("No report saved.")
            return
        try:
            REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
            ts = session_dir.name.replace("session_", "")
            out = REPORTS_ROOT / f"report_{ts}.docx"
            build_docx(result).save(out)
            print(f"Saved report: {out.resolve()}")
        except Exception as exc:  # noqa: BLE001
            print(f"(could not save docx: {type(exc).__name__}: {exc})", file=sys.stderr)

    # --- shutdown: analyse a pending session, delete this run's folders, exit ---
    def _shutdown(self):
        print("\n[quit] wrapping up...")
        if self.running:
            self.running = False
            self._finish(self.session_dir)

        # Stop accepting/await background reads before deleting anything.
        self._pool.shutdown(wait=True, cancel_futures=True)

        with self._analysis_lock:
            removed = 0
            for d in self.sessions:
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

    app = App(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]))

    print(
        "Screen Capture Tool - hotkey mode (background reads)\n"
        "  Cmd+Shift+1  start / stop session\n"
        "  Cmd+Shift+2  capture full screen\n"
        "  Cmd+Shift+8  capture region\n"
        "  Cmd+Shift+9  quit  (analyses a pending session, deletes this run's folders)\n"
        "[idle] Press Cmd+Shift+1 to start a session."
    )

    app.listener = keyboard.GlobalHotKeys({
        HK_TOGGLE: app.toggle,
        HK_FULL: app.on_full,
        HK_REGION: app.on_region,
        HK_QUIT: app.quit,
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
