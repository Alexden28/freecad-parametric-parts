"""Two-part 3D-printable enclosure generated from a PCB interface description.

The board is clamped between bosses in the base and standoffs hanging from the lid; four
countersunk M3 screws go through lid, standoff and PCB into the base bosses.
Coordinate system: X = board length, Y = board width, Z = up. Board coordinates follow KiCad
(origin at the top-left corner, Y pointing down) and are mapped with `board_to_xy`.
"""
import Part

from .geom import V, X, Y, Z, rounded_box, cylinder, slot, fuse_all

# Standard ISO 10642 countersunk screw lengths available for M3 (mm).
M3_LENGTHS = [6, 8, 10, 12, 14, 16, 20, 25]


def derive(p):
    b = p["board"]
    d = dict(p)
    d["offset"] = p["wall"] + p["clearance"]  # board corner position inside the enclosure
    d["inner_l"] = b["length"] + 2 * p["clearance"]
    d["inner_w"] = b["width"] + 2 * p["clearance"]
    d["outer_l"] = d["inner_l"] + 2 * p["wall"]
    d["outer_w"] = d["inner_w"] + 2 * p["wall"]
    d["pcb_bottom"] = p["floor"] + p["standoff"]
    d["pcb_top"] = d["pcb_bottom"] + b["thickness"]
    d["base_h"] = round(d["pcb_top"] + b["component_height_top"] + p["component_gap"], 2)  # = lid underside
    d["total_h"] = d["base_h"] + p["lid"]
    d["usb_z"] = d["pcb_top"] + b["usb_c"]["height"] / 2
    d["pilot_bottom"] = p["floor_under_pilot"]  # material left under the pilot hole
    d["density"] = p.get("density", 1.27)  # PETG
    return d


def board_to_xy(d, bx, by):
    b = d["board"]
    return V(d["offset"] + bx, d["offset"] + (b["width"] - by), 0)


def build(p):
    d = derive(p)
    b = d["board"]
    holes = [board_to_xy(d, *h) for h in b["holes"]]
    base = build_base(d, holes)
    lid, lid_openings, lid_structure = build_lid(d, holes)
    return {
        "parts": {"base": base, "lid": lid},
        # vents, LED and button holes must not cut into the standoffs or the locating lip
        "lid_openings": (lid_openings, lid_structure),
        "derived": d,
        "holes": expected_holes(d, holes),
        "mates": mating_envelopes(d, holes),
        "dims": drawing_dims(d),
    }


def build_base(d, holes):
    wall, floor = d["wall"], d["floor"]
    outer = rounded_box(d["outer_l"], d["outer_w"], d["base_h"], d["outer_radius"])
    pocket = rounded_box(d["inner_l"], d["inner_w"], d["base_h"], d["outer_radius"] - wall, V(wall, wall, floor))
    shell = outer.cut(pocket)

    bosses = [cylinder(d["boss_d"] / 2, d["standoff"] + 0.5, h + V(0, 0, floor - 0.5), Z) for h in holes]
    shell = shell.fuse(bosses).removeSplitter()

    tools = [cylinder(d["pilot_d"] / 2, d["pcb_bottom"] - d["pilot_bottom"] + 1, h + V(0, 0, d["pilot_bottom"]), Z) for h in holes]
    usb = d["board"]["usb_c"]
    cy = board_to_xy(d, 0, usb["y"]).y
    reach = (d["usb_cutout_w"] - d["usb_cutout_h"]) / 2
    tools.append(slot(V(-1, cy - reach, d["usb_z"]), V(-1, cy + reach, d["usb_z"]), d["usb_cutout_h"] / 2, wall + 2, X))
    return shell.cut(fuse_all(tools)).removeSplitter()


def build_lid(d, holes):
    top = d["base_h"]
    lc, lt = d["lip_clearance"], d["lip_thickness"]
    r_in = d["outer_radius"] - d["wall"]
    plate = rounded_box(d["outer_l"], d["outer_w"], d["lid"], d["outer_radius"], V(0, 0, top))
    lip_outer = rounded_box(d["inner_l"] - 2 * lc, d["inner_w"] - 2 * lc, d["lip_height"] + 0.5, r_in - lc,
                            V(d["wall"] + lc, d["wall"] + lc, top - d["lip_height"]))
    lip_inner = rounded_box(d["inner_l"] - 2 * (lc + lt), d["inner_w"] - 2 * (lc + lt), d["lip_height"] + 1, max(0.2, r_in - lc - lt),
                            V(d["wall"] + lc + lt, d["wall"] + lc + lt, top - d["lip_height"] - 0.5))
    standoffs = [cylinder(d["standoff_d"] / 2, top - d["pcb_top"] + 0.5, h + V(0, 0, d["pcb_top"]), Z) for h in holes]
    lip = lip_outer.cut(lip_inner)
    lid = plate.fuse([lip] + standoffs).removeSplitter()

    b = d["board"]
    zt = top + d["lid"]
    screw_tools = []
    for h in holes:
        screw_tools.append(cylinder(d["screw_clearance"] / 2, zt - d["pcb_top"] + 2, h + V(0, 0, d["pcb_top"] - 1), Z))
        sink = (d["csk_d"] - d["screw_clearance"]) / 2  # 90 degree countersink depth
        screw_tools.append(Part.makeCone(d["screw_clearance"] / 2, d["csk_d"] / 2 + 0.01, sink + 0.01, h + V(0, 0, zt - sink), Z))
    tools = []
    for name, diameter in (("led", d["led_hole_d"]),):
        c = board_to_xy(d, *b[name])
        tools.append(cylinder(diameter / 2, d["lid"] + 2, c + V(0, 0, top - 1), Z))
    for btn in b["buttons"]:
        c = board_to_xy(d, *btn)
        tools.append(cylinder(d["pinhole_d"] / 2, d["lid"] + 2, c + V(0, 0, top - 1), Z))
    s = board_to_xy(d, *b["sensor"])
    n, pitch, length, width = d["vent_count"], d["vent_pitch"], d["vent_length"], d["vent_width"]
    for i in range(n):
        x = s.x + (i - (n - 1) / 2) * pitch
        tools.append(slot(V(x, s.y - length / 2 + width / 2, top - 1), V(x, s.y + length / 2 - width / 2, top - 1), width / 2, d["lid"] + 2))
    openings = fuse_all(tools)
    lid = lid.cut(fuse_all(screw_tools + [openings])).removeSplitter()
    return lid, openings, fuse_all([lip] + standoffs)


