"""Agent tool registry (Milestone 8).

A thin adapter layer: each tool here is a JSON schema (what the model sees) plus
a small wrapper that unpacks the model's input, calls the real implementation in
core/, and returns a short string for the tool_result. Heavy logic stays in
core/ (analysis, validate, outputs) — this file only references it.

Public surface:
  TOOL_SCHEMAS    list of tool definitions sent to the Messages API
  run_tool(name, ctx, tool_input) -> str   dispatch + run one tool (never raises)
  ToolContext     per-run state (client, images, dirs) passed to every wrapper
"""

import json
import time
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core import analysis, validate, outputs


@dataclass
class ToolContext:
    client: object                       # anthropic client (None in mock tests)
    images: list = field(default_factory=list)   # list[Path] of captures
    cache_dir: Path = None               # per-run extraction cache
    out_dir: Path = Path("reports")      # where save_output writes
    out_name: str = "agent_output"       # base filename for saved artifacts
    session_dir: Path = None             # live session folder (enables capture/ask-more)
    interactive: bool = False            # True in the live hotkey session
    max_captures: int = 20               # safety cap on agent-driven captures
    region: dict = None                  # fixed capture rectangle (owned session)
    ready_event: object = None           # threading.Event set by the "next" hotkey
    confirm_saves: bool = True            # False in owned/auto mode -> save without asking


# ── wrappers (ctx, input dict) -> str ────────────────────────────────────────

def _t_list_captures(ctx, _inp):
    if not ctx.images:
        return "No captures available."
    lines = [f"{i}: {p.name}" for i, p in enumerate(ctx.images)]
    return f"{len(ctx.images)} screenshot(s) available (read with read_capture):\n" + "\n".join(lines)


def _t_read_capture(ctx, inp):
    i = int(inp["index"])
    if i < 0 or i >= len(ctx.images):
        return f"Error: index {i} out of range (0..{len(ctx.images) - 1})."
    path = ctx.images[i]
    if ctx.cache_dir is not None:
        analysis.extract_to_cache(ctx.client, path, ctx.cache_dir)
        text = analysis.cache_path_for(path, ctx.cache_dir).read_text()
    else:
        text = analysis.extract_one(ctx.client, path)
    return text or "(no text found in this screenshot)"


def _t_classify(ctx, inp):
    meta = analysis.synthesize_final(ctx.client, inp.get("text", ""))
    return json.dumps({k: meta[k] for k in ("is_code", "language", "extension", "overview")})


