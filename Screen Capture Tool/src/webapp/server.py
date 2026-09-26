"""Ledelsea — local web UI (Phase 1: branded shell + reports viewer).

Runs a local FastAPI server that serves the UI and lists saved reports.
Screen capture stays local; this is the control panel / viewer.

Run:  python -m webapp        (or: python webapp/server.py)
"""

from pathlib import Path

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from webapp.reports import scan_reports
from webapp.session import SessionManager
from core import status
from core.capture import capture_full_png
from core.outputs import save_report_bundle
from core.project import analyze_project

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
REPORTS = PROJECT / "reports"
PENDING = REPORTS / "pending"
STATIC = HERE / "static"

app = FastAPI(title="Ledelsea — CodeSnap")
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
def api_session_start(single: bool = False, idle_stop: float | None = None, region: str | None = None,
                      project_mode: bool = False, program: str | None = None):
    if program and not _program_exists(program):
        return JSONResponse({"error": f"Unknown program: {program}"}, status_code=404)
    started = _session.start(single=single, idle_stop=idle_stop, region=region, project_mode=project_mode,
                             program=program)
    return {"running": _session.running(), "started": started, "single": single,
            "idle_stop": idle_stop, "region": region, "project_mode": project_mode or bool(program),
            "program": program}


def _program_exists(slug: str) -> bool:
    from core.model import programs_root
    return bool(slug) and "/" not in slug and (programs_root() / slug / "program.db").exists()


def _open_program(slug: str):
    from core.model import ProgramStore
    if not _program_exists(slug):
        raise HTTPException(status_code=404, detail=f"Unknown program: {slug}")
    return ProgramStore.open(slug)


def _client():
    import os
    import anthropic
    from core import analysis
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="No API key set — add it in the app first.")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0)


def _artifact_summary(store, artifact: dict) -> dict:
    keep = ("id", "name", "artifact_type", "language", "version", "status", "validation_tool",
            "validation_ok", "validation_errors", "created", "updated")
    out = {k: artifact.get(k) for k in keep}
    out["entities"] = len(store._all("SELECT DISTINCT entity_id FROM entity_source WHERE artifact_id = ?",
                                     (artifact["id"],)))
    out["frames"] = len(store.artifact_evidence(artifact["id"]))
    out["cost"] = store.artifact_cost(artifact["id"])
    return out


@app.get("/api/programs")
def api_programs():
    from core.model import ProgramStore
    return {"programs": ProgramStore.list()}


