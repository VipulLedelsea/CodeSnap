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
PROBE_LINES = 3                                   # a short scroll down that must move the picture if the wheel reaches the editor


def enabled() -> bool:
    """Off by default: in a screen-share the person must keep full control of their editor. Never under a test run, which must not scroll a real window."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    if "CODESNAP_SCROLL_TO_TOP" in os.environ:
        return os.environ["CODESNAP_SCROLL_TO_TOP"] != "0"
    try:
        from core import settings
        return bool(settings.get("scroll_to_top", False))        # the person's choice in Settings, read at each capture
    except Exception:  # noqa: BLE001
        return False


def scroll_wheel_up(lines: int) -> None:
    """Scroll the window under the pointer up by `lines` lines."""
    import Quartz
    event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(lines))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def scroll_wheel_down(lines: int) -> None:
    """Scroll the window under the pointer down by `lines` lines."""
    scroll_wheel_up(-int(lines))


def editor_point(fracs):
    """Where the pointer must sit for the wheel to reach the code: the middle of the capture area (fractions of the screen), or
    the middle of the screen when the whole screen is captured. None when the screen cannot be measured."""
    try:
        import mss
        from core.capture import _monitor
        with mss.mss() as sct:
            mon = _monitor(sct)
        left, top, width, height = fracs if fracs else (0.0, 0.0, 1.0, 1.0)
        return (mon["left"] + (left + width / 2) * mon["width"], mon["top"] + (top + height / 2) * mon["height"])
    except Exception:  # noqa: BLE001 - no display or no mss: scroll where the pointer is
        return None


def pointer_position():
    import Quartz
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return (point.x, point.y)


def move_pointer(point) -> None:
    import Quartz
    Quartz.CGWarpMouseCursorPosition(point)
    Quartz.CGAssociateMouseAndMouseCursorPosition(True)


def scroll_to_top(grab, scroll_up, changed, settle=0.6, sleep=time.sleep, scroll_down=None):
    """Scroll up until two pictures in a row are the same. Returns the number of scroll steps taken (0: already at the top),
    or None if the top is not proven: the picture never settled (a video, a blinking element), or it did not move when the
    file was scrolled a little down and back, so the wheel may not be reaching the editor (a picture that never changes proves
    nothing about where the file is). The probe needs `scroll_down`; without it a picture that stays put counts as the top."""
    def up():
        steps, previous = 0, grab()
        for n in range(MAX_STEPS):
            scroll_up(STEP_LINES[min(n, len(STEP_LINES) - 1)])
            sleep(settle)
            current = grab()
            if not changed(previous, current):
                # one more scroll up that must change nothing: a person scrolling down at the same moment can leave two
                # pictures that match without the file being at its top
                scroll_up(STEP_LINES[min(n, len(STEP_LINES) - 1)])
                sleep(settle)
                if not changed(current, grab()):
                    return steps
            steps += 1
            previous = current
        return None

    steps = up()
    if steps != 0 or scroll_down is None:
        if steps is not None:
            sleep(settle)
        return steps
    top = grab()
    scroll_down(PROBE_LINES)
    sleep(settle)
    moved = changed(top, grab())
    if moved and up() is None:
        return None                      # scrolled away from the top and could not get back to a settled picture
    if not moved:
        return None
    sleep(settle)                         # the editor's smooth-scroll animation must have finished before the first frame is taken
    return 0
