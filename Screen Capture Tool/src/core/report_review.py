"""Re-read a finished report against the code. Each risk and debt claim in the report is checked by a stronger model
against the cited source file (or the verified findings, for claims that span files). Claims the code does not show
are removed from the next build; claims that only partly hold are kept with the correction."""
import hashlib
import io
import re
import time

from core import deepdive as D

CHUNK = 40
MODEL_ENV = "CODESNAP_FINAL_MODEL"
TOOL = {
    "name": "record_report_review",
    "description": "Record a verdict for each report claim.",
    "input_schema": {"type": "object", "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported", "cannot_check"]},
        "quote": {"type": "string", "description": "Exact text copied from the source that decides the verdict"},
        "lines": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
        "correction": {"type": "string", "description": "What the code actually shows, when the claim is partly right"},
        "absent_term": {"type": "string", "description": "For unsupported without a contradicting quote: a name, value or identifier the claim depends on that occurs nowhere in the file"},
        "finding": {"type": "integer", "description": "Claims spanning files: number of the finding that proves, corrects or contradicts the claim"},
        "why": {"type": "string"}}, "required": ["id", "verdict"]}}}, "required": ["verdicts"]},
}
SYSTEM = """You check claims from a draft assessment report against the source code they cite.
For each numbered claim decide:
- supported: the code shows it. Copy an exact quote from the code that proves it.
- partly: some of it holds. Say in `correction` what the code really shows, with an exact quote.
- unsupported: the code contradicts it (copy the contradicting code as the quote), or it depends on a specific name, value or identifier that occurs nowhere in the file (put that exact term, as written in the claim, in absent_term). If you can do neither, use cannot_check.
- cannot_check: the claim is about something outside the code (staff, owners, tests that were not supplied, run schedules, deployed versions, data volumes). Never mark these unsupported.
Lines marked with a warning sign were not read reliably; do not rest a verdict on them.
Judge only what the code shows. Do not invent behaviour.
Claims can be any statement the report makes about the program: what a file does, counts, dependencies, data flow, risks, recommendations that rest on code facts. Statements that are generic advice or about the people and process around the code are cannot_check."""
PROGRAM_SYSTEM = """You check claims from a draft assessment report against findings that were already verified against the source code of several files. The findings are a partial list.
For each numbered claim decide:
- supported: the findings show it. Give the finding's number in `finding`.
- partly: some of it holds. Say in `correction` what the findings show and give the finding's number in `finding`.
- unsupported: a finding contradicts it. Give that finding's number in `finding` and say in `why` how it contradicts. If no finding contradicts it, use cannot_check.
- cannot_check: the findings neither show nor contradict it, or it is about something outside the code (staff, owners, tests that were not supplied, run schedules, deployed versions, data volumes).
Judge only what the findings show. Do not invent behaviour."""
TABLES = (("Risk ID", "risk"), ("Debt ID", "debt"), ("Vuln ID", "vuln"))


def claim_key(text) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text or "").strip().lower().encode()).hexdigest()[:16]


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _absent(term, claim, text):
    t = _norm(term).lower()
    return len(t) >= 4 and t in _norm(claim).lower() and t not in _norm(text).lower()


def gate(v, claim, text=None, findings=0):
    verdict = v.get("verdict", "cannot_check")
    if verdict not in ("supported", "partly", "unsupported"):
        return "cannot_check"
    if text is None:
        finding = v.get("finding")
        return verdict if isinstance(finding, int) and 1 <= finding <= findings else "cannot_check"
    if verdict == "unsupported":
        return verdict if _quote_ok(v.get("quote"), text) or _absent(v.get("absent_term"), claim, text) else "cannot_check"
    return verdict if _quote_ok(v.get("quote"), text) else "cannot_check"


def claim_line(i, c):
    para = (c.get("para") or "").strip()
    return f"{i}. {c['text']}" + (f"\n   (paragraph: {para[:300]})" if para and para != c["text"] else "")


def risk_text(title, comps):
    return title + (f" ({', '.join(comps[:3])})" if comps else "")


SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
SKIP = re.compile(r"^(?:DRAFT:|Figure |Table |The draft report's|Source:|Note:)")
MAX_TEXT = 500


def sentences(text):
    return [x.strip() for x in SENT.split((text or "").strip()) if x.strip()]


def _keep(sentence):
    return len(sentence.split()) >= 7 and not SKIP.match(sentence)


def _named(text, names):
    return [n for n in names if n.lower() in text.lower()]


