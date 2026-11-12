from core import exec_summary as ES


class _S:
    def __init__(self, a, saved): self.m = {"assessment": a, "exec_summary": saved}
    def get_meta(self, k): return self.m.get(k)


def test_paragraphs_show_report_label_when_wording_differs():
    s = {"verdict": "Remediate", "report_label": "Retain and modernize selected components"}
    assert "Retain and modernize selected components" in ES.paragraphs(s)[0]
    assert "report's recommended" not in ES.paragraphs({"verdict": "Retain", "report_label": "Retain"})[0]
