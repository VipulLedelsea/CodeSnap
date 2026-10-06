import re
from functools import lru_cache
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

TEMPLATE = Path(__file__).parent / "assets" / "Application_Assessment_Report_Template.docx"
NUMBERED = re.compile(r"^(\d+)(\.\d+)?\.?\s")


def _style(paragraph):
    return paragraph.style.name if paragraph.style is not None else ""


@lru_cache(maxsize=1)
def template_headings():
    document = Document(str(TEMPLATE))
    return {re.sub(r"\s+", " ", p.text).strip().lower() for p in document.paragraphs
            if _style(p).startswith("Heading") and p.text.strip()}


def _key(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def _blocks(document):
    blocks, current = [], None
    for el in list(document.element.body.iterchildren()):
        heading = None
        if el.tag == qn("w:p"):
            p = Paragraph(el, document)
            if _style(p).startswith(("Heading 1", "Heading 2")) and p.text.strip():
                heading = p
        if heading is not None:
            current = {"level": 1 if _style(heading).startswith("Heading 1") else 2, "text": heading.text.strip(), "elements": [el]}
            blocks.append(current)
        elif current is not None:
            current["elements"].append(el)
    return blocks


def extra_blocks(document):
    allowed = template_headings()
    keep_h1 = False
    extra = []
    for block in _blocks(document):
        text = block["text"]
        if block["level"] == 1:
            keep_h1 = bool(NUMBERED.match(text)) or _key(text) in allowed or _key(text) in {
                "rating scales and definitions", "document control"}
            if text.startswith("Appendix") and not text.startswith("Appendix G"):
                keep_h1 = False
            if not keep_h1:
                extra.append(block)
            continue
        if not keep_h1:
            extra.append(block)
        elif NUMBERED.match(text) and _key(text) not in allowed and not _renamed(text):
            extra.append(block)
    return extra


RENAMED_OK = ("1.1 ", "1.2 ", "1.3 ")


def _renamed(text):
    return text.startswith(RENAMED_OK)


def remove_extras(document):
    removed = []
    for block in extra_blocks(document):
        removed.append(block["text"])
        for el in block["elements"]:
            if el.getparent() is not None and el.tag != qn("w:sectPr"):
                el.getparent().remove(el)
    return removed


def removed_numbers(headings):
    return sorted({m.group(0).strip() for h in headings for m in [re.match(r"^\d+\.\d+", h)] if m})


def strip_references(text, numbers):
    if not numbers:
        return text
    alt = "|".join(re.escape(n) for n in numbers)
    text = re.sub(rf"\s*\((?:see\s+)?Sections?\s+(?:(?:{alt})(?:\s*(?:,|and)\s*)?)+\)", "", text)
    text = re.sub(rf"\s*\((?:see\s+)?(?:(?:{alt})(?:\s*(?:,|and)\s*)?)+\)", "", text)
    text = re.sub(rf"\b(Sections?)\s+(\d+\.\d+)\s+and\s+(?:{alt})\b", r"\1 \2", text)
    text = re.sub(rf"\b(Sections?)\s+(?:{alt})\s+and\s+(\d+\.\d+)\b", r"\1 \2", text)
    text = re.sub(rf"\b(\d+\.\d+)\s+and\s+(?:{alt})\b", r"\1", text)
    text = re.sub(rf"\b(?:{alt})\s+and\s+(\d+\.\d+)\b", r"\1", text)
    text = re.sub(rf"[,;]?\s*(?:see|in|from|under)\s+(?:Sections?\s+)?(?:{alt})(?!\d)", "", text)
    text = re.sub(rf"\s*,\s*(?:{alt})(?![\d])", "", text)
    text = re.sub(rf"(?<![\d.])(?:{alt})\s*,\s*", "", text)
    return text
