from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core.model import ProgramStore
from core.uireview import run_ui_review
from core.uireview.page import check_page, contrast
from core.uireview.site import scan_site

from test_linker import COBOL, LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"
HOST = "https://aid.example.mn.gov"
PAGES = {
    f"{HOST}/": ("<html><head><title>Aid</title><script src='/js/jquery-1.8.3.min.js'></script></head><body>"
                 "<a href='/Login.aspx'>Login</a><a href='/Reports.aspx'>here</a><a href='/private/x.aspx'>p</a></body></html>",
                 [("server", "Microsoft-IIS/7.5"), ("x-aspnet-version", "4.0.30319"),
                  ("set-cookie", "ASP.NET_SessionId=abc; path=/"), ("content-type", "text/html")]),
    f"{HOST}/Login.aspx": ("<html lang=en><head><title>Login</title></head><body><h1>Sign in</h1><form method=get action=/auth>"
                           "<label for=u>User</label><input id=u name=userid maxlength=8><input name=password type=text>"
                           "</form></body></html>", [("content-type", "text/html")]),
    f"{HOST}/Reports.aspx": ("<html><body><img src=chart.png><div onclick='go()'>Open</div></body></html>", [("content-type", "text/html")]),
    f"{HOST}/robots.txt": ("User-agent: *\nDisallow: /private/", [("content-type", "text/plain")]),
}


def fake(url):
    if url.startswith("http://"):
        return {"url": url, "status": 200, "headers": [("content-type", "text/html")], "body": "<html></html>", "chain": [], "tls": None}
    body, h = PAGES.get(url, ("", []))
    return {"url": url, "status": 200 if body else 404, "headers": h, "body": body, "chain": [(url, 200)],
            "tls": {"version": "TLSv1.2", "cert_ok": True}}


def rules(text):
    return {f["rule"] for f in check_page(text)}


def test_contrast():
    assert contrast("#000", "#fff") == 21.0 and contrast("#999999", "white") < 4.5 and contrast("bogus", "#fff") is None


def test_accessibility_rules():
    bad = ("<html><head></head><body><img src=a.png><input id=x name=district><div onclick='f()'>go</div>"
           "<a href='/r'>click here</a><font color='#aaaaaa'>low</font><meta name=viewport content='user-scalable=no'>"
           "<table><tr><td>a</td></tr><tr><td>b</td></tr><tr><td>c</td></tr></table></body></html>")
    got = rules(bad)
    assert {"ACC-ALT", "ACC-LABEL", "ACC-KEYBOARD", "ACC-LINK", "ACC-TITLE", "ACC-LANG", "ACC-ZOOM", "ACC-DEPRECATED",
            "ACC-TABLE", "ACC-CONTRAST"} <= got
    good = ("<html lang=en><head><title>Ok</title></head><body><h1>Ok</h1><img src=a.png alt='chart'>"
            "<label for=d>District</label><input id=d name=district maxlength=6><a href='/r'>Payment history</a>"
            "<button type=submit>Look up aid</button></body></html>")
    assert rules(good) == set()


def test_ui_security_and_usability_rules():
    page = ("<html lang=en><title>t</title><h1>x</h1><form method=get action='/find'><label for=s>SSN</label>"
            "<input id=s name=ssn></form><form method=post action='http://x.gov/pay'><input type=hidden name=amount value=5>"
            "<label for=p>Pw</label><input id=p name=password><button>Delete</button></form>"
            "<a href='https://x' target=_blank>ext</a><script src='http://cdn.x/lib.js'></script></html>")
    got = rules(page)
    assert {"UIS-GET", "UIS-CSRF", "UIS-MIXED", "UIS-HIDDEN", "UIS-PWFIELD", "UIS-BLANK", "USE-CONFIRM"} <= got
    assert "UIS-CSRF" not in rules("<form method=post><input type=hidden name=__RequestVerificationToken></form>")
    assert "UIS-CSRF" not in rules('<form runat="server" method="post"></form>')


def test_comments_and_server_code_ignored():
    assert rules("<!-- <img src=a.png> --><%-- <input name=x> --%><% Response.Write(\"<img src=b>\") %>") == set()


def test_site_scan():
    r = scan_site(HOST + "/", fetcher=fake)
    got = {f["rule"] for f in r["findings"]}
    assert {"WEB-HTTPS", "WEB-HSTS", "WEB-CSP", "WEB-FRAME", "WEB-COOKIE", "WEB-DISCLOSURE", "UIS-GET", "UIS-PWFIELD",
            "ACC-ALT", "ACC-KEYBOARD"} <= got
    pages = [p["url"] for p in r["summary"]["pages"]]
    assert f"{HOST}/Login.aspx" in pages and not any("/private/" in p for p in pages)
    assert ("iis", "7.5") in r["summary"]["technologies"] and r["summary"]["libraries"]
    assert len(scan_site(HOST + "/", fetcher=fake, max_pages=1)["summary"]["pages"]) == 1


