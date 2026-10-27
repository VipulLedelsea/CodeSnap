"""Ledelsea — local web UI (Phase 1: branded shell + reports viewer).

Runs a local FastAPI server that serves the UI and lists saved reports.
Screen capture stays local; this is the control panel / viewer.

Run:  python -m webapp        (or: python webapp/server.py)
"""

import hmac
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from webapp.reports import scan_reports
from webapp.session import SessionManager
from core import status
from core.capture import capture_full_png
from core.outputs import save_report_bundle
from core.project import analyze_project

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
from core.paths import captures_dir, reports_dir  # noqa: E402

REPORTS = reports_dir()
PENDING = REPORTS / "pending"
STATIC = HERE / "static"

log = logging.getLogger("codesnap.webapp")

app = FastAPI(title="Ledelsea — CodeSnap")
_session = SessionManager()
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# ── Request guard: Host allow-list, same-origin check and a per-launch token ──
# The server only listens on loopback, but any web page the user visits can still
# fire requests at it (CSRF) or rebind its own DNS name to 127.0.0.1. So: only
# loopback Host names are served, browser-originated writes must be same-origin and
# carry the random token that is embedded in the page we serve at "/".
CSRF_TOKEN = secrets.token_urlsafe(32)
CSRF_HEADER = "x-codesnap-token"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Browser requests (Origin / Sec-Fetch-Site present) always need the token. Plain
# non-browser clients (curl, tests) can't be driven by a hostile web page, so they
# only need it when CODESNAP_REQUIRE_TOKEN=1.
_REQUIRE_TOKEN_ALWAYS = os.environ.get("CODESNAP_REQUIRE_TOKEN") == "1"


def allow_host(host: str) -> None:
    """Allow an extra bound host name (e.g. when serving on a non-default interface)."""
    if host:
        _ALLOWED_HOSTS.add(host.lower())
        _ALLOWED_HOSTS.add(f"[{host.lower()}]" if ":" in host else host.lower())


def _host_only(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.split(":")[0]


def _forbidden(message: str, code: int = 403):
    return JSONResponse({"error": message}, status_code=code)


@app.middleware("http")
async def request_guard(request, call_next):
    host_header = request.headers.get("host", "")
    if _host_only(host_header) not in _ALLOWED_HOSTS:
        return _forbidden("Host not allowed", 400)
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site")
        if origin is not None and (origin == "null" or urlparse(origin).netloc.lower() != host_header.strip().lower()):
            return _forbidden("Cross-origin request blocked")
        if site is not None and site not in ("same-origin", "none"):
            return _forbidden("Cross-origin request blocked")
        if origin is not None or site is not None or _REQUIRE_TOKEN_ALWAYS:
            sent = request.headers.get(CSRF_HEADER, "")
            if not hmac.compare_digest(sent.encode(), CSRF_TOKEN.encode()):
                return _forbidden("Missing or invalid session token")
    return await call_next(request)


def _plain_filename(name) -> str | None:
    """A bare file name (no directories, no dot-files, no NULs) or None."""
    if not isinstance(name, str) or not name or name != name.strip():
        return None
    if "/" in name or "\\" in name or "\0" in name or name.startswith(".") or name in (".", ".."):
        return None
    if Path(name).name != name:
        return None
    return name


def _file_in(base: Path, name) -> Path | None:
    """Resolve `name` inside `base`; None unless it is a plain filename that stays in `base`."""
    plain = _plain_filename(name)
    if plain is None:
        return None
    target = (base / plain).resolve()
    return target if target.parent == base.resolve() else None


def _cleanup_tmp(directory: Path) -> BackgroundTask:
    return BackgroundTask(shutil.rmtree, str(directory), ignore_errors=True)


@app.middleware("http")
async def no_cache(request, call_next):
    # Serve the UI assets uncached so edits show up on a normal refresh
    # (no more "restart + hard-refresh" to see new frontend code).
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _account_name() -> str:
    """The first name of whoever is signed in to this Mac (shown in the sidebar), or their account name."""
    import getpass
    try:
        import pwd
        full = (pwd.getpwuid(os.getuid()).pw_gecos or "").split(",")[0].strip()
    except Exception:  # noqa: BLE001
        full = ""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = ""
    return (full.split()[0] if full else user) or "You"


def _html_escape(text: str) -> str:
    import html as _h
    return _h.escape(text, quote=True)


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
    html = html.replace("__CODESNAP_TOKEN__", CSRF_TOKEN)
    name = _account_name()
    html = html.replace("__CODESNAP_USER__", _html_escape(name)).replace("__CODESNAP_INITIAL__", _html_escape(name[:1].upper() or "?"))
    return html


@app.get("/api/reports")
def api_reports():
    return {"reports": scan_reports(REPORTS)}


@app.get("/api/download/{name}")
def api_download(name: str):
    # no path traversal: only a bare filename inside reports/
    if _plain_filename(name) is None:
        return JSONResponse({"error": "bad name"}, status_code=400)
    target = _file_in(REPORTS, name)
    if target is None or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target), filename=name)


@app.get("/api/pending")
def api_pending():
    # Reports staged by auto/burst sessions, not yet saved. Downloadable on demand.
    return {"reports": scan_reports(PENDING)}


def _pending_bundle(name: str):
    """(json path, meta, code path or None) for a staged report; raises HTTPException."""
    import json
    if _plain_filename(name) is None:
        raise HTTPException(status_code=400, detail="bad name")
    src_json = _file_in(PENDING, f"{name}.json")
    if src_json is None or not src_json.is_file():
        raise HTTPException(status_code=404, detail="not found")
    meta = json.loads(src_json.read_text())
    code_file = (meta or {}).get("code_file", "")
    src_code = _file_in(PENDING, code_file) if code_file else None
    if code_file and src_code is None:
        raise HTTPException(status_code=400, detail="bad code file name in report")
    return src_json, src_code


@app.get("/api/pending/download/{name}")
def api_pending_download(name: str):
    """Read-only: serve a staged report's code file (or its json) without saving it."""
    try:
        src_json, src_code = _pending_bundle(name)
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    served = src_code if src_code is not None and src_code.is_file() else src_json
    return FileResponse(str(served), filename=served.name)


@app.post("/api/pending/download/{name}")
def api_pending_promote(name: str):
    """Promote (save) a staged bundle from pending/ into reports/, then serve its code file."""
    try:
        src_json, src_code = _pending_bundle(name)
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    REPORTS.mkdir(parents=True, exist_ok=True)
    dst_json = REPORTS / src_json.name
    shutil.move(str(src_json), str(dst_json))
    served = dst_json
    if src_code is not None and src_code.is_file():
        dst_code = _file_in(REPORTS, src_code.name)
        if dst_code is not None:
            shutil.move(str(src_code), str(dst_code))
            served = dst_code
    return FileResponse(str(served), filename=served.name)


@app.post("/api/session/start")
def api_session_start(single: bool = False, idle_stop: float | None = None, region: str | None = None,
                      project_mode: bool = False, program: str | None = None, capture_kind: str = "code",
                      display: str | None = None, confirm: bool = False):
    if program and not _program_exists(program):
        return JSONResponse({"error": f"Unknown program: {program}"}, status_code=404)
    if capture_kind not in ("code", "screen", "auto"):
        return JSONResponse({"error": "capture_kind must be auto, code or screen"}, status_code=400)
    if program:
        from core.usage import program_budget
        with _open_program(program) as store:
            limit, spent = program_budget(store), store.usage()["cost"]
        if limit and spent >= limit:
            return JSONResponse({"error": f"API budget reached for this program (${spent:.2f} of ${limit:.2f}). "
                                          f"Raise the budget to keep capturing."}, status_code=402)
    # a capture only holds back analysis of its own program, so only that program needs the warning
    busy = [] if confirm or _session.running() or not program else [p for p in _programs_being_analysed() if p == program]
    if busy:
        return JSONResponse({"error": "Analysis is running for " + ", ".join(busy) + ". A capture holds it until the capture "
                                      "ends. Start the capture anyway?", "needs_confirm": True, "busy": busy}, status_code=409)
    try:
        started = _session.start(single=single, idle_stop=idle_stop, region=region, project_mode=project_mode,
                                 program=program, capture_kind=capture_kind, display=display)
        api_session_kind(capture_kind)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail='Pick a valid screen and capture area.')
    return {"running": _session.running(), "started": started, "single": single,
            "idle_stop": idle_stop, "region": region, "project_mode": project_mode or bool(program),
            "program": program, "capture_kind": capture_kind}


_SPACING_REFERENCE = {}


@app.get('/api/session/settings')
def api_session_settings_get():
    return _session.saved()


