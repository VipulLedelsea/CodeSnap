import io
import zipfile

from core import robust
from core.diagrams import all_diagrams, drawio, vsdx

from . import docx_report, html
from .content import build


def generate(store, *, rescan=True, client=None, today=None, pdf=None) -> dict:
    kwargs = {"client": client} if client else {}
    from .wording import scrub
    report = scrub(build(store, rescan=rescan, today=today, **kwargs))
    diagrams = {d["id"]: scrub(d) for d in all_diagrams(store)}
    return {"report": report, "diagrams": diagrams}


def html_report(store, **kw) -> str:
    g = generate(store, **kw)
    return html.render(g["report"], g["diagrams"])


def docx_bytes(store, **kw) -> bytes:
    from . import template_docx
    g = generate(store, **kw)
    return template_docx.render(store, g["report"], g["diagrams"])


def pdf_from_docx(docx: bytes):
    """The Word report as PDF, through LibreOffice or Microsoft Word when one is installed; None otherwise."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "report.docx", Path(d) / "report.pdf"
        src.write_bytes(docx)
        for exe in (shutil.which("soffice"), shutil.which("libreoffice"),
                    "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
            if not exe or not Path(exe).exists():
                continue
            try:
                subprocess.run([exe, f"-env:UserInstallation=file://{d}/lo", "--headless", "--convert-to", "pdf",
                                "--outdir", d, str(src)], capture_output=True, timeout=240)
            except Exception:  # noqa: BLE001
                continue
            if out.exists():
                return out.read_bytes()
        try:
            from docx2pdf import convert   # drives Microsoft Word on macOS / Windows
            convert(str(src), str(out))
            if out.exists():
                return out.read_bytes()
        except Exception:  # noqa: BLE001
            pass
    return None


PDF_MISSING = ("PDF export needs LibreOffice (free) or Microsoft Word on this computer. Until then, open the Word "
               "report and use File > Save As > PDF.")


def package(store, **kw) -> dict:
    g = generate(store, **kw)
    slug = store.info["slug"]
    ds = list(g["diagrams"].values())
    from . import template_docx
    docx = template_docx.render(store, g["report"], g["diagrams"])
    files = {
        f"{slug}_assessment_report.html": html.render(g["report"], g["diagrams"]).encode(),
        f"{slug}_assessment_report.docx": docx,
        f"{slug}_diagrams.vsdx": vsdx(ds, f"{store.info['name']} diagrams"),
        f"{slug}_diagrams.drawio": drawio(ds).encode(),
    }
    pdf = pdf_from_docx(docx) if kw.get("pdf", True) else None
    if pdf:
        files[f"{slug}_assessment_report.pdf"] = pdf
    out = store.exports_dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        robust.write_bytes(out / name, data)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return {"dir": str(out), "files": sorted(files), "zip": buf.getvalue(), "verdict": g["report"]["verdict"]}


def waiting(store) -> int:
    return sum(1 for a in store.artifacts() if a["status"] == "captured")


def cached_package(store, force: bool = False) -> dict:
    """The program report, built once when every capture is analysed and reused until something it depends on changes."""
    slug = store.info["slug"]
    out = store.exports_dir / "report"
    names = [f"{slug}_assessment_report.html", f"{slug}_assessment_report.docx", f"{slug}_diagrams.vsdx",
             f"{slug}_diagrams.drawio", f"{slug}_assessment_report_package.zip"]
    fresh = store.get_meta("report_stamp") == store.model_stamp() and all((out / n).exists() for n in names)
    if fresh and not force:
        return {"dir": str(out), "files": names, "built": False}
    pdf = out / f"{slug}_assessment_report.pdf"
    if pdf.exists():
        pdf.unlink()        # never serve a PDF of an older report
    pkg = package(store, rescan=True)
    robust.write_bytes(out / names[-1], pkg["zip"])
    store.set_meta("report_stamp", store.model_stamp())
    store.set_meta("report_built_at", __import__("datetime").datetime.now().isoformat(timespec="seconds"))
    return {"dir": str(out), "files": names, "built": True, "verdict": pkg["verdict"]}


__all__ = ["PDF_MISSING", "pdf_from_docx", "build", "cached_package", "docx_bytes", "generate", "html_report", "package", "waiting"]
