"""Generate, validate and export every part defined in configs/parts.json.

Run with FreeCAD's headless interpreter (no GUI needed):
    FreeCADCmd generate.py            (Windows: "C:\\...\\FreeCAD 1.1\\bin\\FreeCADCmd.exe" generate.py)

For each part it writes to output/<id>/: native .FCStd, STEP, STL, a dimensioned A4 drawing (SVG),
a shaded preview (PNG) and a JSON validation report. A summary goes to output/VALIDATION.md.
The process exits with status 1 if any check fails, so it can gate a CI pipeline.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
sys.path.insert(0, ROOT)

import Part  # noqa: E402

from cadlib import bracket, enclosure, validate, export, drawing, render  # noqa: E402
from cadlib.geom import V  # noqa: E402

OUT = os.path.join(ROOT, "output")
STEEL = (0.55, 0.58, 0.62)
COLORS = {"bracket": (0.18, 0.55, 0.85), "base": (0.95, 0.55, 0.15), "lid": (0.30, 0.75, 0.45), "pcb": (0.10, 0.45, 0.20)}


def save_report(folder, report, info):
    ok, total = report.counts()
    data = {"part": report.part, "passed": report.passed, "checks_passed": ok, "checks_total": total, **info, "checks": report.rows}
    with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=lambda v: [round(v.x, 3), round(v.y, 3), round(v.z, 3)] if hasattr(v, "x") else str(v))
    return data


def run_bracket(cfg, author):
    folder = os.path.join(OUT, cfg["id"])
    os.makedirs(folder, exist_ok=True)
    built = bracket.build(cfg)
    shape, d = built["shape"], built["derived"]

    report = validate.Report(cfg["id"])
    validate.topology(report, shape)
    validate.envelope(report, shape, (d["width"], d["base_depth"], d["height"]))
    validate.holes(report, shape, built["holes"])
    validate.interference(report, shape, built["mates"])
    validate.min_webs(report, bracket.min_webs(d), 1.5)

    mass = validate.mass(shape, cfg["density"])
    export.fcstd(os.path.join(folder, f"{cfg['id']}.FCStd"), {cfg["title"]: (shape, COLORS["bracket"])}, cfg, cfg["title"])
    export.step(os.path.join(folder, f"{cfg['id']}.step"), shape)
    facets = export.stl(os.path.join(folder, f"{cfg['id']}.stl"), shape)
    meta = {"title": cfg["title"].upper(), "subtitle": f"{cfg['motor']} L-bracket, generated from configs/parts.json",
            "author": author, "material": cfg["material"], "mass": f"{mass:.1f} g"}
    scale = drawing.make_drawing(shape, built["dims"], meta, os.path.join(folder, "drawing.svg"))
    m = built["mates"]
    render.render([(shape, COLORS["bracket"], 1.0)], os.path.join(folder, "preview.png"), elev=28, azim=38)
    render.render(
        [(shape, COLORS["bracket"], 1.0), (m["motor body"], STEEL, 0.35), (m["motor shaft"], STEEL, 0.9), (m["GT2 20T pulley"], (0.8, 0.7, 0.2), 0.6)],
        os.path.join(folder, "assembly.png"), azim=-125,
    )
    return save_report(folder, report, {"title": cfg["title"], "mass_g": round(mass, 1), "volume_mm3": round(shape.Volume, 1),
                                        "stl_facets": facets, "drawing_scale": scale, "summary": bracket.summary(d)})


def run_enclosure(cfg, author):
    folder = os.path.join(OUT, cfg["id"])
    os.makedirs(folder, exist_ok=True)
    built = enclosure.build(cfg)
    d = built["derived"]
    base, lid = built["parts"]["base"], built["parts"]["lid"]

    report = validate.Report(cfg["id"])
    validate.topology(report, base, "base")
    validate.topology(report, lid, "lid")
    validate.envelope(report, base, (d["outer_l"], d["outer_w"], d["base_h"]), label="base")
    validate.holes(report, base, [h for h in built["holes"] if h["part"] == "base"])
    validate.holes(report, lid, [h for h in built["holes"] if h["part"] == "lid"])
    validate.interference(report, base, built["mates"])
    validate.interference(report, lid, {k: v for k, v in built["mates"].items() if k != "USB-C plug overmold"})
    validate.interference(report, lid, {"base (assembled)": base})
    openings, structure = built["lid_openings"]
    overlap = openings.common(structure).Volume
    report.check("interference", "lid openings clear of standoffs and lip", overlap < validate.VOLUME_EPS, f"overlap {overlap:.4f} mm^3")
    stack = enclosure.screw_stack(d)
    report.check("fasteners", "standard M3 countersunk screw fits the stack", stack["screw"] is not None, stack["screw"] or "none")
    report.check("fasteners", "thread engagement >= 1.3 x d (3.9 mm)", stack["engagement_mm"] >= 3.9, f"{stack['engagement_mm']} mm")
    validate.min_webs(report, enclosure.min_webs(d), 0.6)
    report.check("manufacturability", "walls >= 4 perimeters of a 0.4 mm nozzle", d["wall"] >= 1.6, f"{d['wall']} mm")

    # Cross-check against the real board: the STEP exported by KiCad from the routed PCB, with the
    # component 3D models. Its origin is the board's bottom-left corner, Z = 0 at the board's underside.
    pcb_parts = None
    if cfg["board"].get("step"):
        assembly = Part.read(os.path.join(ROOT, cfg["board"]["step"]))
        assembly.translate(V(d["offset"], d["offset"], d["pcb_bottom"]))
        solids = sorted(assembly.Solids, key=lambda s: s.Volume, reverse=True)
        board_body, components = solids[0], Part.makeCompound(solids[1:])
        tallest = assembly.BoundBox.ZMax - (d["pcb_bottom"] + d["board"]["thickness"])
        report.check("interference", "KiCad PCB 3D model clear of base", base.common(assembly).Volume < validate.VOLUME_EPS,
                     f"{len(solids)} solids from {cfg['board']['step']}")
        report.check("interference", "KiCad PCB 3D model clear of lid", lid.common(assembly).Volume < validate.VOLUME_EPS,
                     f"overlap {lid.common(assembly).Volume:.4f} mm^3")
        report.check("dimensions", "tallest real component within the height budget",
                     tallest <= d["board"]["component_height_top"], f"{tallest:.2f} mm of {d['board']['component_height_top']} mm")
        pcb_parts = (board_body, components)

    mass = validate.mass(base, d["density"]) + validate.mass(lid, d["density"])
    pcb = built["mates"]["PCB (with mounting holes)"]
    export.fcstd(os.path.join(folder, f"{cfg['id']}.FCStd"),
                 {"Base": (base, COLORS["base"]), "Lid": (lid, COLORS["lid"]), "PCB envelope": (pcb, COLORS["pcb"])}, cfg, cfg["title"])
    export.step(os.path.join(folder, f"{cfg['id']}_assembly.step"), Part.makeCompound([base, lid]))
    facets = export.stl(os.path.join(folder, f"{cfg['id']}_base.stl"), base)
    lid_print = lid.copy()
    lid_print.rotate(V(d["outer_l"] / 2, d["outer_w"] / 2, d["base_h"] + d["lid"] / 2), V(1, 0, 0), 180)  # print upside down
    lid_print.translate(V(0, 0, -lid_print.BoundBox.ZMin))
    facets += export.stl(os.path.join(folder, f"{cfg['id']}_lid.stl"), lid_print)

    meta_base = {"title": "ENCLOSURE BASE", "subtitle": cfg["board"]["name"], "author": author,
                 "material": cfg["material"], "mass": f"{validate.mass(base, d['density']):.1f} g"}
    meta_lid = dict(meta_base, title="ENCLOSURE LID", mass=f"{validate.mass(lid, d['density']):.1f} g")
    scale = drawing.make_drawing(base, built["dims"], meta_base, os.path.join(folder, "drawing_base.svg"))
    drawing.make_drawing(lid, [x for x in built["dims"] if x[0] == "top"], meta_lid, os.path.join(folder, "drawing_lid.svg"))

    exploded = lid.copy()
    exploded.translate(V(0, 0, 18))
    board_items = [(pcb_parts[0], COLORS["pcb"], 1.0), (pcb_parts[1], (0.35, 0.36, 0.40), 1.0)] if pcb_parts else [(pcb, COLORS["pcb"], 1.0)]
    render.render([(base, COLORS["base"], 1.0), *board_items, (exploded, COLORS["lid"], 0.85)],
                  os.path.join(folder, "exploded.png"), elev=28, azim=-60)
    render.render([(base, COLORS["base"], 1.0), (lid, COLORS["lid"], 1.0)], os.path.join(folder, "preview.png"), elev=30, azim=-50)
    return save_report(folder, report, {"title": cfg["title"], "mass_g": round(mass, 1), "stl_facets": facets,
                                        "drawing_scale": scale, "summary": enclosure.summary(d)})


def write_summary(results):
    lines = ["# Validation summary", "", "Generated by `generate.py`. Every row is an automated check on the generated B-rep geometry.", "",
             "| Part | Checks | Mass | Result |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['title']} (`{r['part']}`) | {r['checks_passed']}/{r['checks_total']} | {r['mass_g']} g | {'PASS' if r['passed'] else 'FAIL'} |")
    for r in results:
        lines += ["", f"## {r['title']}", "", "| Category | Check | Result | Detail |", "|---|---|---|---|"]
        for c in r["checks"]:
            lines.append(f"| {c['category']} | {c['check']} | {'pass' if c['pass'] else '**FAIL**'} | {c['detail']} |")
    with open(os.path.join(OUT, "VALIDATION.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    with open(os.path.join(ROOT, "configs", "parts.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    results = []
    for cfg in config["brackets"]:
        t = time.time()
        results.append(run_bracket(cfg, config["author"]))
        print(f"{cfg['id']}: {results[-1]['checks_passed']}/{results[-1]['checks_total']} checks in {time.time() - t:.1f}s")
    for cfg in config["enclosures"]:
        t = time.time()
        results.append(run_enclosure(cfg, config["author"]))
        print(f"{cfg['id']}: {results[-1]['checks_passed']}/{results[-1]['checks_total']} checks in {time.time() - t:.1f}s")
    write_summary(results)
    failed = [c for r in results for c in r["checks"] if not c["pass"]]
    for r in results:
        for c in r["checks"]:
            if not c["pass"]:
                print(f"  FAIL {r['part']}: {c['check']} ({c['detail']})")
    print("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED")
    return 1 if failed else 0


# FreeCADCmd executes this file as a script (its __name__ is not always "__main__"), so run unconditionally.
status = main()
if status:
    sys.exit(status)
