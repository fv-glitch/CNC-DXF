"""Trace Kilroy-source.webp -> Kilroy.dxf.

Usage:
    pip install ezdxf opencv-python-headless numpy pillow
    python Kilroy.py [output.dxf] [--width MM]

Traces both edges of every black stroke as closed polylines, so the
drawing can be V-carved or pocketed. Scaled to --width mm wide (default
200); rescale freely in CAM. Origin at the bottom-left of the drawing.

Layers:
    OUTSIDE  outer edge of each black area, incl. the eyes (counter-clockwise)
    INSIDE   edges of the white areas enclosed by the strokes (clockwise)
"""
import argparse
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "Kilroy-source.webp"

UPSAMPLE = 4        # trace on an upsampled copy for sub-pixel edges
SMOOTH_SIGMA = 1.2  # contour smoothing, in source pixels
SIMPLIFY_TOL = 0.15 # max deviation when reducing points, in source pixels
MIN_AREA = 20.0     # drop specks smaller than this, in source pixels^2


def ink_mask(path):
    """Greyscale 'ink' image (0 = paper, 255 = ink) from an RGBA/RGB file."""
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).astype(np.float32) / 255.0
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    ink = a[..., 3] * (1.0 - lum)  # transparent or white -> 0, opaque black -> 1
    return (ink * 255).astype(np.uint8)


def smooth_closed(pts, sigma):
    """Gaussian-smooth a closed contour along its length."""
    if sigma <= 0 or len(pts) < 8:
        return pts
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    padded = np.vstack([pts[-r:], pts, pts[:r]])
    return np.c_[np.convolve(padded[:, 0], k, "valid"),
                 np.convolve(padded[:, 1], k, "valid")]


def signed_area(p):
    return 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])


def trace(path):
    ink = ink_mask(path)
    # the artwork touches the image edges; pad so every loop closes cleanly
    ink = cv2.copyMakeBorder(ink, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=0)
    h, w = ink.shape
    big = cv2.resize(ink, (w * UPSAMPLE, h * UPSAMPLE), interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
    contours, hier = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    loops = []
    for i, c in enumerate(contours):
        p = c[:, 0, :].astype(np.float64) / UPSAMPLE  # source px, y down
        if abs(signed_area(p)) < MIN_AREA:
            continue
        is_hole = hier[0][i][3] != -1
        p = smooth_closed(p, SMOOTH_SIGMA * UPSAMPLE)
        p = cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2),
                             SIMPLIFY_TOL, True)[:, 0, :].astype(np.float64)
        p[:, 1] = h - p[:, 1]  # y up
        a = signed_area(p)
        if (a < 0) != is_hole:  # outer CCW, holes CW
            p = p[::-1]
        loops.append((p, is_hole))
    return loops, w, h


def build(out, width_mm):
    loops, w, h = trace(SRC)
    xs = np.concatenate([p[:, 0] for p, _ in loops])
    ys = np.concatenate([p[:, 1] for p, _ in loops])
    x0, y0 = xs.min(), ys.min()
    s = width_mm / (xs.max() - x0)

    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.layers.add("OUTSIDE", color=1)  # outer edge of each black area (incl. eyes)
    doc.layers.add("INSIDE", color=5)   # edges of the white areas enclosed by the strokes
    msp = doc.modelspace()
    for p, is_hole in loops:
        q = (p - [x0, y0]) * s
        msp.add_lwpolyline(q.round(4).tolist(), close=True,
                           dxfattribs={"layer": "INSIDE" if is_hole else "OUTSIDE"})
    doc.saveas(out)
    return loops, s, (xs.max() - x0) * s, (ys.max() - y0) * s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(HERE / "Kilroy.dxf"))
    ap.add_argument("--width", type=float, default=200.0, help="drawing width in mm")
    args = ap.parse_args()
    loops, s, W, H = build(args.out, args.width)
    n_holes = sum(hole for _, hole in loops)
    print(f"wrote {args.out}: {len(loops)} closed loops "
          f"({len(loops) - n_holes} outer, {n_holes} inner), "
          f"{sum(len(p) for p, _ in loops)} vertices, {W:.1f} x {H:.1f} mm")