def extract_claims(docx_bytes, file_names):
    from docx import Document
    doc = Document(io.BytesIO(docx_bytes))
    names = sorted(file_names, key=len, reverse=True)
    out, seen = [], set()

    def add(kind, cid, text, files, para=""):
        k = claim_key(text)
        if k in seen or not text:
            return
        seen.add(k)
        out.append({"key": k, "kind": kind, "id": cid, "text": text, "files": files, "para": para})

    plain = []
    for table in doc.tables:
        if not table.rows:
            continue
        head = [c.text.strip() for c in table.rows[0].cells]
        kind = next((k for h, k in TABLES if head and head[0] == h), None)
        if not kind:
            plain.append(table)
            continue
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            text = f"{cells[1]}|{cells[7] if len(cells) > 7 else ''}" if kind == "vuln" else cells[1]
            if text and not text.lower().startswith("none"):
                add(kind, cells[0], text, _named(text, names))
    texts = []
    for p in doc.paragraphs:
        style = p.style.name if p.style is not None else ""
        if not style.startswith(("Heading", "Title", "Caption", "TOC")):
            texts.append(p.text)
    for table in plain:
        for row in table.rows[1:]:
            for cell in row.cells:
                texts.append(cell.text)
    for t in texts:
        for sent in sentences(t):
            if _keep(sent):
                add("text", "", sent[:MAX_TEXT], _named(sent, names), t)
    return out


def _quote_ok(quote, text):
    q = re.sub(r"\s+", " ", quote or "").strip()
    return bool(q) and q in re.sub(r"\s+", " ", text or "")


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_$#@-]{3,}")
_RANK = {"supported": 3, "partly": 2, "unsupported": 1}


def _claim_window(client_args, a, b):
    store, client, model, art, claims, q = client_args
    text = art.get("transcription") or ""
    n = len(text.split("\n"))
    shown = (a, b) != (1, n)
    note = (f"You are shown lines {max(a - D.SEGMENT_CONTEXT, 1)}-{min(b + D.SEGMENT_CONTEXT, n)} of {n}. Judge each claim from these "
            f"lines only; if they do not settle it, answer cannot_check.\n") if shown else ""
    listing = D.listing(text, q["bad_lines"], a - D.SEGMENT_CONTEXT, b + D.SEGMENT_CONTEXT) if shown else D.listing(text, q["bad_lines"])
    body = (f"File: {art['name']}\nLanguage: {art.get('language') or 'unknown'}\n{note}\n{listing}\n\nClaims:\n"
            + "\n".join(claim_line(i, c) for i, c in enumerate(claims, 1)))
    msg, ms = D._call(client, model, SYSTEM, TOOL, body)
    D._log(store, "report_review", art["id"], model, msg, ms)
    return {int(v["id"]): v for v in (D._tool(msg, TOOL["name"]) or {}).get("verdicts") or []
            if isinstance(v, dict) and str(v.get("id", "")).isdigit()}


def _assign(claims, text, windows, per_claim=2):
    """For a long file: the windows each claim is sent to, chosen by the names and values it shares with the code there.
    A name found in few windows counts for more than one found everywhere."""
    lines = text.split("\n")
    sets = [set(w.upper() for w in _WORD.findall("\n".join(lines[a - 1:b]))) for a, b in windows]
    seen_in = {}
    for st in sets:
        for w in st:
            seen_in[w] = seen_in.get(w, 0) + 1
    out = []
    for c in claims:
        words = {w.upper() for w in _WORD.findall(c["text"])}
        score = [sum(1.0 / seen_in[w] for w in words if w in st) for st in sets]
        out.append([i for i in sorted(range(len(windows)), key=lambda i: -score[i])[:per_claim] if score[i] > 0])
    return out


def _ask(store, client, model, art, claims):
    text = art.get("transcription") or ""
    q = D.capture_quality(store, art)
    n = len(text.split("\n"))
    if n <= D.SEGMENT_LINES * 1.25:
        got = _claim_window((store, client, model, art, claims, q), 1, n)
    else:
        windows = D.segments(n)
        where = _assign(claims, text, windows)
        jobs = []
        for wi, (a, b) in enumerate(windows):
            ids = [i for i, ws in enumerate(where) if wi in ws]
            if ids:
                jobs.append((a, b, ids))

        def one(job):
            a, b, ids = job
            res = _claim_window((store, client, model, art, [claims[i] for i in ids], q), a, b)
            return {ids[k - 1]: v for k, v in res.items() if 1 <= k <= len(ids)}
        got = {}
        for part in D.parallel(one, jobs):
            for i, v in part.items():
                if _RANK.get(v.get("verdict"), 0) > _RANK.get((got.get(i) or {}).get("verdict"), 0):
                    got[i] = v
        got = {i + 1: v for i, v in got.items()}
    out = {}
    for i, c in enumerate(claims, 1):
        v = got.get(i) or {"verdict": "cannot_check"}
        verdict = gate(v, c["text"], text=text)
        out[c["key"]] = {"verdict": verdict, "correction": (v.get("correction") or "")[:300], "why": (v.get("why") or "")[:300],
                         "file": art["name"], "lines": v.get("lines"), "id": c["id"], "kind": c["kind"]}
    return out


