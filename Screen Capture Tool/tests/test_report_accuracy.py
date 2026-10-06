"""Every statement in the report must be backed by the source it was built from, and the report must never disagree
with itself. Built from the 2026-09-30 demo program (COBOL batch, RPG posting, an HTML page, a screen image of that
page and an IMS DBD). Each test pins one kind of error found when the report was checked claim by claim."""
import io
import re
import shutil
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from docx.oxml.ns import qn
from docx.table import Table

from core.model import ProgramStore
from core.report import docx_bytes

DEMO = Path(__file__).resolve().parent / "fixtures" / "demo930"
if not (DEMO / "sources").is_dir():
    pytest.skip("tests/fixtures/demo930 is not present in this checkout", allow_module_level=True)
SOURCES = "\n".join(p.read_text(errors="ignore") for p in (DEMO / "sources").iterdir())


def _blocks(d):
    out = []
    for el in d.element.body.iterchildren():
        if el.tag == qn("w:p"):
            from docx.text.paragraph import Paragraph
            t = " ".join(Paragraph(el, d).text.split())
            if t.strip():
                out.append(t)
        elif el.tag == qn("w:tbl"):
            for r in Table(el, d).rows:
                cells, seen = [], []
                for c in r.cells:
                    if not any(c._tc is s for s in seen):
                        seen.append(c._tc)
                        cells.append(c.text.replace("\n", " / "))
                out.append(" | ".join(cells))
    return out


@pytest.fixture(scope="module")
def rep(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    shutil.copytree(DEMO, root / "demo930")
    # These tests pin generator facts that live in sections the final report trims
    # to the template, so read the report before that trim.
    from core.report import template_fit
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(template_fit, "remove_extras", lambda document: [])
        from core.report import editorial
        mp.setattr(editorial, "KEY_FINDINGS_MAX", 99)
        mp.setattr(editorial, "PROSE_LINES", 10_000)
        with ProgramStore.open("demo930", root=root) as st:
            d = docx.Document(io.BytesIO(docx_bytes(st, rescan=True)))
    lines = _blocks(d)
    return {"lines": lines, "text": "\n".join(lines)}


def section(rep, start, end=None):
    ls = rep["lines"]
    i = next(k for k, l in enumerate(ls) if l.startswith(start))
    j = next((k for k in range(i + 1, len(ls)) if end and ls[k].startswith(end)), len(ls))
    return ls[i:j]


def rows_after(rep, start, end):
    return [l for l in section(rep, start, end) if " | " in l]


def hits(rep, rx, flags=0):
    return [l[:200] for l in rep["lines"] if re.search(rx, l, flags) and not l.startswith(GLOSSARY)]


GLOSSARY = ("CICS | ", "IMS | ", "Term | ")


# ── nothing the source does not show ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("term", ["CICS", "DB/DC", "service accounts sign in", "Encrypt=True", "REST endpoint", "Tier 1 payment",
                                  "SQL Server", "desktop file", "lost with the PC"])
def test_no_technology_or_fact_the_source_does_not_show(rep, term):
    assert term.lower() not in SOURCES.lower()
    assert not hits(rep, re.escape(term), re.I)


def test_no_approval_where_the_code_has_none(rep):
    assert not re.search(r"(?i)approv", SOURCES)
    assert not hits(rep, r"(?i)approval screens|approves and posts|calculates, approves|failed approval|approved without")


def test_district_level_data_is_not_personal_data(rep):
    inv = rows_after(rep, "5.1 Data inventory", "5.2")
    assert inv and not [r for r in inv if "Personal data" in r]
    assert not hits(rep, r"personal data is handled|application handles personal data|Raised one level")


def test_totals_are_not_said_to_be_printed(rep):
    assert not hits(rep, r"(?i)totals are printed|totals on the control report|control totals, record counts")


def test_risks_are_worded_as_possibilities(rep):
    assert not hits(rep, r"(?i)(?<!can )(?<!could )\bdisagree between\b|no vendor fix|introduces an error nobody")


def test_no_guessed_downstream_systems(rep):
    assert not hits(rep, r"(?i)in practice the accounting system|a bank or EFT")


def test_no_hosting_claim_without_hosting_evidence(rep):
    assert not hits(rep, r"(?i)internet facing")


def test_rpg_indicators_are_not_claimed(rep):
    assert "*IN" not in SOURCES
    assert not hits(rep, r"\*INxx")


def test_display_file_is_not_data_and_record_format_is_not_a_component(rep):
    assert not hits(rep, r"Data it holds:.*AIDDSP")
    assert not hits(rep, r"AIDDSP, AIDSCR|AIDSCR, AIDDSP|AIDSCR \(not provided\)|provided: .*AIDSCR")
    assert not hits(rep, r"defines AIDDB01")


