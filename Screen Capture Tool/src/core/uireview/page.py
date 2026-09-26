import re
from html.parser import HTMLParser

from core.security.rules import pii_class

SKIP_INPUT = {"hidden", "submit", "button", "image", "reset"}
VOID = {"input", "img", "br", "hr", "meta", "link", "area", "base", "col", "embed", "param", "source", "track", "wbr"}
VAGUE_LINK = {"click here", "here", "more", "read more", "link", "click", "this"}
VAGUE_BUTTON = re.compile(r"^(button\d*|submit|ok|go|btn\d*)$", re.I)
DESTRUCTIVE = re.compile(r"\b(delete|remove|purge|approve|reject|void|cancel payment|submit payment|finali[sz]e|post)\b", re.I)
VALIDATE_HINT = re.compile(r"(id|date|year|amount|amt|zip|phone|ssn|marss|number|num|nbr|count|rate)$", re.I)
CSRF = re.compile(r"csrf|xsrf|_token|authenticity|requestverificationtoken|__viewstate", re.I)
HIDDEN_SENSITIVE = re.compile(r"price|amount|amt|total|role|isadmin|admin|userid|user_id|ssn|marss|discount|approved", re.I)
DEPRECATED = {"font", "center", "marquee", "blink", "frameset", "frame", "basefont", "big", "strike", "tt"}


def _hex(c):
    c = (c or "").strip().lower()
    names = {"white": "ffffff", "black": "000000", "red": "ff0000", "yellow": "ffff00", "gray": "808080", "grey": "808080",
             "silver": "c0c0c0", "blue": "0000ff", "navy": "000080", "green": "008000", "lime": "00ff00",
             "orange": "ffa500", "lightgray": "d3d3d3", "lightgrey": "d3d3d3", "maroon": "800000", "aqua": "00ffff"}
    if c in names:
        return names[c]
    m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6})", c)
    if not m:
        return None
    h = m.group(1)
    return "".join(ch * 2 for ch in h) if len(h) == 3 else h


def contrast(fg, bg):
    def lum(h):
        vals = []
        for i in (0, 2, 4):
            v = int(h[i:i + 2], 16) / 255
            vals.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]
    a, b = _hex(fg), _hex(bg)
    if not a or not b:
        return None
    la, lb = lum(a), lum(b)
    return round((max(la, lb) + 0.05) / (min(la, lb) + 0.05), 2)


