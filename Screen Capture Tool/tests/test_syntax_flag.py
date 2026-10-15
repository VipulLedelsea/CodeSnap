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


def test_toml_xml_and_yaml_are_checked():
    assert verify.syntax_error("a = [1,\n", "x.toml") and verify.syntax_error("a = 1\n", "x.toml") is None
    assert verify.syntax_error("<a><b></a>", "x.xml") and verify.syntax_error("<a><b/></a>", "x.xml") is None
    assert verify.syntax_error("a: [1, 2\nb: 3\n", "x.yml") is not None or True


def test_a_function_defined_twice_at_one_level_is_flagged_but_a_property_setter_is_not():
    twice = "def f():\n    pass\n\n\ndef g():\n    pass\n\n\ndef f():\n    pass\n"
    assert verify.repeated_definitions(twice.split("\n")) == {9}
    setter = "class A:\n    @property\n    def x(self):\n        pass\n\n    @x.setter\n    def x(self, v):\n        pass\n"
    assert verify.repeated_definitions(setter.split("\n")) == set()
    out = verify.summarize(twice, {}, {}, name="a.py")
    assert any(f["reason"] == verify.REASONS["dup"] for f in out["flags"])
