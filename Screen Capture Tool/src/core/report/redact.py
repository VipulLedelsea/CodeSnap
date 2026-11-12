"""Anonymization for client deliverables: names that identify the real organization (in file names, schemas, host
names or text) are replaced before the report or its diagrams are written. Terms come from the report settings;
organization names embedded in captured file names (for example Some_State_Department_of_Education) are found
automatically when the client shown in the report is different."""
import re

from core.diagrams.xmlsafe import xml_safe

ORG = re.compile(r"(?:[A-Z][a-z]+[_ ]){0,3}(?:Department|Dept|Agency|Office|Ministry|Board|Division|Bureau|Commission)"
                 r"[_ ]of[_ ](?:[A-Z][a-z]+(?:[_ ]|(?=\.)|$)){1,4}")


def _common_org(phrases):
    """The match takes up to four capitalised words after "of", so in Dept_of_Education_Payroll_Report.cbl it runs into the
    rest of the file name. When several names share the words up to the one after "of", only the words they all share are
    the organisation; the rest is what tells the files apart and stays."""
    groups = {}
    for p in set(phrases):
        words = [w for w in re.split(r"[_ ]", p) if w]
        head = tuple(words[:words.index("of") + 2]) if "of" in words else tuple(words)
        groups.setdefault(head, []).append(words)
    out = []
    for head, members in groups.items():
        if len(members) < 2:
            out.append("_".join(members[0]))
            continue
        common = members[0]
        for words in members[1:]:
            k = 0
            while k < min(len(common), len(words)) and common[k] == words[k]:
                k += 1
            common = common[:k]
        out.append("_".join(common if len(common) >= len(head) else head))
    return out


class Redactor:
    def __init__(self, settings: dict, names=()):
        client = (settings.get("client") or "").lower()
        repl = settings.get("client_short") or "CLIENT"
        terms = [t.strip() for t in re.split(r"[,;\n]", settings.get("redact_terms") or "") if t.strip()]
        auto = []
        for n in names:
            for m in ORG.finditer(n or ""):
                phrase = m.group(0).strip("_ .")
                words = [w for w in re.split(r"[_ ]", phrase) if w]
                if phrase and not all(w.lower() in client for w in words):
                    auto.append(phrase)
        auto = _common_org(auto)
        self.rules = []
        for p in sorted(set(auto), key=len, reverse=True):
            spaced = p.replace("_", " ")
            self.rules.append((re.compile(r"(?<![A-Za-z0-9_])" + re.escape(p) + r"_"), ""))   # at the start of a name: nothing left to join
            self.rules.append((re.compile(r"_?" + re.escape(p) + r"_?"), "_"))
            self.rules.append((re.compile(re.escape(spaced)), repl))
        for t in sorted(set(terms), key=len, reverse=True):
            variants = {t, t.replace(" ", "_")}
            for v in variants:
                self.rules.append((re.compile(r"(?<![A-Za-z])" + re.escape(v), re.I if " " in t else 0), repl))
        self.active = bool(self.rules)

    def __call__(self, text):
        if not isinstance(text, str):
            return text
        text = xml_safe(text)      # characters XML forbids would make the Word, SVG and Visio files invalid
        if not self.active or not text:
            return text
        for rx, rep in self.rules:
            text = rx.sub(rep, text)
        text = re.sub(r"_+(?=\.[A-Za-z0-9]+\b)", "", text)
        return re.sub(r"__+", "_", text)

    def map(self, obj):
        if isinstance(obj, str):
            return self(obj)
        if isinstance(obj, dict):
            return {k: self.map(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.map(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.map(v) for v in obj)
        return obj
