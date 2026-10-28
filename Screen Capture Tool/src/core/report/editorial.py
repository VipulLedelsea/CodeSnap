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


SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<!etc\.)(?<!vs\.)(?<!cf\.)(?<=[.!?])\s+(?=[A-Z])")


def _sentences(text):
    """Split into sentences without breaking after e.g., i.e., etc., vs. or cf. (a capital letter often follows them)."""
    return SENTENCE_END.split(text)


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


def apply(doc, assessment, evidence, settings, *, metadata=None, security_counts=None, priority_reasons=(), analysis_stage=None, full_summary=False, evidence_rows=()):
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
            for sentence in ([text] if re.match(r"^\d+\.", text) else _sentences(text)):
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
                        parts = _sentences(cell.text)
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
            sentences = _sentences(text)
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
    _shorten_cells(document)
    overflow = _cap_registers(document)
    _add_appendices(doc, overflow, evidence_rows)
    _collapse_empty_tables(document)
    _landscape_wide_tables(document)
    _strip_removed_refs(document, numbers)
    _style(document)
    _simple_english(document)



# Tables kept short in the body: heading, rows kept, columns shown for rows moved to the appendix (id, description, rating)
REGISTER_CAPS = (("9.1 ", 6, (0, 1, 6), "Risk register"), ("7.3 ", 6, (0, 1, 7), "Technical debt register"),
                 ("5.1 ", 10, (0, 1, 5), "Data inventory"))
SUMMARY_WORDS = 22


ASIDE = re.compile(r"\s*\((?:e\.g\.|i\.e\.|and |such as|including|for example|repeated)[^()]*\)", re.I)
APPENDIX_WORDS = 40        # the further entries are the only place their text appears, so they keep more of it


def _short(text, words=SUMMARY_WORDS):
    parts = text.split()
    if len(parts) <= words:
        return text
    squeezed = ASIDE.sub("", text)          # a long aside ("(and repeated identically before every ... e.g. 152, 169)") hides the point
    if squeezed != text:
        return _short(squeezed, words)
    cut = " ".join(parts[:words])
    # a full stop after e.g., i.e., etc. or vs. is not the end of a sentence
    stops = [m.start() for m in re.finditer(r"(?<!e\.g)(?<!i\.e)(?<!etc)(?<!vs)\. ", cut)]
    k = max(stops[-1] if stops else -1, cut.rfind("; "), cut.rfind(", "))
    whole = k > len(cut) // 2
    # when no sentence or clause ends inside the limit, say the text was cut instead of ending it with a full stop
    out = (cut[:k] if whole else cut).rstrip(" ,;:.")
    while out.count("(") > out.count(")"):                  # never leave a bracket open: back up to before it
        out = out[:out.rfind("(")].rstrip(" ,;:.")
        whole = False
    return out + ("." if whole else "\u2026")



CELL_WORDS = 55


def _shorten_cells(document):
    """A table cell of more than 55 words keeps its first whole sentences or clauses within that limit."""
    for table in document.tables:
        for row in table.rows:
            seen = set()
            for cell in row.cells:
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                text = cell.text
                if len(text.split()) > CELL_WORDS and "\n" not in text and not text.lstrip().startswith("<insert"):
                    short = _short(text, CELL_WORDS)
                    if short != text and cell.paragraphs and cell.paragraphs[0].runs:
                        _set_text(cell.paragraphs[0], short)


def _cap_registers(document):
    """Keep the longest registers to their highest rows. The rows taken out are returned with the register name, so the
    appendix can list them and the body says where they went."""
    moved = []
    heading = None
    for el in list(document.element.body.iterchildren()):
        if el.tag == qn("w:p"):
            p = Paragraph(el, document)
            if (p.style.name if p.style is not None else "").startswith("Heading"):
                heading = p.text
        elif el.tag == qn("w:tbl") and heading:
            for prefix, keep, columns, name in REGISTER_CAPS:
                if not heading.startswith(prefix):
                    continue
                table = Table(el, document)
                body = list(table.rows)[1:]
                if len(body) <= keep + 3:      # moving a few rows saves nothing
                    break
                extra = body[keep:]
                rows = [[_short(r.cells[min(c, len(r.cells) - 1)].text, APPENDIX_WORDS if c == columns[0] else SUMMARY_WORDS) for c in columns] for r in extra]
                head = [table.rows[0].cells[min(c, len(table.rows[0].cells) - 1)].text for c in columns]
                if name == "Data inventory":      # the other columns are all open items; list the names only
                    rows, head = [[r[0]] for r in rows], [head[0]]
                for r in extra:
                    r._tr.getparent().remove(r._tr)
                note = _paragraph(document, f"The {keep} highest entries are shown. The other {len(extra)} are listed in Appendix H.")
                el.addnext(note)
                moved.append((name, head, rows))
                break
            heading = None
    return moved


