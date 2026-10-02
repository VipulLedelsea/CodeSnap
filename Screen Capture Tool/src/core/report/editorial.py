"""Short reader-facing report, with complete supporting evidence kept separately in the appendix.

This is a presentation pass. It must not change scores, source quotes or assessment decisions.
"""
import io
import re
import textwrap
from copy import deepcopy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.table import Table

MAX_LINES = 10
LINE_WIDTH = 68
HEADERS = {
    "Attribute": "Item", "Entry": "Result", "Observation": "What we found",
    "Observations": "What we found", "Recommended disposition": "Recommended action",
    "Disposition": "Action", "Remediation approach": "How to fix it",
    "Rationale": "Reason", "Gap identified": "What needs work",
    "Current state": "Current position", "Impact on operations and change": "Effect on the business",
    "Recommended mitigation": "Next action", "Existing mitigation": "Current protection",
    "Technical debt": "Maintenance problems", "Dimension": "Area",
    "Technology and version": "Technology and version", "Evidence": "Evidence",
    "Estimated effort": "Estimated work", "End of mainstream support": "Standard support ends",
    "End of extended support": "Extended support ends", "Measured value": "Result",
    "Acceptable threshold": "Target", "Root cause": "Cause", "What is true": "Position",
    "Quantity": "Qty", "Mainstream support end": "Standard support ends",
    "Vuln ID": "ID", "Affected component": "File", "CVE or CWE reference": "CVE/CWE",
    "CVSS score": "CVSS", "Severity": "Level", "Exploit known (Y/N)": "Exploit?",
    "Recommended remediation": "Action", "Restricted detail ref": "Detail",
    "Connected system (APP ID if in scope)": "System", "Frequency and trigger": "When",
    "Recommended future state": "Next action", "Dependencies": "Depends on",
}
PHRASES = {
    "recommended disposition": "recommended action", "Recommended disposition": "Recommended action",
    "provisional recommendation": "recommendation to confirm", "remediation": "repairs",
    "Remediation": "Repairs", "non-functional requirements": "service requirements",
    "Non-functional requirements": "Service requirements", "Technical debt summary": "Maintenance summary",
    "Technical debt register": "Maintenance issues", "Technical debt": "Maintenance problems",
    "technical debt": "maintenance problems", "Portfolio position": "Place in the application portfolio",
    "Transition architecture and decisions": "Future design and decisions",
    "Regulatory and policy alignment": "Policy requirements",
    "Risk and impact matrix": "Risks and business effects",
    "Current-state process": "Current process", "Estimated total remediation effort": "Estimated repair work",
    "material reviewed": "information reviewed", "supplied material": "information provided",
    "remains unconfirmed": "is not confirmed", "remain unconfirmed": "are not confirmed",
    "to confirm": "to check", "To confirm": "To check",
    "Calculation changes need verified regression coverage": "Test calculation changes against known results before release",
    "Confirm business criticality": "Confirm how important the application is to the business",
    "Proposed repairs is": "Proposed repairs are", "Repairs priorities": "Repair priorities",
}


def plain(text):
    for old, new in PHRASES.items():
        text = text.replace(old, new)
    text = re.sub(r"Support cover for (\d+) specialist skill sets is to check", r"Confirm support for \1 technical skill areas", text)
    text = re.sub(r"Provide (\d+) missing components", r"Check whether the \1 missing code references are required", text)
    return re.sub(r"\.\.(?=\s|$)", ".", text)


def lines(text):
    return textwrap.wrap(text, LINE_WIDTH, break_long_words=True, break_on_hyphens=False) or [""]


def decision(assessment, evidence):
    """Colour is an action recommendation, never a claim of certified operational safety."""
    verdict = assessment.get("verdict") or {}
    if not assessment.get("components") or not verdict:
        return "Not rated", "Complete the review before deciding what to do.", "666666"
    code = verdict.get("code")
    if code in {"retire", "replace", "rearchitect"}:
        return "Red", "Start retirement or replacement now. Protect essential services during the change.", "B42318"
    if (code != "retain" or evidence.get("blockers") or
            assessment.get("confidence", {}).get("level") != "high" or
            assessment.get("total_risk", {}).get("level") in {"high", "critical"}):
        return "Yellow", "Workable, but changes or checks are still needed.", "996300"
    return "Green", "Keep the application and continue routine maintenance.", "176B3A"


