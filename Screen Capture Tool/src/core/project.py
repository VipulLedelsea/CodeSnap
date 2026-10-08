"""Project mode — cross-file dependency analysis from separately captured files.

Each file is captured on its own (one capture = one file), producing a faithful
transcription. This module takes the SET of transcribed files and infers how they
depend on one another (imports, calls, class usage) purely from the code text, and
draws a project-level dependency diagram. No file-system access needed.

analyze_project(client, files) -> report dict (shaped for outputs.save_report_bundle,
so the existing web report UI renders it, with the dependency graph in `diagrams`).
"""

from core.analysis import MODEL, _parse_json
from core.limits import fit_text

PROJECT_SYSTEM = (
    "You are given the source of several files from ONE project, each preceded by its "
    "filename. Work out how the files depend on one another, based ONLY on what is in the "
    "code — imports, references, calls, class/function usage. NEVER invent a dependency "
    "that isn't supported by the code.\n"
    "Return ONLY a JSON object with these keys:\n"
    '  "project_name": a short descriptive name for the project as a single word or PascalCase, based on what it does (e.g. "Calculator", "TodoApp"). No spaces or punctuation.\n'
    '  "overview": 2-4 plain-English sentences on what the project does and how the files fit together.\n'
    '  "files": array of {"name": <filename>, "summary": <one sentence on that file\'s role>}.\n'
    '  "dependencies": array of {"from": <filename>, "to": <filename>, "why": <short reason, e.g. "imports config">}. Only real edges; empty array if the files are independent.\n'
    '  "mermaid": a Mermaid "graph LR" of the dependencies. Give every node a SAFE id (letters/'
    "digits only) and put the filename as a QUOTED label, e.g.  F1[\"main.py\"] --> F2[\"utils.py\"]. "
    "Never put a filename with a dot directly as a node id. Add a short edge label where useful.\n"
    "Return only the raw JSON object — no code fences, no commentary."
)


def analyze_project(client, files: list) -> dict:
    """files: list of {'name': str, 'code': str}. Returns a report dict."""
    per = max(4000, 300000 // max(len(files), 1))
    blocks = [f"===== FILE: {f['name']} =====\n{fit_text(f['code'], per)}" for f in files if f.get("code")]
    joined = "\n\n".join(blocks)
    msg = client.messages.create(
        model=MODEL, max_tokens=4096, system=PROJECT_SYSTEM,
        messages=[{"role": "user", "content": joined}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    data = _parse_json(text) or {}
    return _assemble_project(files, data)


def _assemble_project(files: list, data: dict) -> dict:
    project_name = str(data.get("project_name", "")).strip()
    overview = str(data.get("overview", "")).strip() or "(no overview produced)"
    fsum = data.get("files", []) if isinstance(data.get("files"), list) else []
    deps = data.get("dependencies", []) if isinstance(data.get("dependencies"), list) else []
    mermaid = str(data.get("mermaid", "")).strip()

    lines = []
    if fsum:
        lines.append("Files")
        for f in fsum:
            if isinstance(f, dict):
                lines.append(f"- {f.get('name', '?')}: {f.get('summary', '')}".rstrip())
    if deps:
        lines.append("")
        lines.append("Dependencies")
        for d in deps:
            if isinstance(d, dict):
                why = f" ({d['why']})" if d.get("why") else ""
                lines.append(f"- {d.get('from', '?')} → {d.get('to', '?')}{why}")
    elif fsum:
        lines.append("")
        lines.append("No cross-file dependencies detected — the files appear independent.")
    tech = "\n".join(lines) or "n/a"

    if mermaid:
        body_md = mermaid if mermaid.lstrip().startswith("```") else f"```mermaid\n{mermaid}\n```"
        diagrams = f"**Dependency graph**\n{body_md}"   # labelled so it renders as an image (not raw) in the report
    else:
        diagrams = ""

    manifest = "Files in this project:\n" + "\n".join(f"- {f['name']}" for f in files)
    return {
        "language": "Project",
        "project_name": project_name,
        "overview": overview,
        "errors": "None",
        "tech_stack": tech,
        "diagrams": diagrams,
        "extension": "txt",
        "code": manifest,
    }