@app.post('/api/session/settings')
def api_session_settings(payload: dict = Body(...)):
    try:
        from webapp.session import capture_settings
        from core.spacing import profile
        cfg=capture_settings(payload.get('region'),payload.get('display'))
        if payload.get('spacing_origin') is not None:
            if (payload.get('spacing_reference')!=_SPACING_REFERENCE.get('id') or
                    cfg['display']!=_SPACING_REFERENCE.get('display')):
                raise ValueError('Retake the screenshot before setting the source margin.')
            cal=profile(_SPACING_REFERENCE['data'],cfg['region'],payload['spacing_origin'])
            settings=_session.configure(cfg['region'],cfg['display'],spacing=cal)
        elif payload.get('clear_spacing'):
            settings=_session.configure(cfg['region'],cfg['display'],spacing=None)
        else:
            settings = _session.configure(cfg['region'],cfg['display'])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {'ok': True, 'applies': 'now' if _session.running() else 'next_capture', **settings}


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


def _program_client(slug):
    from core.usage import program_client, SavedBudget, UsageTracker, BudgetExceeded
    try:
        SavedBudget(slug).check(UsageTracker())
        return program_client(slug, _client())
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))


def _artifact_summary(store, artifact: dict) -> dict:
    keep = ("id", "name", "artifact_type", "language", "version", "status", "validation_tool",
            "validation_ok", "validation_errors", "created", "updated")
    out = {k: artifact.get(k) for k in keep}
    out["entities"] = len(store._all("SELECT DISTINCT entity_id FROM entity_source WHERE artifact_id = ?",
                                     (artifact["id"],)))
    out["frames"] = len(store.artifact_evidence(artifact["id"]))
    pend = store.pending_captures().get(artifact["id"])
    if pend:
        out["pending"] = {k: pend.get(k) for k in ("kind", "error", "recapture_of", "attempts", "paused")}
        if artifact["status"] == "captured":
            out["pending"].update(store.capture_progress(artifact["id"]))
    out["cost"] = store.artifact_cost(artifact["id"])
    v = store.verification(artifact["id"])
    if v and artifact["status"] != "captured":
        out["check"] = {k: v.get(k) for k in ("lines", "verified", "reread", "confirmed", "manual", "flagged", "unchecked", "gaps")}
    from core import deepdive
    q = None
    if artifact["status"] != "captured" and (artifact.get("transcription") or "").strip():
        dd = (store.get_meta("deepdive") or {}).get(str(artifact["id"])) or {}
        q = deepdive.capture_quality(store, artifact, deepdive.current_concerns(store, artifact))
        out["quality"] = {"status": q["status"], "issues": q["issues"]}
        if dd:
            out["deep"] = {"facts": len(dd.get("facts") or []), "current": dd.get("hash") == deepdive._hash(artifact.get("transcription"))}
        out["recapture"] = deepdive.recapture_outcome(store, artifact, q)
    out["state"] = deepdive.file_state(store, artifact, q)
    if out["state"] == "done" and _review_in_progress(store, artifact):
        out["state"] = "reviewing"
    rebuilding = _REBUILDS.get(store.info["slug"])
    if rebuilding and rebuilding["name"] == artifact["name"]:
        out["state"] = "reading"
        out["rebuild"] = dict(rebuilding)
    return out


def _review_in_progress(store, artifact) -> bool:
    """A file is not done while the program's analysis is still running and it has not been through it: a folder being
    added, a deep review or batch pipeline that has not reached this file, or the cross-file stage that follows the last
    file. Between model calls no file is marked active, so without this every file reads done during those gaps."""
    from core import deepdive
    slug = store.info["slug"]
    running = bool((_DEEP.get(slug) or {}).get("running") or (_FOLDER_JOBS.get(slug) or {}).get("running")
                   or (store.get_meta("pipeline_job") or {}).get("state") == "running")
    if not running:
        return False
    dd = (store.get_meta("deepdive") or {}).get(str(artifact["id"])) or {}
    if dd.get("hash") != deepdive._hash(artifact.get("transcription")):
        return True
    return deepdive.program_stale(store) or not store.get_meta("deepdive_program")


def _progress(arts: list) -> dict:
    """Files, not captures: a recapture in progress counts against the file it replaces."""
    names = {a["name"] for a in arts if not (a.get("pending") or {}).get("recapture_of")}
    by_file = {}
    for a in sorted(arts, key=lambda a: bool((a.get("pending") or {}).get("recapture_of"))):
        key = (a.get("pending") or {}).get("recapture_of") or a["name"]
        if key not in names:
            names.add(key)
        cur = by_file.get(key)
        busy = a["state"] in ("waiting", "reading", "reviewing")
        if cur is None or busy or (a.get("pending") or {}).get("recapture_of"):
            by_file[key] = a["state"]
    c = {k: sum(1 for v in by_file.values() if v == k) for k in ("done", "needs_recapture", "failed", "waiting", "reading", "reviewing", "paused")}
    total = len(by_file)
    finished = c["done"] + c["needs_recapture"] + c["failed"]
    return {"total": total, "finished": finished, "to_go": total - finished, **c,
            "pct": round(100 * finished / total) if total else 0}


_DEEP = {}
_DEEP_QUEUE = {}    # slug -> ids of corrected files waiting for the running review to end
_REBUILDS = {}
_JOB_LOCK = threading.RLock()      # guards check-and-register on _DEEP / _REBUILDS
_REBUILD_LOCK = _JOB_LOCK


