# Screen Capture Tool — Requirements

_Last updated: 2026-06-16_

## Core purpose
Take an image of a screen and return a clear explanation of what's on it. The MVP is exactly that, run manually on a single screenshot. Anything fancier goes on a "later" list.

**Design intent:** the program is a thin capture client. It grabs the screen and hands the image to Claude via the **Anthropic API**; Claude does the reading, classifying, and explaining. We call the API directly and shape behavior through prompts — we do *not* use the Claude Agent SDK or build an agent loop framework.

## Authorization
Teaching project; user has authorization to access the content. Caveat noted: "authorized to access" is not the same as "authorized to extract/reproduce elsewhere" — keep in mind, not a blocker.

## Stack
- Python throughout
- `mss` + `Pillow` for screen capture (grab pixels, save the frame to disk)
- **Anthropic API** via the `anthropic` Python SDK as the processing brain — the screenshot is base64-encoded and sent as an image content block to the Messages API with a vision-capable model; we handle the request/response ourselves.
- Auth: a **Claude Platform API key** (pay-as-you-go), read from `ANTHROPIC_API_KEY` in `.env` (via `python-dotenv`).
- FastAPI + a basic web page later, only if a real UI is wanted
- Explicitly avoiding for v1: Electron, queues, databases, microservices, premature abstractions

## The five layers
1. **Understanding** — the heart, and the biggest unknown. Can Claude reliably read & explain content from a screenshot? Validate first. We feed it the image and a good prompt via the Messages API.
2. **Capture** — grab pixels (`mss`), full screen or region, on a hotkey or interval; save the frame to a file we can encode and send.
3. **Routing** — classify what's on screen (code, legal doc, spreadsheet, diagram, UI, chart, prose, etc.) and explain with an approach suited to that type.
   - **Done via prompt engineering**, not an agent framework: we craft the system/user prompt so Claude performs the typing and routing in its response.
   - **Content typing is OPEN-ENDED**: Claude decides the content type on the fly each time; no hardcoded category list.
   - **Fallback**: if open-ended typing produces too many errors / low-quality explanations, constrain toward a predefined set of content types with tuned per-type prompt instructions.
4. **State/context** — keep prior captures/explanations and pass them back in the `messages` array (multi-turn) so explanations build on each other instead of treating each screenshot as isolated. We manage this history ourselves.
5. **Output** — terminal first; UI only once the core works.

## Milestones (riskiest slice first)
1. ~~**Foundation**~~ ✅ *(completed 2026-06-17)* — repo, virtualenv, `anthropic` installed, API key in `.env`, a "hello Claude" Messages API call returns text (`hello_api.py`).
2. **Core value end-to-end** — manual screenshot saved to disk → base64-encoded → sent as an image block in a Messages API call with a prompt → printed explanation. Do not move on until this feels good.
2.5. **Multi-image doc export** — accept multiple image files; for each, explain what's on screen and extract any visible text preserving its original structure (headings, lists, tables, paragraphs); combine all output into a single `.docx`, one section per image.
3. **Real capture** — hotkey-triggered region/full-screen capture feeding step 2 automatically.
4. **Content routing** — prompt-engineer open-ended content typing, then have Claude explain with an approach suited to that type. (Prompt work, not loop-building.)
5. **Multi-capture context** — dedupe near-identical frames, stitch, maintain running context across screens by passing prior messages/explanations back in the `messages` array.
6. **UI + polish** — only what you'll actually use.

## Solo-build traps to watch
- No accountability — set visible milestones.
- Claude does the heavy lifting on understanding; resist re-implementing its reasoning yourself. Lean on good prompts before adding code.
- Steps 4 & 5 are tempting to over-engineer; start with a single well-crafted prompt and simple history before anything clever.
- Tempting to build a slick UI before the core understanding is solid; don't.
