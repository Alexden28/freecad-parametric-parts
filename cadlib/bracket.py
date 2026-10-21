"""Parametric L-bracket for NEMA stepper motors.

Coordinate system: X = across the bracket, Y = along the motor shaft (the base extends towards +Y),
Z = up. The motor bolts to the -Y face of the vertical plate, the screw heads sit on the +Y side.
"""
import Part

from .geom import V, X, Y, Z, near, is_line_along, edges_where, cylinder, slot, fuse_all

# NEMA ICS 16 frame data (mm). `pilot` = centring boss diameter, `body_len` = typical motor length.
NEMA = {
    "NEMA14": {"face": 35.2, "hole_spacing": 26.0, "pilot": 22.0, "screw": "M3", "body_len": 34.0, "shaft_d": 5.0},
    "NEMA17": {"face": 42.3, "hole_spacing": 31.0, "pilot": 22.0, "screw": "M3", "body_len": 40.0, "shaft_d": 5.0},
    "NEMA23": {"face": 56.4, "hole_spacing": 47.14, "pilot": 38.1, "screw": "M5", "body_len": 56.0, "shaft_d": 6.35},
}

# ISO 4762 socket head cap screws: clearance hole (medium fit), head diameter, head height.
SCREWS = {
    "M3": {"clearance": 3.4, "head_d": 5.5, "head_h": 3.0, "cbore_d": 6.5},
    "M4": {"clearance": 4.5, "head_d": 7.0, "head_h": 4.0, "cbore_d": 8.0},
    "M5": {"clearance": 5.5, "head_d": 8.5, "head_h": 5.0, "cbore_d": 10.0},
}


def derive(p):
    """Turn the user-facing parameters into every dimension the model needs."""
    m = NEMA[p["motor"]]
    s = SCREWS[m["screw"]]
    base_screw = SCREWS[p.get("base_screw", "M5")]
    t = p["thickness"]
    face = m["face"]
    margin = p.get("margin", 3.0)
    d = {
        "motor": m,
        "screw": s,
        "base_screw": base_screw,
        "t": t,
        "face": face,
        "width": round(face + 2 * margin, 2),
        "axis_z": t + p.get("motor_clearance", 2.0) + face / 2,
        "base_depth": p.get("base_depth", round(0.8 * face + t, 1)),
        "gusset": p.get("gusset_leg", round(0.55 * face, 1)),
        "bend_r": p.get("bend_radius", t),
        "corner_r": p.get("corner_radius", 3.0),
        "pilot_hole": m["pilot"] + 2 * p.get("pilot_clearance", 0.25),
        "cbore_depth": p.get("counterbore_depth", 1.5),
        "density": p.get("density", 1.24),  # g/cm^3, PLA by default
    }
    d["height"] = round(d["axis_z"] + face / 2 + margin, 2)
    d["slot_x"] = round(d["width"] / 2 - t - base_screw["clearance"] / 2 - 3.0, 2)
    d["slot_y"] = (t + d["gusset"] * 0.35, d["base_depth"] - base_screw["clearance"] / 2 - 4.0)
    return d


def build(p):
    d = derive(p)
    t, W, H, D, L = d["t"], d["width"], d["height"], d["base_depth"], d["gusset"]
    zc = d["axis_z"]
    half = d["motor"]["hole_spacing"] / 2

    plate = Part.makeBox(W, t, H, V(-W / 2, 0, 0))
    base = Part.makeBox(W, D, t, V(-W / 2, 0, 0))
    body = plate.fuse(base).removeSplitter()

    # Edges are picked by geometry, not by index, so the selection survives any parameter change.
    bend = edges_where(body, lambda e: is_line_along(e, X) and near(e.Vertexes[0].Point.y, t) and near(e.Vertexes[0].Point.z, t))
    body = body.makeFillet(d["bend_r"], bend)
    corners = edges_where(
        body, lambda e: is_line_along(e, Z) and near(e.Vertexes[0].Point.y, D) and near(abs(e.Vertexes[0].Point.x), W / 2)
    )
    body = body.makeFillet(d["corner_r"], corners)

    ribs = []
    for x0 in (W / 2 - t, -W / 2):
        tri = Part.Face(Part.makePolygon([V(x0, t, t), V(x0, t + L, t), V(x0, t, t + L), V(x0, t, t)]))
        ribs.append(tri.extrude(V(t, 0, 0)))
    body = body.fuse(ribs).removeSplitter()

    s = d["screw"]
    tools = [cylinder(d["pilot_hole"] / 2, t + 2, V(0, -1, zc), Y)]
    screw_axes = []
    for sx in (-1, 1):
        for sz in (-1, 1):
            c = V(sx * half, 0, zc + sz * half)
            screw_axes.append(c)
            tools.append(cylinder(s["clearance"] / 2, t + 2, c + V(0, -1, 0), Y))
            tools.append(cylinder(s["cbore_d"] / 2, d["cbore_depth"] + 1, c + V(0, t - d["cbore_depth"], 0), Y))
    bs = d["base_screw"]
    y0, y1 = d["slot_y"]
    for sx in (-1, 1):
        tools.append(slot(V(sx * d["slot_x"], y0, -1), V(sx * d["slot_x"], y1, -1), bs["clearance"] / 2, t + 2))
    body = body.cut(fuse_all(tools)).removeSplitter()

    return {
        "shape": body,
        "derived": d,
        "holes": expected_holes(d, screw_axes),
        "mates": mating_envelopes(d, screw_axes),
        "dims": drawing_dims(d),
    }


