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
from core.text import normalized_line

# which copy of a line to keep when several screenshots show it
RANK = {"verified": 5, "reread": 5, "confirmed": 4, "joined": 3, "unchecked": 2, "edited": 2, "mismatch": 1,
        "rows": 1, "wrapped": 1, "cut": 0, "": 0}

REASONS = {
    "mismatch": "the screenshot shows a different number of characters than was read (a character may be missing or "
                "extra); a zoomed re-read didn't settle it",
    "cut": "cut off at the edge of the screen and never seen whole: turn on word wrap or scroll sideways, then use "
           "Add screenshots",
    "rows": "the screenshot has a different number of lines here than was read (a line may have been skipped or "
            "added): compare this part with the screen",
    "wrapped": "joined from a word-wrapped line; check the join",
    "break": "no overlap between two screens here, so lines between them may never have been on screen: scroll back "
             "over this part more slowly and use Add screenshots",
    "edited": "changed by the compile-fix step after reading; compare it with the screenshot",
    "spacing": "screenshots disagree about this line's spacing; confirm its source margin and compare the saved readings",
    "syntax": "the source stops parsing here: this line, or one just before it, may be misread, misplaced or missing; compare "
              "it with the screenshot",
}


def syntax_error(code: str, name: str = ""):
    """(line, message) where Python or JSON source first fails to parse, or None. An independent check that needs no
    screenshot: a misread indent, a dropped bracket or a line stitched in twice usually breaks the parse. Other languages
    are not checked here."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if ext in ("py", "pyw"):
            import ast
            ast.parse(code)
        elif ext == "json":
            import json
            json.loads(code)
    except SyntaxError as exc:
        return exc.lineno or 1, exc.msg
    except ValueError as exc:
        return getattr(exc, "lineno", 1) or 1, getattr(exc, "msg", str(exc))
    return None


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
    # The overlap must start with b's first min_k characters, so look only where those occur (a C-speed search) instead of
    # testing every position of a.
    lo, hi, head = max(0, len(a0) - len(b0)), len(a0) - min_k, b0[:min_k]
    at = a0.find(head, lo)
    if at == -1 or at > hi:
        return None
    # A complete SQL statement is a new source row, not a horizontally
    # scrolled suffix merely because many INSERTs share the same ending.
    if re.match(r'^(?:--|(?:CREATE|INSERT|SELECT|UPDATE|DELETE|ALTER|DROP|GRANT|REVOKE|MERGE)\b)', b0, re.I):
        return None
    b_lead = re.sub(r"^\s*(\[CUT OFF\]\s*)?", "", b)      # a piece cut at its left edge starts with the marker
    while at != -1 and at <= hi:
        if b0.startswith(a0[at:]):
            return a0 + b_lead[len(a0) - at:]
        at = a0.find(head, at + 1)
    return None


def _piece_of(l: str, g: str) -> bool:
    """l is part of line g seen after scrolling right: it starts part-way into g, or runs on past g's cut end."""
    l0, g0 = normalized_line(_stem(l)), normalized_line(_stem(g))
    if len(l0) < 8 or not g0:
        return False
    if l0 in g0:
        return not g0.startswith(l0)
    j = join_sideways(g, l)
    return j is not None and j != g


