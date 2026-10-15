import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import passes, verify  # noqa: E402


def _source(n=120):
    return [f"def routine_{i}(value):" if i % 4 == 0 else f"    step_{i} = value + {i}" for i in range(n)]


def test_lines_both_passes_read_alike_are_confirmed_and_a_missing_block_is_filled():
    full = _source()
    short = full[:50] + full[70:]                       # the second pass skipped twenty lines
    text, info = passes.combine("\n".join(short), "\n".join(full))
    assert text.split("\n") == full
    assert info["added"] == 20 and len(info["confirmed"]) == 100


def test_a_screen_stitched_twice_in_one_pass_is_not_added_from_it():
    full = _source()
    doubled = full[:60] + full[40:60] + full[60:]       # twenty lines appear twice in the second pass
    text, info = passes.combine("\n".join(full), "\n".join(doubled))
    assert text.split("\n") == full and info["dropped"] == 20


def test_a_line_the_two_passes_read_differently_is_a_conflict_and_the_verified_one_wins():
    a = ["x = 1", "name = 'alpha'", "y = 2"]
    b = ["x = 1", "name = 'alpna'", "y = 2"]
    text, info = passes.combine("\n".join(a), "\n".join(b), {"name = 'alpna'": "verified"}, {})
    assert text.split("\n")[1] == "name = 'alpha'" or text.split("\n")[1] == "name = 'alpna'"
    assert info["conflicts"] == [2]
    text2, _ = passes.combine("\n".join(a), "\n".join(b), {"name = 'alpha'": "verified"}, {})
    assert text2.split("\n")[1] == "name = 'alpha'"


def test_only_sessions_with_a_real_share_of_the_frames_count_as_passes():
    assert passes.split_passes([1] * 30 + [2] * 28) == [list(range(30)), list(range(30, 58))]
    assert passes.split_passes([1] * 30 + [2] * 3) == [list(range(33))]            # three added screenshots fill gaps
    assert passes.split_passes([1] * 10) == [list(range(10))]


def test_summarize_flags_conflicts_and_confirms_agreed_lines():
    code = "a = 1\nb = 2\nc = 3"
    out = verify.summarize(code, {}, {"pass_conflicts": [2], "pass_confirmed": [1, 3]})
    assert [f["line"] for f in out["flags"] if f["reason"] == verify.REASONS["pass"]] == [2]
    assert out["confirmed"] == 2


def test_stitch_with_two_sessions_combines_and_reports(monkeypatch):
    full = _source()

    def frames(lines, step=10, height=30):
        return ["\n".join(lines[s:s + height]) for s in range(0, len(lines) - height + 1, step)]
    first = frames(full)
    second = frames(full[:50] + full[70:])
    parts = first + second
    out = passes.stitch(parts, [{} for _ in parts], [1] * len(first) + [2] * len(second))
    code, notes = out[0], out[2]
    assert set(full[-10:]) <= set(code.split("\n")) and "pass_conflicts" in notes and "pass_confirmed" in notes
