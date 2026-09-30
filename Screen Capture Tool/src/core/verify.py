"""Transcription verification: prove each line, or say which lines to look at.

Three independent signals, each used only when the screenshot provides it:

* Pixel check (core.colfix.check): editor text sits on a fixed character grid, so every word's length and column can
  be measured. A line whose words all match is "verified". A line whose matching screen row shows a different character
  count is a "mismatch" (a dropped or added character) and gets a zoomed re-read. No grid (proportional font, a photo,
  a UI screen) means "unchecked", never a guess.
* Editor line numbers (optional): when the editor shows a line-number gutter the model reports it separately. The
  numbers put every line in its place across screenshots (so no overlap guessing), show lines that were never on screen
  and join sideways-scrolled pieces of the same line. Without a gutter the overlap stitching is used as before.
* Sideways pieces: a screenshot taken after scrolling right shows the rest of lines that were cut at the right edge.
  Those pieces are joined onto their lines instead of being added to the end of the file.
"""
import re
import difflib

# which copy of a line to keep when several screenshots show it
RANK = {"verified": 5, "reread": 5, "confirmed": 4, "joined": 3, "unchecked": 2, "edited": 2, "mismatch": 1,
        "wrapped": 1, "cut": 0, "": 0}

REASONS = {
    "mismatch": "the screenshot shows a different number of characters than was read (a character may be missing or "
                "extra); a zoomed re-read didn't settle it",
    "cut": "cut off at the edge of the screen and never seen whole: turn on word wrap or scroll sideways, then use "
           "Add screenshots",
    "wrapped": "joined from a word-wrapped line; check the join",
    "break": "no overlap between two screens here, so lines between them may never have been on screen: scroll back "
             "over this part more slowly and use Add screenshots",
    "edited": "changed by the compile-fix step after reading; compare it with the screenshot",
}


def best(a: str, b: str) -> str:
    return a if RANK.get(a or "", 0) >= RANK.get(b or "", 0) else b


# ── editor line numbers ─────────────────────────────────────────────────────────────────────────────────────────

def valid_numbers(nums, lines) -> list:
    """The model's gutter numbers, or [] when they can't be trusted (missing, wrong length, not increasing by one).
    Returning [] is the normal case for editors without line numbers; stitching then falls back to overlaps."""
    if not isinstance(nums, list) or len(nums) != len(lines) or not nums:
        return []
    out = []
    for n in nums:
        if isinstance(n, bool):
            n = None
        if isinstance(n, str) and n.strip().isdigit():
            n = int(n.strip())
        out.append(n if isinstance(n, int) and n > 0 else None)
    given = [n for n in out if n is not None]
    body = sum(1 for l in lines if l.strip())
    if len(given) < 3 or len(given) < 0.6 * max(body, 1):
        return []
    steps = [b - a for a, b in zip(given, given[1:])]
    if not steps or sum(1 for s in steps if s == 1) < 0.85 * len(steps):
        return []   # sticky-scroll headers and folded code give a few jumps; a misread gutter gives many
    # a COBOL sequence number read as a line number: the "gutter" is really part of every line
    if sum(1 for n, l in zip(out, lines) if n is not None and l.lstrip().startswith(str(n))) > 0.5 * len(given):
        return []
    return out


# ── sideways-scrolled pieces ────────────────────────────────────────────────────────────────────────────────────

def _stem(s: str) -> str:
    return s.replace("[CUT OFF]", "").rstrip()


def join_sideways(a: str, b: str, min_k: int = 8):
    """a with the rest of the line from b, when b is a piece of the same line seen after scrolling right: b starts with
    the end of a. Returns a itself when b lies inside a, else None."""
    a0, b0 = _stem(a), _stem(b).strip()
    if len(b0) < min_k or not a0.strip():
        return None
    if b0 in a0:
        return a
    b_lead = re.sub(r"^\s*(\[CUT OFF\]\s*)?", "", b)      # a piece cut at its left edge starts with the marker
    for p in range(max(0, len(a0) - len(b0)), len(a0) - min_k + 1):
        if b0.startswith(a0[p:]):
            return a0 + b_lead[len(a0) - p:]
    return None


def _piece_of(l: str, g: str) -> bool:
    """l is part of line g seen after scrolling right: it starts part-way into g, or runs on past g's cut end."""
    l0, g0 = " ".join(_stem(l).split()), " ".join(_stem(g).split())
    if len(l0) < 8 or not g0:
        return False
    if l0 in g0:
        return not g0.startswith(l0)
    j = join_sideways(g, l)
    return j is not None and j != g


