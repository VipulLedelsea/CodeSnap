import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core import analysis, colfix  # noqa: E402
from render import render_code  # noqa: E402


def _source():
    out = []
    for n in range(1, 9):
        out += [f"def handler_{n}(request):", "    value = request.get('id')", "    if value is None:",
                "        return None", "    total = compute(value)", "    return {'total': total}", ""]
    return out


def _frames(tmp_path, source, height, step):
    parts, metas = [], []
    for i, start in enumerate(range(0, len(source) - height + 1, step)):
        text = "\n".join(source[start:start + height])
        png = render_code(text, tmp_path / f"f{i}.png")
        parts.append(text)
        metas.append({"image": str(png)})
    return parts, metas


def test_repeated_handlers_are_stitched_by_the_scroll_the_pixels_measured(tmp_path):
    source = _source()
    parts, metas = _frames(tmp_path, source, height=26, step=13)
    rows = analysis._frame_rows(parts, metas, [])
    assert all(rows)
    stitched = analysis._stitch(parts, set(), {}, rows)
    assert stitched.rstrip("\n").split("\n")[:len(source) - 8] == source[:len(source) - 8][:len(stitched.split("\n"))]
    assert stitched.count("def handler_3(request):") == 1


def test_the_seam_is_found_only_where_the_repeated_lines_agree_exactly():
    merged = ["x = 1", "SUBTRACT 12 FROM A", "IF Y < 2003", "MOVE 1 TO Z", "END-IF", "2190-NEXT."]
    assert analysis._seam(merged, ["SUBTRACT 12 FROM A", "IF Y < 2003", "MOVE 1 TO Z", "END-IF", "2190-NEXT."]) == 5
    look_alike = ["SUBTRACT 11 FROM A", "IF Y < 2002", "MOVE 1 TO Z", "END-IF", "2180-NEXT."]
    assert analysis._seam(merged, look_alike) is None
