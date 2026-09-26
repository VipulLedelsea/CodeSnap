import re
from html.parser import HTMLParser
from pathlib import Path

from .common import entity, rel

_LIB = re.compile(r"(jquery|jquery-ui|bootstrap|angular|angularjs|knockout|backbone|underscore|prototype|mootools|"
                  r"dojo|extjs|ext-all|yui|modernizr|moment|react|vue|lodash|json2|swfobject)[.-]?(\d+(?:\.\d+){0,3})?", re.I)
_DIRECTIVE = re.compile(r"<%@\s*(Page|Control|Master)\b([^%]*)%>", re.I)
_ASPX_ATTRS = re.compile(r"\b(Inherits|CodeBehind|CodeFile|AutoEventWireup|MasterPageFile)\s*=|\bLanguage\s*=\s*\"(C#|VB|cs|vb)\"", re.I)
_JSP_INCLUDE = re.compile(r"<(?:jsp:include|%@\s*include)\s+(?:page|file)\s*=\s*\"([^\"]+)\"", re.I)
_ATTR = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")
_INPUT_TAGS = {"input", "select", "textarea", "button"}


def _screen_name(ref: str) -> str:
    base = ref.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    return re.sub(r"\.(aspx|asp|jsp|jspx|html?|php|do|action|xhtml|cfm)$", "", base, flags=re.I) or base


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self.h1 = None
        self.forms = []
        self.fields = []
        self.labels = {}
        self.links = []
        self.scripts = []
        self.objects = []
        self._in = None
        self._label_for = None
        self._buf = ""
        self.doctype = None

    def handle_decl(self, decl):
        self.doctype = decl

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        line = self.getpos()[0]
        if tag in ("title", "h1", "label", "button", "a", "option"):
            self._in, self._buf = (tag, a, line), ""
        if tag == "label":
            self._label_for = a.get("for") or a.get("associatedcontrolid")
        if tag == "form":
            self.forms.append({"action": a.get("action", ""), "method": (a.get("method") or "GET").upper(),
                               "line": line, "name": a.get("name") or a.get("id")})
        elif tag in _INPUT_TAGS or tag.startswith("asp:") or tag.startswith("html:"):
            self.fields.append({"tag": tag, "attrs": a, "line": line, "text": None,
                                "form": len(self.forms) - 1 if self.forms else None})
        elif tag == "script" and a.get("src"):
            self.scripts.append((a["src"], line))
        elif tag in ("object", "embed", "applet", "param"):
            self.objects.append((tag, a, line))
        if tag == "a" and a.get("href"):
            self.links.append((a["href"], line))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._in and self._in[0] == tag:
            text = " ".join(self._buf.split())
            kind, a, line = self._in
            if kind == "title":
                self.title = text or None
            elif kind == "h1" and not self.h1:
                self.h1 = text or None
            elif kind == "label" and self._label_for:
                self.labels[self._label_for] = text
            elif kind == "button" and self.fields:
                self.fields[-1]["text"] = text
            self._in = None
            if kind == "label":
                self._label_for = None

    def handle_data(self, data):
        if self._in:
            self._buf += data


def _lib(src: str):
    m = _LIB.search(Path(src.split("?")[0]).name)
    if not m:
        return None
    return {"name": m.group(1).lower(), "version": m.group(2), "src": src}


