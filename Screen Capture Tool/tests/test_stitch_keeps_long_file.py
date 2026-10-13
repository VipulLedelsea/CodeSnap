"""A long stitched file is not thrown away for one screen of text because a class name repeats."""
from core import analysis


def _file(n_models=12):
    out = ['"""Schemas."""', "", "from pydantic import BaseModel", ""]
    for i in range(n_models):
        out += [f"class Model{i}(BaseModel):", f"    id: int", f"    name: str", f"    value_{i}: float",
                f"    other_{i}: str", f"    third_{i}: int", "", "    class Config:", "        from_attributes = True",
                f"        title = 'model {i}'", "", "", "", "", "", ""]
    return out


def _frames(lines, height=15, step=8):
    return ["\n".join(lines[i:i + height]) for i in range(0, max(1, len(lines) - height + step), step)]


def test_repeated_inner_class_name_does_not_collapse_the_file_to_one_screen():
    lines = _file()
    code = analysis.merge_verified(_frames(lines))[0]
    assert len(code.splitlines()) >= 0.9 * len(lines)
    assert "class Model11(BaseModel):" in code


def test_mis_merged_duplicate_is_flagged_not_silently_replaced_by_one_screen(monkeypatch):
    lines = _file()
    real = analysis._stitch
    # a stitch that repeats a block: the whole long text must still win over one frame, with the repeat reported
    monkeypatch.setattr(analysis, "_stitch", lambda parts, prefer, notes: "\n".join(lines + lines[10:30]))
    code, _, notes, _ = analysis.merge_verified(_frames(lines))
    assert len(code.splitlines()) > len(lines)
    assert notes.get("duplicate_headers")


def test_real_overlap_with_separator_and_blank_row_noise_is_not_repeated():
    """Two consecutive screens of a real capture (batch-test-10-09 USER.py): their 25 shared rows differ in a separator
    drawn with other dashes and an extra blank row, so the strict matcher finds no overlap. The shared rows must still be
    written once."""
    import json
    from pathlib import Path
    fx = json.loads((Path(__file__).parent / "fixtures" / "overlap_noisy_frames.json").read_text())
    code = analysis.stitch_parts([fx["a"], fx["b"]])
    rows = [r for r in code.splitlines() if r.strip().startswith("class ")]
    assert len(rows) == len(set(r.strip() for r in rows)), rows
    assert len(code.splitlines()) < len(fx["a"].splitlines()) + len(fx["b"].splitlines()) - 15
