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


class _Art(dict):
    pass


class _RunStore:
    """Just enough store for report_review.run: artifacts, the earlier verdicts and the deepdive findings."""

    def __init__(self, texts, earlier=None):
        self.texts = texts
        self.meta = {"report_review": {"verdicts": earlier or {}}, "deepdive": {}}

    def artifacts(self):
        return [{"id": i, "name": n, "transcription": t, "language": "cobol"} for i, (n, t) in enumerate(self.texts.items(), 1)]

    def get_meta(self, k, default=None):
        return self.meta.get(k, default)

    def set_meta(self, k, v):
        self.meta[k] = v


def test_rerun_asks_only_about_claims_whose_file_changed(monkeypatch):
    from core import deepdive as D
    s_a = "A.cbl reads the master file and writes every record twice per run."
    s_b = "B.cbl never closes its output file after the final record is written."
    docx = make([f"{s_a} {s_b}"])
    texts = {"A.cbl": "line one\nline two", "B.cbl": "other one\nother two"}
    earlier = {RR.claim_key(s_a): {"verdict": "supported", "file": "A.cbl", "basis": D._hash(texts["A.cbl"]), "kind": "text"},
               RR.claim_key(s_b): {"verdict": "supported", "file": "B.cbl", "basis": "stale", "kind": "text"}}
    asked = []

    def fake_ask(store, client, model, art, claims):
        asked.extend((art["name"], c["key"]) for c in claims)
        return {c["key"]: {"verdict": "partly", "file": art["name"], "basis": D._hash(art["transcription"]), "kind": "text",
                           "id": "", "correction": "", "why": "", "lines": None} for c in claims}

    monkeypatch.setattr(RR, "_ask", fake_ask)
    monkeypatch.setattr(D, "_META_LOCK", __import__("threading").Lock())
    store = _RunStore(texts, earlier)
    out = RR.run(store, None, docx, model="m")
    assert asked == [("B.cbl", RR.claim_key(s_b))]
    assert out["reused"] == 1
    kept = store.meta["report_review"]["verdicts"]
    assert kept[RR.claim_key(s_a)]["verdict"] == "supported" and kept[RR.claim_key(s_b)]["verdict"] == "partly"