def _paragraph(document, text, style=None):
    p = document.add_paragraph(text, style)
    p.paragraph_format.space_after = Pt(6)
    return p._p


def _diagram(components):
    """An inventory diagram; no guessed connections between components."""
    from PIL import Image, ImageDraw
    from core.diagrams.render import _font
    image = Image.new("RGB", (1200, 280), "white")
    draw = ImageDraw.Draw(image)
    font, small = _font(26, True), _font(22)
    kinds = {}
    for c in components:
        key = c.get("language") or c.get("type") or "Other"
        kinds[key] = kinds.get(key, 0) + 1
    grouped = sorted(kinds.items(), key=lambda x: (-x[1], x[0]))
    boxes = grouped[:3]
    if len(grouped) > 3:
        boxes = grouped[:2] + [("Other formats", sum(n for _, n in grouped[2:]))]
    if not boxes:
        boxes = [("No components reviewed", 0)]
    width = 1160 / len(boxes)
    for i, (label, count) in enumerate(boxes):
        x = 20 + i * width
        draw.rounded_rectangle((x, 30, x + width - 20, 210), radius=8, fill="#F2F4F5", outline="#B8BEC4", width=2)
        for j, line in enumerate(textwrap.wrap(label, 22)):
            draw.text((x + 18, 50 + j * 32), line, font=font, fill="#111111")
        draw.text((x + 18, 145), f"{count} component{'s' if count != 1 else ''}", font=small, fill="#333333")
    draw.text((24, 235), "Reviewed components by format. Connections and deployment require separate evidence.", font=small, fill="#333333")
    out = io.BytesIO(); image.save(out, format="PNG")
    return out.getvalue()


def _next_steps_diagram():
    from PIL import Image, ImageDraw
    from core.diagrams.render import _font
    image = Image.new("RGB", (1200, 160), "white")
    draw = ImageDraw.Draw(image); font = _font(24, True)
    for i, label in enumerate(("Confirm evidence", "Fix or replace", "Test", "Owner approves")):
        x = 10 + i * 300
        draw.rounded_rectangle((x, 35, x + 255, 125), radius=6, fill="#F2F4F5", outline="#A0A8B0", width=2)
        draw.text((x + 12, 65), label, font=font, fill="black")
        if i < 3:
            draw.line((x + 260, 80, x + 286, 80), fill="black", width=3)
            draw.polygon(((x + 286, 80), (x + 278, 75), (x + 278, 85)), fill="black")
    out = io.BytesIO(); image.save(out, format="PNG")
    return out.getvalue()


