import re

from core.security.rules import pii_class

ABEND = re.compile(r"\b(DFH[A-Z]{2}\d{4}|ABEND|ASRA|AEI\d|SQLCODE\s*-?\d+|exception|stack trace|runtime error|"
                   r"object reference not set|null pointer|500 internal|server error)\b", re.I)


def check_screens(store) -> list:
    out = []
    ents = store.entities()
    children = {}
    for e in ents:
        if e["parent_id"]:
            children.setdefault(e["parent_id"], []).append(e)
    terminal = []
    arts = {a["id"]: a for a in store.artifacts()}
    for s in ents:
        if s["kind"] != "screen" or s["origin"] == "placeholder":
            continue
        attrs = s.get("attrs") or {}
        art = arts.get(s["artifact_id"]) or {}
        name = art.get("name", "")
        is_bms = name.lower().endswith(".bms") or "bms" in (art.get("language") or "").lower()
        hints = " ".join(attrs.get("technology_hints") or [])
        if is_bms or attrs.get("screen_type") == "terminal" or re.search(r"3270|5250|terminal", hints, re.I):
            terminal.append(s)
        if attrs.get("technology") != "screenshot":
            continue

        def add(rule, category, severity, detail, snippet="", **refs):
            out.append({"rule": rule, "category": category, "severity": severity, "line": None, "detail": detail,
                        "snippet": snippet[:160], "refs": refs, "artifact_id": s["artifact_id"], "screen": s["name"],
                        "observed": True})

        for m in attrs.get("messages") or []:
            text = str(m.get("text") or "")
            sev = str(m.get("severity") or "").lower()
            if ABEND.search(text):
                add("UIB-CRASH", "usability", "high", f"screen shows a system failure: {text}", text)
            elif sev in ("error", "fatal"):
                add("UIB-ERROR", "usability", "medium", f"visible error message: {text}", text)
        for issue in attrs.get("issues") or []:
            add("UIB-OBSERVED", "usability", "low", f"observed on screen: {issue}", issue)
        for f in children.get(s["id"], []):
            fa = f.get("attrs") or {}
            if fa.get("action"):
                continue
            notes = str(fa.get("notes") or "")
            label = str(fa.get("label") or f["name"])
            if re.search(r"no (visible )?label|unlabel", notes, re.I) or re.fullmatch(r"field \d+", label, re.I):
                add("ACC-LABEL", "accessibility", "medium", f"field '{label}' has no visible label", label,
                    wcag="1.3.1 / 3.3.2 (A)")
            hit = None if fa.get("no_pii") else pii_class(label.replace(" ", "_"))
            if hit and hit[1] in ("critical", "high") and not re.search(r"mask|\*{3}|hidden|last 4", notes, re.I):
                add("UIS-PII", "ui_security", "high" if hit[1] == "critical" else "medium",
                    f"{hit[0]} shown in full on screen ('{label}')", label, cwe="CWE-359", ferpa=True)
            if re.search(r"cryptic|code.*no legend|abbrev", notes, re.I):
                add("USE-CODES", "usability", "low", f"'{label}': {notes}", label)
    from .flows import canonical_screens
    canon = canonical_screens(store)
    terminal = [t for t in terminal if t["id"] not in canon]
    if terminal:
        names = sorted({t["name"] for t in terminal})
        first = terminal[0]
        out.append({"rule": "ACC-TERMINAL", "category": "accessibility", "severity": "medium", "line": None,
                    "detail": f"{len(names)} screen(s) run in a 3270 terminal ({', '.join(names[:5])}) — no screen-reader, "
                              f"zoom or reflow support; WCAG 2.1 AA is not achievable without a web front end",
                    "snippet": "", "refs": {"wcag": "1.4.4 / 1.4.10 / 4.1.2 (AA)"}, "artifact_id": first["artifact_id"],
                    "screen": first["name"]})
    return out
