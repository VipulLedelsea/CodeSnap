"""Second-pass capture comparison.

A file captured twice gives two independent readings of it. The way a stitch goes wrong (a screen appended twice, a block
skipped, a row read with a wrong indent) differs from one pass to the next, so where the two agree a line is as good as
confirmed, and where they differ the difference points straight at the error. combine() merges two readings of one file:

* a line both passes read the same stays, and counts as confirmed;
* a stretch only one pass has (a block the other skipped, or the start or end the other never reached) is added, unless it
  repeats text its own pass already holds, which is the signature of a screen stitched in twice;
* a stretch the two read differently takes the reading the pixel check verified, and is reported as a conflict either way,
  because two independent readings that disagree leave no line to trust.
"""
import difflib
import re

RANK = {"verified": 5, "reread": 5, "confirmed": 4, "joined": 3, "unchecked": 2, "edited": 2, "mismatch": 1, "cut": 0, "": 0}


def _key(line):
    return " ".join(line.replace("[CUT OFF]", "").split())


def _rank(statuses, line):
    return RANK.get((statuses or {}).get(line.rstrip(), ""), 0)


def _repeats_inside(block, lines, at, min_len=3):
    """Does `block` (lines[at:at+len]) also appear elsewhere in `lines`, so that it is a copy rather than the only one?"""
    keys = [_key(l) for l in lines]
    size = len(block)
    if size < min_len:
        return False
    want = [_key(l) for l in block]
    for i in range(len(keys) - size + 1):
        if i != at and keys[i:i + size] == want:
            return True
    return False


def _displaced(block, other, near):
    """Are the lines of `block` (a stretch only one pass has) found elsewhere in the other pass, so that the stretch is a copy
    stitched in at the wrong place rather than text the other pass skipped? `near` is the stretch of the other pass the block
    would sit beside, which does not count: the lines have to be somewhere else."""
    keys = [_key(l) for l in block if len(_key(l)) >= 6]
    if len(keys) < 3:
        return False
    elsewhere = {_key(l) for i, l in enumerate(other) if not (near[0] <= i < near[1])}
    return sum(1 for k in keys if k in elsewhere) >= 0.8 * len(keys)


def combine(first, second, first_status=None, second_status=None):
    """Merge two readings (text) of one file. Returns (text, info) with info = {"confirmed": [1-based line numbers of the
    result both passes read the same], "conflicts": [1-based line numbers where they differ], "added": number of lines
    taken only from the second pass, "dropped": number of lines left out as repeats}."""
    a, b = first.split("\n"), second.split("\n")
    sm = difflib.SequenceMatcher(None, [_key(l) for l in a], [_key(l) for l in b], autojunk=False)
    out, confirmed, conflicts = [], [], []
    added = dropped = 0

    def put(line, state=None):
        out.append(line)
        if state == "confirmed":
            confirmed.append(len(out))
        elif state == "conflict":
            conflicts.append(len(out))

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                same_indent = len(x) - len(x.lstrip(" ")) == len(y) - len(y.lstrip(" "))
                if not x.strip():
                    put(x)
                elif same_indent:
                    put(x if _rank(first_status, x) >= _rank(second_status, y) else y, "confirmed")
                else:
                    put(x if _rank(first_status, x) >= _rank(second_status, y) else y, "conflict")
        elif tag == "replace":
            xs, ys = a[i1:i2], b[j1:j2]
            if len(xs) == len(ys):
                for x, y in zip(xs, ys):
                    keep = x if _rank(first_status, x) >= _rank(second_status, y) else y
                    put(keep, "conflict" if x.strip() or y.strip() else None)
            else:
                # different amounts of text in the same place: keep the longer reading, whole, and report it
                keep = xs if sum(1 for l in xs if l.strip()) >= sum(1 for l in ys if l.strip()) else ys
                for line in keep:
                    put(line, "conflict" if line.strip() else None)
        elif tag == "delete":                                  # only the first pass has these lines
            block = a[i1:i2]
            if _repeats_inside(block, a, i1) or _displaced(block, b, (max(0, j1 - 1), j1 + 1)):
                dropped += len(block)
                continue
            for line in block:
                put(line, "conflict" if line.strip() and i1 and i2 < len(a) else None)
        else:                                                   # only the second pass has these lines
            block = b[j1:j2]
            if _repeats_inside(block, b, j1) or _displaced(block, a, (max(0, i1 - 1), i1 + 1)):
                dropped += len(block)
                continue
            added += len(block)
            for line in block:
                put(line, "conflict" if line.strip() and i1 and i1 < len(a) else None)
    return "\n".join(out), {"confirmed": confirmed, "conflicts": conflicts, "added": added, "dropped": dropped}


def split_passes(sessions, min_frames=6, min_share=0.4):
    """Group frame indexes into capture passes by session. A session is a pass when it holds at least `min_frames` screenshots
    and `min_share` of the largest session's: a handful of screenshots added later (Add screenshots) fills gaps in the
    capture and is not a second reading of the file, so it joins the largest session. Returns a list of index lists, the first
    two being the passes to compare, or a single list when the file was captured once."""
    groups = {}
    for i, s in enumerate(sessions):
        groups.setdefault(s, []).append(i)
    if len(groups) < 2:
        return [list(range(len(sessions)))]
    ordered = sorted(groups.values(), key=len, reverse=True)
    big = [g for g in ordered if len(g) >= min_frames and len(g) >= min_share * len(ordered[0])]
    if len(big) < 2:
        return [list(range(len(sessions)))]
    extra = [i for g in ordered if g not in big[:2] for i in g]
    first = sorted(big[0] + extra)
    return [first, sorted(big[1])]


def _verified_share(code, statuses):
    lines = [l for l in code.split("\n") if l.strip()]
    return sum(1 for l in lines if RANK.get(statuses.get(l.rstrip(), ""), 0) >= 4) / max(1, len(lines))


def stitch(parts, metas, sessions=None):
    """merge_verified for a capture that may hold two passes. One pass is stitched exactly as before. Two passes are stitched
    on their own and then combined: the better verified one is the base, the other fills what it lacks, and the result carries
    notes["pass_confirmed"] (lines both read alike) and notes["pass_conflicts"] (lines they read differently)."""
    from core import verify
    from core.analysis import merge_verified
    groups = split_passes(sessions) if sessions and len(sessions) == len(parts) else [list(range(len(parts)))]
    if len(groups) < 2:
        code, clean, notes, statuses = merge_verified(parts, metas)
        return code, clean, notes, statuses
    runs = []
    for idx in groups:
        code, clean, notes, statuses = merge_verified([parts[i] for i in idx], [metas[i] for i in idx])
        runs.append((code, clean, notes, statuses))
    runs.sort(key=lambda r: _verified_share(r[0], r[3]), reverse=True)
    (code, clean, notes, statuses), (other, _, _, other_statuses) = runs[0], runs[1]
    combined, info = combine(code, other, statuses, other_statuses)
    verify.remap_line_evidence(code, combined, notes)
    merged = dict(other_statuses)
    merged.update(statuses)
    notes["pass_confirmed"] = info["confirmed"]
    notes["pass_conflicts"] = info["conflicts"]
    notes["passes"] = {"added": info["added"], "dropped": info["dropped"], "frames": [len(g) for g in groups]}
    return combined, clean, notes, merged
