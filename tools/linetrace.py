"""Shared tracer: black line art image -> CNC-ready DXF.

pip install ezdxf opencv-python-headless numpy pillow scipy scikit-image

Layers written (all closed loops are LWPOLYLINEs, units mm):
    OUTSIDE       outer edge of every black area (counter-clockwise)
    INSIDE        edges of white areas enclosed by black (clockwise)
    CENTERLINE    single-line paths along the middle of each stroke
    FILL_OUTSIDE  outer edge of solid areas too wide for one stroke-width pass
    FILL_INSIDE   white islands inside those solid areas
    BORDER        optional offset outline around the whole drawing

Everything is scaled so the OUTSIDE geometry is `width_mm` wide, with the
origin at its bottom-left corner.
"""
from collections import defaultdict

import cv2
import ezdxf
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from skimage.morphology import skeletonize

N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


# ---------------------------------------------------------------- input
def ink_mask(path, pad=4):
    """0..255 'ink' image: transparent or white -> 0, opaque black -> 255."""
    a = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    ink = (a[..., 3] * (1.0 - lum) * 255).astype(np.uint8)
    # artwork may touch the image edge; pad so every loop closes cleanly
    return cv2.copyMakeBorder(ink, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)


def binarise(ink, up):
    h, w = ink.shape
    big = cv2.resize(ink, (w * up, h * up), interpolation=cv2.INTER_CUBIC) if up > 1 else ink
    return (big > 127).astype(np.uint8)


def half_width(mask):
    """Typical stroke half-width in pixels of `mask`."""
    d = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    sk = skeletonize(mask > 0)
    return float(np.median(d[sk])), d, sk


# ---------------------------------------------------------------- helpers
def signed_area(p):
    return 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])


def smooth(p, sigma, closed):
    if sigma <= 0 or len(p) < 5:
        return p
    q = gaussian_filter1d(p, sigma, axis=0, mode="wrap" if closed else "nearest")
    if not closed:
        q[0], q[-1] = p[0], p[-1]
    return q


def simplify(p, tol, closed):
    q = cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2), tol, closed)[:, 0, :]
    return q.astype(np.float64)


def contours(mask, sigma, tol, min_area):
    """Closed loops of a binary mask -> [(pts (x, y-down), is_hole)]."""
    cs, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    for i, c in enumerate(cs):
        p = c[:, 0, :].astype(np.float64)
        if abs(signed_area(p)) < min_area:
            continue
        out.append((simplify(smooth(p, sigma, True), tol, True), hier[0][i][3] != -1))
    return out


# ---------------------------------------------------------------- outlines
def outlines(ink, up=4, sigma=1.2, tol=0.15, min_area=20.0):
    """Both edges of every black area, in source pixels (y down)."""
    loops = contours(binarise(ink, up), sigma * up, tol * up, min_area * up * up)
    return [(p / up, hole) for p, hole in loops]


