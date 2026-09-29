import io
import math
import zipfile
from xml.sax.saxutils import escape, quoteattr

from .layout import LINE_H, PAD

STYLE = {
    "system": ("#FBF6F2", "#BE6E4A"), "actor": ("#E4EFF6", "#2E7DB0"), "external_system": ("#F2F2F5", "#6E6E73"),
    "data_store": ("#EAF4EE", "#3B8F5E"), "table": ("#EAF4EE", "#3B8F5E"), "missing": ("#FCFAF8", "#A99C90"),
    "class": ("#FFFFFF", "#2A2521"), "component": ("#FFFFFF", "#2A2521"), "participant": ("#FFFFFF", "#2A2521"),
}
INK, MUTED, EDGE = "#2A2521", "#857A70", "#5E5750"


GROUP_STYLE = {"lane": ("#FAF7F4", "#D9CFC6", "#BE6E4A", 13), "group": ("#FFFFFF", "#CFC5BC", "#857A70", 11),
               "bar": ("#F4F1EE", "#D9CFC6", "#2A2521", 12)}


def _style(n):
    if n.get("fill") or n.get("chip"):
        return n.get("fill") or "#FFFFFF", n.get("stroke") or "#CFC5BC"
    if n.get("compact"):
        return ("#FCFAF8", "#A99C90") if n.get("dashed") else ("#FFFFFF", "#8F847A")
    fill, stroke = STYLE.get(n.get("kind"), STYLE["class"])
    return fill, ("#A99C90" if n.get("dashed") else stroke)


def _svg_group(g):
    fill, stroke, ink, size = GROUP_STYLE[g["style"]]
    dash = ' stroke-dasharray="6,4"' if g.get("dashed") else ""
    tx, ty = (g["x"] + 12, g["y"] + 21) if g["style"] == "bar" else (g["x"] + 10, g["y"] + (19 if g["style"] == "lane" else 15))
    return (f'<rect x="{g["x"]:.1f}" y="{g["y"]:.1f}" width="{g["w"]:.1f}" height="{g["h"]:.1f}" rx="8" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.1"{dash}/>'
            f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{size}" font-weight="700" fill="{ink}">{escape(g["title"])}</text>')


def _svg_compact(n):
    fill, stroke = _style(n)
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    dash = ' stroke-dasharray="5,4"' if n.get("dashed") else ""
    if n.get("chip"):
        ink = n.get("ink") or n.get("stroke") or INK
        return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
                f'<text x="{x + w / 2:.1f}" y="{y + 16:.1f}" text-anchor="middle" font-size="10.5" fill="{ink}">{escape(n["title"])}</text>')
    out = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"{dash}/>']
    ic = n.get("icon")
    if ic:
        iy = y + (h - 20) / 2
        out.append(f'<rect x="{x + 8:.1f}" y="{iy:.1f}" width="22" height="20" rx="4" fill="{ic["color"]}"/>'
                   f'<text x="{x + 19:.1f}" y="{iy + 13.5:.1f}" text-anchor="middle" font-size="8" font-weight="700" fill="#fff">{escape(ic["text"])}</text>')
    ty = y + (18 if n.get("sub") else h / 2 + 4)
    out.append(f'<text x="{x + 36:.1f}" y="{ty:.1f}" font-size="11.5" font-weight="700" fill="{INK}">{escape(n["title"])}</text>')
    if n.get("sub"):
        out.append(f'<text x="{x + 36:.1f}" y="{y + 33:.1f}" font-size="10" fill="{MUTED}">{escape(str(n["sub"]))}</text>')
    b = n.get("badge")
    if b:
        out.append(f'<rect x="{x + w - 42:.1f}" y="{y + 5:.1f}" width="36" height="14" rx="7" fill="{b["color"]}"/>'
                   f'<text x="{x + w - 24:.1f}" y="{y + 15:.1f}" text-anchor="middle" font-size="8" font-weight="700" fill="#fff">{escape(b["text"])}</text>')
    return "".join(out)