def sideways_views(frames: list) -> set:
    """Indexes of the screens that were taken scrolled right: most of their lines are cut at the left edge, or are
    pieces of lines another screen shows from their start."""
    out = set()
    for i, f in enumerate(frames):
        long_ = [l for l in f if len(_stem(l).strip()) >= 8]
        if not long_:
            continue
        leadcut = sum(1 for l in long_ if l.lstrip().startswith("[CUT OFF]"))
        if leadcut >= 0.5 * len(long_):
            out.add(i)
            continue
        others = [g for j, fr in enumerate(frames) if j != i for g in fr]
        pieces = sum(1 for l in long_ if any(_piece_of(l, g) for g in others))
        if pieces >= 0.5 * len(long_):
            out.add(i)
    return out


def sideways_merge(merged: list, lines: list, force: bool = False):
    """If `lines` is a sideways-scrolled view of text already in `merged` (pieces that start part-way into known lines),
    return (merged with the rest of cut lines joined on, number of lines extended); otherwise None. A sideways view is
    never appended as new lines, even when it adds nothing."""
    cand = [l for l in lines if len(_stem(l).strip()) >= 8]
    if len(cand) < 3:
        return None
    out, ext, piece, miss, pos, joined = list(merged), 0, 0, 0, 0, []
    for l in cand:
        b0 = _stem(l).strip()
        hit = None
        for i in list(range(pos, len(out))) + list(range(0, pos)):
            j = join_sideways(out[i], l)
            if j is not None:
                hit = (i, j)
                break
        if hit is None:
            if not any(_sim(m, l) >= 0.9 for m in out):
                miss += 1
            continue
        i, j = hit
        if j != out[i]:
            out[i] = j
            ext += 1
            joined.append(j)
        elif not _stem(out[i]).strip().startswith(b0):
            piece += 1             # starts part-way into a known line: the view is scrolled right
        pos = i + 1
    if force or (ext + piece >= max(3, 0.4 * len(cand)) and miss <= 0.25 * len(cand)):
        sideways_merge.joined = joined
        return out, ext
    return None


def _same_line(x: str, y: str) -> bool:
    """Two reads of one line: nearly the same text and the same numbers (lines that differ only in a number are
    different lines)."""
    return re.findall(r"\d+", _stem(x)) == re.findall(r"\d+", _stem(y)) and _sim(x, y) >= 0.75


def _sim(x: str, y: str) -> float:
    return difflib.SequenceMatcher(None, _stem(x).strip(), _stem(y).strip()).ratio()


# ── stitching by line number ────────────────────────────────────────────────────────────────────────────────────

def merge_by_numbers(parts: list, metas: list):
    """Put every screenshot's lines at their editor line number. Returns (text, notes, statuses) or None when any
    screenshot has no usable numbers or the screenshots disagree about what a line number holds."""
    shown = [(p, m or {}) for p, m in zip(parts, metas) if (p or "").strip()]
    if not shown or any(not m.get("numbers") for _, m in shown):
        return None
    cands, wrapped = {}, 0
    for p, m in shown:
        lines, nums, st = p.split("\n"), m["numbers"], m.get("status") or []
        if len(nums) != len(lines):
            return None
        prev = None
        for i, (l, n) in enumerate(zip(lines, nums)):
            s = st[i] if i < len(st) else "unchecked"
            if n is None:
                if prev is not None and l.strip():      # a word-wrapped continuation row
                    c = cands[prev][-1]
                    c[0], c[1] = c[0].rstrip() + " " + l.strip(), "wrapped"
                    wrapped += 1
                continue
            cands.setdefault(n, []).append([l, s or "unchecked"])
            prev = n
    if not cands:
        return None
    out, conflicts, sideways = {}, 0, 0
    for n, cs in cands.items():
        cs = sorted(cs, key=lambda c: -RANK.get(c[1], 0))
        keep = list(cs[0])
        for t, s in cs[1:]:
            if not t.strip():
                continue
            if not keep[0].strip():
                keep = [t, s]
                continue
            a0, t0 = _stem(keep[0]).strip(), _stem(t).strip()
            if t0 in a0:
                continue                                  # the kept copy already holds all of it
            if a0 in t0:
                keep = [t, s]                             # the kept copy was a piece of this one
                continue
            j = join_sideways(keep[0], t) or join_sideways(t, keep[0])
            if j is not None and _stem(j) not in (_stem(keep[0]), _stem(t)):
                both = keep[1] in ("verified", "reread") and s in ("verified", "reread")
                keep = [j, "verified" if both and "[CUT OFF]" not in j else "joined"]
                sideways += 1
                continue
            if _same_line(keep[0], t):
                continue                                  # same line, the higher-ranked copy is already kept
            conflicts += 1
        out[n] = keep
    if conflicts > max(2, 0.1 * len(out)):
        return None
    lo, hi = min(out), max(out)
    gaps, start = [], None
    for n in range(1, hi + 1):
        if n not in out and start is None:
            start = n
        elif n in out and start is not None:
            gaps.append([start, n - 1])
            start = None
    text = "\n".join(out[n][0] for n in sorted(out))
    notes = {"numbers": True, "first_line": lo, "last_line": hi, "gaps": gaps, "wrapped": wrapped,
             "sideways": sideways}
    return text, notes, {v[0].rstrip(): v[1] for v in out.values() if v[0].strip()}


