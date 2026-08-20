"""Ledelsea — local web UI (Phase 1: branded shell + reports viewer).

Runs a local FastAPI server that serves the UI and lists saved reports.
Screen capture stays local; this is the control panel / viewer.

Run:  python -m webapp        (or: python webapp/server.py)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from webapp.reports import scan_reports
from webapp.session import SessionManager
from core import status
from core.capture import capture_full_png

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
REPORTS = PROJECT / "reports"
PENDING = REPORTS / "pending"
STATIC = HERE / "static"

app = FastAPI(title="Ledelsea — Code Capture")
_session = SessionManager()
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    # Serve the UI assets uncached so edits show up on a normal refresh
    # (no more "restart + hard-refresh" to see new frontend code).
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.get("/", response_class=HTMLResponse)
def index():
    # Stamp asset URLs with the files' mtime so the browser always fetches the
    # current app.js / styles.css (no stale-cache after edits, no hard-refresh).
    html = (STATIC / "index.html").read_text()
    try:
        v = str(int(max((STATIC / "app.js").stat().st_mtime,
                        (STATIC / "styles.css").stat().st_mtime)))
    except OSError:
        v = "0"
    html = html.replace("/static/app.js", f"/static/app.js?v={v}")
    html = html.replace("/static/styles.css", f"/static/styles.css?v={v}")
    return html


@app.get("/api/reports")
def api_reports():
    return {"reports": scan_reports(REPORTS)}


@app.get("/api/download/{name}")
def api_download(name: str):
    # no path traversal: only a bare filename inside reports/
    if "/" in name or "\\" in name or name.startswith("."):
        return JSONResponse({"error": "bad name"}, status_code=400)
    target = (REPORTS / name).resolve()
    if target.parent != REPORTS.resolve() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target), filename=name)


@app.get("/api/pending")
def api_pending():
    # Reports staged by auto/burst sessions, not yet saved. Downloadable on demand.
    return {"reports": scan_reports(PENDING)}


@app.get("/api/pending/download/{name}")
def api_pending_download(name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        return JSONResponse({"error": "bad name"}, status_code=400)
    import json
    import shutil
    src_json = (PENDING / f"{name}.json").resolve()
    if src_json.parent != PENDING.resolve() or not src_json.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    meta = json.loads(src_json.read_text())
    REPORTS.mkdir(parents=True, exist_ok=True)
    # promote (save) the bundle from pending/ into reports/, then serve the code file
    dst_json = REPORTS / src_json.name
    shutil.move(str(src_json), str(dst_json))
    served = dst_json
    code_file = meta.get("code_file", "")
    if code_file:
        src_code = PENDING / code_file
        if src_code.is_file():
            dst_code = REPORTS / code_file
            shutil.move(str(src_code), str(dst_code))
            served = dst_code
    return FileResponse(str(served), filename=served.name)


@app.post("/api/session/start")
def api_session_start(single: bool = False, idle_stop: float | None = None, region: str | None = None):
    started = _session.start(single=single, idle_stop=idle_stop, region=region)
    return {"running": _session.running(), "started": started, "single": single,
            "idle_stop": idle_stop, "region": region}


@app.get("/api/key/status")
def api_key_status():
    """Does the app have an Anthropic API key yet? (drives the first-run banner)"""
    import os
    from core import analysis
    analysis.load_env()
    return {"has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/key")
def api_key_set(value: str = ""):
    """Save the user's Anthropic key to ~/.code_capture/.env (found by the capture
    worker on launch) and this process's env. Local-only server, so this is fine."""
    import os
    key = (value or "").strip()
    if not (key.startswith("sk-ant") and len(key) > 20):
        return JSONResponse({"ok": False, "error": "That doesn't look like an Anthropic key (it should start with 'sk-ant')."}, status_code=400)
    cfg = Path.home() / ".code_capture"
    try:
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text(f"ANTHROPIC_API_KEY={key}\n")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"Couldn't save: {exc}"}, status_code=500)
    os.environ["ANTHROPIC_API_KEY"] = key
    return {"ok": True}


@app.get("/api/screen.png")
def api_screen(delay: float = 0.0, notify: bool = False):
    """One full screenshot, for the 'pick code area' picker. Optional delay lets the
    user bring their code to the front first; notify pings the desktop when done."""
    import time as _t
    if delay > 0:
        _t.sleep(min(delay, 10.0))
    try:
        png = capture_full_png()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
    if notify:
        try:
            from core.notify import notify as _notify
            _notify("Code Capture", "Screenshot taken — switch back to draw the code box.")
        except Exception:  # noqa: BLE001 - notification is optional
            pass
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/stop")
def api_session_stop():
    _session.stop()
    return {"running": _session.running()}


@app.get("/api/session/status")
def api_session_status():
    return {"running": _session.running(), "events": status.recent()}


def _serve_in_thread(host="127.0.0.1", port=8000):
    """Run uvicorn in a background daemon thread (signal handlers off, since those
    only work on the main thread). Returns once the thread is started."""
    import threading
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, daemon=True).start()
    return server


def _wait_until_up(url, timeout=15.0):
    import time
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    return False


def main():
    """Boot the local server, then show the UI. In the packaged .app this opens a
    NATIVE window (pywebview); in dev it opens your browser. Flags: --native forces
    the window, --browser forces the browser."""
    import sys
    url = "http://127.0.0.1:8000"
    _serve_in_thread()
    if not _wait_until_up(url):
        print("Server failed to start.", file=sys.stderr)
        return 1

    frozen = getattr(sys, "frozen", False)
    want_native = ("--native" in sys.argv) or (frozen and "--browser" not in sys.argv)
    if want_native:
        try:
            import webview
            print(f"Code Capture running (native window) at {url}")
            win = webview.create_window("Code Capture", url, width=1200, height=840,
                                        min_size=(940, 620))
            try:
                win.events.closed += lambda: _session.stop()   # tidy up a running capture
            except Exception:  # noqa: BLE001
                pass
            webview.start()      # blocks on the main thread until the window is closed
            return 0
        except Exception as exc:  # noqa: BLE001 - fall back to the browser
            print(f"(native window unavailable: {exc}; opening browser instead)", file=sys.stderr)

    import webbrowser
    webbrowser.open(url)
    print(f"Ledelsea UI running at {url}  (Ctrl+C to stop)")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    main()
