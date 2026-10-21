"""Automated checks run on every generated part. Each check returns a row for the report."""
import Part

VOLUME_EPS = 1e-4  # mm^3: anything below is numerical noise from touching faces


class Report:
    def __init__(self, part):
        self.part = part
        self.rows = []

    def check(self, category, name, ok, detail=""):
        self.rows.append({"category": category, "check": name, "pass": bool(ok), "detail": detail})
        return ok

    @property
    def passed(self):
        return all(r["pass"] for r in self.rows)

    def counts(self):
        ok = sum(r["pass"] for r in self.rows)
        return ok, len(self.rows)


def topology(report, shape, label=""):
    """B-rep sanity: valid, exactly one solid, closed shells, positive volume."""
    prefix = f"{label}: " if label else ""
    report.check("topology", f"{prefix}shape is valid (BRepCheck)", shape.isValid())
    report.check("topology", f"{prefix}exactly one solid", len(shape.Solids) == 1, f"{len(shape.Solids)} solid(s)")
    closed = all(s.isClosed() for s in shape.Shells)
    report.check("topology", f"{prefix}watertight (all shells closed)", closed, f"{len(shape.Shells)} shell(s)")
    report.check("topology", f"{prefix}positive volume", shape.Volume > 0, f"{shape.Volume:.1f} mm^3")


def envelope(report, shape, expected, tol=0.05, label=""):
    bb = shape.BoundBox
    actual = (bb.XLength, bb.YLength, bb.ZLength)
    ok = all(abs(a - e) <= tol for a, e in zip(actual, expected))
    detail = "actual {:.2f} x {:.2f} x {:.2f} / spec {:.2f} x {:.2f} x {:.2f}".format(*actual, *expected)
    report.check("dimensions", f"{label + ': ' if label else ''}bounding box matches spec", ok, detail)


def holes(report, shape, specs, tol=0.01):
    """Every specified hole must exist as a cylindrical face with the right diameter, on the right axis."""
    cylinders = []
    for f in shape.Faces:
        if type(f.Surface).__name__ == "Cylinder":
            cylinders.append(f.Surface)
    for h in specs:
        found = False
        for c in cylinders:
            if abs(2 * c.Radius - h["diameter"]) > tol:
                continue
            if abs(abs(c.Axis.normalize().dot(h["axis"])) - 1) > 1e-6:
                continue
            # distance from the spec centre to the cylinder axis line
            offset = (h["center"] - c.Center)
            radial = offset - c.Axis.normalize() * offset.dot(c.Axis.normalize())
            if radial.Length <= tol:
                found = True
                break
        report.check("features", f"{h['name']} present", found, f"dia {h['diameter']:.2f} mm")


def interference(report, part, mates):
    """Zero-volume intersection with every mating solid (motor, screws, PCB, cables...)."""
    for name, solid in mates.items():
        common = part.common(solid)
        vol = common.Volume if not common.isNull() else 0.0
        report.check("interference", f"clear of {name}", vol < VOLUME_EPS, f"overlap {vol:.4f} mm^3")


def min_webs(report, webs, minimum):
    for name, value in webs:
        report.check("manufacturability", f"{name} >= {minimum:g} mm", value >= minimum - 1e-9, f"{value:.2f} mm")


def mass(shape, density):
    """grams, with the volume in mm^3 and the density in g/cm^3"""
    return shape.Volume * density / 1000.0
