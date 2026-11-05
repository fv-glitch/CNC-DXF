"""Trace Dickbutt-source.webp -> Dickbutt.dxf.

Usage:
    pip install ezdxf opencv-python-headless numpy pillow scipy scikit-image
    python Dickbutt.py [output.dxf] [--width MM]

Scaled so the artwork is --width mm wide (default 200); rescale freely in CAM.
Origin at the bottom-left of the artwork (the border extends a little past it).

Layers:
    OUTSIDE       outer edge of each black area (counter-clockwise)
    INSIDE        edges of the white areas enclosed by the strokes (clockwise)
    CENTERLINE    single-line paths along the middle of every stroke; stops at
                  the edge of the solid eyes
    FILL_OUTSIDE  the solid eyes (with their highlight notch): pocket these
    BORDER        sticker-style die-cut outline, ~20 source px outside the art
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import linetrace as lt  # noqa: E402

SRC = HERE / "Dickbutt-source.webp"
BORDER_PX = 20.0  # sticker edge sits ~20 source px outside the artwork


def build(out, width_mm):
    ink = lt.ink_mask(SRC)
    loops = lt.outlines(ink)
    paths, fills, hw = lt.centrelines(ink)
    edge = lt.border(ink, BORDER_PX)
    s, W, H = lt.write_dxf(out, ink.shape[0], width_mm, loops, paths, fills, edge)
    return loops, paths, fills, 2 * hw * s, BORDER_PX * s, W, H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(HERE / "Dickbutt.dxf"))
    ap.add_argument("--width", type=float, default=200.0, help="artwork width in mm")
    args = ap.parse_args()
    loops, paths, fills, stroke, off, W, H = build(args.out, args.width)
    holes = sum(h for _, h in loops)
    print(f"wrote {args.out}: {W:.1f} x {H:.1f} mm, stroke ~{stroke:.2f} mm, border offset {off:.1f} mm")
    print(f"  outline: {len(loops) - holes} outside + {holes} inside loops")
    print(f"  centerline: {len(paths)} paths ({sum(c for _, c in paths)} closed), "
          f"fill: {len(fills)} loops")