class _PieceIndex:
    """Answers "is this line a piece of a line on some OTHER screen?" for a whole capture without comparing it with every line.
    The distinct lines of all screens are searched as one text (C speed); only the few places where the line can occur are
    tested with the exact rules of _piece_of. The answer for a line needs at most two screens that hold a source, so the
    search stops there; the screen being judged is excluded afterwards."""

    def __init__(self, frames):
        where = {}
        for k, fr in enumerate(frames):
            for g in fr:
                where.setdefault(g, set()).add(k)
        self.raw = list(where)
        self.frames = [where[g] for g in self.raw]
        self.stem = [_stem(g) for g in self.raw]
        self.norm = [normalized_line(x) for x in self.stem]
        self._cache = {}
        for name, items in (("n", self.norm), ("r", self.stem)):
            starts, pos = [], 0
            for x in items:
                starts.append(pos)
                pos += len(x) + 1
            setattr(self, name + "_starts", starts)
            setattr(self, name + "_blob", "\n".join(items))

    def _line_of(self, starts, pos):
        import bisect
        return bisect.bisect_right(starts, pos) - 1

    def holders(self, l):
        """Up to two distinct screens that hold a line l is a piece of."""
        got = self._cache.get(l)
        if got is not None:
            return got
        out, l0 = set(), normalized_line(_stem(l))
        if len(l0) >= 8:
            blob, starts = self.n_blob, self.n_starts
            at = blob.find(l0)
            while at != -1 and len(out) < 2:
                k = self._line_of(starts, at)
                # inside a line, but the line must not simply start with it
                if at > starts[k] and not self.norm[k].startswith(l0) and self.norm[k]:
                    out |= self.frames[k]
                at = blob.find(l0, at + 1)
            if len(out) < 2:
                b0 = _stem(l).strip()
                head = b0[:8]
                at = self.r_blob.find(head) if len(b0) >= 8 else -1
                while at != -1 and len(out) < 2:
                    k = self._line_of(self.r_starts, at)
                    g, a0 = self.raw[k], self.stem[k]
                    # the same test as _piece_of for a line that does not contain l: join_sideways gives something new
                    if self.norm[k] and l0 not in self.norm[k]:
                        j = join_sideways(g, l)
                        if j is not None and j != g:
                            out |= self.frames[k]
                    at = self.r_blob.find(head, at + 1)
        self._cache[l] = out
        return out


def sideways_views(frames: list) -> set:
    """Indexes of the screens that were taken scrolled right: most of their lines are cut at the left edge, or are
    pieces of lines another screen shows from their start."""
    out = set()
    index = None
    for i, f in enumerate(frames):
        long_ = [l for l in f if len(_stem(l).strip()) >= 8]
        if not long_:
            continue
        leadcut = sum(1 for l in long_ if l.lstrip().startswith("[CUT OFF]"))
        if leadcut >= 0.5 * len(long_):
            out.add(i)
            continue
        index = index or _PieceIndex(frames)
        need = 0.5 * len(long_)
        pieces = 0
        for n, l in enumerate(long_):
            if pieces >= need or pieces + (len(long_) - n) < need:
                break                                   # decided either way
            if index.holders(l) - {i}:
                pieces += 1
        if pieces >= need:
            out.add(i)
    return out


def sideways_merge(merged: list, lines: list, force: bool = False):
    """(merged, extended) from sideways_merge_ex, or None."""
    got = sideways_merge_ex(merged, lines, force)
    return None if got is None else got[:2]


def sideways_merge_ex(merged: list, lines: list, force: bool = False):
    """If `lines` is a sideways-scrolled view of text already in `merged` (pieces that start part-way into known lines),
    return (merged with the rest of cut lines joined on, number of lines extended, the joined lines); otherwise None. A sideways view is
    never appended as new lines, even when it adds nothing."""
    cand = [l for l in lines if len(_stem(l).strip()) >= 8]
    if len(cand) < 3:
        return None
    out, ext, piece, miss, pos, joined = list(merged), 0, 0, 0, 0, []
    stems = [_stem(x) for x in out]
    blob = "\n".join(stems)
    exact = {x.strip() for x in stems}
    need, allowed = max(3, 0.4 * len(cand)), 0.25 * len(cand)
    for l in cand:
        b0 = _stem(l).strip()
        head = b0[:8]
        hit = None
        # a line can only join one that contains its first eight characters, so most lines are ruled out by one search
        if head in blob:
            for i in list(range(pos, len(out))) + list(range(0, pos)):
                if head not in stems[i]:
                    continue
                j = join_sideways(out[i], l)
                if j is not None:
                    hit = (i, j)
                    break
        if hit is None:
            if b0 not in exact and not _has_close(stems, b0):
                miss += 1
                if not force and miss > allowed:
                    return None          # the answer can only be "no" from here
            continue
        i, j = hit
        if j != out[i]:
            out[i] = j
            stems[i] = _stem(j)
            blob = "\n".join(stems)
            exact.add(stems[i].strip())
            ext += 1
            joined.append(j)
        elif not _stem(out[i]).strip().startswith(b0):
            piece += 1             # starts part-way into a known line: the view is scrolled right
        pos = i + 1
    if force or (ext + piece >= need and miss <= allowed):
        return out, ext, joined
    return None


