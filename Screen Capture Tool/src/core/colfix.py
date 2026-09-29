"""Pixel-measured spacing for fixed-column source (COBOL, RPG, JCL, BMS, IMS/assembler macros).

The vision model reads the words reliably but miscounts runs of spaces, and in these languages the column a word
starts in is part of its meaning. In a monospaced editor screenshot every character occupies one cell of a regular
grid, so the column of each word can be measured from the pixels. This keeps the model's words and replaces only the
spaces between them with the measured ones. The only characters it ever changes are the repeats in separator rules
(------, ======), whose length it also measures. A line is left alone whenever the measurement and the text don't
clearly agree.
"""
import re

import numpy as np
from PIL import Image

MAX_SHIFT = 8          # a measured column this far from the transcribed one means the row was matched wrongly
MIN_GRID_FIT = 0.6     # how well glyph edges must sit on one character grid before we trust it


def _ink(path):
    im = np.asarray(Image.open(path).convert("L")).astype(int)
    return np.abs(im - np.median(im)) > 60


def _decorated(ink, a, b, runs) -> bool:
    """A solid square on the row: an editor colour swatch (CSS colours) or similar inline decoration. It shifts the
    text after it off the character grid, so such a row is never used to judge the transcription."""
    for s, e in runs:
        box = ink[a:b, s:e + 1]
        ys = np.where(box.any(1))[0]
        if not len(ys):
            continue
        h, w = ys[-1] - ys[0] + 1, e - s + 1
        if w >= 5 and h >= 0.5 * (b - a) and 0.6 <= w / h <= 1.6 and box[ys[0]:ys[-1] + 1].mean() >= 0.95:
            return True
    return False


def _rows(ink, min_h=4, max_h=80, join=2, bands_out=None, deco_out=None):
    """Screen rows of text, each as a list of (x_start, x_end) ink runs. Bands split by a hairline gap (an underscore
    or a descender below the letters) are joined back into their row. The (y_start, y_end) of each row is appended to
    bands_out when given."""
    bands, start = [], None
    for y, on in enumerate(list(ink.any(1)) + [False]):
        if on and start is None:
            start = y
        elif not on and start is not None:
            prev_h = bands[-1][1] - bands[-1][0] if bands else 0
            if bands and start - bands[-1][1] <= max(join, prev_h * 0.35) and (y - start < min_h or prev_h < min_h):
                bands[-1] = (bands[-1][0], y)
            else:
                bands.append((start, y))
            start = None
    rows = []
    for a, b in bands:
        if not min_h <= b - a <= max_h:
            continue
        cols = np.where(ink[a:b].any(0))[0]
        runs, s, prev = [], cols[0], cols[0]
        for x in cols[1:]:
            if x - prev > 1:
                runs.append((int(s), int(prev)))
                s = x
            prev = x
        runs.append((int(s), int(prev)))
        rows.append(runs)
        if bands_out is not None:
            bands_out.append((a, b))
        if deco_out is not None:
            deco_out.append(_decorated(ink, a, b, runs))
    return rows


def _grid(rows, lo=4.0, hi=32.0):
    starts = np.array([s for runs in rows for s, _ in runs], float)
    if len(starts) < 20:
        return 0.0, None, None
    best = (0.0, None, None)
    for p in np.arange(lo, hi, 0.02):
        ang = (starts / p) % 1.0 * 2 * np.pi
        c, s = np.cos(ang).mean(), np.sin(ang).mean()
        fit = float(np.hypot(c, s))
        if fit > best[0] + 1e-9:
            best = (fit, float(p), float(np.arctan2(s, c) / (2 * np.pi)) % 1.0)
    return best


def _word_columns(runs, pitch, offset):
    """Start column and width (in character cells) of every word on one screen row. Each run of ink is mapped to the
    character cells it touches; a word ends where at least one whole cell is empty (narrow glyphs like '.' or ')'
    leave wide pixel gaps but never an empty cell)."""
    first = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.25))
    last = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.05))
    words, cur = [], [first(runs[0][0]), last(runs[0][1])]
    for s, e in runs[1:]:
        a, b = first(s), last(e)
        if a > cur[1] + 1:
            words.append(cur)
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    words.append(cur)
    return [(a, b - a + 1) for a, b in words]


def _starts(line):
    out, pos = [], 0
    for w in line.split():
        pos = line.index(w, pos)
        out.append(pos)
        pos += len(w)
    return out


def _same_row(measured, line) -> bool:
    """A screen row matches a line only if it has the same number of words with the same widths (±1 cell: a glyph edge can touch the next cell)."""
    words = line.split()
    return len(words) == len(measured) and all(abs(w - len(t)) <= 1 for (_, w), t in zip(measured, words))


