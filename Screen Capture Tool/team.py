"""In-process multi-agent team (A2A) — Milestone 11.

A Coordinator delegates to three specialists, each with its OWN model, prompt,
and strictly limited capability. The agents "talk" by passing task inputs and
returning results — the same message shape the single-agent loop already uses,
just split by role.

  Coordinator  (Sonnet) — owns the goal, decides what to run, assembles + saves
                          the final report. Reads no screenshots itself.
  Extractor    (Haiku)  — reads the captures and returns a faithful, verbatim
                          transcription. Has NO fix/classify ability, so it
                          structurally cannot 'clean up' the code.
  Analyst      (Sonnet) — classifies + writes the plain-English overview and the
                          top-5 tech-stack review.
  Decoder  (Sonnet) — syntax/compile-checks the code and applies minimal,
                          error-only fixes. Nothing else.

The single-agent loop in agent.py is untouched; this is an opt-in path
(python agent.py --team, or a burst session launched with --team).
"""

import json
import tempfile
from pathlib import Path

import tools
from core import analysis, validate, outputs
from core.analysis import MODEL

MAX_ITERS = 10
MAX_TOKENS = 4096


# ── specialist agents ────────────────────────────────────────────────────────

def agent_extract(ctx) -> dict:
    """Extractor (Haiku). Reads every capture faithfully and returns:
      code   — the clean stitched transcription (overlaps de-duplicated)
      marked — the same content split by '===== Screenshot N =====' markers
               (lets the Analyst cite which screenshot each part came from)
    Faithfulness is structural: extraction goes through the Haiku OCR path and
    the returned code is the stitched cache, never a paraphrase."""
    parts = []
    for p in sorted(ctx.images):
        if ctx.cache_dir is not None:
            analysis.extract_to_cache(ctx.client, p, ctx.cache_dir)
            parts.append(analysis.cache_path_for(p, ctx.cache_dir).read_text())
        else:
            parts.append(analysis.extract_one(ctx.client, p))
    code = analysis.stitch_parts(parts)
    marked = "\n\n".join(f"===== Screenshot {i + 1} =====\n{t}" for i, t in enumerate(parts))
    return {"code": code, "marked": marked, "parts": parts}


ANALYST_SYSTEM = """You are the Analyst on a team. You receive a faithful transcription of on-screen content, split by '===== Screenshot N =====' markers. You do NOT edit the content — you describe it.

Return ONLY a JSON object (no prose, no code fences) with these keys:
  is_code    (boolean) — is the primary content source code?
  language   (string)  — e.g. "Python", "JavaScript", "C++" (empty if not code)
  extension  (string)  — file extension without a dot, e.g. "py", "js", "cpp" (empty if not code)
  overview   (string)  — a clear, plain-English summary a non-expert can follow. One sentence on what it does overall, then one short paragraph per main part in everyday language (briefly explain any technical term). Logical order, short sentences. Weave INLINE citations like "(Screenshot 1)" into the sentences using the markers.
  tech_stack (string)  — AT MOST the 5 most important issues, most critical first. State whether the code is up to date overall, then up to 5 concrete points on obsolete/deprecated patterns, APIs, or libraries and the modern replacement. If fully current, say so in one line. Empty string if not code.

Return JSON only."""


