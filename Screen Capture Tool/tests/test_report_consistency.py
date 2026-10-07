"""Whole-report checks on three different applications: a six-platform payment system (run 1), a mixed legacy sample
(SFAID) and a small modern non-financial app. Each report must be internally consistent and must only say what
applies to that application."""
import io
import re
import shutil
from pathlib import Path

import pytest

from conftest import need_fixture

docx = pytest.importorskip("docx")

from core.model import ProgramStore
from core.report import docx_bytes

from test_linker import COBOL, LEGACY, add

TESTS = Path(__file__).resolve().parent
SEC = TESTS / "samples" / "security"
RUN1 = TESTS / "fixtures" / "run1_program"
BANNED = re.compile(r"\b(CodeSnap|Claude|AI|screenshots?|scann(ed|ing)|captured?)\b")


def text_of(data: bytes):
    d = docx.Document(io.BytesIO(data))
    paras = [p.text for p in d.paragraphs]
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    return d, "\n".join(paras), "\n".join(cells)


def build(store):
    data = docx_bytes(store, rescan=True)
    d, paras, cells = text_of(data)
    xml = "\n".join("".join(t.text or "" for t in p.iter(docx.oxml.ns.qn("w:t")))
                     for p in d.element.body.iter(docx.oxml.ns.qn("w:p")))
    return {"doc": d, "paras": paras, "cells": cells, "all": paras + "\n" + cells, "xml": xml}


@pytest.fixture(scope="module")
def run1(tmp_path_factory):
    root = tmp_path_factory.mktemp("run1")
    need_fixture(RUN1)
    shutil.copytree(RUN1, root / "live-test-09-29")
    st = ProgramStore.open("live-test-09-29", root=root)
    yield build(st)
    st.close()


@pytest.fixture(scope="module")
def sfaid(tmp_path_factory):
    st = ProgramStore.create("SFAID Payments", root=tmp_path_factory.mktemp("sfaid"))
    for f, l, e in [("StudentLookup.aspx.cs", "C#", "cs"), ("StudentExport.java", "Java", "java"),
                    ("STUPAY.cbl", "COBOL", "cbl"), ("web.config", "XML", "config"), ("Lookup.html", "HTML", "html")]:
        add(st, f, (SEC / f).read_text(), l, e)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        add(st, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])
    add(st, "AIDSCHEMA.sql", (LEGACY / "AIDSCHEMA.sql").read_text(), "SQL", "sql")
    yield build(st)
    st.close()


LIB_PY = '''from flask import Flask, request
import psycopg2
app = Flask(__name__)
conn = psycopg2.connect("dbname=library user=app host=db01")
@app.route("/books")
def books():
    cur = conn.cursor()
    cur.execute("SELECT title, author FROM books WHERE title LIKE %s", ("%" + request.args.get("q", "") + "%",))
    return {"books": cur.fetchall()}
'''
LIB_SQL = '''CREATE TABLE books (id SERIAL PRIMARY KEY, title VARCHAR(200), author VARCHAR(100));
CREATE TABLE members (id SERIAL PRIMARY KEY, name VARCHAR(100), email VARCHAR(100));
CREATE TABLE loans (id SERIAL PRIMARY KEY, book_id INT REFERENCES books(id), member_id INT REFERENCES members(id));
'''


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    st = ProgramStore.create("Library Catalog", root=tmp_path_factory.mktemp("lib"))
    add(st, "catalog.py", LIB_PY, "Python", "py")
    add(st, "schema.sql", LIB_SQL, "SQL", "sql")
    add(st, "index.html", '<html><body><form action="/books"><input name="q"><button>Search</button></form></body></html>',
        "HTML", "html")
    yield build(st)
    st.close()


ALL = ["run1", "sfaid", "library"]


@pytest.fixture(params=ALL)
def report(request):
    return request.getfixturevalue(request.param)


# ── every report ───────────────────────────────────────────────────────────────────────────────────────────────

def test_one_rating_scale_and_no_placeholders(report):
    assert "out of 100" not in report["all"] and "/100" not in report["all"]
    assert not re.search(r"\[[A-Z][^\]]{1,80}\]", report["all"])
    assert not BANNED.search(report["all"])