def _deep_start(slug: str, artifact_ids=None) -> dict:
    """Run the deep code analysis for every file that needs it, in the background (one job per program)."""
    from core import deepdive
    job = _DEEP.get(slug)
    if job and job.get("running"):
        return job
    if slug in _REBUILDS:
        raise HTTPException(status_code=409, detail="Wait for the saved capture rebuild to finish before reviewing.")
    client = _program_client(slug)
    with _open_program(slug) as store:
        total = len(artifact_ids) if artifact_ids else len(deepdive.pending(store)) or int(deepdive.program_stale(store))
        # going into analysis ends the person's review of these files: what the reviewer finds next is a note, not a new question
        # (bookkeeping only: it must never stop the analysis from starting)
        try:
            deepdive.close_review(store, artifact_ids or [a["id"] if isinstance(a, dict) else a for a in deepdive.pending(store)])
        except Exception:  # noqa: BLE001
            pass
    with _JOB_LOCK:   # re-check and register atomically: two requests must not both start a job
        job = _DEEP.get(slug)
        if job and job.get("running"):
            return job
        if slug in _REBUILDS:
            raise HTTPException(status_code=409, detail="Wait for the saved capture rebuild to finish before reviewing.")
        job = {"running": True, "done": 0, "total": total, "errors": [], "started": time.time()}
        _DEEP[slug] = job

    def work():
        from core.model import ProgramStore
        from core import slots
        try:
            with slots.slot(slug), ProgramStore.open(slug) as st:
                from core import pipeline
                if pipeline.staged() and not artifact_ids:
                    res = pipeline.run_staged(st, client, progress=lambda d, t: job.update(done=d, total=t))
                else:
                    res = deepdive.run(st, client, artifact_ids=artifact_ids, force=bool(artifact_ids),
                                       progress=lambda d, t: job.update(done=d, total=t))
                job["errors"] = res["errors"]
        except Exception as exc:  # noqa: BLE001
            job["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            job["running"] = False
            job["finished"] = time.time()
            _deep_drain(slug)
    threading.Thread(target=work, daemon=True).start()
    return job


def _pipeline_running(slug: str) -> bool:
    """True while the batch pipeline (another process) is analysing this program. A run that has not moved for 12 hours is
    treated as dead."""
    try:
        with _open_program(slug) as store:
            job = store.get_meta("pipeline_job") or {}
        if job.get("state") != "running":
            return False
        began = time.mktime(time.strptime(job.get("updated") or job.get("started"), "%Y-%m-%dT%H:%M:%S"))
        return time.time() - began < 12 * 3600
    except Exception:  # noqa: BLE001
        return False


def _deep_watch(slug: str, every: float = 90.0):
    """Look again soon: the corrected files in the queue are reviewed once nothing else is being reviewed."""
    def look():
        if not _DEEP_QUEUE.get(slug):
            return
        if (_DEEP.get(slug) or {}).get("running") or _pipeline_running(slug):
            _deep_watch(slug, every)
        else:
            _deep_drain(slug)
    timer = threading.Timer(every, look)
    timer.daemon = True
    timer.start()


def _deep_drain(slug: str):
    """Files corrected by the user while a review was running are reviewed once it ends (only those still out of date)."""
    ids = _DEEP_QUEUE.pop(slug, None)
    if not ids:
        return
    try:
        from core import deepdive
        with _open_program(slug) as store:
            todo = [a["id"] for a in deepdive.pending(store) if a["id"] in ids]
        if todo:
            _deep_start(slug, todo)
    except Exception:  # noqa: BLE001
        pass


def _deep_when_ready(slug: str, artifact_id: int | None = None):
    """Review a file as soon as its own open problems are resolved (runs after the answering request ends). With no file
    given, review everything out of date once no file has an open problem. While a review is running the file waits in
    a queue and is reviewed when that run ends."""
    def go():
        try:
            from core import deepdive
            if slug in _REBUILDS or not api_key_status()["has_key"]:
                return
            from core.model.line_review import items
            from core import batching
            file_id = None if batching.enabled() else artifact_id    # batch: stop for attention, then run the rest as one batch
            if file_id is not None:
                with _open_program(slug) as store:
                    art = store.artifact(file_id)
                    if not art or not art.get("is_current", 1) or items(store, art):
                        return
                    if not any(a["id"] == file_id for a in deepdive.pending(store)):
                        return
                with _JOB_LOCK:
                    if (_DEEP.get(slug) or {}).get("running") or _pipeline_running(slug):
                        _DEEP_QUEUE.setdefault(slug, set()).add(file_id)
                        _deep_watch(slug)
                        return
                _deep_start(slug, [file_id])
                return
            if (_DEEP.get(slug) or {}).get("running"):
                return
            with _open_program(slug) as store:
                if any(store.capture_progress(a["id"]).get("analysing") for a in store.artifacts()):
                    return
                def has_questions(a):
                    try:
                        return bool(a.get("is_current", 1)) and bool(items(store, a))
                    except Exception:  # noqa: BLE001
                        return False
                if any(has_questions(a) for a in store.artifacts()):
                    return
                todo = deepdive.pending(store)
            if todo:
                _deep_start(slug)
        except Exception:  # noqa: BLE001
            pass
    timer = threading.Timer(1.0, go)
    timer.daemon = True
    timer.start()


@app.post("/api/programs/{slug}/deepdive")
def api_program_deepdive(slug: str, artifact_id: int | None = None):
    """Start (or restart for one file) the deep, evidence-checked code analysis."""
    bad = _preflight()
    if bad:
        return JSONResponse({"error": bad}, status_code=400)
    job = _deep_start(slug, [artifact_id] if artifact_id is not None else None)
    return {"ok": True, **{k: v for k, v in job.items() if k != "started"}}


@app.get("/api/programs/{slug}/deepdive")
def api_program_deepdive_status(slug: str):
    from core import deepdive
    with _open_program(slug) as store:
        job = _DEEP.get(slug) or {"running": False}
        return {"job": {k: v for k, v in job.items() if k != "started"},
                "pending": [a["name"] for a in deepdive.pending(store)],
                "files": store.get_meta("deepdive") or {}, "program": store.get_meta("deepdive_program") or {},
                "rescan": deepdive.rescan_requests(store)}


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


def _program_budget(store):
    from core.usage import program_budget
    return program_budget(store)


@app.get("/api/programs/{slug}")
def api_program(slug: str):
    with _open_program(slug) as store:
        revision = store.model_stamp()
        return {
            "program": store.info,
            "revision": revision,
            "coverage": store.coverage(),
            "usage": store.usage(),
            "budget_usd": _program_budget(store),
            "usage_by_step": store.usage_by_step()["steps"],
            "artifacts": (arts := [_artifact_summary(store, a) for a in store.artifacts()]),
            "progress": _progress(arts),
            "recapture_target": store.get_meta("recapture_target"),
            "report": {"built_at": store.get_meta("report_built_at"),
                       "current": store.get_meta("report_stamp") == revision},
            "waiting": sum(1 for a in store.artifacts() if a["status"] == "captured"),
            "session_running": _session.running() and _session.program == slug,
            "worker_running": _session.worker_running(slug),
            "capture_elsewhere": _session.running() and _session.program != slug,
        }


@app.post("/api/programs/{slug}/recapture")
def api_program_recapture(slug: str, payload: dict = Body(...)):
    with _open_program(slug) as store:
        art = store.artifact(int((payload or {}).get("artifact_id") or 0))
        if art is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        if (store.current_artifact(art['name']) or {}).get('id') != art['id']:
            raise HTTPException(status_code=409, detail="This version was replaced. Choose the current file.")
        if (store.pending_captures().get(art['id']) or {}).get('recapture_of'):
            raise HTTPException(status_code=409, detail="This is a pending replacement. Choose the original file to recapture or add screenshots.")
        paused = bool((store.pending_captures().get(art['id']) or {}).get('paused'))
        mode = "append" if paused or (payload or {}).get("mode") == "append" else "replace"
        target = {"name": art["name"], "artifact_id": art["id"], "version": art["version"], "mode": mode}
        if paused:
            target["paused"] = True   # resuming: the next capture is added to this same file
        store.set_meta("recapture_target", target)
        return {"ok": True, "recapture_target": target}


@app.delete("/api/programs/{slug}/recapture")
def api_program_recapture_cancel(slug: str):
    with _open_program(slug) as store:
        store.set_meta("recapture_target", None)
    return {"ok": True}


@app.post("/api/programs/{slug}/pending/process")
def api_program_pending_process(slug: str):
    with _open_program(slug) as store:
        paused = {k for k, v in store.pending_captures().items() if v.get("paused")}
        waiting = sum(1 for a in store.artifacts() if a["status"] == "captured" and a["id"] not in paused)
    if not waiting:
        return {"ok": True, "waiting": 0}
    if _session.running() and _session.program == slug:
        return {"ok": True, "waiting": waiting, "note": "The running capture session is analysing them."}
    bad = _preflight(reading_models=True)
    if bad:
        return JSONResponse({"error": bad}, status_code=400)
    if not _session.process_pending(slug):
        return {"ok": True, "waiting": waiting, "note": "Already analysing in the background."}
    return {"ok": True, "waiting": waiting, "note": "Analysing in the background."}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/screenshots")
def api_program_artifact_screenshots(slug: str, artifact_id: int, payload: dict = Body(...)):
    """Add screenshots (PNG/JPEG data URLs) to a file; the file is re-read from all its screenshots as a new version."""
    import base64
    import tempfile
    images = [str(x) for x in (payload or {}).get("images") or []][:40]
    if not images:
        return JSONResponse({"error": "Choose one or more screenshots."}, status_code=400)
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        paths = []
        for i, data in enumerate(images, 1):
            head, _, body = data.partition(",")
            if "base64" not in head or not body:
                return JSONResponse({"error": "Screenshots must be images."}, status_code=400)
            ext = "jpg" if "jpeg" in head or "jpg" in head else "png"
            p = tmp / f"{i:03d}.{ext}"
            try:
                import io
                from PIL import Image
                decoded = base64.b64decode(body, validate=True)
                with Image.open(io.BytesIO(decoded)) as image:
                    if image.format not in ('PNG', 'JPEG'):
                        raise ValueError('Unsupported image format')
                    image.verify()
            except (ValueError, OSError) as exc:
                return JSONResponse({"error": "Choose a valid PNG or JPEG screenshot."}, status_code=400)
            p.write_bytes(decoded)
            paths.append(p)
        with _open_program(slug) as store:
            art = store.artifact(artifact_id)
            if art is None:
                raise HTTPException(status_code=404, detail="No such file in this program.")
            if (store.current_artifact(art['name']) or {}).get('id') != artifact_id:
                raise HTTPException(status_code=409, detail="This version was replaced. Choose the current file.")
            if (store.pending_captures().get(artifact_id) or {}).get('recapture_of'):
                raise HTTPException(status_code=409, detail="This is a pending replacement. Add screenshots to the original file.")
            kind = "screen" if art["artifact_type"] == "ui_screen" else "code"
            new_id = store.add_pending_capture(paths, kind=kind, session_id=store.add_session(mode="upload"),
                                               recapture_of=art["name"], keep_frames_of=artifact_id)
            frames = len(store.artifact_evidence(new_id))
        out = api_program_pending_process(slug)
        if isinstance(out, JSONResponse):
            return out
        return {**out, "artifact_id": new_id, "frames": frames, "added": len(paths)}


def _claims_alive(slug: str) -> bool:
    from core.model.store import _owner_alive
    with _open_program(slug) as store:
        pending = store.pending_captures() or {}
    return any((v.get("claim") or {}).get("owner") and _owner_alive(v["claim"]["owner"]) for v in pending.values())


def _preflight(reading_models: bool = False) -> str:
    """A message when a model the run needs does not answer; "" when all do or when there is no key to test with."""
    if not api_key_status()["has_key"] or os.environ.get("CODESNAP_SKIP_PREFLIGHT") == "1":
        return ""
    from core import preflight
    try:
        failed = preflight.check_models(_client(), preflight.reading_models() if reading_models else preflight.analysis_models())
    except HTTPException:
        return ""
    return preflight.describe(failed) if failed else ""


def _programs_being_analysed() -> list:
    from core.model import ProgramStore
    out = []
    for info in ProgramStore.list():
        slug = info.get("slug")
        try:
            if slug and _analysis_busy(slug):
                out.append(slug)
        except Exception:  # noqa: BLE001 - a program that cannot be opened must not block a capture
            continue
    return out


def _analysis_busy(slug: str) -> bool:
    if slug in _REBUILDS or (_DEEP.get(slug) or {}).get("running"):
        return True
    return _claims_alive(slug)


def _stop_analysis(slug: str, wait: float = 30.0) -> bool:
    from core import capture_gate
    capture_gate.cancel_analysis(wait + 30, slug)
    began = time.time()
    terminated = False
    while time.time() - began < wait:
        if not _analysis_busy(slug):
            break
        if not terminated and time.time() - began > 8:
            _session.stop_pending(slug)
            terminated = True
        time.sleep(0.5)
    stopped = not _analysis_busy(slug)
    capture_gate.clear_cancel(slug)
    return stopped


@app.post("/api/programs/{slug}/analysis/stop")
def api_program_analysis_stop(slug: str):
    if not _stop_analysis(slug):
        return JSONResponse({"error": "Analysis is still stopping. Try again in a few seconds."}, status_code=409)
    return {"ok": True}


@app.delete("/api/programs/{slug}/artifacts/{artifact_id}")
def api_program_artifact_delete(slug: str, artifact_id: int, force: bool = False):
    if force and not _stop_analysis(slug):
        return JSONResponse({"error": "Analysis is still stopping. Try again in a few seconds."}, status_code=409)
    with _open_program(slug) as store:
        if not store.artifact(artifact_id):
            return JSONResponse({"error": "File not found"}, status_code=404)
        if not force and (slug in _REBUILDS or store.capture_progress(artifact_id).get("analysing") or (_DEEP.get(slug) or {}).get("running")):
            return JSONResponse({"error": "This program is being analysed. Wait for analysis to finish before removing the file."},
                                status_code=409)
        from core.model.removal import remove_file
        try:
            removed = remove_file(store, artifact_id, force=force)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        from core.model.linker import link_program
        link_program(store)
        return {"ok": True, "removed": artifact_id, "removed_versions": removed}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/rebuild")
def api_program_artifact_rebuild(slug: str, artifact_id: int):
    with _open_program(slug) as store:
        if not store.artifact(artifact_id):
            return JSONResponse({"error": "File not found"}, status_code=404)
        from core import deepdive
        capture_worker_running = (_session.running() and _session.program == slug) or _session.worker_running(slug)
        if ((capture_worker_running and deepdive._active(store)) or
                any(store.capture_progress(a["id"]).get("analysing") for a in store.artifacts())):
            return JSONResponse({"error": "Wait for current analysis to finish before rebuilding a saved capture."}, status_code=409)
        from core.model.restitch import rebuild_saved_capture
        with _REBUILD_LOCK:
            if (_DEEP.get(slug) or {}).get("running"):
                return JSONResponse({"error": "Wait for current analysis to finish before rebuilding a saved capture."}, status_code=409)
            if slug in _REBUILDS:
                return JSONResponse({"error": "A saved capture is already being rebuilt. Wait for it to finish."}, status_code=409)
            job = {"name": store.artifact(artifact_id)["name"], "stage": "Reading saved screenshots", "done": 0, "total": 0}
            _REBUILDS[slug] = job
        try:
            out = rebuild_saved_capture(store, artifact_id, progress=lambda **values: job.update(values))
            _deep_when_ready(slug)
            return out
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        finally:
            with _REBUILD_LOCK:
                _REBUILDS.pop(slug, None)


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/retry")
def api_program_artifact_retry(slug: str, artifact_id: int):
    with _open_program(slug) as store:
        art = store.artifact(artifact_id)
        if art is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        if artifact_id not in store.pending_captures():
            return JSONResponse({"error": "Only a capture that hasn't been analysed can be retried — use Recapture."},
                                status_code=400)
        try:
            store.retry_pending(artifact_id)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
    return api_program_pending_process(slug)


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/finish")
def api_program_artifact_finish(slug: str, artifact_id: int):
    """Stop waiting for more of a paused file: analyse what has been captured."""
    with _open_program(slug) as store:
        info = store.pending_captures().get(artifact_id)
        if not info or not info.get("paused"):
            return JSONResponse({"error": "This file is not paused."}, status_code=400)
        if (store.get_meta("recapture_target") or {}).get("artifact_id") == artifact_id:
            store.set_meta("recapture_target", None)
        store.update_pending(artifact_id, paused=False)
    return api_program_pending_process(slug)


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/version-of")
def api_program_artifact_version_of(slug: str, artifact_id: int, payload: dict = Body(...)):
    from core.model import new_version_from
    with _open_program(slug) as store:
        src, target = store.artifact(artifact_id), store.artifact(int((payload or {}).get("target_id") or 0))
        if src is None or target is None or src["id"] == target["id"]:
            raise HTTPException(status_code=404, detail="Pick another file in this program.")
        if src["status"] == "captured":
            return JSONResponse({"error": "Wait until this capture has been analysed."}, status_code=409)
        new_id = new_version_from(store, None, artifact_id, target["name"])
        return {"ok": True, "artifact": _artifact_summary(store, store.artifact(new_id))}


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
        file_entity = store.entity_by_key(f"file:{artifact['name']}")
        profile = (file_entity or {}).get("attrs", {}).get("profile")
        from core import deepdive
        from core.model.line_review import items
        dd = (store.get_meta("deepdive") or {}).get(str(artifact_id))
        q = deepdive.capture_quality(store, artifact, deepdive.current_concerns(store, artifact))
        return {"artifact": artifact, "entities": entities, "evidence": evidence, "profile": profile,
                "verification": store.verification(artifact_id), "deep": dd,
                "deep_current": bool(dd) and dd.get("hash") == deepdive._hash(artifact.get("transcription")),
                "quality": {"status": q["status"], "issues": q["issues"]},
                "review_lines": items(store, artifact)}


def _file_busy(slug: str, store, art: dict) -> str | None:
    """Why this one file cannot take an answer right now (None when it can). Other files being read or reviewed do not matter:
    a file can be checked as soon as its own results are in, while the rest of the program is still being analysed."""
    from core import deepdive
    rebuilding = _REBUILDS.get(slug)
    if rebuilding and rebuilding.get("name") == art["name"]:
        return "This file is being rebuilt from its saved screenshots. Try again when that finishes."
    if store.capture_progress(art["id"]).get("analysing") or art.get("status") == "captured":
        return "This file is still being read. You can answer as soon as its results are in."
    if str(art["id"]) in deepdive._active(store):
        return "This file is being reviewed right now. Try again in a few minutes."
    for aid, info in (store.pending_captures() or {}).items():
        if aid != art["id"] and (info.get("recapture_of") == art["name"] or info.get("added_to") == art["id"]):
            return "A new capture of this file is being analysed. Wait for it to finish."
    return None


@app.get("/api/programs/{slug}/artifacts/{artifact_id}/review/{line}")
def api_line_review(slug: str, artifact_id: int, line: int):
    from core.model.line_review import detail
    with _open_program(slug) as store:
        art = store.artifact(artifact_id)
        if not art or not art['is_current']:
            raise HTTPException(status_code=404, detail="This file was removed or replaced. Refresh the review.")
        try:
            return detail(store, art, line)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/review/{line}")
def api_line_review_answer(slug: str, artifact_id: int, line: int, payload: dict = Body(...)):
    from core import feedback, deepdive
    from core.model.corrections import CorrectionError
    with _open_program(slug) as store:
        art = store.artifact(artifact_id)
        if not art or not art['is_current']:
            raise HTTPException(status_code=404, detail="This file was removed or replaced. Refresh the review.")
        busy = _file_busy(slug, store, art)
        if busy:
            raise HTTPException(status_code=409, detail=busy)
        lines = (art.get('transcription') or '').splitlines()
        if (payload.get('text_hash') != deepdive._hash(art.get('transcription')) or
                not 0 < line <= len(lines) or payload.get('old_text') != lines[line-1]):
            raise HTTPException(status_code=409, detail="This source changed. Refresh the screenshot question before answering.")
        delete = payload.get('delete') is True
        text = "" if delete or payload.get('remove') is True else payload.get('new_text')
        if not isinstance(text, str) or (not text.strip() and not delete and payload.get('remove') is not True) \
                or '\n' in text or '\r' in text:
            raise HTTPException(status_code=400, detail="Enter one complete source line, preserving its spaces.")
        op = 'artifact.delete_line' if delete else 'artifact.confirm_line' if text == lines[line-1] else 'artifact.replace_line'
        change = {'artifact': art['name'], 'line': line, 'old_text': lines[line-1]}
        if op == 'artifact.replace_line':
            change['new_text'] = text
        try:
            result = feedback.apply(store, [{'op': op, 'payload': change}],
                                    note='User answered a saved screenshot question.', client=None)
        except CorrectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        from core.model.line_review import items
        remaining = items(store, store.artifact(artifact_id))
        _deep_when_ready(slug, artifact_id)
        return {'ok': True, **result, 'review_status': 'completed', 'review_lines': remaining,
                'remaining_issues': [] if delete else [item for item in remaining if item['line'] == line]}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/review/{line}/missing")
def api_line_review_missing(slug: str, artifact_id: int, line: int, payload: dict = Body(...)):
    from core import deepdive
    from core.model import confirmed
    from core.model.line_review import items
    with _open_program(slug) as store:
        art = store.artifact(artifact_id)
        if not art or not art['is_current']:
            raise HTTPException(status_code=404, detail="This file was removed or replaced. Refresh the review.")
        lines = (art.get('transcription') or '').splitlines()
        if payload.get('text_hash') != deepdive._hash(art.get('transcription')) or not 0 < line <= len(lines):
            raise HTTPException(status_code=409, detail="This source changed. Refresh the screenshot question before answering.")
        busy = _file_busy(slug, store, art)
        if busy:
            raise HTTPException(status_code=409, detail=busy)
        confirmed.mark_missing(store, art['name'], art.get('transcription'), line)
        remaining = items(store, art)
        _deep_when_ready(slug, artifact_id)
        return {'ok': True, 'review_lines': remaining,
                'message': f'Lines are missing before line {line}. Record that part of the screen again with Add screenshots.'}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/rename")
def api_program_artifact_rename(slug: str, artifact_id: int, payload: dict = Body(...)):
    with _open_program(slug) as store:
        try:
            store.rename_artifact(artifact_id, str((payload or {}).get("name", "")))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return {"ok": True, "artifact": _artifact_summary(store, store.artifact(artifact_id))}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/type")
def api_program_artifact_type(slug: str, artifact_id: int, payload: dict = Body(...)):
    from core.model import ARTIFACT_TYPES, ingest_artifact
    atype = str((payload or {}).get("artifact_type", ""))
    if atype not in ARTIFACT_TYPES:
        return JSONResponse({"error": f"Unknown type: {atype}"}, status_code=400)
    with _open_program(slug) as store:
        if store.artifact(artifact_id) is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        store.set_artifact_type(artifact_id, atype)
        try:
            counts = ingest_artifact(store, _LazyClient(slug), artifact_id)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Re-extraction failed: {exc}"}, status_code=500)
        return {"ok": True, **counts, "artifact": _artifact_summary(store, store.artifact(artifact_id))}


class _LazyClient:
    def __init__(self, slug):
        self.slug = slug
        self._client = None

    @property
    def messages(self):
        if self._client is None:
            self._client = _program_client(self.slug)
        return self._client.messages


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/reextract")
def api_program_artifact_reextract(slug: str, artifact_id: int):
    from core.model import ingest_artifact
    client = _program_client(slug)
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


@app.post("/api/programs/{slug}/relink")
def api_program_relink(slug: str):
    from core.model.linker import link_program
    with _open_program(slug) as store:
        return {"ok": True, **link_program(store), "coverage": store.coverage()}


@app.get("/api/programs/{slug}/flows")
def api_program_flows(slug: str, limit: int = 500):
    from core.model.linker import trace_flows
    with _open_program(slug) as store:
        flows = trace_flows(store)
    return {"flows": flows[:limit], "total": len(flows)}


@app.post("/api/programs/{slug}/security/scan")
def api_program_security_scan(slug: str, online: bool = False):
    from core.security import run_scan
    with _open_program(slug) as store:
        result = run_scan(store, online=online, cache_dir=store.path / "cache" / "osv")
        return {"ok": True, **result, "findings": store.findings()}


@app.get("/api/programs/{slug}/findings")
def api_program_findings(slug: str, category: str | None = None):
    from core.security import summary
    with _open_program(slug) as store:
        return {"findings": store.findings(category), "summary": summary(store)}


@app.post("/api/programs/{slug}/findings/{finding_id}/status")
def api_program_finding_status(slug: str, finding_id: int, payload: dict = Body(...)):
    status_ = str((payload or {}).get("status", "")).strip()
    if status_ not in ("open", "accepted", "dismissed", "fixed"):
        return JSONResponse({"error": "status must be open, accepted, dismissed or fixed"}, status_code=400)
    from core.model.corrections import add, finding_sig
    with _open_program(slug) as store:
        f = store.finding(finding_id)
        if f is None:
            raise HTTPException(status_code=404, detail="No such finding.")
        add(store, "finding.status", {"sig": finding_sig(f), "status": status_}, str((payload or {}).get("note", "")))
        return {"ok": True, "finding": store.finding(finding_id)}


@app.get("/api/programs/{slug}/technologies")
def api_program_technologies(slug: str):
    from core.security import technologies
    with _open_program(slug) as store:
        return {"technologies": technologies(store)}


@app.post("/api/eol/refresh")
def api_eol_refresh():
    from core.security import eol
    return eol.refresh()


@app.get("/api/programs/{slug}/assessment")
def api_program_assessment(slug: str):
    with _open_program(slug) as store:
        return {"assessment": store.get_meta("assessment"), "inputs": store.get_meta("assessment_inputs", {})}


@app.post("/api/programs/{slug}/assessment")
def api_program_assess(slug: str, scan: bool = True, online: bool = False):
    from core.assess import run_assessment
    with _open_program(slug) as store:
        return {"ok": True, "assessment": run_assessment(store, scan=scan, online=online),
                "inputs": store.get_meta("assessment_inputs", {})}


@app.post("/api/programs/{slug}/assessment/inputs")
def api_program_assess_inputs(slug: str, payload: dict = Body(...)):
    from core.assess import run_assessment, set_inputs
    with _open_program(slug) as store:
        try:
            inputs = set_inputs(store, payload or {})
        except (TypeError, ValueError):
            return JSONResponse({"error": "impact / criticality must be 1–5"}, status_code=400)
        return {"ok": True, "inputs": inputs, "assessment": run_assessment(store, scan=False)}


def _diagrams(store):
    from core.diagrams import all_diagrams
    from core.report import _redactor
    return _redactor(store).map(all_diagrams(store))


@app.get("/api/programs/{slug}/diagrams")
def api_program_diagrams(slug: str):
    from core.diagrams import diagram_coverage
    from core.diagrams.export import summary
    with _open_program(slug) as store:
        ds = _diagrams(store)
        return {"diagrams": summary(ds), "coverage": diagram_coverage(store, ds)}


@app.get("/api/programs/{slug}/diagrams/export/{fmt}")
def api_program_diagrams_export(slug: str, fmt: str):
    from core.diagrams import drawio, vsdx
    from core.diagrams.export import bundle
    with _open_program(slug) as store:
        ds = _diagrams(store)
        from core.report import _redactor
        name = _redactor(store)(store.info["name"])
        if fmt == "vsdx":
            body, mt = vsdx(ds, f"{name} diagrams"), "application/vnd.ms-visio.drawing"
        elif fmt == "drawio":
            body, mt = drawio(ds).encode(), "application/xml"
        elif fmt == "zip":
            body, mt = bundle(store, ds), "application/zip"
        else:
            raise HTTPException(status_code=404, detail="Use vsdx, drawio or zip.")
    return Response(body, media_type=mt,
                    headers={"Content-Disposition": f'attachment; filename="{slug}_diagrams.{fmt}"'})


@app.get("/api/programs/{slug}/diagrams/{diagram_id}.{fmt}")
def api_program_diagram(slug: str, diagram_id: str, fmt: str):
    from core.diagrams import png, svg
    with _open_program(slug) as store:
        d = next((x for x in _diagrams(store) if x["id"] == diagram_id), None)
    if d is None:
        raise HTTPException(status_code=404, detail="No such diagram.")
    if fmt == "svg":
        return Response(svg(d), media_type="image/svg+xml")
    if fmt == "png":
        return Response(png(d), media_type="image/png")
    raise HTTPException(status_code=404, detail="Use svg or png.")


@app.post("/api/programs/{slug}/report/prepare")
def api_program_report_prepare(slug: str):
    """Start the deep code analysis the report needs (if any). The report GETs never do this."""
    from core import report as rep
    from core import deepdive
    with _open_program(slug) as store:
        if rep.waiting(store):
            return {"ok": True, "started": False, "waiting": True}
        job = _DEEP.get(slug) or {}
        needs = bool(deepdive.pending(store) or deepdive.program_stale(store))
    if job.get("running"):
        return {"ok": True, "started": False, "running": True}
    if needs and api_key_status()["has_key"]:
        _deep_start(slug)
        return {"ok": True, "started": True}
    return {"ok": True, "started": False}


@app.get("/api/programs/{slug}/report.{fmt}")
def api_program_report(slug: str, fmt: str, rescan: bool = True, client: str | None = None):
    from core import report as rep
    if fmt not in ("html", "docx", "pdf", "zip"):
        raise HTTPException(status_code=404, detail="Use html, docx, pdf or zip.")
    with _open_program(slug) as store:
        if client:   # a report for a different client name is built fresh, not cached
            if fmt == "html":
                return HTMLResponse(rep.html_report(store, rescan=rescan, client=client))
            if fmt == "pdf":
                body = rep.pdf_from_docx(rep.docx_bytes(store, rescan=rescan, client=client))
                if body is None:
                    return JSONResponse({"error": rep.PDF_MISSING}, status_code=501)
                return Response(body, media_type="application/pdf",
                                headers={"Content-Disposition": f'attachment; filename="{slug}_assessment_report.pdf"'})
            body = (rep.docx_bytes(store, rescan=rescan, client=client) if fmt == "docx"
                    else rep.package(store, rescan=rescan, client=client)["zip"])
            mt = "application/zip" if fmt == "zip" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            name = f"{slug}_assessment_report.{fmt}" if fmt != "zip" else f"{slug}_assessment_report_package.zip"
            return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"'})
        n = rep.waiting(store)
        if not n:
            from core import deepdive
            todo = deepdive.pending(store)
            job = _DEEP.get(slug) or {}
            if (todo or deepdive.program_stale(store) or job.get("running")) and api_key_status()["has_key"]:
                # Read-only: starting the analysis is a POST (/report/prepare); a GET never starts work.
                if not job.get("running"):
                    msg = "The deep code analysis hasn't been started yet. Open the report from the app (View report) to start it."
                else:
                    msg = (f"Deep code analysis is running ({job.get('done', 0)} of {job.get('total', len(todo))} files). " if todo else
                           "Drawing the cross-file observations from the reviewed files. ") + (
                           "The report is built from it; refresh in a minute.")
                if fmt == "html":
                    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=20>"
                                        f"<body style='font:16px system-ui;padding:40px'><h2>Analysing the code</h2>"
                                        f"<p>{msg}</p>", status_code=409)
                return JSONResponse({"error": msg}, status_code=409)
        if n:
            msg = f"The report is built once every file is analysed — {n} still waiting."
            if fmt == "html":
                return HTMLResponse(f"<!doctype html><meta charset=utf-8><body style='font:16px system-ui;padding:40px'>"
                                    f"<h2>Not ready yet</h2><p>{msg}</p><p>This page can be refreshed.</p>", status_code=409)
            return JSONResponse({"error": msg}, status_code=409)
        res = rep.cached_package(store)
        if fmt == "pdf":
            path = Path(res["dir"]) / f"{slug}_assessment_report.pdf"
            if not path.exists():
                return HTMLResponse(f"<!doctype html><meta charset=utf-8><body style='font:16px system-ui;padding:40px'>"
                                    f"<h2>PDF not available</h2><p>{rep.PDF_MISSING}</p>", status_code=501)
            return Response(path.read_bytes(), media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{slug}_assessment_report.pdf"'})
        path = Path(res["dir"]) / {"html": res["files"][0], "docx": res["files"][1], "zip": res["files"][4]}[fmt]
        body = path.read_bytes()
        if fmt == "html":
            return HTMLResponse(body.decode())
        mt = "application/zip" if fmt == "zip" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    name = f"{slug}_assessment_report.{fmt}" if fmt != "zip" else f"{slug}_assessment_report_package.zip"
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/programs/{slug}/report-medium.{fmt}")
def api_program_report_medium(slug: str, fmt: str):
    """The medium-length report: the full report cut to the sections a delivery lead reads."""
    from core import report as rep
    if fmt not in ("docx", "pdf"):
        raise HTTPException(status_code=404, detail="Use docx or pdf.")
    with _open_program(slug) as store:
        n = rep.waiting(store)
        if n:
            return JSONResponse({"error": f"The report is built once every file is analysed: {n} still waiting."}, status_code=409)
        res = rep.cached_package(store)
        full = (Path(res["dir"]) / res["files"][1]).read_bytes()
    from core.report import medium
    body = medium.cut(full)
    if fmt == "pdf":
        body = rep.pdf_from_docx(body)
        if body is None:
            return JSONResponse({"error": rep.PDF_MISSING}, status_code=501)
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{slug}_medium_report.{fmt}"'})


@app.get("/api/programs/{slug}/executive-summary.{fmt}")
def api_program_executive_summary(slug: str, fmt: str):
    """The executive summary as its own Word or PDF file, built from the saved summary while it still matches the findings."""
    from core import report as rep
    from core.report import summary_doc
    if fmt not in ("docx", "pdf"):
        raise HTTPException(status_code=404, detail="Use docx or pdf.")
    with _open_program(slug) as store:
        body = summary_doc.docx_bytes(store)
        if body is None:
            return JSONResponse({"error": "The executive summary is not ready. It is written in the final stage of the analysis, "
                                          "and is rewritten whenever the findings change."}, status_code=409)
    if fmt == "pdf":
        body = rep.pdf_from_docx(body)
        if body is None:
            return JSONResponse({"error": rep.PDF_MISSING}, status_code=501)
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{slug}_executive_summary.{fmt}"'})


@app.get("/api/programs/{slug}/report-settings")
def api_report_settings(slug: str):
    from core.report.settings import BUSINESS_KEYS, FIELDS, get
    with _open_program(slug) as store:
        return {"fields": [{"key": k, "label": l, "group": "business" if k in BUSINESS_KEYS else "details"} for k, l in FIELDS],
                "values": get(store)}


@app.post("/api/programs/{slug}/report-settings")
def api_report_settings_save(slug: str, payload: dict = Body(...)):
    from core.report.settings import save
    with _open_program(slug) as store:
        return {"ok": True, "values": save(store, payload or {})}


@app.post("/api/programs/{slug}/ui/review")
def api_program_ui_review(slug: str, site_url: str | None = None, max_pages: int = 10):
    from core.uireview import run_ui_review
    with _open_program(slug) as store:
        return {"ok": True, **run_ui_review(store, site_url=site_url or None, max_pages=max(1, min(max_pages, 50)))}


@app.get("/api/programs/{slug}/ui")
def api_program_ui(slug: str):
    from core.uireview import CATEGORIES, summary
    with _open_program(slug) as store:
        return {"summary": summary(store), "site": store.get_meta("site_scan"), "flows": store.get_meta("ui_flows"),
                "findings": [f for f in store.findings() if f["category"] in CATEGORIES]}


@app.get("/api/programs/{slug}/corrections")
def api_program_corrections(slug: str):
    from core.model.corrections import history
    with _open_program(slug) as store:
        return {"corrections": history(store)}


@app.post("/api/programs/{slug}/corrections")
def api_program_correct(slug: str, payload: dict = Body(...)):
    from core import feedback
    from core.model.corrections import CorrectionError
    ops = (payload or {}).get("ops") or ([{"op": payload.get("op"), "payload": payload.get("payload") or {}}]
                                         if (payload or {}).get("op") else [])
    if not ops:
        return JSONResponse({"error": "Send an op or a list of ops."}, status_code=400)
    with _open_program(slug) as store:
        try:
            out = {"ok": True, **feedback.apply(store, ops, str(payload.get("note", "")), client=_LazyClient(slug))}
            _deep_when_ready(slug)
            return out
        except CorrectionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/programs/{slug}/corrections/{correction_id}/undo")
def api_program_correction_undo(slug: str, correction_id: int):
    from core import feedback
    from core.model.corrections import CorrectionError
    with _open_program(slug) as store:
        try:
            out = {"ok": True, **feedback.undo(store, correction_id, client=_LazyClient(slug))}
            _deep_when_ready(slug)
            return out
        except CorrectionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/programs/{slug}/corrections/interpret")
def api_program_correction_interpret(slug: str, payload: dict = Body(...)):
    from core import feedback
    text = str((payload or {}).get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "Describe the correction first."}, status_code=400)
    client = _program_client(slug)
    with _open_program(slug) as store:
        return {"ok": True, **feedback.interpret(store, text, client)}


