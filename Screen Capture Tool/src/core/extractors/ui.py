import base64
import json
import re
from pathlib import Path

from .common import entity, rel

MARKER = "codesnap_ui_screen"
PROMPT_VERSION = "ui-screen-v1"
FIELD_TYPES = ["text", "number", "date", "currency", "select", "checkbox", "radio", "textarea", "password", "file",
               "display", "table", "button", "link", "menu", "tab", "pf_key", "other"]

UI_SYSTEM = """You document ONE screen of a running legacy business application from screenshots, for a system assessment.
Record the screen's STRUCTURE only — never transcribe data values that could identify people or money amounts
(names, IDs, SSNs, addresses, dollar figures). For each field report its label and kind, not its contents.
Use the record_screen tool. Include:
- title: the screen/window/page title as shown (or a short descriptive title if none is shown)
- screen_type: form | list | report | menu | dialog | error | login | dashboard | terminal (3270/5250 green screen)
- technology_hints: what the UI appears to be built with, from visible evidence only (e.g. "3270 terminal",
  "WinForms", "ASP.NET Web Forms", "Java Swing", "Internet Explorer only", "Silverlight", "modern web",
  "5250 green screen", "Oracle Forms", "PowerBuilder", "MS Access form", "Visual Basic 6", "Delphi",
  "Visual FoxPro", "Crystal Reports 2016" — include a version only when it is visible)
- fields: every visible input or display field: label (as shown), kind, required (marked * or similar),
  read_only, and notes (e.g. "no visible label", "truncated", "free-text code")
- actions: buttons, links, menu items, PF keys: label, kind
- messages: visible errors, warnings, banners: text (without personal data), severity
- issues: visible usability/accessibility problems (unlabeled fields, low contrast, tiny text, cryptic codes,
  inconsistent layout, error text without guidance, mixed date formats)
Report only what is visible. Do not guess hidden screens or behaviour."""

UI_TOOL = {
    "name": "record_screen",
    "description": "Record the structure of the screen shown.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "screen_type": {"type": "string"},
            "technology_hints": {"type": "array", "items": {"type": "string"}},
            "fields": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "kind": {"type": "string", "enum": FIELD_TYPES},
                "required": {"type": "boolean"}, "read_only": {"type": "boolean"}, "notes": {"type": "string"}},
                "required": ["label", "kind"]}},
            "actions": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "kind": {"type": "string"}}, "required": ["label"]}},
            "messages": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "severity": {"type": "string"}}, "required": ["text"]}},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "fields", "actions"],
    },
}


def _media_type(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(
        path.suffix.lower(), "image/png")


def extract_ui_screen(client, image_paths, model=None) -> dict:
    from core.analysis import MODEL, _parse_json
    model = model or MODEL
    content = []
    for p in list(image_paths)[:8]:
        p = Path(p)
        content.append({"type": "image", "source": {"type": "base64", "media_type": _media_type(p),
                                                      "data": base64.standard_b64encode(p.read_bytes()).decode()}})
    content.append({"type": "text", "text": "These screenshots show one application screen (possibly scrolled). "
                                            "Call record_screen once."})
    msg = client.messages.create(model=model, max_tokens=4096, system=UI_SYSTEM, tools=[UI_TOOL],
                                 tool_choice={"type": "auto"}, messages=[{"role": "user", "content": content}])
    data = None
    for block in getattr(msg, "content", []) or []:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == "record_screen":
            data = dict(block.input or {})
    if data is None:
        data = _parse_json("".join(getattr(b, "text", "") for b in msg.content)) or {}
    if not isinstance(data, dict) or not data.get("title"):
        raise ValueError("screen extraction returned nothing")
    return {MARKER: 1, "prompt_version": PROMPT_VERSION, **data}


def to_transcription(screen: dict) -> str:
    return json.dumps(screen, indent=2, ensure_ascii=False)


def screen_name(screen: dict, fallback: str = "screen") -> str:
    title = re.sub(r"\s+", " ", str(screen.get("title") or fallback)).strip()
    return title[:80] or fallback


def parse_ui_json(text: str, filename: str = "") -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or MARKER not in data:
        return None
    name = screen_name(data, filename.rsplit(".", 1)[0] or "screen")
    entities = [entity("screen", name, None, 1, 1, title=data.get("title"), screen_type=data.get("screen_type"),
                       technology="screenshot", technology_hints=data.get("technology_hints") or None,
                       issues=data.get("issues") or None, messages=data.get("messages") or None)]
    relations, seen = [], set()
    for i, f in enumerate(data.get("fields") or [], 1):
        label = str(f.get("label") or f"field {i}").strip()[:80]
        key = label if label not in seen else f"{label} ({i})"
        seen.add(key)
        entities.append(entity("ui_element", key, name, None, None, type=f.get("kind"), label=label,
                               input=f.get("kind") not in ("display", "table", "button", "link", "menu", "tab"),
                               required=f.get("required") or None, read_only=f.get("read_only") or None,
                               notes=f.get("notes") or None))
    for a in data.get("actions") or []:
        label = str(a.get("label") or "").strip()[:80]
        if not label:
            continue
        key = label if label not in seen else f"{label} (action)"
        seen.add(key)
        entities.append(entity("ui_element", key, name, None, None, type=a.get("kind") or "button", label=label,
                               input=False, action=True))
    profile = {"language": "UI screen", "frameworks": data.get("technology_hints") or [],
               "legacy_markers": [h for h in (data.get("technology_hints") or [])
                                  if re.search(r"3270|5250|terminal|silverlight|activex|internet explorer|flash|vb6|visual basic 6|oracle forms|powerbuilder|foxpro|access|delphi|crystal", h, re.I)],
               "settings": {"fields": len(data.get("fields") or []), "actions": len(data.get("actions") or []),
                            "issues": len(data.get("issues") or [])}}
    return {"entities": entities, "relations": relations, "file_attrs": {"profile": profile}}
