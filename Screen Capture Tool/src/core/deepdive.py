"""Deep code analysis: a line-by-line review of every file by the strongest model, held to the evidence.

Three rules keep it truthful:
1. Every fact cites line numbers and a verbatim quote from those lines. The quote is checked against the file; a fact
   whose quote is not in the file is rejected, and one whose quote is on other lines has its lines corrected.
2. A second, independent pass re-reads the code and marks each fact supported, partly supported (with a corrected
   statement) or unsupported; unsupported facts are dropped.
3. Lines the capture could not read reliably are marked in the listing; a fact that rests only on them is set aside
   as unverifiable, and the file is flagged for a rescan with the reason and what to do.

The program-level synthesis may only combine facts that survived; each observation must cite fact ids that exist.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone

PROMPT_VERSION = "deepdive-v1"
MAX_TOKENS = 20000   # the SDK refuses non-streamed calls much above this
THINKING = 8000
CATEGORIES = ["purpose", "business_rule", "calculation", "data_read", "data_write", "interface", "control_flow",
              "error_handling", "security", "data_integrity", "defect", "dependency", "configuration", "ui"]
SEVERITIES = ["high", "medium", "low", "info"]

DEEP_SYSTEM = """You are a senior software architect performing a forensic, line-by-line review of ONE source file from
a legacy business application. An enterprise architect will rely on your findings without re-reading the code, so
accuracy matters more than anything else.

You receive the file with a line number before every line ("  12| code"). Lines marked "⚠" could not be read
reliably from the screen capture: do not base any fact only on them.

Read EVERY line. Then call the record_analysis tool once with:

purpose: what this file does, in two or three plain sentences, with line references like "(lines 5-40)".

facts: an exhaustive list. Cover every program section, paragraph, function or method; every file, table, record or
screen read or written (with the fields where shown); every calculation, formula, constant, rate and threshold;
every condition that changes behaviour; every call to another program, service or system; every error path and
what happens on failure; every security weakness; anything that could corrupt or lose data; and defects such as
fields that are computed but never used, totals never written, conditions that can never be true, or unhandled
cases. Each fact has:
  - category: one of the listed categories
  - statement: one specific, plain-English sentence with the real names and values from the code
  - lines: [first, last] line numbers that show it
  - quote: text copied EXACTLY, character for character, from one of those lines (at least 8 characters). Do not
    correct typos, spacing or case in the quote.
  - basis: "observed" if the code states it directly; "inferred" if it is a conclusion you drew (then give the
    reasoning in one sentence)
  - reasoning: required when basis is "inferred"
  - severity: for security, data_integrity and defect facts (high, medium, low or info)

unknowns: things this file depends on but does not show (programs it calls, tables it uses whose definitions are
not here, values set elsewhere), each with the line where it is referenced. Put anything you are unsure of here
instead of in facts.

capture_concerns: lines that look mis-read or incomplete (a statement cut off, characters that cannot be right,
a structure that does not close), with the line and the reason.

Rules:
- Record ONLY what this code shows. Never invent names, values, systems, owners, volumes, frequencies or behaviour.
- Do not guess what other programs do. Do not describe typical behaviour of a language or product as a fact about
  this file.
- If two readings are possible, say so in the statement or leave the fact out.
- Prefer many precise facts to a few general ones."""

REVIEW_SYSTEM = """You are checking another reviewer's findings about ONE source file, as an independent auditor.
You receive the numbered file and a list of findings, each with an id, a statement and the lines it cites.
For each finding decide, from the cited lines and the rest of the file only:
  - "supported": the statement is fully correct as written
  - "partly": part of it is wrong or overstated; give a corrected statement that is fully supported
  - "unsupported": the code does not show it
