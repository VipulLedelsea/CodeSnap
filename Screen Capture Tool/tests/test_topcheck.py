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


def _scrollable(position, responsive=True, length=400):
    """An editor whose picture is its scroll position; an unresponsive one ignores the wheel (it is under another window)."""
    state = {"top": position}

    def move(delta):
        if responsive:
            state["top"] = min(length, max(0, state["top"] + delta))
    return (lambda: ("frame", state["top"]), lambda lines: move(-lines), lambda lines: move(lines), lambda a, b: a != b, state)


def test_a_wheel_that_reaches_the_editor_proves_the_top_when_the_picture_stays_put():
    grab, up, down, changed, state = _scrollable(0)
    assert topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None, scroll_down=down) == 0
    assert state["top"] == 0                    # the probe scrolled down a little and came back


def test_a_picture_that_never_moves_does_not_prove_the_top_when_the_wheel_is_not_reaching_the_editor():
    grab, up, down, changed, state = _scrollable(250, responsive=False)
    assert topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None, scroll_down=down) is None
    # without the probe the same picture would have been taken for the top
    assert topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None) == 0


def test_a_scrolled_file_still_reaches_the_top_with_the_probe_available():
    grab, up, down, changed, state = _scrollable(250)
    steps = topcheck.scroll_to_top(grab, up, changed, sleep=lambda s: None, scroll_down=down)
    assert state["top"] == 0 and steps >= 1


def test_a_person_scrolling_at_the_same_moment_cannot_fake_the_top():
    """Two matching pictures in a row are not enough: the person's own wheel can leave them equal. One more scroll up must also change nothing."""
    from core import topcheck
    state = {"pos": 10, "calls": 0}
    def grab():
        return state["pos"]
    def up(lines):
        state["calls"] += 1
        if state["calls"] == 1:
            return                       # the wheel did nothing once (the person's scroll cancelled it): two equal pictures
        state["pos"] = max(0, state["pos"] - lines)
    steps = topcheck.scroll_to_top(grab, up, lambda a, b: a != b, sleep=lambda s: None)
    assert steps is not None and state["pos"] == 0
