"""Shared tracer: black line art image -> CNC-ready DXF.

pip install ezdxf opencv-python-headless numpy pillow scipy scikit-image

Every path is fitted with as few lines and true arcs as possible (no splines,
no segments under 0.5 mm) so CNC controllers such as SCM Maestro cut it smoothly.

Layers written (LWPOLYLINEs with arcs, or separate LINE/ARC entities; mm):
    OUTSIDE       outer edge of every black area (counter-clockwise)
    INSIDE        edges of white areas enclosed by black (clockwise)
    CENTERLINE    single-line paths along the middle of each stroke
    FILL_OUTSIDE  outer edge of solid areas too wide for one stroke-width pass
    FILL_INSIDE   white islands inside those solid areas
    BORDER        optional offset outline around the whole drawing

Everything is scaled so the OUTSIDE geometry is `width_mm` wide, with the
origin at its bottom-left corner.
"""
import math
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


def resample(p, step, closed):
    """Keep every `step`-th point (and the last point of open paths)."""
    q = p[::max(1, int(step))]
    if not closed and not np.array_equal(q[-1], p[-1]):
        q = np.vstack([q, p[-1:]])
    return q


def contours(mask, sigma, step, min_area):
    """Closed loops of a binary mask -> [(dense pts (x, y-down), is_hole)]."""
    cs, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    for i, c in enumerate(cs):
        p = c[:, 0, :].astype(np.float64)
        if abs(signed_area(p)) < min_area:
            continue
        out.append((resample(smooth(p, sigma, True), step, True), hier[0][i][3] != -1))
    return out


# ---------------------------------------------------------------- arc fitting
def _circle3(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    sa, sb, sc = a @ a, b @ b, c @ c
    ux = (sa * (b[1] - c[1]) + sb * (c[1] - a[1]) + sc * (a[1] - b[1])) / d
    uy = (sa * (c[0] - b[0]) + sb * (a[0] - c[0]) + sc * (b[0] - a[0])) / d
    ctr = np.array([ux, uy])
    return ctr, float(np.hypot(*(a - ctr)))


def _line_fits(P, i, j, tol):
    a, d = P[i], P[j] - P[i]
    seg = P[i:j + 1]
    L2 = d @ d
    t = np.clip(((seg - a) @ d) / L2, 0, 1) if L2 > 1e-18 else np.zeros(len(seg))
    return np.max(np.hypot(*(seg - a - t[:, None] * d).T)) <= tol


def _arc_sweep(P, i, j, tol):
    """Signed sweep (rad) of an arc from P[i] to P[j] within tol of all points, else None."""
    if j - i < 2:
        return None
    m = (i + j) // 2
    cr = _circle3(P[i], P[m], P[j])
    if cr is None:
        return None
    c, r = cr
    if r < 2 * tol or r > 1e5 * tol:
        return None
    seg = P[i:j + 1]
    if np.max(np.abs(np.hypot(*(seg - c).T) - r)) > tol:
        return None
    v1, v2 = P[m] - P[i], P[j] - P[m]
    ccw = v1[0] * v2[1] - v1[1] * v2[0] > 0
    ang = np.arctan2(seg[:, 1] - c[1], seg[:, 0] - c[0])
    rel = (ang - ang[0]) if ccw else (ang[0] - ang)
    slack = 2 * tol / r + 1e-9
    rel = (rel + slack) % (2 * np.pi) - slack
    sweep = rel[-1]
    if sweep <= 0 or sweep > 1.9 * np.pi or np.any(np.diff(rel) < -slack):
        return None
    return sweep if ccw else -sweep


def _reach(ok, i, n, first):
    """Largest j >= first with ok(j), assuming ok is (mostly) monotone; None if none."""
    if first > n - 1 or not ok(first):
        return None
    lo, step = first, 1
    while True:
        hi = min(first + step, n - 1)
        if hi == lo or not ok(hi):
            break
        lo, step = hi, step * 2
        if hi == n - 1:
            return lo
    hi = min(first + step, n - 1)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def fit_arcs(P, tol, closed, min_len=0.0):
    """Dense polyline -> [(x, y, bulge)] of lines and arcs within tol.

    Greedy longest-fit, then segments shorter than min_len are merged into a
    neighbour or have their shared vertex moved, where that still fits.
    """
    P = np.asarray(P, float)
    if closed:
        # start at the sharpest corner so a smooth stretch isn't split needlessly
        d1, d2 = P - np.roll(P, 1, 0), np.roll(P, -1, 0) - P
        turn = np.abs(np.arctan2(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0], (d1 * d2).sum(1)))
        k = int(np.argmax(turn))
        P = np.vstack([np.roll(P, -k, 0), np.roll(P, -k, 0)[:1]])
    n = len(P)

    def fit(a, b):  # bulge of the best single segment P[a]..P[b], or None
        if _line_fits(P, a, b, tol):
            return 0.0
        sw = _arc_sweep(P, a, b, tol)
        return None if sw is None else math.tan(sw / 4)

    def length(a, b, bulge):
        c = float(np.hypot(*(P[b] - P[a])))
        if bulge:
            th = 4 * math.atan(abs(bulge))
            c *= th / (2 * math.sin(th / 2))
        return c

    B, i = [0], 0  # segment boundaries (indices into P)
    while i < n - 1:
        jl = _reach(lambda j: _line_fits(P, i, j, tol), i, n, i + 1)
        ja = _reach(lambda j: _arc_sweep(P, i, j, tol) is not None, i, n, i + 2)
        i = ja if ja is not None and ja > jl else jl
        B.append(i)
    G = [fit(a, b) for a, b in zip(B[:-1], B[1:])]

    for _ in range(4 * len(B)):
        short = [k for k in range(len(G)) if length(B[k], B[k + 1], G[k]) < min_len]
        if not short:
            break
        done = False
        for k in short:
            # 1) merge with a neighbour
            for lo, hi in ((k - 1, k + 1), (k, k + 2)):
                if lo >= 0 and hi < len(B) and (g := fit(B[lo], B[hi])) is not None:
                    del B[lo + 1]
                    G[lo:hi] = [g]
                    done = True
                    break
            if done:
                break
            # 2) move the vertex shared with a neighbour to lengthen the short one
            cur = length(B[k], B[k + 1], G[k])
            best = None
            for lo, mid, hi in ((k - 1, k, k + 1), (k, k + 1, k + 2)):
                if lo < 0 or hi >= len(B):
                    continue
                for j in range(B[lo] + 1, B[hi]):
                    g1, g2 = fit(B[lo], j), fit(j, B[hi])
                    if g1 is None or g2 is None:
                        continue
                    score = min(length(B[lo], j, g1), length(j, B[hi], g2))
                    if score > cur and (best is None or score > best[0]):
                        best = (score, mid, j, lo, g1, g2)
            if best:
                _, mid, j, lo, g1, g2 = best
                B[mid] = j
                G[lo], G[lo + 1] = g1, g2
                done = True
                break
        if not done:
            break

    out = [(P[a][0], P[a][1], g) for a, g in zip(B[:-1], G)]
    if not closed:
        out.append((P[-1][0], P[-1][1], 0.0))
    return out