def _align(measured, lines):
    """Monotonic row-to-line matching (longest common subsequence under _same_row), keeping only matches that sit in a
    run of 3+ consecutive rows and lines, so a lone '}' or a gutter-only blank row can't be paired with the wrong line."""
    n, k = len(measured), len(lines)
    ok = [[_same_row(measured[i], lines[j]) for j in range(k)] for i in range(n)]
    L = [[0] * (k + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(k - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if ok[i][j] else max(L[i + 1][j], L[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < k:
        if ok[i][j] and L[i][j] == L[i + 1][j + 1] + 1:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif L[i + 1][j] >= L[i][j + 1]:
            i += 1
        else:
            j += 1
    kept = set()
    for idx in range(len(pairs)):
        run = [pairs[idx]]
        for step in (1, 2):
            if idx + step < len(pairs) and pairs[idx + step] == (pairs[idx][0] + step, pairs[idx][1] + step):
                run.append(pairs[idx + step])
            else:
                break
        if len(run) == 3:
            kept.update(run)
    return sorted(kept)


_RULE = re.compile(r"^(\S{0,8}?)(-|=|\*|_|#|\.)\2{7,}$")


def _anchored(plain, pairset, ri, li) -> bool:
    """A line with letters or digits identifies its screen row. A lone '}' or ');' matches every such row, so it is
    trusted only when both neighbours are matched to the neighbouring rows and one of them has letters or digits;
    otherwise the pixels never move it and a disagreement is not reported as an error."""
    if any(ch.isalnum() for ch in plain[li]):
        return True
    nb = [(ri - 1, li - 1), (ri + 1, li + 1)]
    return all(p in pairset for p in nb) and any(0 <= l < len(plain) and any(ch.isalnum() for ch in plain[l]) for _, l in nb)


def _measured_word(word, width):
    """Separator rules (------, ======, ******) are where the model miscounts characters; there the pixels decide."""
    m = _RULE.match(word)
    if m and 0 < abs(width - len(word)) <= 2:
        return m.group(1) + m.group(2) * (width - len(m.group(1)))
    return word


def _rebuild(line, cols, widths=None):
    out = ""
    for i, (w, c) in enumerate(zip(line.split(), cols)):
        w = _measured_word(w, widths[i]) if widths else w
        c = max(c, len(out) + (1 if out else 0))
        out += " " * (c - len(out)) + w
    return out


def _measure(image_path, text: str):
    """Match the screenshot's text rows to the transcribed lines. Returns None when the screenshot has no usable
    fixed-width character grid (proportional font, a photo, too little text); every check then says "unchecked"."""
    lines = text.split("\n")
    body = [(i, l) for i, l in enumerate(lines) if l.strip() and "[CUT OFF]" not in l]
    if not body:
        return None
    try:
        ink = _ink(image_path)
        bands, deco = [], []
        rows = _rows(ink, bands_out=bands, deco_out=deco)
        fit, pitch, offset = _grid(rows)
    except Exception:  # noqa: BLE001 - measurement is an extra; never let it break a transcription
        return None
    if pitch is None or fit < MIN_GRID_FIT:
        return None
    measured = [_word_columns(r, pitch, offset) for r in rows]
    plain = [l for _, l in body]
    left = min(m[0][0] for m in measured)
    right = left + max(len(l) for l in plain) + 4          # anything further right is a scrollbar or minimap
    measured = [[w for w in m if w[0] <= right] or m[:1] for m in measured]
    variants = [(measured, list(range(len(measured))))]
    # editor line numbers are one extra word per row; a row holding only a line number (a blank source line) is dropped
    multi = [m for m in measured if len(m) > 1]
    if multi:
        ends = [m[0][0] + m[0][1] for m in multi]
        g_end = max(set(ends), key=ends.count)
        keep = [i for i, m in enumerate(measured) if not (len(m) == 1 and m[0][0] + m[0][1] == g_end)]
        variants.append(([measured[i][1:] if len(measured[i]) > 1 else measured[i] for i in keep], keep))
    best = max(((_align(m, plain), m, idx) for m, idx in variants), key=lambda v: len(v[0]))
    pairs, measured, idx = best
    if len(pairs) < max(3, min(len(plain), len(measured)) // 3):
        return None
    votes = {}
    for ri, li in pairs:
        d = _starts(plain[li])[0] - measured[ri][0][0]
        votes[d] = votes.get(d, 0) + 1
    base = max(votes, key=votes.get)
    return {"lines": lines, "body": body, "plain": plain, "measured": measured, "pairs": pairs, "base": base,
            "bands": [bands[i] for i in idx], "deco": [deco[i] for i in idx], "pitch": pitch, "offset": offset,
            "x0": int(max(0, (min(m[0][0] for m in measured) + offset - 1) * pitch))}


def respace(image_path, text: str) -> tuple:
    """Return (text with measured spacing, number of lines changed) for one screenshot's transcription."""
    m = _measure(image_path, text)
    if m is None:
        return text, 0
    lines, body, plain, measured, base = m["lines"], m["body"], m["plain"], m["measured"], m["base"]
    changed = 0
    pairset = set(m["pairs"])
    for ri, li in m["pairs"]:
        if m["deco"][ri] or not _anchored(plain, pairset, ri, li):
            continue
        cols = [c + base for c, _ in measured[ri]]
        if any(abs(a - b) > MAX_SHIFT for a, b in zip(_starts(plain[li]), cols)):
            continue
        new = _rebuild(plain[li], cols, [w for _, w in measured[ri]])
        same_words = all(a == b or _RULE.match(a) for a, b in zip(new.split(), plain[li].split()))
        if new != plain[li] and same_words and len(new.split()) == len(plain[li].split()):
            lines[body[li][0]] = new
            changed += 1
    return "\n".join(lines), changed


# ── verification: does every word have the character count the pixels show? ─────────────────────────────────────

VERIFIED, MISMATCH, UNCHECKED, CUT = "verified", "mismatch", "unchecked", "cut"


def _exact(meas, line, base) -> bool:
    words = line.split()
    return (len(words) == len(meas) and all(w == len(t) for (_, w), t in zip(meas, words))
            and _starts(line) == [c + base for c, _ in meas])


def _plausible(meas, line, base) -> bool:
    """The row and the line are the same line of code if at least half the words sit at the same column with the same
    width (the rest is where the model dropped or added a character)."""
    got = {(s, len(t)) for s, t in zip(_starts(line), line.split())}
    hits = sum(1 for c, w in meas if (c + base, w) in got)
    return hits >= max(1, (max(len(meas), len(line.split())) + 1) // 2)


def check(image_path, text: str) -> dict:
    """Per line of `text`: "verified" (every word's length and column agree with the pixels), "mismatch" (the matching
    screen row shows a different character count: a character was dropped or added), "cut" (cut off at the screen
    edge) or "unchecked" (no fixed-width grid, or the row couldn't be matched). Blank lines get "".
    Also returns the screen rows of the mismatched lines, for a zoomed re-read."""
    lines = text.split("\n")
    status = ["" if not l.strip() else CUT if "[CUT OFF]" in l else UNCHECKED for l in lines]
    m = _measure(image_path, text)
    if m is None:
        return {"grid": False, "status": status, "rows": {}}
    body, plain, measured, base, pairs = m["body"], m["plain"], m["measured"], m["base"], m["pairs"]
    mapping, paired, between = {}, set(), set()
    for ri, li in pairs:
        mapping[li] = ri
        paired.add(li)
    # lines between two matched rows, when the counts agree, are the rows in between
    for (r1, l1), (r2, l2) in zip(pairs, pairs[1:]):
        if r2 - r1 == l2 - l1 > 1:
            for k in range(1, r2 - r1):
                mapping[l1 + k] = r1 + k
                between.add(l1 + k)
    if pairs:                                   # and the few rows above the first / below the last match
        r0, l0 = pairs[0]
        for k in range(1, min(r0, l0, 2) + 1):
            mapping[l0 - k] = r0 - k
        r9, l9 = pairs[-1]
        for k in range(1, min(len(measured) - 1 - r9, len(plain) - 1 - l9, 2) + 1):
            mapping[l9 + k] = r9 + k
    rows = {}
    for li, ri in mapping.items():
        meas, line = measured[ri], plain[li]
        if _exact(meas, line, base):
            st = VERIFIED
        elif m["deco"][ri] or not _anchored(plain, set(pairs), ri, li):
            continue                        # a colour swatch, or a lone brace that any brace row would match
        elif li in paired or li in between or _plausible(meas, line, base):
            st = MISMATCH
            rows[body[li][0]] = {"band": m["bands"][ri], "cols": [c + base for c, _ in meas],
                                 "widths": [w for _, w in meas]}
        else:
            continue
        status[body[li][0]] = st
    return {"grid": True, "status": status, "rows": rows, "x0": m["x0"], "pitch": m["pitch"]}


def accept_reread(line: str, row: dict):
    """A re-read of a mismatched line is accepted only if its words now have exactly the widths the pixels show; the
    spacing is then taken from the pixels. Returns the corrected line or None."""
    words = line.replace("[CUT OFF]", "").split()
    if len(words) != len(row["widths"]) or any(len(w) != n for w, n in zip(words, row["widths"])):
        return None
    return _rebuild(" ".join(words), row["cols"])


def crop_rows(image_path, rows: dict, x0: int = 0, pad: float = 0.35, min_char: int = 14, pitch: float = 10.0):
    """Zoomed crops (PNG bytes) of the given screen rows, in the order of `rows`."""
    import io
    im = Image.open(image_path).convert("RGB")
    scale = max(1.0, min(4.0, min_char / max(pitch, 1.0)))
    out = []
    for row in rows.values():
        y0, y1 = row["band"]
        h = y1 - y0
        box = (max(0, x0), max(0, int(y0 - h * pad)), im.width, min(im.height, int(y1 + h * pad)))
        c = im.crop(box)
        if scale > 1:
            c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        c.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out
