"""Cross-file reference checks, the unrated-defect selection, and the scanner fixes found by scoring the Permit Portal report."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core import crossrefs  # noqa: E402
from core.report import codefindings as CFM  # noqa: E402
from core.security import rules  # noqa: E402
from core.uireview import page  # noqa: E402


class Fake:
    def __init__(self, files):
        self._a = [{"id": i, "name": n, "transcription": t} for i, (n, t) in enumerate(files.items(), 1)]

    def artifacts(self):
        return self._a


FILES = {
    "auth.py": 'ROLES = ("resident", "inspect", "admin")\nSECRET = "permits-2019"\ndef has_role(u, r):\n    return r in u["role"]\n',
    "app.py": 'import auth\nSECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")\n'
              'def f(user):\n    if not auth.has_role(user, "inspector"):\n        return 403\n',
    "deploy.sh": 'export SECRET_KEY=dev-secret-change-me\nDB_PASSWORD="Sp1ngfield!2021"\n',
    "config.yaml": "db:\n  password: Sp1ngfield!2021\nlimits:\n  max_megabytes: 500\n",
    "scheduler.py": 'def b(db):\n    db.execute("SELECT slot FROM bookings WHERE id = ?", (1,))\n    db.execute("INSERT INTO permits (a) VALUES (?)", (1,))\n',
    "schema.sql": "CREATE TABLE permits (id INTEGER);\n",
    "index.html": '<link rel="stylesheet" href="/static/site.css">\n<script src="/static/permits.js"></script>\n',
    "permits.js": "function x() {}\n",
}


def titles(files=FILES):
    return [o["title"] for o in crossrefs.conflicts(Fake(files))]


def test_a_role_asked_for_that_the_list_does_not_hold_is_reported():
    t = titles()
    assert any("role 'inspector'" in x for x in t)
    assert not any("role 'inspect'" in x for x in t)


def test_a_table_used_but_never_created_is_reported_and_a_created_one_is_not():
    t = titles()
    assert any("'bookings'" in x for x in t)
    assert not any("'permits'" in x for x in t)


def test_the_same_secret_in_several_files_is_reported_once_per_value():
    obs = [o for o in crossrefs.conflicts(Fake(FILES)) if o["source"] == "repeated secrets"]
    assert sorted(len(o["files"]) for o in obs) == [2, 2]
    assert any("Sp1ngfield" in o["statement"] for o in obs)


def test_a_missing_asset_and_an_unread_settings_file_are_reported_and_a_provided_asset_is_not():
    t = titles()
    assert any("site.css" in x for x in t)
    assert not any("permits.js" in x for x in t)
    assert any("config.yaml is not read" in x for x in t)


def test_nothing_is_reported_when_the_files_agree():
    ok = {"auth.py": 'ROLES = ("a", "b")\n', "app.py": 'auth.has_role(u, "a")\n', "schema.sql": "CREATE TABLE t (id INT);\n",
          "q.py": 'db.execute("SELECT id FROM t")\n'}
    assert titles(ok) == []


def test_a_defect_the_model_left_unrated_is_selected_and_rated_medium():
    arts = [{"id": 1, "name": "notifications.py"}]
    facts = {1: [{"statement": "send_sms() loops forever (while True) retrying every 5 seconds, with no maximum retry count, blocking the caller indefinitely.",
                  "category": "control_flow", "severity": None, "basis": "observed"},
                 {"statement": "STATUS_TEXT maps six permit statuses to fixed notification text.", "category": "business_rule", "severity": None}]}
    picked = CFM.select(None, arts, facts)
    assert [p["severity"] for p in picked] == ["medium"] and "loops forever" in picked[0]["text"]


def test_two_findings_about_different_constants_are_not_one_finding():
    a = "SMTP username and password are embedded as plaintext module-level constants (SMTP_USER, SMTP_PASSWORD)."
    b = "SMS API key is embedded as a plaintext module-level constant (SMS_KEY)."
    assert not CFM._same(a, b)


def test_an_inner_html_write_with_values_is_high_and_a_plain_clear_is_low():
    hi = rules.scan_text("el.innerHTML = '<li>' + row.description + '</li>';\n", "a.js", "JavaScript")
    lo = rules.scan_text("el.innerHTML = '';\n", "b.js", "JavaScript")
    assert [f["severity"] for f in hi if f["rule"] == "SEC-XSS"] == ["high"]
    assert [f["severity"] for f in lo if f["rule"] == "SEC-XSS"] == ["low"]


def test_a_python_like_pattern_is_not_sql_injection_but_a_joined_query_is():
    safe = rules.scan_text('rows = db.execute("SELECT id FROM users WHERE role LIKE \'%reviewer%\'").fetchall()\n', "r.py", "Python")
    bad = rules.scan_text('sql = "SELECT * FROM p WHERE d LIKE \'%" + term + "%\'"\nrows = db.execute(sql)\n', "a.py", "Python")
    assert not any(f["rule"] == "SEC-SQLI" for f in safe)
    assert any(f["rule"] == "SEC-SQLI" and f["line"] == 1 for f in bad)


def test_a_form_that_a_script_submits_is_not_a_get_form():
    html = ('<form onsubmit="login(this.p.value); return false;"><input name="password" type="password"></form>\n'
            '<form><input name="password" type="password"></form>\n')
    hits = [f for f in page.check_page(html) if f["rule"] == "UIS-GET"]
    assert len(hits) == 1 and hits[0]["line"] == 2


def test_a_finding_read_from_the_source_by_a_rule_is_marked_checked_and_a_model_one_is_not():
    obs = [{"title": "The same secret is written into a.py and b.py", "statement": "x", "files": ["a.py", "b.py"], "source": "repeated secrets"},
           {"title": "Two files never agree", "statement": "y", "files": ["a.py", "b.py"]}]
    risks = CFM.program_items(obs)["risks"]
    assert [r["checked"] for r in risks] == [True, False]


def test_a_sentence_that_only_describes_the_code_is_not_a_finding_but_one_that_says_something_is_wrong_is():
    arts = [{"id": 1, "name": "a.py"}]
    plain = {"statement": "apply_discount() supports senior, veteran and nonprofit kinds and returns the discounted total.", "category": "business_rule", "severity": "medium"}
    wrong = {"statement": "next_business_day skips only Sunday because weekday() > 5 is true for 6 alone, so Saturday is booked despite the apparent intent.",
             "category": "business_rule", "severity": None}
    picked = CFM.select(None, arts, {1: [plain, wrong]})
    assert [p["text"][:17] for p in picked] == ["next_business_day"]


def test_the_review_prompt_asks_for_the_probes_and_forbids_invention():
    from core import deepdive
    s = deepdive.DEEP_SYSTEM
    for phrase in ("Reachability", "Boundaries and limits", "Check then act", "Output encoding", "work one concrete input through the lines",
                   "Never invent names, values, systems", "contradict each other"):
        assert phrase in s
    assert deepdive.PROMPT_VERSION.startswith("deepdive-v6")
