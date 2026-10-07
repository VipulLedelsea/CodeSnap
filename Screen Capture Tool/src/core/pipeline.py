import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core import deepdive

DRAFT_MODEL = os.environ.get("CODESNAP_DRAFT_MODEL", "claude-haiku-4-5")
FINAL_MODEL = os.environ.get("CODESNAP_FINAL_MODEL", "claude-sonnet-5")
MAX_CLAIMS = 60


def staged() -> bool:
    return os.environ.get("CODESNAP_PIPELINE", "").lower() == "staged"


def claims_from(dd: dict) -> list:
    out = []
    for f in (dd or {}).get("facts") or []:
        lines = f.get("lines") or [0, 0]
        out.append(f"[{f.get('category', '?')}, lines {lines[0]}-{lines[-1]}] {f.get('statement', '')}")
    return out[:MAX_CLAIMS]


def _build(store, draft):
    from core import report
    pkg = report.cached_package(store, force=True)
    if draft:
        out = Path(pkg["dir"])
        slug = store.info["slug"]
        src = out / f"{slug}_assessment_report.docx"
        if src.exists():
            shutil.copyfile(src, out / f"{slug}_assessment_report_DRAFT.docx")
    return pkg


def _draft_bytes(store):
    from core import report
    out = Path(report.cached_package(store)["dir"])
    f = out / f"{store.info['slug']}_assessment_report_DRAFT.docx"
    return f.read_bytes() if f.exists() else None


def _final_bytes(store):
    from core import report
    out = Path(report.cached_package(store)["dir"])
    f = out / f"{store.info['slug']}_assessment_report.docx"
    return f.read_bytes() if f.exists() else None


def _job(store, state, **extra):
    store.set_meta("pipeline_job", {**(store.get_meta("pipeline_job") or {}), "state": state,
                                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra})


def interrupted(root=None) -> list:
    from core.model import ProgramStore
    from core.model.workspace import programs_root
    out = []
    for d in sorted(p for p in programs_root(root).iterdir() if p.is_dir()):
        try:
            with ProgramStore.open(d.name, root=root) as st:
                if (st.get_meta("pipeline_job") or {}).get("state") == "running":
                    out.append(d.name)
        except Exception:  # noqa: BLE001
            continue
    return out


def run_staged(store, client, progress=None, report=True) -> dict:
    _job(store, "running", started=(store.get_meta("pipeline_job") or {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        res = _run_staged(store, client, progress, report)
    except BaseException:
        raise
    _job(store, "done" if res["complete"] else "partial", errors=len(res["errors"]))
    try:
        from core.notify import notify
        notify("CodeSnap", "Your report is ready." if res["complete"] else "Analysis finished with some files unfinished.")
    except Exception:  # noqa: BLE001
        pass
    return res


def _run_staged(store, client, progress=None, report=True) -> dict:
    """Stage 1: cheap model reads every file, draft report. Stage 2: stronger model re-reads each file against the
    draft's claims, reviews them, decides what needs a rescan, and the final report is built from that."""
    errors = []
    store.set_meta("analysis_stage", "draft")
    first = deepdive.run(store, client, model=DRAFT_MODEL, review=False, program=False, stage="draft", progress=progress)
    errors += first["errors"]
    draft_pkg = None
    if report:
        try:
            draft_pkg = _build(store, draft=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"draft report: {type(exc).__name__}: {exc}"[:240])
    dd = store.get_meta("deepdive") or {}
    store.set_meta("deepdive_draft", dd)
    ids = [a["id"] for a in store.artifacts() if (dd.get(str(a["id"])) or {}).get("stage") == "draft"]
    claims = {i: claims_from(dd.get(str(i))) for i in ids}
    draft_docx = _draft_bytes(store) if draft_pkg else None

    def _rescan():
        if not draft_docx:
            return {}
        from core import report_review
        return report_review.run(store, client, draft_docx, model=FINAL_MODEL)

    with ThreadPoolExecutor(max_workers=2) as pool:
        scan = pool.submit(_rescan)
        second = deepdive.run(store, client, artifact_ids=ids, force=True, model=FINAL_MODEL,
                              review_model=deepdive.DEFAULT_REVIEW_MODEL, claims=claims, stage="final", program=True,
                              progress=progress)
        try:
            scan.result()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"report re-read: {type(exc).__name__}: {exc}"[:240])
    errors += second["errors"]
    dd = store.get_meta("deepdive") or {}
    complete = bool(ids) and all((dd.get(str(i)) or {}).get("stage") == "final" for i in ids)
    store.set_meta("analysis_stage", "final" if complete else "draft")
    final_pkg = None
    if report:
        try:
            final_pkg = _build(store, draft=not complete)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"final report: {type(exc).__name__}: {exc}"[:240])
    inconsistencies = []
    final_docx = _final_bytes(store) if final_pkg else None
    if final_docx:
        try:
            from core import report_consistency
            inconsistencies = report_consistency.run(store, client, final_docx, model=FINAL_MODEL)["items"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"report consistency: {type(exc).__name__}: {exc}"[:240])
    return {"draft_files": first["analysed"], "final_files": second["analysed"], "errors": errors,
            "inconsistencies": inconsistencies,
            "rescan": deepdive.rescan_requests(store), "complete": complete,
            "report_review": store.get_meta("report_review") and len(store.get_meta("report_review")), "draft_report": bool(draft_pkg), "final_report": bool(final_pkg)}
