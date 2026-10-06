import base64
import re
from pathlib import Path
from xml.sax.saxutils import escape

from core.diagrams import svg

LOGO = Path(__file__).resolve().parents[2] / "webapp" / "static" / "ledelsea_logo_t.png"
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


def render_document(data: bytes, diagrams: dict) -> str:
    """Render the issued Word document's content so export formats share one assessment."""
    import io
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from core.diagrams import svg
    document = Document(io.BytesIO(data))

    def paragraph(element, parent):
        p = Paragraph(element, parent)
        text = escape(p.text).replace("\n", "<br>")
        style = (p.style.name if p.style is not None else "").lower()
        tag = "h2" if style.startswith("heading 1") else "h3" if style.startswith("heading") else "p"
        images = []
        for blip in element.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid in document.part.related_parts:
                part = document.part.related_parts[rid]
                images.append(f'<img alt="Assessment figure" style="max-width:100%" src="data:{part.content_type};base64,{base64.b64encode(part.blob).decode()}">')
        ink = "996300" if p.text.startswith("Needs changes") else {"RED": "B42318", "YELLOW": "996300", "GREEN": "176B3A"}.get(p.text.split(" ", 1)[0])
        status_style = f' style="color:#{ink};font-weight:700"' if ink else ''
        return f'<{tag}{status_style}>{text}</{tag}>' + ''.join(images) if text or images else ""

    def table(element, parent):
        t = Table(element, parent)
        rows = []
        for index, row in enumerate(t.rows):
            cells, seen = [], set()
            for cell in row.cells:
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                span = cell._tc.grid_span
                shade = cell._tc.xpath('./w:tcPr/w:shd')
                fill = shade[0].get(qn('w:fill')) if shade else None
                cell_style = f' style="background:#{fill}"' if fill and re.fullmatch(r'[0-9A-Fa-f]{6}', fill) else ''
                tag = 'th' if index == 0 else 'td'
                cells.append(f'<{tag} colspan="{span}"{cell_style}>{blocks(cell._tc, cell)}</{tag}>')
            rows.append('<tr>' + ''.join(cells) + '</tr>')
        return '<div class="tw"><table>' + ''.join(rows) + '</table></div>'

    def blocks(element, parent):
        return ''.join(paragraph(child, parent) if child.tag == qn('w:p') else
                       table(child, parent) if child.tag == qn('w:tbl') else '' for child in element)

    figures = ''.join(f'<figure>{svg(d)}<figcaption>{escape(d["title"])}</figcaption></figure>' for d in diagrams.values())
    title = escape(document.core_properties.title or 'Application Assessment Report')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><style>{CSS} .page p{{white-space:pre-wrap;overflow-wrap:anywhere}} '
            f'th{{text-transform:none;letter-spacing:normal;background:#ECEFF1;color:#111}} '
            f'h2{{border:0}} td p,th p{{margin:0}}</style></head><body><main class="page">'
            f'{blocks(document.element.body, document)}<section><h2>Source-derived diagrams</h2>{figures}</section></main></body></html>')
