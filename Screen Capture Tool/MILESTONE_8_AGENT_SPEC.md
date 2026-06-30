# Milestone 8 — Agentic Mode (full spec)

**Goal:** evolve the tool from a fixed, pre-programmed pipeline into a
self-contained **agent** that decides what to do at runtime by calling tools —
reading captures, classifying, checking/fixing code, saving output, asking for
more captures, and (later) driving capture, remembering context, and conversing.
The deterministic pipeline stays as the default path; agent mode is additive.

**Mechanism:** the Anthropic Messages API tool-use loop (function calling) — no
Agent SDK. We describe tools, the model picks one, we run it and feed the result
back, repeat until done.

**Status legend:** ✅ built & tested · 🟡 partial / stub · ⬜ planned

---

## Architecture at a glance

```
Human ──goal/permission──▶ Agent loop (agent.py) ──picks a tool──▶ tools.py
   ▲                              │                                   │
   │ "ask for more"               │ observes result                   ▼
   └──────────────────────────────┘                            core/ (real logic)
                                   └──────────────▶ Verified output (reports/)
```

The agent loop never runs work itself — it chooses; `tools.py` wrappers call the
real functions in `core/`; results flow back into the conversation, which is the
agent's working memory.

## Components

| Component | File | Status |
|---|---|---|
| Engine logic (extract, classify, fix, validate, savers) | `core/analysis.py`, `core/validate.py`, `core/outputs.py` | ✅ |
| Tool registry (schemas + thin wrappers + dispatch) | `tools.py` | ✅ |
| Agent loop (`run_agent`) + system prompt | `agent.py` | ✅ |
| Offline runner (`--dir`, default `tests/inbox/`) | `agent.py` | ✅ |
| Guardrails: iteration cap, never-execute-code, errors-as-text | `agent.py`, `tools.py` | ✅ |
| Conversational REPL + session memory | `agent.py` | ⬜ (Phase 2) |
| Live hotkey integration (`--agent`) | `hotkey_capture.py` | ⬜ (Phase 3) |
| Guardrails: permission prompts, cost budget, audit log | TBD | ⬜ (Phase 4) |

## Tools — and what each connects to

| Tool | Connects to | Status |
|---|---|---|
| `list_captures` | inline (reads `ctx.images`) | ✅ |
| `read_capture` | `core.analysis.extract_to_cache` / `extract_one` (+ content-hash cache) | ✅ |
| `classify` | `core.analysis.synthesize_final` | ✅ |
| `check_code` | `core.validate.check_source` (compile-only) | ✅ |
| `fix_code` | `core.analysis.fix_source` | ✅ |
| `save_output` (source / docx / text) | `core.outputs.save_source_file` / `save_docx` / `save_text` | ✅ |
| `request_more_captures` | stub today; interactive in P3 | 🟡 |
| `capture_screen` / `capture_region` | `hotkey_capture.capture_full_png` / `capture_region_png` | ⬜ (Phase 3) |
| `save_output` (pdf / csv) | extend `core.outputs` | ⬜ (Phase 4) |
| `plan` | new reasoning tool | ⬜ (Phase 4) |
| `lint` / `run_tests` / `git` | new tools | ⬜ (Phase 4) |
| `memory_read` / `memory_write` | new cross-run store | ⬜ (Phase 4) |

---

## Phase breakdown

### Phase 1 — Core loop ✅ (built, mock-tested, pytest green)
Self-contained tool-use loop running offline over a folder of screenshots.
- Built: `core/` refactor (+ `core/outputs.py`), `tools.py` registry, `agent.py` loop + offline runner.
- Delivers: **any content type** + **smarter verification**, offline.
- Run: `python agent.py` (uses `tests/inbox/`).
- Guardrails present: 14-iteration cap, compile-only (never runs code), tool errors returned as text.

### Phase 2 — Conversation + memory ⬜
Turn the one-shot run into an ongoing session.
- After the first result, an interactive prompt; the user's instruction is
  appended to the same conversation and the loop continues.
- Delivers: **conversational follow-ups** ("redo as PDF", "just the imports",
  "do the next file"); session memory = the persisted conversation.
- Files: `agent.py` (REPL wrapper around `run_agent`, persistent `messages`).
- Connects to: existing tools (no new ones strictly required; may extend
  `save_output` formats).

### Phase 3 — Live capture integration ⬜
Bring the agent into the existing hotkey workflow.
- `python hotkey_capture.py --agent` → same hotkeys/capture; at **stop**, route
  the session's screenshots to `run_agent` instead of the deterministic pipeline.
- New tools: `capture_screen`, `capture_region` (wrap existing capture fns) so
  the agent can also *initiate* a capture.
- `request_more_captures` becomes **interactive**: agent pauses, user snaps more
  with the hotkeys (listener still running), presses Enter, wrapper re-scans the
  session folder and feeds the new shots back.
- Delivers: **ask for more captures**, agent-driven capture.
- Files: `hotkey_capture.py` (flag + routing), `tools.py` (capture tools, live
  `request_more_captures`), `agent.py` (reused).

### Phase 4 — Expanded autonomy ⬜ (optional / future)
- More **Act** tools: PDF/CSV export, linters, multi-file write, git.
- **Plan** tool for multi-step jobs; **self-review** pass.
- **Cross-run memory** store (remembers projects/preferences between sessions).
- Stronger **guardrails**: permission prompts before sensitive actions
  (capture, overwrite, delete), a cost/budget ceiling, and an audit log of every
  tool call.

---

## Honest boundaries
- The agent cannot see the screen on its own — capture needs OS permission and a
  human at the machine; the agent decides *when*, not *whether it's allowed*.
- More autonomy = more tokens/latency and less determinism; the Phase 4
  guardrails (permissions, budgets, logging) are what keep it safe to let act.
- Keep a human in the loop for anything destructive.

## Build order / dependencies
P1 ✅ → P2 (independent) → P3 (depends on P1 tools + the hotkey app) → P4 (any time).
Each phase is a small, testable addition on the existing loop — nothing is rebuilt.
