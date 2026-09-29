"""Pixel-measured spacing for fixed-column source (COBOL, RPG, JCL, BMS, IMS/assembler macros).

The vision model reads the words reliably but miscounts runs of spaces, and in these languages the column a word
starts in is part of its meaning. In a monospaced editor screenshot every character occupies one cell of a regular
grid, so the column of each word can be measured from the pixels. This keeps the model's words and replaces only the
spaces between them with the measured ones. It never adds, drops or changes a visible character, and it leaves a
line alone whenever the measurement and the text don't clearly agree.
"""
import numpy as np
from PIL import Image

MAX_SHIFT = 8          # a measured column this far from the transcribed one means the row was matched wrongly
MIN_GRID_FIT = 0.6     # how well glyph edges must sit on one character grid before we trust it


def _ink(path):
    im = np.asarray(Image.open(path).convert("L")).astype(int)
    return np.abs(im - np.median(im)) > 60


def _rows(ink, min_h=4, max_h=80, join=2):
    """Screen rows of text, each as a list of (x_start, x_end) ink runs. Bands split by a hairline gap (an underscore
    or a descender below the letters) are joined back into their row."""
    bands, start = [], None
    for y, on in enumerate(list(ink.any(1)) + [False]):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if bands and start - bands[-1][1] <= join and (y - start < min_h or bands[-1][1] - bands[-1][0] < min_h):
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
    cell = lambda x: int(np.floor((x - offset * pitch) / pitch + 0.25))
    words, cur = [], [cell(runs[0][0]), cell(runs[0][1])]
    for s, e in runs[1:]:
        a, b = cell(s), cell(e)
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


def _rebuild(line, cols):
    out = ""
    for w, c in zip(line.split(), cols):
        c = max(c, len(out) + (1 if out else 0))
        out += " " * (c - len(out)) + w
    return out


def respace(image_path, text: str) -> tuple:
    """Return (text with measured spacing, number of lines changed) for one screenshot's transcription."""
    lines = text.split("\n")
    body = [(i, l) for i, l in enumerate(lines) if l.strip() and "[CUT OFF]" not in l]
    if not body:
        return text, 0
    try:
        rows = _rows(_ink(image_path))
        fit, pitch, offset = _grid(rows)
    except Exception:  # noqa: BLE001 - measurement is an extra; never let it break a transcription
        return text, 0
    if pitch is None or fit < MIN_GRID_FIT:
        return text, 0
    measured = [_word_columns(r, pitch, offset) for r in rows if r]
    plain = [l for _, l in body]
    left = min(m[0][0] for m in measured)
    right = left + max(len(l) for l in plain) + 4          # anything further right is a scrollbar or minimap
    measured = [[w for w in m if w[0] <= right] or m[:1] for m in measured]
    no_gutter = [x[1:] if len(x) > 1 else x for x in measured]   # editor line numbers are one extra word per row
    pairs, measured = max(((_align(m, plain), m) for m in (measured, no_gutter)), key=lambda pm: len(pm[0]))
    if len(pairs) < max(3, min(len(plain), len(measured)) // 3):
        return text, 0
    votes = {}
    for ri, li in pairs:
        d = _starts(plain[li])[0] - measured[ri][0][0]
        votes[d] = votes.get(d, 0) + 1
    base = max(votes, key=votes.get)
    changed = 0
    for ri, li in pairs:
        cols = [c + base for c, _ in measured[ri]]
        if any(abs(a - b) > MAX_SHIFT for a, b in zip(_starts(plain[li]), cols)):
            continue
        new = _rebuild(plain[li], cols)
        if new != plain[li] and new.split() == plain[li].split():
            lines[body[li][0]] = new
            changed += 1
    return "\n".join(lines), changed