def blocks(n):
    head = [l for l in ((n.get("stereotype") and f"«{n['stereotype']}»"), n["title"]) if l]
    head_h = LINE_H * len(head) + 2 * PAD - 4
    out = [{"lines": head, "y": 0, "h": head_h, "align": "center", "head": True}]
    y = head_h
    for sec in n.get("sections") or []:
        h = LINE_H * max(1, len(sec)) + PAD
        out.append({"lines": sec, "y": y, "h": h, "align": "left" if n.get("kind") == "class" else "center"})
        y += h
    return out


def _label_pos(pts):
    segs = list(zip(pts, pts[1:]))
    horiz = [(a, b) for a, b in segs if abs(a[1] - b[1]) < 1]
    a, b = max(horiz or segs, key=lambda ab: abs(ab[0][0] - ab[1][0]) + abs(ab[0][1] - ab[1][1]))
    if horiz and len(pts) == 4 and (a, b) == segs[-1]:
        return a[0] + (b[0] - a[0]) * 0.55, a[1] - 5
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 5


def _msg_pos(e):
    return min(p[0] for p in e["points"]) + 6, e["points"][0][1] - 5


def svg(scene: dict, title=True) -> str:
    W, H = scene["width"], scene["height"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{EDGE}"/></marker>'
           '<marker id="open" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           f'<path d="M0,0 L10,5 L0,10" fill="none" stroke="{EDGE}" stroke-width="1.4"/></marker>'
           '<marker id="triangle" viewBox="0 0 12 12" refX="12" refY="6" markerWidth="11" markerHeight="11" orient="auto-start-reverse">'
           f'<path d="M0,0 L12,6 L0,12 z" fill="#fff" stroke="{EDGE}" stroke-width="1.2"/></marker></defs>',
           f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>']
    if title:
        out.append(f'<text x="30" y="26" font-size="15" font-weight="700" fill="{INK}">{escape(scene.get("title", ""))}</text>')
    for g in scene.get("groups") or []:
        out.append(_svg_group(g))
    for e in scene["edges"]:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in e["points"])
        dash = ' stroke-dasharray="5,4"' if e.get("style") == "dashed" else ""
        head = e.get("head", "arrow")
        marker = "" if head == "none" else f' marker-end="url(#{head})"'
        color = "#C9BFB6" if e.get("lifeline") else EDGE
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.2"{dash}{marker}/>')
        if e.get("label"):
            x, y = _msg_pos(e) if e.get("message") else _label_pos(e["points"])
            anchor = "start" if e.get("message") else "middle"
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="10.5" fill="{MUTED}" '
                       f'paint-order="stroke" stroke="#fff" stroke-width="3">{escape(e["label"])}</text>')
    for n in scene["nodes"]:
        if n.get("compact"):
            out.append(_svg_compact(n))
            continue
        fill, stroke = _style(n)
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        dash = ' stroke-dasharray="5,4"' if n.get("dashed") else ""
        rx = 14 if n.get("kind") == "actor" else 6 if n.get("kind") in ("system", "external_system") else 3
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1.3"{dash}/>')
        for b in blocks(n):
            if not b.get("head"):
                out.append(f'<line x1="{x:.1f}" y1="{y + b["y"]:.1f}" x2="{x + w:.1f}" y2="{y + b["y"]:.1f}" stroke="{stroke}" stroke-width="0.8"/>')
            for i, line in enumerate(b["lines"]):
                ty = y + b["y"] + PAD + 10 + i * LINE_H
                bold = b.get("head") and i == len(b["lines"]) - 1
                italic = b.get("head") and line.startswith("«")
                tx, anchor = (x + w / 2, "middle") if b["align"] == "center" else (x + PAD, "start")
                weight = ' font-weight="700"' if bold else ""
                style = ' font-style="italic" font-size="10.5"' if italic else ""
                color = MUTED if italic else INK
                out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" fill="{color}"{weight}{style}>{escape(str(line))}</text>')
    out.append("</svg>")
    return "".join(out)


