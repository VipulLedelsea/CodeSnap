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

SYSTEM_PROMPT = (
    "You turn captured screenshots into the best, verified output. You work by "
    "calling tools — you cannot see the screenshots until you read them.\n"
    "Recommended approach:\n"
    "  1. Call list_captures to see how many there are.\n"
    "  2. read_capture each one (in order) to get its text.\n"
    "  3. Decide what the content is. If it spans several shots, treat them as one document.\n"
    "  4. If a capture looks cut off or incomplete, call request_more_captures instead of guessing.\n"
    "  5. If it is code: save_output as a 'source' file with the right extension, then check_code; "
    "if it fails, use fix_code on the reported errors and check again (a few times). "
    "Fix only transcription errors — never invent code.\n"
    "  6. If it is a document/prose: save_output as 'docx'. Otherwise 'text'.\n"
    "  7. When done, briefly tell the user what you produced and where.\n"
    "Never execute the captured code (check_code only compiles/parses). Be economical: "
    "do not re-read a screenshot you already read."
)


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
