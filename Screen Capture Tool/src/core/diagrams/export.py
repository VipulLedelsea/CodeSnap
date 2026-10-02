import io
import json
import re
import zipfile

from core import robust

from .build import all_diagrams, diagram_coverage
from .render import drawio, png, svg, vsdx


def _fname(d):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{d['id']}_{d['title']}")[:80]


def summary(diagrams):
    return [{"id": d["id"], "kind": d["kind"], "title": d["title"], "nodes": len(d["nodes"]),
             "edges": sum(1 for e in d["edges"] if not e.get("lifeline")), "width": d["width"], "height": d["height"],
             "truncated": d.get("truncated", False)} for d in diagrams]


def bundle(store, diagrams=None, with_png=True) -> bytes:
    diagrams = diagrams or all_diagrams(store)
    from core.report import _redactor
    redactor = _redactor(store)
    diagrams = redactor.map(diagrams)
    slug = store.info["slug"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}_diagrams.vsdx", vsdx(diagrams, _redactor(store)(f"{store.info['name']} diagrams")))
        z.writestr(f"{slug}_diagrams.drawio", drawio(diagrams))
        for d in diagrams:
            z.writestr(f"svg/{_fname(d)}.svg", svg(d))
            if with_png:
                z.writestr(f"png/{_fname(d)}.png", png(d))
        z.writestr("coverage.json", json.dumps({"diagrams": summary(diagrams),
                                                "coverage": redactor.map(diagram_coverage(store, diagrams))}, indent=2))
    return buf.getvalue()


def save(store) -> dict:
    from core.report import _redactor
    diagrams = _redactor(store).map(all_diagrams(store))
    out = store.exports_dir / "diagrams"
    out.mkdir(parents=True, exist_ok=True)
    robust.write_bytes(out / f"{store.info['slug']}_diagrams.vsdx", vsdx(diagrams, _redactor(store)(f"{store.info['name']} diagrams")))
    robust.write_text(out / f"{store.info['slug']}_diagrams.drawio", drawio(diagrams))
    for d in diagrams:
        robust.write_text(out / f"{_fname(d)}.svg", svg(d))
    return {"dir": str(out), "diagrams": summary(diagrams), "coverage": diagram_coverage(store, diagrams)}