def test_validation_is_only_credited_where_the_code_checks_input(rep):
    row = next(r for r in rows_after(rep, "5.2", "5.3") if r.startswith("Validation controls"))
    assert "DistrictAidPayment.rpg" not in row


# ── the line-by-line review is not contradicted ─────────────────────────────────────────────────────────────────

def test_rule_findings_the_review_disproves_are_downgraded(rep):
    reg = rows_after(rep, "8.3 Vulnerability register", "8.4")
    cmd = [r for r in reg if "DistrictAidPayment.rpg:17" in r]
    assert cmd and "C:H/I:H/A:H" not in cmd[0] and " | Low (lowered after the line-by-line review)" in cmd[0]
    ssn = [r for r in reg if "html:57" in r]
    assert ssn and " | Low" in ssn[0]


def test_error_handling_row_uses_the_review(rep):
    assert not hits(rep, r"No swallowed errors were found")
    row = next(r for r in rows_after(rep, "8.6", "9.") if r.startswith("Error handling in posting"))
    assert "line" in row


def test_one_finding_per_source_line(rep):
    reg = rows_after(rep, "8.3 Vulnerability register", "8.4")
    assert len([r for r in reg if "html:46" in r]) == 1


def test_credentials_counted_once_and_everywhere_the_same(rep):
    assert hits(rep, r"^2 hard-coded credentials were also found")
    hv = next(r for r in rep["lines"] if r.startswith("Hard-coded values"))
    assert int(hv.split(" | ")[1]) >= 4


def test_exploit_column_is_not_asserted(rep):
    reg = rows_after(rep, "8.3 Vulnerability register", "8.4")
    assert reg and not [r for r in reg if re.search(r"\| Y \|", r)]


def test_severity_matches_its_cvss_band_or_says_why(rep):
    for r in rows_after(rep, "8.3 Vulnerability register", "8.4")[1:]:
        m = re.search(r"\| ([\d.]+) (Critical|High|Medium|Low) \(indicative[^|]*\| (Critical|High|Medium|Low)\b([^|]*)\|", r)
        if m and m.group(2) != m.group(3):
            assert "review" in m.group(4) or "indicative CVSS" in m.group(4), r


# ── the report agrees with itself ───────────────────────────────────────────────────────────────────────────────

def _register_counts(rep):
    reg = rows_after(rep, "8.3 Vulnerability register", "8.4")[1:]
    out = {}
    for r in reg:
        sev = r.split(" | ")[4].split(" ")[0].lower()
        out[sev] = out.get(sev, 0) + 1
    return out


def test_vulnerability_counts_agree(rep):
    c = _register_counts(rep)
    snap = next(r for r in rep["lines"] if r.startswith("Open critical or high vulnerabilities"))
    assert f"{c.get('critical', 0)} critical" in snap and f"{c.get('high', 0)} high" in snap
    summ = next(l for l in rep["lines"] if l.startswith("Security (Section 8)"))
    for k in ("critical", "high", "medium"):
        if c.get(k):
            assert f"{c[k]} {k}" in summ
    rows = rows_after(rep, "8.2 Vulnerability assessment summary", "8.3")
    tot = {k: 0 for k in ("critical", "high", "medium", "low")}
    for r in rows[1:]:
        cells = r.split(" | ")
        nums = [x for x in cells[-4:] if x.isdigit()]
        if len(nums) == 4:
            for k, n in zip(tot, nums):
                tot[k] += int(n)
    for k in tot:
        assert tot[k] == c.get(k, 0), (k, tot, c)


def test_platform_and_skill_counts_are_not_mixed_up(rep):
    assert not hits(rep, r"\b3 legacy platforms\b|needed on 3 platforms|on 3 platforms \(")


def test_screens_counted_once(rep):
    uc = next(r for r in rep["lines"] if r.startswith("Business users of the application screens"))
    size = next(r for r in rep["lines"] if r.startswith("Size indicators"))
    n = int(re.search(r"(\d+) screens?", uc).group(1))
    assert f"{n} screen" in size and "AIDSCR" not in uc


def test_review_coverage_statements_agree(rep):
    intro = next(l for l in rep["lines"] if "reviewed line by line" in l and "components" in l and "3.6" not in l[:5])
    m = re.search(r"(\d+) of the (\d+) components", intro)
    assert m, intro
    assert not hits(rep, r"^Code review \(Section 3\.6\)\. Each component was reviewed")
    ev = [r for r in rows_after(rep, "13.2", "13.3") if "School_Finance_State_Aid.screen" in r]
    assert ev and "checked line by line: complete" not in ev[0]


def test_no_shared_data_claim_when_nothing_is_shared(rep):
    assert hits(rep, r"share no data at run time|no data is shared directly")
    assert not hits(rep, r"data stores? connect the components|exchange data through files and shared databases")