def _add_appendices(doc, overflow, evidence_rows):
    """Appendix H: the register entries left out of the body. Appendix I: the findings the key-findings summary relies
    on, with file and lines."""
    from core.report import template_docx as TD
    document = doc.d
    if not overflow and not evidence_rows:
        return
    listed = next((p for p in document.paragraphs if p.text.startswith("Appendix G:")), None)
    for letter, text, wanted in (("I", "Appendix I: Evidence for the key findings (Section 1.2)", bool(evidence_rows)),
                                 ("H", "Appendix H: Further register entries (Sections 5.1, 7.3 and 9.1)", bool(overflow))):
        if listed is not None and wanted:
            el = deepcopy(listed._p)
            listed._p.addnext(el)
            _set_text(Paragraph(el, document), text)
    if overflow:
        document.add_paragraph("Appendix H. Further register entries", "Heading 1").paragraph_format.page_break_before = True
        for name, head, rows in overflow:
            anchor = document.add_paragraph(name, "Heading 2")
            if len(head) == 1:
                document.add_paragraph(f"{len(rows)} further entries: " + ", ".join(r[0] for r in rows) + ".")
                continue
            TD._table_after(doc, doc.table_proto, anchor._p, head, rows)
            document.add_paragraph("")
    if evidence_rows:
        document.add_paragraph("Appendix I. Evidence for the key findings (Section 1.2)", "Heading 1").paragraph_format.page_break_before = True
        anchor = document.add_paragraph("Each statement in the key findings rests on the review findings below.")
        TD._table_after(doc, doc.table_proto, anchor._p, ["File", "Lines", "Type", "Finding"], evidence_rows)



WIDE = []              # tables placed on a landscape page; _style sizes their columns to the wider page
WIDE_COLUMNS = 8       # a table with this many columns or more, and several rows, goes on a landscape page
WIDE_ROWS = 4
WIDE_TEXT = 2500       # characters; a small table fits on a portrait page


def _collapse_empty_tables(document):
    """A table with no entries ('None identified') shows that sentence across the full width, not in the first column."""
    for table in document.tables:
        if len(table.rows) != 2 or len(table.columns) < 3:
            continue
        row = table.rows[1]
        if len(row._tr.tc_lst) == len(table.columns) and row.cells[0].text.strip() and not any(c.text.strip() for c in row.cells[1:]):
            merged = row.cells[0].merge(row.cells[-1])
            for extra in [q for q in merged.paragraphs if not q.text.strip()][:]:
                if len(merged.paragraphs) > 1:
                    extra._p.getparent().remove(extra._p)


def _section_break(document, landscape):
    """A paragraph that ends a section; the section it ends is portrait or landscape."""
    body = document.element.body
    final = body.find(qn("w:sectPr"))
    sect = deepcopy(final)
    if landscape:
        size = sect.find(qn("w:pgSz"))
        width, height = size.get(qn("w:w")), size.get(qn("w:h"))
        size.set(qn("w:w"), height); size.set(qn("w:h"), width); size.set(qn("w:orient"), "landscape")
    kind = sect.find(qn("w:type"))
    if kind is None:
        kind = OxmlElement("w:type")
        sect.find(qn("w:pgSz")).addprevious(kind)       # the schema puts the section type just before the page size
    kind.set(qn("w:val"), "nextPage")
    p = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    ppr.append(sect)
    p.append(ppr)
    return p, sect


