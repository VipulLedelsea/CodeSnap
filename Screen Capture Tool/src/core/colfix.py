"""Pixel-measured spacing for fixed-column source (COBOL, RPG, JCL, BMS, IMS/assembler macros).

The vision model reads the words reliably but miscounts runs of spaces, and in these languages the column a word
starts in is part of its meaning. In a monospaced editor screenshot every character occupies one cell of a regular
grid, so the column of each word can be measured from the pixels. This keeps the model's words and replaces only the
spaces between them with the measured ones. The only characters it ever changes are the repeats in separator rules
(------, ======), whose length it also measures. A line is left alone whenever the measurement and the text don't
clearly agree.
"""
import difflib as _difflib
import re

import numpy as np
from PIL import Image

MAX_SHIFT = 8          # a measured column this far from the transcribed one means the row was matched wrongly
RULE_SLACK = 16        # the model miscounts the characters of a long divider; the pixels may correct it by this many
MIN_GRID_FIT = 0.6     # how well glyph edges must sit on one character grid before we trust it


def _line_pitch(ink):
    """The distance from one text row to the next, from the rows' tops, or None when there are too few rows to tell."""
    on = np.concatenate([[False], ink.any(1), [False]])
    edges = np.flatnonzero(on[1:] != on[:-1])
    bands = [(a, b) for a, b in zip(edges[::2], edges[1::2]) if 8 <= b - a <= 45]
    if len(bands) < 4:
        return None
    return float(np.median(np.diff([a for a, _ in bands])))


def _drop_guides(ink, min_h=None, max_w=3):
    """Remove the editor's indent guides: thin vertical lines (one to three pixels wide, the active guide is drawn heavier)
    that run through several rows of text. They are ink to the threshold below, so every guided row would start at the guide
    instead of at its first character, and rows fuse into one band and cannot be matched to their text. A glyph stroke is one
    row tall; the line a guide draws is many rows tall and has no ink beside it, which is how the two are told apart."""
    if min_h is None:
        # Long guides go first, so the rows can be told apart and the line pitch measured; a guide beside a short block (one
        # row of body under an IF) is only as tall as one row of the screen, which is still taller than any glyph: a stroke
        # such as '|' stops short of the next row, a guide runs through the gap.
        first = _drop_guides(ink, min_h=60, max_w=max_w)
        pitch = _line_pitch(first)
        return _drop_guides(first, min_h=max(24, int(0.9 * pitch)), max_w=max_w) if pitch else first
    out = ink.copy()
    h, w = ink.shape
    long_runs = {}                                           # column -> [(top, bottom)] runs of at least min_h
    for x in np.where(ink.sum(0) >= min_h)[0]:
        ys = np.where(ink[:, x])[0]
        for run in np.split(ys, np.where(np.diff(ys) > 2)[0] + 1):   # a gap of one or two pixels does not end a run
            if run[-1] - run[0] + 1 >= min_h and len(run) >= 0.9 * (run[-1] - run[0] + 1):
                long_runs.setdefault(int(x), []).append((int(run[0]), int(run[-1])))
    done = set()
    for x in sorted(long_runs):
        for top, bottom in long_runs[x]:
            if (x, top) in done:
                continue
            group = [x]                                      # the neighbouring columns that share this run
            while len(group) < max_w + 1 and any(abs(t - top) <= 4 and abs(b - bottom) <= 4 for t, b in long_runs.get(group[-1] + 1, [])):
                group.append(group[-1] + 1)
            if len(group) > max_w:
                continue                                     # wider than a guide: a scrollbar, border or block of text
            span = slice(top, bottom + 1)
            outside = [ink[span, nx].mean() for nx in (group[0] - 1, group[-1] + 1) if 0 <= nx < w]
            if all(o < 0.5 for o in outside):
                for gx in group:
                    out[span, gx] = False
                    done.add((gx, top))
    return out


