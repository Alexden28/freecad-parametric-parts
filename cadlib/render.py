"""Headless shaded renders: a small z-buffer rasterizer in numpy (no FreeCAD GUI or OpenGL needed).

Tessellated faces are flat-shaded with two lights, B-rep edges are drawn on top with a depth test
(the CAD "shaded with edges" look) and the image is supersampled 2x for anti-aliasing.
Items can be marked as ghosts (semi-transparent mating parts such as the motor envelope).
"""
import math

import numpy as np
from PIL import Image

EDGE_RGB = np.array([0.12, 0.14, 0.17])


def _camera(elev, azim):
    e, a = math.radians(elev), math.radians(azim)
    d = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])  # towards the camera
    r = np.cross([0.0, 0.0, 1.0], d)
    r /= np.linalg.norm(r)
    u = np.cross(d, r)
    return r, u, d


def _triangles(shape, deflection):
    verts, tris = shape.tessellate(deflection)
    v = np.array([[p.x, p.y, p.z] for p in verts], dtype=float)
    return v[np.array(tris, dtype=int)]


def _edges(shape, deflection):
    lines = []
    for e in shape.Edges:
        try:
            pts = e.discretize(Deflection=deflection)
        except Exception:
            continue
        lines.append(np.array([[p.x, p.y, p.z] for p in pts]))
    return lines


def _rasterize(tri2, depth, colors, zbuf, img):
    h, w = zbuf.shape
    for i in range(len(tri2)):
        (x0, y0), (x1, y1), (x2, y2) = tri2[i]
        xmin, xmax = max(int(min(x0, x1, x2)), 0), min(int(max(x0, x1, x2)) + 1, w - 1)
        ymin, ymax = max(int(min(y0, y1, y2)), 0), min(int(max(y0, y1, y2)) + 1, h - 1)
        if xmax < xmin or ymax < ymin:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        xs = np.arange(xmin, xmax + 1) + 0.5
        ys = np.arange(ymin, ymax + 1) + 0.5
        X, Y = np.meshgrid(xs, ys)
        w0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / den
        w1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        z = w0 * depth[i, 0] + w1 * depth[i, 1] + w2 * depth[i, 2]
        zsub = zbuf[ymin:ymax + 1, xmin:xmax + 1]
        m = inside & (z > zsub)
        zsub[m] = z[m]
        img[ymin:ymax + 1, xmin:xmax + 1][m] = colors[i]


def render(items, path, elev=24, azim=-58, deflection=0.08, size=(1100, 820), edges=True):
    """items: list of (shape, rgb, alpha). alpha < 1 renders the item as a single-layer ghost."""
    ss = 2
    W, H = size[0] * ss, size[1] * ss
    r, u, d = _camera(elev, azim)
    light1 = 0.25 * r + 0.55 * u + 0.80 * d
    light2 = -0.6 * r - 0.2 * u + 0.75 * d
    light1, light2 = light1 / np.linalg.norm(light1), light2 / np.linalg.norm(light2)

    meshes = [(_triangles(s, deflection), np.array(rgb, float), alpha, s) for s, rgb, alpha in items]
    pts = np.concatenate([m[0].reshape(-1, 3) for m in meshes])
    sx, sy = pts @ r, pts @ u
    span = max(sx.max() - sx.min(), (sy.max() - sy.min()) * W / H)
    scale = 0.88 * W / span
    cx, cy = (sx.max() + sx.min()) / 2, (sy.max() + sy.min()) / 2

    def to_px(p):
        return np.stack([(p @ r - cx) * scale + W / 2, H / 2 - (p @ u - cy) * scale], axis=-1)

    img = np.ones((H, W, 3))
    zbuf = np.full((H, W), -np.inf)
    ghost_img = np.ones((H, W, 3))
    ghost_z = np.full((H, W), -np.inf)
    ghost_alpha = np.zeros((H, W))

    for tri, rgb, alpha, shape in meshes:
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        k = 0.28 + 0.62 * np.abs(n @ light1) + 0.22 * np.abs(n @ light2)  # two-sided: robust to winding
        colors = np.clip(np.outer(k, rgb), 0, 1)
        tri2, depth = to_px(tri), tri @ d
        if alpha >= 1:
            _rasterize(tri2, depth, colors, zbuf, img)
        else:
            before = ghost_z.copy()
            _rasterize(tri2, depth, colors, ghost_z, ghost_img)
            ghost_alpha[ghost_z != before] = alpha

    if edges:
        eps = 0.004 * span
        for tri, rgb, alpha, shape in meshes:
            if alpha < 1:
                continue
            for line in _edges(shape, 0.05):
                p2, dep = to_px(line), line @ d
                for j in range(len(line) - 1):
                    (x0, y0), (x1, y1) = p2[j], p2[j + 1]
                    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 2
                    t = np.linspace(0, 1, steps)
                    xs = (x0 + (x1 - x0) * t).astype(int)
                    ys = (y0 + (y1 - y0) * t).astype(int)
                    zs = dep[j] + (dep[j + 1] - dep[j]) * t
                    ok = (xs >= 1) & (xs < W - 1) & (ys >= 1) & (ys < H - 1)
                    xs, ys, zs = xs[ok], ys[ok], zs[ok]
                    vis = zs >= zbuf[ys, xs] - eps
                    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                        img[ys[vis] + oy, xs[vis] + ox] = EDGE_RGB

    # Composite ghosts that are in front of the opaque geometry (or over the background).
    front = ghost_z > zbuf
    a = (ghost_alpha * front)[..., None]
    img = img * (1 - a) + ghost_img * a

    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    out = out.resize(size, Image.LANCZOS)
    out.save(path, optimize=True)