def _style(s):
    out = {}
    for part in (s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_lang = None
        self.has_html = False
        self.title = None
        self.headings = 0
        self.imgs, self.inputs, self.labels_for, self.links, self.forms, self.clickables = [], [], set(), [], [], []
        self.deprecated, self.tables, self.meta_viewport, self.resources, self.buttons = [], [], None, [], []
        self.label_depth = 0
        self.stack = []
        self.bg_stack = ["ffffff"]
        self.color_issues = []
        self._text_target = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        line = self.getpos()[0]
        st = _style(a.get("style"))
        bg = _hex(st.get("background-color") or st.get("background") or a.get("bgcolor")) or self.bg_stack[-1]
        fg = st.get("color") or (a.get("color") if tag == "font" else None)
        if fg and bg:
            ratio = contrast(fg, bg)
            if ratio is not None and ratio < 4.5:
                self.color_issues.append((line, fg, bg, ratio))
        if tag == "html":
            self.has_html = True
            self.html_lang = a.get("lang") or a.get("xml:lang")
        elif tag == "title":
            self._text_target = ("title", None, line)
            self.title = ""
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings += 1
        elif tag == "label" or tag == "asp:label" and a.get("associatedcontrolid"):
            if a.get("for") or a.get("associatedcontrolid"):
                self.labels_for.add((a.get("for") or a.get("associatedcontrolid")).lower())
            if tag == "label":
                self.label_depth += 1
        elif tag in ("img", "asp:image") or tag == "input" and a.get("type", "").lower() == "image":
            self.imgs.append((line, a, tag))
        elif tag == "meta" and a.get("name", "").lower() == "viewport":
            self.meta_viewport = (line, a.get("content", ""))
        elif tag == "form":
            self.forms.append({"line": line, "method": (a.get("method") or "GET").upper(), "action": a.get("action", ""),
                               "runat": a.get("runat"), "inputs": [], "hidden": []})
        elif tag == "table":
            self.tables.append({"line": line, "rows": 0, "th": 0, "role": a.get("role", "")})
        elif tag == "tr" and self.tables:
            self.tables[-1]["rows"] += 1
        elif tag == "th" and self.tables:
            self.tables[-1]["th"] += 1
        if tag in ("input", "select", "textarea", "asp:textbox", "asp:dropdownlist", "asp:checkbox", "asp:listbox"):
            typ = a.get("type", "text").lower() if tag == "input" else ("text" if tag == "asp:textbox" else tag.split(":")[-1])
            rec = {"line": line, "tag": tag, "type": typ, "a": a, "wrapped": self.label_depth > 0,
                   "form": len(self.forms) - 1 if self.forms else None}
            self.inputs.append(rec)
            if self.forms:
                (self.forms[-1]["hidden"] if typ == "hidden" else self.forms[-1]["inputs"]).append(rec)
        if tag in ("button", "asp:button", "asp:linkbutton") or tag == "input" and a.get("type", "").lower() in ("submit", "button"):
            self.buttons.append({"line": line, "a": a, "text": a.get("value") or a.get("text") or "", "tag": tag})
            if tag == "button":
                self._text_target = ("button", self.buttons[-1], line)
        if tag == "a":
            self.links.append({"line": line, "a": a, "text": "", "img_alt": None})
            self._text_target = ("a", self.links[-1], line)
        if tag == "img" and self._text_target and self._text_target[0] == "a":
            self._text_target[1]["img_alt"] = a.get("alt")
        if a.get("onclick") and tag in ("div", "span", "td", "tr", "img", "li", "p", "label") and not a.get("tabindex") \
                and not a.get("role"):
            self.clickables.append((line, tag))
        if tag in DEPRECATED:
            self.deprecated.append((line, tag))
        for attr in ("src", "href"):
            if tag in ("script", "img", "iframe", "link", "embed", "object") and a.get(attr):
                self.resources.append((line, tag, a[attr]))
        if tag not in VOID:
            self.stack.append(tag)
            self.bg_stack.append(bg)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "label":
            self.label_depth = max(0, self.label_depth - 1)
        if self._text_target and self._text_target[0] == tag:
            self._text_target = None
        if tag in self.stack:
            while self.stack:
                t = self.stack.pop()
                self.bg_stack.pop()
                if t == tag:
                    break

    def handle_data(self, data):
        if not self._text_target:
            return
        kind, obj, _ = self._text_target
        if kind == "title":
            self.title += data
        elif kind == "a":
            obj["text"] += data
        elif kind == "button":
            obj["text"] += data


def _prep(text):
    text = re.sub(r"<%--.*?--%>", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"<%(?!@).*?%>", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def _label_of(rec, s):
    a = rec["a"]
    ident = (a.get("id") or "").lower()
    return rec["wrapped"] or (ident and ident in s.labels_for) or a.get("aria-label") or a.get("aria-labelledby") \
        or a.get("title")


def check_page(text: str) -> list:
    s = _Scan()
    try:
        s.feed(_prep(text or ""))
    except Exception:
        return []
    out = []

    def add(rule, category, severity, line, detail, snippet="", **refs):
        out.append({"rule": rule, "category": category, "severity": severity, "line": line, "detail": detail,
                    "snippet": snippet[:160], "refs": refs})

    for line, a, tag in s.imgs:
        alt = a.get("alternatetext") if tag == "asp:image" else a.get("alt")
        if alt is None and a.get("role") != "presentation" and a.get("aria-hidden") != "true":
            add("ACC-ALT", "accessibility", "medium", line, "image has no text alternative",
                a.get("src") or a.get("imageurl") or tag, wcag="1.1.1 Non-text Content (A)")
    for rec in s.inputs:
        if rec["type"] in SKIP_INPUT:
            continue
        if not _label_of(rec, s):
            name = rec["a"].get("id") or rec["a"].get("name") or rec["tag"]
            add("ACC-LABEL", "accessibility", "medium", rec["line"], f"form field '{name}' has no programmatic label",
                name, wcag="1.3.1 / 3.3.2 / 4.1.2 (A)")
    if s.has_html:
        if not (s.title or "").strip():
            add("ACC-TITLE", "accessibility", "low", 1, "page has no title", wcag="2.4.2 Page Titled (A)")
        if not s.html_lang:
            add("ACC-LANG", "accessibility", "low", 1, "page language not declared (<html lang>)",
                wcag="3.1.1 Language of Page (A)")
        if s.forms and not s.headings:
            add("ACC-HEADINGS", "accessibility", "low", 1, "form page has no headings to navigate by",
                wcag="1.3.1 / 2.4.6 (AA)")
    for line, fg, bg, ratio in s.color_issues[:10]:
        add("ACC-CONTRAST", "accessibility", "medium", line, f"text contrast {ratio}:1 is below 4.5:1",
            f"color {fg} on #{bg}", wcag="1.4.3 Contrast (Minimum) (AA)")
    for line, tag in s.clickables[:10]:
        add("ACC-KEYBOARD", "accessibility", "medium", line, f"clickable <{tag}> cannot be reached by keyboard",
            f"<{tag} onclick>", wcag="2.1.1 Keyboard (A)")
    for lk in s.links:
        text = " ".join(lk["text"].split()).lower()
        if (not text and not lk["img_alt"] and not lk["a"].get("aria-label")) or text in VAGUE_LINK:
            if lk["a"].get("href"):
                add("ACC-LINK", "accessibility", "low", lk["line"], f"link text '{text or '(empty)'}' does not describe its target",
                    lk["a"].get("href", ""), wcag="2.4.4 Link Purpose (A)")
        if lk["a"].get("target", "").lower() == "_blank" and not re.search(r"noopener|noreferrer", lk["a"].get("rel", ""), re.I):
            add("UIS-BLANK", "ui_security", "low", lk["line"], "link opens a new window without rel=noopener",
                lk["a"].get("href", ""), cwe="CWE-1022")
    if s.meta_viewport and re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b", s.meta_viewport[1], re.I):
        add("ACC-ZOOM", "accessibility", "medium", s.meta_viewport[0], "page blocks zooming", s.meta_viewport[1],
            wcag="1.4.4 Resize Text (AA)")
    tags = sorted({t for _, t in s.deprecated})
    if tags:
        add("ACC-DEPRECATED", "accessibility", "low", s.deprecated[0][0], "presentational/obsolete HTML: " + ", ".join(tags),
            wcag="1.3.1 Info and Relationships (A)")
    for t in s.tables:
        if t["rows"] > 2 and not t["th"] and t["role"] != "presentation":
            add("ACC-TABLE", "accessibility", "low", t["line"], "table has no header cells (<th>) — layout table or unlabeled data",
                wcag="1.3.1 Info and Relationships (A)")
    for f in s.forms:
        names = [(r["a"].get("name") or r["a"].get("id") or "") for r in f["inputs"]]
        sensitive = [n for n in names if re.search(r"pass|pwd", n, re.I) or pii_class(n)]
        if f["method"] == "GET" and sensitive and not f["runat"]:
            add("UIS-GET", "ui_security", "high", f["line"], "form sends sensitive fields in the URL (GET): " + ", ".join(sensitive[:4]),
                f"<form method=get action={f['action']}>", cwe="CWE-598", nist=["SC-8", "SI-10"])
        if f["method"] == "POST" and not f["runat"] and not any(CSRF.search((h["a"].get("name") or "") + (h["a"].get("id") or ""))
                                                                  for h in f["hidden"]):
            add("UIS-CSRF", "ui_security", "medium", f["line"], "POST form has no anti-forgery token",
                f"<form method=post action={f['action']}>", cwe="CWE-352", nist=["SC-23"])
        if re.match(r"http://", f["action"] or "", re.I):
            add("UIS-MIXED", "ui_security", "high", f["line"], "form submits over plain HTTP", f["action"], cwe="CWE-319",
                nist=["SC-8"])
        for h in f["hidden"]:
            n = h["a"].get("name") or h["a"].get("id") or ""
            if HIDDEN_SENSITIVE.search(n):
                add("UIS-HIDDEN", "ui_security", "medium", h["line"], f"security-relevant value '{n}' kept in a hidden field the user can edit",
                    n, cwe="CWE-472", nist=["SI-10"])
        text_inputs = [r for r in f["inputs"] if r["type"] in ("text", "textbox")]
        if len(f["inputs"]) > 20:
            add("USE-LONGFORM", "usability", "low", f["line"], f"form has {len(f['inputs'])} fields on one page")
        for r in text_inputs:
            n = r["a"].get("name") or r["a"].get("id") or ""
            if VALIDATE_HINT.search(n) and not (r["a"].get("maxlength") or r["a"].get("pattern")):
                add("USE-VALIDATION", "usability", "low", r["line"], f"field '{n}' has no length/format validation", n)
    for rec in s.inputs:
        n = rec["a"].get("name") or rec["a"].get("id") or ""
        if re.search(r"pass(word)?|pwd", n, re.I) and rec["type"] not in ("password", "hidden") and rec["tag"] == "input":
            add("UIS-PWFIELD", "ui_security", "medium", rec["line"], f"password field '{n}' is not masked", n, cwe="CWE-549")
        if rec["tag"] == "asp:textbox" and re.search(r"pass(word)?|pwd", n, re.I) and rec["a"].get("textmode", "").lower() != "password":
            add("UIS-PWFIELD", "ui_security", "medium", rec["line"], f"password field '{n}' is not masked", n, cwe="CWE-549")
    for b in s.buttons:
        text = " ".join((b["text"] or "").split())
        if DESTRUCTIVE.search(text) and not re.search(r"confirm\(", b["a"].get("onclick", "") + b["a"].get("onclientclick", ""), re.I):
            add("USE-CONFIRM", "usability", "medium", b["line"], f"'{text}' acts immediately with no confirmation step", text)
        elif VAGUE_BUTTON.match(text or "button"):
            add("USE-BUTTON", "usability", "low", b["line"], f"button label '{text or '(none)'}' does not say what it does", text)
    for line, tag, url in s.resources:
        if re.match(r"http://(?!localhost|127\.)", url, re.I) and tag in ("script", "iframe", "link", "img", "embed", "object"):
            add("UIS-MIXED", "ui_security", "medium" if tag == "img" else "high", line,
                f"{tag} loaded over plain HTTP (mixed content)", url, cwe="CWE-319", nist=["SC-8"])
    return out