def _drop_squiggles(rgb, ink, min_w=16, min_h=3, max_h=9):
    """Remove the editor's wavy diagnostic underlines: red ink in a long, flat but not straight band (a few pixels tall, many
    times wider). Drawn under a flagged row they fuse that row with the one below and start at column one of the row, so the
    first word seems to begin at the margin and the screenshot has no usable character grid. A letter is far narrower; a
    divider drawn in red is straight (one or two pixels tall), which is how the two are told apart."""
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    # the anti-aliased edge of a squiggle is fainter than the ink threshold, so the line looks broken when only ink is
    # counted; red-dominant pixels a little above the background are counted for finding it, only ink is removed
    gray = (299 * r + 587 * g + 114 * b) // 1000
    faint = np.abs(gray - np.median(gray)) > 25
    red = (r > 90) & (r - g > 35) & (r - b > 35) & (ink | faint)
    if not red.any():
        return ink
    h, w = red.shape
    parent, boxes = {}, {}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    prev = []
    for y in np.where(red.any(1))[0]:
        xs = np.where(red[y])[0]
        runs = [(int(r[0]), int(r[-1])) for r in np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)]
        cur = []
        for a, b in runs:
            key = (int(y), a)
            parent[key] = key
            boxes[key] = [a, b, int(y), int(y)]
            for pa, pb, pk, py in prev:
                if py == y - 1 and pa <= b + 1 and a <= pb + 1:
                    ra, rb = find(key), find(pk)
                    if ra != rb:
                        parent[rb] = ra
                        x0, x1, y0, y1 = boxes[rb]
                        bx = boxes[ra]
                        boxes[ra] = [min(bx[0], x0), max(bx[1], x1), min(bx[2], y0), max(bx[3], y1)]
            cur.append((a, b, key, int(y)))
        prev = cur
    out = ink.copy()
    seen = set()
    for key in parent:
        root = find(key)
        if root in seen:
            continue
        seen.add(root)
        x0, x1, y0, y1 = boxes[root]
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if bw >= min_w and min_h <= bh <= max_h and bw >= 3 * bh:
            # a squiggle is one unbroken line that rises and falls; letters leave gaps between glyphs, and a divider is flat
            sub = red[y0:y1 + 1, x0:x1 + 1]
            covered = sub.any(0)
            centres = [np.where(sub[:, c])[0].mean() for c in np.where(covered)[0]]
            if covered.mean() >= 0.9 and np.std(centres) >= 0.8 and sub.sum(0).max() <= 7:
                out[y0:y1 + 1, x0:x1 + 1] &= ~red[y0:y1 + 1, x0:x1 + 1]
        elif bw >= 40 and max_h < bh <= 3 * max_h and bw >= 6 * bh:
            # an underline that touches red text above it is one component with the text; the squiggle is its bottom few rows,
            # an unbroken wavy band, while the text above leaves gaps
            sub = red[y0:y1 + 1, x0:x1 + 1]
            band = sub[-(max_h - 2):]
            covered = band.any(0)
            centres = [np.where(band[:, c])[0].mean() for c in np.where(covered)[0]]
            if covered.mean() >= 0.9 and np.std(centres) >= 0.7 and band.sum(0).max() <= max_h - 2:
                lo = y1 - (max_h - 2) + 1
                out[lo:y1 + 1, x0:x1 + 1] &= ~red[lo:y1 + 1, x0:x1 + 1]
    return out


def _ink(path, squiggles=True):
    pic = Image.open(path)
    im = np.asarray(pic.convert("L")).astype(int)
    ink = np.abs(im - np.median(im)) > 60
    if not squiggles:
        return _drop_guides(ink)
    return _drop_guides(_drop_squiggles(np.asarray(pic.convert("RGB")).astype(int), ink))


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
    tall = sorted(b - a for a, b in bands if b - a >= 10)
    typical = tall[len(tall) // 2] if tall else 0
    for n, (a, b) in enumerate(bands):
        if not min_h <= b - a <= max_h:
            continue
        # A wavy diagnostic underline (editors draw one under code they flag) is a short band right under its row. Read as a row
        # of its own it doubles the row count and the screenshot can no longer be matched to its text.
        if (typical and n and b - a <= 0.45 * typical and a - bands[n - 1][1] <= 6
                and bands[n - 1][1] - bands[n - 1][0] >= 10):
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


def _word_joined(runs, pitch, offset):
    """For each word of `_word_columns`, whether its ink is one unbroken run. Box-drawing dashes ('──────') touch their
    neighbours, so a banner rule is a single run; hyphens and em dashes leave a gap between characters."""
    first = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.25))
    last = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.05))
    counts, end = [1], last(runs[0][1])
    for s, e in runs[1:]:
        a, b = first(s), last(e)
        if a > end + 1:
            counts.append(1)
            end = b
        else:
            counts[-1] += 1
            end = max(end, b)
    return [n == 1 for n in counts]


