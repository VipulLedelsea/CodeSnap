import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import topcheck  # noqa: E402


def _editor(position):
    state = {"top": position}
    return (lambda: ("frame", state["top"]),
            lambda lines: state.update(top=max(0, state["top"] - lines)),
            lambda a, b: a != b, state)


def test_a_file_scrolled_down_is_brought_to_its_first_line():
    grab, up, changed, state = _editor(400)
    steps = topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None)
    assert state["top"] == 0 and steps >= 1


def test_a_file_already_at_the_top_is_left_alone():
    grab, up, changed, state = _editor(0)
    assert topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None) == 0


def test_a_picture_that_never_settles_does_not_prove_the_top():
    counter = iter(range(10 ** 6))
    assert topcheck.scroll_to_top(lambda: next(counter), lambda lines: None, lambda a, b: a != b, sleep=lambda s: None) is None
