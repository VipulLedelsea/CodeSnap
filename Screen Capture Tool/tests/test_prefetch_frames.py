import sys, threading, time
from pathlib import Path
sys.path.insert(0, "src")
from core import analysis


def test_prefetch_reads_frames_together(monkeypatch, tmp_path):
    live, peak, lock = [0], [0], threading.Lock()

    def fake(client, path, cache_dir):
        with lock:
            live[0] += 1; peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        if path.name == "bad.png":
            raise RuntimeError("boom")
    monkeypatch.setattr(analysis, "extract_to_cache", fake)
    monkeypatch.setenv("CODESNAP_BATCH", "1")
    jobs = [(Path(f"{i}.png"), tmp_path) for i in range(10)] + [(Path("bad.png"), tmp_path)]
    analysis.prefetch_frames(None, jobs)   # a failing frame must not stop the rest
    assert peak[0] >= 8
