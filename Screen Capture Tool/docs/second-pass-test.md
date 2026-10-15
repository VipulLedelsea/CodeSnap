# Second-pass test on the modern files

Goal: find out, on files whose originals we have, how much a second capture closes the gap to 99.9%. The first pass is the
existing program `batch-test-10-09` (30 files from `~/Downloads/mn-sdams`, 97.9% of lines right). This test adds a second,
independent capture of some of those files and scores the first pass, the second pass and the combination of the two against
the originals.

## What to capture

Start with the **starter set** (94 screenshots in the first pass, so about that many paid reads again). If the numbers look
good, add the rest of the **full set** (402 screenshots in the first pass).

| File | Original | First-pass screenshots | Why it is in the set |
|---|---|---|---|
| AUTH.py | `backend/routers/auth.py` | 33 | missing head, repeated dividers |
| DATABASE.py | `backend/database.py` | 14 | a block read twice |
| CONFIG.py | `backend/config.py` | 10 | missing head, banner dashes |
| NOTIFICATIONS.py | `backend/routers/notifications.py` | 37 | missing lines, docstring prose |
| *(full set)* APPLICATIONS.py | `backend/routers/applications.py` | 57 | indentation, extra lines |
| *(full set)* NOTIFICATION.py | `backend/services/notification.py` | 43 | docstring indentation |
| *(full set)* WORKFLOWS.py | `backend/routers/workflows.py` | 83 | long file, dividers |
| *(full set)* WORKFLOWTRACKER.tsx | `frontend/src/components/WorkflowTracker.tsx` | 125 | red squiggles, deep JSX indentation |

## How to capture (from your own terminal, not from a Claude session)

1. Make a **new program** (for example `pass2-modern`) so the first pass is left alone.
2. Use the **same capture settings as the first pass**: capture area is only the source pane (no file explorer, tabs or
   terminal), column one clicked, same editor, theme, font and zoom. A different zoom is fine, a different pane is not.
3. Name each file exactly as in the first pass (`AUTH.py`, `DATABASE.py`, ...). The comparison matches files by name, ignoring
   case and any number prefix.
4. Open the file, start the capture, and scroll through at a **different pace** from the first time (slower or faster): the
   point is that the two passes make different mistakes, so the seams between screenshots should fall in different places.
5. The capture scrolls the file to its first line before the first screenshot. Check that the first screenshot really shows
   line 1; that guard has not been tried on a live window yet. If it did not scroll, scroll to the top by hand first.
6. Wait for every file to finish analysing before the next step.

## How to score it

Copy both programs, so the live data is never opened, and run the scorer:

```bash
S=$(mktemp -d)
mkdir -p "$S/progs"
cp -R ~/CodeSnap/programs/batch-test-10-09 ~/CodeSnap/programs/pass2-modern "$S/progs/"
mkdir "$S/originals"
for f in backend/routers/auth.py backend/database.py backend/config.py backend/routers/notifications.py; do
  cp ~/Downloads/mn-sdams/$f "$S/originals/"
done
CODESNAP_PROGRAMS="$S/progs" ~/sct-venv/bin/python tests/quality/second_pass_eval.py \
  --first batch-test-10-09 --second pass2-modern --originals "$S/originals" --save "$S/result.json"
```

Add the other four originals to `$S/originals` for the full set. The scorer re-stitches both programs from their saved reads, so
it costs nothing in API calls and takes a few minutes per file.

## How to read the result

The last two lines of the output are what matter:

* `wrong among confirmed` should be **0** (or at most 1 in 1,000). Confirmed lines are the ones both passes read alike; this
  number says whether agreement can be trusted without review. On the legacy test files it was 0 of 11,598.
* `holding N of the combined text's wrong lines`, against `wrong and unflagged`: the flagged conflicts should hold at least 95%
  of the combined text's wrong lines. This says whether review of the flagged lines is enough.
* `combined` against `first`: how many fewer wrong lines the combination leaves. Gaps one pass skipped and screens stitched twice
  in one pass should drop out; wrong dash characters and other errors both passes make will not.

If confirmed lines are reliable and the flagged conflicts hold nearly every remaining wrong line, a second pass of risky files is
worth building into the workflow (a prompt after the first capture, or a rule for files above a size). If the unflagged wrong
lines are many, the errors are the kind both passes share and a second pass will not find them.