def expected_holes(d, holes):
    out = []
    for i, h in enumerate(holes):
        out.append({"part": "base", "name": f"boss pilot {i + 1}", "center": h, "axis": Z, "diameter": d["pilot_d"]})
        out.append({"part": "lid", "name": f"screw clearance {i + 1}", "center": h, "axis": Z, "diameter": d["screw_clearance"]})
    b = d["board"]
    out.append({"part": "lid", "name": "LED light hole", "center": board_to_xy(d, *b["led"]), "axis": Z, "diameter": d["led_hole_d"]})
    for i, btn in enumerate(b["buttons"]):
        out.append({"part": "lid", "name": f"button pinhole {i + 1}", "center": board_to_xy(d, *btn), "axis": Z, "diameter": d["pinhole_d"]})
    return out


def mating_envelopes(d, holes):
    """Solids that must not collide with base or lid once assembled."""
    b = d["board"]
    o = d["offset"]
    keepouts = [cylinder(b["hole_keepout_d"] / 2, 50, h + V(0, 0, -10), Z) for h in holes]
    board = Part.makeBox(b["length"], b["width"], b["thickness"], V(o, o, d["pcb_bottom"]))
    board = board.cut(fuse_all([cylinder(b["hole_d"] / 2, 10, h + V(0, 0, -1), Z) for h in holes]))
    components = Part.makeBox(b["length"], b["width"], b["component_height_top"], V(o, o, d["pcb_top"])).cut(fuse_all(keepouts))
    usb = b["usb_c"]
    cy = board_to_xy(d, 0, usb["y"]).y
    plug = d["usb_plug"]
    # USB-C overmolds are stadium-shaped, like the receptacle they plug into.
    reach = (plug["w"] - plug["h"]) / 2
    x0 = o - plug["inset"] - 30
    overmold = slot(V(x0, cy - reach, d["usb_z"]), V(x0, cy + reach, d["usb_z"]), plug["h"] / 2, 30, X)
    return {"PCB (with mounting holes)": board, "components (top side)": components, "USB-C plug overmold": overmold}


def screw_stack(d):
    """Pick the M3 countersunk screw length and report thread engagement in the base boss."""
    clamp = d["lid"] + (d["base_h"] - d["pcb_top"]) + d["board"]["thickness"]
    pilot_depth = d["pcb_bottom"] - d["pilot_bottom"]
    candidates = [L for L in M3_LENGTHS if 0 < L - clamp <= pilot_depth - 0.5]
    length = max(candidates) if candidates else None
    return {"clamp_mm": round(clamp, 2), "pilot_depth_mm": round(pilot_depth, 2), "screw": f"M3x{length} ISO 10642" if length else None,
            "engagement_mm": round(length - clamp, 2) if length else 0.0}


def drawing_dims(d):
    L, W, H, T = d["outer_l"], d["outer_w"], d["base_h"], d["total_h"]
    h0 = board_to_xy(d, *d["board"]["holes"][0])
    h1 = board_to_xy(d, *d["board"]["holes"][1])
    return [
        ("top", V(0, 0, 0), V(L, 0, 0), 0, 8, f"{L:g}"),
        ("top", V(L, 0, 0), V(L, W, 0), 0, 8, f"{W:g}"),
        ("top", V(h0.x, h0.y, 0), V(h1.x, h1.y, 0), -(W - h0.y), -6, f"{h1.x - h0.x:g}"),
        ("front", V(L, 0, 0), V(L, 0, T), 0, 8, f"{T:g}"),
        ("front", V(0, 0, 0), V(0, 0, H), 0, -8, f"{H:g}"),
    ]


def min_webs(d):
    usb_top = d["usb_z"] + d["usb_cutout_h"] / 2
    usb_bottom = d["usb_z"] - d["usb_cutout_h"] / 2
    return [
        ("wall thickness", d["wall"]),
        ("floor under boss pilot", d["pilot_bottom"]),
        ("bridge above USB cutout", d["base_h"] - usb_top),
        ("wall below USB cutout to floor", usb_bottom - d["floor"]),
        ("boss wall around pilot", (d["boss_d"] - d["pilot_d"]) / 2),
        ("standoff wall around screw", (d["standoff_d"] - d["screw_clearance"]) / 2),
        # The standoff continues below the countersink, so the thinnest spot is where the cone
        # leaves the standoff's outline.
        ("lid under countersink, outside standoff", d["lid"] - (d["csk_d"] - d["standoff_d"]) / 2),
    ]


def summary(d):
    return {
        "board": d["board"]["name"],
        "outer_mm": [round(d["outer_l"], 2), round(d["outer_w"], 2), round(d["total_h"], 2)],
        "pcb_bottom_z_mm": d["pcb_bottom"],
        "screws": screw_stack(d),
    }