def _t_check_code(ctx, inp):
    ext = outputs.safe_ext(inp.get("extension", "txt"))
    tmp = Path(tempfile.mktemp(suffix=f".{ext}"))
    tmp.write_text(inp.get("content", ""))
    try:
        res = validate.check_source(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return json.dumps(res)


def _t_check_captured_code(ctx, inp):
    """Check the code EXACTLY as captured — reads the raw extraction from the cache
    (the model cannot re-type/clean it first), so real on-screen errors surface.
    Returns the raw code + the checker result."""
    ext = outputs.safe_ext(inp.get("extension", "txt"))
    from core.analysis import cache_path_for, stitch_parts
    parts = []
    for pth in sorted(ctx.images):
        if ctx.cache_dir is not None:
            cf = cache_path_for(pth, ctx.cache_dir)
            if cf.exists():
                parts.append(cf.read_text())
    code = stitch_parts(parts)
    if not code.strip():
        return json.dumps({"ok": None, "note": "No cached extraction yet — read the captures first."})
    tmp = Path(tempfile.mktemp(suffix=f".{ext}"))
    tmp.write_text(code)
    try:
        res = validate.check_source(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return json.dumps({"checked": res["checked"], "ok": res["ok"], "tool": res["tool"],
                       "errors": res["errors"], "code": code})


def _t_fix_code(ctx, inp):
    return analysis.fix_source(ctx.client, inp.get("content", ""),
                               inp.get("language", ""), inp.get("errors", ""))


def _t_save_output(ctx, inp):
    fmt = (inp.get("format") or "text").lower()
    content = inp.get("content", "")
    if getattr(ctx, "confirm_saves", True):
        try:
            ans = input(f"\nSave this output (as {fmt})? [Y/n]: ").strip().lower()
        except EOFError:
            ans = "y"
        if ans in ("n", "no"):
            return "User chose NOT to save. Nothing was written."
    if fmt == "source":
        out = outputs.save_source_file(content, ctx.out_dir, ctx.out_name, inp.get("extension", "txt"))
    elif fmt == "docx":
        out = outputs.save_docx({"extracted_text": content}, ctx.out_dir, ctx.out_name)
    else:
        out = outputs.save_text(content, ctx.out_dir, ctx.out_name)
    if not getattr(ctx, "confirm_saves", True):
        from core.notify import notify
        notify("Screen Capture", f"Saved {Path(out).name}")
    return f"Saved: {Path(out).resolve()}"


def _t_request_more_captures(ctx, inp):
    reason = inp.get("reason", "")
    if not ctx.interactive or ctx.session_dir is None:
        return ("No additional captures are available in this run. Proceed with what you have "
                f"or note that the input is incomplete. (reason: {reason})")
    print(f"\n[agent needs more captures] {reason}")
    print("  Capture more now (Cmd+Shift+2 full / Cmd+Shift+8 region), then press Enter.")
    try:
        input("  ...press Enter when done: ")
    except EOFError:
        pass
    current = set(ctx.images)
    new = [p for p in sorted(ctx.session_dir.glob("*.png")) if p not in current]
    ctx.images.extend(new)
    if not new:
        return "No new screenshots were added."
    start = len(ctx.images) - len(new)
    return f"{len(new)} new screenshot(s) added at indices {start}..{len(ctx.images) - 1}."


def _t_capture_screen(ctx, inp):
    if ctx.session_dir is None:
        return "Capture is not available in this run (offline mode)."
    if len(ctx.images) >= ctx.max_captures:
        return f"Capture limit ({ctx.max_captures}) reached — proceed with what you have."
    from core.capture import capture_full_png
    from core.capture import next_png_path
    out = next_png_path(ctx.session_dir)
    out.write_bytes(capture_full_png())
    ctx.images.append(out)
    return f"Captured the full screen as index {len(ctx.images) - 1}."


def _t_capture_region(ctx, inp):
    if ctx.session_dir is None:
        return "Capture is not available in this run (offline mode)."
    if len(ctx.images) >= ctx.max_captures:
        return f"Capture limit ({ctx.max_captures}) reached — proceed with what you have."
    from core.capture import capture_region_png
    data = capture_region_png()
    if data is None:
        return "Region capture was cancelled."
    from core.capture import next_png_path
    out = next_png_path(ctx.session_dir)
    out.write_bytes(data)
    ctx.images.append(out)
    return f"Captured a region as index {len(ctx.images) - 1}."


def _t_capture_next(ctx, inp):
    """Owned-session capture: tell the user to scroll, wait, then grab the screen."""
    if ctx.session_dir is None:
        return "Capture is not available in this run (offline mode)."
    if len(ctx.images) >= ctx.max_captures:
        return f"Capture limit ({ctx.max_captures}) reached — proceed with what you have."
    hint = inp.get("hint", "Scroll so the next section is visible.")
    print(f"\n[agent] {hint}")
    try:
        input("  Scroll, then press Enter (or just Enter if nothing more to show): ")
    except EOFError:
        pass
    from core.capture import capture_full_png, next_png_path
    out = next_png_path(ctx.session_dir)
    out.write_bytes(capture_full_png())
    ctx.images.append(out)
    return f"Captured the screen as index {len(ctx.images) - 1}. Read it to see the new content."


def _t_capturing_done(ctx, inp):
    """Signal that all needed captures are taken — notify the user to return to the terminal."""
    from core.notify import notify
    notify("Screen Capture", "All images captured — return to the terminal for the result.")
    print("\n[agent] All images captured — the result is below.")
    return "Notified the user that capturing is complete."


def _t_await_capture(ctx, inp):
    """Owned session: ask the user to capture (Cmd+Shift+8 region / Cmd+Shift+2 full),
    then WAIT for the screenshot to appear and return it. The user drives the capture."""
    if ctx.session_dir is None:
        return "Capture is not available in this run (offline mode)."
    if len(ctx.images) >= ctx.max_captures:
        return f"Capture limit ({ctx.max_captures}) reached — proceed with what you have."
    hint = inp.get("hint", "Capture the part you want.")
    print(f"\n[agent] {hint}")
    print("  Select a REGION with Cmd+Shift+8 (or full screen with Cmd+Shift+2). Waiting...")
    seen = set(ctx.images)
    deadline = time.monotonic() + 180
    new = []
    while time.monotonic() < deadline:
        new = [p for p in sorted(ctx.session_dir.glob("*.png")) if p not in seen]
        if new:
            break
        time.sleep(0.5)
    if not new:
        return "No new capture detected (timed out). Ask again, or finish with what you already have."
    ctx.images.extend(new)
    start = len(ctx.images) - len(new)
    return f"Captured {len(new)} screenshot(s) at indices {start}..{len(ctx.images) - 1}. Read them."


def _t_next_capture(ctx, inp):
    """Owned session: notify the user to scroll, wait for the next-capture signal
    (Cmd+Shift+7), then re-capture the full screen."""
    if ctx.session_dir is None:
        return "Owned-session capture is not set up."
    if len(ctx.images) >= ctx.max_captures:
        return f"Capture limit ({ctx.max_captures}) reached — proceed with what you have."
    hint = inp.get("hint", "Scroll to the next part.")
    from core.notify import notify
    notify("Screen Capture", f"{hint} Then press Cmd+Shift+7.")
    print(f"\n[agent] {hint}  (scroll, then press Cmd+Shift+7)")
    if ctx.ready_event is not None:
        ctx.ready_event.clear()
        if not ctx.ready_event.wait(timeout=300):
            return "Timed out waiting for Cmd+Shift+7. Ask again, or finish with what you have."
    from core.capture import capture_full_png, next_png_path
    out = next_png_path(ctx.session_dir)
    out.write_bytes(capture_full_png())
    ctx.images.append(out)
    notify("Screen Capture", "Captured — analysing...")
    print("  captured — analysing...")
    return f"Captured the screen as index {len(ctx.images) - 1}. Read it."


# ── schemas (what the model sees) ────────────────────────────────────────────

TOOL_SCHEMAS = [
    {"name": "list_captures",
     "description": "List how many screenshots are available and their indices. Call this first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_capture",
     "description": "Extract and return the text/code visible in one screenshot, by index.",
     "input_schema": {"type": "object",
                      "properties": {"index": {"type": "integer", "description": "0-based screenshot index"}},
                      "required": ["index"]}},
    {"name": "classify",
     "description": "Classify the given text: is it code, what language, what file extension, plus a short overview.",
     "input_schema": {"type": "object",
                      "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "check_code",
     "description": "Syntax/compile-check source code with the local toolchain (never runs it). Returns ok + errors.",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string"},
                                     "extension": {"type": "string", "description": "e.g. py, js, c, cpp, cs"}},
                      "required": ["content", "extension"]}},
    {"name": "check_captured_code",
     "description": "Check the code EXACTLY as captured from the screen (reads the raw extraction; you cannot clean it up first). Returns the raw code and any real errors (e.g. a genuine IndentationError). Use THIS to find errors, not check_code.",
     "input_schema": {"type": "object",
                      "properties": {"extension": {"type": "string", "description": "e.g. py, js, c, cpp, cs"}},
                      "required": ["extension"]}},
    {"name": "fix_code",
     "description": "Given code, its language, and compiler errors, return a minimally corrected version (transcription fixes only).",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string"}, "language": {"type": "string"},
                                     "errors": {"type": "string"}},
                      "required": ["content", "errors"]}},
    {"name": "save_output",
     "description": "Save the final result. format: 'source' (a code file, needs extension), 'docx' (a Word doc), or 'text'.",
     "input_schema": {"type": "object",
                      "properties": {"content": {"type": "string"},
                                     "format": {"type": "string", "enum": ["source", "docx", "text"]},
                                     "extension": {"type": "string"}},
                      "required": ["content", "format"]}},
    {"name": "request_more_captures",
     "description": "Ask the user to capture more screenshots when the current ones look incomplete or cut off.",
     "input_schema": {"type": "object",
                      "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "capture_screen",
     "description": "Capture the full screen right now (live session only). Adds a new screenshot.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "capture_region",
     "description": "Capture a user-selected screen region right now (live session only). Adds a new screenshot.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "capture_next",
     "description": "Ask the user to scroll to the next part, then capture the screen. Use to page through content longer than one screen.",
     "input_schema": {"type": "object",
                      "properties": {"hint": {"type": "string", "description": "What to scroll to, e.g. 'scroll down past line 40'"}}}},
    {"name": "await_capture",
     "description": "Ask the user to capture the region/screen they want (they press Cmd+Shift+8 or 2), then wait for and return that screenshot. Use this in an owned session to get each capture from the user.",
     "input_schema": {"type": "object",
                      "properties": {"hint": {"type": "string", "description": "What to capture next"}}}},
    {"name": "next_capture",
     "description": "Owned session only: notify the user to scroll, wait for their Cmd+Shift+7 signal, then re-capture the full screen. Use this to page through long content.",
     "input_schema": {"type": "object",
                      "properties": {"hint": {"type": "string", "description": "Scroll instruction shown to the user, e.g. 'scroll down past line 40'"}}}},
    {"name": "capturing_done",
     "description": "Owned session only: call this once you have captured everything you need, BEFORE presenting your final answer. Notifies the user that capturing is complete and to return to the terminal.",
     "input_schema": {"type": "object", "properties": {}}},
]

DISPATCH = {
    "list_captures": _t_list_captures,
    "read_capture": _t_read_capture,
    "classify": _t_classify,
    "check_code": _t_check_code,
    "check_captured_code": _t_check_captured_code,
    "fix_code": _t_fix_code,
    "save_output": _t_save_output,
    "request_more_captures": _t_request_more_captures,
    "capture_screen": _t_capture_screen,
    "capture_region": _t_capture_region,
    "capture_next": _t_capture_next,
    "await_capture": _t_await_capture,
    "next_capture": _t_next_capture,
    "capturing_done": _t_capturing_done,
}


def run_tool(name: str, ctx: ToolContext, tool_input: dict) -> str:
    """Dispatch and run one tool. Never raises — errors come back as text so the
    agent can see and react to them."""
    fn = DISPATCH.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'."
    try:
        return fn(ctx, tool_input or {})
    except Exception as exc:  # noqa: BLE001
        return f"Error running {name}: {type(exc).__name__}: {exc}"
