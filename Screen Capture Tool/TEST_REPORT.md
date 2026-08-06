# Code Capture — Pre-Demo Test Report

Automated tests run in the sandbox (deterministic; no API/Mac needed). Date: Aug 2026.

## Results — all green

| Area | What was tested | Result |
|---|---|---|
| Regression suite | `pytest tests/test_logic.py` (stitch, parse, validators, savers) | **10/10 pass** |
| Compiler check — Python | good code passes, broken code caught (IndentationError) | **PASS** |
| Compiler check — JavaScript | good passes, missing `}` caught (`node --check`) | **PASS** |
| Compiler check — C | good passes, missing `;` caught (`gcc -fsyntax-only`) | **PASS** |
| Compiler check — C++ | good passes, missing `;` caught (`g++ -fsyntax-only`) | **PASS** |
| Compiler check — Java | checker wiring verified (resolves `javac`, passes good, catches bad) | **PASS** |
| Compiler check — C# | no toolchain present → **graceful skip** | **PASS** |
| Compiler PATH resolution | tools resolved to absolute paths (works inside the Finder-launched .app) | **PASS** |
| Team pipeline — Python clean | report with Errors=None + 3 diagrams | **PASS** |
| Team pipeline — Python w/ real error | real IndentationError reported; model-typed error ignored | **PASS** |
| Team pipeline — JavaScript clean | real `node --check` passes; Language=JavaScript | **PASS** |
| Team pipeline — C w/ real error | real compiler error surfaced | **PASS** |
| Team pipeline — non-code document | routes to doc path; no Errors/Diagrams sections | **PASS** |
| Faithfulness | Errors come only from the Decoder's real check, never invented | **PASS** |
| Accuracy harness (self-test) | char_sim 1.000, line_match 1.000, 3/3 compile (py/js/c) | **PASS** |
| Web — report scan | bundles + loose + pending listed correctly; diagrams field flows through | **PASS** |
| Web — session flags | default → team (no flag); `--single` passes through | **PASS** |
| Web — download | pending report promotes to `reports/` on download | **PASS** |
| Edge — stitch | overlapping scroll frames merged, no duplicated lines | **PASS** |
| Edge — phash dedup | identical frames dropped (dist 0), changed frames kept (dist ≥ 6) | **PASS** |
| Edge — empty capture | no frames → handled cleanly, no crash | **PASS** |
| Edge — analysis failure | exception mid-analysis → caught, status published, no hang | **PASS** |
| Full compile | every app source file + app.js + CSS | **PASS** |

## Live checklist — verify on the Mac (things the sandbox can't test)

These need real screen capture, the Anthropic API, and a browser:

- [ ] Launch `Code Capture.app` (double-click) — UI opens, logo + tagline correct
- [ ] Cmd+Shift+1 starts a capture; scrolling auto-captures; stops on idle
- [ ] Team run: flowchart shows Get_transcription → Analyze → Repair → Diagram → Finalize
- [ ] Rotating "Analyzing…" messages appear during analysis
- [ ] Report renders: overview with (Screenshot N) citations, tech-stack, code
- [ ] **Different languages on screen**: Python, JavaScript, C/C++, and one more (Java/Go/TS) — verify language detected + transcription faithful
- [ ] Clean code → Errors = None; genuinely broken code → real error shown (not invented)
- [ ] Diagrams render (class / interaction / component) — Mermaid draws with no errors
- [ ] "No classes" case shows the note, not a broken diagram
- [ ] Long file (many screens) — full coverage, no gaps; frame cap (80) not hit for normal files
- [ ] Save code / Save report downloads work
- [ ] Single-agent backup (toggle on) still produces a report
- [ ] Notifications appear (session started / captured / ready)
- [ ] Graceful failure UX: kill Wi-Fi mid-run → "Analysis failed" message, no hang
- [ ] Permissions persist after relaunch (Accessibility / Input Monitoring / Screen Recording)

## Notes
- Java now works: `javac` installed on the Mac (26.0.2). `check_source` resolves compilers
  by absolute path (searching Homebrew/JDK dirs), so Java/C/C++/JS checks run inside the
  bundled .app too — not just the Terminal dev server. C#/Go/Rust skip until their toolchains are installed.
- A saved report file in `reports/pending/` intentionally contains prose (not code)
  and is data, not source — it is not part of the compile check.
