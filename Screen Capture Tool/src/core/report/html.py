import base64
import re
from pathlib import Path
from xml.sax.saxutils import escape

from core.diagrams import svg

LOGO = Path(__file__).resolve().parents[2] / "webapp" / "static" / "ledelsea_logo_t.png"
SEV_CLASS = {"critical": "crit", "high": "high", "medium": "med", "low": "low", "info": "info"}
STATUS_CLASS = {"End of life": "crit", "Legacy — no upgrade path": "med", "Extended support only": "med",
                "Ends within 12 months": "med", "Supported": "ok", "Version not confirmed": "info"}
BUCKET_CLASS = {"good to go": "ok", "patch": "med", "rebuild": "crit"}

CSS = """
:root{--ink:#2A2521;--muted:#6F655C;--line:#E6DDD5;--copper:#BE6E4A;--copper-soft:#F7ECE5;--blue:#2E7DB0;--bg:#FFFFFF}
*{box-sizing:border-box}body{margin:0;background:#F6F3F0;color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
.page{max-width:1120px;margin:0 auto;background:var(--bg);padding:48px 56px 64px}
.cover{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid var(--copper);padding-bottom:22px;margin-bottom:28px}
.cover img{height:64px}.cover .meta{text-align:right;color:var(--muted);font-size:13px}
h1{font-size:30px;margin:6px 0 4px;letter-spacing:-.01em}h1 small{display:block;font-size:15px;color:var(--muted);font-weight:500}
h2{font-size:21px;margin:42px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line);color:var(--ink)}
h2 .n{color:var(--copper);margin-right:8px}h3{font-size:15px;margin:22px 0 8px}
nav.toc{columns:2;font-size:13px;margin:0 0 10px;padding:12px 18px;background:#FBF8F5;border:1px solid var(--line);border-radius:8px}
nav.toc a{color:var(--ink);text-decoration:none;display:block;padding:2px 0}nav.toc a:hover{color:var(--copper)}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:22px;align-items:center;padding:18px 22px;border-radius:12px;background:var(--copper-soft);border:1px solid #EBD3C5;margin:6px 0 16px}
.verdict .big{font-size:30px;font-weight:800;line-height:1.1}.verdict .bucket{text-transform:uppercase;letter-spacing:.06em;font-size:12px;font-weight:700}
.verdict .facts{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:13px}.verdict .facts b{color:var(--ink)}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;margin:14px 0}
.kv div{border:1px solid var(--line);border-radius:8px;padding:9px 12px}.kv span{display:block;font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.kv b{font-size:16px}
table{width:100%;border-collapse:collapse;margin:8px 0 14px;font-size:13px}th{text-align:left;background:#FBF8F5;color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}table.small{font-size:12px}td code{font-size:11px;background:#F4F1EE;padding:1px 4px;border-radius:4px;word-break:break-all}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11.5px;font-weight:700}
.crit{background:#FDE2E1;color:#9B1C1C}.high{background:#FDE7DA;color:#A34514}.med{background:#FFF1D6;color:#7A5200}.low{background:#E8F1FB;color:#1D4F86}
.info{background:#EFEFF2;color:#55555C}.ok{background:#E3F5E8;color:#1F7A3A}
td.score{font-weight:700}td.s-good{color:#1F7A3A}td.s-fair{color:#8A6400}td.s-poor{color:#B4531B}td.s-crit{color:#9B1C1C}
.matrix{border-collapse:separate;border-spacing:4px;width:auto;table-layout:fixed}.matrix th:first-child{width:70px}.matrix td{width:118px;height:54px;text-align:center;border-radius:6px;font-size:11px;border:none}
.matrix th{background:none;text-transform:none;text-align:center}.m-low{background:#E3F5E8}.m-medium{background:#FFF1D6}.m-high{background:#FDE2E1}.m-critical{background:#F4B4B0}
figure{margin:18px 0;padding:12px;border:1px solid var(--line);border-radius:10px;overflow-x:auto;background:#fff}
figure svg{max-width:100%;height:auto}figcaption{font-size:12.5px;color:var(--muted);margin-top:6px}
.tw{overflow-x:auto;max-width:100%}ul{padding-left:20px}li{margin:3px 0}
footer{margin-top:48px;border-top:1px solid var(--line);padding-top:12px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between}
@media print{body{background:#fff}.page{padding:0;max-width:none}h2{page-break-before:always}figure{page-break-inside:avoid}nav.toc{display:none}}
@media (max-width:760px){.page{padding:24px 16px}nav.toc{columns:1}.tw table{min-width:640px}.verdict{grid-template-columns:1fr}.cover{flex-direction:column;gap:12px}.cover .meta{text-align:left}}
"""


def _md(text):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(str(text)))


