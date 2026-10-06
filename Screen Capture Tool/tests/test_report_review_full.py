import io
from docx import Document
from core import report_review as RR


def make(paras):
    d = Document()
    d.add_heading("1. Summary", 1)
    for p in paras:
        d.add_paragraph(p)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_every_body_sentence_is_a_claim():
    raw = make(["PAYROLL.cbl reads the master file and writes every record twice per run. Short one.",
                "The batch job never closes its output file after the final record is written."])
    cl = RR.extract_claims(raw, ["PAYROLL.cbl"])
    texts = [c["text"] for c in cl]
    assert len(cl) == 2 and "Short one." not in texts
    assert cl[0]["files"] == ["PAYROLL.cbl"] and cl[1]["files"] == []


class FakeStore:
    def __init__(self, v):
        self.v = v

    def get_meta(self, k):
        return {"report_review": {"verdicts": self.v}}.get(k)


def test_apply_removes_unsupported_and_annotates_partly():
    s1 = "PAYROLL.cbl reads the master file and writes every record twice per run."
    s2 = "The batch job never closes its output file after the final record is written."
    doc = Document(io.BytesIO(make([f"{s1} {s2}"])))
    store = FakeStore({RR.claim_key(s1): {"verdict": "unsupported"},
                       RR.claim_key(s2): {"verdict": "partly", "correction": "It closes it on the error path only."}})
    n = RR.apply_to_docx(doc, store)
    assert n == {"removed": 1, "corrected": 1}
    text = doc.paragraphs[-1].text
    assert "twice" not in text and "Code check: It closes it on the error path only." in text
