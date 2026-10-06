from types import SimpleNamespace as NS

from core import analysis, neighbor

RAWS = ["import os\n\ndef total(items):\n    result = 0\n    for item in items:\n        result += item.pr[CUT OFF]",
        "    for item in items:\n        result += item.price\n    return result\n\ndef show(value):\n    print(value)"]


class Client:
    def __init__(self, found=True, text="        result += item.price"):
        self.calls, self.found, self.text = [], found, text
        self.messages = NS(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="tool_use", input={"lines": [{"id": 1, "found": self.found, "text": self.text}]})])


def build(tmp_path):
    paths = []
    for i in range(2):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"x")
        paths.append(p)
    final, _, notes, statuses = analysis.merge_verified(list(RAWS), [{}, {}])
    return paths, final, notes, statuses


def test_cut_off_line_is_read_from_the_neighbouring_screenshot(tmp_path):
    paths, final, notes, statuses = build(tmp_path)
    final = final.replace("item.price", "item.pr[CUT OFF]")
    c = Client()
    out, fixed = neighbor.repair(c, paths, list(RAWS), final, notes, statuses)
    assert "item.price" in out and "[CUT OFF]" not in out
    assert fixed and fixed[0]["now"].strip() == "result += item.price" and c.calls


def test_unclear_neighbour_changes_nothing(tmp_path):
    paths, final, notes, statuses = build(tmp_path)
    final = final.replace("item.price", "item.pr[CUT OFF]")
    out, fixed = neighbor.repair(Client(found=False), paths, list(RAWS), final, notes, statuses)
    assert out == final and not fixed


def test_unrelated_reading_is_rejected(tmp_path):
    paths, final, notes, statuses = build(tmp_path)
    final = final.replace("item.price", "item.pr[CUT OFF]")
    out, fixed = neighbor.repair(Client(text="print('hello world today')"), paths, list(RAWS), final, notes, statuses)
    assert out == final and not fixed


def test_clean_text_makes_no_calls(tmp_path):
    paths, final, notes, statuses = build(tmp_path)
    c = Client()
    out, fixed = neighbor.repair(c, paths, list(RAWS), final.replace("[CUT OFF]", "ice"), notes, statuses)
    assert not c.calls
