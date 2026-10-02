import io
import re
from types import SimpleNamespace

from docx import Document
from core.report import editorial


def test_colour_requires_evidence_and_never_confuses_missing_with_green():
    a = {"components": [{"name": "a"}], "verdict": {"code": "retain"},
         "confidence": {"level": "high"}, "total_risk": {"level": "low"}}
    assert editorial.decision(a, {"blockers": []})[0] == "Green"
    assert editorial.decision(a, {"blockers": ["review pending"]})[0] == "Yellow"
    a["verdict"]["code"] = "replace"
    assert editorial.decision(a, {})[0] == "Red"
    assert editorial.decision({}, {})[0] == "Not rated"


def test_short_sections_preserve_full_evidence_and_diagrams():
    d = Document()
    d.add_heading("1. Application summary", 1)
    d.add_heading("1.1 Application snapshot", 2)
    d.add_paragraph("Old long summary.")
    d.add_heading("2. Business context", 1)
    d.add_heading("2.1 Purpose", 2)
    original = " ".join(f"Finding {i} needs a check before changes are approved." for i in range(25))
    d.add_paragraph(original)
    table = d.add_table(rows=9, cols=2)
    table.cell(0, 0).text = "Attribute"; table.cell(0, 1).text = "Entry"
    for i in range(1, 9):
        table.cell(i, 0).text = f"Evidence {i}"; table.cell(i, 1).text = f"a.cbl:{i}"
    d.add_heading("3.6 Code analysis by component", 2)
    d.add_paragraph("One component has a detailed review.")
    d.add_paragraph("a.cbl").runs[0].bold = True
    quote = "Displays 'Remediation' (line 8)."
    d.add_paragraph(quote)
    a = {"components": [{"name": "a.cbl", "language": "COBOL"}], "verdict": {"code": "retain", "label": "Retain"},
         "confidence": {"level": "low"}, "roadmap": {"phases": []}}
    meta = {}
    editorial.apply(SimpleNamespace(d=d), a, {"blockers": ["missing evidence"]}, {}, metadata=meta)
    assert meta["traffic_light"] == "yellow"
    paragraphs = d.paragraphs
    section = next(i for i, p in enumerate(paragraphs) if p.text == "2.1 Purpose")
    assert len(editorial.lines(paragraphs[section + 1].text)) <= 10
    assert "\n" not in paragraphs[section + 1].text
    status = next(p for p in paragraphs if p.text.startswith("Needs changes —"))
    assert str(status.runs[0].font.color.rgb) == "996300"
    from core.report.html import render_document
    check_data = io.BytesIO(); d.save(check_data)
    assert 'color:#996300;font-weight:700' in render_document(check_data.getvalue(), {})
    assert original in "\n".join(p.text for p in paragraphs)
    appendix = next(i for i, p in enumerate(paragraphs) if p.text.startswith("Appendix I"))
    assert not any(p.text == "a.cbl" for p in paragraphs[:appendix])
    name = next(i for i, p in enumerate(paragraphs) if p.text == "a.cbl")
    assert paragraphs[name + 1].text == quote
    evidence_table = next(t for t in d.tables if t.cell(0, 0).text == "Item")
    assert len(evidence_table.rows) == 9
    assert any("a.cbl:8" in c.text for t in d.tables for r in t.rows for c in r.cells)
    assert len(d.inline_shapes) == 2
    assert next(p for p in paragraphs if p.text.startswith("1.3")).paragraph_format.page_break_before
    assert next(p for p in paragraphs if p.text.startswith("2. Business")).paragraph_format.page_break_before
    target = io.BytesIO(); d.save(target)
    assert Document(io.BytesIO(target.getvalue())).inline_shapes


def test_numbered_actions_remain_whole_and_html_preserves_risk_colours():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from core.report.html import render_document
    d = Document()
    d.add_heading("12.4 Sequencing and timing", 2)
    action = "1. Confirm " + "the required evidence " * 60 + ". Nothing is rebuilt before this decision."
    d.add_paragraph(action)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Impact 5"
    t.cell(0, 1).text = "25"
    shade = OxmlElement("w:shd"); shade.set(qn("w:fill"), "F4C7C3")
    t.cell(0, 1)._tc.get_or_add_tcPr().append(shade)
    identifier = "LONG_SOURCE_REFERENCE_" * 30
    t.cell(1, 0).text = "Source"; t.cell(1, 1).text = identifier
    editorial.apply(SimpleNamespace(d=d), {}, {}, {})
    appendix = next(i for i, p in enumerate(d.paragraphs) if p.text.startswith("Appendix I"))
    assert not any(p.text.strip() == "1." or "Nothing is rebuilt" in p.text for p in d.paragraphs[:appendix])
    assert any(p.text == action for p in d.paragraphs[appendix:])
    assert any(identifier in p.text for p in d.paragraphs[appendix:])
    assert t.cell(1, 1).text == "See supporting detail."
    data = io.BytesIO(); d.save(data)
    html = render_document(data.getvalue(), {})
    assert "background:#F4C7C3" in html
    assert "<th" in html