@app.get("/api/programs/{slug}/entities/search")
def api_program_entity_search(slug: str, q: str = "", limit: int = 25):
    with _open_program(slug) as store:
        ql = q.strip().lower()
        if len(ql) < 2:
            return {"entities": []}
        rank = {"program": 0, "class": 1, "table": 2, "screen": 3, "copybook": 4, "data_store": 5, "api_endpoint": 6}
        hits = sorted([e for e in store.entities() if ql in e["name"].lower() and e["kind"] != "file"],
                      key=lambda e: (e["name"].lower() != ql, not e["name"].lower().startswith(ql),
                                     e["origin"] == "placeholder", rank.get(e["kind"], 9), e["name"]))[:max(1, min(limit, 100))]
        out = []
        for e in hits:
            rels = []
            for r in store.relations(from_id=e["id"]) + store.relations(to_id=e["id"]):
                a, b = store.entity(r["from_id"]), store.entity(r["to_id"])
                if a and b:
                    rels.append({"kind": r["kind"], "from_key": a["key"], "from": a["name"], "to_key": b["key"],
                                 "to": b["name"], "origin": r["origin"]})
            src = store.entity_sources(e["id"])
            out.append({"key": e["key"], "name": e["name"], "kind": e["kind"], "origin": e["origin"],
                        "attrs": {k: v for k, v in (e.get("attrs") or {}).items() if k in (
                            "no_pii", "pii", "hardcoded_secret", "store_type", "aliases")},
                        "file": src[0]["artifact_name"] if src else None, "relations": rels[:30]})
        return {"entities": out}