def _has_close(stems: list, b0: str) -> bool:
    """Is some line of `stems` at least 90% like b0 (the test the old loop made with _sim on every line)? Lines whose length
    alone rules them out are skipped, and the cheap upper bounds of the matcher are tried before the exact ratio."""
    la = len(b0)
    r = difflib.SequenceMatcher(None)
    r.set_seq2(b0)                      # the line being looked for is fixed; its lookup table is built once
    for m in stems:
        m = m.strip()
        lb = len(m)
        if 2 * min(la, lb) < 0.9 * (la + lb):
            continue
        r.set_seq1(m)
        if r.real_quick_ratio() >= 0.9 and r.quick_ratio() >= 0.9 and r.ratio() >= 0.9:
            return True
    return False


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
        prev, prev_text = None, ""
        widest = max((len(_stem(l)) for l, n in zip(lines, nums) if n is not None), default=0)
        for i, (l, n) in enumerate(zip(lines, nums)):
            s = st[i] if i < len(st) else "unchecked"
            if n is None:
                if l.strip():
                    # A word-wrapped continuation follows a row that ran to the right edge (or was cut there).
                    # Anything else is an unnumbered row we cannot place: fall back to overlap stitching rather
                    # than gluing it onto the wrong line or silently dropping it.
                    reaches_edge = prev_text.rstrip().endswith("[CUT OFF]") or (
                        widest > 0 and len(_stem(prev_text)) >= 0.85 * widest)
                    if prev is None or not reaches_edge:
                        return None
                    c = cands[prev][-1]
                    c[0], c[1] = c[0].rstrip() + " " + l.strip(), "wrapped"
                    wrapped += 1
                prev_text = l
                continue
            cands.setdefault(n, []).append([l, s or "unchecked"])
            prev, prev_text = n, l
    if not cands:
        return None
    out, conflicts, sideways = {}, 0, 0
    for n, cs in cands.items():
        cs = sorted(cs, key=lambda c: -RANK.get(c[1], 0))
        keep = list(cs[0])
        disagreement = False
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
                if normalized_line(keep[0]) != normalized_line(t):
                    conflicts += 1
                    disagreement = True
                continue                                  # same line, the higher-ranked copy is already kept
            conflicts += 1
            disagreement = True
        if disagreement:
            keep[1] = 'mismatch'
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
    ordered = sorted(out)
    text = "\n".join(out[n][0] for n in ordered)
    notes = {"numbers": True, "first_line": lo, "last_line": hi, "gaps": gaps, "wrapped": wrapped,
             "sideways": sideways,
             # These arrays describe `text` positionally.  Keeping them separate from
             # the text-keyed compatibility lookup matters when a file contains the
             # same source line more than once.
             "line_statuses": [out[n][1] for n in ordered],
             "source_lines": ordered}
    return text, notes, {v[0].rstrip(): v[1] for v in out.values() if v[0].strip()}


# ── per-file summary ────────────────────────────────────────────────────────────────────────────────────────────

def _norm(line: str) -> str:
    return normalized_line(line)


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


