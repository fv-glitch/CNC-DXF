"""Windsor Nido 8427 passage set -> door-JAMB (frame) DXF for the latch striker.

Usage:
    pip install ezdxf
    python Nido-Passage-Striker.py [output.dxf] [--clearance MM] [--corner MM]

Drawn on the jamb face the latch hits, units mm. Origin = centre of the striker's
latch opening: Y up the jamb (0 = latch / spindle height, the same Y as the door
files), X across the jamb. The opening centre must line up with the latch tongue,
i.e. half the door thickness out from the door stop (+X is toward the stop).
The curved lip points away from the stop and is housed too: its slot runs straight
on off the jamb edge. For the other hand of frame, mirror the file in X.

Caliper readings (stainless striker): plate 65.14 x 25.26, screws 45.00 apart,
curved lip 40.28 wide (housed, runs off the jamb edge). Dust box 24.92 x 18.68.

Layers:
    STRIKER_MORTISE  T-shape: plate + lip slot (+ clearance) running `lip_runout` past
                     the plate so it exits the jamb edge; cut with the tool INSIDE.
                     Plate corners are R`corner`; the plate's own corners are
                     near-square, so square them up by hand (or use a smaller bit).
    BOX_POCKET       dust box body + clearance, deeper pocket behind the opening
    STRIKER_SCREWS   POINTs for the two striker screw pilots
    STRIKER_CENTRE   POINT at the latch opening centre
    REFERENCE        bare plate, lip and dust box outlines, not for cutting
"""
import argparse
import math
from pathlib import Path

import ezdxf

PLATE_LENGTH = 65.14   # along the jamb (Y)
PLATE_WIDTH = 25.26    # across the jamb (X)
SCREWS = 45.00         # screw centres, along Y
LIP_WIDTH = 40.28      # curved lip, along Y
LIP_REACH = 12.0       # how far the lip sticks out past the plate (photo estimate)
LIP_RUNOUT = 15.0      # lip slot length past the plate edge: beyond LIP_REACH so it runs off the jamb
BOX_LENGTH = 24.92     # dust box body, along Y (in line with its screw ears)
BOX_WIDTH = 18.68      # dust box body, across X


def rounded_rect(w, h, r, cx=0.0, cy=0.0):
    """Closed CCW (x, y, bulge) rectangle w (X) by h (Y) with corner radius r."""
    x, y = w / 2, h / 2
    if r <= 0:
        pts = [(x, -y, 0), (x, y, 0), (-x, y, 0), (-x, -y, 0)]
    else:
        b = math.tan(math.radians(90) / 4)  # quarter-circle bulge
        pts = [(x, -y + r, 0), (x, y - r, b), (x - r, y, 0), (-x + r, y, b),
               (-x, y - r, 0), (-x, -y + r, b), (-x + r, -y, 0), (x - r, -y, b)]
    return [(px + cx, py + cy, pb) for px, py, pb in pts]


def striker_mortise(c, r, runout):
    """CCW (x, y, bulge) T-outline: plate + lip slot toward -X, plate corners radius r."""
    w, h, lw = PLATE_WIDTH / 2 + c, PLATE_LENGTH / 2 + c, LIP_WIDTH / 2 + c
    xl = -PLATE_WIDTH / 2 - runout
    b = math.tan(math.radians(90) / 4)
    return [
        (w, -h + r, 0), (w, h - r, b), (w - r, h, 0), (-w + r, h, b),   # +X side and top
        (-w, h - r, 0), (-w, lw, 0),                                    # down to the lip
        (xl, lw, 0), (xl, -lw, 0), (-w, -lw, 0),                        # lip slot, off the jamb
        (-w, -h + r, b), (-w + r, -h, 0), (w - r, -h, b),               # bottom
    ]


def build(out, clearance=0.1, corner=1.6, box_clearance=0.2, lip_runout=LIP_RUNOUT):
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # same point style as the other Nido files
    doc.header["$PDSIZE"] = 0.8
    doc.layers.add("STRIKER_MORTISE", color=4)
    doc.layers.add("BOX_POCKET", color=6)
    doc.layers.add("STRIKER_SCREWS", color=3)
    doc.layers.add("STRIKER_CENTRE", color=1)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()
    poly = lambda v, layer: msp.add_lwpolyline(v, format="xyb", close=True,
                                               dxfattribs={"layer": layer})
    poly(striker_mortise(clearance, corner, lip_runout), "STRIKER_MORTISE")
    poly(rounded_rect(BOX_WIDTH + 2 * box_clearance, BOX_LENGTH + 2 * box_clearance, corner),
         "BOX_POCKET")
    screws = [(0.0, SCREWS / 2), (0.0, -SCREWS / 2)]
    for p in screws:
        msp.add_point(p, dxfattribs={"layer": "STRIKER_SCREWS"})
    msp.add_point((0.0, 0.0), dxfattribs={"layer": "STRIKER_CENTRE"})
    # reference: bare plate, lip (on the side away from the stop) and dust box
    poly(rounded_rect(PLATE_WIDTH, PLATE_LENGTH, 0), "REFERENCE")
    poly(rounded_rect(LIP_REACH, LIP_WIDTH, 0, cx=-(PLATE_WIDTH + LIP_REACH) / 2), "REFERENCE")
    poly(rounded_rect(BOX_WIDTH, BOX_LENGTH, 0), "REFERENCE")
    doc.saveas(out)
    return screws


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(Path(__file__).with_suffix(".dxf")))
    ap.add_argument("--clearance", type=float, default=0.1,
                    help="striker mortise clearance each side, mm (default 0.1)")
    ap.add_argument("--box-clearance", type=float, default=0.2,
                    help="dust box pocket clearance each side, mm (default 0.2)")
    ap.add_argument("--corner", type=float, default=1.6,
                    help="corner radius of both pockets, mm (default 1.6: suits a 3 mm bit)")
    ap.add_argument("--lip-runout", type=float, default=LIP_RUNOUT,
                    help="lip slot length past the plate edge, mm (default 15; must clear the jamb edge)")
    a = ap.parse_args()
    screws = build(Path(a.out), a.clearance, a.corner, a.box_clearance, a.lip_runout)
    print(f"wrote {a.out}: mortise {PLATE_WIDTH + 2 * a.clearance:.2f} x "
          f"{PLATE_LENGTH + 2 * a.clearance:.2f} + lip slot {LIP_WIDTH + 2 * a.clearance:.2f} wide x {a.lip_runout} out, box pocket {BOX_WIDTH + 2 * a.box_clearance:.2f} x "
          f"{BOX_LENGTH + 2 * a.box_clearance:.2f}, R{a.corner}, screws {screws}")
