import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.colfix import respace  # noqa: E402
from render import render_code  # noqa: E402

S = HERE / "samples"
FIXED = ["cobol/AIDCALC.cbl", "cobol/AIDINQ.cbl", "cobol/AIDJOB.jcl", "langpacks/AIDPOST.rpgle", "langpacks/AIDDBD.dbd",
         "langpacks/AIDEDIT.asm"]
FREE = ["legacy/AidPaymentController.cs", "legacy/AidLookupServlet.java", "langpacks/aid_merge.py"]


def _corrupt(line, rnd):
    runs = [(m.start(), m.end()) for m in re.finditer(r"(?<=\S) {2,}(?=\S)|^ +(?=\S)", line)]
    if not runs:
        return line
    a, b = rnd.choice(runs)
    return line[:a] + " " * max(1 if a else 0, b - a + rnd.choice([-2, -1, 1, 2])) + line[b:]


def _run(rel, tmp_path, **style):
    rnd = random.Random(1)
    truth = [l.rstrip() for l in (S / rel).read_text().splitlines()][:40]
    png = render_code("\n".join(truth), tmp_path / "x.png", **style)
    clean, _ = respace(png, "\n".join(truth))
    bad = [_corrupt(l, rnd) if l.strip() and rnd.random() < 0.5 else l for l in truth]
    fixed, _ = respace(png, "\n".join(bad))
    fl = fixed.split("\n")
    body = [i for i, t in enumerate(truth) if t.strip()]
    return (clean.split("\n") == truth, sum(bad[i] == truth[i] for i in body), sum(fl[i] == truth[i] for i in body),
            sum(1 for i in body if bad[i] == truth[i] and fl[i] != truth[i]), len(body))


def test_measured_spacing_fixes_fixed_column_code(tmp_path):
    for rel in FIXED:
        for style in ({"font_size": 16}, {"font_size": 12, "line_numbers": True, "bg": (255, 255, 255), "fg": (20, 20, 20)}):
            untouched, before, after, broke, n = _run(rel, tmp_path, **style)
            assert untouched and broke == 0, (rel, style)
            assert after >= before and after >= 0.8 * n, (rel, style, before, after, n)


def test_free_form_code_is_never_damaged(tmp_path):
    for rel in FREE:
        untouched, before, after, broke, n = _run(rel, tmp_path, font_size=15)
        assert untouched and broke == 0 and after >= before, rel


def test_proportional_or_blank_image_is_left_alone(tmp_path):
    from PIL import Image, ImageDraw
    p = tmp_path / "blank.png"
    Image.new("RGB", (400, 200), "white").save(p)
    assert respace(p, "000100 IDENTIFICATION DIVISION.") == ("000100 IDENTIFICATION DIVISION.", 0)
    q = tmp_path / "prop.png"
    im = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(im).text((10, 10), "Wide WWW words and thin iii ones", fill="black")
    im.save(q)
    assert respace(q, "Wide   WWW words and thin iii ones")[0] in ("Wide   WWW words and thin iii ones",
                                                                  "Wide WWW words and thin iii ones")


def test_cut_off_lines_untouched(tmp_path):
    truth = (S / "cobol/AIDCALC.cbl").read_text().splitlines()[:20]
    png = render_code("\n".join(truth), tmp_path / "x.png", font_size=16)
    text = "\n".join(truth[:-1] + [truth[-1][:20] + " [CUT OFF]"])
    assert respace(png, text)[0].splitlines()[-1] == truth[-1][:20] + " [CUT OFF]"
