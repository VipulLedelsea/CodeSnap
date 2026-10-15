import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import analysis, verify  # noqa: E402


def test_a_banner_read_with_different_dash_characters_is_flagged_for_review():
    final = "x = 1\n# ── Helpers ──────\ny = 2"
    parts = [final, "x = 1\n# —— Helpers ——————\ny = 2", "x = 1\n# -- Helpers ------\ny = 2"]
    assert analysis._glyph_conflicts(final, parts) == [2]
    out = verify.summarize(final, {}, {"glyph_conflicts": [2]})
    assert any(f["reason"] == verify.REASONS["glyph"] and f["line"] == 2 for f in out["flags"])


def test_a_divider_every_screenshot_reads_the_same_way_is_not_flagged():
    final = "# " + "-" * 40 + "\nvalue = 1"
    assert analysis._glyph_conflicts(final, [final, final]) == []