def test_rpg_program_is_called_interactive_consistently(rep):
    ops = rows_after(rep, "10.5 Batch operations", "10.6")
    assert not [r for r in ops if r.startswith("DistrictAidPayment.rpg")]


def test_observability_agrees_with_financial_controls(rep):
    fc = next(r for r in rows_after(rep, "8.6", "9.") if r.startswith("Error handling in posting"))
    obs = next(l for l in rep["lines"] if l.startswith("Monitoring and alerting:"))
    assert ("swallowed" in obs or "not checked" in obs) == ("Not assessed" not in fc)


def test_recommendation_is_a_scored_option(rep):
    rec = next(r for r in rep["lines"] if r.startswith("Recommended disposition | ") and "Section 12" not in r)
    opt = rec.split(" | ")[1].split(" (")[0].split(":")[0].strip()
    head = next(r for r in rows_after(rep, "12.2", "12.3") if r.startswith("Criterion"))
    assert opt.lower() in head.lower(), (opt, head)


def test_weighted_average_printed_as_computed(rep):
    row = next(r for r in rep["lines"] if r.startswith("Overall health rating | 100%"))
    raw = row.split(" | ")[3]
    assert f"Weighted average {raw}" in row


def test_one_effort_estimate(rep):
    total = next(r for r in rep["lines"] if r.startswith("Total | "))
    rng = re.search(r"(\d+)–(\d+)", total.split(" | ")[1] if total.split(" | ")[1] else total).group(0)
    snap = next(r for r in rep["lines"] if r.startswith("Estimated total remediation effort"))
    eff = next(l for l in rep["lines"] if l.startswith("Effort (Section 12.4)"))
    assert rng in snap and rng in eff
    rows = rows_after(rep, "Estimate by skill set", "Assumptions")
    lo = sum(int(re.match(r"(\d+)–", r.split(" | ")[2]).group(1)) for r in rows[1:] if not r.startswith("Total"))
    assert lo == int(rng.split("–")[0])


def test_elapsed_time_covers_the_order_of_work(rep):
    eff = next(l for l in rep["lines"] if l.startswith("Effort (Section 12.4)"))
    hi = int(re.search(r"(\d+)–(\d+) months elapsed", eff).group(2))
    ends = [int(m.group(2)) for l in rep["lines"] for m in [re.search(r"\(months (\d+)–(\d+)\)", l)] if m]
    assert ends and max(ends) <= hi


def test_line_counts_agree(rep):
    size = next(r for r in rep["lines"] if r.startswith("Size indicators"))
    n = re.search(r"([\d,]+) lines", size).group(1)
    ass = next(l for l in rep["lines"] if l.startswith("Assumptions: the estimate covers"))
    assert f"({n} lines)" in ass


def test_browser_compatibility_is_not_excellent_for_an_ie6_page(rep):
    row = next(r for r in rep["lines"] if r.startswith("Mobile and browser compatibility"))
    assert "Excellent" not in row


def test_stability_reflects_high_defects_found_in_review(rep):
    row = next(r for r in rep["lines"] if r.startswith("Stability and reliability"))
    assert int(row.split(" | ")[2]) >= 3


def test_framework_claim_matches_the_register(rep):
    row = next(r for r in rep["lines"] if r.startswith("Security framework"))
    if "referenced by the findings" in row:
        reg = "\n".join(rows_after(rep, "8.3 Vulnerability register", "8.4"))
        assert "NIST" in reg


# ── reads as written by a person ────────────────────────────────────────────────────────────────────────────────

def test_no_stacked_brackets(rep):
    assert len(hits(rep, r"\) \((critical|high|medium|low)\)")) == 0
    assert len(hits(rep, r"\(lines? [\d–-]+\) \(lines? [\d–-]+\)")) == 0


def test_grammar_and_names(rep):
    assert not hits(rep, r"(?<![./])\bjquery\b(?![.-])")
    assert not hits(rep, r"tests on calculations is rated")
    assert not hits(rep, r"\b2 issues: [^.]*\.\s*\|")


def test_one_dash_style_in_line_ranges(rep):
    assert not hits(rep, r"\blines \d+-\d+\b")


def test_screen_image_of_a_page_adds_no_effort(rep):
    row = next(r for r in rep["lines"] if r.startswith("School_Finance_State_Aid.screen | ") and "Covered" in r)
    assert row
    web = next(r for r in rep["lines"] if r.startswith("Web front end | "))
    assert "School_Finance_State_Aid.screen" not in web


def test_unused_library_weaknesses_say_so(rep):
    reg = rows_after(rep, "8.3 Vulnerability register", "8.4")
    cves = [r for r in reg if "CVE-" in r]
    assert cves and all("lowered after the line-by-line review" in r for r in cves)


