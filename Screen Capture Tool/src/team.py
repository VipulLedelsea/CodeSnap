"""In-process multi-agent team (A2A) — Milestone 11.

A Coordinator delegates to three specialists, each with its OWN model, prompt,
and strictly limited capability. The agents "talk" by passing task inputs and
returning results — the same message shape the single-agent loop already uses,
just split by role.

  Coordinator  (Sonnet) — owns the goal, decides what to run, assembles + saves
                          the final report. Reads no screenshots itself.
  Extractor    (EXTRACT_MODEL, the main vision model) — reads the captures and returns a faithful, verbatim
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
import re
import sys
from pathlib import Path

import tools
from core import analysis, validate, outputs
from core.analysis import MODEL, TEXT_MODEL

MAX_ITERS = 10
MAX_TOKENS = 4096


# ── specialist agents ────────────────────────────────────────────────────────

def agent_extract(ctx) -> dict:
    """Extractor (analysis.EXTRACT_MODEL — currently the main vision model, not a cheaper one). Reads every capture faithfully and returns:
      code   — the clean stitched transcription (overlaps de-duplicated)
      marked — the same content split by '===== Screenshot N =====' markers
               (lets the Analyst cite which screenshot each part came from)
    Faithfulness is structural: extraction goes through the verbatim OCR path and
    the returned code is the stitched cache, never a paraphrase."""
    raws = []
    metas = []
    corrections = []
    for p in sorted(ctx.images):
        if ctx.cache_dir is not None:
            analysis.extract_to_cache(ctx.client, p, ctx.cache_dir)
            raws.append(analysis.cache_path_for(p, ctx.cache_dir).read_text())
            corrections.extend(analysis.corrections_for(p, ctx.cache_dir))
            metas.append(analysis.verify_for(p, ctx.cache_dir))
        else:
            r = analysis.extract_structured(ctx.client, p)
            raws.append(r["raw"])
            corrections.extend(r["corrections"])
            metas.append(r.get("verify") or {})
    # clean + collapse dups + stitch (by editor line number when every screenshot shows them), with the line check
    code, parts, notes, statuses = analysis.merge_verified(raws, metas)
    try:
        ctx.verify_info = (statuses, notes, code)
    except Exception:  # noqa: BLE001 - a context without the field (older callers)
        pass
    marked = "\n\n".join(f"===== Screenshot {i + 1} =====\n{t}" for i, t in enumerate(parts))
    numbered = "\n".join(f"{i + 1:>4}  {line}" for i, line in enumerate(code.splitlines()))
    return {"code": code, "marked": marked, "numbered": numbered, "parts": parts,
            "corrections": corrections}


ANALYST_SYSTEM = """You are the Analyst on a team. You receive the source code with a line number prefixed to every line. You do NOT edit the content — you describe it.

Return ONLY a JSON object (no prose, no code fences) with these keys:
  is_code    (boolean) — is the primary content source code?
  language   (string)  — e.g. "Python", "JavaScript", "C++" (empty if not code)
  extension  (string)  — file extension without a dot, e.g. "py", "js", "cpp" (empty if not code)
  name       (string)  — a short filename-safe base name (letters/digits/underscore only, NO extension, NO spaces) describing the file's main content, e.g. "Calculator", "quicksort", "UserModel". Empty if not code.
  overview   (string)  — a clear, plain-English summary a non-expert can follow. One sentence on what it does overall, then one short paragraph per main part in everyday language (briefly explain any technical term). Logical order, short sentences. Weave INLINE LINE-NUMBER citations into the sentences, e.g. "(lines 5-11)" or "(line 27)", using the numbers shown. Do NOT mention screenshots.
  tech_stack (string)  — an honest, brief review. If the code is current and well written, SAY SO in one line and stop — do NOT invent nitpicks or filler to make a list. Only when there are genuine, worthwhile improvements, list them (at most 5, most important first). Put EACH point on its OWN line, numbered "1. ", "2. ", ... with a real newline (\n) between items. Empty string if not code.

Accuracy rules: describe ONLY what the code shows. Never invent names, values, systems, behaviour or intent. If a part is
unclear or looks mis-read, say so plainly instead of guessing. Every line reference must point at the lines that show it.

EXAMPLE — format only. Do NOT reuse this wording; describe the ACTUAL content you receive:
{"is_code": true, "language": "Python", "extension": "py", "name": "even_odd", "overview": "This script reads a whole number and prints whether it is even or odd (lines 1-4).", "tech_stack": "Up to date and idiomatic for its size; no significant changes needed."}