# ---------------------------------------------------------------- centrelines
def _skeleton_edges(sk):
    """Split a 1-px skeleton into edges between end/junction nodes."""
    H, W = sk.shape
    pix = set(zip(*np.nonzero(sk)))
    nb = {p: [(p[0] + dy, p[1] + dx) for dy, dx in N8 if (p[0] + dy, p[1] + dx) in pix] for p in pix}
    node_pix = {p for p in pix if len(nb[p]) != 2}
    # merge touching junction pixels into one node
    node_of, nodes = {}, []
    for p in node_pix:
        if p in node_of:
            continue
        stack, members = [p], []
        node_of[p] = len(nodes)
        while stack:
            q = stack.pop()
            members.append(q)
            if len(nb[q]) >= 3:
                for r in nb[q]:
                    if r in node_pix and r not in node_of and len(nb[r]) >= 3:
                        node_of[r] = len(nodes)
                        stack.append(r)
        nodes.append(np.mean(members, axis=0))
    edges, done = [], set()
    for p in node_pix:
        for q in nb[p]:
            if (p, q) in done or node_of.get(q) == node_of[p]:
                continue
            path, prev, cur = [p], p, q
            while cur not in node_pix:
                path.append(cur)
                nxt = [r for r in nb[cur] if r != prev]
                prev, cur = cur, nxt[0]
            path.append(cur)
            done.add((p, q))
            done.add((cur, prev))
            edges.append([node_of[p], node_of[cur], np.array(path, float)])
    # rings with no nodes at all
    seen = {tuple(map(int, x)) for e in edges for x in e[2]} | node_pix
    for p in pix:
        if p in seen:
            continue
        path, prev, cur = [p], None, p
        while True:
            seen.add(cur)
            nxt = [r for r in nb[cur] if r != prev and r not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            path.append(cur)
        if len(path) > 2:
            edges.append([None, None, np.array(path, float)])
    return nodes, edges


def _prune_and_merge(nodes, edges, spur_len):
    for _ in range(4):
        deg = defaultdict(int)
        for a, b, _ in edges:
            if a is not None:
                deg[a] += 1
                deg[b] += 1
        keep = []
        for a, b, p in edges:
            L = np.sum(np.hypot(*np.diff(p, axis=0).T))
            spur = a is not None and ((deg[a] == 1 and deg[b] >= 3) or (deg[b] == 1 and deg[a] >= 3))
            if not (spur and L < spur_len):
                keep.append([a, b, p])
        changed = len(keep) != len(edges)
        edges = keep
        # merge edges through nodes left with exactly two ends
        while True:
            deg = defaultdict(list)
            for i, (a, b, _) in enumerate(edges):
                if a is not None:
                    deg[a].append(i)
                    deg[b].append(i)
            n2 = next((n for n, es in deg.items() if len(es) == 2 and es[0] != es[1]), None)
            if n2 is None:
                break
            i, j = deg[n2]
            ea, eb = edges[i], edges[j]
            pa = ea[2] if ea[1] == n2 else ea[2][::-1]
            pb = eb[2] if eb[0] == n2 else eb[2][::-1]
            a0 = ea[0] if ea[1] == n2 else ea[1]
            b1 = eb[1] if eb[0] == n2 else eb[0]
            merged = [a0, b1, np.vstack([pa, pb[1:]])]
            edges = [e for k, e in enumerate(edges) if k not in (i, j)] + [merged]
            changed = True
        # a single edge whose ends meet at the same 2-degree node is a ring
        for e in edges:
            if e[0] is not None and e[0] == e[1] and sum(
                    (x[0] == e[0]) + (x[1] == e[0]) for x in edges) == 2:
                e[0] = e[1] = None
        if not changed:
            break
    return edges


def _chains(nodes, edges, look):
    """Join edges straight through junctions to reduce tool lifts."""
    ends = defaultdict(list)  # node -> [(edge idx, which end 0/1, direction)]
    for i, (a, b, p) in enumerate(edges):
        if a is None:
            continue
        for end, n in ((0, a), (1, b)):
            pts = p if end == 0 else p[::-1]
            L = np.cumsum(np.r_[0, np.hypot(*np.diff(pts, axis=0).T)])
            k = min(np.searchsorted(L, look), len(pts) - 1)
            d = pts[k] - nodes[n]
            ends[n].append((i, end, d / (np.linalg.norm(d) + 1e-9)))
    link = {}
    for n, es in ends.items():
        if len(es) < 2:
            continue
        pairs = sorted((float(np.dot(es[x][2], es[y][2])), x, y)
                       for x in range(len(es)) for y in range(x + 1, len(es)))
        used = set()
        for dot, x, y in pairs:
            if dot > -0.5 or x in used or y in used:
                continue
            used |= {x, y}
            ex, ey = es[x][:2], es[y][:2]
            link[ex], link[ey] = ey, ex
    out, used = [], set()

    def walk(i, end):  # start at edge i, entering from `end`
        pts, closed = [], False
        start = (i, end)
        while True:
            used.add(i)
            p = edges[i][2] if end == 0 else edges[i][2][::-1]
            pts.append(p if not pts else p[1:])
            nxt = link.get((i, 1 - end))
            if nxt is None:
                break
            if nxt == start:
                closed = True
                break
            if nxt[0] in used:
                break
            i, end = nxt
        return np.vstack(pts), closed

    for i, (a, b, p) in enumerate(edges):  # open chains first
        for end in (0, 1):
            if i not in used and a is not None and (i, end) not in link:
                out.append(walk(i, end))
    for i, (a, b, p) in enumerate(edges):  # what is left are loops
        if i not in used:
            if a is None:
                used.add(i)
                out.append((p, True))
            else:
                out.append(walk(i, 0))
    return out


def centrelines(ink, target_hw=12.0, thick_ratio=1.7, solid_ratio=2.5, dot_ratio=1.5,
                spur_ratio=1.2, tol=0.3, min_area=20.0):
    """Returns (paths, fills, hw) in source pixels (y down).

    paths: [(pts, closed)] along stroke centres. Complete on its own except for
           solid areas thicker than solid_ratio*hw, which it stops at.
    fills: [(pts, is_hole)] outlines of areas wider than one stroke
           (thicker than thick_ratio*hw), for optional pocketing.
    hw:    typical stroke half-width in source pixels.
    """
    hw0, _, _ = half_width(binarise(ink, 1))
    up = max(1, int(round(target_hw / max(hw0, 1.0))))
    mask = binarise(ink, up)
    hw, dist, _ = half_width(mask)
    # gently round the mask so the skeleton has fewer spurs
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.35 * hw)
    mask_s = (soft > 0.5) & mask.astype(bool)  # never bridge near-touching strokes
    sk = skeletonize(mask_s > 0)

    # solid areas: regions a disc of thick_ratio*hw fits inside, plus small round dots
    r = thick_ratio * hw
    core = (dist > r).astype(np.uint8)
    thick = cv2.distanceTransform(1 - core, cv2.DIST_L2, 5) <= r if core.any() else np.zeros_like(mask, bool)
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask)
    sk_count = np.bincount(lab[sk], minlength=n)
    dot_ids = [i for i in range(1, n)
               if sk_count[i] < dot_ratio * hw and stats[i, cv2.CC_STAT_AREA] >= min_area * up * up]
    dots = np.isin(lab, dot_ids)
    blob = (thick | dots).astype(np.uint8)
    fills = []
    if blob.any():
        grow = cv2.distanceTransform(1 - blob, cv2.DIST_L2, 5) <= 1.2 * hw
        fill_mask = (mask.astype(bool) & grow).astype(np.uint8)
        fills = contours(fill_mask, 1.2 * up, 0.15 * up, min_area * up * up)
    # the centreline stays complete through merged/wide strokes, but stops at the
    # edge of truly solid areas (e.g. big filled eyes) which only make sense as
    # pockets; small round dots become circles a stroke-width cutter clears in one loop
    rs = solid_ratio * hw
    solid_core = (dist > rs).astype(np.uint8)
    if solid_core.any():
        solid = cv2.distanceTransform(1 - solid_core, cv2.DIST_L2, 5) <= rs
        sk &= ~(mask.astype(bool) & (cv2.distanceTransform(
            1 - solid.astype(np.uint8), cv2.DIST_L2, 5) <= 1.2 * hw))
    sk &= ~dots
    dot_paths = []
    for i in dot_ids:
        rr = max(np.sqrt(stats[i, cv2.CC_STAT_AREA] / np.pi) - hw, 0.25 * hw)
        t = np.linspace(0, 2 * np.pi, 33)[:-1]
        dot_paths.append((np.c_[cents[i][0] + rr * np.cos(t), cents[i][1] + rr * np.sin(t)] / up, True))

    nodes, edges = _skeleton_edges(sk)
    edges = _prune_and_merge(nodes, edges, spur_ratio * hw)
    edges = [e for e in edges if len(e[2]) >= 2]
    paths = []
    for pts, closed in _chains(nodes, edges, 2 * hw):
        xy = pts[:, ::-1]  # (row, col) -> (x, y)
        if closed and np.hypot(*(xy[0] - xy[-1])) < 2:
            xy = xy[:-1]
        xy = simplify(smooth(xy, 0.6 * hw, closed), tol * up, closed)
        if len(xy) >= 2 and np.sum(np.hypot(*np.diff(xy, axis=0).T)) >= 0.5 * hw:
            paths.append((xy / up, closed))
    return paths + dot_paths, [(p / up, h) for p, h in fills], hw / up


