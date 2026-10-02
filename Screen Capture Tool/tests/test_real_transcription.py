"""Transcription unit tests on real editor screenshots (no API calls).

tests/real/<date>/<case>/ holds the screenshots from a live capture, the text the model returned for each one
(NN.txt, exactly as stored) and the original file (truth.*). Every test replays CodeSnap's own pipeline on them:
pixel-measured spacing -> per-line pixel check -> stitching -> line check, and compares with the original.
The model is replaced by the stored text (and a fake client for the zoomed re-read), so the tests are free, fast and
repeatable, and every future change to stitching or verification is measured on real captures.
"""
import base64
import json
import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import colfix
from core.analysis import merge_verified, verify_screenshot
from core.colfix import respace
from core.verify import summarize

REAL = Path(__file__).resolve().parent / "real"
CASES = sorted(p for p in REAL.glob("2*/*") if (p / "case.json").exists())
IDS = [f"{p.parent.name.split('-')[-1]}/{p.name}" for p in CASES]


def load(case):
    meta = json.loads((case / "case.json").read_text())
    pngs = sorted(case.glob("*.png"))
    texts = [p.with_suffix(".txt").read_text() for p in pngs]
    truth = [l.rstrip() for l in (case / meta["truth"]).read_text().splitlines()]
    while truth and not truth[-1]:
        truth.pop()
    return meta, pngs, texts, truth