# ---------------------------------------------------------------- outlines
def outlines(ink, up=4, sigma=1.2, min_area=20.0):
    """Both edges of every black area, dense, in source pixels (y down)."""
    loops = contours(binarise(ink, up), sigma * up, up, min_area * up * up)
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
                spur_ratio=1.2, min_area=20.0):
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
        fills = contours(fill_mask, 1.2 * up, up, min_area * up * up)
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
        t = np.linspace(0, 2 * np.pi, 97)[:-1]
        dot_paths.append((np.c_[cents[i][0] + rr * np.cos(t), cents[i][1] + rr * np.sin(t)] / up, True))

    nodes, edges = _skeleton_edges(sk)
    edges = _prune_and_merge(nodes, edges, spur_ratio * hw)
    edges = [e for e in edges if len(e[2]) >= 2]
    paths = []
    for pts, closed in _chains(nodes, edges, 2 * hw):
        xy = pts[:, ::-1]  # (row, col) -> (x, y)
        if closed and np.hypot(*(xy[0] - xy[-1])) < 2:
            xy = xy[:-1]
        xy = resample(smooth(xy, 0.6 * hw, closed), up, closed)
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
    c = resample(smooth(c, 1.5 * up, True), up, True)
    return [((c - pad) / up, False)]


# ---------------------------------------------------------------- output
LAYERS = {"OUTSIDE": 1, "INSIDE": 5, "CENTERLINE": 3, "FILL_OUTSIDE": 6,
          "FILL_INSIDE": 4, "BORDER": 8}


def write_dxf(out, ink_h, width_mm, outline_loops, paths=(), fills=(), border_loops=(),
              tol_px=0.3, tol_mm=None, explode=False, min_seg_mm=0.5):
    """All inputs in source pixels with y down; outputs mm, y up.

    Each path is fitted with as few lines and true arcs as possible while staying
    within tol_px source pixels (or tol_mm, if given) of the traced curve (CNC controllers such as SCM
    Maestro handle long lines/arcs far better than thousands of tiny segments).
    Written as LWPOLYLINEs with arc bulges, or with explode=True as separate
    LINE/ARC entities.
    """
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
        v = fit_arcs(q, tol_mm if tol_mm else tol_px * s, closed, min_seg_mm)
        attrs = {"layer": layer}
        if not explode:
            msp.add_lwpolyline(v, format="xyb", close=closed, dxfattribs=attrs)
            return
        pairs = list(zip(v, v[1:] + v[:1])) if closed else list(zip(v[:-1], v[1:]))
        for (x0_, y0_, b), (x1_, y1_, _) in pairs:
            if b == 0:
                msp.add_line((x0_, y0_), (x1_, y1_), dxfattribs=attrs)
            else:
                c, a0, a1, r = ezdxf.math.bulge_to_arc((x0_, y0_), (x1_, y1_), b)
                msp.add_arc(c, r, math.degrees(a0), math.degrees(a1), dxfattribs=attrs)

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