def apply(doc, assessment, evidence, settings, *, metadata=None, security_counts=None, priority_reasons=()):
    document = doc.d
    from docx.enum.style import WD_STYLE_TYPE
    for name in ("Normal", "Body Text", "List Paragraph"):
        if name not in document.styles:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    body = document.element.body
    detail = []
    groups, current = [], None
    # Keep the template's sections and numbering. Limit prose for each numbered subsection.
    for el in list(body):
        if el.tag == qn("w:p"):
            p = Paragraph(el, document)
            if (p.style.name if p.style is not None else "").startswith("Heading") and (re.match(r"\d", p.text) or p.text.startswith("Appendix")):
                current = {"heading": p.text, "elements": []}
                groups.append(current)
            elif current is not None:
                current["elements"].append(el)
        elif current is not None and el.tag == qn("w:tbl"):
            current["elements"].append(el)
    main = [g for g in groups if not g["heading"].startswith("Appendix")]
    for group in main:
        if not re.match(r"\d", group["heading"]):
            continue
        if group["heading"].startswith("3.6 "):
            # Keep each complete, cited review with its component name. A prose
            # budget must never separate a finding from the file it describes.
            names = {c.get("name") for c in assessment.get("components", [])}
            first = next((i for i, el in enumerate(group["elements"]) if el.tag == qn("w:p")
                          and Paragraph(el, document).text in names), None)
            if first is not None:
                component_detail = group["elements"][first:]
                detail.append((group["heading"] + " — complete component reviews",
                               [deepcopy(el) for el in component_detail]))
                for el in component_detail:
                    el.getparent().remove(el)
                group["elements"] = group["elements"][:first]
                for el in group["elements"]:
                    if el.tag == qn("w:p"):
                        p = Paragraph(el, document)
                        if "marked below" in p.text:
                            p.text = p.text.replace("marked below", "marked in the appendix")
                note = _paragraph(document, "Each component's full review and line references are in the supporting detail appendix.")
                group["elements"][-1].addnext(note)
                group["elements"].append(note)
        narrative = [el for el in group["elements"] if el.tag == qn("w:p") and
                     Paragraph(el, document).text.strip() and not el.xpath(".//w:drawing") and
                     not Paragraph(el, document).text.startswith("Figure ") and
                     not (len(Paragraph(el, document).text.split()) <= 12 and
                          Paragraph(el, document).runs and Paragraph(el, document).runs[0].bold) and
                     not (Paragraph(el, document).style.name if Paragraph(el, document).style is not None else "").startswith("Heading")]
        original = [plain(Paragraph(el, document).text.strip()) for el in narrative]
        selected, records, used = [], [], 0
        candidates = list(zip(narrative, original))
        candidates.sort(key=lambda pair: not pair[1].startswith(("Assessment confidence", "Assumptions:")))
        for source_el, text in candidates:
            chosen = []
            # Complete sentences only; never cut a finding or its qualification halfway through.
            for sentence in ([text] if re.match(r"^\d+\.", text) else re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)):
                n = len(lines(sentence))
                if used + n <= 8:
                    selected.append(sentence); chosen.append(sentence); used += n
            if chosen:
                records.append((source_el, chosen))
        changed = " ".join(selected) != " ".join(original)
        if changed and original:
            detail.append((group["heading"], [deepcopy(el) for el in narrative]))
            selected.append("Full wording and tables are in the supporting detail appendix.")
            records.append((narrative[-1], [selected[-1]]))
        if narrative:
            for source_el, texts in records:
                el = deepcopy(source_el); source_el.addprevious(el)
                p = Paragraph(el, document)
                p.text = " ".join(texts)
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.keep_with_next = False
            for el in narrative:
                el.getparent().remove(el)
        noted_table = changed
        for el in group["elements"]:
            if el.tag != qn("w:tbl"):
                continue
            # Inventory totals and version qualifications must remain together.
            if group["heading"].startswith(("3.1 ", "3.2 ")):
                continue
            table = Table(el, document)
            changed_table = any(len(c.text.split()) > 32 or len(c.text) > 240 for r in table.rows[1:] for c in r.cells)
            if changed_table:
                long_cells = []
                for index, row in enumerate(table.rows[1:], 1):
                    seen = set()
                    for col, cell in enumerate(row.cells):
                        if cell._tc in seen: continue
                        seen.add(cell._tc)
                        if len(cell.text.split()) > 32 or len(cell.text) > 240:
                            label = f"{row.cells[0].text} — {table.rows[0].cells[col].text}"
                            # Use one whole short sentence or refer to the full evidence. No invented summary.
                            sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cell.text)[0]
                            if cell.text.startswith("Blocks issue:"):
                                # An issue gate needs its actual corrective action,
                                # not a generic pointer to another part of the report.
                                continue
                            p = document.add_paragraph(label + ": " + cell.text)
                            long_cells.append(deepcopy(p._p)); p._p.getparent().remove(p._p)
                            cell.text = plain(sentence) if len(sentence.split()) <= 32 and len(sentence) <= 240 else (
                                "Blocks issue: see supporting detail." if cell.text.startswith("Blocks issue:")
                                else "See supporting detail.")
                detail.append((group["heading"] + " table notes", long_cells))
                if not noted_table:
                    note = _paragraph(document, "Key entries shown. Full tables are in the supporting detail appendix.")
                    el.addnext(note); noted_table = True
    # Replace the long section 1 with a bounded two-page leadership brief.
    start = next((p for p in document.paragraphs if p.text.startswith("1. Application summary")), None)
    end = next((p for p in document.paragraphs if p.text.startswith("2. ") and p.style is not None and p.style.name == "Heading 1"), None)
    if start is not None and end is not None:
        el = start._p.getnext()
        snapshot = []
        while el is not None and el is not end._p:
            following = el.getnext()
            if el.tag == qn("w:tbl"):
                snapshot.append(deepcopy(el))
            el.getparent().remove(el); el = following
        if snapshot:
            detail.append(("1.1 Application snapshot", snapshot))
        start.text = "1. Executive summary"
        start.paragraph_format.page_break_before = True
        end.paragraph_format.page_break_before = True
        anchor = start._p
        def add(text, style=None):
            nonlocal anchor
            el = _paragraph(document, text, style); anchor.addnext(el); anchor = el
            return Paragraph(el, document)
        color, action, ink = decision(assessment, evidence)
        add("1.1 Decision", "Heading 2")
        p = add("Needs changes — Fix the issues and complete the missing checks." if color == "Yellow" else f"{color.upper()}  {action}")
        p.runs[0].bold = True; p.runs[0].font.color.rgb = RGBColor.from_string(ink)
        purpose = settings.get("purpose") or "The business purpose still needs confirmation."
        if len(purpose.split()) > 20:
            purpose = "See section 2.1 for the business purpose and owner."
        add(purpose)
        v = assessment.get("verdict") or {}
        add(f"Recommended action: {v.get('label') or 'Not rated'}. Confidence: {assessment.get('confidence', {}).get('level', 'not rated')}.")
        add("1.2 Why this decision", "Heading 2")
        high = security_counts if security_counts is not None else assessment.get("security", {}).get("by_severity", {})
        count = high.get("critical", 0) + high.get("high", 0)
        security_reason = (f"The assessment recorded {count} open critical or high security findings. Review their effect before approving changes."
                           if count else "No open critical or high security findings were recorded. This does not prove the application is secure.")
        reasons = ([security_reason,
                    f"{len(assessment.get('components') or [])} components were reviewed. Hidden source and runtime behavior are not confirmed."]
                   if assessment.get("components") else ["No components have been reviewed yet. No verdict can be given."])
        reasons = list(priority_reasons[:2]) + reasons[:1] if priority_reasons else reasons
        for reason in reasons[:3]:
            short = plain(reason)
            add(short if len(short.split()) <= 35 else "The detailed assessment gives the evidence for this recommendation.")
        if evidence.get("blockers"):
            add("Evidence is incomplete. Confirm the source, technical review and business requirements before approving changes.")
        p = add(""); p.add_run().add_picture(io.BytesIO(_diagram(assessment.get("components") or [])), width=Inches(6.5))
        add("Application overview. These are the components reviewed, not proof of the full system.")
        p = add("1.3 What to do next", "Heading 2"); p.paragraph_format.page_break_before = True
        priorities = [i for phase in assessment.get("roadmap", {}).get("phases", []) for i in phase.get("items", [])
                      if phase.get("phase") in {"assess", "stabilize"}]
        for i, item in enumerate(priorities[:3], 1):
            title = plain(item.get("title") or "Confirm the evidence")
            add(f"{i}. {title}" if len(title.split()) <= 18 else f"{i}. Resolve priority finding {i} in the detailed assessment.")
        if not priorities:
            add("1. Confirm the missing evidence and name the application owner.")
        add("Agree the plan with the owner. Test repairs before release.")
        add("How to read the colours", "Heading 3")
        legend = document.add_table(rows=1, cols=2)
        legend.columns[0].width = Inches(1.0); legend.columns[1].width = Inches(6.0)
        legend.cell(0, 0).text = "Status"; legend.cell(0, 1).text = "Action"
        legend.cell(0, 0).width = Inches(1.0); legend.cell(0, 1).width = Inches(6.0)
        anchor.addnext(legend._tbl); anchor = legend._tbl
        for label, explanation, hexcolor in [
            ("RED", "Act now. Start retirement or replacement and control the risk during the transition.", "B42318"),
            ("YELLOW", "Workable with changes. Repair the issues and complete the missing checks.", "996300"),
            ("GREEN", "Good to keep. Continue routine maintenance; this is not a security certification.", "176B3A")]:
            row = legend.add_row(); row.cells[0].text = label; row.cells[1].text = explanation
        add("Decision path", "Heading 3")
        p = add(""); p.add_run().add_picture(io.BytesIO(_next_steps_diagram()), width=Inches(6.5))
        add("Missing evidence cannot earn green. Keep essential services running during replacement.")
        if metadata is not None:
            metadata["traffic_light"] = color.lower()
    if detail:
        p = document.add_paragraph("Appendix I Supporting detail", "Heading 1")
        p.paragraph_format.page_break_before = True
        document.add_paragraph("Full findings and evidence behind the short sections. Section numbers match the main report.")
        for title, elements in detail:
            document.add_paragraph("Notes for " + plain(title), "Heading 2")
            for el in elements:
                body.insert(len(body) - 1, el)
    # Leadership sees the recommendation before contents and reference material.
    contents = next((p for p in document.paragraphs if p.text.strip() == "Contents"), None)
    if contents is not None and start is not None and end is not None:
        brief, el = [], start._p
        while el is not None and el is not end._p:
            brief.append(el); el = el.getnext()
        for el in brief:
            contents._p.addprevious(el)
        contents.paragraph_format.page_break_before = True
    _style(document)


