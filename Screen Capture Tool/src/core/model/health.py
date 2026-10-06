"""Pipeline health for one program: failed / partial / unverified files, API errors, spend vs budget."""
from .completeness import check as completeness


def _first_line(text, n=160):
    line = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    return line[:n]


def pipeline_health(store) -> dict:
    from core.usage import program_budget
    arts = store.artifacts()
    runs = store.runs()
    last_error = {}
    for r in runs:
        if r["artifact_id"] and not r["ok"] and r["error"]:
            last_error[r["artifact_id"]] = r["error"]
    failed, partial, invalid, unverified, waiting = [], [], [], [], []
    pending = store.pending_captures()
    for a in arts:
        if a["status"] == "captured":
            waiting.append({"id": a["id"], "name": a["name"], "reason": "saved; analysis not finished yet"})
            continue
        if a["status"] == "failed" and (pending.get(a["id"]) or {}).get("error"):
            failed.append({"id": a["id"], "name": a["name"], "reason": _first_line(pending[a["id"]]["error"])})
            continue
        if a["status"] == "failed":
            failed.append({"id": a["id"], "name": a["name"], "reason": _first_line(last_error.get(a["id"])) or
                           "could not be structured (no parser matched and the API step failed)"})
            continue
        text = a.get("transcription") or ""
        if not text.strip():
            continue
        c = completeness(text, a["name"], a.get("language") or "")
        if c["partial"]:
            from .completeness import end_reached, drop_end_reasons
            if end_reached(store, a):
                c = drop_end_reasons(c)
        if c["partial"]:
            partial.append({"id": a["id"], "name": a["name"], "reasons": c["reasons"]})
    parsers = ("cobol-parser", "ts-parser", "extractors", "langpacks")
    local_steps = ("security_scan", "assessment", "ui_review")
    is_parser = lambda r: str(r["model"] or r["prompt_version"] or "").startswith(parsers)
    api = [r for r in runs if not is_parser(r) and r["step"] not in local_steps and ((r["input_tokens"] or 0) > 0 or not r["ok"])]
    api_fail = [r for r in api if not r["ok"]]
    failed_ids = {r["artifact_id"] for r in api_fail if r["artifact_id"]}
    fallbacks = sum(1 for aid in failed_ids if any(r["artifact_id"] == aid and r["ok"] and is_parser(r) for r in runs))
    spent = round(sum(r["cost"] or 0 for r in api), 4)
    limit = program_budget(store)
    local_errors = []
    for step in local_steps:
        oks = [r["id"] for r in runs if r["step"] == step and r["ok"]]
        since = oks[-2] if len(oks) >= 2 else 0
        local_errors += [{"step": step, "error": _first_line(r["error"], 220)} for r in runs
                         if r["step"] == step and not r["ok"] and r["id"] > since]
    issues = len(failed) + len(partial) + len(invalid) + len(local_errors) + len(waiting)
    return {
        "status": "ok" if not issues else ("attention" if not failed else "errors"),
        "files": len(arts), "analysis_errors": local_errors[-10:], "failed": failed, "partial": partial, "invalid": invalid, "unverified": unverified,
        "waiting": waiting,
        "api": {"calls": len(api), "failures": len(api_fail), "cost": spent,
                "recent_errors": [{"step": r["step"], "error": _first_line(r["error"])} for r in api_fail[-5:]],
                "fallbacks": fallbacks},
        "budget": {"limit": limit, "spent": spent, "remaining": round(limit - spent, 4) if limit else None},
    }