@app.get("/api/programs/{slug}/health")
def api_program_health(slug: str):
    from core.model.health import pipeline_health
    with _open_program(slug) as store:
        return pipeline_health(store)


@app.post("/api/programs/{slug}/budget")
def api_program_budget(slug: str, body: dict = Body(...)):
    try:
        value = float(body.get("budget_usd") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "budget must be a number"}, status_code=400)
    if value < 0:
        return JSONResponse({"error": "budget must be zero or more (0 = no limit)"}, status_code=400)
    from core.model.health import pipeline_health
    with _open_program(slug) as store:
        store.set_meta("budget_usd", value or None)
        return pipeline_health(store)["budget"]


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
    client = _program_client(slug) if extract else None
    with _open_program(slug) as store:
        try:
            imported = import_reports(store, [REPORTS, PENDING], client=client)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"Import failed: {exc}"}, status_code=500)
        return {"ok": True, "imported": imported}


_FOLDER_JOBS = {}


@app.post("/api/pick-folder")
def api_pick_folder():
    """Ask macOS for a folder with its own chooser. {path: ""} when the person cancels."""
    import subprocess
    try:
        out = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose the program\'s code folder")'],
                             capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(status_code=500, detail="The folder chooser is not available. Type the folder path instead.")
    return {"path": out.stdout.strip() if out.returncode == 0 else ""}


