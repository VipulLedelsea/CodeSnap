"""Free, deterministic regression tests for the non-AI logic.

No API calls. Validator tests that need an external toolchain skip cleanly
when it isn't installed.
"""
import shutil
import tempfile
from pathlib import Path

import pytest
from core import analysis, validate
import hotkey_capture as hk


# ── stitch / overlap merge ───────────────────────────────────────────────────

def test_stitch_merges_scroll_overlap():
    f1 = "class A:\n    def __init__(self):\n        self.x = 1"
    f2 = "class A:\n    def __init__(self):\n        self.x = 1\n    def go(self):\n        return self.x"
    out = analysis.stitch_parts([f1, f2])
    assert out.count("class A:") == 1
    assert out.count("def __init__") == 1
    assert "def go(self):" in out


def test_stitch_keeps_distinct_blocks():
    a = "import os\nprint(os.getcwd())"
    b = "def helper():\n    return 42"
    out = analysis.stitch_parts([a, b])
    assert "import os" in out and "def helper():" in out


def test_overlap_len_requires_min_run():
    # a single shared line should not be treated as an overlap (min_overlap=2)
    assert analysis._overlap_len(["}"], ["}", "next"]) == 0
    assert analysis._overlap_len(["a", "b", "c"], ["b", "c", "d"]) == 2


# ── JSON parsing ─────────────────────────────────────────────────────────────

def test_parse_json_variants():
    assert analysis._parse_json('{"is_code": true}') == {"is_code": True}
    assert analysis._parse_json('prefix {"a": 1} suffix') == {"a": 1}
    assert analysis._parse_json("not json") is None


# ── hotkey helpers ───────────────────────────────────────────────────────────

def test_safe_ext():
    assert hk._safe_ext("py") == "py"
    assert hk._safe_ext(".CPP") == "cpp"
    assert hk._safe_ext("p y!") == "txt"
    assert hk._safe_ext("") == "txt"
    assert hk._safe_ext("a" * 20) == "txt"


def test_strip_code_fences():
    assert hk._strip_code_fences("```python\nprint(1)\n```") == "print(1)"
    assert hk._strip_code_fences("print(1)") == "print(1)"


# ── validators (skip if toolchain missing) ───────────────────────────────────

def _check(text, ext):
    p = Path(tempfile.mktemp(suffix=f".{ext}"))
    p.write_text(text)
    try:
        return validate.check_source(p)
    finally:
        p.unlink(missing_ok=True)


def test_validate_python_good_and_bad():
    assert _check("def f(x):\n    return x + 1\n", "py")["ok"] is True
    bad = _check("def f(x):\n    return x +\n", "py")
    assert bad["checked"] and bad["ok"] is False


def test_validate_skips_unknown_extension():
    res = _check("anything", "zzz")
    assert res["checked"] is False and "no checker" in res["note"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_validate_js():
    assert _check("let x = 1;\n", "js")["ok"] is True
    assert _check("let x = ;\n", "js")["ok"] is False


@pytest.mark.skipif(shutil.which("gcc") is None and shutil.which("clang") is None,
                    reason="no C compiler")
def test_validate_c():
    assert _check("int main(void){return 0;}\n", "c")["ok"] is True
    assert _check("int main(void){return 0\n", "c")["ok"] is False