def test_snapshot_overall_rating_matches_scorecard(report):
    snap = re.search(r"Overall health rating \(Section 6\)\n([^\n]+)", report["cells"])
    card = re.search(r"Overall health rating\n100%\n(\S+)\n", report["cells"])
    assert snap and card
    assert snap.group(1).startswith(card.group(1)) or card.group(1) == "Insufficient"


def test_security_posture_is_the_same_everywhere(report):
    words = set(re.findall(r"Security posture(?: is rated|:) (\d – \w+|Insufficient evidence|Not enough evidence)", report["paras"]))
    card = re.search(r"Security posture\n15%\n(\S+)", report["cells"]).group(1)
    assert len(words) == 1
    assert next(iter(words)).startswith(card) or card == "Insufficient" and next(iter(words)) in ("Insufficient evidence", "Not enough evidence")


def test_high_finding_count_matches_register(report):
    reg = re.findall(r"VUL-\d+-\d+\n[^\n]*\n[^\n]*\n[^\n]*\n(Critical|High|Medium|Low)", report["cells"])
    snap = re.search(r"Open critical or high vulnerabilities \(Section 8\)\n(\d+)", report["cells"])
    assert snap and int(snap.group(1)) == sum(1 for s in reg if s in ("Critical", "High"))


def test_missing_component_count_is_the_same_everywhere(report):
    counts = {int(n) for n in re.findall(r"(\d+) (?:referenced )?components? (?:referenced but )?not provided", report["all"])}
    counts |= {int(n) for n in re.findall(r"provide the (\d+) missing components", report["all"])}
    assert len(counts) <= 1


def test_highest_risk_is_the_top_of_the_register(report):
    snap = re.search(r"Highest risk score \(Section 9\)\n(\d+) of 25, \w+ \((R-\d+-\d+)", report["cells"])
    if not snap:
        return
    first = re.search(r"(R-\d+-01)\n", report["cells"])
    assert first and snap.group(2) == first.group(1)
    scores, seen = [], set()
    for rid, sc in re.findall(r"(R-\d+-\d+)\n[^\n]+\n[^\n]+\n\d\n\d\n(\d+)\n", report["cells"]):
        if rid in seen:
            break
        seen.add(rid)
        scores.append(int(sc))
    assert scores == sorted(scores, reverse=True) and scores[0] == int(snap.group(1))


def test_figures_are_numbered_in_order(report):
    nums = [int(n) for n in re.findall(r"^Figure (\d)\.", report["paras"], re.M)]
    assert nums == sorted(nums) and nums == list(range(1, len(nums) + 1))


def test_report_follows_the_template_sections_only(report):
    for h in ("1. Application summary", "2. Business context and process mapping", "3. Technical profile",
              "4. Architecture and integrations", "5. Data profile and reporting", "6. Application health and supportability",
              "7. Technical debt", "8. Security and vulnerabilities", "9. Risk and impact matrix",
              "10. Operational support and IT dependency", "11. User experience", "12. Modernization options and recommendation",
              "13. Evidence, open items and sign-off"):
        assert h in report["xml"]
    for removed in ("2.6 Business capability mapping", "3.5 Application boundary", "4.5 Deployment view", "6.3 Service requirements",
                    "6.4 Technology lifecycle", "8.7 Identity and access", "10.5 Batch operations", "10.6 Observability",
                    "12.5 Place in the application portfolio", "12.6 Future design", "12.7 Platform run costs"):
        assert removed not in report["xml"]
    assert report["xml"].count("1. Application summary") == 2


def test_report_is_draft_until_signed_off(report):
    assert "Draft for review" in report["cells"] and "Final" not in re.search(r"Version\n([^\n]+)", report["cells"]).group(1)


def test_staffing_claims_require_staffing_evidence(report):
    # Source reveals maintenance skills, but cannot establish their availability.
    assert not re.search(r"\bscarce\b|small, shrinking pool", report["all"], re.I)
    assert "support cover" in report["all"].lower()
    assert "to confirm" in report["all"].lower()


