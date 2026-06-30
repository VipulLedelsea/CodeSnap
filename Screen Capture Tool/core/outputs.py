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