Be strict: names, values, conditions and what happens must match the code exactly. Call record_review once."""

SYNTH_SYSTEM = """You combine verified findings from several source files of one application into cross-file
observations for an enterprise architect: the same business rule or constant implemented in more than one place
(and whether the values agree), data handed from one component to another, inconsistent handling of the same
entity, and end-to-end flows. You may ONLY use the findings given; every observation must cite the ids of the
findings it rests on, and must not add facts that are not in them. If nothing crosses files, return no observations.
Call record_program once."""

ANALYSIS_TOOL = {
    "name": "record_analysis",
    "description": "Record the forensic analysis of the file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "object", "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "statement": {"type": "string"},
                "lines": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2},
                "quote": {"type": "string"},
                "basis": {"type": "string", "enum": ["observed", "inferred"]},
                "reasoning": {"type": "string"},
                "severity": {"type": "string", "enum": SEVERITIES}},
                "required": ["category", "statement", "lines", "quote", "basis"]}},
            "unknowns": {"type": "array", "items": {"type": "object", "properties": {
                "what": {"type": "string"}, "line": {"type": ["integer", "null"]}}, "required": ["what"]}},
            "capture_concerns": {"type": "array", "items": {"type": "object", "properties": {
                "line": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["line", "reason"]}},
        },
        "required": ["purpose", "facts"],
    },
}
REVIEW_TOOL = {
    "name": "record_review",
    "description": "Record the verdict on each finding.",
    "input_schema": {"type": "object", "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"}, "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported"]},
        "corrected": {"type": "string"}, "why": {"type": "string"}}, "required": ["id", "verdict"]}}},
        "required": ["verdicts"]},
}
PROGRAM_TOOL = {
    "name": "record_program",
    "description": "Record the cross-file observations.",
    "input_schema": {"type": "object", "properties": {"observations": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "statement": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        "required": ["title", "statement", "facts"]}}}, "required": ["observations"]},
}


# ── capture quality ─────────────────────────────────────────────────────────────────────────────────────────────

ADVICE = {
    "cut": "the line runs past the edge of the screen: widen the window or scroll right and capture the rest",
    "break": "the screens did not overlap here, so lines may be missing: scroll back and capture this part again",
    "mismatch": "the text did not match the pixels on screen: zoom in or enlarge the font and capture again",
    "partial": "the file looks incomplete: capture the missing start or end",
    "compile": "the code does not compile as captured, which often means a mis-read: check and recapture these lines",
    "model": "the reviewer found text that cannot be right as captured: recapture these lines",
}


REPORT_REASON = {"cut": "lines cut short in the copy provided", "break": "lines may be missing from the copy provided",
                 "mismatch": "characters that may be wrong in the copy provided", "compile": "does not compile as provided",
                 "model": "text that cannot be right as provided"}


def report_reason(issue):
    """The same issue in words for the client report, which never refers to how the source was obtained."""
    return REPORT_REASON.get(issue["kind"]) or issue["reason"]


def _ranges(nums):
    nums = sorted(set(n for n in nums if n))
    out = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [f"{a}" if a == b else f"{a}–{b}" for a, b in out]


def capture_quality(store, art, concerns=None) -> dict:
    """{status: good | rescan | unchecked, issues: [{kind, lines, reason, advice}], bad_lines: set}"""
    from core.model.completeness import check
    text = art.get("transcription") or ""
    lines = text.split("\n")
    issues, bad = [], set()
    ver = store.verification(art["id"]) or {}
    by_kind = {}
    from core.verify import REASONS
    kind_of = {v: k for k, v in REASONS.items()}
    for f in ver.get("flags") or []:
        k = kind_of.get(f.get("reason"), "mismatch")
        if k in ("wrapped", "edited"):
            k = "mismatch"
        by_kind.setdefault(k, []).append(f["line"])
    for i, l in enumerate(lines, 1):
        if "[CUT OFF]" in l:
            by_kind.setdefault("cut", []).append(i)
    for k, ls in by_kind.items():
        bad.update(ls)
        issues.append({"kind": k, "lines": _ranges(ls), "reason": {"cut": "text cut off at the screen edge",
                                                                   "break": "possible gap between screens",
                                                                   "mismatch": "text may be mis-read"}[k],
                       "advice": ADVICE[k]})
    if art.get("artifact_type") in (None, "code"):
        c = check(text, art["name"], art.get("language") or "",
                  art.get("validation_errors") if art.get("validation_ok") == 0 else "")
        if c["partial"]:
            issues.append({"kind": "partial", "lines": [], "reason": "; ".join(c["reasons"]), "advice": ADVICE["partial"]})
        if art.get("validation_ok") == 0 and (art.get("validation_errors") or "").strip() not in ("", "None"):
            nums = [int(n) for n in re.findall(r"(?:line|:)\s*(\d{1,5})\b", art["validation_errors"])[:20]
                    if 0 < int(n) <= len(lines)]
            issues.append({"kind": "compile", "lines": _ranges(nums), "reason": art["validation_errors"].strip().splitlines()[0][:160],
                           "advice": ADVICE["compile"]})
    for c in concerns or []:
        ln = c.get("line")
        if isinstance(ln, int) and 0 < ln <= len(lines):
            bad.add(ln)
    if concerns:
        issues.append({"kind": "model", "lines": _ranges([c.get("line") for c in concerns if isinstance(c.get("line"), int)]),
                       "reason": "; ".join(c.get("reason", "") for c in concerns[:3])[:240], "advice": ADVICE["model"]})
    status = "rescan" if any(i["kind"] in ("cut", "break", "mismatch", "partial", "model") for i in issues) else \
        "unchecked" if not ver and art.get("artifact_type") in (None, "code") else "good"
    if status == "good" and any(i["kind"] == "compile" for i in issues):
        status = "rescan"
    return {"status": status, "issues": issues, "bad_lines": sorted(bad), "verified": bool(ver)}


def rescan_requests(store) -> list:
    """Files whose capture is not good enough to rely on, with what to recapture and how."""
    dd = store.get_meta("deepdive") or {}
    out = []
    for a in store.artifacts():
        if not (a.get("transcription") or "").strip():
            continue
        q = capture_quality(store, a, (dd.get(str(a["id"])) or {}).get("capture_concerns"))
        if q["status"] == "rescan":
            out.append({"artifact_id": a["id"], "name": a["name"], "issues": q["issues"]})
    return out


# ── the per-file analysis ───────────────────────────────────────────────────────────────────────────────────────

def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def listing(text, bad=()):
    lines = text.split("\n")
    w = len(str(len(lines)))
    bad = set(bad)
    return "\n".join(f"{'⚠' if i in bad else ' '}{str(i).rjust(w)}| {l}" for i, l in enumerate(lines, 1))


def _tool(message, name):
    for b in getattr(message, "content", []) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == name:
            return dict(getattr(b, "input", {}) or {})
    text = "".join(getattr(b, "text", "") or "" for b in getattr(message, "content", []) or [] if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None
    return None


def _call(client, model, system, tool, content, thinking=True):
    """One call with extended thinking (the model reasons before it answers); falls back without it."""
    base = dict(model=model, max_tokens=MAX_TOKENS, system=system, tools=[tool], timeout=600,
                messages=[{"role": "user", "content": content + f"\n\nCall {tool['name']} once with your complete answer."}])
    began = time.monotonic()
    if thinking:
        try:
            msg = client.messages.create(thinking={"type": "enabled", "budget_tokens": THINKING},
                                         tool_choice={"type": "auto"}, **base)
            return msg, int((time.monotonic() - began) * 1000)
        except Exception as exc:  # noqa: BLE001
            if not re.search(r"thinking|budget|tool_choice|unsupported|invalid", str(exc), re.I):
                raise
    try:
        msg = client.messages.create(tool_choice={"type": "tool", "name": tool["name"]}, **base)
    except Exception as exc:  # noqa: BLE001
        if "tool_choice" not in str(exc):
            raise
        msg = client.messages.create(tool_choice={"type": "auto"}, **base)
    return msg, int((time.monotonic() - began) * 1000)


def _log(store, step, artifact_id, model, msg, ms):
    from core.usage import cost as usage_cost
    u = getattr(msg, "usage", None)
    i, o = getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)
    store.log_run(step, artifact_id=artifact_id, model=model, prompt_version=PROMPT_VERSION, input_tokens=i,
                  output_tokens=o, ms=ms, cost=usage_cost(model, i, o),
                  ok=getattr(msg, "stop_reason", None) != "max_tokens",
                  error="output truncated (max_tokens)" if getattr(msg, "stop_reason", None) == "max_tokens" else None)


def _occurrences(q, lines):
    """Every place the (whitespace-normalised) quote occurs, as (first line, last line); quotes may span up to 4 lines."""
    n, out = len(lines), []
    for i in range(1, n + 1):
        if q not in _norm(" ".join(lines[i - 1:i + 3])):
            continue
        if i < n and q in _norm(" ".join(lines[i:i + 3])) and q not in _norm(lines[i - 1]):
            continue
        j = next(j for j in range(i, min(n, i + 3) + 1) if q in _norm(" ".join(lines[i - 1:j])))
        if not out or out[-1] != (i, j):
            out.append((i, j))
    return out


def check_facts(facts, text, bad=()):
    """Hold each fact to the file: the quote must be in the file. Returns (kept, corrected, rejected, unverifiable)."""
    lines = text.split("\n")
    n = len(lines)
    bad = set(bad)
    kept, rejected, unverifiable, corrected = [], [], [], 0
    for f in facts or []:
        if not isinstance(f, dict) or not f.get("statement") or f.get("category") not in CATEGORIES:
            rejected.append({**(f if isinstance(f, dict) else {}), "why": "malformed"})
            continue
        ls = [int(x) for x in (f.get("lines") or []) if isinstance(x, (int, float)) or str(x).isdigit()][:2]
        q = _norm(f.get("quote"))
        if len(q) < 4:
            rejected.append({**f, "why": "no quote"})
            continue
        if f.get("basis") == "inferred" and not (f.get("reasoning") or "").strip():
            rejected.append({**f, "why": "inferred without reasoning"})
            continue
        a, b = (ls + ls)[:2] if ls else (0, 0)
        a, b = min(a, b), max(a, b)
        cited = _norm(" ".join(lines[max(0, a - 1):min(n, b)])) if a else ""
        if not (a and q in cited):
            spans = _occurrences(q, lines)
            if not spans:
                rejected.append({**f, "why": "quote not found in the file"})
                continue
            a, b = min(spans, key=lambda sp: abs(sp[0] - a) if a else sp[0])
            corrected += 1
        f = {**f, "lines": [a, b], "quote": f.get("quote").strip()}
        if all(i in bad for i in range(a, b + 1)):
            unverifiable.append({**f, "why": "rests only on lines the capture could not read reliably"})
            continue
        kept.append(f)
    return kept, corrected, rejected, unverifiable


def analyse_file(store, client, art, model=None, review=True) -> dict:
    from core.analysis import MODEL
    model = model or MODEL
    text = art.get("transcription") or ""
    q0 = capture_quality(store, art)
    header = (f"File: {art['name']}\nLanguage: {art.get('language') or 'unknown'}\n"
              f"Lines: {len(text.splitlines())}\n"
              + (f"Lines marked ⚠ are unreliable ({', '.join(_ranges(q0['bad_lines'])[:20])}).\n"
                 if q0["bad_lines"] else ""))
    msg, ms = _call(client, model, DEEP_SYSTEM, ANALYSIS_TOOL, header + "\n" + listing(text, q0["bad_lines"]))
    _log(store, "deepdive", art["id"], model, msg, ms)
    data = _tool(msg, ANALYSIS_TOOL["name"]) or {}
    concerns = [c for c in data.get("capture_concerns") or [] if isinstance(c, dict)]
    q = capture_quality(store, art, concerns)
    kept, corrected, rejected, unverifiable = check_facts(data.get("facts"), text, q["bad_lines"])
    reviewed = {"supported": 0, "partly": 0, "unsupported": 0}
    if review and kept:
        for i, f in enumerate(kept, 1):
            f["id"] = i
        payload = "\n".join(f"{f['id']}. [{f['category']}] {f['statement']} (lines {f['lines'][0]}-{f['lines'][1]})" for f in kept)
        rmsg, rms = _call(client, model, REVIEW_SYSTEM, REVIEW_TOOL,
                          f"File: {art['name']}\n\n{listing(text, q['bad_lines'])}\n\nFindings:\n{payload}")
        _log(store, "deepdive_review", art["id"], model, rmsg, rms)
        verdicts = {int(v["id"]): v for v in (_tool(rmsg, REVIEW_TOOL["name"]) or {}).get("verdicts") or []
                    if isinstance(v, dict) and str(v.get("id", "")).isdigit()}
        final = []
        for f in kept:
            v = verdicts.get(f["id"])
            if v is None:
                f["review"] = "not reviewed"
                final.append(f)
                continue
            reviewed[v["verdict"]] = reviewed.get(v["verdict"], 0) + 1
            if v["verdict"] == "unsupported":
                rejected.append({**f, "why": "the independent review found it unsupported: " + (v.get("why") or "")})
                continue
            if v["verdict"] == "partly" and (v.get("corrected") or "").strip():
                f = {**f, "statement": v["corrected"].strip(), "review": "corrected"}
            else:
                f["review"] = v["verdict"]
            final.append(f)
        kept = final
    for i, f in enumerate(kept, 1):
        f["id"] = i
    purpose = (data.get("purpose") or "").strip()
    return {"artifact_id": art["id"], "name": art["name"], "version": art.get("version"), "hash": _hash(text),
            "model": model, "prompt_version": PROMPT_VERSION, "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "purpose": purpose, "facts": kept, "unknowns": [u for u in data.get("unknowns") or [] if isinstance(u, dict)],
            "capture_concerns": concerns, "quality": {k: v for k, v in q.items() if k != "bad_lines"},
            "unverifiable": unverifiable, "rejected": len(rejected), "rejected_detail": rejected[:30],
            "corrected_lines": corrected, "reviewed": reviewed}


def _hash(text):
    return hashlib.sha1((text or "").encode()).hexdigest()[:16]


def pending(store) -> list:
    dd = store.get_meta("deepdive") or {}
    out = []
    for a in store.artifacts():
        if not (a.get("transcription") or "").strip() or a.get("status") in ("captured", "failed") \
                or a.get("artifact_type") in ("ui_screen", "document"):
            continue
        r = dd.get(str(a["id"]))
        if not r or r.get("hash") != _hash(a.get("transcription")) or r.get("prompt_version") != PROMPT_VERSION:
            out.append(a)
    return out


def synthesize(store, client, model=None) -> dict:
    from core.analysis import MODEL
    model = model or MODEL
    dd = store.get_meta("deepdive") or {}
    facts, index = [], {}
    for aid, r in dd.items():
        for f in r.get("facts") or []:
            fid = f"F{aid}.{f['id']}"
            index[fid] = (r["name"], f)
            facts.append(f"{fid} [{r['name']} lines {f['lines'][0]}-{f['lines'][1]}] ({f['category']}) {f['statement']}")
    if len(dd) < 2 or not facts:
        return {"observations": [], "ran_at": None}
    msg, ms = _call(client, model, SYNTH_SYSTEM, PROGRAM_TOOL, "Verified findings:\n" + "\n".join(facts[:1500]))
    _log(store, "deepdive_program", None, model, msg, ms)
    obs = []
    for o in (_tool(msg, PROGRAM_TOOL["name"]) or {}).get("observations") or []:
        ids = [x for x in (o.get("facts") or []) if x in index]
        if not ids or not o.get("statement"):
            continue
        files = sorted({index[x][0] for x in ids})
        obs.append({"title": o.get("title", "").strip(), "statement": o["statement"].strip(), "facts": ids,
                    "cites": [f"{index[x][0]} lines {index[x][1]['lines'][0]}–{index[x][1]['lines'][1]}" for x in ids],
                    "files": files})
    return {"observations": obs, "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model}


def run(store, client, artifact_ids=None, progress=None, force=False) -> dict:
    """Analyse every file that has no current deep analysis (or the ones given), then the program."""
    todo = [a for a in pending(store) if artifact_ids is None or a["id"] in artifact_ids]
    if artifact_ids and force:
        todo += [store.artifact(i) for i in artifact_ids if store.artifact(i) and store.artifact(i) not in todo]
    done, errors = 0, []
    for a in todo:
        try:
            res = analyse_file(store, client, a)
            dd = store.get_meta("deepdive") or {}
            dd[str(a["id"])] = res
            store.set_meta("deepdive", dd)
            done += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{a['name']}: {type(exc).__name__}: {exc}"[:240])
            store.log_run("deepdive", artifact_id=a["id"], prompt_version=PROMPT_VERSION, ok=False, error=errors[-1])
        if progress:
            progress(done + len(errors), len(todo))
    live = {str(a["id"]) for a in store.artifacts()}
    dd = {k: v for k, v in (store.get_meta("deepdive") or {}).items() if k in live}
    store.set_meta("deepdive", dd)
    if todo or not store.get_meta("deepdive_program"):
        try:
            store.set_meta("deepdive_program", synthesize(store, client))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"program synthesis: {type(exc).__name__}: {exc}"[:240])
    return {"analysed": done, "errors": errors, "files": len(dd)}