def test_open_items_that_block_issue_come_first(report):
    items = re.findall(r"OI-\d+-\d+\n([^\n]+)", report["cells"])
    flags = [i.startswith("Blocks issue") for i in items]
    assert flags and flags == sorted(flags, reverse=True)


# ── the payment system (run 1) ─────────────────────────────────────────────────────────────────────────────────

def test_run1_draws_the_architectural_conclusions(run1):
    t = run1["all"]
    assert "Re-architect (phased, by component)" in t
    assert re.search(r"Payment data is held in \d+ places across \d+ platforms", t)
    assert "Microsoft SQL Server" in t and "drift apart between the" in t
    assert "approved without an authorized second person" in t


def test_run1_security_and_controls_are_consistent(run1):
    assert re.search(r"Security posture: [45] – ", run1["paras"])
    enc = re.search(r"Encryption in transit[^\n]*\n([^\n]+)\n([^\n]+)\n(\d) –", run1["cells"])
    assert enc and int(enc.group(3)) >= 3
    audit = re.search(r"Audit logging and monitoring\n([^\n]+)", run1["cells"]).group(1)
    assert "Local log file only" in audit


def test_run1_is_anonymized_and_tier_is_provisional(run1):
    assert not re.search(r"Minnesota|\bMDE", run1["all"])
    assert "CLIENT.DISTRICT_AID" in run1["all"]
    assert "Tier 1 (temporary" in run1["cells"]


def test_run1_eol_and_estimate(run1):
    assert "No (rewrite required)" in run1["cells"] and "Expired April 2008" in run1["cells"]
    assert "-221" not in run1["cells"]
    assert "Estimate by skill set" in run1["paras"] and "parallel runs" in run1["cells"]
    assert "5 means the least" in run1["all"]


def test_run1_no_credentials_in_dependency_reduction(run1):
    sec_103 = run1["cells"].split("Change to a statutory rate")[0][-400:]
    assert "credential" not in sec_103.lower()


# ── the non-financial modern app ───────────────────────────────────────────────────────────────────────────────

def test_library_says_nothing_that_does_not_apply(library):
    t = library["all"].lower()
    for word in ("payment", "posting", "vb6", "terminal screen", "ims ", "cics", "mainframe", "district"):
        if word == "payment":
            t = t.replace("payment card data", "")
        assert word not in t, word
    assert "8.6 financial" not in t


def test_library_recommendation_is_proportionate(library):
    assert re.search(r"Recommended disposition\n(Retain|Retain and modernize)", library["cells"])
    assert "Re-architect (phased" not in library["all"]
    assert "Python runtime" in library["cells"]


def test_sfaid_builds_with_mixed_legacy(sfaid):
    assert "COBOL" in sfaid["cells"] and "6.1 Health scorecard" in sfaid["paras"]


def test_shared_counts_agree_across_all_report_sections(report):
    from test_report_accuracy import _blocks, rows_after, section

    blocks = _blocks(report['doc'])
    rendered = {'lines': blocks}
    size = next(line for line in blocks if line.startswith('Size indicators'))
    match = re.search(r'(\d+) data store', size)
    count = int(match.group(1)) if match else 0
    observation = next(line for line in section(rendered, '4.4', '5.')
                       if line.startswith('The current source identifies'))
    assert int(re.search(r'(\d+) data store', observation).group(1)) == count
    stack = rows_after(rendered, '3.2', '3.3')
    unconfirmed = sum(row.split(' | ')[1].count('version unknown)') for row in stack)
    confidence = next(line for line in section(rendered, '13.3', '13.4')
                      if line.startswith('Assessment confidence'))
    match = re.search(r'(\d+) technology versions?', confidence)
    assert (int(match.group(1)) if match else 0) == unconfirmed
    migration = [line for line in blocks if re.search(r'(?:migration|reconciliation) of the \d+ copies', line)]
    reconcile = [r for r in rows_after(rendered, '12.4', '13.') if r.split(' | ')[0].startswith('Data ')]
    assert len(migration) == len({m for m in migration})
    assert len(reconcile) <= 2
