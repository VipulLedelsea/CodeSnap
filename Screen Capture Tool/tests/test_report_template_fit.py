"""The finished report contains the template's sections and nothing more."""
import io
import shutil
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from core.model import ProgramStore
from core.report import docx_bytes, template_fit

DEMO = Path(__file__).resolve().parent / "fixtures" / "demo930"
EXTRA_OK = {"rating scales and definitions", "appendix g. glossary",
            # the register overflow appendices: rows cut from a long register go here and the body says so
            "appendix h. further register entries", "technical debt register", "risk register",
            "appendix i: open items, continued", "appendix j: technical debt register, continued", "appendix k: risk register, continued"}


@pytest.mark.skipif(not DEMO.exists(), reason="the demo930 fixture program is git-ignored and only exists on the original machine")
def test_report_headings_are_all_in_the_template(tmp_path):
    shutil.copytree(DEMO, tmp_path / "demo930")
    with ProgramStore.open("demo930", root=tmp_path) as st:
        d = docx.Document(io.BytesIO(docx_bytes(st, rescan=True)))
    allowed = template_fit.template_headings() | EXTRA_OK
    heads = [" ".join(p.text.split()).lower() for p in d.paragraphs
             if p.style is not None and p.style.name.startswith("Heading") and p.text.strip()]
    assert [h for h in heads if h not in allowed] == []


def test_references_to_removed_sections_are_dropped():
    assert template_fit.strip_references("Code review (Section 3.6). Done.", ["3.6"]) == "Code review. Done."
    assert template_fit.strip_references("See Sections 4.4 and 5.5.", ["5.5"]) == "See Sections 4.4."