def parse_web_page(text: str, filename: str = "") -> dict:
    stripped = re.sub(r"<%--.*?--%>", "", text, flags=re.S)
    page = _Page()
    page.feed(re.sub(r"<%(?!@).*?%>", lambda m: " " * len(m.group(0)), stripped, flags=re.S))
    name = _screen_name(filename) if filename else (page.title or "page")
    entities, relations = [], []
    code_behind = None
    frameworks, legacy, libraries = [], [], []
    for m in _DIRECTIVE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if _ASPX_ATTRS.search(m.group(2)):
            attrs = {k.lower(): v for k, v in _ATTR.findall(m.group(2))}
            code_behind = attrs.get("inherits") or code_behind
            frameworks.append(f"ASP.NET Web Forms ({m.group(1).capitalize()})")
            if attrs.get("codebehind") or attrs.get("codefile"):
                relations.append(rel("depends_on", name, f"file:{attrs.get('codebehind') or attrs.get('codefile')}",
                                     line, code_behind=True))
        else:
            frameworks.append("JSP")
            for imp in re.findall(r'import\s*=\s*"([^"]+)"', m.group(2)):
                for cls in imp.split(","):
                    relations.append(rel("imports", name, f"module:{cls.strip()}", line))
    for m in _JSP_INCLUDE.finditer(text):
        relations.append(rel("includes", name, f"screen:{_screen_name(m.group(1))}", text.count("\n", 0, m.start()) + 1))
    if code_behind:
        cls = code_behind.split(".")[-1]
        relations.append(rel("uses", name, f"class:{cls}", 1, code_behind=True))
    entities.append(entity("screen", name, None, 1, len(text.splitlines()), title=page.title or page.h1,
                           url=filename or None, technology="web"))
    for i, form in enumerate(page.forms):
        if form["action"]:
            target = form["action"]
            if re.search(r"\.(aspx|jsp|html?|do|action|php|asp)(\?|$)", target, re.I) or target.startswith("/"):
                ep = f"{form['method']} {target.split('?')[0]}"
                entities.append(entity("api_endpoint", ep, None, form["line"], form["line"], method=form["method"],
                                       path=target.split("?")[0]))
                relations.append(rel("calls", name, ep, form["line"], verb="form submit"))
    for f in page.fields:
        a, tag = f["attrs"], f["tag"]
        fid = a.get("id") or a.get("name") or a.get("property")
        ftype = a.get("type", "").lower() or (tag.split(":", 1)[1].lower() if ":" in tag else tag)
        if not fid and not f["text"] and ftype not in ("submit", "button"):
            continue
        if ftype == "hidden":
            continue
        label = page.labels.get(a.get("id", "")) or a.get("aria-label") or a.get("placeholder") or a.get("title")
        is_button = ftype in ("submit", "button", "reset", "image") or tag == "button"
        btn_text = (f["text"] or a.get("value") or a.get("text")) if is_button else None
        element = fid or btn_text or f"{ftype}@{f['line']}"
        attrs = {"type": ftype, "label": label, "input": ftype not in ("submit", "button", "reset", "image", "label",
                                                                       "literal", "hyperlink", "linkbutton"),
                 "required": ("required" in a) or None, "read_only": ("readonly" in a or "disabled" in a) or None,
                 "max_length": int(a["maxlength"]) if a.get("maxlength", "").isdigit() else None,
                 "text": btn_text, "has_label": bool(label) if not is_button else None,
                 "server_control": tag.startswith("asp:") or None}
        entities.append(entity("ui_element", element, name, f["line"], f["line"], **attrs))
        handler = a.get("onclick") if tag.startswith("asp:") else None
        if handler and code_behind:
            relations.append(rel("calls", element, f"function:{code_behind.split('.')[-1]}.{handler}", f["line"],
                                 verb="server event"))
    for href, line in page.links:
        if re.match(r"^(javascript:|mailto:|#)", href, re.I):
            continue
        if re.match(r"^https?://", href, re.I):
            host = re.match(r"^https?://([^/:]+)", href).group(1).lower()
            relations.append(rel("connects_to", name, f"external_system:{host}", line, url=href[:200]))
        elif re.search(r"\.(aspx|jsp|html?|do|action|php|asp)(\?|#|$)", href, re.I):
            relations.append(rel("navigates_to", name, f"screen:{_screen_name(href)}", line))
    for src, line in page.scripts:
        lib = _lib(src)
        if lib:
            libraries.append(f"{lib['name']} {lib['version']}".strip())
            if lib["name"] == "jquery" and lib["version"] and tuple(int(x) for x in lib["version"].split(".")[:2]) < (3, 5):
                legacy.append(f"jQuery {lib['version']} (known XSS issues before 3.5)")
    for tag, a, line in page.objects:
        blob = " ".join(a.values()).lower()
        if "clsid" in blob or tag == "object" and a.get("classid"):
            legacy.append(f"ActiveX control (L{line})")
        if ".swf" in blob or "shockwave" in blob:
            legacy.append(f"Flash (L{line})")
        if "silverlight" in blob or ".xap" in blob:
            legacy.append(f"Silverlight (L{line})")
        if tag == "applet":
            legacy.append(f"Java applet (L{line})")
    if re.search(r"<!--\[if\s+(lt\s+|lte\s+)?IE", text, re.I):
        legacy.append("IE conditional comments")
    doctype = (page.doctype or "").upper()
    if "XHTML" in doctype or "HTML 4" in doctype:
        legacy.append(f"doctype {page.doctype.split('//')[2] if doctype.count('//') > 2 else page.doctype[:40]}")
    unlabeled = sum(1 for e in entities if e["kind"] == "ui_element" and e["attrs"].get("has_label") is False)
    profile = {"language": "ASPX" if code_behind else ("JSP" if "JSP" in frameworks else "HTML"),
               "frameworks": sorted(set(frameworks)), "libraries": libraries, "legacy_markers": legacy,
               "settings": {"fields": sum(1 for e in entities if e["kind"] == "ui_element"),
                            "unlabeled_fields": unlabeled}}
    return {"entities": entities, "relations": relations, "file_attrs": {"profile": profile}}


def looks_like_web(text: str) -> bool:
    head = (text or "").lstrip()[:2000].lower()
    return head.startswith("<!doctype html") or "<html" in head or "<%@ page" in head or "<asp:" in head \
        or ("<form" in head and "<input" in head)
