import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.colfix import respace  # noqa: E402
from render import render_code  # noqa: E402

TRUTH = ["import os", "", "def first():", "    return 1", "", "# " + "-" * 70, "# Section title", "# " + "-" * 70,
         "", "def second():", "    return os.getcwd()", "", "x = first()"]


def test_a_divider_with_a_misread_dash_count_takes_its_length_from_the_pixels(tmp_path):
    png = render_code("\n".join(TRUTH), tmp_path / "x.png")
    bad = list(TRUTH)
    bad[5], bad[7] = "# " + "-" * 62, "# " + "-" * 66
    fixed, changed = respace(png, "\n".join(bad))
    assert fixed.split("\n") == TRUTH and changed >= 2
