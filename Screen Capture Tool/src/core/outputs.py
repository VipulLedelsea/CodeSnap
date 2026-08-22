"""Output savers — shared by hotkey_capture.py and the agent.

Pure functions (no prompts, no I/O beyond writing the file) so both the
interactive hotkey app and the agent's save_output tool can reuse them.
"""

from pathlib import Path


def safe_ext(ext: str) -> str:
    """Allow only a short alphanumeric extension; fall back to txt."""
    ext = (ext or "").strip().lstrip(".").lower()
    return ext if ext.isalnum() and 1 <= len(ext) <= 10 else "txt"


def strip_code_fences(text: str) -> str:
    """Remove a wrapping ```lang ... ``` fence if one was added anyway."""
    lines = (text or "").splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].lstrip().startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines)


def save_source_file(code: str, dest_dir, name: str, ext: str) -> Path:
    """Write code (fences stripped) to dest_dir/<name>.<ext>. Returns the path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{name}.{safe_ext(ext)}"
    out.write_text(strip_code_fences(code))
    return out


def save_text(text: str, dest_dir, name: str) -> Path:
    """Write plain text to dest_dir/<name>.txt."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{name}.txt"
    out.write_text(text or "")
    return out


def save_docx(result, dest_dir, name: str) -> Path:
    """Build a .docx from a result dict ({extracted_text}) and save it."""
    from .analysis import build_docx  # local import keeps python-docx optional
    if isinstance(result, str):
        result = {"extracted_text": result}
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{name}.docx"
    build_docx(result).save(out)
    return out


def save_report_bundle(report: dict, dest_dir, name: str, code_name: str = None):
    """Write a code file + a report_<name>.json bundle (language, overview, errors,
    tech_stack, code). Returns the code file Path. Used so the web UI can show the
    full report, not just the raw code."""
    import json
    from datetime import datetime
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = safe_ext(report.get("extension", "txt"))
    code = strip_code_fences(report.get("code", ""))
    code_path = dest_dir / f"{code_name or name}.{ext}"
    code_path.write_text(code)
    meta = {
        "language": report.get("language", ""),
        "overview": report.get("overview", ""),
        "errors": report.get("errors", ""),
        "tech_stack": report.get("tech_stack", ""),
        "diagrams": report.get("diagrams", ""),
        "extension": ext,
        "code": code,
        "code_file": code_path.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "members": report.get("members", []),
    }
    (dest_dir / f"{name}.json").write_text(json.dumps(meta, indent=2))
    return code_path


def report_docx(report: dict, dest_path, images=None):
    """Build a polished .docx report: overview, errors, tech review, and the rendered
    diagram images. No code section (dedicated code download) and no raw Mermaid."""
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    import base64, io
    COPPER = RGBColor(0xBE, 0x6E, 0x4A)
    INK = RGBColor(0x2B, 0x26, 0x22)
    MUTED = RGBColor(0x6E, 0x64, 0x5C)
    GREEN = RGBColor(0x3B, 0x8F, 0x5E)

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"; normal.font.size = Pt(11); normal.font.color.rgb = INK

    title = doc.add_paragraph()
    tr = title.add_run("Code Capture report")
    tr.bold = True; tr.font.size = Pt(24); tr.font.color.rgb = INK
    title.paragraph_format.space_after = Pt(2)

    meta = (report.get("language") or report.get("extension") or "").strip()
    sub = doc.add_paragraph()
    sr = sub.add_run((meta + "  \u00b7  " if meta else "") + "Compiler-verified by Code Capture")
    sr.italic = True; sr.font.size = Pt(10.5); sr.font.color.rgb = MUTED
    sub.paragraph_format.space_after = Pt(10)

    def heading(text):
        h = doc.add_paragraph()
        hr = h.add_run(text); hr.bold = True; hr.font.size = Pt(14); hr.font.color.rgb = COPPER
        h.paragraph_format.space_before = Pt(14); h.paragraph_format.space_after = Pt(3)

    def body(text, color=None):
        p = doc.add_paragraph(); r = p.add_run(str(text) if text else "")
        if color:
            r.font.color.rgb = color
        p.paragraph_format.space_after = Pt(6)

    heading("Overview"); body(report.get("overview", ""))
    heading("Errors found")
    errs = report.get("errors", "None")
    body(errs, GREEN if str(errs).strip().lower() == "none" else None)
    heading("Tech-stack review"); body(report.get("tech_stack", "n/a"))
    if images:
        heading("Diagrams")
        for item in images:
            label = item.get("label") if isinstance(item, dict) else None
            b64 = item.get("data") if isinstance(item, dict) else item
            try:
                raw = base64.b64decode(b64)
                if label:
                    lp = doc.add_paragraph(); lr = lp.add_run(str(label))
                    lr.bold = True; lr.font.color.rgb = INK
                    lp.paragraph_format.space_before = Pt(6); lp.paragraph_format.space_after = Pt(2)
                    lp.paragraph_format.keep_with_next = True   # keep the caption on the same page as its diagram
                # size to fit the page without upscaling small diagrams
                try:
                    from PIL import Image as _PILImage
                    iw, ih = _PILImage.open(io.BytesIO(raw)).size
                    dpi, maxw, maxh = 150.0, 6.0, 7.0
                    nw, nh = iw / dpi, ih / dpi
                    scale = min(maxw / max(nw, 0.1), maxh / max(nh, 0.1), 1.0)
                    doc.add_picture(io.BytesIO(raw), width=Inches(max(nw * scale, 1.2)))
                except Exception:  # noqa: BLE001
                    doc.add_picture(io.BytesIO(raw), width=Inches(5.0))
            except Exception:  # noqa: BLE001
                pass
    doc.save(str(dest_path))
    return dest_path
