"""Live run of the staged pipeline (Haiku draft, then Sonnet grounded final) on a COPY of a saved program.
Your saved program is not touched. Use a small program first; cost is printed at the end.

Run:  cd ~/codesnap && source ~/sct-venv/bin/activate && \
      CODESNAP_BATCH=1 CODESNAP_PIPELINE=staged PYTHONPATH=src python tests/live/staged_run.py live-demo-09-20
Optional second argument: programs folder (default ~/CodeSnap/programs).
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import anthropic

from core import analysis, deepdive, pipeline
from core.model import ProgramStore
from core.usage import UsageTracker, summarize

analysis.load_env()
os.environ.setdefault("CODESNAP_BATCH", "1")
os.environ.setdefault("CODESNAP_PIPELINE", "staged")
os.environ.setdefault("CODESNAP_BATCH_WINDOW", "5")
os.environ.setdefault("CODESNAP_BATCH_POLL", "15")
os.environ["CODESNAP_BATCH_JOURNAL"] = str(Path(tempfile.mkdtemp()) / "journal.json")

slug = sys.argv[1]
source = Path(sys.argv[2] if len(sys.argv) > 2 else "~/CodeSnap/programs").expanduser() / slug
work = Path(tempfile.mkdtemp())
shutil.copytree(source, work / slug)
print("working on a copy in", work)

client = UsageTracker().wrap(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
began = time.time()
with ProgramStore.open(slug, root=work) as store:
    store.set_meta("deepdive", {})
    store.set_meta("deepdive_program", {})
    files = [a["name"] for a in deepdive.pending(store)]
    print("files to analyse:", files)
    res = pipeline.run_staged(store, client, progress=lambda d, t: print(f"  progress {d}/{t}"))
    dd = store.get_meta("deepdive") or {}
    draft = store.get_meta("deepdive_draft") or {}
    print("\nstage flag:", store.get_meta("analysis_stage"), "| complete:", res["complete"])
    print("errors:", res["errors"] or "none")
    for a in store.artifacts():
        k = str(a["id"])
        if k in dd:
            print(f"  {a['name']}: draft facts {len((draft.get(k) or {}).get('facts') or [])} -> final facts {len(dd[k].get('facts') or [])}"
                  f" (stage {dd[k].get('stage')})")
    from core import report_review
    rr = (store.get_meta("report_review") or {}).get("verdicts") or {}
    cnt = {}
    for v in rr.values():
        cnt[v["verdict"]] = cnt.get(v["verdict"], 0) + 1
    print("report re-read:", cnt or "none", "|", report_review.summary_line(store) or "no summary")
    print("rescan requests:", [r["name"] for r in res["rescan"]] or "none")
    out = Path(store.exports_dir) / "report"
    print("reports:", sorted(p.name for p in out.glob("*.docx")))

records = client.tracker.take(everything=True)
s = summarize(records)
print(f"\nelapsed {(time.time() - began) / 60:.1f} min | calls {s['calls']} | cost ${s['cost']:.2f} (batch discount already applied)")
for step, v in sorted(s["by_step"].items(), key=lambda kv: -kv[1]["cost"]):
    print(f"  {step:20s} calls {v['calls']:3d}  ${v['cost']:.3f}")
by_model = {}
for r in records:
    by_model[r["model"]] = by_model.get(r["model"], 0) + 1
print("calls by model:", by_model)
print("\nChecks: draft file ends in _DRAFT.docx; final report has no DRAFT banner; Haiku appears only in draft + review.")
