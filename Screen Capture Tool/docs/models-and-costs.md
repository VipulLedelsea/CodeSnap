# Which model runs which step, and what it costs

Prices are the tool's own rates (`src/core/usage.py`, `PRICES`), in dollars per million tokens, input / output. Batch mode
(`CODESNAP_BATCH=1`) bills every call at half price; a call that falls back to live after a slow batch is billed in full.
Prompt caching of the system prompt is applied automatically (`cached_request`), so repeated prompts read at a fraction of the
input price.

| Model | Input / Output |
|---|---|
| claude-haiku-5-5 | 0.10 / 0.50 |
| claude-haiku-4-5 | 1.00 / 5.00 |
| claude-sonnet-5 and sonnet-5-5 | 2.00 / 10.00 |
| claude-opus-5-5 | 4.00 / 20.00 |

## Reading screenshots (every frame)

| Step name in the usage report | What it does | Model (default) | Change with |
|---|---|---|---|
| `read_first` | First read of a frame, plain lines | haiku-5-5 | `CODESNAP_PLAIN_MODEL` |
| `transcribe` | Second reader, used when the first read is not trustworthy | sonnet-5 | `CODESNAP_READ_MODEL` |
| `read_recheck` | Re-reads flagged lines at higher zoom | sonnet-5 | `CODESNAP_READ_MODEL` |
| `neighbor_reread` | Looks for an unclear line in the neighbouring frames | sonnet-5 | `CODESNAP_NEIGHBOR_MODEL` |
| `indent_review` | Checks indentation against the image (Python and similar) | sonnet-5 | `CODESNAP_READ_MODEL` |
| `column_review` | Checks COBOL columns against the image | sonnet-5 | `CODESNAP_READ_MODEL` |
| (kind check) | Code or application screen, one word back | sonnet-5-5 | `CODESNAP_TEXT_MODEL` |

## Per file, after reading

| Step | What it does | Model (default) | Change with |
|---|---|---|---|
| `classify` | Language, file type, short overview | sonnet-5-5 | `CODESNAP_TEXT_MODEL` |
| `analyst` | Plain-English overview and tech-stack note | sonnet-5-5 | `CODESNAP_TEXT_MODEL` |
| `fix` | Error-only repair of code that does not compile (only when it fails) | **opus-5-5** | `CODESNAP_MODEL` |
| `explain_error` | Explains the compiler errors | sonnet-5-5 | `CODESNAP_TEXT_MODEL` |
| `structure` | Entities and relations for the program model | **opus-5-5** | `CODESNAP_MODEL` |
| `ui_screen` | Application-screen reading | **opus-5-5** | `CODESNAP_MODEL` |
| `interpret_correction` | Turns a typed correction into model changes | sonnet-5-5 | `CODESNAP_TEXT_MODEL` |

## Staged batch pipeline

| Step | What it does | Model (default) | Change with |
|---|---|---|---|
| `deepdive` (draft) | Cheap first line-by-line review of every file | **haiku-4-5** | `CODESNAP_DRAFT_MODEL` |
| `deepdive` (final) | Full review, checking the draft's claims | sonnet-5 | `CODESNAP_FINAL_MODEL` |
| `deepdive_review` | Independent check of each finding | sonnet-5 | `CODESNAP_DEEP_REVIEW_MODEL` |
| `program_synthesis` | Cross-file observations | **opus-5-5** | no setting; `synthesize()` uses `CODESNAP_MODEL` |
| `report_reread` | Checks the draft report's claims against the code | sonnet-5 | `CODESNAP_FINAL_MODEL` |
| `exec_summary` | Executive summary | sonnet-5 | `CODESNAP_FINAL_MODEL` |
| `report_consistency` | Finds contradictions in the finished report | sonnet-5 | `CODESNAP_FINAL_MODEL` |

## Worth a look when comparing cost with quality

- **The draft model is haiku-4-5, ten times the price per token of the haiku-5-5 that reads the frames.** Whether haiku-5-5 drafts
  as well is a cheap test: set `CODESNAP_DRAFT_MODEL=claude-haiku-5-5` on a copy of a program.
- **Opus 5.5 is used for `structure`, `fix`, `ui_screen` and `program_synthesis`.** The reading bake-off in `analysis.py`
  found Sonnet 5 as accurate for reading at a fraction of the cost; nobody has measured that for these four steps.
- Spend on the batch-test-10-09 program (about 1,870 calls, $12.03 in all): `transcribe` $3.90, `structure` $3.09,
  `fix` $2.29, then about $1.7 of calls that were not labelled (the deep review and the first read, now named
  `deepdive` and `read_first`), then `analyst`, `indent_review`, `classify`. The usage report in the app now splits these by step.
