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
    # A complete SQL statement is a new source row, not a horizontally
    # scrolled suffix merely because many INSERTs share the same ending.
    if re.match(r'^(?:--|(?:CREATE|INSERT|SELECT|UPDATE|DELETE|ALTER|DROP|GRANT|REVOKE|MERGE)\b)', b0, re.I):
        return None
    b_lead = re.sub(r"^\s*(\[CUT OFF\]\s*)?", "", b)      # a piece cut at its left edge starts with the marker
    for p in range(max(0, len(a0) - len(b0)), len(a0) - min_k + 1):
        if b0.startswith(a0[p:]):
            return a0 + b_lead[len(a0) - p:]
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


def sideways_views(frames: list) -> set:
    """Indexes of the screens that were taken scrolled right: most of their lines are cut at the left edge, or are
    pieces of lines another screen shows from their start."""
    out = set()
    blobs = [("\n".join(normalized_line(_stem(g)) for g in fr), "\n".join(_stem(g) for g in fr)) for fr in frames]
    for i, f in enumerate(frames):
        long_ = [l for l in f if len(_stem(l).strip()) >= 8]
        if not long_:
            continue
        leadcut = sum(1 for l in long_ if l.lstrip().startswith("[CUT OFF]"))
        if leadcut >= 0.5 * len(long_):
            out.add(i)
            continue
        others = [g for j, fr in enumerate(frames) if j != i for g in fr]
        # Cheap necessary conditions (C-speed substring tests over the other screens) before the exact per-line
        # comparison: a piece must lie inside some line (normalized) or start with the last >= 8 chars of one.
        norm_blob = "\n".join(blobs[j][0] for j in range(len(frames)) if j != i)
        raw_blob = "\n".join(blobs[j][1] for j in range(len(frames)) if j != i)
        pieces = 0
        for l in long_:
            l0 = normalized_line(_stem(l))
            head = _stem(l).strip()[:8]
            if (len(l0) < 8 or l0 not in norm_blob) and (len(head) < 8 or head not in raw_blob):
                continue
            if any(_piece_of(l, g) for g in others):
                pieces += 1
        if pieces >= 0.5 * len(long_):
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
        return out, ext, joined
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


def summarize(code: str, statuses: dict, notes: dict | None = None, read_code: str | None = None) -> dict:
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
    flags = []
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
        elif s in REASONS:
            counts["flagged"] += 1
            flag = {"line": i, "text": l.strip()[:160], "reason": REASONS[s]}
            if read_i is not None and read_i < len(source_lines) and isinstance(source_lines[read_i], int):
                flag["source_line"] = source_lines[read_i]
            flags.append(flag)
        else:
            counts["unchecked"] += 1
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
