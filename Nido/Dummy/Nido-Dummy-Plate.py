"""Windsor Nido dummy fixing plate -> DXF.

Usage:
    pip install ezdxf
    python Nido-Dummy-Plate.py [output.dxf]

Writes Nido-Dummy-Plate.dxf next to this script unless an output path is given.

Origin = spindle centre, +Y toward the notch, units mm.
Caliper-measured: overall width 29.94, overall height 31.23,
across flats 24.93, bottom edge -> top of flat 17.52.
Photo-derived (scaled from the calipered values): outer R16, notch,
hole PCD/diameter, hub ring.

Layers:
    OUTLINE       closed polyline (lines + true arcs) of the plate profile
    HOLES         screw hole circles
    HOLE_CENTRES  POINT at the centre of each screw hole (for drilling ops)
    REFERENCE     hub ring and spindle centre cross, not for cutting
"""
import math
import sys
from pathlib import Path

import ezdxf

# ---- caliper measurements ----
W_EARS = 29.94      # overall width (ear tip to ear tip)
H_TOTAL = 31.23     # overall height (bottom of arc to top of notch shoulders)
W_FLATS = 24.93     # across the two parallel flats
H_FLAT_TOP = 17.52  # bottom of arc to top end of the flats

# ---- photo-derived ----
R = 16.0            # outer arc radius, concentric with spindle
NOTCH_HW = 3.80     # notch half-width (7.6 wide U-slot)
NOTCH_YC = 13.70    # centre of the notch's round bottom (bottom at 9.9)
HOLE_D = 3.8
HOLE_PCD = 23.1
HOLE_ANGLES = (30.0, 150.0, 270.0)
BOSS_D = 12.4       # raised hub ring (reference only)

# ---- derived geometry ----
xf = W_FLATS / 2
y_flat_top = -R + H_FLAT_TOP
x_tip = W_EARS / 2
y_tip = math.sqrt(R * R - x_tip * x_tip)
y_flat_bot = -math.sqrt(R * R - xf * xf)
y_shoulder = H_TOTAL - R  # highest point of the outline


def shoulder_top(rf):
    fx = NOTCH_HW + rf
    fy = math.sqrt((R - rf) ** 2 - fx * fx)
    return fy + rf  # fillet arc passes through its own top (centre angle < 90 deg)


# solve the notch-shoulder fillet radius so the outline peaks at y_shoulder
lo, hi = 0.0, 3.0
for _ in range(100):
    mid = (lo + hi) / 2
    if shoulder_top(mid) > y_shoulder:
        lo = mid
    else:
        hi = mid
RF = (lo + hi) / 2
FX = NOTCH_HW + RF
FY = math.sqrt((R - RF) ** 2 - FX * FX)
TX, TY = FX * R / (R - RF), FY * R / (R - RF)  # fillet / outer-arc tangent point
assert FY > NOTCH_YC, "fillet must sit above the notch's round bottom"


def ang(x, y, cx=0.0, cy=0.0):
    return math.atan2(y - cy, x - cx)


def bulge(a0, a1, ccw):
    sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
    return math.tan(sweep / 4)


# outline vertices (x, y, bulge-to-next), counter-clockwise
outline = [
    (x_tip, y_tip, bulge(ang(x_tip, y_tip), ang(TX, TY), True)),        # outer arc
    (TX, TY, bulge(ang(TX, TY, FX, FY), math.pi, True)),                # R shoulder fillet
    (NOTCH_HW, FY, 0),                                                  # notch wall
    (NOTCH_HW, NOTCH_YC, bulge(0, math.pi, False)),                     # notch round bottom
    (-NOTCH_HW, NOTCH_YC, 0),                                           # notch wall
    (-NOTCH_HW, FY, bulge(0, ang(-TX, TY, -FX, FY), True)),             # L shoulder fillet
    (-TX, TY, bulge(ang(-TX, TY), ang(-x_tip, y_tip), True)),           # outer arc
    (-x_tip, y_tip, 0),                                                 # L ear chamfer
    (-xf, y_flat_top, 0),                                               # L flat
    (-xf, y_flat_bot, bulge(ang(-xf, y_flat_bot), ang(xf, y_flat_bot), True)),  # bottom arc
    (xf, y_flat_bot, 0),                                                # R flat
    (xf, y_flat_top, 0),                                                # R ear chamfer, closes
]

holes = [
    (round(HOLE_PCD / 2 * math.cos(math.radians(a)), 6) + 0.0,  # + 0.0 drops -0.0
     round(HOLE_PCD / 2 * math.sin(math.radians(a)), 6) + 0.0)
    for a in HOLE_ANGLES
]


def build(out):
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # show points as an X
    doc.header["$PDSIZE"] = 0.8   # point marker size, mm
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("HOLES", color=1)
    doc.layers.add("HOLE_CENTRES", color=3)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()

    msp.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in outline], format="xyseb",
                       close=True, dxfattribs={"layer": "OUTLINE"})
    for c in holes:
        msp.add_circle(c, HOLE_D / 2, dxfattribs={"layer": "HOLES"})
        msp.add_point(c, dxfattribs={"layer": "HOLE_CENTRES"})
    msp.add_circle((0, 0), BOSS_D / 2, dxfattribs={"layer": "REFERENCE"})
    msp.add_line((-2, 0), (2, 0), dxfattribs={"layer": "REFERENCE"})
    msp.add_line((0, -2), (0, 2), dxfattribs={"layer": "REFERENCE"})
    doc.saveas(out)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_suffix(".dxf")
    build(out)
    print(f"wrote {out}")
    print(f"  shoulder fillet R{RF:.3f}, ear tips (+/-{x_tip:.3f}, {y_tip:.3f}), "
          f"flats y {y_flat_bot:.3f}..{y_flat_top:.3f}")
    for x, y in holes:
        print(f"  hole centre ({x:7.3f}, {y:7.3f})  dia {HOLE_D}")
