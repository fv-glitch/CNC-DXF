"""Windsor Nido 8427 passage set -> door-EDGE DXF (1172 tubular latch).

Usage:
    pip install ezdxf
    python Nido-Passage-Edge.py [output.dxf] [--clearance MM] [--corner MM]

Drawn on the door edge, units mm. Origin = latch bore centre: X across the door
thickness (0 = middle of the edge), Y up the door (0 = spindle height, the same
Y as Nido-Passage-Door.dxf). The latch is symmetric, so one file suits LH and RH.

Latch 1172: 57 mm backset (spindle centre is 57 in from this edge), 77 mm case.
Faceplate measured with calipers: 60.14 x 25.30, screws ~45 apart on its centreline.
Edge bore Ø26 (bore at least the 77 mm case deep).

Layers:
    FACEPLATE_MORTISE  faceplate outline + clearance, R`corner` corners; cut with
                       the tool INSIDE (R2 suits bits up to Ø4)
    FACEPLATE_SCREWS   POINTs for the two faceplate screw pilots
    BORE_CENTRE        POINT at the Ø26 latch bore centre
    REFERENCE          Ø26 bore circle and the bare faceplate outline, not for cutting
"""
import argparse
import math
from pathlib import Path

import ezdxf

FP_LENGTH = 60.14    # faceplate, along the door height
FP_WIDTH = 25.30     # faceplate, across the door thickness
FP_SCREWS = 45.0     # faceplate screw centres
BORE_D = 26.0
BACKSET = 57.0


def rounded_rect(w, h, r):
    """Closed CCW (x, y, bulge) rectangle centred on the origin with corner radius r."""
    x, y = w / 2, h / 2
    if r <= 0:
        return [(x, -y, 0), (x, y, 0), (-x, y, 0), (-x, -y, 0)]
    b = math.tan(math.radians(90) / 4)  # quarter-circle bulge
    return [
        (x, -y + r, 0), (x, y - r, b), (x - r, y, 0), (-x + r, y, b),
        (-x, y - r, 0), (-x, -y + r, b), (-x + r, -y, 0), (x - r, -y, b),
    ]


def build(out, clearance=0.1, corner=2.0):
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # same point style as the other Nido files
    doc.header["$PDSIZE"] = 0.8
    doc.layers.add("FACEPLATE_MORTISE", color=4)
    doc.layers.add("FACEPLATE_SCREWS", color=3)
    doc.layers.add("BORE_CENTRE", color=1)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()
    msp.add_lwpolyline(rounded_rect(FP_WIDTH + 2 * clearance, FP_LENGTH + 2 * clearance, corner),
                       format="xyb", close=True, dxfattribs={"layer": "FACEPLATE_MORTISE"})
    screws = [(0.0, FP_SCREWS / 2), (0.0, -FP_SCREWS / 2)]
    for p in screws:
        msp.add_point(p, dxfattribs={"layer": "FACEPLATE_SCREWS"})
    msp.add_point((0.0, 0.0), dxfattribs={"layer": "BORE_CENTRE"})
    msp.add_circle((0.0, 0.0), BORE_D / 2, dxfattribs={"layer": "REFERENCE"})
    msp.add_lwpolyline(rounded_rect(FP_WIDTH, FP_LENGTH, 0), format="xyb", close=True,
                       dxfattribs={"layer": "REFERENCE"})
    doc.saveas(out)
    return screws


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(Path(__file__).with_suffix(".dxf")))
    ap.add_argument("--clearance", type=float, default=0.1,
                    help="mortise clearance each side of the faceplate, mm (default 0.1)")
    ap.add_argument("--corner", type=float, default=2.0,
                    help="mortise corner radius, mm (default 2.0; keep >= tool radius)")
    args = ap.parse_args()
    screws = build(Path(args.out), args.clearance, args.corner)
    w, h = FP_WIDTH + 2 * args.clearance, FP_LENGTH + 2 * args.clearance
    print(f"wrote {args.out}: mortise {w:.2f} x {h:.2f} R{args.corner}, screws {screws}, "
          f"bore Ø{BORE_D} at origin")