Return JSON only."""


def _analyst_enrich(client, text: str, base: dict) -> dict:
    """Analyst enrichment given a precomputed classify `base` — adds the rich
    overview + tech-stack review WITHOUT a second classify call (used by the
    parallel pipeline so the classify runs once, up front)."""
    out = {
        "is_code": base.get("is_code", False),
        "language": base.get("language", ""),
        "extension": base.get("extension", ""),
        "overview": base.get("overview", ""),
        "tech_stack": "",
        "name": "",
    }
    if not (text or "").strip():
        return out
    try:
        msg = client.messages.create(
            model=TEXT_MODEL, max_tokens=2048, system=ANALYST_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        data = analysis._parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        if analysis.is_fatal_api_error(exc):
            print(f"(analyst call failed, report continues without the enrichment: {type(exc).__name__}: {exc})", file=sys.stderr)
        data = None
    if isinstance(data, dict) and data:
        out["is_code"] = bool(data.get("is_code", out["is_code"]))
        out["language"] = str(data.get("language") or out["language"]).strip()
        out["extension"] = str(data.get("extension") or out["extension"]).strip().lstrip(".").lower()
        out["overview"] = str(data.get("overview") or out["overview"]).strip()
        out["tech_stack"] = str(data.get("tech_stack") or "").strip()
        out["name"] = str(data.get("name") or "").strip()
    return out


def _apply_legacy_kind(base: dict, code: str) -> dict:
    from core.cobol import KINDS, detect_kind
    kind = detect_kind(code, base.get("language", ""), base.get("extension", ""))
    if kind:
        language, extension = KINDS[kind]
        base = {**base, "is_code": True, "language": language, "extension": extension}
    return base


def agent_analyze(client, marked_text: str) -> dict:
    """Analyst (Sonnet). Classifies and writes the overview + tech-stack review."""
    base = _apply_legacy_kind(analysis.synthesize_final(client, marked_text), marked_text)
    return _analyst_enrich(client, marked_text, base)


def _check(code: str, extension: str) -> dict:
    # private temp dir, private cwd, include-path guard and key redaction all live in validate.check_code_text
    return validate.check_code_text(code, extension)


_INDENT_ERR = re.compile(
    r"IndentationError|TabError|unexpected indent|unindent does not match|expected an indented block",
    re.I)


_INDENT_SENSITIVE_LANGS = {"python", "py", "yaml", "yml", "coffeescript", "coffee",
                           "haskell", "hs", "fsharp", "f#", "nim", "cython", "pyx"}


def _indent_sensitive(language, extension=None):
    """True only for languages where indentation is load-bearing (can be a real error)."""
    l = (language or "").strip().lower()
    e = (extension or "").strip().lower().lstrip(".")
    return l in _INDENT_SENSITIVE_LANGS or e in {"py", "pyx", "yaml", "yml", "coffee", "hs", "nim", "fs"}


def _indent_caveat(errors: str) -> str:
    """If the compiler error is about indentation, flag it as lower-confidence \u2014
    indentation is read approximately from a screenshot and can drift a space,
    so an indentation error may be a transcription artifact, not a real bug."""
    if errors and _INDENT_ERR.search(errors):
        return (errors + "\n(Lower confidence: indentation is transcribed approximately from the "
                "screenshot and can drift by a space \u2014 verify against the original before treating "
                "this as a real indentation error.)")
    return errors



def agent_decoder(client, code: str, extension: str, language: str) -> dict:
    """Decoder (Sonnet). Checks the code AS CAPTURED, then applies a minimal,
    error-only fix if needed. Reports the REAL errors found (never invents), and
    whether the fix resolved them."""
    res = _check(code, extension)
    if not res.get("checked"):
        return {"errors": "Not verified: " + (res.get("note") or "no checker for this language."),
                "code": code, "checked": False, "tool": res.get("tool", ""), "resolved": None}
    if res.get("ok"):
        return {"errors": "None", "code": code, "checked": True,
                "tool": res.get("tool", ""), "resolved": True}
    raw_errors = res.get("errors", "")

    # A [CUT OFF] marker in the code means the screenshot was truncated at the edge —
    # that is an incomplete capture, not a real code error.
    if "[CUT OFF]" in code:
        return {"errors": ("Possible incomplete capture \u2014 a line was cut off at the screen edge "
                           "([CUT OFF]). Re-capture with the full width/height visible.\n(checker output: "
                           + raw_errors + ")"),
                "code": code, "checked": True, "tool": res.get("tool", ""),
                "resolved": None, "truncated": True}

    # Single faithful scan: report the indentation error the checker found as-is
    # (indentation is read approximately from a screenshot, so it is noted as lower-confidence).
    errors = _indent_caveat(raw_errors)
    if validate.looks_truncated(errors):
        # The capture was likely cut off (an open quote/brace/statement never closed),
        # so this is probably NOT a real code bug. Do NOT "fix" it by inventing the
        # missing part — flag it as an incomplete capture instead.
        note = ("Possible incomplete capture — the code may have been cut off before its end "
                "(e.g. a closing quote or brace was not captured), so this may not be a real "
                "error. If the code is complete on screen, re-capture and scroll to the end.")
        return {"errors": f"{note}\n(checker output: {errors})", "code": code, "checked": True,
                "tool": res.get("tool", ""), "resolved": None, "truncated": True}
    try:
        fixed = outputs.strip_code_fences(analysis.fix_source(client, code, language, errors))
        problem = analysis.fix_looks_complete(code, fixed)
    except analysis.FixRejected as exc:
        fixed, problem = "", str(exc)
    if problem:
        # never replace the captured code with a truncated or drastically shorter "fix"
        return {"errors": errors, "code": code, "checked": True, "tool": res.get("tool", ""),
                "resolved": False, "remaining": f"Automatic fix discarded: {problem}."}
    res2 = _check(fixed, extension)
    if res2.get("ok"):
        # fix compiles: ship the corrected code (errors describe what was wrong, now resolved)
        return {"errors": errors, "code": fixed, "checked": True,
                "tool": res.get("tool", ""), "resolved": True}
    # fix didn't resolve: ship the code AS CAPTURED so the error's line numbers
    # point at the code the report actually shows (no display/line-number drift).
    return {"errors": errors, "code": code, "checked": True, "tool": res.get("tool", ""),
            "resolved": False, "remaining": res2.get("errors", "")}


DIAGRAMMER_SYSTEM = """You are the Diagrammer. You receive source code that was transcribed from a screen. Produce diagrams in Mermaid syntax based ONLY on what is actually present in the code. Never invent classes, methods, calls, or relationships that are not in the code. If the code is partial or cut off, diagram only what is visible and add a short Mermaid %% comment noting it is incomplete.

