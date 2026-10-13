"""Compare the counts the report states in words with the counts in the program model. Pure code, no model call.

Only explicit totals are checked ("12 files were reviewed", "3 screens were supplied"). A phrase such as "9 of 12 files
use COBOL" is a share of a total, so it is skipped, as is any count that is not stated as the whole.
"""
import re

_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUM = r"(\d{1,6}|" + "|".join(_WORDS) + r")"
_SCOPE = r"(?:provided |supplied |received |source |code |application |UI |program )*"
_DONE = r"(?:were|was|are|is|have been|has been)?\s*(?:all\s+)?(?:reviewed|provided|supplied|received|analysed|analyzed|read)"
# noun -> patterns whose first group is the stated number
_PATTERNS = {
    "files": [rf"(?<!of )(?<!\d )\b{_NUM}\s+{_SCOPE}files?\s+{_DONE}", rf"\b(?:reviewed|received|supplied|covers?|covering)\s+{_NUM}\s+{_SCOPE}files?\b"],
    "screens": [rf"(?<!of )\b{_NUM}\s+{_SCOPE}screens?\s+{_DONE}", rf"\b(?:reviewed|received|supplied|covers?|covering)\s+{_NUM}\s+{_SCOPE}screens?\b"],
    "tables": [rf"(?<!of )\b(?:identif\w+|defin\w+|contain\w*|found|lists?|declares?)\s+{_NUM}\s+(?:database |SQL )?tables?\b"],
}


def truth(store) -> dict:
    """{noun: count} from the model. Files exclude UI screens, which are counted on their own."""
    arts = [a for a in store.artifacts() if (a.get("transcription") or "").strip()]
    screens = sum(1 for a in arts if a.get("artifact_type") == "ui_screen")
    kinds = store.coverage().get("entities_by_kind") or {}
    out = {"files": len(arts) - screens, "screens": screens}
    if "table" in kinds:
        out["tables"] = kinds["table"]
    return out


def _number(token):
    return int(token) if token.isdigit() else _WORDS.get(token.lower())


def check(report_text: str, actual: dict) -> list:
    """Items shaped like the consistency read's: one per stated count that differs from the model."""
    items, section = [], ""
    for line in report_text.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        for sentence in re.split(r"(?<=[.;])\s+", line):
            for noun, patterns in _PATTERNS.items():
                if noun not in actual:
                    continue
                for pattern in patterns:
                    for m in re.finditer(pattern, sentence, re.I):
                        stated = _number(m.group(1))
                        if stated is None or stated == actual[noun]:
                            continue
                        items.append({"topic": f"Number of {noun}", "kind": "number", "first": sentence.strip()[:300],
                                      "first_section": section,
                                      "second": f"Program model: {actual[noun]} {noun}", "second_section": "program model",
                                      "why": f"The report says {stated} {noun}; the program model holds {actual[noun]}."})
    seen, out = set(), []
    for it in items:
        key = (it["topic"], it["first"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
