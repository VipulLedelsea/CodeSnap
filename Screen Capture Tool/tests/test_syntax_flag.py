import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from core import verify  # noqa: E402

GOOD = "import os\n\ndef f():\n    return os.getcwd()\n"
BAD = "import os\n\n    def f():\n    return os.getcwd()\n"


def test_python_that_does_not_parse_is_flagged_at_the_failing_line():
    out = verify.summarize(BAD, {}, {}, name="a.py")
    assert any(f["reason"] == verify.REASONS["syntax"] for f in out["flags"])
    assert out["lines"] == verify.summarize(BAD, {}, {}, name="a.txt")["lines"]


def test_python_that_parses_and_other_languages_are_not_flagged():
    assert not verify.summarize(GOOD, {}, {}, name="a.py")["flags"]
    assert not verify.summarize(BAD, {}, {}, name="a.cbl")["flags"]
    assert not verify.summarize(BAD, {}, {})["flags"]


def test_json_is_checked_too():
    assert verify.syntax_error('{"a": 1,}', "x.json")
    assert verify.syntax_error('{"a": 1}', "x.json") is None
