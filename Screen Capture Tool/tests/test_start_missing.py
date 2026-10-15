import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.model.completeness import check  # noqa: E402


def test_a_python_docstring_with_no_opening_quotes_means_the_start_is_missing():
    text = 'Authentication router.\n\nSecond line.\n"""\n\nfrom x import y\n'
    assert any("start probably not captured" in r for r in check(text, "a.py")["reasons"])
    assert not check('"""doc"""\nimport os\n', "a.py")["reasons"]


def test_a_block_comment_that_closes_before_it_opens_means_the_start_is_missing():
    assert any("start probably not captured" in r for r in check(" * Slice\n */\nimport a from 'b'\n", "s.ts")["reasons"])
    assert not check("/** x */\nimport a from 'b'\n", "s.ts")["reasons"]