def fair_facts(dd, names, cap, per_file_min=3):
    """Lines like '[n] file lines a-b: statement' from every reviewed file, most serious first and an equal share per file,
    so a long first file cannot crowd out the others."""
    sev = {"high": 0, "medium": 1, "low": 2, "info": 3}
    per = {}
    for k, r in dd.items():
        fs = sorted(r.get("facts") or [], key=lambda f: (sev.get(f.get("severity"), 4), (f.get("lines") or [0])[0]))
        per[k] = fs
    share = max(per_file_min, cap // max(len(per), 1))
    picked = [(k, f) for k, fs in per.items() for f in fs[:share]]
    extra = [(k, f) for k, fs in per.items() for f in fs[share:]]
    picked += sorted(extra, key=lambda kf: sev.get(kf[1].get("severity"), 4))[:max(cap - len(picked), 0)]
    out = []
    for k, f in picked[:cap]:
        lines = f.get("lines") or [0, 0]
        out.append(f"[{len(out) + 1}] {names.get(k, k)} lines {lines[0]}-{lines[-1]}: {f.get('statement', '')}")
    return out


def _ask_program(store, client, model, claims):
    dd = store.get_meta("deepdive") or {}
    names = {str(a["id"]): a["name"] for a in store.artifacts()}
    facts = fair_facts(dd, names, 600)
    body = ("Source findings already checked against quotes in the code:\n" + "\n".join(facts)
            + "\n\nClaims (these span several files; decide from the findings above):\n"
            + "\n".join(claim_line(i, c) for i, c in enumerate(claims, 1)))
    msg, ms = D._call(client, model, PROGRAM_SYSTEM, TOOL, body)
    D._log(store, "report_review", None, model, msg, ms)
    got = {int(v["id"]): v for v in (D._tool(msg, TOOL["name"]) or {}).get("verdicts") or []
           if isinstance(v, dict) and str(v.get("id", "")).isdigit()}
    out = {}
    for i, c in enumerate(claims, 1):
        v = got.get(i) or {}
        verdict = gate(v, c["text"], findings=len(facts))
        out[c["key"]] = {"verdict": verdict, "correction": (v.get("correction") or "")[:300], "why": (v.get("why") or "")[:300],
                         "file": None, "lines": None, "id": c["id"], "kind": c["kind"]}
    return out


def run(store, client, report_docx, model=None) -> dict:
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from core import pipeline
    model = model or os.environ.get(MODEL_ENV) or pipeline.FINAL_MODEL
    arts = {a["name"]: a for a in store.artifacts() if (a.get("transcription") or "").strip()}
    claims = extract_claims(report_docx, list(arts))
    by_file, spanning = {}, []
    for c in claims:
        (by_file.setdefault(c["files"][0], []) if len(c["files"]) == 1 else spanning).append(c)
    verdicts, errors = {}, []
    with ThreadPoolExecutor(max_workers=12) as pool:
        jobs = [pool.submit(_ask, store, client, model, arts[n], cs[i:i + CHUNK])
                for n, cs in by_file.items() for i in range(0, len(cs), CHUNK)]
        jobs += [pool.submit(_ask_program, store, client, model, spanning[i:i + CHUNK]) for i in range(0, len(spanning), CHUNK)]
        for j in as_completed(jobs):
            try:
                verdicts.update(j.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"report review: {type(exc).__name__}: {exc}"[:240])
    with D._META_LOCK:
        store.set_meta("report_review", {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "verdicts": verdicts})
    counts = {}
    for v in verdicts.values():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    return {"claims": len(claims), "counts": counts, "errors": errors}


def verdicts(store) -> dict:
    return (store.get_meta("report_review") or {}).get("verdicts") or {}


def summary_line(store):
    v = verdicts(store)
    if not v:
        return ""
    c = {}
    for x in v.values():
        c[x["verdict"]] = c.get(x["verdict"], 0) + 1
    return (f"{sum(c.values())} statements in the draft report were checked against the code: {c.get('supported', 0)} confirmed, "
            f"{c.get('partly', 0)} partly right (corrected), {c.get('unsupported', 0)} contradicted or not shown by the code (removed), "
            f"{c.get('cannot_check', 0)} could not be checked from the code alone (people, schedules, volumes or other files).")


def apply_to_docx(document, store):
    v = verdicts(store)
    if not v:
        return {"removed": 0, "corrected": 0}
    changed = {"removed": 0, "corrected": 0}

    def fix(par):
        text = par.text
        if not text.strip() or not par.runs:
            return
        parts, edited = [], False
        for sent in sentences(text):
            r = v.get(claim_key(sent[:MAX_TEXT])) if _keep(sent) else None
            if r and r.get("verdict") == "unsupported":
                changed["removed"] += 1
                edited = True
                continue
            if r and r.get("verdict") == "partly" and r.get("correction"):
                sent = f"{sent} Code check: {r['correction'].strip()}"
                changed["corrected"] += 1
                edited = True
            parts.append(sent)
        if edited:
            par.runs[0].text = " ".join(parts) if parts else "Removed after the code check: not shown by the code."
            for r_ in par.runs[1:]:
                r_.text = ""

    for p in document.paragraphs:
        style = p.style.name if p.style is not None else ""
        if not style.startswith(("Heading", "Title", "Caption", "TOC")):
            fix(p)
    for table in document.tables:
        head = table.rows[0].cells[0].text.strip() if table.rows else ""
        if any(head == h for h, _ in TABLES):
            continue
        for row in table.rows[1:]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    fix(p)
    return changed
