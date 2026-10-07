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
PROSE_LINES = 8        # most prose lines kept under each subsection
KEY_FINDINGS_MAX = 5   # the template asks for 3-5 short paragraphs under 1.2
FINDING_ORDER = ("Security", "Risk", "Effort", "Supportability", "Architecture")
LINE_WIDTH = 68
KEEP_SENTENCE = re.compile(r"Rating moved from|were not counted|line-by-line review found|No test files were identified|Errors are swallowed|scores (?:higher|the same) \(|cannot be recommended")
HEADERS = {}  # the template's column names are kept as written
PHRASES = {
    "provisional recommendation": "recommendation to confirm", "material reviewed": "information reviewed", "supplied material": "information provided",
    "remains unconfirmed": "is not confirmed", "remain unconfirmed": "are not confirmed",
    "to confirm": "to check", "To confirm": "To check",
    "Calculation changes need verified regression coverage": "Test calculation changes against known results before release",
    "Confirm business criticality": "Confirm how important the application is to the business",
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


def apply(doc, assessment, evidence, settings, *, metadata=None, security_counts=None, priority_reasons=(), analysis_stage=None, full_summary=False):
    document = doc.d
    from docx.enum.style import WD_STYLE_TYPE
    for name in ("Normal", "Body Text", "List Paragraph"):
        if name not in document.styles:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    body = document.element.body
    from core.report import template_fit
    removed = template_fit.remove_extras(document)
    numbers = template_fit.removed_numbers(removed)
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
        if not re.match(r"\d", group["heading"]) or group["heading"].startswith("1.2 "):
            continue
        narrative = [el for el in group["elements"] if el.tag == qn("w:p") and
                     Paragraph(el, document).text.strip() and not el.xpath(".//w:drawing") and
                     not Paragraph(el, document).text.startswith("Figure ") and
                     not (len(Paragraph(el, document).text.split()) <= 12 and
                          Paragraph(el, document).runs and Paragraph(el, document).runs[0].bold) and
                     not (Paragraph(el, document).style.name if Paragraph(el, document).style is not None else "").startswith("Heading")]
        if group["heading"].startswith("12.4 "):
            narrative = [el for el in narrative if not Paragraph(el, document).text.startswith(
                ("0.", "1.", "2.", "3.", "4.", "5.", "Constraint"))]
        original = [plain(template_fit.strip_references(Paragraph(el, document).text.strip(), numbers)) for el in narrative]
        selected, records, used = [], [], 0
        candidates = list(zip(narrative, original))
        candidates.sort(key=lambda pair: not pair[1].startswith(("Assessment confidence", "Assumptions:")))
        for source_el, text in candidates:
            chosen = []
            # Complete sentences only; never cut a finding or its qualification halfway through.
            for sentence in ([text] if re.match(r"^\d+\.", text) else re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)):
                n = len(lines(sentence))
                if used + n <= PROSE_LINES:
                    selected.append(sentence); chosen.append(sentence); used += n
            if chosen:
                records.append((source_el, chosen))
        changed = " ".join(selected) != " ".join(original)
        if narrative:
            for source_el, texts in records:
                el = deepcopy(source_el); source_el.addprevious(el)
                p = Paragraph(el, document)
                p.text = " ".join(texts)
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.keep_with_next = False
            for el in narrative:
                el.getparent().remove(el)
        for el in group["elements"]:
            if el.tag != qn("w:tbl"):
                continue
            if group["heading"].startswith(("3.1 ", "3.2 ")):
                continue
            table = Table(el, document)
            for row in table.rows[1:]:
                seen = set()
                for cell in row.cells:
                    if cell._tc in seen: continue
                    seen.add(cell._tc)
                    if (len(cell.text.split()) > 32 or len(cell.text) > 240) and not cell.text.startswith("Blocks issue:"):
                        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cell.text)
                        sentence = " ".join([parts[0]] + [x for x in parts[1:] if KEEP_SENTENCE.search(x)])
                        if len(sentence) < len(cell.text):
                            cell.text = plain(sentence)
    # Section 1 keeps the template layout: 1.1 snapshot, 1.2 key findings, 1.3 actions.
    color, action, ink = decision(assessment, evidence)
    findings = next((p for p in document.paragraphs if p.text.startswith("1.2 ")), None)
    if findings is not None:
        line = ("Needs changes. Fix the problems and finish the missing checks." if color == "Yellow"
                else f"{color.upper()}  {action}")
        if analysis_stage == "draft":
            line = "DRAFT: first-pass review, not yet checked line by line. " + line
        el = _paragraph(document, line)
        findings._p.addnext(el)
        first = Paragraph(el, document)
        first.runs[0].bold = True
        first.runs[0].font.color.rgb = RGBColor.from_string(ink)
        body_ps, nxt = [], el.getnext()
        while nxt is not None and not (nxt.tag == qn("w:p") and Paragraph(nxt, document).style is not None
                                       and Paragraph(nxt, document).style.name.startswith("Heading")):
            if nxt.tag == qn("w:p") and Paragraph(nxt, document).text.strip():
                body_ps.append(nxt)
            nxt = nxt.getnext()
        alt = "|".join(map(re.escape, numbers)) or "$^"
        gone = re.compile(rf"\bSections?\s+(?:{alt})\b|\((?:{alt})\)")
        keep = []
        for i, e in enumerate(body_ps):
            para = Paragraph(e, document)
            text = plain(template_fit.strip_references(para.text, numbers))
            if gone.search(text) or para.text.startswith("Code review"):
                continue
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
            if i == 0 and text.startswith("This assessment describes"):
                text = ("This report covers only the source code that was reviewed. "
                        "Ratings are temporary until the open items are closed.")
            elif full_summary:
                pass   # the written executive summary is kept whole: it was already limited to what executives need
            else:
                out, used = [], 0
                for sentence in sentences:
                    n = len(lines(sentence))
                    if used + n <= MAX_LINES:
                        out.append(sentence); used += n
                text = " ".join(out)
            _set_text(para, text)
            keep.append(e)
        def rank(e):
            if e is keep[0]:
                return 0
            label = Paragraph(e, document).text.split(" (")[0].split(".")[0]
            if label in FINDING_ORDER:
                return 2 + FINDING_ORDER.index(label)
            return 1 if len(label.split()) > 3 else 20
        ordered = keep[1:] if full_summary else sorted(keep, key=rank)[:KEY_FINDINGS_MAX - 1]
        for e in body_ps:
            if e not in ordered:
                e.getparent().remove(e)
        for e in ordered:
            e.getparent().remove(e)
        anchor = el
        for e in ordered:
            anchor.addnext(e); anchor = e
    if metadata is not None:
        metadata["traffic_light"] = color.lower()
    _strip_removed_refs(document, numbers)
    _style(document)
    _simple_english(document)