@app.get("/api/programs/{slug}/import-folder")
def api_program_folder_status(slug: str):
    if not _program_exists(slug):
        raise HTTPException(status_code=404, detail=f"Unknown program: {slug}")
    return _FOLDER_JOBS.get(slug) or {"running": False}


@app.post("/api/programs/{slug}/import-folder")
def api_program_import_folder(slug: str, payload: dict = Body(...)):
    """Add a folder's source files to the program as they are (no screenshots), then read their structure and review them."""
    from core.model.folder_import import add_folder_files, scan_folder, structure_files
    folder = str((payload or {}).get("path") or "").strip()
    if not folder:
        return JSONResponse({"error": "Choose the folder that holds the code."}, status_code=400)
    try:
        found = scan_folder(folder)
    except (ValueError, OSError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if not found["files"]:
        return JSONResponse({"error": "No source files were found in that folder."}, status_code=400)
    with _JOB_LOCK:
        if (_FOLDER_JOBS.get(slug) or {}).get("running"):
            return JSONResponse({"error": "A folder is already being added to this program."}, status_code=409)
        job = _FOLDER_JOBS[slug] = {"running": True, "stage": "Adding files", "done": 0, "total": len(found["files"]),
                                    "skipped": found["skipped"], "folder": folder}
    client = _program_client(slug)

    def work():
        try:
            def tick(stage):
                def inner(done, total):
                    job.update(stage=stage, done=done, total=total)
                return inner
            with _open_program(slug) as store:
                added = add_folder_files(store, folder, tick("Adding files"))
                job.update(added=added["added"], unreadable=added["unreadable"])
                failed = structure_files(store, client, added["names"], tick("Reading structure"))
                job["structure_failed"] = failed
            _deep_when_ready(slug)
        except Exception as exc:  # noqa: BLE001
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            job.update(running=False, stage="Done")

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "files": len(found["files"]), "skipped": found["skipped"]}


