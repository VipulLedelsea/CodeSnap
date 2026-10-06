import io

import numpy as np
from PIL import Image

PROFILE_BINS = 392
MATCH_TOLERANCE = 0.05
MIN_MATCHES = 12
MIN_MATCH_SHARE = 0.8
RIVAL_RATIO = 1.3
RIVAL_GAP = 0.008
VERTICAL_RULE_SHARE = 0.5
MAX_RESIDUAL = 1.0


def _load(source):
    if isinstance(source, (bytes, bytearray)):
        source = Image.open(io.BytesIO(source))
    elif not isinstance(source, Image.Image):
        source = Image.open(source)
    return np.asarray(source.convert("L"), dtype=np.int16)


def _lines(source):
    gray = _load(source)
    dev = np.abs(gray - np.median(gray)).astype(np.float32)
    ink = dev > 40
    rules = ink.mean(axis=0) > VERTICAL_RULE_SHARE
    ink[:, rules] = False
    dev[:, rules] = 0
    rows = ink.any(axis=1)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], rows.view(np.int8), [0]))))
    bands = list(zip(edges[::2], edges[1::2]))
    width = ink.shape[1]
    cuts = np.linspace(0, width, PROFILE_BINS + 1).astype(int)
    out = []
    for top, bottom in bands:
        lo, hi = max(top - 2, 0), min(bottom + 2, ink.shape[0])
        profile = np.add.reduceat(dev[lo:hi].sum(axis=0), cuts[:-1])
        total = float(profile.sum())
        if total >= 8:
            out.append((int(top), int(bottom), profile / total, total))
    return out, ink.shape[0]


def _distance(a, b):
    return float(np.abs(a - b).sum()) / 2.0


def residual(a, b, shift):
    ga, gb = _load(a), _load(b)
    height = ga.shape[0]
    if shift == 0 or abs(shift) >= height:
        return 1.0
    if shift > 0:
        top, bottom = ga[shift:], gb[:height - shift]
    else:
        top, bottom = ga[:height + shift], gb[-shift:]
    background = np.median(ga)
    ink_top = np.abs(top - background) > 40
    ink_bottom = np.abs(bottom - background) > 40
    rules = (ink_top.mean(axis=0) > VERTICAL_RULE_SHARE) & (ink_bottom.mean(axis=0) > VERTICAL_RULE_SHARE)
    differ = (ink_top ^ ink_bottom)
    differ[:, rules] = False
    total = max(int((ink_top | ink_bottom)[:, ~rules].sum()), 1)
    return float(differ.sum()) / total


def _drop_static(la, lb):
    static_a, static_b = set(), set()
    for i, x in enumerate(la):
        for j, y in enumerate(lb):
            if abs(x[0] - y[0]) <= 1 and abs(x[1] - y[1]) <= 1 and float(np.abs(x[2] - y[2]).sum()) / 2.0 <= 0.01:
                static_a.add(i)
                static_b.add(j)
    return ([x for i, x in enumerate(la) if i not in static_a], [y for j, y in enumerate(lb) if j not in static_b])


def estimate(a, b, min_overlap_lines=12):
    la, height = _lines(a)
    lb, height_b = _lines(b)
    if height != height_b or len(la) < min_overlap_lines or len(lb) < min_overlap_lines:
        return {"ok": False, "reason": "too few lines"}
    la, lb = _drop_static(la, lb)
    if len(la) < min_overlap_lines or len(lb) < min_overlap_lines:
        return {"ok": False, "reason": "too few lines"}
    na, nb = len(la), len(lb)
    pa = np.stack([x[2] for x in la])
    pb = np.stack([x[2] for x in lb])
    dist = np.abs(pa[:, None, :] - pb[None, :, :]).sum(axis=2) / 2.0
    ta = np.array([x[3] for x in la])
    tb = np.array([x[3] for x in lb])
    similar_size = np.abs(ta[:, None] - tb[None, :]) <= 0.08 * np.maximum(ta[:, None], tb[None, :])
    similar_size = np.abs(ta[:, None] - tb[None, :]) <= 0.15 * np.maximum(ta[:, None], tb[None, :])
    dist = np.where(similar_size, dist, 1.0)
    match = dist <= MATCH_TOLERANCE
    scores = {}
    for k in range(-(nb - 1), na):
        i0, j0 = max(k, 0), max(-k, 0)
        n = min(na - i0, nb - j0)
        if n < min_overlap_lines:
            continue
        d = dist[np.arange(i0, i0 + n), np.arange(j0, j0 + n)]
        inner = d[1:-1] if n > 2 else d
        scores[k] = (float(np.minimum(inner, 0.2).mean()), n, float((inner <= MATCH_TOLERANCE).mean()))
    if not scores:
        return {"ok": False, "reason": "no overlap"}
    ranked = sorted(scores.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
    k, (cost, n, share) = ranked[0]
    rival_cost = next((v[0] for kk, v in ranked[1:] if abs(kk - k) > 0), 1.0)
    i0, j0 = max(k, 0), max(-k, 0)
    pairs = [(i0 + t, j0 + t) for t in range(n) if match[i0 + t, j0 + t]]
    if not pairs:
        return {"ok": False, "reason": "no match"}
    shifts = [la[i][0] - lb[j][0] for i, j in pairs]
    shift = int(np.median(shifts))
    spread = int(max(shifts) - min(shifts))
    count = len(pairs)
    unique = rival_cost >= max(cost * RIVAL_RATIO, cost + RIVAL_GAP)
    ok = bool(count >= MIN_MATCHES and share >= MIN_MATCH_SHARE and unique and spread <= 3 and shift != 0)
    return {"ok": ok, "shift": shift, "matches": count, "overlap_lines": n, "share": round(share, 3),
            "rival": round(rival_cost, 3), "cost": round(cost, 4), "spread": spread, "overlap_px": height - abs(shift), "height": height}
