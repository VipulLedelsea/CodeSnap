"""Pick up staged runs that were interrupted (laptop closed, app quit). Batches keep running at Anthropic; this
re-attaches to them through the journal and carries on to the final report.

  python src/resume.py            # every interrupted program
  python src/resume.py my-slug    # one program
"""
import os
import sys
import threading

import anthropic

from core import analysis, pipeline
from core.model import ProgramStore
from core.usage import program_client


def resume(slug, progress=None):
    analysis.load_env()
    client = program_client(slug, anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
    with ProgramStore.open(slug) as store:
        return pipeline.run_staged(store, client, progress=progress)


def resume_all(slugs=None):
    done = {}
    for slug in slugs or pipeline.interrupted():
        try:
            done[slug] = resume(slug)
        except Exception as exc:  # noqa: BLE001
            done[slug] = {"errors": [f"{type(exc).__name__}: {exc}"]}
    return done


def resume_in_background():
    if os.environ.get("CODESNAP_PIPELINE", "").lower() != "staged":
        return None
    t = threading.Thread(target=resume_all, daemon=True, name="codesnap-resume")
    t.start()
    return t


if __name__ == "__main__":
    os.environ.setdefault("CODESNAP_BATCH", "1")
    os.environ.setdefault("CODESNAP_PIPELINE", "staged")
    found = sys.argv[1:] or pipeline.interrupted()
    print("resuming:", found or "nothing interrupted")
    for slug, res in resume_all(found).items():
        print(slug, "->", "complete" if res.get("complete") else "not complete", res.get("errors") or "")