def _line_map(source: str, target: str, carry_replacements: bool = False) -> list:
    """Return target-index -> source-index after lines have been cleaned, stitched,
    or minimally repaired.  Equal blocks are mapped by occurrence and context, so
    repeated lines do not all collapse onto the same warning.  Same-sized replace
    blocks may be carried positionally for compiler repairs."""
    src, dst = (source or "").split("\n"), (target or "").split("\n")
    sk, dk = [_norm(_stem(l)) for l in src], [_norm(_stem(l)) for l in dst]
    mapped = [None] * len(dst)
    sm = difflib.SequenceMatcher(None, sk, dk, autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal":
            for off in range(b1 - b0):
                mapped[b0 + off] = a0 + off
        elif carry_replacements and tag == "replace" and a1 - a0 == b1 - b0:
            for off in range(b1 - b0):
                mapped[b0 + off] = a0 + off
    return mapped


def remap_line_evidence(source: str, target: str, notes: dict, carry_replacements: bool = True) -> None:
    """Move position-aligned evidence in ``notes`` from source to target in place.

    This is used after source cleaning and again when producing the final report.
    Displayed line numbers always come from the target's final positions; editor
    gutter numbers survive only as optional ``source_lines`` evidence.
    """
    mapping = _line_map(source, target, carry_replacements=carry_replacements)
    src, dst = (source or "").split("\n"), (target or "").split("\n")
    statuses = list(notes.get("line_statuses") or [])
    if statuses:
        # A whitespace-normalised match is enough to locate a row, but not enough
        # to prove its exact transcription (fixed-column legacy code is the clearest
        # example).  Only carry pixel status when the saved line is character-exact.
        notes["line_statuses"] = [
            statuses[j] if j is not None and j < len(statuses) and src[j].rstrip() == dst[i].rstrip() else None
            for i, j in enumerate(mapping)
        ]
    source_lines = list(notes.get("source_lines") or [])
    if source_lines:
        notes["source_lines"] = [source_lines[j] if j is not None and j < len(source_lines) else None for j in mapping]


def align_line_evidence(code: str, raw_parts: list, clean_parts: list, metas: list, notes: dict) -> None:
    """Attach per-occurrence screenshot evidence to the final stitched lines.

    ``lookup`` remains for compatibility, but this positional representation is
    authoritative.  Each frame is aligned raw -> cleaned -> final, which keeps two
    identical lines independent when only one of their screenshot rows was bad.
    """
    final_lines = (code or "").split("\n")
    aligned = [None] * len(final_lines)
    source_lines = [None] * len(final_lines)
    for raw, clean, meta in zip(raw_parts, clean_parts, metas):
        raw = raw or ""
        clean = clean or ""
        clean_lines = clean.split("\n")
        raw_to_clean = _line_map(raw, clean, carry_replacements=True)
        clean_to_final = _line_map(clean, code, carry_replacements=False)
        statuses = (meta or {}).get("status") or []
        numbers = (meta or {}).get("numbers") or []
        for final_i, clean_i in enumerate(clean_to_final):
            if clean_i is None or clean_i >= len(raw_to_clean):
                continue
            raw_i = raw_to_clean[clean_i]
            if raw_i is None:
                continue
            if clean_lines[clean_i].rstrip() != final_lines[final_i].rstrip():
                continue
            status = statuses[raw_i] if raw_i < len(statuses) and statuses[raw_i] else "unchecked"
            aligned[final_i] = best(aligned[final_i] or "", status)
            if raw_i < len(numbers) and isinstance(numbers[raw_i], int):
                source_lines[final_i] = numbers[raw_i]
    notes["line_statuses"] = aligned
    if any(n is not None for n in source_lines):
        notes["source_lines"] = source_lines


def summarize(code: str, statuses: dict, notes: dict | None = None, read_code: str | None = None, name: str = "") -> dict:
    """Counts for one file plus the lines to look at. `read_code` is the text as read, before any compile fix: lines
    that differ from it are reported as edited."""
    notes = notes or {}
    read_lines = (read_code or "").split("\n") if read_code is not None else None
    final_lines = (code or "").split("\n")
    final_to_read = _line_map(read_code or "", code or "", carry_replacements=True) if read_code is not None else []
    aligned = list(notes.get("line_statuses") or [])
    source_lines = list(notes.get("source_lines") or [])
    norm = {_norm(k) for k in statuses}
    spacing_conflicts = set(notes.get('spacing_conflicts') or [])
    counts = {"verified": 0, "reread": 0, "confirmed": 0, "joined": 0, "flagged": 0, "unchecked": 0}
    flags, kinds = [], {}
    for i, l in enumerate(final_lines, 1):
        if not l.strip():
            continue
        read_i = final_to_read[i - 1] if final_to_read else None
        changed = read_lines is not None and (read_i is None or _norm(l) != _norm(read_lines[read_i]))
        s = aligned[read_i] if read_i is not None and read_i < len(aligned) else None
        if "[CUT OFF]" in l:
            s = "cut"
        elif changed:
            s = "edited"
        elif (read_i + 1 if read_i is not None else (i if read_lines is None else None)) in spacing_conflicts:
            s = 'spacing'
        elif s is None:
            s = statuses.get(l.rstrip())
            if s is None:
                s = "edited" if read_lines is not None and _norm(l) not in norm else "unchecked"
        if s in ("verified", "reread", "confirmed", "joined"):
            counts[s] += 1
            kinds[i] = s
        elif s in REASONS:
            counts["flagged"] += 1
            flag = {"line": i, "text": l.strip()[:160], "reason": REASONS[s]}
            if read_i is not None and read_i < len(source_lines) and isinstance(source_lines[read_i], int):
                flag["source_line"] = source_lines[read_i]
            flags.append(flag)
        else:
            counts["unchecked"] += 1
            kinds[i] = "unchecked"
    bad = syntax_error(code or "", name)
    if bad and not any(f["line"] == bad[0] for f in flags):
        line = min(bad[0], len(final_lines))
        flags.append({"line": line, "text": final_lines[line - 1].strip()[:160], "reason": REASONS["syntax"]})
        counts["flagged"] += 1
        if kinds.get(line):
            counts[kinds[line]] -= 1          # the line was already counted once; it now counts as flagged
    lines_ = final_lines
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
           "gap_coordinate": "editor" if notes.get("numbers") else None,
           "first_line": notes.get("first_line"), "last_line": notes.get("last_line"),
           "sideways": notes.get("sideways", 0), "wrapped": notes.get("wrapped", 0), "flags": flags[:50],
           "breaks": sum(flag['reason'] == REASONS['break'] for flag in flags)}
    if notes.get("column_shifted_frames"):
        # stretches of a screenshot that were read one column to the right and were moved back (core.analysis._align_frame_columns)
        out["column_shifted"] = [{"screen": k + 1, "first_row": a, "last_row": b} for k, a, b in notes["column_shifted_frames"]]
    if notes.get("indent_runs_moved"):
        out["indent_shifted"] = [{"first_line": a, "last_line": b} for a, b in notes["indent_runs_moved"]]
    if notes.get('spacing_statuses'):
        measured=sum(s=='measured' for s in notes['spacing_statuses'])
        out['spacing']={'measured':measured,'total':total,'unconfirmed':max(0,total-measured),
                        'conflicts':len(spacing_conflicts),'scope':'visible nonblank columns; tabs and invisible trailing blanks are not proven'}
    out["headline"] = headline(out)
    return out