@app.post("/api/programs")
def api_program_create(payload: dict = Body(...)):
    from core.model import ProgramStore
    name = str((payload or {}).get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Give the program a name."}, status_code=400)
    with ProgramStore.create(name, str(payload.get("description", "")).strip()) as store:
        return {"ok": True, "program": store.info}


@app.get("/api/programs/{slug}")
def api_program(slug: str):
    with _open_program(slug) as store:
        return {
            "program": store.info,
            "coverage": store.coverage(),
            "usage": store.usage(),
            "usage_by_step": store.usage_by_step()["steps"],
            "artifacts": [_artifact_summary(store, a) for a in store.artifacts()],
        }


@app.get("/api/programs/{slug}/artifacts/{artifact_id}")
def api_program_artifact(slug: str, artifact_id: int):
    with _open_program(slug) as store:
        artifact = store.artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        entities = store._all(
            "SELECT DISTINCT e.id, e.kind, e.name, e.key, e.line_start, e.line_end, e.origin FROM entity e "
            "JOIN entity_source s ON s.entity_id = e.id WHERE s.artifact_id = ? ORDER BY e.line_start",
            (artifact_id,),
        )
        evidence = [{"id": e["id"], "ord": e["ord"]} for e in store.artifact_evidence(artifact_id)]
        return {"artifact": artifact, "entities": entities, "evidence": evidence}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/rename")
def api_program_artifact_rename(slug: str, artifact_id: int, payload: dict = Body(...)):
    with _open_program(slug) as store:
        try:
            store.rename_artifact(artifact_id, str((payload or {}).get("name", "")))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return {"ok": True, "artifact": _artifact_summary(store, store.artifact(artifact_id))}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/reextract")
def api_program_artifact_reextract(slug: str, artifact_id: int):
    from core.model import ingest_artifact
    client = _client()
    with _open_program(slug) as store:
        if store.artifact(artifact_id) is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        try:
            counts = ingest_artifact(store, client, artifact_id)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Re-extraction failed: {exc}"}, status_code=500)
        return {"ok": True, **counts}


@app.get("/api/programs/{slug}/graph")
def api_program_graph(slug: str):
    from core.model import dependency_mermaid
    with _open_program(slug) as store:
        graph = store.graph()
        return {**graph, "mermaid": dependency_mermaid(graph)}


@app.get("/api/programs/{slug}/coverage")
def api_program_coverage(slug: str):
    with _open_program(slug) as store:
        return store.coverage()


@app.get("/api/programs/{slug}/export")
def api_program_export(slug: str):
    with _open_program(slug) as store:
        store.export()
        path = store.exports_dir / "program.json"
    return FileResponse(str(path), filename=f"{slug}.program.json", media_type="application/json")


@app.get("/api/programs/{slug}/evidence/{evidence_id}")
def api_program_evidence(slug: str, evidence_id: int):
    with _open_program(slug) as store:
        ev = store.evidence(evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="No such screenshot.")
    return FileResponse(ev["abs_path"])


@app.post("/api/programs/{slug}/import")
def api_program_import(slug: str, extract: bool = True):
    from core.model import import_reports
    client = _client() if extract else None
    with _open_program(slug) as store:
        try:
            imported = import_reports(store, [REPORTS, PENDING], client=client)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Import failed: {exc}"}, status_code=500)
        return {"ok": True, "imported": imported}


@app.get("/api/key/status")
def api_key_status():
    """Does the app have an Anthropic API key yet? (drives the first-run banner)"""
    import os
    from core import analysis
    analysis.load_env()
    return {"has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/key")
def api_key_set(value: str = ""):
    """Save the user's Anthropic key to ~/.codesnap/.env (found by the capture
    worker on launch) and this process's env. Local-only server, so this is fine."""
    import os
    key = (value or "").strip()
    if not (key.startswith("sk-ant") and len(key) > 20):
        return JSONResponse({"ok": False, "error": "That doesn't look like an Anthropic key (it should start with 'sk-ant')."}, status_code=400)
    cfg = Path.home() / ".codesnap"
    try:
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / ".env").write_text(f"ANTHROPIC_API_KEY={key}\n")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"Couldn't save: {exc}"}, status_code=500)
    os.environ["ANTHROPIC_API_KEY"] = key
    return {"ok": True}


@app.post("/api/reports/clear")
def api_reports_clear():
    """Delete all staged (pending) and saved reports from disk. Keeps the folders."""
    import time as _t
    def _unlink_retry(f, tries=8):
        for _ in range(tries):
            try:
                f.unlink(); return True
            except FileNotFoundError:
                return True
            except OSError:                 # iCloud "Resource deadlock avoided" — retry briefly
                _t.sleep(0.15)
        return False
    removed, failed = 0, 0
    for d in (PENDING, REPORTS):
        if d.exists():
            for f in list(d.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    if _unlink_retry(f): removed += 1
                    else: failed += 1
    return {"ok": failed == 0, "removed": removed, "failed": failed}


@app.post("/api/project/analyze")
def api_project_analyze(payload: dict = Body(...)):
    """Cross-file dependency analysis over selected captured files (project mode)."""
    import os
    from datetime import datetime
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if len(items) < 2:
        return JSONResponse({"error": "Pick at least 2 captured files to build a project map."}, status_code=400)
    lookup = {}
    for r in scan_reports(REPORTS) + scan_reports(PENDING):
        if r.get("kind") == "report" and r.get("code"):
            lookup[r["name"]] = r
    import re
    def _slug(x, default="File"):
        b = re.sub(r"[^A-Za-z0-9_]+", "_", (x or "").strip()).strip("_")
        return b or default
    def _unique(dirp, stem):
        cand, i = stem, 2
        while (dirp / f"{cand}.json").exists():
            cand = f"{stem}_{i}"; i += 1
        return cand

    files, picked = [], []
    for it in items:
        r = lookup.get((it or {}).get("report"))
        if r:
            fname = ((it.get("filename") or r.get("code_file") or r["name"]) or "").strip()
            files.append({"name": fname, "code": r["code"]})
            picked.append((r, fname))
    if len(files) < 2:
        return JSONResponse({"error": "Couldn't find code for the selected captures."}, status_code=400)

    from core import analysis
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"error": "No API key set — add it in the app first."}, status_code=400)
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0)
    try:
        report = analyze_project(client, files)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Project analysis failed: {exc}"}, status_code=500)

    # Rename each member's bundle on disk to its detected filename (e.g. calc.py),
    # so the file downloads/displays with a real name instead of report_<timestamp>.
    members = []
    for r, fname in picked:
        if "." in fname:
            base, ext = fname.rsplit(".", 1)
        else:
            base, ext = fname, (r.get("extension") or "txt")
        stem = _unique(REPORTS, _slug(base))
        new_name = r["name"]
        try:
            save_report_bundle({
                "language": r.get("language", ""), "overview": r.get("overview", ""),
                "errors": r.get("errors", ""), "tech_stack": r.get("tech_stack", ""),
                "diagrams": r.get("diagrams", ""), "extension": ext, "code": r.get("code", ""),
            }, REPORTS, stem)
            for base_dir in (REPORTS, PENDING):          # remove the old report_<ts> bundle
                for fp in (base_dir / f"{r['name']}.json", base_dir / (r.get("code_file") or "_")):
                    try:
                        if fp.name and fp.name != "_" and fp.exists():
                            fp.unlink()
                    except Exception:  # noqa: BLE001
                        pass
            new_name = stem
        except Exception:  # noqa: BLE001
            pass
        members.append({"name": new_name, "filename": fname})
    report["members"] = members

    # Name the project report after what it is, e.g. ProjectReport_Calculator.
    pname = _slug(report.get("project_name", ""), "")
    base_name = "ProjectReport_" + pname if pname else "ProjectReport_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    name = _unique(REPORTS, base_name)
    try:
        save_report_bundle(report, REPORTS, name)   # finished deliverable -> Recent results
    except Exception:  # noqa: BLE001 - still return it even if the save hiccups
        pass
    return {"ok": True, "name": name, "report": report}


