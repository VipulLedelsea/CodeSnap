"""Live check of the Batch API wrapper. Costs well under one cent. Takes a few minutes (batches are not instant).

Run:  cd ~/codesnap && source ~/sct-venv/bin/activate && CODESNAP_BATCH=1 PYTHONPATH=src python tests/live/batch_smoke.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import anthropic

from core import analysis, batching
from core.usage import UsageTracker

analysis.load_env()
os.environ["CODESNAP_BATCH"] = "1"
os.environ["CODESNAP_BATCH_WINDOW"] = "3"
os.environ["CODESNAP_BATCH_POLL"] = "10"
os.environ["CODESNAP_BATCH_JOURNAL"] = str(Path(tempfile.mkdtemp()) / "journal.json")
MODEL = "claude-haiku-4-5"

client = UsageTracker().wrap(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
tracker = client.tracker
words = ["maple", "granite", "harbor", "violet"]
answers, began = {}, time.time()


def ask(word):
    msg = client.messages.create(model=MODEL, max_tokens=20, system="Reply with the single word you are given, nothing else.",
                                 messages=[{"role": "user", "content": word}])
    answers[word] = msg.content[0].text.strip().lower()


threads = [threading.Thread(target=ask, args=(w,)) for w in words]
[t.start() for t in threads]
[t.join() for t in threads]
print(f"finished in {time.time() - began:.0f}s")
bad = {w: a for w, a in answers.items() if w not in a}
records = tracker.take(everything=True)
print("answers:", answers)
print("calls:", len(records), "cost: $%.5f" % sum(r["cost"] or 0 for r in records), "(already halved for batch)")
journal = batching.Journal().get
print("journal entries left (should be none):", len(batching.Journal()._load()))
if bad or len(answers) != len(words):
    print("FAIL: answers mixed up or missing", bad)
    sys.exit(1)
print("PASS: every caller got its own answer")