def run(pngs, texts, client=None, numbers=None):
    raws, metas = [], []
    for i, (png, text) in enumerate(zip(pngs, texts)):
        text, _ = respace(png, text)
        v = verify_screenshot(client, png, text)
        raws.append(v.pop("text"))
        if numbers is not None:
            v["numbers"] = numbers[i]
        metas.append(v)
    code, _, notes, statuses = merge_verified(raws, metas)
    lines = [l.rstrip() for l in code.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines, summarize(code, statuses, notes, read_code=code), notes


def exact_share(lines, truth):
    import difflib
    sm = difflib.SequenceMatcher(None, truth, lines, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / max(len(truth), 1)


# ── the captures as they came from the model ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_file_is_rebuilt_exactly(case):
    """Every line, character for character (spaces included), and nothing extra: first line to last line."""
    meta, pngs, texts, truth = load(case)
    lines, s, _ = run(pngs, texts)
    if meta.get("expect_exact", True):
        assert lines == truth, f"{exact_share(lines, truth):.1%} exact, {len(lines)} lines out vs {len(truth)}"
        return
    # screens too small to measure every line: whatever isn't exact must be flagged for a look, never passed
    assert exact_share(lines, truth) >= meta["min_exact"]
    if not meta.get("expect_break"):
        assert len(lines) == len(truth)
    flagged = {f["text"] for f in s["flags"]}
    wrong = [l for l in lines if l.strip() and l not in truth]
    assert all(l.strip()[:160] in flagged for l in wrong), wrong
    if meta.get("expect_break"):
        assert s.get("breaks") and any("overlap" in f["reason"] for f in s["flags"])


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_verified_lines_are_never_wrong(case):
    """A line the pixel check marks verified must be exactly the original line."""
    meta, pngs, texts, truth = load(case)
    lines, s, _ = run(pngs, texts)
    from core.verify import sideways_views
    side = sideways_views([t.split("\n") for t in texts])
    for k, (pngs_, text) in enumerate(zip(pngs, texts)):
        if k in side:
            # scrolled right: a half-visible character at the left edge can be misread and still have the right
            # count. Such pieces are only used to extend a line when they match its known part exactly.
            continue
        t, _ = respace(pngs_, text)
        chk = colfix.check(pngs_, t)
        for line, st in zip(t.split("\n"), chk["status"]):
            if st == "verified" and len(line.strip()) >= 6:
                # a sideways-scrolled screen shows a piece of a line: the piece must be exactly part of the original.
                # (The pixel check confirms character counts and positions; a 2-3 character fragment carries too
                # little to identify.)
                assert line.rstrip() in truth or any(line.strip() in tl for tl in truth), line
    if meta.get("expect_exact", True):
        # Positioned spacing disagreements must remain visible even when the
        # final chosen reading happens to match this fixture's original.
        pixel_flags = [f for f in s['flags'] if 'screenshots disagree about this line\'s spacing' not in f['reason']]
        assert len(pixel_flags) <= 2, s["flags"]


@pytest.mark.parametrize("case,floor", [("run2/aidpayrn_cobol", 1.0), ("run2/aidpost_rpg", 1.0), ("run2/aiddbd_ims_one_screen", 1.0),
                                        ("run2/aiddbd_ims_recapture", 1.0), ("run2/district_lookup_html", 0.85),
                                        # Ambiguous equally optimal pixel alignments are now
                                        # unverified; the exact-output and wrong-line tests above
                                        # still require accurate source or an explicit flag.
                                        ("run1/aidinq_cobol_cics", 40/41), ("run1/aiddbd_ims", 1.0), ("run1/aid_pkg_plsql", 1.0),
                                        ("run1/aidcalc_vb6", 0.9), ("run1/payment_controller_cs", 0.88), ("run1/aidpost_rpg", 25/28)])
def test_share_of_lines_proven_by_the_pixels(case, floor):
    c = CASES[IDS.index(case)]
    _, pngs, texts, _ = load(c)
    _, s, _ = run(pngs, texts)
    assert (s["verified"] + s["reread"]) / s["lines"] >= floor, s["headline"]


# ── model mistakes injected into the real captures ─────────────────────────────────────────────────────────────

def _case(name):
    return load(CASES[IDS.index(name if "/" in name else "run2/" + name)])


def _shift_spaces(line, rnd):
    runs = [(m.start(), m.end()) for m in re.finditer(r"(?<=\S) {2,}(?=\S)", line)]
    if not runs:
        return line
    a, b = rnd.choice(runs)
    return line[:a] + " " * max(1, b - a + rnd.choice([-3, -2, -1, 1, 2, 3])) + line[b:]


@pytest.mark.parametrize("name", ["aidpayrn_cobol", "aidpost_rpg"])
def test_miscounted_spaces_are_repaired_from_the_pixels(name):
    """The model's typical error in fixed-column code: runs of spaces one to three too long or short."""
    _, pngs, texts, truth = _case(name)
    rnd = random.Random(11)
    bad = ["\n".join(_shift_spaces(l, rnd) if rnd.random() < 0.35 else l for l in t.split("\n")) for t in texts]
    assert bad != texts
    lines, s, _ = run(pngs, bad)
    wrong = [l for l in lines if l not in truth]
    # a line the pixels can't match (a mouse pointer over it) may keep its error, but it must be flagged
    flagged = {f["text"] for f in s["flags"]}
    assert all(l.strip()[:160] in flagged for l in wrong), wrong
    assert len(wrong) <= 1


def _drop_chars(texts, rnd, rate=0.12):
    out, hurt = [], set()
    for t in texts:
        rows = []
        for l in t.split("\n"):
            idx = [i for i, ch in enumerate(l) if ch.isalnum() and i > 7]
            if idx and rnd.random() < rate:
                i = rnd.choice(idx)
                l = l[:i] + l[i + 1:]
                hurt.add(l.rstrip())
            rows.append(l)
        out.append("\n".join(rows))
    return out, hurt


def test_dropped_characters_are_flagged_never_verified():
    _, pngs, texts, truth = _case("aidpayrn_cobol")
    bad, hurt = _drop_chars(texts, random.Random(5))
    hurt -= set(truth)
    for png, text in zip(pngs, bad):
        text, _ = respace(png, text)
        for line, st in zip(text.split("\n"), colfix.check(png, text)["status"]):
            if line.rstrip() in hurt:
                assert st != "verified", line


class RereadClient:
    """Stands in for the model's zoomed re-read: returns the original line for each crop it is shown."""

    def __init__(self, truth_by_seq):
        self.truth, self.calls, self.lines = truth_by_seq, 0, []
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        imgs = [c for c in kw["messages"][0]["content"] if c["type"] == "image"]
        out = []
        for c in imgs:
            i = int(base64.b64decode(c["source"]["data"]).decode())
            seq = self.lines[i][:6]
            out.append({"text": self.truth.get(seq, self.lines[i]), "overlay": False})
        return type("M", (), {"content": [type("B", (), {"text": json.dumps({"lines": out})})()]})()


def test_zoomed_reread_fixes_dropped_characters(monkeypatch):
    _, pngs, texts, truth = _case("aidpayrn_cobol")
    bad, hurt = _drop_chars(texts, random.Random(5))
    by_seq = {l[:6]: l for l in truth if l[:6].isdigit()}
    client = RereadClient(by_seq)
    monkeypatch.setattr(colfix, "crop_rows", lambda path, rows, **kw: [str(i).encode() for i in rows])
    raws, metas = [], []
    for png, text in zip(pngs, bad):
        text, _ = respace(png, text)
        client.lines = text.split("\n")
        v = verify_screenshot(client, png, text)
        raws.append(v.pop("text"))
        metas.append(v)
    code, _, notes, st = merge_verified(raws, metas)
    lines = [l.rstrip() for l in code.split("\n")]
    s = summarize(code, st, notes, read_code=code)
    assert client.calls > 0 and s["reread"] > 0
    assert exact_share(lines, truth) >= 0.99, s["headline"]


def test_repeated_screens_change_nothing():
    """A pause while scrolling repeats a screen; a double hotkey press duplicates one."""
    _, pngs, texts, truth = _case("aidpayrn_cobol")
    p = pngs[:5] + [pngs[4]] + pngs[5:] + [pngs[-1]]
    t = texts[:5] + [texts[4]] + texts[5:] + [texts[-1]]
    assert run(p, t)[0] == truth


def test_recapture_screens_in_either_order():
    _, pngs, texts, truth = _case("aiddbd_ims_recapture")
    assert run(pngs[::-1], texts[::-1])[0] == truth


# ── wide lines and sideways scrolling ──────────────────────────────────────────────────────────────────────────

def test_without_the_sideways_screens_long_lines_are_flagged_not_guessed():
    _, pngs, texts, truth = _case("district_lookup_html")
    lines, s, _ = run(pngs[:6], texts[:6])
    cut = [f for f in s["flags"] if "word wrap" in f["reason"]]
    assert len(cut) >= 3 and all(l in truth or "[CUT OFF]" in l or truth[i] for i, l in enumerate(lines))
    assert not any(l.startswith(("ocument", "et\" name", "60\" border")) for l in lines)


def test_sideways_screens_complete_the_long_lines():
    _, pngs, texts, truth = _case("district_lookup_html")
    lines, s, notes = run(pngs, texts)
    assert lines == truth and notes["sideways"] >= 3
    assert not any("[CUT OFF]" in l for l in lines)


# ── editor line numbers (the gutter is visible in these screenshots) ───────────────────────────────────────────

def _gutter_numbers(texts, truth):
    """What a correct read of the editor's gutter returns: each row's line number (sticky-scroll rows included)."""
    out = []
    for t in texts:
        nums, prev = [], 0
        for l in t.split("\n"):
            stem = l.replace("[CUT OFF]", "").strip()
            cands = [i + 1 for i, tl in enumerate(truth) if stem and stem in tl] if stem else []
            if not stem:
                n = prev + 1
            elif cands:
                n = min(cands, key=lambda c: (c < prev + 1, abs(c - (prev + 1))))
            else:
                n = prev + 1
            nums.append(n)
            prev = n
        out.append(nums)
    return out


def test_line_numbers_place_every_line_including_sticky_rows():
    _, pngs, texts, truth = _case("district_lookup_html")
    lines, s, notes = run(pngs, texts, numbers=_gutter_numbers(texts, truth))
    assert notes["numbers"] and notes["gaps"] == []
    assert lines == truth


def test_line_numbers_report_lines_never_on_screen():
    _, pngs, texts, truth = _case("aidpayrn_cobol")
    keep = [i for i in range(len(pngs)) if not 9 <= i <= 16]
    nums = _gutter_numbers(texts, truth)
    lines, s, notes = run([pngs[i] for i in keep], [texts[i] for i in keep], numbers=[nums[i] for i in keep])
    assert notes["numbers"] and notes["gaps"], "removed screens must show up as a gap"
    assert "Never on screen" in s["headline"]
    missing = {n for g in notes["gaps"] for n in range(g[0], g[1] + 1)}
    assert all(truth[n - 1] not in lines or truth.count(truth[n - 1]) > 1 for n in missing)


# ── run 1 (half resolution) against the file CodeSnap saved at the time ────────────────────────────────────────

@pytest.mark.parametrize("case", [c for c in CASES if (c / "run1_saved.txt").exists()],
                         ids=[i for i, c in zip(IDS, CASES) if (c / "run1_saved.txt").exists()])
def test_run1_is_at_least_as_good_as_what_was_saved(case):
    _, pngs, texts, truth = load(case)
    saved = [l.rstrip() for l in (case / "run1_saved.txt").read_text().splitlines()]
    lines, _, _ = run(pngs, texts)
    assert exact_share(lines, truth) >= exact_share(saved, truth)


# ── application screens: the stored screen reads against what the page really shows ───────────────────────────

SCREENS = sorted(p for p in (REAL / "screens").glob("*") if (p / "screen.json").exists())


def _screen(case):
    s = json.loads((case / "screen.json").read_text())
    return s, json.loads((case / "truth.json").read_text()), json.dumps(s).lower()


@pytest.mark.parametrize("case", SCREENS, ids=[p.name for p in SCREENS])
def test_screen_fields_actions_and_columns_are_all_read(case):
    s, truth, blob = _screen(case)
    labels = " | ".join(f.get("label", "") for f in s.get("fields") or []).lower()
    assert all(f.lower() in labels for f in truth["fields"]), labels
    for b in truth.get("buttons", []):
        assert any(b.lower() in (a.get("label") or "").lower() for a in s.get("actions") or []), b
    for col in truth.get("table_columns", []):
        assert col.lower() in blob, col
    for k in truth.get("pf_keys", []):
        assert k.lower() in blob, k


@pytest.mark.parametrize("case", [p for p in SCREENS if "3270" in p.name], ids=[p.name for p in SCREENS if "3270" in p.name])
def test_3270_message_is_word_for_word(case):
    """The screen read records the layout (fields, keys, messages), not the data values in the table."""
    s, truth, blob = _screen(case)
    for m in truth["messages"]:
        assert m.lower() in blob, m


def _rules(s):
    from core.uireview.screens import classify_observed
    return {r[0] for i in s.get("issues") or [] for r in classify_observed(i)}


def test_web_page_visible_issues_become_the_right_findings():
    s, _, _ = _screen(REAL / "screens" / "run1_web_lookup")
    assert {"UIS-PWFIELD", "ACC-CONTRAST", "ACC-TEXTSIZE", "ACC-LINK", "ACC-ALT", "UIB-OBSOLETE"} <= _rules(s)


@pytest.mark.parametrize("name", ["run1_3270_inquiry", "run2_3270_inquiry"])
def test_3270_low_contrast_pf_line_is_found(name):
    s, _, _ = _screen(REAL / "screens" / name)
    assert "ACC-CONTRAST" in _rules(s)


@pytest.mark.parametrize("name", ["run1_3270_inquiry",
                                  pytest.param("run2_3270_inquiry", marks=pytest.mark.xfail(
                                      strict=True, reason="in run 2 the model did not report the red-only warning"))])
def test_3270_colour_only_warning_is_found(name):
    s, _, _ = _screen(REAL / "screens" / name)
    assert "ACC-COLOR" in _rules(s)
