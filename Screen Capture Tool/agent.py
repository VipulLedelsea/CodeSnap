"""Agentic mode (Milestone 8) — self-contained tool-use loop.

Hands a goal + an inventory of captured screenshots to Claude and lets it drive
the tools in tools.py (read, classify, check, fix, save, capture, ask-for-more)
until it produces a verified output. The deterministic hotkey pipeline is
untouched; this is a separate entry point.

  python agent.py                 # one run over tests/inbox/
  python agent.py --chat          # keep talking: follow-ups after the result
  python agent.py --dir path --out reports
"""

import argparse
import os
import sys
import time
from pathlib import Path

from core.analysis import MODEL, load_env
from tools import TOOL_SCHEMAS, ToolContext, run_tool

MAX_ITERS = 14          # hard cap on think/act cycles (runaway guard)
MAX_TOKENS = 4096

SYSTEM_PROMPT = """
You turn captured screenshots into the best, verified output. You work by calling tools — you cannot see the screenshots until you read them.

Core rule: NEVER invent, complete, or guess content. Transcribe and report only what is actually captured. It is better to flag a gap than to fabricate.

Workflow:
  1. list_captures, then read_capture each one in order. Keep the code EXACTLY as returned — do not silently fix indentation, typos, or cut-off lines.
  2. If a capture is blank, or a line is marked [CUT OFF] or clearly incomplete, do NOT fill it in. Note it, and call request_more_captures to ask for a clean shot. Never reconstruct missing code.
  3. If it is CODE: call check_code on the code EXACTLY as captured (do not pre-fix it). The errors it returns are the REAL errors in the captured code — these are what you report.
  4. Present your final answer in EXACTLY this format (Markdown):
        **Language:** <language>
        **Overview:** <plain-English summary of what the code does>
        **Errors found:** <the actual errors check_code reported on the as-captured code, e.g. an IndentationError with its line; or 'None' only if it genuinely passed. List blank/cut-off captures here too.>
        **Code:**
        ```<ext>
        <the code — corrected ONLY for the specific errors you reported (e.g. fix the bad indent). Do NOT change anything else, and do NOT invent content for missing/cut-off parts; leave a clear  # [missing — recapture]  marker instead.>
        ```
  5. In that SAME turn, also call save_output (format 'source', with the extension and the code you displayed) to offer saving — the user will be asked to confirm. Never save before presenting.

For non-code content: give **Language/Type** and **Overview**, show the text, then call save_output ('docx' for documents, else 'text').
Never execute the captured code (check_code only compiles/parses). Do not re-read a screenshot you already read.
"""


def _blocks(resp):
    return getattr(resp, "content", []) or []


def _short(d):
    s = str(d)
    return s if len(s) <= 60 else s[:57] + "..."


def run_agent(client, ctx, goal=None, messages=None, max_iters=MAX_ITERS, verbose=True, audit=None):
    """Drive the tool-use loop. Continues `messages` if given (so a conversation
    can span turns). Returns (final_text, messages)."""
    if messages is None:
        messages = []
    if goal is not None:
        messages.append({"role": "user", "content": goal})
    if audit is None:
        audit = []

    for _ in range(max_iters):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT, tools=TOOL_SCHEMAS, messages=messages,
        )
        messages.append({"role": "assistant", "content": _blocks(resp)})

        if getattr(resp, "stop_reason", None) == "tool_use":
            for b in _blocks(resp):
                if getattr(b, "type", None) == "text" and (b.text or "").strip():
                    print("\n" + b.text.strip())
            results = []
            for b in _blocks(resp):
                if getattr(b, "type", None) == "tool_use":
                    audit.append(b.name)
                    if verbose:
                        print(f"  → {b.name}({_short(b.input)})")
                    out = run_tool(b.name, ctx, b.input)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            messages.append({"role": "user", "content": results})
            continue

        final = "".join(getattr(b, "text", "") for b in _blocks(resp)
                         if getattr(b, "type", None) == "text").strip()
        return final, messages

    return "(stopped: hit the iteration cap before finishing)", messages


def converse(client, ctx, goal, verbose=True):
    """Run the agent, then accept follow-up instructions in the same context."""
    messages = None
    audit = []
    first = goal
    while True:
        final, messages = run_agent(client, ctx, goal=first, messages=messages, verbose=verbose, audit=audit)
        print(f"\n{'=' * 60}\n{final}\n{'=' * 60}")
        try:
            nxt = input("\nFollow-up ('q' to quit): ").strip()
        except EOFError:
            break
        if not nxt or nxt.lower() in ("q", "quit", "exit"):
            break
        first = nxt
    print(f"({len(audit)} tool call(s) this session)")


def gather_images(folder: Path):
    return sorted(Path(folder).glob("*.png"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the agent over a folder of screenshots.")
    ap.add_argument("--dir", default="tests/inbox", help="Folder of .png screenshots (default tests/inbox).")
    ap.add_argument("--out", default="reports", help="Where to save outputs (default reports).")
    ap.add_argument("--chat", action="store_true", help="Stay interactive for follow-up instructions.")
    ap.add_argument("--max-iters", type=int, default=MAX_ITERS)
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (add it to .env).", file=sys.stderr)
        return 1
    try:
        import anthropic
    except ImportError:
        print("anthropic not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    images = gather_images(args.dir)
    if not images:
        print(f"No .png screenshots in {args.dir}/.", file=sys.stderr)
        return 1

    ts = time.strftime("%Y%m%d_%H%M%S")
    ctx = ToolContext(
        client=anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]),
        images=images,
        cache_dir=Path(args.dir) / ".cache",
        out_dir=Path(args.out),
        out_name=f"agent_{ts}",
    )
    goal = (f"There are {len(images)} screenshot(s) available. Produce the best verified "
            f"output of what they show, following your instructions.")

    print(f"Agent running over {len(images)} screenshot(s) from {args.dir}/ ...\n")
    if args.chat:
        converse(ctx.client, ctx, goal)
    else:
        audit = []
        final, _ = run_agent(ctx.client, ctx, goal=goal, max_iters=args.max_iters, audit=audit)
        print(f"\n{'=' * 60}\n{final}\n{'=' * 60}")
        print(f"(guardrails: {len(audit)}/{args.max_iters} tool steps — {', '.join(audit) or 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
