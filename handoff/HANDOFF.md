# CodeSnap handoff to Claude — 2026-10-02

## 1. Changes made
See [CHANGES.md](CHANGES.md) for one line per changed application file. Covers capture/recapture, source spacing, screen-only technology analysis, evidence-based reports, UI reliability and prompt caching. The local `CodeSnap-changes.patch` is against the pre-push `origin/main`, including two already-created local commits: `12f96a6` (synthetic legacy test program) and `2530c6d` (source corrections/line references).

## 2. Issues fixed
- Screenshot counter lagged: worker and shared caches were out of sync; progress now counts current-session reads once.
- Failed replacements looked complete or could target stale program state: added ownership, retry and pending-state guards.
- Indentation/literal spaces changed during OCR/rebuild: one pixel-measured path now protects literals, source labels and accepted corrections.
- Reports overstated evidence or disagreed across exports: current-source checks, release gates and Word-derived HTML now qualify findings consistently.
- Paragraph lines ended early: removed fixed-character hard breaks. Yellow label now reads “Needs changes” in dark amber.

## 3. Open issues
- Live acceptance remains: restart at idle, capture overlapping code screens, watch the read counter, force one failed recapture, then retry and compare the resulting source with the screen.
- Recalibrate the first source column after moving/zooming/sideways scrolling; whole-cell movement can evade geometry detection. Tabs, clipped/hidden text and invisible bytes remain limitations.
- Narrow multi-column report tables still wrap words tightly; generate a report and inspect the integration/risk registers.
- Final issue/sign-off remains blocked where source review, deployment or business evidence is missing; do not bypass “Blocks issue” rows.

## 4. Unverified or risky
- No paid provider or native live-capture acceptance test was run for these final changes. Prompt-cache savings and semantic accuracy across all 218 labels are unverified.
- The 218-label catalog supports visible text/screens, not native project import, compiler/runtime compatibility or hidden material. Synthetic matrices do not prove every historical dialect.
- Scope is broad: accumulated report, security, rating, architecture and privacy changes are included, not only the last amber/wrapping edit. Review the file manifest and patch.
- Earlier spacing publication changed six live saved-source versions (1,376 edits), backed up and compared to 12,122 original nonblank rows. Live databases/captures/reports are deliberately excluded from this public GitHub push.
- Local DB fixtures and real screenshot cases are excluded; the complete local suite is not reproducible from a fresh checkout without those private fixtures.

## 5. Current state
Python compilation, JavaScript syntax and whitespace checks passed. Final full local offline suite: **1,671 passed, 1 expected failure, 3 dependency warnings**, 334.51 seconds, zero network/provider attempts (see [test-results.txt](test-results.txt)). Prior final focused report checks: 72 passed; earlier wider report/deep-review checks: 245 passed (overlapping counts).
The app has not been restarted or demonstrated running with the final code. Restart it at idle before live acceptance; report cache revision is v13.

Run offline checks from `Screen Capture Tool/`: `.venv/bin/python tests/offline_runner.py tests -q`. Use the normal project setup to install dependencies; private fixtures are required for the full local result.