def test_site_scan_bad_cert_and_down():
    cert = scan_site("https://bad.example", fetcher=lambda u: {"url": u, "status": None, "headers": [], "body": "",
                                                              "chain": [], "tls": {"cert_ok": False, "error": "expired"},
                                                              "error": "certificate"})
    assert [f["rule"] for f in cert["findings"]] == ["WEB-CERT"]
    down = scan_site("example.org", fetcher=lambda u: {"url": u, "status": None, "headers": [], "body": "", "chain": [],
                                                       "tls": None, "error": "timeout"})
    assert down["findings"] == [] and down["summary"]["start"] == "https://example.org"


@pytest.fixture
def program(tmp_path):
    store = ProgramStore.create("UI", root=tmp_path)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])
    for f, l, e in (("DistrictAid.aspx", "ASPX", "aspx"), ("AidLookup.jsp", "JSP", "jsp")):
        add(store, f, (LEGACY / f).read_text(), l, e)
    add(store, "AIDQ.screen", (LEGACY / "ScreenAidInquiry.screen").read_text(), "UI screen", "screen", "ui_screen")
    add(store, "Lookup.html", (SEC / "Lookup.html").read_text(), "HTML", "html")
    yield store
    store.close()


def test_review_program(program):
    r = run_ui_review(program)
    got = {f["rule"] for f in program.findings()}
    assert {"ACC-LABEL", "ACC-TERMINAL", "UIB-CRASH", "UIB-OBSERVED", "UIS-GET"} <= got
    assert sum(1 for f in program.findings() if f["rule"] == "ACC-TERMINAL") == 1
    assert all(f["evidence"] and f["source"] for f in program.findings())
    assert any("vision" in f["source"] for f in program.findings() if f["rule"] == "UIB-OBSERVED")
    assert any(j["steps"][-1]["screen"] == "PaymentHistory" for j in r["flows"]["journeys"])
    assert "PaymentHistory" in r["flows"]["dead_ends"]


def test_live_findings_survive_offline_rerun_and_status_kept(program):
    run_ui_review(program, site_url=HOST + "/", fetcher=fake)
    live = [f for f in program.findings() if f["source"].startswith("live scan")]
    assert live and program.get_meta("site_scan")["final_url"] == HOST + "/"
    target = next(f for f in program.findings() if f["rule"] == "ACC-LANG")
    program.set_finding_status(target["id"], "accepted")
    run_ui_review(program)
    assert len([f for f in program.findings() if f["source"].startswith("live scan")]) == len(live)
    assert next(f for f in program.findings() if f["title"] == target["title"])["status"] == "accepted"


def test_assessment_uses_ui_and_site(program):
    from core.assess import run_assessment
    run_ui_review(program, site_url=HOST + "/", fetcher=fake)
    a = run_assessment(program)
    assert "ux" in a["scores"] and a["scores"]["ux"]["score"] < 100
    site = next(c for c in a["components"] if c["name"].startswith("Live site"))
    assert site["scores"]["security"]["score"] < 100 and site["scores"]["supportability"]["score"] < 100
    titles = {i["title"] for p in a["roadmap"]["phases"] for i in p["items"]}
    assert {"Fix accessibility (WCAG 2.1 AA)", "Harden web server configuration", "Web front end for 3270 screens"} <= titles


def test_report_and_diagram(program):
    from core.diagrams import all_diagrams
    from core.report import build, html_report
    run_ui_review(program, site_url=HOST + "/", fetcher=fake)
    ids = {d["id"] for d in all_diagrams(program)}
    assert "userflow" in ids
    r = build(program, rescan=False)
    assert any(s["id"] == "ui" for s in r["sections"])
    page = html_report(program, rescan=False)
    assert "User flow" in page and "aid.example.mn.gov" in page


def test_ui_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "UI API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "Lookup.html", (SEC / "Lookup.html").read_text(), "HTML", "html")
    r = client.post(f"/api/programs/{slug}/ui/review").json()
    assert r["ok"] and r["summary"]["accessibility"]["total"] >= 1
    d = client.get(f"/api/programs/{slug}/ui").json()
    assert d["findings"] and d["flows"] is not None and d["site"] is None
