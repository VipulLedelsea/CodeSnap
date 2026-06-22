"""Milestone 3 — Hotkey-triggered capture (session model).

Runs in the background. You start a session, take as many screenshots as you
want with a hotkey, and on stop the whole batch is sent to Claude in ONE call
via multi_explain.analyse_images() — analysed as a single continuous document.
After analysis you're asked whether to save a Word report.

Hotkeys (global — work in any app):
  Cmd+Shift+1  start / stop session   (toggle: idle <-> running)
  Cmd+Shift+2  capture full screen    (while running; saves a PNG)
  Cmd+Shift+8  capture a region       (while running; drag-select, Esc cancels)
  Cmd+Shift+9  quit                   (or Ctrl+C in the terminal)

Flow:
  start  -> a fresh folder captures/session_<timestamp>/ is created
  2 / 8  -> each press saves an ordered PNG (001.png, 002.png, ...) — no API call
  stop   -> all PNGs go to Claude in one request; overview + extracted text
            print, then you're asked: save the report? If yes it is written to
            reports/report_<timestamp>.docx (a persistent folder, NOT the
            session folder).
  quit   -> if a session is still running it is analysed first (no lost work);
            then this run's whole session folders are DELETED. Saved reports
            live in reports/ and are never touched.

macOS permissions (System Settings -> Privacy & Security), granted to your
terminal app (Terminal / iTerm):
  - Input Monitoring + Accessibility   (for the global hotkey listener)
  - Screen Recording                   (for screen capture)
First run may do nothing until these are granted; restart the terminal after.

Run it:  python hotkey_capture.py
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Reuse the Milestone 2.5 brain: env loading, the one-call analyser, docx builder.
from multi_explain import load_env, analyse_images, build_docx

# Hotkey config. Avoid Cmd+Shift+3/4/5/6 — macOS reserves those for screenshots.
HK_TOGGLE = "<cmd>+<shift>+1"
HK_FULL = "<cmd>+<shift>+2"
HK_REGION = "<cmd>+<shift>+8"
HK_QUIT = "<cmd>+<shift>+9"

CAPTURES_ROOT = Path("captures")  # scratch PNGs (gitignored); deleted on quit
REPORTS_ROOT = Path("reports")    # persistent .docx reports; survive quit


def capture_full_png() -> bytes:
    """Full primary-screen capture via mss -> PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])  # [1] = primary display ([0] = all combined)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def capture_region_png() -> "bytes | None":
    """Interactive region capture via macOS `screencapture -i`.

    Native crosshair; user drags a box. Returns PNG bytes, or None if cancelled.
    """
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


class App:
    """Run state + API client. Hotkeys are wired to these methods."""

    def __init__(self, client):
        self.client = client
        self.running = False            # idle until a session is started
        self.session_dir = None         # current session's capture folder
        self.count = 0                  # captures taken this session
        self.sessions = []              # every session folder created this run
        self._busy = threading.Lock()   # serialises captures / analysis / cleanup
        self.listener = None            # set in main()

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
        # Do the (possibly slow) analyse + cleanup off the listener thread.
        threading.Thread(target=self._shutdown, daemon=True).start()

    # --- session lifecycle ---
    def _start_session(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = CAPTURES_ROOT / f"session_{ts}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.sessions.append(self.session_dir)
        self.count = 0
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
    def _do_capture(self, kind, session_dir):
        if not self._busy.acquire(blocking=False):
            print("(busy — finish the current capture/selection first)")
            return
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
            self.count += 1
            out = session_dir / f"{self.count:03d}.png"
            out.write_bytes(data)
            print(f"  saved capture {self.count}: {out.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"Capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            self._busy.release()

    def _finish(self, session_dir):
        # Analyse under the lock (waits for any capture in flight), then release
        # before the interactive prompt so the lock isn't held while we wait on input.
        with self._busy:
            imgs = sorted(session_dir.glob("*.png")) if session_dir else []
            if not imgs:
                print("[stopped] no captures in this session — nothing to analyse.")
                return
            print(f"Analysing {len(imgs)} capture(s) in one request...")
            try:
                result = analyse_images(self.client, imgs)
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
        # Never lose un-analysed work: if a session is still open, analyse it.
        if self.running:
            self.running = False
            self._finish(self.session_dir)

        with self._busy:
            removed = 0
            for d in self.sessions:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            # Drop captures/ entirely if it's now empty.
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
        "Screen Capture Tool - hotkey mode (session)\n"
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
        app._shutdown()  # synchronous: analyse pending, delete this run's folders
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