@app.post("/api/programs/{slug}/artifacts/{artifact_id}/accept-all")
def api_accept_all_file(slug: str, artifact_id: int):
    """Accept every flag on one file, of whatever kind, as it is."""
    from core.model.accept import accept_all
    with _open_program(slug) as store:
        art = store.artifact(artifact_id)
        if art is None:
            raise HTTPException(status_code=404, detail="No such file in this program.")
        done = accept_all(store, art)
    _deep_when_ready(slug)
    return {"ok": True, **done}


@app.post("/api/programs/{slug}/accept-all")
def api_accept_all_program(slug: str):
    """Accept every flag on every current file of the program, so nothing holds the analysis back."""
    from core.model.accept import accept_all
    count, lines = 0, 0
    with _open_program(slug) as store:
        for art in store.artifacts():
            if (art.get("transcription") or "").strip() and art.get("is_current", 1):
                done = accept_all(store, art)
                count += 1
                lines += len(done["lines"]) + len(done["findings"])
    _deep_when_ready(slug)
    return {"ok": True, "files": count, "accepted": lines}


@app.post("/api/open-in-browser")
def api_open_in_browser(payload: dict = Body(...)):
    """The app's own window cannot open a second window, so a link meant for a new tab (the report, a saved screenshot, a diagram)
    opens in the person's default browser. Only this app's own pages and the Anthropic console are opened."""
    import webbrowser
    target = str(payload.get("url") or "")
    if target.startswith("/") and not target.startswith("//"):
        target = f"http://127.0.0.1:{os.environ.get('CODESNAP_PORT', '8000')}{target}"
    elif not target.startswith("https://console.anthropic.com/"):
        raise HTTPException(status_code=400, detail="That address cannot be opened from here.")
    webbrowser.open(target)
    return {"ok": True}


@app.get("/api/settings")
def api_settings():
    from core import settings
    return {"batch": os.environ.get("CODESNAP_BATCH", "0").lower() in ("1", "true", "on", "yes"),
            "scroll_to_top": bool(settings.get("scroll_to_top", False))}


@app.post("/api/settings")
def api_settings_set(payload: dict = Body(...)):
    from core import settings
    if "batch" in payload:
        settings.set_batch(bool(payload["batch"]))
    if "scroll_to_top" in payload:
        settings.set("scroll_to_top", bool(payload["scroll_to_top"]))
    return api_settings()


@app.get("/api/about")
def api_about():
    """What support will ask for: the version and where this install keeps its data."""
    from core import paths, version
    from core.model.workspace import DEFAULT_ROOT
    import os
    return {"version": version.VERSION, "data": str(paths.data_root()),
            "programs": str(Path(os.environ.get("CODESNAP_PROGRAMS") or DEFAULT_ROOT).expanduser())}


@app.get("/api/permissions")
def api_permissions():
    """Which of the macOS permissions CodeSnap needs are still missing (null = cannot tell, shown as fine)."""
    from core import permissions
    now = permissions.status()                       # one check, so the two fields can never disagree
    return {**now, "missing": [name for name, ok in now.items() if ok is False]}


@app.post("/api/permissions/open")
def api_permissions_open(pane: str = "screen"):
    from core import permissions
    if pane not in permissions.PANES:
        return JSONResponse({"error": "pane must be screen or accessibility"}, status_code=400)
    return {"ok": permissions.request(pane)}


