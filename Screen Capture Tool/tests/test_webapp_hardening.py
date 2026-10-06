"""Regression tests for the web UI hardening pass (CSRF/Host, side-effect-free GETs,
path traversal, races, key handling, temp cleanup). Offline."""
import json
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from webapp import reports, server  # noqa: E402
from webapp.session import SessionManager  # noqa: E402

STATIC = Path(server.STATIC)


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    rep, pend = tmp_path / "reports", tmp_path / "reports" / "pending"
    pend.mkdir(parents=True)
    monkeypatch.setattr(server, "REPORTS", rep)
    monkeypatch.setattr(server, "PENDING", pend)
    return rep, pend


@pytest.fixture()
def client():
    return TestClient(server.app)


# ── 1. Host / Origin / token ────────────────────────────────────────────────
def test_unknown_host_is_rejected(client):
    assert client.get("/api/reports", headers={"host": "evil.example"}).status_code == 400


def test_loopback_hosts_are_served(client):
    for host in ("127.0.0.1:8000", "localhost:8000", "testserver"):
        assert client.get("/api/key/status", headers={"host": host}).status_code == 200


def test_cross_origin_post_is_blocked(client):
    r = client.post("/api/session/stop", headers={"origin": "http://evil.example",
                                                  "x-codesnap-token": server.CSRF_TOKEN})
    assert r.status_code == 403
    r = client.post("/api/session/stop", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert client.post("/api/session/stop", headers={"origin": "null"}).status_code == 403


def test_browser_post_needs_token_but_same_origin_with_token_works(client):
    same = {"origin": "http://testserver"}
    assert client.post("/api/session/stop", headers=same).status_code == 403
    assert client.post("/api/session/stop", headers={**same, "x-codesnap-token": "wrong"}).status_code == 403
    ok = client.post("/api/session/stop", headers={**same, "x-codesnap-token": server.CSRF_TOKEN})
    assert ok.status_code == 200


def test_token_always_required_when_strict(client, monkeypatch):
    monkeypatch.setattr(server, "_REQUIRE_TOKEN_ALWAYS", True)
    assert client.post("/api/session/stop").status_code == 403
    assert client.post("/api/session/stop", headers={"x-codesnap-token": server.CSRF_TOKEN}).status_code == 200


def test_index_embeds_token_and_frontend_sends_it(client):
    html = client.get("/").text
    assert server.CSRF_TOKEN in html and "__CODESNAP_TOKEN__" not in html
    js = (STATIC / "app.js").read_text()
    assert "X-CodeSnap-Token" in js and 'name="codesnap-token"' in (STATIC / "index.html").read_text()


def test_bound_host_can_be_allowed(client):
    server.allow_host("192.0.2.7")
    try:
        assert client.get("/api/key/status", headers={"host": "192.0.2.7:9000"}).status_code == 200
    finally:
        server._ALLOWED_HOSTS.discard("192.0.2.7")


# ── 2. GETs have no side effects ────────────────────────────────────────────
def _stage(pend, name="report_1", code_file="a.py"):
    (pend / f"{name}.json").write_text(json.dumps({"code_file": code_file, "code": "x=1", "language": "Python"}))
    if code_file:
        (pend / code_file).write_text("x=1")


def test_pending_get_does_not_move_files_post_promotes(dirs, client):
    rep, pend = dirs
    _stage(pend)
    r = client.get("/api/pending/download/report_1")
    assert r.status_code == 200 and (pend / "report_1.json").exists() and not (rep / "report_1.json").exists()
    r = client.post("/api/pending/download/report_1")
    assert r.status_code == 200 and (rep / "report_1.json").exists() and (rep / "a.py").exists()
    assert not (pend / "report_1.json").exists()


def test_report_get_never_starts_analysis(monkeypatch, tmp_path):
    from core import deepdive, report as rep
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    started = []
    monkeypatch.setattr(server, "_deep_start", lambda slug, ids=None: started.append(slug) or {"running": True})
    monkeypatch.setattr(server, "api_key_status", lambda: {"has_key": True})
    monkeypatch.setattr(rep, "waiting", lambda store: 0)
    monkeypatch.setattr(deepdive, "pending", lambda store: [{"name": "x"}])
    c = TestClient(server.app)
    slug = c.post("/api/programs", json={"name": "Hardening"}).json()["program"]["slug"]
    r = c.get(f"/api/programs/{slug}/report.html")
    assert r.status_code == 409 and started == []
    assert c.post(f"/api/programs/{slug}/report/prepare").json()["started"] is True
    assert started == [slug]


# ── 3. Path traversal via code_file ─────────────────────────────────────────
def test_pending_promote_rejects_traversing_code_file(dirs, client):
    rep, pend = dirs
    secret = rep.parent / "secret.txt"
    secret.write_text("top secret")
    _stage(pend, "report_2", code_file="")
    (pend / "report_2.json").write_text(json.dumps({"code_file": "../../secret.txt"}))
    assert client.post("/api/pending/download/report_2").status_code == 400
    assert client.get("/api/pending/download/report_2").status_code == 400
    assert secret.exists() and (pend / "report_2.json").exists()


def test_plain_filename_helpers(tmp_path):
    for bad in ("../x", "a/b", "a\\b", ".hidden", "..", "", " x", "x\0y", None, 5):
        assert server._plain_filename(bad) is None
    assert server._plain_filename("ok.py") == "ok.py"
    assert server._file_in(tmp_path, "../escape") is None
    assert server._file_in(tmp_path, "fine.py") == (tmp_path / "fine.py").resolve()


def test_project_analyze_does_not_delete_outside_reports(dirs, client, monkeypatch):
    rep, pend = dirs
    victim = rep.parent / "victim.txt"
    victim.write_text("keep me")
    for n, code_file in (("report_a", "../../victim.txt"), ("report_b", "b.py")):
        (pend / f"{n}.json").write_text(json.dumps({"code": "x = 1", "code_file": code_file, "language": "Python", "extension": "py"}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(server, "analyze_project", lambda c, files: {"project_name": "P", "overview": "o"})
    monkeypatch.setattr("core.usage.UsageTracker.wrap", lambda self, c: c)
    r = client.post("/api/project/analyze", json={"items": [{"report": "report_a"}, {"report": "report_b"}]})
    assert r.status_code == 200
    assert victim.exists()


def test_project_analyze_reports_save_failure_as_warning(dirs, client, monkeypatch):
    rep, pend = dirs
    for n in ("report_a", "report_b"):
        (pend / f"{n}.json").write_text(json.dumps({"code": "x = 1", "code_file": f"{n}.py", "language": "Python", "extension": "py"}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(server, "analyze_project", lambda c, files: {"project_name": "P"})
    monkeypatch.setattr("core.usage.UsageTracker.wrap", lambda self, c: c)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(server, "save_report_bundle", boom)
    r = client.post("/api/project/analyze", json={"items": [{"report": "report_a"}, {"report": "report_b"}]})
    body = r.json()
    assert r.status_code == 200 and body["warnings"] and "disk full" in " ".join(body["warnings"])


# ── 4/5. Front end ──────────────────────────────────────────────────────────
def test_frontend_security_settings():
    js = (STATIC / "app.js").read_text()
    assert 'securityLevel: "strict"' in js and '"loose"' not in js
    assert "onclick=\"download" not in js
    assert '.replace(/"/g, "&quot;")' in js and "&#39;" in js
    assert "/api/key?value=" not in js


def test_escape_html_escapes_quotes():
    js = (STATIC / "app.js").read_text()
    fn = "function escapeHtml(" + js.split("function escapeHtml(", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = fn + 'process.stdout.write(escapeHtml(`<a href="x" onclick=\'y\'>&`));'
    try:
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        pytest.skip("node not installed")
    assert out == "&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;"


# ── 6. Races ────────────────────────────────────────────────────────────────
def test_deep_start_registers_one_job_under_concurrency(monkeypatch, tmp_path):
    from core import deepdive
    monkeypatch.setattr(server, "_program_client", lambda slug: object())

    class Store:
        info = {"slug": "s"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(server, "_open_program", lambda slug: Store())
    monkeypatch.setattr(deepdive, "pending", lambda store: [1])
    release, runs = threading.Event(), []

    def run(*a, **k):
        runs.append(1)
        release.wait(5)
        return {"errors": []}
    monkeypatch.setattr(deepdive, "run", run)
    import core.model as model
    monkeypatch.setattr(model.ProgramStore, "open", staticmethod(lambda slug: Store()))
    server._DEEP.pop("race", None)
    jobs = []
    threads = [threading.Thread(target=lambda: jobs.append(server._deep_start("race"))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    release.set()
    assert len({id(j) for j in jobs}) == 1
    server._DEEP.pop("race", None)


class _FakePopen:
    def __init__(self, *a, **k):
        self.terminated, self.pid = False, 1234
    def poll(self): return None if not self.terminated else 0
    def terminate(self): self.terminated = True


def test_session_start_is_serialised(monkeypatch):
    spawned = []
    monkeypatch.setattr("webapp.session.subprocess.Popen", lambda *a, **k: spawned.append(_FakePopen()) or spawned[-1])
    monkeypatch.setattr(SessionManager, "configure", lambda self, *a, **k: {})
    import core.status as status
    monkeypatch.setattr(status, "clear", lambda: None)
    monkeypatch.setattr(status, "publish", lambda *a, **k: None)
    mgr = SessionManager()
    threads = [threading.Thread(target=mgr.start) for _ in range(6)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert len(spawned) == 1


# ── 11. Stop terminates the pending worker too ──────────────────────────────
def test_stop_terminates_pending_worker(monkeypatch):
    mgr = SessionManager()
    mgr._pending = _FakePopen()
    assert mgr.stop() is True and mgr._pending.terminated
    assert mgr.stop() is False


# ── 7. scan_reports robustness + cache ──────────────────────────────────────
def test_scan_reports_survives_files_vanishing(tmp_path, monkeypatch):
    (tmp_path / "report_1.json").write_text(json.dumps({"code": "a", "code_file": "a.py"}))
    (tmp_path / "notes.md").write_text("hi")
    real_stat = Path.stat

    def flaky(self, *a, **k):
        if self.name == "notes.md":
            raise FileNotFoundError(self)
        return real_stat(self, *a, **k)
    monkeypatch.setattr(Path, "stat", flaky)
    out = reports.scan_reports(tmp_path)
    assert [r["name"] for r in out] == ["report_1"]


def test_scan_reports_caches_by_mtime_and_returns_copies(tmp_path, monkeypatch):
    p = tmp_path / "report_1.json"
    p.write_text(json.dumps({"code": "a"}))
    reads = []
    orig = reports._read_retry
    monkeypatch.setattr(reports, "_read_retry", lambda path, tries=8: reads.append(path) or orig(path, tries))
    first = reports.scan_reports(tmp_path)
    first[0]["code"] = "mutated"
    second = reports.scan_reports(tmp_path)
    assert second[0]["code"] == "a" and len(reads) == 1
    p.write_text(json.dumps({"code": "bb"}))
    assert reports.scan_reports(tmp_path)[0]["code"] == "bb"


# ── 8. API key handling ─────────────────────────────────────────────────────
def test_key_accepts_body_and_writes_private_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key = "sk-ant-" + "x" * 30
    r = client.post("/api/key", json={"value": key})
    assert r.json()["ok"] is True
    env = tmp_path / ".codesnap" / ".env"
    assert key in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/api/key", json={"value": "nope"}).status_code == 400


def test_run_py_writes_env_privately():
    assert "0o600" in Path(server.PROJECT / "run.py").read_text()


# ── 9. Temp dirs are cleaned up ─────────────────────────────────────────────
def test_docx_download_removes_its_temp_dir(dirs, client, monkeypatch):
    rep, pend = dirs
    _stage(pend, "report_3", "c.py")
    made = []
    real = server.tempfile.mkdtemp
    monkeypatch.setattr(server.tempfile, "mkdtemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    import core.outputs as outputs
    monkeypatch.setattr(outputs, "report_docx", lambda rep_, path, images=None: Path(path).write_bytes(b"docx"))
    r = client.get("/api/report/docx/report_3")
    assert r.status_code == 200 and r.content == b"docx"
    r = client.post("/api/report/docx", json={"name": "report_3", "images": []})
    assert r.status_code == 200
    assert made and not any(Path(d).exists() for d in made)
