"""Technical drawing generator: hidden-line-removed orthographic views (OpenCascade HLR via TechDraw),
dimensions and a title block, written as a self-contained A4 landscape SVG.
"""
import datetime
import math

import FreeCAD as App
import TechDraw

from .geom import VIEWS, view_matrix, project_point

A4 = (297.0, 210.0)
FRAME = 10.0
TITLE_H = 28.0


def _project(shape, view):
    right, up = VIEWS[view]
    s = shape.copy()
    s.transformShape(view_matrix(right, up))
    res = TechDraw.projectEx(s, App.Vector(0, 0, 1))
    # projectEx returns [visible sharp, smooth, seam, outline, iso, hidden sharp, smooth, seam, outline, iso]
    visible = [c for c in res[0:4] if c and not c.isNull()]
    hidden = [c for c in res[5:9] if c and not c.isNull()]
    return visible, hidden


def _polylines(compounds, deflection=0.05):
    lines = []
    for comp in compounds:
        for e in comp.Edges:
            try:
                pts = e.discretize(Deflection=deflection)
            except Exception:
                continue
            if len(pts) >= 2:
                lines.append([(p.x, p.y) for p in pts])
    return lines


def _bounds(lines):
    xs = [x for l in lines for x, _ in l]
    ys = [y for l in lines for _, y in l]
    return min(xs), min(ys), max(xs), max(ys)


class Sheet:
    def __init__(self):
        self.out = []

    def add(self, s):
        self.out.append(s)

    def polyline(self, pts, cls):
        d = " ".join(f"{x:.3f},{y:.3f}" for x, y in pts)
        self.add(f'<polyline class="{cls}" points="{d}"/>')

    def text(self, x, y, s, size=3.5, anchor="middle", weight="normal", rotate=None):
        tr = f' transform="rotate({rotate} {x:.2f} {y:.2f})"' if rotate is not None else ""
        self.add(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}"{tr}>{s}</text>')

    def line(self, x0, y0, x1, y1, cls="thin"):
        self.add(f'<line class="{cls}" x1="{x0:.3f}" y1="{y0:.3f}" x2="{x1:.3f}" y2="{y1:.3f}"/>')


