"""Screenshots whose columns the pixel check placed are not moved by noisy neighbour deltas."""
from core import analysis


def frame(lead, n=12):
    return "\n".join(" " * lead + f"statement_{i}()" for i in range(n))


def test_pinned_frames_are_never_shifted_or_chained():
    frames = [frame(0), frame(5), frame(0), frame(5), frame(0)]
    assert analysis._equalize_frame_offsets(frames, pinned={0, 1, 2, 3, 4}) == frames


def test_unpinned_frames_are_still_equalized():
    frames = [frame(0), frame(1), frame(1)]
    fixed = analysis._equalize_frame_offsets(frames)
    assert fixed != frames


def test_measured_lines_one_column_right_move_left_but_model_lines_stay():
    text = "\n".join([" a = 1"] * 6 + ["b = 2"])
    meta = {"spacing": {"calibrated": True, "line_status": ["measured"] * 6 + ["unmeasured"]}}
    out = analysis._drop_measured_margin([text], [meta])[0].split("\n")
    assert out[:6] == ["a = 1"] * 6 and out[6] == "b = 2"


def test_measured_margin_untouched_when_a_measured_line_is_at_column_zero():
    text = "\n".join([" a = 1"] * 5 + ["b = 2"])
    meta = {"spacing": {"calibrated": True, "line_status": ["measured"] * 6}}
    assert analysis._drop_measured_margin([text], [meta]) == [text]
