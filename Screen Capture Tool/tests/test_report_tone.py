"""The report reads as if a person wrote it: counts in plain English, no form-filling labels, no stock AI phrases,
no echoed phrases or piled-up qualifiers, and sentences a reader can follow."""
import io
import re
import shutil
from pathlib import Path

import pytest

from conftest import need_fixture

docx = pytest.importorskip("docx")

from core.model import ProgramStore
from core.report import docx_bytes

RUN1 = Path(__file__).resolve().parent / "fixtures" / "run1_program"


@pytest.fixture(scope="module")
def paras(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tone")
    need_fixture(RUN1)
    shutil.copytree(RUN1, tmp / "p")
    with ProgramStore.open("p", root=tmp) as st:
        d = docx.Document(io.BytesIO(docx_bytes(st)))
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    return [p.text for p in d.paragraphs if p.text.strip()] + [c for c in dict.fromkeys(cells) if c.strip()]


def hits(paras, rx):
    return [p[:160] for p in paras if re.search(rx, p)]


def test_counts_are_written_out_not_as_file_s(paras):
    assert not hits(paras, r"\w\((e?s|ies)\)")


def test_no_form_filling_labels(paras):
    assert not hits(paras, r"What we see:|Why it matters:|Main reasons:|In short,|in plain terms|Fix: ")


def test_no_stock_ai_phrasing(paras):
    rx = (r"(?i)\b(delve|leverag\w+|robust|seamless\w*|comprehensive|holistic|furthermore|moreover|it is important to note|"
          r"it's worth noting|in today's|crucial|pivotal|tapestry|landscape of)\b")
    assert not hits(paras, rx)


def test_no_echoed_phrases_or_stacked_qualifiers(paras):
    assert not hits(paras, r"\b([A-Za-z][\w ]{3,40}) in \1\b")
    assert not hits(paras, r"\(([^()]*)\(([^()]*)\)\)\)")                     # three levels of brackets
    assert not hits(paras, r"rated [^.]{0,40}, rated")
    assert not [p for p in paras if p.count("(not provided)") > 3]
    assert not [p for p in paras if p.count("not identified)") > 2]
    assert not [p for p in paras if p.count("(tier provisional") > 0]


def test_no_text_cut_off_mid_word(paras):
    assert not hits(paras, r"\b[a-z]: [A-Z_]{4,}")                               # "…to show s: SCREEN"


def test_one_colon_per_sentence_in_the_summary(paras):
    start = next(i for i, p in enumerate(paras) if p.startswith("1.2 Why this decision"))
    end = next(i for i, p in enumerate(paras) if p.startswith("1.3 "))
    for p in paras[start + 1:end]:
        for sent in re.split(r"(?<=[.])\s+(?=[A-Z])", p):
            assert sent.count(": ") <= 1, sent


def test_sentences_are_readable_length(paras):
    prose = [s for p in paras if len(p) > 80 for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", p)]
    words = [len(s.split()) for s in prose]
    assert sum(words) / len(words) <= 28
    long = [s[:120] for s, n in zip(prose, words) if n > 70]
    assert len(long) <= 3, long
