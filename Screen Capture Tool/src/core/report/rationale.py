"""Every score in the report carries its reason: where it started, what was deducted and why.

Scores are computed 0-100 (100 = best) from itemised deductions; the report template rates on a 1-5 condition scale
(1 = excellent, 5 = critical). Both are shown together with the deductions that produced them.
"""

CONDITION = [(90, 1, "Excellent"), (75, 2, "Good"), (55, 3, "Fair"), (35, 4, "Poor"), (-1, 5, "Critical")]
BANDS = ("90 or more is 1 – Excellent, 75 to 89 is 2 – Good, 55 to 74 is 3 – Fair, 35 to 54 is 4 – Poor, and below 35 "
         "is 5 – Critical")


def condition(score):
    """0-100 (100 best) -> (1-5 condition, label)."""
    if score is None:
        return None, "Not rated"
    for floor, n, label in CONDITION:
        if score >= floor:
            return n, label
    return 5, "Critical"


DIM_NAMES = {"health": "code health", "tech_debt": "maintainability", "security": "security",
             "supportability": "supportability", "complexity": "complexity", "coupling": "dependencies",
             "ux": "usability and accessibility", "overall": "overall"}


def rating_words(score) -> str:
    c, label = condition(score)
    return f"{c} – {label}" if c else "Not rated"


WORDS = False     # True for the Word report: ratings in words (1-5, 1 best), no 0-100 figures


def explain(score, factors, n=3, none_text="No problems were found in the files reviewed.") -> str:
    """'Condition 3 – Fair. Scored 62 out of 100; points were taken off because …'."""
    from .plain import reasons, reasons_words, sentence
    if score is None:
        return "Insufficient evidence: the material reviewed gives no evidence for this."
    if WORDS:
        rs = reasons_words(factors, n)
        return f"{rating_words(score)}" + (f", mainly because {sentence(rs)}." if rs else f". {none_text}")
    rs = reasons(factors, n)
    head = f"{rating_words(score)}. Scored {score} out of 100"
    return head + (f"; points were taken off because {sentence(rs)}." if rs else f". {none_text}")


def program_factors(components, dim, n=6) -> list:
    """The deductions for one dimension across all components, labelled with the component."""
    out = []
    for c in components:
        for f in c["scores"].get(dim, {}).get("factors", []):
            out.append({**f, "component": c["name"]})
    return sorted(out, key=lambda f: f["points"])[: n if n else None]


def explain_program(a, dim, n=3) -> str:
    """The program-level score for one dimension, with the reasons in plain English."""
    from .plain import reasons, reasons_words, sentence
    s = (a.get("scores") or {}).get(dim) or {}
    score = s.get("score")
    if score is None:
        return explain(None, [])
    name = DIM_NAMES.get(dim, dim)
    if WORDS:
        w = s.get("worst") or {}
        worst_c = condition(w.get("score"))[0] if w.get("score") is not None else None
        head = rating_words(w["score"]) if worst_c else rating_words(score)
        out = f"{head}, going by the weakest file" + (f" ({w.get('component')})" if w.get("component") else "")
        rs = reasons_words(program_factors(a.get("components") or [], dim, 0), n)
        out += f", mainly because {sentence(rs)}." if rs else ". No problems were found."
        if worst_c and condition(score)[0] != worst_c:
            out += f" Averaged across all files it would be {rating_words(score)}."
        return out
    out = f"{rating_words(score)}. {name[:1].upper() + name[1:]} scored {score} out of 100"
    w = s.get("worst") or {}
    if w and w.get("score") is not None and w["score"] < score:
        out += f" (weakest file: {w.get('component')}, {w.get('score')})"
    rs = reasons(program_factors(a.get("components") or [], dim, 0), n)
    return out + (f". Points were taken off because {sentence(rs)}." if rs else ". No problems were found.")


def risk_reason(c) -> str:
    r = c.get("risk") or {}
    worst = min(((d, (c["scores"].get(d) or {}).get("score")) for d in ("security", "supportability", "health")),
                key=lambda x: 101 if x[1] is None else x[1])
    src = r.get("impact_source") or ""
    if src == "staff":
        imp = "rated by the business owner"
    else:
        m = src[src.find("(") + 1:src.rfind(")")] if "(" in src else ""
        imp = (f"it {m}" if m else "default") + " (a default until the business owner rates it)"
    return (f"Likelihood {r.get('likelihood')} of 5, because its weakest area ({DIM_NAMES.get(worst[0], worst[0])}) "
            f"scored {worst[1]} out of 100. Impact {r.get('impact')} of 5: {imp}. "
            f"Risk score {r.get('likelihood')} × {r.get('impact')} = {r.get('score')} of 25.")


def template_rating(score25) -> str:
    """The template's risk bands: 15+ High, 8–14 Medium, ≤7 Low."""
    return "High" if score25 >= 15 else "Medium" if score25 >= 8 else "Low"
