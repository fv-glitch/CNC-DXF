"""Trace Kilroy-source.webp -> Kilroy.dxf.

Usage:
    pip install ezdxf opencv-python-headless numpy pillow scipy scikit-image
    python Kilroy.py [output.dxf] [--width MM] [--explode] [--tol MM]

Scaled to --width mm wide (default 200); rescale freely in CAM.
Origin at the bottom-left of the drawing.

Layers:
    OUTSIDE       outer edge of each black area, incl. the eyes (counter-clockwise)
    INSIDE        edges of the white areas enclosed by the strokes (clockwise)
    CENTERLINE    single-line paths along the middle of every stroke; complete on
                  its own (eye dots are small loops a stroke-width cutter clears)
    FILL_OUTSIDE  areas wider than one stroke-width pass (eye dots, where finger
                  strokes merge), for optional pocketing
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import linetrace as lt  # noqa: E402

SRC = HERE / "Kilroy-source.webp"


def build(out, width_mm, explode=False, tol_mm=None):
    ink = lt.ink_mask(SRC)
    loops = lt.outlines(ink)
    paths, fills, hw = lt.centrelines(ink)
    s, W, H = lt.write_dxf(out, ink.shape[0], width_mm, loops, paths, fills,
                           explode=explode, tol_mm=tol_mm)
    return loops, paths, fills, 2 * hw * s, W, H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(HERE / "Kilroy.dxf"))
    ap.add_argument("--explode", action="store_true",
                    help="write separate LINE/ARC entities instead of polylines")
    ap.add_argument("--tol", type=float, default=None,
                    help="max deviation from the traced curve in mm (default 0.3 source px)")
    ap.add_argument("--width", type=float, default=200.0, help="drawing width in mm")
    args = ap.parse_args()
    loops, paths, fills, stroke, W, H = build(args.out, args.width, args.explode, args.tol)
    holes = sum(h for _, h in loops)
    print(f"wrote {args.out}: {W:.1f} x {H:.1f} mm, stroke ~{stroke:.2f} mm")
    print(f"  outline: {len(loops) - holes} outside + {holes} inside loops")
    print(f"  centerline: {len(paths)} paths ({sum(c for _, c in paths)} closed), "
          f"fill: {len(fills)} loops")