def agent_analyze(client, marked_text: str) -> dict:
    """Analyst (Sonnet). Classifies and writes the overview + tech-stack review."""
    base = analysis.synthesize_final(client, marked_text)  # reliable is_code/lang/ext/overview baseline
    out = {
        "is_code": base.get("is_code", False),
        "language": base.get("language", ""),
        "extension": base.get("extension", ""),
        "overview": base.get("overview", ""),
        "tech_stack": "",
    }
    if not marked_text.strip():
        return out
    try:
        msg = client.messages.create(
            model=MODEL, max_tokens=2048, system=ANALYST_SYSTEM,
            messages=[{"role": "user", "content": marked_text}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        data = analysis._parse_json(raw)
    except Exception:  # noqa: BLE001
        data = None
    if data:
        out["is_code"] = bool(data.get("is_code", out["is_code"]))
        out["language"] = str(data.get("language") or out["language"]).strip()
        out["extension"] = str(data.get("extension") or out["extension"]).strip().lstrip(".").lower()
        out["overview"] = str(data.get("overview") or out["overview"]).strip()
        out["tech_stack"] = str(data.get("tech_stack") or "").strip()
    return out


def _check(code: str, extension: str) -> dict:
    ext = outputs.safe_ext(extension or "txt")
    tmp = Path(tempfile.mktemp(suffix=f".{ext}"))
    tmp.write_text(code)
    try:
        return validate.check_source(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def agent_decoder(client, code: str, extension: str, language: str) -> dict:
    """Decoder (Sonnet). Checks the code AS CAPTURED, then applies a minimal,
    error-only fix if needed. Reports the REAL errors found (never invents), and
    whether the fix resolved them."""
    res = _check(code, extension)
    if not res.get("checked"):
        return {"errors": res.get("note") or "Not checked (no toolchain).",
                "code": code, "checked": False, "tool": res.get("tool", ""), "resolved": None}
    if res.get("ok"):
        return {"errors": "None", "code": code, "checked": True,
                "tool": res.get("tool", ""), "resolved": True}
    errors = res.get("errors", "")
    fixed = outputs.strip_code_fences(analysis.fix_source(client, code, language, errors))
    res2 = _check(fixed, extension)
    return {"errors": errors, "code": fixed, "checked": True, "tool": res.get("tool", ""),
            "resolved": bool(res2.get("ok")),
            "remaining": None if res2.get("ok") else res2.get("errors", "")}


# ── report assembly ──────────────────────────────────────────────────────────

def _assemble(language, overview, errors, code, tech_stack, extension, is_code) -> str:
    if is_code:
        return (f"**Language:** {language}\n"
                f"**Overview:** {overview}\n"
                f"**Errors found:** {errors or 'None'}\n"
                f"**Code:**\n```{extension or 'txt'}\n{code}\n```\n"
                f"**Tech-stack review:** {tech_stack or 'n/a'}")
    return (f"**Type:** {language or 'Document'}\n"
            f"**Overview:** {overview}\n\n{code}")


# ── coordinator tools (delegate to the specialists) ──────────────────────────

def _tc_get_transcription(client, ctx, scratch, _inp):
    ex = agent_extract(ctx)
    scratch["code"] = ex["code"]
    scratch["marked"] = ex["marked"]
    return ex["marked"] or "(no text found in the captures)"


def _tc_analyze(client, ctx, scratch, _inp):
    a = agent_analyze(client, scratch.get("marked") or scratch.get("code", ""))
    scratch["analysis"] = a
    scratch["is_code"] = a["is_code"]
    scratch["language"] = a["language"]
    scratch["extension"] = a["extension"] or "txt"
    return json.dumps(a)


def _tc_repair(client, ctx, scratch, _inp):
    if not scratch.get("is_code"):
        return "Content is not code — no repair needed."
    d = agent_decoder(client, scratch.get("code", ""),
                          scratch.get("extension", "txt"), scratch.get("language", ""))
    scratch["code"] = d["code"]        # fixed code becomes what we save
    scratch["errors"] = d["errors"]
    summary = {k: v for k, v in d.items() if k != "code"}
    return json.dumps(summary)


def _tc_finalize(client, ctx, scratch, inp):
    language = inp.get("language") or scratch.get("language", "")
    extension = inp.get("extension") or scratch.get("extension", "txt")
    overview = inp.get("overview", "")
    errors = inp.get("errors") or scratch.get("errors", "None")
    tech = inp.get("tech_stack", "")
    is_code = bool(scratch.get("is_code", True))
    code = scratch.get("code", "")
    scratch["report_md"] = _assemble(language, overview, errors, code, tech, extension, is_code)
    if is_code:
        saved = tools._t_save_output(ctx, {
            "format": "source", "content": code, "extension": extension,
            "language": language, "overview": overview, "errors": errors, "tech_stack": tech})
    else:
        fmt = "docx" if extension in ("docx", "doc") else "text"
        saved = tools._t_save_output(ctx, {"format": fmt, "content": code or overview})
    return f"Report assembled and saved. {saved}"


COORDINATOR_TOOLS = [
    {"name": "get_transcription",
     "description": "Delegate to the Extractor (Haiku): read every capture faithfully and return the verbatim transcription, split by '===== Screenshot N =====' markers. Call this FIRST.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "analyze",
     "description": "Delegate to the Analyst: classify the content and write the plain-English overview + top-5 tech-stack review. Returns JSON {is_code, language, extension, overview, tech_stack}.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "repair",
     "description": "Delegate to the Decoder: syntax/compile-check the code as-captured and apply minimal, error-only fixes. Returns the REAL errors found and whether they were resolved. Only call if the content is code.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "finalize",
     "description": "Assemble and save the final report. Provide the prose fields; the code is taken from the Extractor/Decoder result automatically. Call exactly once, last.",
     "input_schema": {"type": "object",
                      "properties": {
                          "language": {"type": "string"},
                          "extension": {"type": "string"},
                          "overview": {"type": "string", "description": "plain-English overview with inline (Screenshot N) citations"},
                          "errors": {"type": "string", "description": "the errors the Decoder reported, or 'None'"},
                          "tech_stack": {"type": "string", "description": "the Analyst's top-5 review (empty for non-code)"}},
                      "required": ["overview"]}},
]

_TC_DISPATCH = {
    "get_transcription": _tc_get_transcription,
    "analyze": _tc_analyze,
    "repair": _tc_repair,
    "finalize": _tc_finalize,
}

_TC_STAGE = {"get_transcription": "read", "analyze": "classify",
             "repair": "fix", "finalize": "save"}


COORDINATOR_SYSTEM = """You are the Coordinator of a team of specialist agents. You never read the screenshots yourself — you delegate to your team, then assemble their results into one report. Core rule: NEVER invent, complete, or guess content; report only what your specialists return.

Your team (each is a tool):
  get_transcription — the Extractor (faithful, verbatim). Call FIRST.
  analyze           — the Analyst. Returns JSON {is_code, language, extension, overview, tech_stack}.
  repair            — the Decoder. Checks the code as-captured and fixes ONLY real errors. Reports the actual errors found. Call only if is_code is true.
  finalize          — assemble + save the report.

Workflow: get_transcription -> analyze -> (if is_code) repair -> finalize.

When you call finalize:
  - overview: use the Analyst's plain-English overview, keeping the inline (Screenshot N) citations.
  - errors: the errors the Decoder reported (or 'None'). Never invent fixes beyond what the Decoder did.
  - tech_stack: the Analyst's top-5 review (empty for non-code).
Call finalize exactly once, then stop. Do not describe the content in your own words beyond passing the specialists' results through."""


def _publish(name):
    try:
        from core import status
        status.publish(name, kind="tool", stage=_TC_STAGE.get(name))
    except Exception:  # noqa: BLE001
        pass


def _blocks(resp):
    return getattr(resp, "content", []) or []


def run_team(client, ctx, goal=None, verbose=True, audit=None, max_iters=MAX_ITERS):
    """Coordinator loop. Delegates to the specialists and returns the assembled
    report markdown (the same format as the single-agent path)."""
    if audit is None:
        audit = []
    scratch = {}
    if goal is None:
        goal = (f"{len(ctx.images)} screenshot(s) are available. Produce the best verified "
                f"report by delegating to your team, then finalize.")
    try:
        from core import status
        status.publish("Coordinator started", kind="start", stage="start")
    except Exception:  # noqa: BLE001
        pass
    messages = [{"role": "user", "content": goal}]

    for _ in range(max_iters):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=COORDINATOR_SYSTEM, tools=COORDINATOR_TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": _blocks(resp)})

        if getattr(resp, "stop_reason", None) == "tool_use":
            results = []
            for b in _blocks(resp):
                if getattr(b, "type", None) == "tool_use":
                    audit.append(b.name)
                    _publish(b.name)
                    if verbose:
                        print(f"  → [coordinator] {b.name}")
                    fn = _TC_DISPATCH.get(b.name)
                    try:
                        out = fn(client, ctx, scratch, b.input or {}) if fn else f"Unknown tool {b.name}"
                    except Exception as exc:  # noqa: BLE001
                        out = f"Error in {b.name}: {type(exc).__name__}: {exc}"
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            messages.append({"role": "user", "content": results})
            continue
        break

    try:
        from core import status
        status.publish("Report ready", kind="done", stage="done")
    except Exception:  # noqa: BLE001
        pass
    if scratch.get("report_md"):
        return scratch["report_md"], messages
    final = "".join(getattr(b, "text", "") for b in _blocks(resp)
                    if getattr(b, "type", None) == "text").strip()
    return final or "(team finished without producing a report)", messages