@app.get("/api/key/status")
def api_key_status():
    """Does the app have an Anthropic API key yet? (drives the first-run banner)"""
    import os
    from core import analysis
    analysis.load_env()
    return {"has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


def _write_private(path: Path, text: str) -> None:
    """Write a secret file readable by the owner only (0600), never briefly world-readable."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(str(path), 0o600)


@app.post("/api/key")
def api_key_set(payload: dict | None = Body(None), value: str = ""):
    """Save the user's Anthropic key to ~/.codesnap/.env (found by the capture
    worker on launch) and this process's env. Local-only server, so this is fine."""
    if isinstance(payload, dict) and payload.get("value") is not None:   # preferred: keep the key out of URLs/logs
        value = str(payload.get("value"))
    key = (value or "").strip()
    if not (key.startswith("sk-ant") and len(key) > 20):
        return JSONResponse({"ok": False, "error": "That doesn't look like an Anthropic key (it should start with 'sk-ant')."}, status_code=400)
    cfg = Path.home() / ".codesnap"
    try:
        cfg.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(cfg, 0o700)
        except OSError:
            pass
        _write_private(cfg / ".env", f"ANTHROPIC_API_KEY={key}\n")
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
            fname = fname.replace("\\", "/").rsplit("/", 1)[-1] or r["name"]   # a label, never a path
            files.append({"name": fname, "code": r["code"]})
            picked.append((r, fname))
    if len(files) < 2:
        return JSONResponse({"error": "Couldn't find code for the selected captures."}, status_code=400)

    from core import analysis
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"error": "No API key set — add it in the app first."}, status_code=400)
    import anthropic
    from core.usage import UsageTracker
    client = UsageTracker().wrap(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
    try:
        report = analyze_project(client, files)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Project analysis failed: {exc}"}, status_code=500)

    # Rename each member's bundle on disk to its detected filename (e.g. calc.py),
    # so the file downloads/displays with a real name instead of report_<timestamp>.
    members, warnings = [], []
    for r, fname in picked:
        if "." in fname:
            base, ext = fname.rsplit(".", 1)
        else:
            base, ext = fname, (r.get("extension") or "txt")
        ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:12] or "txt"
        stem = _unique(REPORTS, _slug(base))
        new_name = r["name"]
        try:
            save_report_bundle({
                "language": r.get("language", ""), "overview": r.get("overview", ""),
                "errors": r.get("errors", ""), "tech_stack": r.get("tech_stack", ""),
                "diagrams": r.get("diagrams", ""), "extension": ext, "code": r.get("code", ""),
            }, REPORTS, stem)
            for base_dir in (REPORTS, PENDING):          # remove the old report_<ts> bundle
                for victim in (f"{r['name']}.json", r.get("code_file") or ""):
                    fp = _file_in(base_dir, victim) if victim else None   # plain names inside base_dir only
                    if fp is None:
                        continue
                    try:
                        if fp.exists():
                            fp.unlink()
                    except OSError as exc:
                        log.warning("could not remove old report file %s: %s", fp, exc)
                        warnings.append(f"Couldn't remove the old copy of {victim}: {exc}")
            new_name = stem
        except Exception as exc:  # noqa: BLE001
            log.exception("could not rename report bundle for %s", fname)
            warnings.append(f"Couldn't save {fname} under its own name ({exc}); it keeps its original name.")
        members.append({"name": new_name, "filename": fname})
    report["members"] = members

    # Name the project report after what it is, e.g. ProjectReport_Calculator.
    pname = _slug(report.get("project_name", ""), "")
    base_name = "ProjectReport_" + pname if pname else "ProjectReport_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    name = _unique(REPORTS, base_name)
    try:
        save_report_bundle(report, REPORTS, name)   # finished deliverable -> Recent results
    except Exception as exc:  # noqa: BLE001 - still return it even if the save hiccups
        log.exception("could not save project report %s", name)
        warnings.append(f"The project report was built but could not be saved to Recent results ({exc}).")
    out = {"ok": True, "name": name, "report": report}
    if warnings:
        out["warnings"] = warnings
    return out


@app.post("/api/report/docx")
def api_report_docx_post(payload: dict = Body(...)):
    """Build a Word report including rendered diagram images (dev browser path)."""
    name = (payload or {}).get("name", "")
    images = (payload or {}).get("images") or []
    rep = next((r for r in scan_reports(REPORTS) + scan_reports(PENDING)
                if r.get("kind") == "report" and r.get("name") == name), None)
    if not rep:
        return JSONResponse({"error": "not found"}, status_code=404)
    from core.outputs import report_docx
    tmpdir = Path(tempfile.mkdtemp())
    tmp = tmpdir / f"{_plain_filename(name) or 'report'}.docx"
    try:
        report_docx(rep, tmp, images)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return FileResponse(str(tmp), filename=f"{name}.docx", background=_cleanup_tmp(tmpdir))


@app.get("/api/report/docx/{name}")
def api_report_docx(name: str):
    """Build a Word (.docx) report for a saved/pending report and serve it (dev browser)."""
    if _plain_filename(name) is None:
        return JSONResponse({"error": "bad name"}, status_code=400)
    rep = next((r for r in scan_reports(REPORTS) + scan_reports(PENDING)
                if r.get("kind") == "report" and r.get("name") == name), None)
    if not rep:
        return JSONResponse({"error": "not found"}, status_code=404)
    from core.outputs import report_docx
    tmpdir = Path(tempfile.mkdtemp())
    tmp = tmpdir / f"{name}.docx"
    try:
        report_docx(rep, tmp)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return FileResponse(str(tmp), filename=f"{name}.docx", background=_cleanup_tmp(tmpdir))


@app.get("/api/screen.png")
def api_screen(delay: float = 0.0, notify: bool = False, display: str | None = None):
    """One full screenshot, for the 'pick code area' picker. Optional delay lets the
    user bring their code to the front first; notify pings the desktop when done."""
    import time as _t
    if delay > 0:
        _t.sleep(min(delay, 10.0))
    try:
        from core.capture import pick_display
        shown = pick_display(display)
        png = capture_full_png()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
    if notify:
        try:
            from core.notify import notify as _notify
            _notify("CodeSnap", "Screenshot taken — switch back to draw the code box.")
        except Exception:  # noqa: BLE001 - notification is optional
            pass
    import hashlib
    reference=hashlib.sha256(png).hexdigest()
    _SPACING_REFERENCE.update(id=reference,data=png,display=shown)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-CodeSnap-Display": str(shown), 'X-CodeSnap-Spacing-Reference':reference})


@app.post("/api/session/kind")
def api_session_kind(kind: str = "code"):
    if kind not in ("code", "screen", "auto"):
        return JSONResponse({"error": "kind must be auto, code or screen"}, status_code=400)
    d = captures_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / ".capture_kind").write_text(kind)
    return {"ok": True, "kind": kind, "running": _session.running()}


@app.get("/api/displays")
def api_displays():
    try:
        from core.capture import displays
        return {"displays": displays()}
    except Exception as exc:  # noqa: BLE001
        return {"displays": [], "error": str(exc)}


@app.post("/api/session/stop")
def api_session_stop(program: str | None = None):
    _session.stop(program)
    return {"running": _session.running()}


@app.post("/api/session/pause")
def api_session_pause(paused: bool = True):
    """Hold the running capture (or carry on with it); the same file stays open."""
    try:
        _session.control(paused=paused, park=False)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return {"running": True, "paused": paused}


@app.post("/api/session/park")
def api_session_park():
    """End the capture without analysing: saved to the program as a paused file to resume later."""
    try:
        _session.control(park=True)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if not _session.program:
        return JSONResponse({"error": "Saving for later needs a program. Pause instead, or stop the session."}, status_code=400)
    return {"running": True, "parking": True}


@app.get("/api/session/status")
def api_session_status(program: str | None = None):
    """Live events for one program (its own stream); without a program, the shared stream and the capture session."""
    running = _session.running() and (program is None or _session.program == program)
    working = running or (program is not None and _session.worker_running(program))
    return {"running": running, "paused": running and _session.paused(), "working": working, "events": status.recent(program=program or ""),
            "active_programs": _session.active_programs()}


def _serve_in_thread(host="127.0.0.1", port=8000):
    """Run uvicorn in a background daemon thread (signal handlers off, since those
    only work on the main thread). Returns once the thread is started."""
    import threading
    import uvicorn
    allow_host(host)
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
    try:
        import resume
        resume.resume_in_background()
    except Exception:  # noqa: BLE001
        pass
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
                        from core.outputs import report_docx
                        tmpdir = Path(tempfile.mkdtemp())
                        try:
                            tmp = tmpdir / (name + ".docx")
                            report_docx(rep, tmp, images)
                            dest = self.window.create_file_dialog(getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG, save_filename=name + ".docx")
                            if not dest:
                                return False
                            dest = dest if isinstance(dest, str) else dest[0]
                            shutil.copy(str(tmp), dest)
                            return True
                        finally:
                            shutil.rmtree(tmpdir, ignore_errors=True)
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
