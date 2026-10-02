"""M11 robustness: hostile inputs, transient I/O, partial captures, budget guard, pipeline health, scale."""
import errno
import random
import time
from pathlib import Path

import pytest

from core import robust
from core.model.completeness import check as completeness
from core.model.ingest import _parse_deterministic
from core.security.rules import scan_text
from core.assess.scores import text_metrics
from core import langpacks

SAMPLES = Path(__file__).resolve().parent / "samples"
ALL = sorted(p for p in SAMPLES.rglob("*") if p.is_file() and p.suffix not in (".png", ".md", ".pyc")
             and "broken" not in p.name and p.name != "make_samples.py")


def _variants(text):
    lines = text.splitlines()
    rnd = random.Random(len(text))
    yield "truncated", "\n".join(lines[: max(1, int(len(lines) * 0.6))])
    yield "garbage", "".join(rnd.choice("{}()[]<>'\"\\;:*#%&$@!\t |-=+.,\n") for _ in range(3000))
    yield "long_line", (lines[0] if lines else "x") + " " + "A" * 50000
    yield "open_quote", '"' + "a" * 20000
    yield "nul_crlf", text.replace("\n", "\x00\r\n", 5)
    yield "empty", ""


@pytest.mark.parametrize("path", ALL, ids=[p.name for p in ALL])
def test_hostile_inputs_never_crash_or_hang(path):
    text = path.read_text(errors="replace")
    for label, v in _variants(text):
        began = time.monotonic()
        _parse_deterministic(v, {"name": path.name, "language": "", "artifact_type": "code"})
        scan_text(v, path.name)
        text_metrics(v, path.name)
        langpacks.check(v, path.name)
        completeness(v, path.name)
        assert time.monotonic() - began < 5, (path.name, label)


def test_retry_rides_out_icloud_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(robust, "DELAY", 0.001)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError(35, "Resource deadlock avoided")
        return "ok"

    assert robust.retry(flaky, delay=0.001) == "ok" and calls["n"] == 3
    with pytest.raises(FileNotFoundError):
        robust.retry(lambda: Path(tmp_path / "nope").read_text(), delay=0.001)
    import sqlite3
    assert robust.transient(sqlite3.OperationalError("database is locked"))
    assert not robust.transient(OSError(errno.ENOENT, "missing"))


def test_evidence_copy_retries(tmp_path, monkeypatch):
    from core.model import ProgramStore
    real = robust.shutil.copyfile
    state = {"n": 0}

    def flaky(src, dest):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError(35, "Resource deadlock avoided")
        return real(src, dest)

    monkeypatch.setattr(robust.shutil, "copyfile", flaky)
    shot = tmp_path / "a.png"
    shot.write_bytes(b"\x89PNG fake")
    store = ProgramStore.create("Retry", root=tmp_path / "p")
    assert store.add_evidence(shot) and state["n"] == 2
    store.close()


def _truncations():
    for p in ALL:
        lines = p.read_text(errors="replace").splitlines()
        if len(lines) > 8:
            for frac in (0.4, 0.6, 0.8):
                yield p.name, "\n".join(lines[: int(len(lines) * frac)])


def test_partial_capture_detection_rate():
    false_pos = [p.name for p in ALL if completeness(p.read_text(errors="replace"), p.name)["partial"]]
    assert not false_pos, false_pos
    cases = list(_truncations())
    hits = sum(1 for n, t in cases if completeness(t, n)["partial"])
    assert hits / len(cases) >= 0.6, f"{hits}/{len(cases)}"


@pytest.mark.parametrize("name,text,reason", [
    ("Svc.cs", "namespace A {\n  public class B {\n    void C() {\n      int x = 1;\n", "unclosed"),
    ("X.java", "    }\n    return y;\n  }\n}\n", "start"),
    ("P.cbl", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
              "       01  A PIC X.\n", "PROCEDURE"),
    ("S.cbl", "".join(f"{n:06d}     DISPLAY 'X'.\n" for n in list(range(100, 1100, 100)) + list(range(9000, 9600, 100))), "sequence"),
    ("m.frm", "Sub A()\n  If x Then\n    y = 1\n", "never closed"),
    ("w.config", "<configuration>\n  <appSettings>\n    <add key=\"a\" value=\"b\"/>\n", "XML"),
    ("p.html", "<html><body><form><input name=a>\n", "never closed"),
    ("AIDX.nsp", "0010 DEFINE DATA LOCAL\n0020 1 #A (A10)\n0030 END-DEFINE\n0040 READ X BY Y\n0050 DISPLAY #A\n", "END"),
])
def test_partial_capture_reasons(name, text, reason):
    r = completeness(text, name)
    assert r["partial"] and any(reason.lower() in x.lower() for x in r["reasons"]), r


class _Msg:
    def __init__(self):
        self.usage = type("U", (), {"input_tokens": 100000, "output_tokens": 20000})()
        self.model, self.stop_reason, self.content = "claude-opus-5-5", "end_turn", []


class _Fake:
    class messages:
        calls = 0

        @classmethod
        def create(cls, **kw):
            cls.calls += 1
            return _Msg()


