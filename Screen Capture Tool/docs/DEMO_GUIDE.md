# Code Capture — Demo Guide

Two parts: the **Script** (what to say) and the **Runbook** (what to do, with
fallbacks). Target: ~7 minutes, mixed team audience.

> The golden rule: **the demo is only as reliable as the capture.** Use a file
> that fits on one screen, turn the editor's line numbers OFF, and you'll get a
> clean result every time. Everything below is built around that.

---

## Part 1 — Demo Script

### 0. Hook (20 sec)
> "How often do you see code you want — in a screenshot, a video, a slide, someone
> else's screen — and there's no way to copy it? You retype it and introduce bugs.
> Code Capture turns anything on your screen into clean, **verified** code — with a
> team of AI agents."

### 1. The problem (30 sec)
- Code lives in un-copyable places: screenshares, PDFs, videos, tutorials, images.
- Retyping is slow and error-prone; plain OCR gives you messy text, not verified code.
- The promise: **"You get back clean code that we've run through a real compiler —
  plus an explanation and diagrams."**

### 2. Live demo — the centerpiece (2.5 min)
Have `quick_library.py` (or `todo_app.py`) open, **line numbers off**, fitting on screen.
1. "I open the app — it's a normal Mac app." (open `Code Capture.app`)
2. "I hit Start, switch to my editor, press **Cmd+Shift+1**."
3. For `quick_library.py`: **don't scroll** (one screen). For `todo_app.py`: **one slow,
   smooth scroll** top to bottom. Narrate: "it captures as I scroll and drops
   near-duplicate frames with perceptual hashing."
4. Point at the **live pipeline**: "Watch the team — read, analyse, check, diagram,
   finalise." (the flowchart advances live)
5. Report lands — walk it top to bottom:
   - **Overview** in plain English, with `(lines N–M)` citations.
   - **Errors found** — "This is checked against the *real* compiler. Valid code says
     None — meaning we verified it compiles."
   - **The code** — clean and downloadable.
   - **Tech-stack review** — is it current, and any worthwhile improvements.
   - **Diagrams** — class, interaction, and component diagrams drawn from the code.

### 3. The verification angle (45 sec)
- Capture `calculator_broken.py` (a real IndentationError): "and when the code on
  screen actually has a bug, the compiler catches it — that's a *real* error, not a
  guess — and the team fixes it in the Code section."
- If you didn't rehearse this and aren't sure it'll surface, **skip the live capture
  and show the pre-generated error report** in your fallback tab instead.

### 4. How it works (1 min)
- "Under the hood it's a **team of AI agents**, each with one job:"
  - **Extractor** — transcribes exactly what's on screen (can't rewrite logic).
  - **Analyst** — writes the overview + tech review.
  - **Decoder** — runs the real compiler and fixes only genuine errors.
  - **Diagrammer** — draws the diagrams.
  - A **Coordinator** runs the team.
- "Splitting the work keeps it faithful and reliable."

### 5. It's a real product (30 sec)
- "This isn't a script — it's a double-click Mac app, built on the Anthropic API."
- Sidebar: "Documents and Data-extract are next — same pipeline, new content types."

### 6. Close (20 sec)
> "Point Code Capture at code anywhere and get back verified, documented, diagrammed
> results you can actually use."

**Anticipated Q&A**
- *Accuracy?* "Extraction is done by a strong model and the output is compiler-checked,
  so the code you get is verified to compile."
- *Cost?* "Cost-aware model routing and downscaled images keep it efficient."
- *Privacy?* "Runs locally; screenshots go only to the Anthropic API for reading."
- *Languages?* "Python, JavaScript, C, C++, Java today."
- *Long files?* "Best on what fits a screen or two; very long, fast-scrolled captures
  are the hardest case — we reconstruct from overlapping frames."

---

## Part 2 — Runbook (what to do)

### The night before / setup (do once)
- [ ] Rebuild the app so it has the latest code: `./build_app.command`
- [ ] Grant permissions to **Code Capture** (System Settings → Privacy & Security):
      Screen Recording, Accessibility, Input Monitoring
- [ ] `ANTHROPIC_API_KEY` present at `~/.code_capture/.env`
- [ ] **Editor: turn line numbers OFF** (this is the #1 thing that keeps captures clean)
- [ ] Open the three samples, each sized to fit on screen:
      - `demo_samples/quick_library.py` — clean, one screen (main demo)
      - `demo_samples/todo_app.py` — clean, one gentle scroll (to show scrolling)
      - `demo_samples/calculator_broken.py` — one screen, real IndentationError
- [ ] **Rehearse each capture once.** Confirm: clean file → Errors None + diagrams;
      broken file → the IndentationError actually shows.
- [ ] **Save the fallback tabs:** after a good rehearsal run of the clean file AND the
      broken file, leave both reports open in browser tabs (Recent results). If a live
      capture misbehaves, switch to these real reports.

### Just before you present
- [ ] Turn on Do Not Disturb / Focus **off**-ish: allow notifications so the session
      banners show, but close anything that might pop up mid-demo.
- [ ] Solid internet.
- [ ] Screen mirroring tested; browser zoom set so the report is readable.

### Running it (exact sequence)
1. Open `Code Capture.app` → browser UI opens.
2. Click **Start capture**.
3. Switch to the editor showing `quick_library.py`.
4. Press **Cmd+Shift+1**. **Do not scroll** (one screen) → it auto-stops and analyses.
5. Walk through the report (overview → errors none → code → tech → diagrams).
6. (Optional scroll demo) Repeat with `todo_app.py`: press Cmd+Shift+1, do **one slow
   smooth scroll** top to bottom.
7. (Verification beat) Repeat with `calculator_broken.py` → the IndentationError shows.
8. Click **Save code** / **Save report** to show downloads.

### If something goes wrong
- **Hotkey does nothing** → permissions weren't granted to this build. Use the fallback
  report tab: "here's one I ran earlier."
- **Capture looks duplicated / garbled** → you scrolled too fast or the file was too
  long. Re-run on a one-screen file with no scroll, or use the fallback tab.
- **Broken-file error doesn't show** (extraction cleaned it) → don't dwell; show the
  pre-generated error report from your fallback tab instead.
- **Network/API hiccup** → app shows "Analysis failed — try again"; re-run or use fallback.
- **A diagram doesn't render** → scroll past it; the rest still tells the story.
- **App won't open (Gatekeeper)** → right-click the app → Open (once).

### Golden rules
- **Line numbers OFF, file fits one screen, slow scroll (if any).** Most issues trace
  back to these.
- **Always have the fallback tabs open.** You stay calm even if a live run hiccups.
- Lead with the **clean, compiler-verified result** — that's what's rock-solid. Treat
  the error catch as a bonus, backed by the fallback report.
