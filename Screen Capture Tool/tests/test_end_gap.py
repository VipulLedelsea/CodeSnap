import numpy as np
from PIL import Image
from core.model import completeness as C


def _shot(path, rows, height=300):
    a = np.full((height, 200), 255, dtype=np.uint8)
    for i in range(rows):
        y = 10 + i * 20
        a[y:y + 10, 10:120] = 0
    Image.fromarray(a).save(path)


def test_big_gap_means_end_of_file(tmp_path):
    _shot(tmp_path / "a.png", 6)
    assert C.blank_tail(tmp_path / "a.png") > 5
    _shot(tmp_path / "b.png", 14)
    assert C.blank_tail(tmp_path / "b.png") < 1.5


def test_end_reasons_dropped_only_when_end_reached():
    r = {"partial": True, "reasons": ["2 unclosed '{' at end of file — end probably not captured",
                                      "sequence numbers jump 000010 → 000900 — lines missing between screenshots"]}
    out = C.drop_end_reasons(r)
    assert out["partial"] and len(out["reasons"]) == 1 and "sequence" in out["reasons"][0]