def _grade(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    return "s-good" if v >= 80 else "s-fair" if v >= 60 else "s-poor" if v >= 40 else "s-crit"


def _cell(val, i, block):
    txt = escape(str(val))
    if block.get("sev_col") == i:
        key = str(val).split(" ")[0].lower()
        return f'<td><span class="pill {SEV_CLASS.get(key, "info")}">{txt}</span></td>'
    if block.get("status_col") == i:
        return f'<td><span class="pill {STATUS_CLASS.get(str(val), "info")}">{txt}</span></td>'
    if block.get("score_col") == i or i in (block.get("score_cols") or []):
        return f'<td class="score {_grade(val)}">{txt}</td>'
    if i == 3 and block.get("head", [None] * 4)[3:4] == ["Evidence"] and val:
        return f"<td><code>{txt}</code></td>"
    return f"<td>{txt}</td>"


def _block(b, diagrams):
    t = b["type"]
    if t == "p":
        return f"<p>{_md(b['text'])}</p>"
    if t == "h":
        return f"<h3>{escape(b['text'])}</h3>"
    if t == "bullets":
        return "<ul>" + "".join(f"<li>{_md(i)}</li>" for i in b["items"]) + "</ul>"
    if t == "kv":
        return '<div class="kv">' + "".join(f"<div><span>{escape(k)}</span><b>{escape(str(v))}</b></div>" for k, v in b["items"]) + "</div>"
    if t == "table":
        if not b["rows"]:
            return '<p class="muted">None.</p>'
        head = "".join(f"<th>{escape(h)}</th>" for h in b["head"])
        rows = "".join("<tr>" + "".join(_cell(v, i, b) for i, v in enumerate(r)) + "</tr>" for r in b["rows"])
        return (f'<div class="tw"><table class="{"small" if b.get("small") else ""}"><thead><tr>{head}</tr></thead>'
                f'<tbody>{rows}</tbody></table></div>')
    if t == "verdict":
        v = b["verdict"] or {}
        cls = BUCKET_CLASS.get(v.get("bucket"), "info")
        return (f'<div class="verdict"><div><div class="big">{escape(v.get("label", "No verdict"))}</div>'
                f'<span class="pill {cls} bucket">{escape(v.get("bucket", ""))}</span></div>'
                f'<div class="facts"><span>Overall score <b>{b.get("overall", "n/a")}/100</b></span>'
                f'<span>Total risk <b>{escape(b["total_risk"]["level"].title())}</b></span>'
                f'<span>Confidence <b>{escape(b["confidence"]["level"].title())}</b></span></div></div>')
    if t == "matrix":
        levels = lambda l, i: "critical" if l * i >= 20 else "high" if l * i >= 12 else "medium" if l * i >= 6 else "low"
        rows = []
        for ri, row in enumerate(b["cells"]):
            like = 5 - ri
            cells = "".join(f'<td class="m-{levels(like, ci + 1)}" title="{escape(", ".join(names))}">'
                            f'{"<b>" + str(len(names)) + "</b><br>" + escape(", ".join(names[:2])) + ("…" if len(names) > 2 else "") if names else ""}</td>'
                            for ci, names in enumerate(row))
            rows.append(f"<tr><th>{like}</th>{cells}</tr>")
        foot = "<tr><th></th>" + "".join(f"<th>{i}</th>" for i in range(1, 6)) + "</tr>"
        return (f'<div class="tw"><table class="matrix"><tr><th>Likelihood</th><th colspan="5">Impact →</th></tr>'
                f'{"".join(rows)}{foot}</table></div>')
    if t == "diagram":
        d = diagrams.get(b["id"])
        if not d:
            return ""
        from .content import DIAGRAM_NOTES
        return f'<figure>{svg(d, title=False)}<figcaption><b>{escape(d["title"])}.</b> {escape(DIAGRAM_NOTES.get(d["kind"], ""))}</figcaption></figure>'
    if t == "diagrams":
        from .content import DIAGRAM_NOTES
        ds = [d for d in diagrams.values() if d["kind"] == b["kind"]][: b.get("limit", 4)]
        return "".join(f'<figure>{svg(d, title=False)}<figcaption><b>{escape(d["title"])}.</b> '
                       f'{escape(DIAGRAM_NOTES.get(d["kind"], ""))}</figcaption></figure>' for d in ds)
    return ""


def render(report: dict, diagrams: dict) -> str:
    logo = base64.b64encode(LOGO.read_bytes()).decode() if LOGO.exists() else ""
    logo_html = f'<img alt="Ledelsea" src="data:image/png;base64,{logo}">' if logo else "<b>Ledelsea</b>"
    toc = "".join(f'<a href="#{s["id"]}">{i}. {escape(s["title"])}</a>' for i, s in enumerate(report["sections"], 1))
    body = []
    for i, s in enumerate(report["sections"], 1):
        body.append(f'<section id="{s["id"]}"><h2><span class="n">{i}</span>{escape(s["title"])}</h2>'
                    + "".join(_block(b, diagrams) for b in s["blocks"]) + "</section>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(report["program"])} — Application Assessment Report</title><style>{CSS}</style></head><body><div class="page">'
            f'<div class="cover"><div>{logo_html}'
            f'<h1>{escape(report["program"])}<small>Application Assessment Report</small></h1></div>'
            f'<div class="meta">Prepared for<br><b>{escape(report["client"])}</b><br>by {escape(report["prepared_by"])}<br>'
            f'{escape(report["date"])}</div></div><nav class="toc">{toc}</nav>{"".join(body)}'
            f'<footer><span>Ledelsea · Application Assessment Report</span><span>{escape(report["date"])} · '
            f'confidential — prepared for {escape(report["client"])}</span></footer></div></body></html>')
