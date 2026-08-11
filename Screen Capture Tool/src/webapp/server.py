"""Ledelsea — local web UI (Phase 1: branded shell + reports viewer).

Runs a local FastAPI server that serves the UI and lists saved reports.
Screen capture stays local; this is the control panel / viewer.

Run:  python -m webapp        (or: python webapp/server.py)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.reports import scan_reports
from webapp.session import SessionManager
from core import status

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
def api_session_start(single: bool = False):
    started = _session.start(single=single)
    return {"running": _session.running(), "started": started, "single": single}


@app.post("/api/session/stop")
def api_session_stop():
    _session.stop()
    return {"running": _session.running()}


@app.get("/api/session/status")
def api_session_status():
    return {"running": _session.running(), "events": status.recent()}


def main():
    import threading
    import webbrowser
    import uvicorn
    url = "http://127.0.0.1:8000"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Ledelsea UI running at {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
