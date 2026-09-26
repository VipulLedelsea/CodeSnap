import re

from core.cobol.parser import _SQL_READ, _SQL_WRITE

from .grammars import lang_for, parse
from .profile import technology_profile
from .stdlib import is_library_type

PARSER_VERSION = "ts-parser-v1"
_SQL_START = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|EXEC|CALL)\b", re.I)
_CONN = re.compile(r"(Data Source|Server|Initial Catalog|Database|Provider|DSN|User ID|Uid)\s*=|jdbc:[a-z0-9]+:", re.I)
_SECRET = re.compile(r"((?:Password|Pwd)\s*=\s*)([^;\"']*)", re.I)
_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


def _line(node) -> int:
    return node.start_point[0] + 1


def _end(node) -> int:
    return node.end_point[0] + 1


def _string_value(node) -> str:
    raw = _text(node)
    raw = re.sub(r'^[@$]*"', '"', raw)
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw.strip("\"'")


def _descendants(node):
    stack = list(reversed(node.children))
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _entity(kind, name, parent=None, start=None, end=None, **attrs):
    return {"kind": kind, "name": name, "parent": parent, "line_start": start, "line_end": end,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def _rel(kind, source, target, line, target_kind=None, **attrs):
    return {"kind": kind, "source": source, "target": target, "target_kind": target_kind, "line": line,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def mask_connection(value: str) -> str:
    return _SECRET.sub(lambda m: m.group(1) + "****", value)


def connection_target(value: str) -> str | None:
    jdbc = re.search(r"jdbc:[^\s\"']+", value, re.I)
    if jdbc:
        url = jdbc.group(0)
        named = re.search(r"(?:databaseName|database|dbname)=([^;&]+)", url, re.I)
        if named:
            return named.group(1)
        tail = re.split(r"[/:@]", url.split("?")[0].split(";")[0].rstrip("/"))[-1]
        return tail if tail and not tail.isdigit() else None
    for key in ("Initial Catalog", "Database", "DSN", "Data Source", "Server"):
        m = re.search(rf"{key}\s*=\s*([^;\"']+)", value, re.I)
        if m:
            return m.group(1).strip()
    return None


def _clean_type(t: str) -> str:
    t = re.sub(r"<.*>", "", t or "").replace("[]", "").strip("*& ")
    return t.split(".")[-1].split("::")[-1]


class _Walker:
    def __init__(self, lang, code):
        self.lang, self.code = lang, code
        self.entities, self.relations = [], []
        self.class_stack = []
        self.methods = {}
        self.fields = {}
        self.module = None
        self._base_path, self._servlet, self._route, self._controller = "", False, None, False

    def cls(self):
        return self.class_stack[-1] if self.class_stack else None

    def owner(self, method):
        return method or self.cls() or self.module or "__file__"

    def run(self, root):
        self.collect_methods(root)
        self.visit(root, None, {})
        return self.entities, self.relations

    def collect_methods(self, root):
        stack = [(root, None)]
        while stack:
            node, cls = stack.pop()
            if node.type in self.CLASS_TYPES:
                name = _text(node.child_by_field_name("name"))
                for child in node.children:
                    stack.append((child, name or cls))
                continue
            if node.type in self.METHOD_TYPES and cls:
                name = self.method_name(node)
                if name:
                    self.methods.setdefault(cls, set()).add(name)
            for child in node.children:
                stack.append((child, cls))

    def visit(self, node, method, scope):
        handler = getattr(self, "on_" + node.type, None)
        if handler and handler(node, method, scope) is False:
            return
        for child in node.children:
            self.visit(child, method, scope)

    def emit_sql_and_conn(self, node, method):
        literals = [_string_value(n) for n in self.string_nodes(node)]
        if not literals:
            return
        joined = " ".join(literals)
        source = self.owner(method)
        if _SQL_START.search(joined) or re.search(r"\b(SELECT\s.+\sFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", joined, re.I):
            writes = {m.group(1).upper() for m in _SQL_WRITE.finditer(joined)}
            reads = {m.group(1).upper() for m in _SQL_READ.finditer(joined)} - writes
            verb = joined.strip().split()[0].upper() if joined.strip() else "SQL"
            for t in sorted(reads):
                self.relations.append(_rel("reads", source, f"table:{t}", _line(node), verb=f"SQL {verb}", embedded=True))
            for t in sorted(writes):
                self.relations.append(_rel("writes", source, f"table:{t}", _line(node), verb=f"SQL {verb}", embedded=True))
        for lit in literals:
            if _CONN.search(lit):
                target = connection_target(lit)
                if target:
                    if not any(e["kind"] == "data_store" and e["name"] == target.upper() for e in self.entities):
                        self.entities.append(_entity("data_store", target.upper(), None, _line(node), _line(node),
                                                     store_type="database", defined_by="connection string"))
                    self.relations.append(_rel("connects_to", source, f"data_store:{target.upper()}", _line(node),
                                               connection=mask_connection(lit)[:200], store_type="database",
                                               hardcoded_secret=bool(_SECRET.search(lit) and not re.search(
                                                   r"(Password|Pwd)\s*=\s*;?$", lit, re.I))))

    def string_nodes(self, node):
        out, stack = [], [node]
        while stack:
            n = stack.pop()
            if n.type in self.STRING_TYPES:
                out.append(n)
                continue
            if n.type in self.METHOD_TYPES or n.type in self.CLASS_TYPES:
                continue
            stack.extend(reversed(n.children))
        return out

    def resolve_call(self, obj, name, method, scope):
        cls = self.cls()
        if obj in (None, "", "this", "base", "super"):
            if cls and name in self.methods.get(cls, ()):
                return f"function:{cls}.{name}"
            if obj in ("base", "super"):
                return None
            return name if any(name in ms for ms in self.methods.values()) else None
        obj = obj.replace("this.", "").replace("this->", "")
        typ = scope.get(obj) or self.fields.get((cls, obj))
        if typ and not is_library_type(typ):
            return f"function:{_clean_type(typ)}.{name}"
        if not typ and obj[:1].isupper() and re.fullmatch(r"[A-Za-z_]\w*", obj) and not is_library_type(obj):
            return f"function:{obj}.{name}"
        return None

    def statement_node(self, node):
        cur = node
        while cur is not None and cur.type not in self.STATEMENT_TYPES:
            cur = cur.parent
        return cur or node


class JavaWalker(_Walker):
    CLASS_TYPES = {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
    METHOD_TYPES = {"method_declaration", "constructor_declaration"}
    STRING_TYPES = {"string_literal"}
    STATEMENT_TYPES = {"expression_statement", "local_variable_declaration", "return_statement", "field_declaration"}

    def method_name(self, node):
        return _text(node.child_by_field_name("name"))

    def annotations(self, node):
        mods = next((c for c in node.children if c.type == "modifiers"), None)
        out = []
        for a in (mods.children if mods else []):
            if a.type in ("annotation", "marker_annotation"):
                name = _text(a.child_by_field_name("name"))
                args = a.child_by_field_name("arguments")
                value = next((_string_value(s) for s in (self.string_nodes(args) if args else [])), None)
                out.append((name, value))
        return out, _text(mods)

    def on_package_declaration(self, node, method, scope):
        name = _text(node).replace("package", "").strip(" ;")
        self.module = name
        self.entities.append(_entity("module", name, None, _line(node), _line(node), language="Java"))
        return False

    def on_import_declaration(self, node, method, scope):
        name = _text(node).replace("import", "").replace("static ", "").strip(" ;")
        self.relations.append(_rel("imports", "__file__", f"module:{name}", _line(node)))
        return False

    def on_class_declaration(self, node, method, scope):
        name = _text(node.child_by_field_name("name"))
        kind = "interface" if node.type == "interface_declaration" else "class"
        anns, mods = self.annotations(node)
        attrs = {"stereotype": node.type.split("_")[0] if node.type not in ("class_declaration",) else None,
                 "visibility": next((v for v in ("public", "protected", "private") if v in mods.split()), None),
                 "annotations": [a for a, _ in anns]}
        self.entities.append(_entity(kind, name, self.cls(), _line(node), _end(node), language="Java", **attrs))
        sup = node.child_by_field_name("superclass")
        if sup is not None:
            base = _clean_type(_text(sup).replace("extends", "").strip())
            if base:
                self.relations.append(_rel("inherits", name, f"class:{base}", _line(sup)))
        for field in ("interfaces", "extends_interfaces"):
            ifs = node.child_by_field_name(field) or next((c for c in node.children if c.type in ("super_interfaces", "extends_interfaces")), None)
            if ifs is not None:
                for t in re.findall(r"[A-Za-z_][\w.]*(?:<[^>]*>)?", _text(ifs).replace("implements", "").replace("extends", "")):
                    self.relations.append(_rel("implements" if kind == "class" else "inherits", name,
                                               f"interface:{_clean_type(t)}", _line(ifs)))
                break
        base_path = next((v for a, v in anns if a in ("Path", "RequestMapping")), "") or ""
        self.class_stack.append(name)
        self._base_path = base_path
        self._servlet = sup is not None and "HttpServlet" in _text(sup)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                self.visit(child, None, {})
        self.class_stack.pop()
        return False

    on_interface_declaration = on_enum_declaration = on_record_declaration = on_class_declaration

    def on_field_declaration(self, node, method, scope):
        typ = _text(node.child_by_field_name("type"))
        for d in node.children:
            if d.type == "variable_declarator":
                name = _text(d.child_by_field_name("name"))
                self.fields[(self.cls(), name)] = typ
                self.entities.append(_entity("field", name, self.cls(), _line(d), _line(d), type=typ))
        self.emit_sql_and_conn(node, None)
        return False

    def on_method_declaration(self, node, method, scope):
        name = self.method_name(node)
        params = node.child_by_field_name("parameters")
        anns, mods = self.annotations(node)
        rtype = _text(node.child_by_field_name("type")) or None
        self.entities.append(_entity("function", name, self.cls(), _line(node), _end(node),
                                     signature=f"{name}{_text(params)}", returns=rtype,
                                     visibility=next((v for v in ("public", "protected", "private") if v in mods.split()), None),
                                     static="static" in mods.split() or None))
        local = {}
        for p in (params.children if params else []):
            if p.type in ("formal_parameter", "spread_parameter"):
                local[_text(p.child_by_field_name("name"))] = _text(p.child_by_field_name("type"))
        verb = next((a.upper() for a, _ in anns if a.upper() in _HTTP_METHODS), None)
        mapping = next(((a, v) for a, v in anns if a.endswith("Mapping")), None)
        path = next((v for a, v in anns if a == "Path"), None)
        if mapping:
            verb = verb or {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
                            "DeleteMapping": "DELETE"}.get(mapping[0], "ANY")
            path = mapping[1] or ""
        if self._servlet and name in ("doGet", "doPost", "doPut", "doDelete", "service"):
            verb, path = name[2:].upper() if name != "service" else "ANY", f"servlet:{self.cls()}"
        if verb:
            full = path if path and path.startswith("servlet:") else "/" + "/".join(
                s.strip("/") for s in (self._base_path, path or "") if s and s.strip("/"))
            ep = f"{verb} {full}"
            self.entities.append(_entity("api_endpoint", ep, None, _line(node), _line(node), method=verb, path=full))
            self.relations.append(_rel("calls", ep, name, _line(node), target_kind="function"))
        body = node.child_by_field_name("body")
        if body is not None:
            self.visit(body, name, local)
        return False

    on_constructor_declaration = on_method_declaration

    def on_local_variable_declaration(self, node, method, scope):
        typ = _text(node.child_by_field_name("type"))
        for d in node.children:
            if d.type == "variable_declarator":
                val = d.child_by_field_name("value")
                t = typ
                if typ == "var" and val is not None and val.type == "object_creation_expression":
                    t = _text(val.child_by_field_name("type"))
                scope[_text(d.child_by_field_name("name"))] = t
        self.emit_sql_and_conn(node, method)

    def on_expression_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def on_return_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def on_method_invocation(self, node, method, scope):
        obj = node.child_by_field_name("object")
        name = _text(node.child_by_field_name("name"))
        target = self.resolve_call(_text(obj) if obj is not None else None, name, method, scope)
        if target and method:
            self.relations.append(_rel("calls", method, target, _line(node), target_kind="function"))

    def on_object_creation_expression(self, node, method, scope):
        typ = _clean_type(_text(node.child_by_field_name("type")))
        if typ and not is_library_type(typ):
            self.relations.append(_rel("uses", self.owner(method), f"class:{typ}", _line(node), verb="new"))


class CSharpWalker(_Walker):
    CLASS_TYPES = {"class_declaration", "interface_declaration", "struct_declaration", "record_declaration",
                   "enum_declaration"}
    METHOD_TYPES = {"method_declaration", "constructor_declaration"}
    STRING_TYPES = {"string_literal", "verbatim_string_literal", "interpolated_string_expression", "raw_string_literal"}
    STATEMENT_TYPES = {"expression_statement", "local_declaration_statement", "return_statement", "field_declaration",
                       "using_statement"}

    def method_name(self, node):
        return _text(node.child_by_field_name("name"))

    def attributes(self, node):
        out = []
        for al in node.children:
            if al.type == "attribute_list":
                for a in al.children:
                    if a.type == "attribute":
                        name = _text(a.child_by_field_name("name")).split(".")[-1]
                        value = next((_string_value(s) for s in self.string_nodes(a)), None)
                        out.append((name, value))
        return out

    def modifiers(self, node):
        return [_text(c) for c in node.children if c.type == "modifier"]

    def on_namespace_declaration(self, node, method, scope):
        name = _text(node.child_by_field_name("name"))
        self.module = name
        self.entities.append(_entity("module", name, None, _line(node), _end(node), language="C#"))

    on_file_scoped_namespace_declaration = on_namespace_declaration

    def on_using_directive(self, node, method, scope):
        name = _text(node).replace("using", "").replace("static", "").strip(" ;")
        if "=" in name:
            name = name.split("=")[1].strip()
        self.relations.append(_rel("imports", "__file__", f"module:{name}", _line(node)))
        return False

    def on_class_declaration(self, node, method, scope):
        name = _text(node.child_by_field_name("name"))
        kind = "interface" if node.type == "interface_declaration" else "class"
        mods = self.modifiers(node)
        attrs = self.attributes(node)
        self.entities.append(_entity(kind, name, self.cls(), _line(node), _end(node), language="C#",
                                     stereotype=node.type.split("_")[0] if node.type != "class_declaration" else None,
                                     visibility=next((m for m in mods if m in ("public", "internal", "protected", "private")), None),
                                     annotations=[a for a, _ in attrs]))
        bases = next((c for c in node.children if c.type == "base_list"), None)
        base_names = [_clean_type(t) for t in re.findall(r"[A-Za-z_][\w.]*(?:<[^>]*>)?", _text(bases).lstrip(":"))] if bases else []
        for i, b in enumerate(base_names):
            is_iface = bool(re.fullmatch(r"I[A-Z]\w*", b))
            if i == 0 and kind == "class" and not is_iface:
                self.relations.append(_rel("inherits", name, f"class:{b}", _line(bases)))
            else:
                self.relations.append(_rel("implements" if kind == "class" else "inherits", name,
                                           f"interface:{b}", _line(bases)))
        self._route = next((v for a, v in attrs if a in ("Route", "RoutePrefix")), None)
        self._controller = name.endswith("Controller") and any(b in ("Controller", "ApiController", "ControllerBase")
                                                               for b in base_names)
        self.class_stack.append(name)
        body = node.child_by_field_name("body") or next((c for c in node.children if c.type == "declaration_list"), None)
        if body is not None:
            for child in body.children:
                self.visit(child, None, {})
        self.class_stack.pop()
        return False

    on_interface_declaration = on_struct_declaration = on_record_declaration = on_enum_declaration = on_class_declaration

    def on_field_declaration(self, node, method, scope):
        decl = next((c for c in node.children if c.type == "variable_declaration"), None)
        if decl is None:
            return False
        typ = _text(decl.child_by_field_name("type"))
        for d in decl.children:
            if d.type == "variable_declarator":
                name = _text(d.child_by_field_name("name")) or _text(d.children[0])
                self.fields[(self.cls(), name)] = typ
                self.entities.append(_entity("field", name, self.cls(), _line(d), _line(d), type=typ,
                                             visibility=next((m for m in self.modifiers(node) if m in ("public", "internal", "protected", "private")), None)))
        self.emit_sql_and_conn(node, None)
        return False

    def on_property_declaration(self, node, method, scope):
        name = _text(node.child_by_field_name("name"))
        typ = _text(node.child_by_field_name("type"))
        self.fields[(self.cls(), name)] = typ
        self.entities.append(_entity("field", name, self.cls(), _line(node), _end(node), type=typ, property=True))
        return False

    def on_method_declaration(self, node, method, scope):
        name = self.method_name(node)
        params = node.child_by_field_name("parameters")
        mods = self.modifiers(node)
        returns = _text(node.child_by_field_name("returns") or node.child_by_field_name("type")) or None
        self.entities.append(_entity("function", name, self.cls(), _line(node), _end(node),
                                     signature=f"{name}{_text(params)}", returns=returns,
                                     visibility=next((m for m in mods if m in ("public", "internal", "protected", "private")), None),
                                     static="static" in mods or None))
        local = {}
        for p in (params.children if params else []):
            if p.type == "parameter":
                local[_text(p.child_by_field_name("name"))] = _text(p.child_by_field_name("type"))
        attrs = self.attributes(node)
        verb = next((a[4:].upper() for a, _ in attrs if a.startswith("Http") and a[4:].upper() in _HTTP_METHODS), None)
        path = next((v for a, v in attrs if a == "Route" and v is not None), None)
        if path is None:
            path = next((v for a, v in attrs if a.startswith("Http") and v is not None), None)
        if not verb and any(a == "WebMethod" for a, _ in attrs):
            verb, path = "POST", f"asmx:{self.cls()}/{name}"
        if not verb and any(a == "OperationContract" for a, _ in attrs):
            verb, path = "SOAP", f"wcf:{self.cls()}/{name}"
        if not verb and self._controller and "public" in mods and node.type == "method_declaration":
            verb = "ANY"
        if verb:
            if path and ":" in path:
                full = path
            else:
                ctrl = (self.cls() or "")[:-10] if (self.cls() or "").endswith("Controller") else self.cls() or ""
                pieces = [self._route] if self._route else [ctrl]
                pieces.append(path if path is not None else name)
                full = "/" + "/".join(p.strip("/") for p in pieces if p and p.strip("/"))
            ep = f"{verb} {full}"
            self.entities.append(_entity("api_endpoint", ep, None, _line(node), _line(node), method=verb, path=full))
            self.relations.append(_rel("calls", ep, name, _line(node), target_kind="function"))
        body = node.child_by_field_name("body")
        if body is not None:
            self.visit(body, name, local)
        return False

    on_constructor_declaration = on_method_declaration

    def on_local_declaration_statement(self, node, method, scope):
        decl = next((c for c in node.children if c.type == "variable_declaration"), None)
        if decl is not None:
            typ = _text(decl.child_by_field_name("type"))
            for d in decl.children:
                if d.type == "variable_declarator":
                    name = _text(d.child_by_field_name("name")) or _text(d.children[0])
                    t = typ
                    creation = next((n for n in _descendants(d) if n.type == "object_creation_expression"), None)
                    if typ == "var" and creation is not None:
                        t = _text(creation.child_by_field_name("type"))
                    scope[name] = t
        self.emit_sql_and_conn(node, method)

    def on_using_statement(self, node, method, scope):
        decl = next((c for c in node.children if c.type == "variable_declaration"), None)
        if decl is None:
            return
        typ = _text(decl.child_by_field_name("type"))
        for d in decl.children:
            if d.type == "variable_declarator":
                name = _text(d.child_by_field_name("name")) or _text(d.children[0])
                creation = next((n for n in _descendants(d) if n.type == "object_creation_expression"), None)
                scope[name] = _text(creation.child_by_field_name("type")) if typ == "var" and creation is not None else typ
        self.emit_sql_and_conn(decl, method)

    def on_expression_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def on_return_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def on_invocation_expression(self, node, method, scope):
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "member_access_expression":
            obj, name = _text(fn.child_by_field_name("expression")), _text(fn.child_by_field_name("name"))
        else:
            obj, name = None, _text(fn)
        name = name.split("<")[0]
        target = self.resolve_call(obj, name, method, scope)
        if target and method:
            self.relations.append(_rel("calls", method, target, _line(node), target_kind="function"))

    def on_object_creation_expression(self, node, method, scope):
        typ = _clean_type(_text(node.child_by_field_name("type")))
        if typ and not is_library_type(typ):
            self.relations.append(_rel("uses", self.owner(method), f"class:{typ}", _line(node), verb="new"))


class CppWalker(_Walker):
    CLASS_TYPES = {"class_specifier", "struct_specifier"}
    METHOD_TYPES = {"function_definition"}
    STRING_TYPES = {"string_literal", "raw_string_literal", "concatenated_string"}
    STATEMENT_TYPES = {"expression_statement", "declaration", "return_statement"}

    def method_name(self, node):
        decl = node.child_by_field_name("declarator")
        while decl is not None and decl.type not in ("function_declarator",):
            decl = decl.child_by_field_name("declarator")
        if decl is None:
            return None
        inner = decl.child_by_field_name("declarator")
        text = _text(inner)
        return text.split("::")[-1] if text else None

    def collect_methods(self, root):
        super().collect_methods(root)
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "function_definition":
                decl = node.child_by_field_name("declarator")
                while decl is not None and decl.type != "function_declarator":
                    decl = decl.child_by_field_name("declarator")
                name = _text(decl.child_by_field_name("declarator")) if decl is not None else ""
                if "::" in name:
                    cls, _, m = name.rpartition("::")
                    self.methods.setdefault(cls.split("::")[-1], set()).add(m)
                elif name:
                    self.methods.setdefault(None, set()).add(name)
            stack.extend(node.children)

    def on_preproc_include(self, node, method, scope):
        path = node.child_by_field_name("path")
        header = _text(path).strip('"<>')
        self.relations.append(_rel("includes", "__file__", f"module:{header}", _line(node),
                                   system=_text(path).startswith("<") or None))
        return False

    def on_namespace_definition(self, node, method, scope):
        name = _text(node.child_by_field_name("name"))
        if name:
            self.module = name
            self.entities.append(_entity("module", name, None, _line(node), _end(node), language="C++"))

    def on_class_specifier(self, node, method, scope):
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None or body is None:
            return
        name = _text(name_node)
        self.entities.append(_entity("class", name, self.cls(), _line(node), _end(node), language="C++",
                                     stereotype="struct" if node.type == "struct_specifier" else None))
        bases = next((c for c in node.children if c.type == "base_class_clause"), None)
        if bases is not None:
            for t in re.findall(r"[A-Za-z_][\w:]*", re.sub(r"\b(public|private|protected|virtual)\b", "", _text(bases).lstrip(":"))):
                self.relations.append(_rel("inherits", name, f"class:{_clean_type(t)}", _line(bases)))
        self.class_stack.append(name)
        for child in body.children:
            self.visit(child, None, {})
        self.class_stack.pop()
        return False

    on_struct_specifier = on_class_specifier

    def on_field_declaration(self, node, method, scope):
        typ = _text(node.child_by_field_name("type"))
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return False
        inner = decl
        while inner is not None and inner.type in ("pointer_declarator", "reference_declarator", "array_declarator"):
            inner = inner.child_by_field_name("declarator") or (inner.children[-1] if inner.children else None)
        if inner is not None and inner.type == "function_declarator":
            return False
        name = _text(inner)
        if name:
            self.fields[(self.cls(), name)] = typ
            self.entities.append(_entity("field", name, self.cls(), _line(node), _line(node), type=typ))
        return False

    def on_function_definition(self, node, method, scope):
        decl = node.child_by_field_name("declarator")
        while decl is not None and decl.type != "function_declarator":
            decl = decl.child_by_field_name("declarator")
        if decl is None:
            return False
        full = _text(decl.child_by_field_name("declarator"))
        cls = self.cls()
        name = full
        if "::" in full:
            owner, _, name = full.rpartition("::")
            cls = owner.split("::")[-1]
        params = decl.child_by_field_name("parameters")
        rtype = _text(node.child_by_field_name("type")) or None
        self.entities.append(_entity("function", name, cls, _line(node), _end(node),
                                     signature=f"{name}{_text(params)}", returns=rtype))
        local = {}
        for p in (params.children if params else []):
            if p.type in ("parameter_declaration", "optional_parameter_declaration"):
                pd = p.child_by_field_name("declarator")
                while pd is not None and pd.type in ("pointer_declarator", "reference_declarator"):
                    pd = pd.child_by_field_name("declarator") or (pd.children[-1] if pd.children else None)
                if pd is not None:
                    local[_text(pd)] = _text(p.child_by_field_name("type"))
        pushed = cls != self.cls()
        if pushed:
            self.class_stack.append(cls)
        body = node.child_by_field_name("body")
        key = name if not cls else name
        if body is not None:
            self.visit(body, key, local)
        if pushed:
            self.class_stack.pop()
        return False

    def on_declaration(self, node, method, scope):
        typ = _text(node.child_by_field_name("type"))
        for d in node.children:
            inner = d
            if inner.type == "init_declarator":
                inner = inner.child_by_field_name("declarator")
            while inner is not None and inner.type in ("pointer_declarator", "reference_declarator", "array_declarator"):
                inner = inner.child_by_field_name("declarator") or (inner.children[-1] if inner.children else None)
            if inner is not None and inner.type == "identifier":
                if method is None and self.cls() is None:
                    continue
                scope[_text(inner)] = typ
        self.emit_sql_and_conn(node, method)

    def on_expression_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def on_return_statement(self, node, method, scope):
        self.emit_sql_and_conn(node, method)

    def resolve_call(self, obj, name, method, scope):
        if obj is None and name in self.methods.get(None, set()):
            return name
        return super().resolve_call(obj, name, method, scope)

    def on_call_expression(self, node, method, scope):
        fn = node.child_by_field_name("function")
        if fn is None or not method:
            return
        target = None
        if fn.type == "field_expression":
            obj = _text(fn.child_by_field_name("argument"))
            target = self.resolve_call(obj, _text(fn.child_by_field_name("field")), method, scope)
        elif fn.type == "qualified_identifier":
            owner, _, name = _text(fn).rpartition("::")
            owner = owner.split("::")[-1]
            if owner and not is_library_type(owner) and owner != "std":
                target = f"function:{owner}.{name}"
        elif fn.type == "identifier":
            target = self.resolve_call(None, _text(fn), method, scope)
        if target:
            self.relations.append(_rel("calls", method, target, _line(node), target_kind="function"))

    def on_new_expression(self, node, method, scope):
        typ = _clean_type(_text(node.child_by_field_name("type")))
        if typ and not is_library_type(typ):
            self.relations.append(_rel("uses", self.owner(method), f"class:{typ}", _line(node), verb="new"))


WALKERS = {"java": JavaWalker, "c_sharp": CSharpWalker, "cpp": CppWalker}


def _dedupe(relations):
    seen, out = set(), []
    for r in relations:
        key = (r["kind"], r["source"], r["target"], r["line"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def parse_source(code: str, filename: str = "", language: str = "") -> dict | None:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    lang = lang_for(language, ext)
    if lang is None:
        return None
    tree = parse(code, lang)
    walker = WALKERS[lang](lang, code)
    entities, relations = walker.run(tree.root_node)
    profile = technology_profile(code, lang)
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": profile},
            "lang": lang}