# ---------------------------------------------------------------- border
def border(ink, offset_px, up=2):
    """Offset outline around the whole drawing (like a sticker die-cut)."""
    mask = binarise(ink, up)
    pad = int(offset_px * up) + 4
    mask = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    grown = (cv2.distanceTransform(1 - mask, cv2.DIST_L2, 5) <= offset_px * up).astype(np.uint8)
    cs, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    c = simplify(smooth(c, 1.5 * up, True), 0.15 * up, True)
    return [((c - pad) / up, False)]


# ---------------------------------------------------------------- output
LAYERS = {"OUTSIDE": 1, "INSIDE": 5, "CENTERLINE": 3, "FILL_OUTSIDE": 6,
          "FILL_INSIDE": 4, "BORDER": 8}


def write_dxf(out, ink_h, width_mm, outline_loops, paths=(), fills=(), border_loops=()):
    """All inputs in source pixels with y down; outputs mm, y up."""
    allx = np.concatenate([p[:, 0] for p, _ in outline_loops])
    ally = np.concatenate([ink_h - p[:, 1] for p, _ in outline_loops])
    x0, y0 = allx.min(), ally.min()
    s = width_mm / (allx.max() - x0)

    def tf(p):
        return np.c_[(p[:, 0] - x0) * s, (ink_h - p[:, 1] - y0) * s].round(4)

    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()

    def add(layer, p, closed, hole=None):
        if layer not in doc.layers:
            doc.layers.add(layer, color=LAYERS[layer])
        q = tf(p)
        if closed and hole is not None and (signed_area(q) < 0) != hole:
            q = q[::-1]  # outer loops CCW, holes CW
        msp.add_lwpolyline(q.tolist(), close=closed, dxfattribs={"layer": layer})

    for p, hole in outline_loops:
        add("INSIDE" if hole else "OUTSIDE", p, True, hole)
    for p, closed in paths:
        add("CENTERLINE", p, closed)
    for p, hole in fills:
        add("FILL_INSIDE" if hole else "FILL_OUTSIDE", p, True, hole)
    for p, _ in border_loops:
        add("BORDER", p, True, False)
    doc.saveas(out)
    return s, (allx.max() - x0) * s, (ally.max() - y0) * s
