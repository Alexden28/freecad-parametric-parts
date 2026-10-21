"""Small geometry helpers on top of FreeCAD's Part API (OpenCascade B-rep)."""
import math

import FreeCAD as App
import Part

V = App.Vector
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)
TOL = 1e-6


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


def is_line_along(edge, axis):
    """True for a straight edge parallel to `axis`."""
    if type(edge.Curve).__name__ != "Line":
        return False
    d = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
    if d.Length < TOL:
        return False
    return abs(abs(d.normalize().dot(axis)) - 1.0) < 1e-6


def edges_where(shape, predicate):
    return [e for e in shape.Edges if predicate(e)]


def mid(edge):
    return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))


def rounded_box(length, width, height, radius, origin=V(0, 0, 0)):
    """Box with its four vertical edges filleted (enclosure walls, lids, pockets)."""
    box = Part.makeBox(length, width, height, origin)
    if radius <= 0:
        return box
    verticals = edges_where(box, lambda e: is_line_along(e, Z))
    return box.makeFillet(radius, verticals)


def cylinder(radius, height, base, direction):
    return Part.makeCylinder(radius, height, base, direction)


def slot(p0, p1, radius, height, direction=Z):
    """Stadium-shaped slot between two centre points, extruded along `direction` (a vertical slot by default)."""
    d = p1 - p0
    length = d.Length
    a = cylinder(radius, height, p0, direction)
    b = cylinder(radius, height, p1, direction)
    if length < TOL:
        return a
    u = V(d).normalize()
    side = u.cross(direction).normalize()
    c0 = p0 + side * radius
    corners = [c0, c0 + d, c0 + d - side * (2 * radius), c0 - side * (2 * radius), c0]
    web = Part.Face(Part.makePolygon(corners)).extrude(V(direction).normalize() * height)
    return a.fuse([b, web]).removeSplitter()


def fuse_all(shapes):
    head, *rest = shapes
    return head.fuse(rest).removeSplitter() if rest else head


def view_matrix(right, up):
    """Rotation that maps a view's (right, up, towards-viewer) frame onto world (X, Y, Z)."""
    r = V(right).normalize()
    u = V(up).normalize()
    t = r.cross(u)
    return App.Matrix(r.x, r.y, r.z, 0, u.x, u.y, u.z, 0, t.x, t.y, t.z, 0, 0, 0, 0, 1)


# Third-angle projection views (ISO 128 / ASME Y14.3 "third angle"): name -> (right, up)
VIEWS = {
    "front": (X, Z),  # looking from -Y towards +Y
    "top": (X, Y),  # looking down from +Z
    "right": (Y, Z),  # looking from +X towards -X
    "iso": (V(1, 1, 0), V(-1, 1, 2)),  # viewer at (+X, -Y, +Z)
}


def project_point(p, view):
    right, up = VIEWS[view]
    r = V(right).normalize()
    u = V(up).normalize()
    return (p.dot(r), p.dot(u))


def angle_deg(a, b):
    return math.degrees(a.getAngle(b))