Return EXACTLY these three sections, in order, each a bold label on its own line followed by one fenced ```mermaid block:

**Class diagram**
A Mermaid `classDiagram` of the classes actually defined (their attributes, methods, and relationships). If the code defines NO classes, output this single line instead of a code block: _No classes defined in the captured code._

**Interaction diagram**
A Mermaid `sequenceDiagram` of the main runtime flow visible in the code (which function or object calls which, in order). Keep it to the primary path.

**Component / module diagram**
A Mermaid `flowchart TD` of the modules / files / functions and their imports or calls as visible in the code.

Keep each diagram small and readable. Emit VALID Mermaid only. Output nothing except the three labeled sections.

EXAMPLE — this shows ONLY the required format and valid Mermaid syntax. Do NOT copy these names or structure; produce diagrams for the ACTUAL code you receive.

**Class diagram**
```mermaid
classDiagram
  class Timer {
    +start()
    +stop()
  }
```

**Interaction diagram**
```mermaid
sequenceDiagram
  Caller->>Timer: start()
  Caller->>Timer: stop()
```

**Component / module diagram**
```mermaid
flowchart TD
  main --> Timer
```
"""


def agent_diagrammer(client, code: str, language: str) -> str:
    """Diagrammer (Sonnet). Returns markdown with three fenced Mermaid diagrams
    (class, interaction, component) derived ONLY from the captured code. Empty
    string if there is no code."""
    if not code.strip():
        return ""
    try:
        msg = client.messages.create(
            model=TEXT_MODEL, max_tokens=2000, system=DIAGRAMMER_SYSTEM,
            messages=[{"role": "user", "content": f"Language: {language or 'unknown'}\n\n{code}"}],
        )
        return "".join(getattr(b, "text", "") for b in msg.content).strip()
    except Exception:  # noqa: BLE001
        return ""


# ── report assembly ──────────────────────────────────────────────────────────

def _fmt_corrections(corrections) -> str:
    """Render the Extractor's corrections_applied[] as an advisory note (or "").

    These are things that looked wrong on screen but were kept VERBATIM in the code
    above \u2014 an outlet that keeps raw transcription faithful. Purely informational.
    """
    if not corrections:
        return ""
    lines = []
    for c in corrections[:12]:
        saw = str(c.get("saw", "")).strip()
        sug = str(c.get("suggested", c.get("changed_to", ""))).strip()
        if not saw:
            continue
        lines.append(f'- "{saw}" \u2014 looks like: "{sug}"' if sug else f'- "{saw}" looked off')
    if not lines:
        return ""
    return ("text the transcriber flagged as suspicious but kept exactly as shown "
            "(the code above is unmodified):\n" + "\n".join(lines))


def _assemble(language, overview, errors, code, tech_stack, extension, is_code, diagrams="", corrections=None) -> str:
    if is_code:
        out = (f"**Language:** {language}\n"
               f"**Overview:** {overview}\n"
               f"**Errors found:** {errors or 'None'}\n"
               f"**Code:**\n```{extension or 'txt'}\n{code}\n```\n"
               f"**Tech-stack review:** {tech_stack or 'n/a'}")
        note = _fmt_corrections(corrections)
        if note:
            out += f"\n**Transcription notes:** {note}"
        if diagrams:
            out += f"\n**Diagrams:**\n{diagrams}"
        return out
    return (f"**Type:** {language or 'Document'}\n"
            f"**Overview:** {overview}\n\n{code}")


# ── coordinator tools (delegate to the specialists) ──────────────────────────

def _tc_get_transcription(client, ctx, scratch, _inp):
    ex = agent_extract(ctx)
    scratch["code"] = ex["code"]
    scratch["marked"] = ex["marked"]
    scratch["numbered"] = ex.get("numbered", "")
    scratch["corrections"] = ex.get("corrections", [])
    return ex["marked"] or "(no text found in the captures)"


def _tc_analyze(client, ctx, scratch, _inp):
    a = agent_analyze(client, scratch.get("numbered") or scratch.get("code", ""))
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


def _tc_diagram(client, ctx, scratch, _inp):
    if not scratch.get("is_code"):
        return "Content is not code — no diagrams needed."
    code = scratch.get("code", "")
    if not code.strip():
        return "No code available to diagram."
    d = agent_diagrammer(client, code, scratch.get("language", ""))
    scratch["diagrams"] = d
    n = d.count("```mermaid")
    return f"Diagrammer produced {n} diagram(s): class, interaction, component/module."


