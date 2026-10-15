"""Start a capture at the first line of the file.

A capture is the screens the person scrolls through, so a file whose first screen was already below the top is read
without its head (a docstring, the imports, a license header) and nothing in the text says so. Before the first frame the
editor is scrolled up until the picture stops changing: that proves the top, whatever the file holds. Needs no editor
integration, only a scroll wheel event over the editor.
"""
import os
import time

STEP_LINES = (15, 30, 60, 120, 240, 480, 960)       # grows, so a very long file still reaches the top
MAX_STEPS = 60


def enabled() -> bool:
    """On by default; never under a test run, which must not scroll a real window."""
    return os.environ.get("CODESNAP_SCROLL_TO_TOP", "1") != "0" and "PYTEST_CURRENT_TEST" not in os.environ


def scroll_wheel_up(lines: int) -> None:
    """Scroll the window under the pointer up by `lines` lines."""
    import Quartz
    event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(lines))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def scroll_to_top(grab, scroll_up, changed, settle=0.35, sleep=time.sleep):
    """Scroll up until two pictures in a row are the same. Returns the number of scroll steps taken (0: already at the top),
    or None if the picture never settled (a video, a blinking element) so the top is not proven."""
    steps, previous = 0, grab()
    for n in range(MAX_STEPS):
        scroll_up(STEP_LINES[min(n, len(STEP_LINES) - 1)])
        sleep(settle)
        current = grab()
        if not changed(previous, current):
            return steps
        steps += 1
        previous = current
    return None
