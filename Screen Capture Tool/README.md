# Screen Capture Tool

Capture screenshots with a hotkey and turn them into a clear explanation, a Word
document, or — when the screenshots are code — a checked, runnable source file.

The program is a **thin capture client**: it grabs the screen and hands the
images to Claude through the **Anthropic API**. All the reading, classifying,
and reasoning is done by the model via direct API calls — there is no
hand-built "understanding" engine and no agent framework.

## How it works

1. **Capture** — a global hotkey grabs the full screen (`mss`) or a region you
   drag (`screencapture`). Each shot is saved to a per-session folder.
2. **Read (in the background)** — the moment a screenshot lands, it's sent to
   Claude to extract its text. Results are cached by image content hash, so an
   identical frame is never read twice.
3. **Stitch** — when you stop, the per-image text is merged into one document,
   removing the overlap between consecutive scroll captures.
4. **Classify + route** — one call summarises the document and decides whether
   it's code. Non-code → a Word `.docx`. Code → a real source file.
5. **Check + fix (code only)** — the source file is syntax/compile-checked with
   the *local* toolchain (never run). If it fails, the compiler errors are sent
   back to Claude to fix transcription mistakes, then re-checked — up to 3 times.

## Requirements

- Python 3.10+
- An **Anthropic API key** (Claude Platform / Console, pay-as-you-go)
- macOS (region capture and the global hotkeys use macOS facilities)
- Optional, for code-mode checks: `node` (JS), `gcc`/`clang` (C/C++),
  `csc` (C#), `javac` (Java). Python is checked with its own parser, no install
  needed. Missing toolchains are skipped gracefully.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Add your key to a `.env` file in this folder (it is gitignored — never commit it):

```
ANTHROPIC_API_KEY=sk-ant-...
```

### macOS permissions

Grant these to your terminal app (Terminal / iTerm) in
**System Settings → Privacy & Security**, then restart the terminal:

- **Input Monitoring** and **Accessibility** — for the global hotkey listener
- **Screen Recording** — for screen capture

On first run the hotkeys may do nothing until these are granted.

## Usage

```bash
python hotkey_capture.py
```

| Hotkey | Action |
| --- | --- |
| `Cmd+Shift+1` | Start / stop a session (toggle) |
| `Cmd+Shift+2` | Capture the full screen |
| `Cmd+Shift+8` | Capture a region (drag-select; `Esc` cancels) |
| `Cmd+Shift+9` | Quit (analyses a pending session first, then deletes this run's captures) |

Typical flow: press `Cmd+Shift+1` to start, snap a few screenshots, press
`Cmd+Shift+1` again to analyse. You'll see the overview and extracted text, then
be asked whether to save the output. Press `Cmd+Shift+9` to quit; captured PNGs
for the run are deleted, while saved outputs in `reports/` are kept.

## Outputs

Saved outputs go to the `reports/` folder (gitignored):

- **Documents** → `report_<timestamp>.docx`
- **Code** → `report_<timestamp>.<ext>` (`.py`, `.js`, `.c`, `.cpp`, `.cs`, …),
  detected automatically, with a chance to confirm or override the extension at
  save time.

## Code mode

When a session is detected as code, the tool:

- identifies the language and picks the file extension,
- saves the extracted code as a source file,
- runs the language's real syntax/compile checker locally (Python `ast`,
  `node --check`, `gcc -fsyntax-only`, etc.) — **check only, it never runs your
  code**,
- on failure, sends the compiler errors back to Claude to correct transcription
  mistakes (minimal, faithful fixes — no inventing logic), then re-checks, up to
  3 attempts.

**Honest limits:** "compiles" is not the same as "behaves correctly," output
quality depends on how cleanly the code was transcribed from pixels (high-zoom,
sharp screenshots help a lot), and a partial capture can't be turned into a
complete program. Treat the result as a strong draft you can run and tidy.

## Project layout

```
hotkey_capture.py   Entry point: hotkey listener, capture sessions, output routing
analysis.py         Engine: per-image extraction, caching, stitching, classify, fix
validate.py         Local syntax/compile checkers (check only)
requirements.txt    Dependencies
.env                Your API key (gitignored)
captures/           Scratch screenshots, per session (gitignored, deleted on quit)
reports/            Saved .docx / source files (gitignored)
Previous Versions/  Earlier single-image scripts, kept for reference
```

## Privacy

Screenshots are sent to the Anthropic API for analysis, so whatever is on screen
leaves your machine. Avoid capturing passwords or other secrets. Generated
reports are written unencrypted to `reports/`, which is gitignored to keep
extracted screen text out of the repository.

## Notes

- The model is set by `MODEL` in `analysis.py` (a vision-capable Claude model).
- Sending all images in one request is avoided by design — each image is read
  once and the results are stitched locally — which keeps cost and latency down
  and avoids truncation on long documents.