def test_skill_set_counts_agree(rep):
    eff = next(l for l in rep["lines"] if l.startswith("Effort (Section 12.4)"))
    n = int(re.search(r"across (\d+) skill sets", eff).group(1))
    rows = rows_after(rep, "Estimate by skill set", "Assumptions")[1:]
    assert n == len([r for r in rows if not r.startswith("Total")])


def test_open_items_have_one_section_reference(rep):
    assert not hits(rep, r"\(\d+(\.\d+)?\) \(Section \d")
    assert not hits(rep, r"\(Section (Cover|Document control)\)")


def test_db_accounts_only_with_a_connection():
    from core.report.evidence import db_credentials
    f = {"rule": "SEC-CRED", "detail": "Credential literal in code. Raised one level: this file or connection handles "
                                         "personal data.", "evidence": [{"snippet": 'var apiKey = "****";'}]}
    assert db_credentials([f]) == []
    g = {**f, "evidence": [{"snippet": "Data Source=X;User ID=web;Password=****"}]}
    assert db_credentials([g]) == [g]


def test_uncalled_script_function_is_not_personal_data():
    from core.security.scan import uncalled_lines
    text = "function a(){\n x();\n}\nfunction showSsn(ssn) {\n  document.write(ssn);\n}\n<body onload='a()'>"
    assert {4, 5, 6} <= uncalled_lines(text) and 1 not in uncalled_lines(text)


def test_current_data_store_count_agrees(rep):
    size = next(r for r in rep["lines"] if r.startswith("Size indicators"))
    count = re.search(r"(\d+) data store", size)
    observation = next(l for l in section(rep, "4.4", "5.") if l.startswith("The current source identifies"))
    assert int(re.search(r"(\d+) data store", observation).group(1)) == (int(count.group(1)) if count else 0)
    from core.report.evidence import data_stores

    class Store:
        def entities(self, kind):
            return [{"id": i, "name": name, "origin": origin} for i, name, origin in
                    [(1, "CURRENT", "code"), (2, "OLD", "code"), (3, "MISSING", "placeholder"), (4, "DISPLAY", "code")]]

        def entity_sources(self, entity_id):
            return [{"artifact_id": 2 if entity_id == 2 else 1}]

    assert [e["name"] for e in data_stores(Store(), [{"id": 1, "transcription": "dcl-f DISPLAY workstn;"}])] == ["CURRENT"]


def test_migration_entity_copies_match_ownership(rep):
    ownership = rows_after(rep, "System of record by entity", "6. Application health")
    counts = [int(r.split(" | ")[1]) for r in ownership if r.split(" | ")[1].isdigit()]
    copies = sum(n for n in counts if n >= 2)
    migration = [l for l in rep["lines"] if re.search(r"migration of the \d+ copies", l)]
    assert copies > 0 and migration
    assert int(re.search(r"migration of the (\d+) copies", migration[0]).group(1)) == copies


def test_unconfirmed_versions_match_displayed_stack(rep):
    stack = rows_after(rep, "3.2", "3.3")
    count = sum(r.split(" | ")[1].count("version unknown)") for r in stack)
    confidence = next(l for l in section(rep, "13.3", "13.4") if l.startswith("Assessment confidence"))
    assert count > 0
    assert int(re.search(r"(\d+) technology versions?", confidence).group(1)) == count


def test_pain_points_and_usability_titles_end_at_boundaries():
    from core.text import shorten_at_boundary
    from core.report.template_docx import _pain_points
    from core.uireview.screens import check_screens
    issue = "The page gives no feedback after submission, " + "users cannot tell whether their payment was received " * 3
    assert shorten_at_boundary(issue, 90) == "The page gives no feedback after submission"
    assert _pain_points([{"severity": "medium", "title": issue}]) == ["The page gives no feedback after submission."]
    assert shorten_at_boundary("x" * 100, 90) == "x" * 100

    class Store:
        def entities(self):
            return [{"id": 1, "parent_id": None, "kind": "screen", "origin": "code", "name": "form",
                     "artifact_id": 1, "attrs": {"technology": "screenshot", "issues": [issue]}}]

        def artifacts(self):
            return [{"id": 1, "name": "form.screen"}]

        def relations(self):
            return []

    assert check_screens(Store())[0]["title"] == "The page gives no feedback after submission"


def test_coupling_without_deductions_has_no_weakest_file(monkeypatch):
    from core.report import rationale as R
    monkeypatch.setattr(R, "WORDS", True)
    assessment = {"scores": {"coupling": {"score": 100, "worst": {"score": 100, "component": "clean"}}},
                  "components": [{"name": "clean", "scores": {"coupling": {"factors": [
                      {"points": 0, "rule": "COUPLING", "text": "No calls found"}]}}}]}
    assert R.explain_program(assessment, "coupling") == "1 – Excellent. No problems were found."
    monkeypatch.setattr(R, "WORDS", False)
    assert "weakest file" not in R.explain_program(assessment, "coupling")
