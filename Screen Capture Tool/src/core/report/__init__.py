import io
import zipfile

from core import robust
from core.diagrams import all_diagrams, drawio, vsdx

from . import docx_report, html
from .content import build


def generate(store, *, rescan=True, client=None, today=None) -> dict:
    kwargs = {"client": client} if client else {}
    report = build(store, rescan=rescan, today=today, **kwargs)
    diagrams = {d["id"]: d for d in all_diagrams(store)}
    return {"report": report, "diagrams": diagrams}


def html_report(store, **kw) -> str:
    g = generate(store, **kw)
    return html.render(g["report"], g["diagrams"])


def docx_bytes(store, **kw) -> bytes:
    g = generate(store, **kw)
    return docx_report.render(g["report"], g["diagrams"])


def package(store, **kw) -> dict:
    g = generate(store, **kw)
    slug = store.info["slug"]
    ds = list(g["diagrams"].values())
    files = {
        f"{slug}_holistic_review.html": html.render(g["report"], g["diagrams"]).encode(),
        f"{slug}_holistic_review.docx": docx_report.render(g["report"], g["diagrams"]),
        f"{slug}_diagrams.vsdx": vsdx(ds, f"{store.info['name']} diagrams"),
        f"{slug}_diagrams.drawio": drawio(ds).encode(),
    }
    out = store.exports_dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        robust.write_bytes(out / name, data)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return {"dir": str(out), "files": sorted(files), "zip": buf.getvalue(), "verdict": g["report"]["verdict"]}


__all__ = ["build", "docx_bytes", "generate", "html_report", "package"]