def _tc_finalize(client, ctx, scratch, inp):
    a = scratch.get("analysis", {}) or {}
    language = a.get("language") or inp.get("language") or scratch.get("language", "")
    extension = a.get("extension") or inp.get("extension") or scratch.get("extension", "txt")
    # Overview + tech-stack come straight from the Analyst so its line-number
    # citations and per-line formatting are preserved (the Coordinator can't reword them).
    overview = a.get("overview") or inp.get("overview", "")
    tech = a.get("tech_stack", inp.get("tech_stack", "")) if a else inp.get("tech_stack", "")
    # Errors reflect ONLY the Decoder's real compiler check — never model-typed.
    errors = scratch.get("errors") or "None"
    if errors != "None":
        _expl = analysis.explain_error(client, language, errors, scratch.get("code", ""))
        if _expl:
            errors = _expl + "\n\nCompiler details:\n" + errors
    is_code = bool(scratch.get("is_code", True))
    code = scratch.get("code", "")
    diagrams = scratch.get("diagrams", "")
    scratch["report_md"] = _assemble(language, overview, errors, code, tech, extension, is_code,
                                     diagrams, scratch.get("corrections"))
    _apply_content_name(ctx, (a or {}).get("name"))
    if is_code:
        saved = tools._t_save_output(ctx, {
            "format": "source", "content": code, "extension": extension,
            "language": language, "overview": overview, "errors": errors, "tech_stack": tech,
            "diagrams": diagrams})
    else:
        fmt = "docx" if extension in ("docx", "doc") else "text"
        saved = tools._t_save_output(ctx, {"format": fmt, "content": code or overview})
    return f"Report assembled and saved. {saved}"


