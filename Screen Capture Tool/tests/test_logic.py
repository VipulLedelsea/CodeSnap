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


# ── extraction cleaning (regression for the "markdown fed to javac" bug) ──────

def test_clean_source_strips_fences_and_headers():
    from core.analysis import clean_source
    messy = "# Title\n\n```java\npublic class A {}\n```"
    out = clean_source(messy)
    assert "```" not in out
    assert "# Title" not in out
    assert "public class A {}" in out


def test_clean_source_strips_line_number_gutter():
    from core.analysis import clean_source
    messy = "```py\n1  x = 1\n2  y = 2\n3  print(x + y)\n```"
    out = clean_source(messy)
    assert "1  x" not in out and "2  y" not in out
    assert "x = 1" in out and "print(x + y)" in out


def test_merge_frames_collapses_duplicate_screens():
    from core.analysis import merge_frames
    a = "```java\npublic class A {\n    void m() {}\n}\n```"
    b = "```java\n1  public class A {\n2      void m() {}\n3  }\n```"  # same code, gutter
    code, parts = merge_frames([a, b, a])
    assert code.count("public class A") == 1          # collapsed to one copy
    assert "    void m()" in code                      # kept the indented version
    assert "```" not in code and "1  public" not in code


def test_clean_source_strips_markdown_headers_without_fences():
    from core.analysis import clean_source, merge_frames
    # a screen-reader adding "# ..." headers over code (no fences) must not reach the compiler
    a = "public class A {\n    void m() {}\n}"
    b = "# A.java\n\n# public class A\n\n" + a
    out = clean_source(b)
    assert not any(l.lstrip().startswith("#") for l in out.splitlines())
    # and duplicate frames (one plain, one header-prefixed) collapse to a single copy
    code, _ = merge_frames([a, b, a])
    assert code.count("public class A") == 1


def test_clean_source_keeps_real_comments_and_directives():
    from core.analysis import clean_source
    assert "# note here" in clean_source("x = 1\n# note here\ny = 2")   # python comment kept
    assert "#include <stdio.h>" in clean_source("#include <stdio.h>\nint main(){return 0;}")


def test_looks_truncated_distinguishes_capture_cutoff_from_real_errors():
    from core.validate import looks_truncated
    assert looks_truncated("unterminated triple-quoted string literal (detected at line 99)")
    assert looks_truncated("SyntaxError: '(' was never closed")
    assert looks_truncated("reached end of file while parsing")
    assert not looks_truncated("IndentationError: expected an indented block")
    assert not looks_truncated("error: ';' expected")


def test_merge_frames_handles_ocr_variance_and_duplicate_recaptures():
    from core.analysis import merge_frames
    full = [
        "class Book:", "    title = ''", "    author = ''",
        "class Library:", "    def __init__(self):", "        self.books = []",
        "    def add(self, b):", "        self.books.append(b)",
    ]
    b = lambda i, j: "\n".join(full[i:j])
    f1 = b(0, 5)                                                  # top: through def __init__
    f2 = b(3, 8).replace("class Library:", "class Library :")     # overlaps 2 lines + OCR wobble
    f3 = b(0, 5).replace("class Book:", "class Book :")           # duplicate re-capture of the top
    code, _ = merge_frames([f1, f2, f3])
    assert code.count("class Book") == 1        # no duplicated class
    assert code.count("class Library") == 1
    assert "def add" in code                    # bottom content preserved
    assert len(code.splitlines()) <= 12         # not a concatenated mess


def test_merge_frames_top_stays_visible_each_frame():
    # the real failure: short-ish file where every frame re-shows the top and just
    # reveals a bit more at the bottom (top never scrolls off). Must not duplicate.
    from core.analysis import merge_frames
    full = [f"a{i} = {i}" for i in range(1, 16)]
    full[2] = "class Book:"; full[9] = "class Library:"
    w = lambda t: t.replace("class Book:", "class Book :")  # OCR wobble
    b = lambda i, j: w("\n".join(full[i:j]))
    code, _ = merge_frames([b(0, 8), b(0, 12), b(0, 15)])   # top stays, grows downward
    assert code.count("class Book") == 1
    assert code.count("class Library") == 1
    assert "a15 = 15" in code                                # last line captured
    assert len([l for l in code.splitlines() if l.strip()]) <= 17


def test_merge_frames_falls_back_when_stitch_would_duplicate():
    # even if stitching fails on messy frames, the result must not duplicate a class.
    from core.analysis import merge_frames
    whole = "class A:\n    def m(self):\n        return 1\n\nclass B:\n    def n(self):\n        return 2\n"
    frames = [whole, whole.replace("return 1", "return 1 "), whole.replace("class A:", "class A: ")]
    code, _ = merge_frames(frames)
    assert code.count("class A") == 1 and code.count("class B") == 1


def test_normalize_extract_parses_line_array_and_corrections():
    # structured JSON: raw_transcription (line array) + corrections_applied[]
    from core.analysis import _normalize_extract
    payload = (
        '{"raw_transcription": ["def add(a, b)", "    return a + b"],'
        ' "corrections_applied": [{"line": 1, "saw": "def add(a, b)",'
        ' "suggested": "def add(a, b):"}]}'
    )
    out = _normalize_extract(payload)
    # raw is joined verbatim — the missing colon is PRESERVED, not fixed
    assert out["raw"] == "def add(a, b)\n    return a + b"
    assert "def add(a, b):" not in out["raw"]
    assert len(out["corrections"]) == 1
    assert out["corrections"][0]["saw"] == "def add(a, b)"


def test_normalize_extract_falls_back_on_non_json():
    # if the model doesn't return JSON, treat the whole reply as raw text (never crash)
    from core.analysis import _normalize_extract
    out = _normalize_extract("x = 1\ny = 2")
    assert out["raw"] == "x = 1\ny = 2"
    assert out["corrections"] == []


def test_normalize_extract_tolerates_json_in_prose():
    # extracts the embedded object even with stray text around it
    from core.analysis import _normalize_extract
    out = _normalize_extract('here:\n{"raw_transcription": ["a=1"], "corrections_applied": []}\ndone')
    assert out["raw"] == "a=1"
    assert out["corrections"] == []


def test_fmt_corrections_renders_note_and_empty():
    from team import _fmt_corrections
    assert _fmt_corrections([]) == ""
    assert _fmt_corrections(None) == ""
    note = _fmt_corrections([{"line": 1, "saw": "def f()", "suggested": "def f():"}])
    assert "def f()" in note and "def f():" in note