def _landscape_wide_tables(document):
    """Tables with eight or more columns (the risk and debt registers) get a landscape page, where their text columns
    have room. The heading above each stays with its table."""
    body = document.element.body
    final = body.find(qn("w:sectPr"))
    children = list(body.iterchildren())
    targets = []
    for i, el in enumerate(children):
        if el.tag != qn("w:tbl"):
            continue
        table = Table(el, document)
        if (len(table.columns) >= WIDE_COLUMNS and len(table.rows) > WIDE_ROWS and not table.cell(0, 0).text.startswith("Impact 5")
                and sum(len(c.text) for r in table.rows for c in r.cells) > WIDE_TEXT):
            head = i - 1
            while head >= 0 and not (children[head].tag == qn("w:p") and Paragraph(children[head], document).style is not None
                                     and Paragraph(children[head], document).style.name.startswith("Heading")):
                head -= 1
            end = i + 1
            while end < len(children) and children[end].tag == qn("w:p") and Paragraph(children[end], document).text.strip() \
                    and not (getattr(Paragraph(children[end], document).style, "name", "") or "").startswith("Heading") \
                    and not children[end].xpath(".//w:sectPr"):
                end += 1
            targets.append((head, i, end, el))
    first = True
    for head, i, end, el in targets:
        before, sect_p = _section_break(document, landscape=False)
        after, sect_l = _section_break(document, landscape=True)
        if not first:                  # only the document's first section keeps the cover page's own header
            for tag in ("w:headerReference", "w:footerReference", "w:titlePg"):
                for node in sect_p.findall(qn(tag)):
                    sect_p.remove(node)
        for tag in ("w:headerReference", "w:footerReference", "w:titlePg"):
            for node in sect_l.findall(qn(tag)):
                sect_l.remove(node)
        for node in final.findall(qn("w:titlePg")):
            final.remove(node)
        children[head].addprevious(before)
        children[end - 1].addnext(after)
        WIDE.append(el)
        first = False


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
            if not p.text.strip() and not style.startswith("Heading") and not p._p.xpath(skip + "|.//w:sectPr") and el.getparent() is not None:
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



CHAR_IN = 0.072        # inches per character at 9 pt Arial, on average


def _fit_columns(table, available):
    """Column widths in EMU from what each column holds: identifiers and ratings stay narrow, descriptions get the
    room. No column is narrower than its longest word, so words are not broken across lines."""
    n = len(table.columns)
    rows = [r for r in table.rows if len(r._tr.tc_lst) == n]
    if not rows:
        return [int(available / max(n, 1))] * max(n, 1)
    scale = 0.9 if n >= 8 else 1.0
    need, want = [], []
    for j in range(n):
        texts = [r.cells[j].text for r in rows[1:]] or [rows[0].cells[j].text]
        words = [len(w) for t in texts for w in t.split()] or [1]
        head = max([len(w) for w in rows[0].cells[j].text.split()] or [1])
        mean = sum(min(len(t), 260) for t in texts) / len(texts)
        low = max(0.45, (min(max(words), 14) * CHAR_IN + 0.18) * scale, (min(head, 11) * CHAR_IN * 0.85 + 0.18) * scale)
        need.append(low)
        want.append(max(low, (0.3 + mean * 0.05) * scale))
    room = available / 914400
    if sum(need) >= room:
        widths = [x * room / sum(need) for x in need]
    elif sum(want) >= room:
        extra = (room - sum(need)) / (sum(want) - sum(need) or 1)
        widths = [a + (b - a) * extra for a, b in zip(need, want)]
    else:
        widths = [w * room / sum(want) for w in want]
    return [int(w * 914400) for w in widths]


def _style(document):
    for style in document.styles:
        if style.type == 1:
            style.font.color.rgb = RGBColor(0, 0, 0)
    for name in ("Normal", "Body Text", "List Paragraph"):
        style = document.styles[name]
        style.font.name = "Arial"; style.font.size = Pt(10)
        style.font.color.rgb = RGBColor(0, 0, 0)
    for name, size, before, after in (("Title", 24, 0, 6), ("Heading 1", 16, 20, 6), ("Heading 2", 13, 14, 4), ("Heading 3", 11, 10, 3)):
        style = document.styles[name]
        style.font.name = "Arial"; style.font.size = Pt(size); style.font.color.rgb = RGBColor(0, 0, 0)
        if name != "Title":
            style.paragraph_format.space_before = Pt(before); style.paragraph_format.space_after = Pt(after)
            style.paragraph_format.keep_with_next = True
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
                run.font.size = Pt(10)
            if not p.text.startswith(("RED", "YELLOW", "GREEN", "Needs changes")):
                run.font.color.rgb = RGBColor(0, 0, 0)
    for table in document.tables:
        heat_map = table.cell(0, 0).text.startswith("Impact 5")
        table.autofit = False
        section = document.sections[0]
        available = section.page_width - section.left_margin - section.right_margin
        if table._tbl in WIDE:
            available = section.page_height - section.left_margin - section.right_margin
        fitted = _fit_columns(table, int(available))
        small = len(fitted) >= 8
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
            trpr = row._tr.get_or_add_trPr()
            for tag in ("w:cantSplit", "w:tblHeader"):
                if tag == "w:tblHeader" and row_index:
                    continue
                if trpr.find(qn(tag)) is None:
                    trpr.append(OxmlElement(tag))
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
                        run.font.name = "Arial"; run.font.size = Pt(8 if small else 8.5)
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