def _font(size, bold=False):
    from PIL import ImageFont
    names = (["Helvetica-Bold.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else
             ["Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf"])
    dirs = ["/System/Library/Fonts/", "/System/Library/Fonts/Supplemental/", "/Library/Fonts/",
            "/usr/share/fonts/truetype/dejavu/", ""]
    for d in dirs:
        for nm in names:
            try:
                return ImageFont.truetype(d + nm, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _dashed(draw, pts, fill, width, dash=6, gap=4):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            continue
        dx, dy, t = (x2 - x1) / length, (y2 - y1) / length, 0.0
        while t < length:
            e = min(t + dash, length)
            draw.line([(x1 + dx * t, y1 + dy * t), (x1 + dx * e, y1 + dy * e)], fill=fill, width=width)
            t = e + gap


def png(scene: dict, scale: float = 2.0) -> bytes:
    from PIL import Image, ImageDraw
    W, H = int(scene["width"] * scale), int(scene["height"] * scale)
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    f, fb, fs, ft = _font(int(12 * scale)), _font(int(12 * scale), True), _font(int(10.5 * scale)), _font(int(15 * scale), True)
    S = lambda v: v * scale
    d.text((S(30), S(12)), scene.get("title", ""), fill=INK, font=ft)
    fg, f8, f10 = _font(int(11 * scale), True), _font(int(8 * scale), True), _font(int(10 * scale))
    for g in scene.get("groups") or []:
        fill, stroke, ink, size = GROUP_STYLE[g["style"]]
        box = [S(g["x"]), S(g["y"]), S(g["x"] + g["w"]), S(g["y"] + g["h"])]
        d.rounded_rectangle(box, radius=S(8), fill=fill)
        if g.get("dashed"):
            (x0, y0, x1, y1) = box
            _dashed(d, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], stroke, max(1, int(scale)))
        else:
            d.rounded_rectangle(box, radius=S(8), outline=stroke, width=max(1, int(scale)))
        gf = _font(int(size * scale), True)
        d.text((S(g["x"] + (12 if g["style"] == "bar" else 10)), S(g["y"] + (8 if g["style"] == "bar" else 5))), g["title"], fill=ink, font=gf)
    for e in scene["edges"]:
        pts = [(S(x), S(y)) for x, y in e["points"]]
        color = "#C9BFB6" if e.get("lifeline") else EDGE
        if e.get("style") == "dashed":
            _dashed(d, pts, color, max(1, int(scale)))
        else:
            d.line(pts, fill=color, width=max(1, int(scale * 1.1)))
        if e.get("head", "arrow") != "none" and len(pts) >= 2:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            ang = math.atan2(y2 - y1, x2 - x1)
            size = S(9 if e.get("head") == "triangle" else 7)
            p1 = (x2 - size * math.cos(ang - 0.45), y2 - size * math.sin(ang - 0.45))
            p2 = (x2 - size * math.cos(ang + 0.45), y2 - size * math.sin(ang + 0.45))
            if e.get("head") == "open":
                d.line([p1, (x2, y2), p2], fill=color, width=max(1, int(scale)))
            else:
                d.polygon([(x2, y2), p1, p2], fill="#FFFFFF" if e.get("head") == "triangle" else color, outline=color)
        if e.get("label"):
            x, y = _msg_pos(e) if e.get("message") else _label_pos(e["points"])
            if e.get("message"):
                y -= 11
            if not e.get("message"):
                w = d.textlength(e["label"], font=fs)
                x, y = S(x) - w / 2, S(y) - S(11)
            else:
                x, y = S(x), S(y)
            d.text((x, y), e["label"], fill=MUTED, font=fs, stroke_width=int(2 * scale), stroke_fill="#FFFFFF")
    for n in scene["nodes"]:
        fill, stroke = _style(n)
        x, y, w, h = S(n["x"]), S(n["y"]), S(n["w"]), S(n["h"])
        if n.get("compact"):
            if n.get("chip"):
                d.rounded_rectangle([x, y, x + w, y + h], radius=S(12), fill=fill, outline=stroke, width=max(1, int(scale)))
                tw = d.textlength(n["title"], font=fs)
                d.text((x + (w - tw) / 2, y + S(5)), n["title"], fill=n.get("ink") or n.get("stroke") or INK, font=fs)
                continue
            if n.get("dashed"):
                d.rounded_rectangle([x, y, x + w, y + h], radius=S(6), fill=fill)
                _dashed(d, [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], stroke, max(1, int(scale)))
            else:
                d.rounded_rectangle([x, y, x + w, y + h], radius=S(6), fill=fill, outline=stroke, width=max(1, int(scale)))
            ic = n.get("icon")
            if ic:
                iy = y + (h - S(20)) / 2
                d.rounded_rectangle([x + S(8), iy, x + S(30), iy + S(20)], radius=S(4), fill=ic["color"])
                tw = d.textlength(ic["text"], font=f8)
                d.text((x + S(19) - tw / 2, iy + S(5)), ic["text"], fill="#FFFFFF", font=f8)
            ty = y + (S(6) if n.get("sub") else (h - S(13)) / 2)
            d.text((x + S(36), ty), n["title"], fill=INK, font=fg)
            if n.get("sub"):
                d.text((x + S(36), y + S(24)), str(n["sub"]), fill=MUTED, font=f10)
            b = n.get("badge")
            if b:
                d.rounded_rectangle([x + w - S(42), y + S(5), x + w - S(6), y + S(19)], radius=S(7), fill=b["color"])
                tw = d.textlength(b["text"], font=f8)
                d.text((x + w - S(24) - tw / 2, y + S(7)), b["text"], fill="#FFFFFF", font=f8)
            continue
        d.rounded_rectangle([x, y, x + w, y + h], radius=S(6), fill=fill, outline=stroke, width=max(1, int(scale * 1.2)))
        for b in blocks(n):
            if not b.get("head"):
                d.line([(x, y + S(b["y"])), (x + w, y + S(b["y"]))], fill=stroke, width=1)
            for i, line in enumerate(b["lines"]):
                bold = b.get("head") and i == len(b["lines"]) - 1
                italic = b.get("head") and str(line).startswith("«")
                font = fb if bold else fs if italic else f
                ty = y + S(b["y"] + PAD + i * LINE_H)
                tw = d.textlength(str(line), font=font)
                tx = x + (w - tw) / 2 if b["align"] == "center" else x + S(PAD)
                d.text((tx, ty), str(line), fill=MUTED if italic else INK, font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _html(n):
    if n.get("compact"):
        ic = n.get("icon")
        head = (f'<span style="background:{ic["color"]};color:#fff;font-size:9px;font-weight:bold;padding:2px 4px;'
                f'border-radius:3px">{escape(ic["text"])}</span>&nbsp;') if ic else ""
        b = n.get("badge")
        tail = (f'&nbsp;<span style="background:{b["color"]};color:#fff;font-size:8px;padding:1px 4px;border-radius:6px">'
                f'{escape(b["text"])}</span>') if b else ""
        sub = f'<br><span style="color:{MUTED};font-size:10px">{escape(str(n["sub"]))}</span>' if n.get("sub") else ""
        return f"{head}<b>{escape(n['title'])}</b>{tail}{sub}" if not n.get("chip") else escape(n["title"])
    parts = []
    if n.get("stereotype"):
        parts.append(f"<i>«{escape(n['stereotype'])}»</i>")
    parts.append(f"<b>{escape(n['title'])}</b>")
    for sec in n.get("sections") or []:
        parts.append("<hr>" + "<br>".join(escape(str(l)) for l in sec))
    return "<br>".join(parts[:2]) + "".join(parts[2:])


def drawio(scenes: list) -> str:
    out = ['<mxfile host="Ledelsea" type="device">']
    for di, sc in enumerate(scenes):
        out.append(f'<diagram id="d{di}" name={quoteattr(sc["title"][:60])}><mxGraphModel dx="0" dy="0" grid="1" '
                   f'gridSize="10" page="1" pageWidth="{sc["width"]}" pageHeight="{sc["height"]}"><root>'
                   '<mxCell id="0"/><mxCell id="1" parent="0"/>')
        ids = {}
        for gi, g in enumerate(sc.get("groups") or []):
            fill, stroke, ink, size = GROUP_STYLE[g["style"]]
            gid = f"g{di}_{gi}"
            ids[g["id"]] = gid
            style = (f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor={ink};"
                     f"verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;fontSize={size};{'dashed=1;' if g.get('dashed') else ''}")
            out.append(f'<mxCell id="{gid}" value={quoteattr(g["title"])} style="{style}" vertex="1" parent="1">'
                       f'<mxGeometry x="{g["x"]:.0f}" y="{g["y"]:.0f}" width="{g["w"]:.0f}" height="{g["h"]:.0f}" as="geometry"/></mxCell>')
        for i, n in enumerate(sc["nodes"]):
            fill, stroke = _style(n)
            cid = f"n{di}_{i}"
            ids[n["id"]] = cid
            align = "align=left;spacingLeft=6;" if n.get("kind") == "class" or (n.get("compact") and not n.get("chip")) else "align=center;"
            style = (f"rounded={1 if n.get('kind') in ('actor', 'system', 'external_system') or n.get('compact') else 0};whiteSpace=wrap;html=1;"
                     f"fillColor={fill};strokeColor={stroke};fontColor={n.get('ink') or INK};"
                     f"verticalAlign={'middle' if n.get('compact') else 'top'};{align}"
                     f"{'dashed=1;' if n.get('dashed') else ''}fontSize=12;")
            out.append(f'<mxCell id="{cid}" value={quoteattr(_html(n))} style="{style}" vertex="1" parent="1">'
                       f'<mxGeometry x="{n["x"]:.0f}" y="{n["y"]:.0f}" width="{n["w"]:.0f}" height="{n["h"]:.0f}" as="geometry"/></mxCell>')
        for j, e in enumerate(sc["edges"]):
            head = {"arrow": "block", "open": "open", "triangle": "block;endFill=0", "none": "none"}[e.get("head", "arrow")]
            style = (f"endArrow={head};html=1;strokeColor={'#C9BFB6' if e.get('lifeline') else EDGE};fontSize=10;"
                     f"fontColor={MUTED};{'dashed=1;' if e.get('style') == 'dashed' else ''}")
            p0, pn = e["points"][0], e["points"][-1]
            mids = "".join(f'<mxPoint x="{x:.0f}" y="{y:.0f}"/>' for x, y in e["points"][1:-1])
            link = "" if e.get("message") or e.get("lifeline") or e["from"] == e["to"] else \
                f' source="{ids.get(e["from"], "")}" target="{ids.get(e["to"], "")}"'
            out.append(f'<mxCell id="e{di}_{j}" value={quoteattr(e.get("label") or "")} style="{style}" edge="1" parent="1"{link}>'
                       f'<mxGeometry relative="1" as="geometry"><mxPoint x="{p0[0]:.0f}" y="{p0[1]:.0f}" as="sourcePoint"/>'
                       f'<mxPoint x="{pn[0]:.0f}" y="{pn[1]:.0f}" as="targetPoint"/>'
                       f'{"<Array as=" + chr(34) + "points" + chr(34) + ">" + mids + "</Array>" if mids else ""}</mxGeometry></mxCell>')
        out.append("</root></mxGraphModel></diagram>")
    out.append("</mxfile>")
    return "".join(out)


_NS = 'xmlns="http://schemas.microsoft.com/office/visio/2012/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xml:space="preserve"'
DPI = 96.0


def _c(name, value, unit=None, formula=None):
    u = f' U="{unit}"' if unit else ""
    f = f" F={quoteattr(formula)}" if formula else ""
    return f'<Cell N="{name}" V="{value}"{u}{f}/>'


def _rect_geo(w, h, ix=0, nofill=0, noline=0):
    return (f'<Section N="Geometry" IX="{ix}">{_c("NoFill", nofill)}{_c("NoLine", noline)}'
            f'<Row T="MoveTo" IX="1">{_c("X", 0)}{_c("Y", 0)}</Row><Row T="LineTo" IX="2">{_c("X", f"{w:.4f}")}{_c("Y", 0)}</Row>'
            f'<Row T="LineTo" IX="3">{_c("X", f"{w:.4f}")}{_c("Y", f"{h:.4f}")}</Row><Row T="LineTo" IX="4">{_c("X", 0)}{_c("Y", f"{h:.4f}")}</Row>'
            f'<Row T="LineTo" IX="5">{_c("X", 0)}{_c("Y", 0)}</Row></Section>')


class _Vsdx:
    def __init__(self, H):
        self.H, self.id, self.shapes = H, 0, []

    def nid(self):
        self.id += 1
        return self.id

    def box(self, x, y, w, h, *, fill=None, line=None, dashed=False, text="", align=1, valign=0, size=12, bold=False,
            italic=False, color=INK, arrow=None, margin=None):
        W, Hh = max(w, 1) / DPI, max(h, 1) / DPI
        pinx, piny = (x + w / 2) / DPI, (self.H - y - h / 2) / DPI
        cells = [_c("PinX", f"{pinx:.4f}"), _c("PinY", f"{piny:.4f}"), _c("Width", f"{W:.4f}"), _c("Height", f"{Hh:.4f}"),
                 _c("LocPinX", f"{W / 2:.4f}", formula="Width*0.5"), _c("LocPinY", f"{Hh / 2:.4f}", formula="Height*0.5"),
                 _c("LineWeight", "0.0125"), _c("LinePattern", 0 if line is None else (2 if dashed else 1)),
                 _c("LineColor", line or "#000000"), _c("FillForegnd", fill or "#FFFFFF"),
                 _c("FillPattern", 0 if fill is None else 1), _c("VerticalAlign", valign),
                 _c("TopMargin", "0.06" if margin is None else margin), _c("BottomMargin", "0.0"),
                 _c("LeftMargin", "0.05" if margin is None else margin), _c("RightMargin", "0.03" if margin is None else margin)]
        style = (1 if bold else 0) | (2 if italic else 0)
        chars = f'<Section N="Character"><Row IX="0">{_c("Size", f"{size / 72:.4f}")}{_c("Color", color)}{_c("Style", style)}</Row></Section>'
        para = f'<Section N="Paragraph"><Row IX="0">{_c("HorzAlign", align)}</Row></Section>'
        geo = _rect_geo(W, Hh, nofill=0 if fill else 1, noline=0 if line else 1)
        txt = f"<Text>{escape(text)}</Text>" if text else ""
        self.shapes.append(f'<Shape ID="{self.nid()}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">'
                           f'{"".join(cells)}{chars}{para}{geo}{txt}</Shape>')

    def path(self, pts, *, color=EDGE, dashed=False, head="arrow"):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        w, h = max(x1 - x0, 1), max(y1 - y0, 1)
        W, Hh = w / DPI, h / DPI
        rows = []
        for i, (px, py) in enumerate(pts):
            lx, ly = (px - x0) / DPI, (y1 - py) / DPI
            rows.append(f'<Row T="{"MoveTo" if i == 0 else "LineTo"}" IX="{i + 1}">{_c("X", f"{lx:.4f}")}{_c("Y", f"{ly:.4f}")}</Row>')
        end = {"arrow": 4, "open": 1, "triangle": 11, "none": 0}.get(head, 4)
        cells = [_c("PinX", f"{(x0 + w / 2) / DPI:.4f}"), _c("PinY", f"{(self.H - y0 - h / 2) / DPI:.4f}"),
                 _c("Width", f"{W:.4f}"), _c("Height", f"{Hh:.4f}"),
                 _c("LocPinX", f"{W / 2:.4f}", formula="Width*0.5"), _c("LocPinY", f"{Hh / 2:.4f}", formula="Height*0.5"),
                 _c("LineWeight", "0.0125"), _c("LineColor", color), _c("LinePattern", 2 if dashed else 1),
                 _c("EndArrow", end), _c("EndArrowSize", 1), _c("FillPattern", 0)]
        self.shapes.append(f'<Shape ID="{self.nid()}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">{"".join(cells)}'
                           f'<Section N="Geometry" IX="0">{_c("NoFill", 1)}{_c("NoLine", 0)}{"".join(rows)}</Section></Shape>')

    def xml(self):
        return f'<?xml version="1.0" encoding="utf-8"?><PageContents {_NS}><Shapes>{"".join(self.shapes)}</Shapes></PageContents>'


def _vsdx_page(sc):
    v = _Vsdx(sc["height"])
    v.box(30, 6, max(260, len(sc.get("title", "")) * 11 + 40), 26, text=sc.get("title", ""), align=0, size=14, bold=True)
    for g in sc.get("groups") or []:
        fill, stroke, ink, size = GROUP_STYLE[g["style"]]
        v.box(g["x"], g["y"], g["w"], g["h"], fill=fill, line=stroke, dashed=bool(g.get("dashed")))
        v.box(g["x"] + 6, g["y"] + 2, min(g["w"] - 8, len(g["title"]) * 8 + 20), 20, text=g["title"], align=0,
              size=size - 2, bold=True, color=ink)
    for e in sc["edges"]:
        v.path(e["points"], color="#C9BFB6" if e.get("lifeline") else EDGE, dashed=e.get("style") == "dashed",
               head=e.get("head", "arrow"))
        if e.get("label"):
            if e.get("message"):
                x, y = _msg_pos(e)
                y -= 13
                v.box(x, y, len(e["label"]) * 6.5 + 10, 16, text=e["label"], align=0, size=9, color=MUTED)
            else:
                x, y = _label_pos(e["points"])
                wl = len(e["label"]) * 6.5 + 10
                v.box(x - wl / 2, y - 12, wl, 16, fill="#FFFFFF", text=e["label"], align=1, size=9, color=MUTED)
    for n in sc["nodes"]:
        fill, stroke = _style(n)
        v.box(n["x"], n["y"], n["w"], n["h"], fill=fill, line=stroke, dashed=bool(n.get("dashed")))
        if n.get("compact"):
            if n.get("chip"):
                v.box(n["x"], n["y"] + 3, n["w"], n["h"] - 3, text=n["title"], align=1, size=8.5,
                      color=n.get("ink") or n.get("stroke") or INK)
                continue
            ic = n.get("icon")
            if ic:
                iy = n["y"] + (n["h"] - 20) / 2
                v.box(n["x"] + 8, iy, 22, 20, fill=ic["color"], text=ic["text"], align=1, valign=1, size=6, bold=True,
                      color="#FFFFFF", margin="0")
            txt = n["title"] + (f"\n{n['sub']}" if n.get("sub") else "")
            v.box(n["x"] + 34, n["y"], n["w"] - 34 - (44 if n.get("badge") else 4), n["h"], text=txt, align=0, valign=1,
                  size=9, bold=False)
            b = n.get("badge")
            if b:
                v.box(n["x"] + n["w"] - 42, n["y"] + 5, 36, 14, fill=b["color"], text=b["text"], align=1, valign=1,
                      size=6.5, bold=True, color="#FFFFFF", margin="0")
            continue
        for b in blocks(n):
            if not b.get("head"):
                v.path([(n["x"], n["y"] + b["y"]), (n["x"] + n["w"], n["y"] + b["y"])], color=stroke, head="none")
            v.box(n["x"], n["y"] + b["y"], n["w"], b["h"], text="\n".join(str(l) for l in b["lines"]),
                  align=1 if b["align"] == "center" else 0, size=9 if not b.get("head") else 9.5, bold=bool(b.get("head")))
    return v.xml()


def vsdx(scenes: list, title="Diagrams") -> bytes:
    buf = io.BytesIO()
    pages_xml, page_rels, overrides = [], [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, sc in enumerate(scenes, 1):
            z.writestr(f"visio/pages/page{i}.xml", _vsdx_page(sc))
            name = quoteattr(sc["title"][:31].replace("/", "-"))
            pw, ph = f"{sc['width'] / DPI:.4f}", f"{sc['height'] / DPI:.4f}"
            pages_xml.append(f'<Page ID="{i - 1}" NameU={name} Name={name}><PageSheet LineStyle="0" FillStyle="0" TextStyle="0">'
                             f'{_c("PageWidth", pw, "IN")}{_c("PageHeight", ph, "IN")}'
                             f'{_c("PageScale", 1, "IN")}{_c("DrawingScale", 1, "IN")}{_c("DrawingSizeType", 3)}{_c("DrawingScaleType", 0)}'
                             f'</PageSheet><Rel r:id="rId{i}"/></Page>')
            page_rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page{i}.xml"/>')
            overrides.append(f'<Override PartName="/visio/pages/page{i}.xml" ContentType="application/vnd.ms-visio.page+xml"/>')
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
                   '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
                   + "".join(overrides) +
                   '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                   '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                   '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                   '</Relationships>')
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="utf-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title><dc:creator>Ledelsea</dc:creator></cp:coreProperties>')
        z.writestr("docProps/app.xml",
                   '<?xml version="1.0" encoding="utf-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                   '<Application>Microsoft Visio</Application><Company>Ledelsea</Company></Properties>')
        z.writestr("visio/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/></Relationships>')
        z.writestr("visio/pages/_rels/pages.xml.rels",
                   '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(page_rels) + "</Relationships>")
        z.writestr("visio/pages/pages.xml", f'<?xml version="1.0" encoding="utf-8"?><Pages {_NS}>{"".join(pages_xml)}</Pages>')
        style = ("".join([_c("EnableLineProps", 1), _c("EnableFillProps", 1), _c("EnableTextProps", 1), _c("HideForApply", 0),
                          _c("LineWeight", "0.01"), _c("LineColor", "#000000"), _c("LinePattern", 1), _c("FillForegnd", "#FFFFFF"),
                          _c("FillPattern", 1), _c("VerticalAlign", 1), _c("LeftMargin", "0.05"), _c("RightMargin", "0.05"),
                          _c("TopMargin", "0.05"), _c("BottomMargin", "0.05")])
                 + f'<Section N="Character"><Row IX="0">{_c("Font", "Calibri")}{_c("Size", "0.1667")}{_c("Color", "#000000")}</Row></Section>'
                 + f'<Section N="Paragraph"><Row IX="0">{_c("HorzAlign", 1)}</Row></Section>')
        z.writestr("visio/document.xml",
                   f'<?xml version="1.0" encoding="utf-8"?><VisioDocument {_NS}>'
                   '<DocumentSettings TopPage="0" DefaultTextStyle="0" DefaultLineStyle="0" DefaultFillStyle="0" DefaultGuideStyle="0">'
                   '<GlueSettings>9</GlueSettings><SnapSettings>65847</SnapSettings><SnapExtensions>34</SnapExtensions>'
                   '<SnapAngles/><DynamicGridEnabled>0</DynamicGridEnabled><ProtectStyles>0</ProtectStyles>'
                   '<ProtectShapes>0</ProtectShapes><ProtectMasters>0</ProtectMasters><ProtectBkgnds>0</ProtectBkgnds></DocumentSettings>'
                   '<Colors><ColorEntry IX="0" RGB="#000000"/><ColorEntry IX="1" RGB="#FFFFFF"/></Colors>'
                   '<FaceNames><FaceName NameU="Calibri" UnicodeRanges="-536859905 -1073732485 9 0" CharSets="536871423 0" '
                   'Panose="2 15 5 2 2 2 4 3 2 4" Flags="325"/></FaceNames>'
                   f'<StyleSheets><StyleSheet ID="0" NameU="No Style" IsCustomNameU="1" Name="No Style" IsCustomName="1">{style}</StyleSheet></StyleSheets>'
                   '<DocumentSheet NameU="TheDoc" IsCustomNameU="1" Name="TheDoc" IsCustomName="1" LineStyle="0" FillStyle="0" TextStyle="0">'
                   f'{_c("OutputFormat", 0)}{_c("LockPreview", 0)}</DocumentSheet></VisioDocument>')
    return buf.getvalue()