def _dimension(sheet, a, b, offset, label):
    """Linear dimension between sheet points a and b, drawn `offset` mm to the side (sign = side)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    ax, ay = x0 + nx * offset, y0 + ny * offset
    bx, by = x1 + nx * offset, y1 + ny * offset
    ext = 1.5 if offset > 0 else -1.5
    sheet.line(x0 + nx * 1.0 * (1 if offset > 0 else -1), y0 + ny * 1.0 * (1 if offset > 0 else -1), ax + nx * ext, ay + ny * ext)
    sheet.line(x1 + nx * 1.0 * (1 if offset > 0 else -1), y1 + ny * 1.0 * (1 if offset > 0 else -1), bx + nx * ext, by + ny * ext)
    sheet.add(f'<line class="dim" x1="{ax:.3f}" y1="{ay:.3f}" x2="{bx:.3f}" y2="{by:.3f}" marker-start="url(#arrow)" marker-end="url(#arrow)"/>')
    # Text reads left-to-right or bottom-to-top (ISO 129) and sits just "above" the dimension line.
    angle = math.degrees(math.atan2(uy, ux))
    if angle > 90 or angle < -90:
        angle -= 180 * (1 if angle > 0 else -1)
    rad = math.radians(angle)
    mx = (ax + bx) / 2 + math.sin(rad) * 1.0
    my = (ay + by) / 2 - math.cos(rad) * 1.0
    sheet.text(mx, my, label, size=3.2, rotate=angle if abs(angle) > 1 else None)


def make_drawing(shape, dims, meta, path, views=("front", "top", "right", "iso")):
    projected = {}
    for v in views:
        vis, hid = _project(shape, v)
        projected[v] = (_polylines(vis), _polylines(hid))

    # Layout: third-angle arrangement (top above front, right view to the right of front), iso in the corner.
    sizes = {v: _bounds(projected[v][0]) for v in views}
    w = lambda v: sizes[v][2] - sizes[v][0]
    h = lambda v: sizes[v][3] - sizes[v][1]
    gap = 22.0
    area_w = A4[0] - 2 * FRAME - 20
    area_h = A4[1] - 2 * FRAME - TITLE_H - 20
    need_w = w("front") + w("right") + w("iso") * 0.8 + 3 * gap
    need_h = h("top") + h("front") + 2 * gap
    raw = min(area_w / need_w, area_h / need_h)
    scale = max(s for s in (0.5, 1, 1.5, 2, 2.5, 3, 4, 5) if s <= raw) if raw >= 0.5 else raw
    iso_scale = scale * 0.8

    origin_x = FRAME + 14
    top_band = FRAME + 10
    front_y = top_band + h("top") * scale + gap  # sheet y of the front view's top edge
    place = {
        "top": (origin_x, top_band),
        "front": (origin_x, front_y),
        "right": (origin_x + w("front") * scale + gap, front_y),
        "iso": (A4[0] - FRAME - 10 - w("iso") * iso_scale, top_band + 4),
    }

    def to_sheet(view, x, y):
        k = iso_scale if view == "iso" else scale
        px, py = place[view]
        x0, y0, x1, y1 = sizes[view]
        return px + (x - x0) * k, py + (y1 - y) * k  # flip Y: SVG grows downwards

    sheet = Sheet()
    for v in views:
        vis, hid = projected[v]
        for l in hid:
            if v != "iso":
                sheet.polyline([to_sheet(v, x, y) for x, y in l], "hidden")
        for l in vis:
            sheet.polyline([to_sheet(v, x, y) for x, y in l], "visible")
        if v == "iso":  # principal views are identified by their third-angle position, as is customary
            label_x, label_y = to_sheet(v, (sizes[v][0] + sizes[v][2]) / 2, sizes[v][1])
            sheet.text(label_x, label_y + 6, "ISOMETRIC VIEW", size=3, weight="bold")

    # dims: (view, p1, p2, model_offset, paper_offset, label). The model part scales with the view,
    # the paper part is a fixed distance on the sheet. Positive offsets go right/down on the sheet.
    for view, p1, p2, model_offset, paper_offset, label in dims:
        a = to_sheet(view, *project_point(p1, view))
        b = to_sheet(view, *project_point(p2, view))
        _dimension(sheet, a, b, model_offset * scale + paper_offset, label)

    _title_block(sheet, meta, scale)
    svg = _wrap(sheet)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return scale


def _title_block(sheet, meta, scale):
    x1, y1 = A4[0] - FRAME, A4[1] - FRAME
    x0, y0 = FRAME, y1 - TITLE_H
    sheet.add(f'<rect class="frame" x="{FRAME}" y="{FRAME}" width="{A4[0] - 2 * FRAME}" height="{A4[1] - 2 * FRAME}"/>')
    sheet.line(x0, y0, x1, y0, "frame")
    cols = [x0, x0 + 110, x0 + 160, x0 + 205, x1]
    for c in cols[1:-1]:
        sheet.line(c, y0, c, y1, "frame")
    mid = y0 + TITLE_H / 2
    sheet.line(cols[1], mid, x1, mid, "thin")
    sheet.text(x0 + 4, y0 + 10, meta["title"], size=6, anchor="start", weight="bold")
    sheet.text(x0 + 4, y0 + 17, meta["subtitle"], size=3.2, anchor="start")
    sheet.text(x0 + 4, y0 + 23.5, f"Drawn: {meta['author']}   Date: {datetime.date.today().isoformat()}   Rev {meta.get('rev', 'A')}", size=3, anchor="start")
    fields = [
        ("MATERIAL", meta["material"]), ("MASS", meta["mass"]),
        ("SCALE", f"{scale:g}:1" if scale >= 1 else f"1:{1 / scale:g}"), ("UNITS", "mm"),
        ("PROJECTION", "3rd angle"), ("TOLERANCE", meta.get("tolerance", "ISO 2768-m")),
    ]
    slots = [(cols[1], y0), (cols[2], y0), (cols[3], y0), (cols[1], mid), (cols[2], mid), (cols[3], mid)]
    for (label, value), (cx, cy) in zip(fields, slots):
        sheet.text(cx + 2.5, cy + 4.2, label, size=2.4, anchor="start")
        sheet.text(cx + 2.5, cy + 10.5, value, size=3.6, anchor="start", weight="bold")
    # third-angle projection symbol
    sx, sy = cols[3] + 50, y0 + 3.5
    sheet.add(f'<g class="thin" transform="translate({sx:.1f},{sy:.1f})"><path d="M0 2 L0 8 L8 9.5 L8 0.5 Z"/>'
              f'<circle cx="16" cy="5" r="4.5"/><circle cx="16" cy="5" r="2"/></g>')


def _wrap(sheet):
    style = (
        "polyline,line,path,rect,circle{fill:none;stroke:#111;stroke-linejoin:round;stroke-linecap:round}"
        ".visible{stroke-width:0.45}.hidden{stroke-width:0.22;stroke:#555;stroke-dasharray:1.6 0.9}"
        ".thin{stroke-width:0.18}.dim{stroke-width:0.18}.frame{stroke-width:0.5}"
        "text{font-family:'DejaVu Sans',Arial,sans-serif;fill:#111}"
    )
    body = "\n".join(sheet.out)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{A4[0]}mm" height="{A4[1]}mm" viewBox="0 0 {A4[0]} {A4[1]}">\n'
        f"<defs><style>{style}</style>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
        '<path d="M0,1.5 L10,5 L0,8.5 Z" style="fill:#111;stroke:none"/></marker></defs>\n'
        f'<rect x="0" y="0" width="{A4[0]}" height="{A4[1]}" fill="#fff"/>\n{body}\n</svg>\n'
    )