def test_budget_guard_stops_api_calls():
    from core.usage import Budget, BudgetExceeded, UsageTracker
    tracker = UsageTracker()
    client = tracker.wrap(_Fake())
    warned = []
    tracker.budget = Budget(1.0, spent=0.0, on_warn=lambda t, l: warned.append(t))
    with pytest.raises(BudgetExceeded):
        for _ in range(20):
            client.messages.create(model="claude-opus-5-5", system="x", messages=[])
    assert warned and tracker.total_cost >= 1.0 and _Fake.messages.calls < 20


def _store_with(tmp_path, files, client=None):
    from core.model import ProgramStore, ingest_capture
    from test_linker import NoApi
    store = ProgramStore.create("Health", root=tmp_path)
    for name, code, errors in files:
        ingest_capture(store, client or NoApi(), [], {"is_code": True, "code": code, "extension": name.rsplit(".", 1)[-1],
                                                      "language": "", "errors": errors}, name=name)
    return store


def test_pipeline_health_and_confidence(tmp_path):
    pytest.importorskip("tree_sitter")
    from core.assess import run_assessment
    from core.model.health import pipeline_health
    from core.report import html_report
    lp = SAMPLES / "langpacks"
    files = [(n, (lp / n).read_text(), "None") for n in ("AIDPOST.rpgle", "AIDCALC.frm", "aid_pkg.pkb", "AIDNIGHT.clle",
                                                          "aid_forecast.sas", "aidlookup.asp")]
    files.append(("Cut.cs", "namespace A {\n public class Cut {\n  public void M() {\n   var x = 1;\n", "Cut.cs(4,14): error CS1513: } expected"))
    files.append(("notes.xyz", "random words that no parser understands", "None"))
    store = _store_with(tmp_path, files)
    h = pipeline_health(store)
    assert [f["name"] for f in h["failed"]] == ["notes.xyz"]
    assert "Cut.cs" in [p["name"] for p in h["partial"]] and "Cut.cs" in [p["name"] for p in h["invalid"]]
    assert h["status"] == "errors" and h["api"]["failures"] >= 1
    a = run_assessment(store)
    assert a["confidence"]["level"] != "high"
    assert any("partially captured" in n for n in a["confidence"]["notes"])
    html = html_report(store, rescan=False)
    assert "Cut.cs" in html and ("Source validation:" in html or "Open source validation" in html)
    store.close()


def test_scan_survives_a_crashing_rule(tmp_path, monkeypatch):
    from core.security import scan as scan_mod
    from core.model.health import pipeline_health
    store = _store_with(tmp_path, [("AIDCALC.frm", (SAMPLES / "langpacks" / "AIDCALC.frm").read_text(), "None")])

    def boom(*a, **k):
        raise RuntimeError("rule exploded")

    monkeypatch.setattr(scan_mod, "scan_text", boom)
    scan_mod.run_scan(store)
    errs = pipeline_health(store)["analysis_errors"]
    assert errs and "rule exploded" in errs[0]["error"]
    store.close()


def test_budget_api_and_capture_refusal(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setattr(server._session, "start", lambda **kw: True)
    monkeypatch.setattr(server._session, "running", lambda: True)
    c = TestClient(server.app)
    slug = c.post("/api/programs", json={"name": "Budgeted"}).json()["program"]["slug"]
    assert c.post(f"/api/programs/{slug}/budget", json={"budget_usd": -1}).status_code == 400
    assert c.post(f"/api/programs/{slug}/budget", json={"budget_usd": 0.5}).json()["limit"] == 0.5
    from core.model import ProgramStore
    with ProgramStore.open(slug) as store:
        store.log_run("extract", model="claude-opus-5-5", input_tokens=100000, output_tokens=10000, cost=0.6)
    h = c.get(f"/api/programs/{slug}/health").json()
    assert h["budget"]["spent"] == 0.6 and h["budget"]["remaining"] < 0
    r = c.post(f"/api/session/start?program={slug}")
    assert r.status_code == 402 and "budget" in r.json()["error"]
    assert c.post(f"/api/programs/{slug}/budget", json={"budget_usd": 0}).json()["limit"] is None
    assert c.post(f"/api/session/start?program={slug}").status_code == 200


def test_large_mixed_program_runs_end_to_end(tmp_path):
    pytest.importorskip("tree_sitter")
    from core.assess import run_assessment
    from core.diagrams import all_diagrams, vsdx
    from core.model import ProgramStore, ingest_capture
    from core.report import package
    from test_linker import NoApi
    store = ProgramStore.create("Large", root=tmp_path)
    began = time.monotonic()
    n = 0
    for k in range(2):
        for p in ALL:
            if p.suffix == ".py" and p.parent == SAMPLES:
                continue
            text = p.read_text(errors="replace")
            name = p.name if k == 0 else f"{p.stem}_copy{p.suffix}"
            if k == 1 and n % 5 == 0:
                text = "\n".join(text.splitlines()[: max(3, len(text.splitlines()) // 2)])
            rep = {"is_code": True, "code": text, "extension": p.suffix[1:].lower(), "language": "", "errors": "None"}
            if p.suffix == ".screen":
                rep["artifact_type"] = "ui_screen"
            ingest_capture(store, NoApi(), [], rep, name=name)
            n += 1
    a = run_assessment(store)
    ds = all_diagrams(store)
    assert vsdx(ds)[:2] == b"PK"
    pk = package(store, rescan=False)
    assert pk["zip"][:2] == b"PK" and a["verdict"] and len(ds) > 50
    assert a["health"]["partial"], "truncated copies should be flagged"
    assert time.monotonic() - began < 240
    store.close()