def spacing_agreement(code, parts, metas, notes):
    """Record positioned spacing disagreements; more indentation proves nothing.

    This withholds certainty rather than rewriting selected source. Calibrated
    automatic selection is a separate step, not an inference from majority OCR.
    """
    final = code.split('\n')
    conflicts = set(notes.get('spacing_conflicts') or [])
    statuses = notes.get('spacing_statuses') or []
    lead = lambda s: len(s) - len(s.lstrip())
    agree, differ, shifts = {}, {}, []
    for k, part in enumerate(parts):
        rows = part.split('\n')
        mapping = _line_map(part, code)
        deltas = {}
        for i, j in enumerate(mapping):
            if i < len(statuses) and statuses[i] == 'measured':
                continue
            if j is None or not final[i].strip() or '[CUT OFF]' in final[i] + rows[j]:
                continue
            if _norm(final[i]) == _norm(rows[j]):
                if final[i].rstrip() != rows[j].rstrip():
                    deltas[i] = lead(final[i]) - lead(rows[j])
                    differ.setdefault(i, []).append(k)
                else:
                    agree[i] = agree.get(i, 0) + 1
        # a screenshot that is off by one constant amount on every line it disagrees about was shifted as a whole;
        # that is a frame offset, not a disagreement about the line
        uniform = len(deltas) >= 3 and len(set(deltas.values())) == 1
        shifts.append((k, deltas, uniform))
    for k, deltas, uniform in shifts:
        for i in deltas:
            if uniform and agree.get(i):
                continue
            conflicts.add(i + 1)
    notes['spacing_conflicts'] = sorted(conflicts)


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
    if v.get("manual"):
        bits.append(f"{v['manual']} corrected from text supplied by the analyst")
    if v["flagged"]:
        bits.append(f"{v['flagged']} to check")
    if v["unchecked"]:
        bits.append(f"{v['unchecked']} couldn't be matched to the pixels (proportional text or editor decorations)")
    s = ", ".join(bits) + "."
    spacing=v.get('spacing')
    if spacing:
        s+=f" Spacing measured from a confirmed source margin: {spacing['measured']} of {spacing['total']} lines."
        if spacing.get('unconfirmed'):
            s+=' Set the source margin in Pick code area; keep column one visible and reset it after moving or zooming the editor.'
    if v.get("gaps"):
        label = "Never on screen (editor source)" if v.get("gap_coordinate") == "editor" else "Never on screen"
        s += f" {label}: " + ", ".join(_span(g) for g in v["gaps"][:6]) + "."
    if v.get("breaks"):
        s += f" {v['breaks']} place(s) where two screens don't overlap, so lines may be missing there."
    return s