def _style(document):
    for style in document.styles:
        if style.type == 1:
            style.font.color.rgb = RGBColor(0, 0, 0)
    for name in ("Normal", "Body Text", "List Paragraph"):
        style = document.styles[name]
        style.font.name = "Arial"; style.font.size = Pt(11)
        style.font.color.rgb = RGBColor(0, 0, 0)
    for name, size in (("Title", 24), ("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
        style = document.styles[name]
        style.font.name = "Arial"; style.font.size = Pt(size); style.font.color.rgb = RGBColor(0, 0, 0)
    in_appendix = False
    for p in document.paragraphs:
        if p.text.startswith("Appendix") and (p.style.name if p.style is not None else "").startswith("Heading"):
            in_appendix = True
        if not in_appendix and not p._p.xpath(".//w:drawing|.//w:fldChar|.//w:hyperlink") and plain(p.text) != p.text:
            p.text = plain(p.text)
        for run in p.runs:
            run.font.name = "Arial"
            if (p.style.name if p.style is not None else "").startswith("Heading"):
                run.font.color.rgb = RGBColor(0, 0, 0)
                run.font.size = document.styles[p.style.name].font.size
            else:
                run.font.size = Pt(11)
            if not p.text.startswith(("RED", "YELLOW", "GREEN", "Needs changes —")):
                run.font.color.rgb = RGBColor(0, 0, 0)
    for table in document.tables:
        heat_map = table.cell(0, 0).text.startswith("Impact 5")
        table.autofit = False
        section = document.sections[0]
        available = section.page_width - section.left_margin - section.right_margin
        widths = [max(c.width or 1, 1) for c in table.rows[0].cells]
        total = sum(widths)
        minimum = min(Inches(.65), int(available / len(widths)))
        fitted = [int(minimum + (available - minimum * len(widths)) * w / total) for w in widths]
        pr = table._tbl.tblPr
        width = pr.find(qn("w:tblW"))
        if width is not None:
            width.set(qn("w:type"), "dxa"); width.set(qn("w:w"), str(int(available / 635)))
        borders = pr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders"); pr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            item = borders.find(qn("w:" + edge))
            if item is None: item = OxmlElement("w:" + edge); borders.append(item)
            item.set(qn("w:val"), "single" if edge in {"bottom", "insideH"} else "nil")
            item.set(qn("w:sz"), "4"); item.set(qn("w:color"), "D8DDE1")
        for i, column in enumerate(table.columns):
            column.width = fitted[min(i, len(fitted)-1)]
        for row_index, row in enumerate(table.rows):
            for i, cell in enumerate(row.cells):
                cell.width = fitted[min(i, len(fitted)-1)]
                tcpr = cell._tc.get_or_add_tcPr()
                for border in list(tcpr.findall(qn("w:tcBorders"))): tcpr.remove(border)
                if not heat_map:
                    for shade in list(tcpr.findall(qn("w:shd"))): tcpr.remove(shade)
                if row_index == 0 and not heat_map:
                    shade = OxmlElement("w:shd"); shade.set(qn("w:fill"), "ECEFF1"); tcpr.append(shade)
                    if cell.text in HEADERS: cell.text = HEADERS[cell.text]
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(4); p.paragraph_format.space_before = Pt(3)
                    for run in p.runs:
                        run.font.name = "Arial"; run.font.size = Pt(9)
                        run.font.color.rgb = RGBColor(0, 0, 0); run.bold = row_index == 0
                        if row_index and cell.text in {"RED", "YELLOW", "GREEN"}:
                            run.font.color.rgb = RGBColor.from_string({"RED": "B42318", "YELLOW": "996300", "GREEN": "176B3A"}[cell.text])
                            run.bold = True
    for section in document.sections:
        for part in (section.header, section.first_page_header, section.even_page_header):
            for p in part.paragraphs:
                ppr = p._p.get_or_add_pPr()
                for border in list(ppr.findall(qn("w:pBdr"))): ppr.remove(border)
                for run in p.runs:
                    run.font.color.rgb = RGBColor(0, 0, 0); run.font.name = "Arial"; run.font.size = Pt(9)