def expected_holes(d, screw_axes):
    zc = d["axis_z"]
    holes = [{"name": "pilot bore", "center": V(0, 0, zc), "axis": Y, "diameter": d["pilot_hole"]}]
    for i, c in enumerate(screw_axes):
        holes.append({"name": f"motor screw {i + 1}", "center": c, "axis": Y, "diameter": d["screw"]["clearance"]})
        holes.append({"name": f"counterbore {i + 1}", "center": c, "axis": Y, "diameter": d["screw"]["cbore_d"]})
    return holes


def mating_envelopes(d, screw_axes):
    """Simplified solids of everything that has to fit around the bracket. Each must not overlap the part."""
    m, s = d["motor"], d["screw"]
    face, zc, t = d["face"], d["axis_z"], d["t"]
    env = {
        "motor body": Part.makeBox(face, m["body_len"], face, V(-face / 2, -m["body_len"], zc - face / 2)),
        "motor pilot boss": cylinder(m["pilot"] / 2, 2.0, V(0, 0, zc), Y),
        "motor shaft": cylinder(m["shaft_d"] / 2, 24.0, V(0, 0, zc), Y),
        "GT2 20T pulley": cylinder(8.0, 16.0, V(0, t + 4.0, zc), Y),
    }
    for i, c in enumerate(screw_axes):
        head_y = t - d["cbore_depth"]
        env[f"screw head {i + 1}"] = cylinder(s["head_d"] / 2, s["head_h"], c + V(0, head_y, 0), Y)
        # Hex key needs a straight line to the screw from the open +Y side.
        env[f"hex key access {i + 1}"] = cylinder(s["head_d"] / 2, 60.0, c + V(0, head_y + s["head_h"], 0), Y)
    return env


def drawing_dims(d):
    """Dimensions shown on the technical drawing: (view, p1, p2, offset in mm, label)."""
    W, H, D, t, zc = d["width"], d["height"], d["base_depth"], d["t"], d["axis_z"]
    half = d["motor"]["hole_spacing"] / 2
    return [
        ("front", V(-W / 2, 0, 0), V(W / 2, 0, 0), 0, 8, f"{W:g}"),
        ("front", V(W / 2, 0, 0), V(W / 2, 0, H), 0, 8, f"{H:g}"),
        ("front", V(-half, 0, zc + half), V(half, 0, zc + half), -(H - zc - half), -6, f"{2 * half:g}"),
        ("front", V(-W / 2, 0, 0), V(-W / 2, 0, zc), 0, -8, f"{zc:g}"),
        ("right", V(0, 0, 0), V(0, D, 0), 0, 8, f"{D:g}"),
        ("right", V(0, 0, 0), V(0, 0, t), 0, -8, f"{t:g}"),
        ("top", V(-d["slot_x"], d["slot_y"][1], 0), V(d["slot_x"], d["slot_y"][1], 0), -(D - d["slot_y"][1]), -6, f"{2 * d['slot_x']:g}"),
    ]


def summary(d):
    return {
        "motor": d["motor"],
        "envelope_mm": [d["width"], d["base_depth"], d["height"]],
        "thickness_mm": d["t"],
        "motor_axis_height_mm": round(d["axis_z"], 2),
        "pilot_bore_mm": d["pilot_hole"],
    }


def min_webs(d):
    """Analytic minimum material between features: (description, value in mm)."""
    half = d["motor"]["hole_spacing"] / 2
    s = d["screw"]
    corner_to_pilot = (2 * half * half) ** 0.5 - d["pilot_hole"] / 2 - s["cbore_d"] / 2
    cbore_floor = d["t"] - d["cbore_depth"]
    slot_to_edge = d["width"] / 2 - d["slot_x"] - d["base_screw"]["clearance"] / 2
    return [
        ("counterbore to pilot bore", corner_to_pilot),
        ("material under counterbore", cbore_floor),
        ("base slot to outer edge", slot_to_edge),
        ("lower screw axis above base", d["axis_z"] - half - s["head_d"] / 2 - d["t"]),
    ]