# ── per-file summary ────────────────────────────────────────────────────────────────────────────────────────────

def _norm(line: str) -> str:
    return " ".join(line.split())


def lookup(parts: list, metas: list) -> dict:
    """line text -> the best status any screenshot gave it."""
    out = {}
    for p, m in zip(parts, metas):
        st = (m or {}).get("status") or []
        for i, l in enumerate((p or "").split("\n")):
            if l.strip():
                k = l.rstrip()
                out[k] = best(out.get(k, ""), st[i] if i < len(st) and st[i] else "unchecked")
    return out


def summarize(code: str, statuses: dict, notes: dict | None = None, read_code: str | None = None) -> dict:
    """Counts for one file plus the lines to look at. `read_code` is the text as read, before any compile fix: lines
    that differ from it are reported as edited."""
    notes = notes or {}
    read = {l.rstrip() for l in (read_code or "").split("\n")} if read_code is not None else None
    norm = {_norm(k) for k in statuses}
    counts = {"verified": 0, "reread": 0, "confirmed": 0, "joined": 0, "flagged": 0, "unchecked": 0}
    flags = []
    for i, l in enumerate((code or "").split("\n"), 1):
        if not l.strip():
            continue
        s = statuses.get(l.rstrip())
        if "[CUT OFF]" in l:
            s = "cut"
        elif s is None:
            s = "edited" if read is not None and l.rstrip() not in read and _norm(l) not in norm else "unchecked"
        if s in ("verified", "reread", "confirmed", "joined"):
            counts[s] += 1
        elif s in REASONS:
            counts["flagged"] += 1
            flags.append({"line": i, "text": l.strip()[:160], "reason": REASONS[s]})
        else:
            counts["unchecked"] += 1
    lines_ = (code or "").split("\n")
    for b in notes.get("breaks") or []:
        prev, nxt = b if isinstance(b, (list, tuple)) else ("", b)
        nb = [k for k, l in enumerate(lines_) if l.strip()]
        i = next((nb[j + 1] for j in range(len(nb) - 1)
                  if lines_[nb[j]].rstrip() == prev and lines_[nb[j + 1]].rstrip() == nxt), None)
        if i is not None:
            flags.append({"line": i + 1, "text": nxt.strip()[:160], "reason": REASONS["break"]})
    flags.sort(key=lambda f: f["line"])
    total = sum(counts.values())
    gaps = notes.get("gaps") or []
    out = {"lines": total, **counts, "numbers": bool(notes.get("numbers")), "gaps": gaps,
           "first_line": notes.get("first_line"), "last_line": notes.get("last_line"),
           "sideways": notes.get("sideways", 0), "wrapped": notes.get("wrapped", 0), "flags": flags[:50],
           "breaks": len(notes.get("breaks") or [])}
    out["headline"] = headline(out)
    return out


def _span(g):
    return f"line {g[0]}" if g[0] == g[1] else f"lines {g[0]}–{g[1]}"


def headline(v: dict) -> str:
    if not v or not v.get("lines"):
        return ""
    ok = v["verified"] + v["reread"]
    bits = [f"{ok} of {v['lines']} lines verified against the screenshot"]
    if v["reread"]:
        bits.append(f"{v['reread']} after a zoomed re-read")
    if v["confirmed"]:
        bits.append(f"{v['confirmed']} confirmed by a second read")
    if v.get("joined"):
        bits.append(f"{v['joined']} pieced together from sideways-scrolled screenshots")
    if v["flagged"]:
        bits.append(f"{v['flagged']} to check")
    if v["unchecked"]:
        bits.append(f"{v['unchecked']} couldn't be matched to the pixels (proportional text or editor decorations)")
    s = ", ".join(bits) + "."
    if v.get("gaps"):
        s += " Never on screen: " + ", ".join(_span(g) for g in v["gaps"][:6]) + "."
    if v.get("breaks"):
        s += f" {v['breaks']} place(s) where two screens don't overlap, so lines may be missing there."
    return s