def _strip_removed_refs(document, numbers):
    if not numbers:
        return
    from core.report import template_fit
    skip = ".//w:drawing|.//w:fldChar|.//w:hyperlink"

    def fix(paragraph):
        style = paragraph.style.name if paragraph.style is not None else ""
        if style.startswith(("Heading", "Title")) or paragraph._p.xpath(skip) or not paragraph.text.strip():
            return
        new = template_fit.strip_references(paragraph.text, numbers)
        if new != paragraph.text:
            _set_text(paragraph, new)
    for paragraph in document.paragraphs:
        fix(paragraph)
    for table in document.tables:
        for row in table.rows:
            seen = set()
            for cell in row.cells:
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                for paragraph in cell.paragraphs:
                    fix(paragraph)


def _set_text(paragraph, text):
    runs = paragraph.runs
    if not runs:
        paragraph.text = text
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def _simple_english(document):
    from core.report.plainenglish import simplify
    skip = ".//w:drawing|.//w:fldChar|.//w:hyperlink"
    def fix(paragraph, prose):
        style = paragraph.style.name if paragraph.style is not None else ""
        if style.startswith(("Heading", "Title")) or paragraph._p.xpath(skip) or len(paragraph.text.split()) < 3:
            return
        if not prose and paragraph._p.getparent() is not None and paragraph._p.getparent().getparent() is not None \
                and paragraph._p.getparent().getparent().getparent() is not None \
                and paragraph._p.getparent().getparent().getprevious() is None:
            return  # header row of a table: keep the template's column names
        new = simplify(paragraph.text, prose=prose)
        if new != paragraph.text:
            _set_text(paragraph, new)
    seen_prose = set()
    for el in list(document.element.body.iterchildren()):
        if el.tag == qn("w:p"):
            p = Paragraph(el, document)
            style = p.style.name if p.style is not None else ""
            fix(p, True)
            key = re.sub(r"\W+", " ", p.text).strip().lower()
            if len(key.split()) >= 10 and not style.startswith(("Heading", "Title")) and not p._p.xpath(skip):
                if key in seen_prose and el.getparent() is not None:
                    el.getparent().remove(el)
                    continue
                seen_prose.add(key)
            if not p.text.strip() and not style.startswith("Heading") and not p._p.xpath(skip) and el.getparent() is not None:
                el.getparent().remove(el)
        elif el.tag == qn("w:tbl"):
            for row in Table(el, document).rows:
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    for p in cell.paragraphs:
                        fix(p, False)


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
            if not p.text.startswith(("RED", "YELLOW", "GREEN", "Needs changes")):
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