@app.post("/api/report/docx")
def api_report_docx_post(payload: dict = Body(...)):
    """Build a Word report including rendered diagram images (dev browser path)."""
    name = (payload or {}).get("name", "")
    images = (payload or {}).get("images") or []
    rep = next((r for r in scan_reports(REPORTS) + scan_reports(PENDING)
                if r.get("kind") == "report" and r.get("name") == name), None)
    if not rep:
        return JSONResponse({"error": "not found"}, status_code=404)
    import tempfile
    from core.outputs import report_docx
    tmp = Path(tempfile.mkdtemp()) / f"{name}.docx"
    report_docx(rep, tmp, images)
    return FileResponse(str(tmp), filename=f"{name}.docx")


@app.get("/api/report/docx/{name}")
def api_report_docx(name: str):
    """Build a Word (.docx) report for a saved/pending report and serve it (dev browser)."""
    if "/" in name or "\\" in name or name.startswith("."):
        return JSONResponse({"error": "bad name"}, status_code=400)
    rep = next((r for r in scan_reports(REPORTS) + scan_reports(PENDING)
                if r.get("kind") == "report" and r.get("name") == name), None)
    if not rep:
        return JSONResponse({"error": "not found"}, status_code=404)
    import tempfile
    from core.outputs import report_docx
    tmp = Path(tempfile.mkdtemp()) / f"{name}.docx"
    report_docx(rep, tmp)
    return FileResponse(str(tmp), filename=f"{name}.docx")


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
            _notify("CodeSnap", "Screenshot taken — switch back to draw the code box.")
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
            print(f"CodeSnap running (native window) at {url}")

            class _JsApi:
                def __init__(self):
                    self.window = None

                def save_report_docx(self, name, images=None):
                    """Build a Word report and save it via the native dialog (real download)."""
                    try:
                        rep = next((r for r in scan_reports(REPORTS) + scan_reports(PENDING)
                                    if r.get("kind") == "report" and r.get("name") == name), None)
                        if not rep:
                            return False
                        import tempfile, shutil
                        from core.outputs import report_docx
                        tmp = Path(tempfile.mkdtemp()) / (name + ".docx")
                        report_docx(rep, tmp, images)
                        dest = self.window.create_file_dialog(getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG, save_filename=name + ".docx")
                        if not dest:
                            return False
                        dest = dest if isinstance(dest, str) else dest[0]
                        shutil.copy(str(tmp), dest)
                        return True
                    except Exception:  # noqa: BLE001
                        return False

                def save_text(self, filename, content):
                    """Native Save dialog + write — real 'download' inside the app window."""
                    try:
                        dest = self.window.create_file_dialog(
                            getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG, save_filename=filename or "download.txt")
                        if not dest:
                            return False
                        path = dest if isinstance(dest, str) else dest[0]
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(content or "")
                        return True
                    except Exception:  # noqa: BLE001
                        return False

            _api = _JsApi()
            win = webview.create_window("CodeSnap", url, width=1200, height=840,
                                        min_size=(940, 620), js_api=_api)
            _api.window = win
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
