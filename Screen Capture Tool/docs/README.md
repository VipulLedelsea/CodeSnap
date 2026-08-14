# Code Capture

**Capture code from your screen and get a clean, verified report.** A team of AI
agents transcribes what's on screen *exactly*, checks it against a real compiler,
fixes only genuine errors, and produces a report with a plain-English overview, a
tech-stack review, and auto-generated diagrams — all viewable and downloadable in
a local web app.

Built by Ledelsea · macOS · Python.

---

## Contents

- [Getting started](#getting-started)
- [How it works](#how-it-works)
- [Features](#features)
- [The multi-agent team](#the-multi-agent-team)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running it](#running-it)
- [Hotkeys](#hotkeys)
- [macOS permissions](#macos-permissions)
- [Supported languages](#supported-languages)
- [Packaging as a macOS app](#packaging-as-a-macos-app)
- [Testing](#testing)
- [Project structure](#project-structure)
- [How it stays faithful](#how-it-stays-faithful)
- [Cost](#cost)
- [Roadmap](#roadmap)

---

## Getting started

### For Mac users

One command sets everything up and launches the app:

```bash
git clone https://github.com/Vipuld14/ScreenCaptureInterpreter.git
cd "ScreenCaptureInterpreter/Screen Capture Tool"
python3 run.py
```

`run.py` creates a virtual environment, installs the dependencies, asks for your
Anthropic API key the first time (saved locally to `.env`, never committed), and
opens the app in your browser. Then: **Start capture** -> switch to your editor ->
**Cmd+Shift+1** -> scroll -> the report appears under *Recent results*.

Build the double-click macOS app instead of running from the terminal:

```bash
python3 run.py --build
```

That produces `dist/Code Capture.app` -- drag it to `/Applications`. First run
needs the macOS permissions in **Privacy & Security** (Screen Recording,
Accessibility, Input Monitoring) -- see [macOS permissions](#macos-permissions).

### For Windows users

Windows runs the app **from source** (the double-click `.app` is macOS-only).
Same repo, use `python` instead of `python3`:

```bash
git clone https://github.com/Vipuld14/ScreenCaptureInterpreter.git
cd "ScreenCaptureInterpreter\Screen Capture Tool"
python run.py
```

That sets up the environment and opens the browser UI the same way. What differs
on Windows:

- The start/capture hotkey is **Win+Shift+1** (the `Cmd` key maps to the Windows key). If it clashes with a system shortcut, keep the terminal window focused.
- You may need to run the terminal **as Administrator** for the global hotkey to register.
- Desktop notifications are macOS-only and are silently skipped -- watch the browser's live status instead.
- Region capture (Win+Shift+8) is macOS-only; use the default **burst** mode, which captures the full screen.
- No packaged `.exe` -- run from source with `python run.py`.

> Code Capture was built and tested primarily on macOS; Windows support is
> run-from-source and less battle-tested.

## How it works

1. **Capture** — start a session and scroll. It screenshots the screen on a timer
   and uses perceptual hashing to keep only the frames that changed, dropping
   near-duplicates. It stops on its own when you stop scrolling.
2. **Read faithfully** — a cheap model (Claude Haiku) transcribes each frame
   verbatim and caches the result. Overlapping scroll frames are stitched so no
   lines are duplicated.
3. **Verify** — the code is checked with the language's real compiler/parser. Any
   errors reported are *real* errors from the toolchain, not guesses.
4. **Report** — you get the language, a plain-English overview with
   `(Screenshot N)` citations, the errors found, the corrected code, a top-5
   tech-stack review, and class / interaction / component **diagrams**.

The report appears in the web UI with a live pipeline view, and both the code and
the report can be downloaded.

## Features

- **Automatic burst capture** — scroll and it captures for you; perceptual-hash
  de-duplication keeps only changed frames.
- **Faithful transcription** — the reader never invents, completes, or "fixes"
  code; incomplete captures are flagged, not guessed.
- **Real compiler checks** — Python, JavaScript, C, C++, Java (and more when the
  toolchain is present). Missing toolchains are skipped, never failed.
- **Auto-generated diagrams** — class, interaction (sequence), and
  component/module diagrams drawn from the captured code (Mermaid).
- **Two-model cost routing** — cheap model for transcription, stronger model for
  reasoning; images are downscaled before sending.
- **Local web UI** — live pipeline flowchart, rotating status while analysing,
  and per-portion downloads (Save code / Save report).
- **Packaged app** — ships as a double-click macOS `.app`.
- **Resilient** — automatic API retries and graceful failure messages so a run
  never hangs silently.

## The multi-agent team

By default, a **Coordinator** delegates to four specialists, each with its own
model and a strict role:

| Agent | Model | Job |
|---|---|---|
| **Extractor** | Haiku | Verbatim transcription only — no ability to alter code |
| **Analyst** | Sonnet | Classify + write the overview and tech-stack review |
| **Decoder** | Sonnet | Compiler-check the code and apply minimal, real fixes |
| **Diagrammer** | Sonnet | Draw the class / interaction / component diagrams |

A single-agent path is kept as a `--single` backup.

## Requirements

- macOS, Python 3.10+
- An Anthropic API key (`ANTHROPIC_API_KEY`)
- Optional, for compiler checks: `node`, `gcc`/`clang`, `g++`, `javac`, … — any
  missing language is simply skipped

## Setup

```bash
python3 -m venv ~/sct-venv && source ~/sct-venv/bin/activate
pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

> Tip: keep the virtual environment **outside** an iCloud-synced folder
> (e.g. `~/sct-venv`) — syncing makes imports and builds slow.

## Running it

**Web app (recommended):**
```bash
python src/main.py
```
Opens the browser UI → **Start capture** → switch to your editor → press
**Cmd+Shift+1** → scroll. The report appears under *Recent results*.

**Command line:**
```bash
python src/main.py --capture            # capture worker, multi-agent team (default)
python src/main.py --capture --single   # capture worker, single-agent backup
```

## Hotkeys

| Key | Action |
|---|---|
| **Cmd+Shift+1** | Start / stop a session |
| **Cmd+Shift+2** | Capture the full screen (manual) |
| **Cmd+Shift+8** | Capture a region (drag-select) |
| **Cmd+Shift+7** | Capture the next part after you scroll (owned session) |
| **Cmd+Shift+9** | Quit (or Ctrl+C in the terminal) |

(Cmd+Shift+3/4/5/6 are avoided — macOS reserves those for screenshots.)

## macOS permissions

The capture worker needs, in **System Settings → Privacy & Security**:

- **Screen Recording** — to read the screen
- **Accessibility** and **Input Monitoring** — for the global hotkey

When running the web app from Terminal, grant these to your **terminal app**.
When running the bundled `.app`, grant them to **Code Capture** (and re-grant
after each rebuild — see DEPLOY.md).

## Supported languages

Compiler/parser checks run for: **Python** (built-in), **JavaScript**
(`node --check`), **C** (`gcc`/`clang`), **C++** (`g++`/`clang++`), **Java**
(`javac`), and **C#** (`csc`, if installed). Compilers are resolved by absolute
path, so checks work inside the bundled app too. Any language without a toolchain
is transcribed and reported, just not compiler-verified.

## Packaging as a macOS app

See **[DEPLOY.md](DEPLOY.md)**. In short:

```bash
pyinstaller --noconfirm packaging/CodeCapture.spec
xattr -cr "dist/Code Capture.app"
codesign --force --deep --sign - "dist/Code Capture.app"
```

`main.py` is the single entry point: it runs the web app by default and the
capture worker with `--capture`, so everything fits in one binary.

## Testing

```bash
python -m pytest tests/test_logic.py          # regression suite
python tests/accuracy_harness.py --selftest   # extraction accuracy (offline)
```

Full pre-demo results are in **[TEST_REPORT.md](TEST_REPORT.md)**.

## Project structure

```
Code Capture.command   double-click launcher (starts the web app)
requirements.txt       Python dependencies
src/                   all application code
  main.py                single entry point (web app / --capture worker)
  hotkey_capture.py      the capture App (hotkeys, burst mode)
  agent.py               single-agent tool-use loop
  team.py                multi-agent team (Coordinator + Extractor/Analyst/Decoder/Diagrammer)
  tools.py               tool registry + ToolContext
  core/                  engine: analysis, validate, outputs, capture, notify, status
  webapp/                FastAPI server + browser UI (static/)
docs/                  README, DEPLOY, DEMO_GUIDE, TEST_REPORT, REQUIREMENTS
deliverables/          slide deck, Q&A prep, internship report, architecture html
packaging/             CodeCapture.spec + build_app.command (build the .app)
assets/                images used by docs/deliverables
demo_samples/          sample code files for demos
tests/                 pytest suite + accuracy harness
captures/  reports/    runtime output (gitignored)
```

Run it from the project root:

```
python src/main.py            # web app (default)
python src/main.py --capture  # capture worker (the web app launches this itself)
```

## How it stays faithful

The whole point is to report what's actually on screen. The Extractor cannot edit
code; the errors come only from the real compiler check (never invented); and
diagrams are drawn only from captured code. If a capture is incomplete or cut off,
it's flagged with a marker — never filled in.

## Cost

Transcription (the high-volume step) uses the cheaper model; only reasoning uses
the stronger one. Every screenshot is downscaled to a 1568px long edge before
sending, and each frame is transcribed once and cached. More captured frames means
more transcription cost, so scroll steadily rather than capturing far more than you
need.

## Roadmap

The web UI shows two upcoming modules marked *soon*: **Documents** (summarise
articles/notes) and **Data extract** (pull tables/structured data). The core
engine already routes non-code content, so these are extensions of the same
pipeline.