COORDINATOR_TOOLS = [
    {"name": "get_transcription",
     "description": "Delegate to the Extractor: read every capture faithfully and return the verbatim transcription, split by '===== Screenshot N =====' markers. Call this FIRST.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "analyze",
     "description": "Delegate to the Analyst: classify the content and write the plain-English overview + top-5 tech-stack review. Returns JSON {is_code, language, extension, overview, tech_stack}.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "repair",
     "description": "Delegate to the Decoder: syntax/compile-check the code as-captured and apply minimal, error-only fixes. Returns the REAL errors found and whether they were resolved. Only call if the content is code.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "diagram",
     "description": "Delegate to the Diagrammer: from the captured code, produce a Class diagram, an Interaction (sequence) diagram, and a Component/module diagram as Mermaid — using ONLY what is actually in the code. Call after repair, and only if the content is code.",
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
    "diagram": _tc_diagram,
    "finalize": _tc_finalize,
}

_TC_STAGE = {"get_transcription": "read", "analyze": "classify",
             "repair": "fix", "diagram": "save", "finalize": "save"}


COORDINATOR_SYSTEM = """You are the Coordinator of a team of specialist agents. You never read the screenshots yourself — you delegate to your team, then assemble their results into one report. Core rule: NEVER invent, complete, or guess content; report only what your specialists return.

Your team (each is a tool):
  get_transcription — the Extractor (faithful, verbatim). Call FIRST.
  analyze           — the Analyst. Returns JSON {is_code, language, extension, overview, tech_stack}.
  repair            — the Decoder. Checks the code as-captured and fixes ONLY real errors. Reports the actual errors found. Call only if is_code is true.
  diagram           — the Diagrammer. Produces Mermaid class, interaction, and component/module diagrams from the code. Call after repair, only if is_code is true.
  finalize          — assemble + save the report.

Workflow: get_transcription -> analyze -> (if is_code) repair -> (if is_code) diagram -> finalize.

When you call finalize:
  - overview: use the Analyst's plain-English overview, keeping its inline line-number citations.
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
    reason = getattr(resp, "stop_reason", None)
    if reason in ("max_tokens", "refusal"):
        why = "ran out of output tokens" if reason == "max_tokens" else "declined to continue"
        return f"(team stopped without a report: the coordinator {why})", messages
    final = "".join(getattr(b, "text", "") for b in _blocks(resp)
                    if getattr(b, "type", None) == "text").strip()
    return final or "(team finished without producing a report)", messages


def _apply_content_name(ctx, name):
    """Rename the output to a content-derived filename (e.g. Calculator) instead of
    report_<timestamp>, kept unique across reports/ and reports/pending/."""
    import re
    from pathlib import Path
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip()).strip("_")
    if not slug:
        return
    root = Path(ctx.out_dir)
    dirs = [root, root / "pending"]
    cand, i = slug, 2
    while any((d / f"Report_{cand}.json").exists() for d in dirs):
        cand = f"{slug}_{i}"; i += 1
    ctx.out_name = "Report_" + cand      # bundle -> Report_Calculator.json
    ctx.code_name = "Code_" + cand       # code file -> Code_Calculator.py




def _merge_indent_review(compile_errors: str, indent_issues: list, code: str) -> str:
    """Fold the image-level indentation review into the errors field. Only surface an
    issue whose line actually appears in the transcription (guards against invented lines)."""
    grounded = []
    for it in (indent_issues or []):
        lt = str(it.get("line_text", "")).strip()
        if lt and lt in code:
            grounded.append(it)
    if not grounded:
        return compile_errors
    note = "Indentation issues seen in the screenshot:\n" + "\n".join(
        f"- {it.get('problem', 'indentation')}: {it.get('line_text', '').strip()}"
        + (f" ({it.get('note', '').strip()})" if it.get("note") else "")
        for it in grounded)
    if compile_errors == "None":
        return (note + "\n(The transcribed code compiled, but the screenshot shows the above \u2014 "
                "the transcription may have auto-corrected the indentation; verify against the original.)")
    return compile_errors + "\n\n" + note


def run_team_fast(client, ctx, goal=None, verbose=True, audit=None, max_iters=None):
    """Parallel team pipeline — same report as run_team(), lower wall-clock time.

    extract -> quick classify -> (Analyst || Decoder || Diagrammer) -> assemble + save.
    The three post-extraction specialists don't depend on each other (only on the
    transcription + a language/extension classify), so they run concurrently. Total
    The Analyst and Decoder are independent and run together; the Diagrammer then
    runs on the Decoder's REPAIRED code (the report's goal is verified code), so its
    diagrams reflect the corrected program. Total time drops from the SUM of the
    three calls to roughly max(Analyst, Decoder) + Diagrammer.
    """
    from concurrent.futures import ThreadPoolExecutor
    if audit is None:
        audit = []

    def _pub(msg, kind="tool", stage=None):
        try:
            from core import status
            status.publish(msg, kind=kind, stage=stage)
        except Exception:  # noqa: BLE001
            pass

    _pub("Coordinator started", kind="start", stage="start")

    # Stage 1 — faithful transcription (must run first) + one quick classify
    audit.append("get_transcription"); _pub("get_transcription", stage="read")
    ex = agent_extract(ctx)
    code0 = ex["code"]
    numbered = ex.get("numbered", "") or code0
    corrections = ex.get("corrections", [])
    base = _apply_legacy_kind(analysis.synthesize_final(client, numbered), code0)
    is_code = bool(base.get("is_code", False))
    language = base.get("language", "") or ""
    extension = base.get("extension", "") or "txt"

    # Non-code -> overview only (document/text path)
    if not (is_code and code0.strip()):
        audit.append("analyze"); _pub("analyze", stage="classify")
        an = _analyst_enrich(client, numbered, base)
        overview = an.get("overview") or base.get("overview", "")
        report_md = _assemble(language or "Document", overview, "None", code0,
                              an.get("tech_stack", ""), extension, False, "", corrections)
        fmt = "docx" if extension in ("docx", "doc") else "text"
        _apply_content_name(ctx, an.get("name"))
        audit.append("finalize"); _pub("finalize", stage="save")
        saved = tools._t_save_output(ctx, {"format": fmt, "content": code0 or overview})
        _pub("Report ready", kind="done", stage="done")
        if verbose:
            print(f"[team-fast] {saved}")
        return report_md, []

    # Stage 2 — Analyst || Decoder (|| indentation reviewer for indent-sensitive langs)
    audit.append("analyze"); _pub("analyze", stage="classify")
    audit.append("repair"); _pub("repair", stage="fix")
    indent_lang = _indent_sensitive(language, extension)
    from core.cobol import detect_kind, lint_columns, merge_column_review, review_columns
    column_lang = detect_kind(code0, language, extension) in ("cobol", "copybook")
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_an = pool.submit(_analyst_enrich, client, numbered, base)
        f_de = pool.submit(agent_decoder, client, code0, extension, language)
        f_rv = pool.submit(analysis.review_indentation, client, getattr(ctx, "images", []), language) if indent_lang else None
        f_col = pool.submit(review_columns, client, getattr(ctx, "images", []), code0) if column_lang else None
        an = f_an.result(); de = f_de.result()
        indent_issues = f_rv.result() if f_rv is not None else []
        column_seen = f_col.result() if f_col is not None else []

    code = de.get("code", code0)          # Decoder ships the fixed code if the error-only fix compiled
    # Stage 3 — Diagrammer draws the REPAIRED code (waits for the Decoder on purpose)
    audit.append("diagram"); _pub("diagram", stage="save")
    di = "" if getattr(ctx, "program_mode", False) else agent_diagrammer(client, code, language)

    overview = an.get("overview") or base.get("overview", "")
    tech = an.get("tech_stack", "")
    language = language or an.get("language", "")
    extension = extension or an.get("extension", "") or "txt"

    # Compiler errors first (with a plain-English explanation), then the image-level
    # indentation review, which catches misalignments the transcription may have
    # silently auto-corrected (so the compiled text looked clean).
    compile_errors = de.get("errors") or "None"
    if compile_errors != "None" and not de.get("truncated") and de.get("checked") is not False:
        _expl = analysis.explain_error(client, language, compile_errors, code)
        if _expl:
            compile_errors = _expl + "\n\nCompiler details:\n" + compile_errors
    errors = _merge_indent_review(compile_errors, indent_issues, code)
    if column_lang:
        errors = merge_column_review(errors, lint_columns(code0), column_seen, code0)
    diagrams = di or ""

    report_md = _assemble(language, overview, errors, code, tech, extension, True,
                          diagrams, corrections)
    _apply_content_name(ctx, an.get("name"))
    audit.append("finalize"); _pub("finalize", stage="save")
    saved = tools._t_save_output(ctx, {
        "format": "source", "content": code, "extension": extension,
        "language": language, "overview": overview, "errors": errors,
        "tech_stack": tech, "diagrams": diagrams})
    _pub("Report ready", kind="done", stage="done")
    if verbose:
        print(f"[team-fast] {saved}")
    return report_md, []