def _word_thin(runs, pitch, offset):
    """For each word of `_word_columns`, whether it is a hairline: one ink run no wider than a third of a character. That is the
    stub of an indent guide the guide filter left behind, not a glyph."""
    first = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.25))
    last = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.05))
    groups, end = [[runs[0]]], last(runs[0][1])
    for s_, e_ in runs[1:]:
        a, b = first(s_), last(e_)
        if a > end + 1:
            groups.append([(s_, e_)])
            end = b
        else:
            groups[-1].append((s_, e_))
            end = max(end, b)
    return [len(g) == 1 and g[0][1] - g[0][0] + 1 <= 0.34 * pitch for g in groups]


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
    # Word widths alone cannot distinguish adjacent similarly shaped statements.
    # Accept a chosen pair only if every optimal alignment gives it the same
    # measured columns. Otherwise a shifted OCR row could inherit its neighbour.
    prefix = [[0] * (k + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(k):
            prefix[i + 1][j + 1] = (prefix[i][j] + 1 if ok[i][j]
                                    else max(prefix[i][j + 1], prefix[i + 1][j]))
    options = [set() for _ in range(k)]
    for i in range(n):
        for j in range(k):
            if ok[i][j] and prefix[i][j] + 1 + L[i + 1][j + 1] == L[0][0]:
                options[j].add(tuple(measured[i]))
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
    return sorted((i, j) for i, j in kept if len(options[j]) == 1)


_RULE = re.compile(r"^(\S{0,8}?)(-|=|\*|_|#|\.)\2{7,}$")


def _rule_only(line) -> bool:
    """A separator line: a comment marker or nothing, then a run of one rule character (# -----, ======, /*****)."""
    words = line.split()
    return bool(words) and any(_RULE.match(w) for w in words) and all(_RULE.match(w) or len(w) <= 2 for w in words)


def _anchored(plain, pairset, ri, li) -> bool:
    """A line with letters or digits identifies its screen row. A lone '}' or ');' matches every such row, so it is
    trusted only when both neighbours are matched to the neighbouring rows and one of them has letters or digits;
    otherwise the pixels never move it and a disagreement is not reported as an error."""
    if any(ch.isalnum() for ch in plain[li]):
        return True
    nb = [(ri - 1, li - 1), (ri + 1, li + 1)]
    if _rule_only(plain[li]) and any(p in pairset for p in nb):
        return True                             # a divider is found by its place between matched neighbours; only its length is corrected
    return all(p in pairset for p in nb) and any(0 <= l < len(plain) and any(ch.isalnum() for ch in plain[l]) for _, l in nb)


def _joined_of(m, ri):
    rows = m.get("joined")
    return rows[ri] if rows and ri < len(rows) else [False] * 400


_DASHES = re.compile(r"^[-\u2013\u2014\u2500]{2,}$")
# a divider's dashes as the reader wrote them: the box-drawing dash of two or more cells is often read as one em dash
_DASH_WORD = re.compile(r"^[-\u2013\u2014\u2500]+$")


def _titled_divider(line, row, joined) -> bool:
    """A comment divider with a title ("# ── Web framework ────"): the pixel row has the same number of words, every word that is
    not a run of dashes has exactly the width the row shows, and every dash run is one unbroken line (the box-drawing dash). Only
    the dashes' kind and length were uncertain, and the pixels settle both."""
    words = line.split()
    if len(words) != len(row) or len(words) < 3 or not re.match(r"^\s*(#|//|--|;)", line):
        return False
    dashes = [i for i, t in enumerate(words) if _DASH_WORD.match(t) and i > 0]
    if not dashes or not all(i < len(joined) and joined[i] for i in dashes):
        return False
    return all(w == len(t) for i, ((_, w), t) in enumerate(zip(row, words)) if i not in dashes)


def _measured_word(word, width, joined=False):
    """Separator rules (------, ======, ******) are where the model miscounts characters; there the pixels decide. A run of
    dashes whose ink is one unbroken line is the box-drawing dash, which a reader tends to take for a hyphen or an em dash;
    its length is the number of cells it covers."""
    if joined and width >= 2 and _DASH_WORD.match(word):
        return "\u2500" * width
    m = _RULE.match(word)
    if m and 0 < abs(width - len(word)) <= RULE_SLACK:
        return m.group(1) + m.group(2) * (width - len(m.group(1)))
    return word


def _rebuild(line, cols, widths=None, joined=None):
    out = ""
    for i, (w, c) in enumerate(zip(line.split(), cols)):
        w = _measured_word(w, widths[i], bool(joined and joined[i])) if widths else w
        c = max(c, len(out) + (1 if out else 0))
        out += " " * (c - len(out)) + w
    return out


def _measure(image_path, text: str, *, source_x=None):
    """Measure the screenshot with its red squiggles taken out and, when it has any, with them left in; keep the reading that
    pairs more rows with their text. Taking a squiggle out can also cut an indent guide into pieces the guide filter then
    misses, so neither choice is right for every theme and the text decides."""
    try:
        clean, plain = _ink(image_path), _ink(image_path, squiggles=False)
    except Exception:  # noqa: BLE001
        return _measure_with(image_path, text, source_x, None)
    first = _measure_with(image_path, text, source_x, clean)
    if np.array_equal(clean, plain):
        return first
    second = _measure_with(image_path, text, source_x, plain)
    if first is None or second is None:
        return first if second is None else second
    if source_x is not None and first.get("absolute_columns") and second.get("absolute_columns"):
        lines = text.split("\n")
        a, b = _offset_consistency(first, lines), _offset_consistency(second, lines)
        if a != b:
            return first if a > b else second
    return first if len(first["pairs"]) > len(second["pairs"]) else second


def _measure_with(image_path, text: str, source_x, ink):
    """Match the screenshot's text rows to the transcribed lines. Returns None when the screenshot has no usable
    fixed-width character grid (proportional font, a photo, too little text); every check then says "unchecked"."""
    lines = text.split("\n")
    body = [(i, l) for i, l in enumerate(lines) if l.strip() and "[CUT OFF]" not in l]
    if not body:
        return None
    try:
        ink = _ink(image_path) if ink is None else ink
        bands, deco = [], []
        rows = _rows(ink, bands_out=bands, deco_out=deco)
        fit, pitch, offset = _grid(rows)
    except Exception:  # noqa: BLE001 - measurement is an extra; never let it break a transcription
        return None
    if pitch is None or fit < MIN_GRID_FIT:
        return None
    measured = [_word_columns(r, pitch, offset) for r in rows]
    joined = [_word_joined(r, pitch, offset) for r in rows]
    thin = [_word_thin(r, pitch, offset) for r in rows]
    plain = [l for _, l in body]
    left = min(m[0][0] for m in measured)
    right = left + max(len(l) for l in plain) + 4          # anything further right is a scrollbar or minimap
    cut_to = [len([w for w in m if w[0] <= right]) or 1 for m in measured]
    joined = [j[:n] for j, n in zip(joined, cut_to)]
    thin = [t[:n] for t, n in zip(thin, cut_to)]
    measured = [[w for w in m if w[0] <= right] or m[:1] for m in measured]
    # An indent guide the filter cut into pieces leaves a hairline stub before the first word of a row. It is not text, and it
    # makes the row's word count disagree with its line's. A real hairline glyph (the '|' of an F# match) is text, so both
    # readings are tried and the one that pairs more rows with their lines is kept; a tie keeps the rows as drawn.
    stripped, joined_s, thin_s = [list(m) for m in measured], [list(j) for j in joined], [list(t) for t in thin]
    for r in range(len(stripped)):
        while len(stripped[r]) > 1 and thin_s[r][0] and stripped[r][1][0] - stripped[r][0][0] >= 3:
            del stripped[r][0], joined_s[r][0], thin_s[r][0]
    variants = []
    for rows_m, rows_j, rows_t in ((measured, joined, thin), (stripped, joined_s, thin_s)):
        if variants and rows_m == measured:
            continue
        variants.append((rows_m, list(range(len(rows_m))), rows_j, rows_t, False))
        # editor line numbers are one extra word per row; a row holding only a line number (a blank source line) is dropped
        multi = [m for m in rows_m if len(m) > 1]
        if multi:
            ends = [m[0][0] + m[0][1] for m in multi]
            g_end = max(set(ends), key=ends.count)
            gutter = (ends.count(g_end) >= 0.7 * len(ends) and
                      all(m[0][1] <= 6 and m[1][0] > g_end for m in multi))
            if gutter:
                keep = [i for i, m in enumerate(rows_m) if not (len(m) == 1 and m[0][0] + m[0][1] == g_end)]
                variants.append(([rows_m[i][1:] if len(rows_m[i]) > 1 else rows_m[i] for i in keep], keep, rows_j, rows_t, True))
    best = max(((_align(v[0], plain), v) for v in variants), key=lambda x: len(x[0]))
    pairs, (measured, idx, rows_j, rows_t, gutter_used) = best
    joined = [rows_j[i][1:] if gutter_used and len(rows_j[i]) > 1 else rows_j[i] for i in idx]
    thin = [rows_t[i][1:] if gutter_used and len(rows_t[i]) > 1 else rows_t[i] for i in idx]
    if len(pairs) < max(3, min(len(plain), len(measured)) // 3):
        return None
    votes = {}
    for ri, li in pairs:
        d = _starts(plain[li])[0] - measured[ri][0][0]
        votes[d] = votes.get(d, 0) + 1
    base = max(votes, key=votes.get)
    # Relative word geometry alone cannot identify source column one. A whole
    # frame shifted by four spaces casts the same unanimous but wrong vote.
    # Only an independently reviewed, fully visible column-one pixel position
    # may replace this estimate; never infer it from the first visible word.
    if source_x is not None:
        if not isinstance(source_x, (int, float)) or not np.isfinite(source_x) or not 0 <= source_x < ink.shape[1]:
            raise ValueError("source_x must be the visible source column-one position inside the image")
        base = -int(round(source_x / pitch - offset))
    return {"lines": lines, "body": body, "plain": plain, "measured": measured, "pairs": pairs, "base": base, "joined": joined, "thin": thin,
            "absolute_columns": source_x is not None,
            "bands": [bands[i] for i in idx], "deco": [deco[i] for i in idx], "pitch": pitch, "offset": offset,
            "x0": int(max(0, (min(m[0][0] for m in measured) + offset - 1) * pitch))}


def respace(image_path, text: str, *, source_x=None) -> tuple:
    """Return measured spacing and changed count. Optional source_x is a reviewed
    column-one pixel position, valid only with no horizontal source clipping.
    Without it, whole-frame indentation remains relative to the transcription.
    """
    m = _measure(image_path, text, source_x=source_x) if source_x is not None else _measure(image_path, text)
    if m is None:
        return text, 0
    lines, body, plain, measured, base = m["lines"], m["body"], m["plain"], m["measured"], m["base"]
    changed = 0
    from core.text import literal_continuations
    protected = literal_continuations(text)
    pairset = set(m["pairs"])
    for ri, li in m["pairs"]:
        if body[li][0] in protected or '\t' in plain[li] or m["deco"][ri] or not _anchored(plain, pairset, ri, li):
            continue
        cols = [c + base for c, _ in measured[ri]]
        shifts = {a - b for a, b in zip(_starts(plain[li]), cols)}
        # A far-off column usually means the row was matched to the wrong line. The exception is a row whose every word is off by
        # the same amount, on a screenshot whose column one is known: the words and the gaps between them are right and only the
        # leading indentation was misread, so the pixels decide it.
        uniform = m["absolute_columns"] and len(shifts) == 1 and min(cols) >= 0
        if not uniform and any(abs(s) > MAX_SHIFT for s in shifts):
            continue
        new = _rebuild(plain[li], cols, [w for _, w in measured[ri]], _joined_of(m, ri))
        from core.text import normalized_line
        if any(quote in plain[li] for quote in ("'", '"', '`')) and normalized_line(new) != normalized_line(plain[li]):
            continue  # Word geometry cannot justify silently changing a literal value.
        same_words = all(a == b or _RULE.match(a) or (_DASHES.match(a) and _DASHES.match(b))
                         for a, b in zip(new.split(), plain[li].split()))
        if new != plain[li] and same_words and len(new.split()) == len(plain[li].split()):
            lines[body[li][0]] = new
            changed += 1
    # Rows between two matched rows with equal counts sit on known screen rows even though no 3-row run anchored them. Such a
    # row is placed by the pixels when it is a divider (its dash count may have been misread, so only its shape must match) or
    # when every word has exactly the width the row shows, so only the leading spaces and gaps were uncertain.
    candidates = []
    for (r1, l1), (r2, l2) in zip(m["pairs"], m["pairs"][1:]):
        if r2 - r1 == l2 - l1 > 1:
            candidates += [(r1 + k, l1 + k, False) for k in range(1, r2 - r1)]
    if m["pairs"]:                                  # the few rows above the first and below the last matched row line up the same way,
        r0, l0 = m["pairs"][0]                      # but only dividers are rewritten there: nothing anchors an ordinary row's column
        candidates += [(r0 - k, l0 - k, True) for k in range(1, min(r0, l0, 3) + 1)]
        r9, l9 = m["pairs"][-1]
        candidates += [(r9 + k, l9 + k, True) for k in range(1, min(len(measured) - 1 - r9, len(plain) - 1 - l9, 3) + 1)]
    for ri, li, dividers_only in candidates:
        if True:
            line = plain[li]
            if (m["deco"][ri] or body[li][0] in protected or "\t" in line or len(measured[ri]) != len(line.split())):
                continue
            rule = _rule_only(line) or _titled_divider(line, measured[ri], _joined_of(m, ri))
            exact = all(w == len(t) or (_DASHES.match(t) and _joined_of(m, ri)[i]) for i, ((_, w), t) in enumerate(zip(measured[ri], line.split())))
            if not (rule or (exact and not dividers_only and _anchored(plain, pairset, ri, li) and m["absolute_columns"])):
                continue
            cols = [c + base for c, _ in measured[ri]]
            if min(cols) < 0:
                continue
            new = _rebuild(line, cols, [w for _, w in measured[ri]], _joined_of(m, ri))
            if dividers_only:       # nothing anchors this row's column, so only its dashes are taken from the pixels
                new = line[:len(line) - len(line.lstrip())] + new.lstrip()
            from core.text import normalized_line
            if normalized_line(new) != normalized_line(line) and not rule and not all(
                    a == b or (_DASH_WORD.match(a) and _DASH_WORD.match(b)) for a, b in zip(new.split(), line.split())):
                continue
            if new != line and len(new.split()) == len(line.split()):
                lines[body[li][0]] = new
                changed += 1
    return "\n".join(lines), changed


# ── verification: does every word have the character count the pixels show? ─────────────────────────────────────

VERIFIED, MISMATCH, UNCHECKED, CUT, ROWS = "verified", "mismatch", "unchecked", "cut", "rows"


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


def check(image_path, text: str, *, source_x=None) -> dict:
    """Per line of `text`: "verified" (every word's length and column agree with the pixels), "mismatch" (the matching
    screen row shows a different character count: a character was dropped or added), "cut" (cut off at the screen
    edge) or "unchecked" (no fixed-width grid, or the row couldn't be matched). Blank lines get "".
    Also returns the screen rows of the mismatched lines, for a zoomed re-read."""
    lines = text.split("\n")
    status = ["" if not l.strip() else CUT if "[CUT OFF]" in l else UNCHECKED for l in lines]
    m = _measure(image_path, text, source_x=source_x) if source_x is not None else _measure(image_path, text)
    if m is None:
        return {"grid": False, "status": status, "rows": {}, "absolute_columns": False}
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
    heights = [b[1] - b[0] for b in m["bands"]]
    med = sorted(heights)[len(heights) // 2] if heights else 0
    centre = [(b[0] + b[1]) / 2 for b in m["bands"]]
    gaps = sorted(b - a for a, b in zip(centre, centre[1:]))
    step = gaps[len(gaps) // 2] if gaps else 1
    left_max = max((len(l) - len(l.lstrip()) for l in plain), default=0)
    # between two lines that match their rows exactly, the screen and the text must have the same number of rows. More
    # rows on screen: a line was skipped. Fewer: a line was added. (Both ends exact rules out a word-wrapped line, whose
    # first row would not match the whole line.)
    for (r1, l1), (r2, l2) in zip(pairs, pairs[1:]):
        if r2 - r1 == l2 - l1 or not (_exact(measured[r1], plain[l1], base) and _exact(measured[r2], plain[l2], base)):
            continue
        if any(m["deco"][r] for r in range(r1 + 1, r2)) or any("[CUT OFF]" in lines[k]
                                                               for k in range(body[l1][0] + 1, body[l2][0])):
            continue                            # a colour swatch, or a cut-off line (not measured) sits in between
        if r2 - r1 < l2 - l1:
            # fewer rows than lines: only trusted when no band between is tall enough to be two rows run together
            # or an undetected row in between (a highlighted cursor line): the rows' spacing says how many are there
            # (near the gap too: rows run together just above it shift which row matches which line)
            if any(heights[r] > 1.6 * med for r in range(max(0, r1 - 2), min(len(heights), r2 + 3))) or \
                    round((centre[r2] - centre[r1]) / step) > r2 - r1:
                continue
            for li in range(l1 + 1, l2):
                status[body[li][0]] = ROWS
        else:
            # more rows than lines: count only rows that look like a line of code (normal height, two or more words,
            # inside the text's columns); a lone glyph, a cursor, an underline or a pop-up is not a skipped line
            real = sum(1 for r in range(r1 + 1, r2) if 0.8 * med <= heights[r] <= 1.3 * med
                       and len(measured[r]) >= 2 and measured[r][0][0] + base <= left_max)
            if real > l2 - l1 - 1:
                status[body[l2][0]] = ROWS
    # lines beyond the first or last row of ink on screen: the reader continued the code from memory or added lines that are not
    # there. Only when two or more lines are surplus (one row can hide a line), and not where a band is tall enough to be two rows
    # run together or a colour swatch could be a row
    if pairs and not any(m["deco"]) and not any(h > 1.6 * med for h in heights):
        (r0, l0), (r9, l9) = pairs[0], pairs[-1]
        head_extra = l0 - r0
        if head_extra >= 2:
            for li in range(head_extra):
                status[body[li][0]] = ROWS
        tail_room = len(measured) - 1 - r9
        tail_extra = len(plain) - 1 - l9 - tail_room
        if tail_extra >= 2:
            for li in range(len(plain) - tail_extra, len(plain)):
                status[body[li][0]] = ROWS
    return {"grid": True, "status": status, "rows": rows, "x0": m["x0"], "pitch": m["pitch"],
            "absolute_columns": m["absolute_columns"]}


def _lead_candidates(m, lines, anchored=False):
    """Leading column of each text line from a measurement, before any row is thrown out as an outlier. With `anchored`, also the
    set of lines tied to their rows by exact matches or sitting between two such matches."""
    out = [None] * len(lines)
    body, plain, measured, base, pairs = m["body"], m["plain"], m["measured"], m["base"], m["pairs"]
    mapping = {li: ri for ri, li in pairs}
    for (r1, l1), (r2, l2) in zip(pairs, pairs[1:]):
        if r2 - r1 == l2 - l1 > 1:
            for k in range(1, r2 - r1):
                mapping.setdefault(l1 + k, r1 + k)
    # between two matched rows that hold a different number of rows and lines (a stray row, a skipped row), the few rows and
    # lines still line up by the widths of their first words; the matched rows on both sides keep the alignment honest
    for (r1, l1), (r2, l2) in zip(pairs, pairs[1:]):
        if r2 - r1 == l2 - l1 or r2 - r1 > 7 or l2 - l1 > 7 or r2 - r1 < 2 or l2 - l1 < 2:
            continue
        rows_shape = [tuple(w for _, w in measured[r][:2]) for r in range(r1 + 1, r2)]
        lines_shape = [tuple(len(t) for t in plain[l].split()[:2]) for l in range(l1 + 1, l2)]
        for block in _difflib.SequenceMatcher(None, rows_shape, lines_shape, autojunk=False).get_matching_blocks():
            for k in range(block.size):
                mapping.setdefault(l1 + 1 + block.b + k, r1 + 1 + block.a + k)
    tied = set(mapping)                               # lines matched exactly, or sitting between two exact matches
    if len(measured) == len(plain):
        words = [(i, plain[i].split()) for i in range(len(plain)) if plain[i].split() and measured[i]]
        # whole rows, not first words: look-alike lines (a template repeated with other names) share first words, and a
        # row-for-row pairing that is off by one must not pass for a pairing that holds
        agree = sum(1 for i, w in words if [width for _, width in measured[i]] == [len(t) for t in w])
        if words and agree >= 0.6 * len(words):
            for i in range(len(plain)):
                mapping.setdefault(i, i)
    # rows and lines that do not pair one for one (a squiggle left a stray row, a row was skipped) still line up in runs: four or
    # more consecutive rows whose first two words have the widths of four consecutive lines are those lines
    if len(mapping) < len(plain):
        shape_rows = [tuple(w for _, w in row[:2]) for row in measured]
        shape_lines = [tuple(len(t) for t in line.split()[:2]) for line in plain]
        for block in _difflib.SequenceMatcher(None, shape_rows, shape_lines, autojunk=False).get_matching_blocks():
            if block.size >= 4:
                for k in range(block.size):
                    mapping.setdefault(block.b + k, block.a + k)
    for li, ri in mapping.items():
        if m["deco"][ri] or not measured[ri] or "\t" in plain[li]:
            continue
        word = 0
        stubs = (m.get("thin") or [[]] * (ri + 1))[ri]
        while word + 1 < len(measured[ri]) and word < len(stubs) and stubs[word] and \
                measured[ri][word + 1][0] - measured[ri][word][0] >= 3:
            word += 1                      # a guide stub left of the first word is not where the line starts
        lead = measured[ri][word][0] + base
        if lead >= 0:
            out[body[li][0]] = int(lead)
    return (out, tied) if anchored else out


def _offset_consistency(m, lines):
    """Share of the placed rows whose pixel indent differs from the readers' by the screenshot's usual amount (within a
    column). A measurement spoiled by marks at the margin or by fused rows scores low, one that is clean scores high."""
    out = _lead_candidates(m, lines)
    gaps = [x - (len(lines[i]) - len(lines[i].lstrip())) for i, x in enumerate(out) if x is not None and lines[i].strip()]
    if len(gaps) < 8:
        return 0.0
    common = max(set(gaps), key=gaps.count)
    return sum(1 for g in gaps if abs(g - common) <= 1) / len(gaps)


def leads(image_path, text: str, *, source_x=None):
    """Per line of `text`: its leading column read from the pixels (an int), or None when it cannot be placed. Only the
    start of each row is used, so a misread word does not matter. A row is paired with a line by the exact word matches the
    pixel check already trusts, by the rows between two such matches, and, when the screenshot has as many rows as the text
    has lines and most first words have the width the text says, row for row. Needs the screenshot's column one (source_x):
    without it only relative columns exist."""
    lines = text.split("\n")
    out = [None] * len(lines)
    if source_x is None:
        return out
    m = _measure(image_path, text, source_x=source_x)
    if m is None or not m["absolute_columns"]:
        return out
    out, tied = _lead_candidates(m, lines, anchored=True)
    exact = {m["body"][li][0] for li in tied}         # rows tied to the text by exact matches are not second-guessed
    # A screenshot is read at one offset from the screen: the readers' indent and the pixels' differ by about the same amount on
    # every row. A row far from that offset is a row whose first ink is a mark at the margin (an indent guide, a cursor line)
    # or that was paired with the wrong line, so it is not used.
    gaps = {i: x - (len(lines[i]) - len(lines[i].lstrip())) for i, x in enumerate(out) if x is not None and lines[i].strip()}
    if len(gaps) >= 8:
        common = max(set(gaps.values()), key=list(gaps.values()).count)
        if sum(1 for g in gaps.values() if abs(g - common) <= 1) >= 0.6 * len(gaps):
            for i, g in gaps.items():
                if abs(g - common) > 1 and i not in exact:
                    out[i] = None
    return out


def accept_reread(line: str, row: dict):
    """A re-read of a mismatched line is accepted only if its words now have exactly the widths the pixels show; the
    spacing is then taken from the pixels. Returns the corrected line or None."""
    words = line.replace("[CUT OFF]", "").split()
    if len(words) != len(row["widths"]) or any(len(w) != n for w, n in zip(words, row["widths"])):
        return None
    observed = line.replace("[CUT OFF]", "")
    rebuilt = _rebuild(observed, row["cols"])
    from core.text import normalized_line
    if normalized_line(rebuilt) != normalized_line(observed):
        return None
    return rebuilt


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
