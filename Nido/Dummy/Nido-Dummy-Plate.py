"""Windsor Nido 8423 Verge Longplate Dummy Set -> DXF (plate + LH/RH door layouts).

Usage:
    pip install ezdxf
    python Nido-Dummy-Plate.py [output.dxf] [--clearance MM]

Writes Nido-Dummy-Plate.dxf next to this script unless an output path is given.

Origin = spindle centre, +Y toward the notch, units mm.
Caliper-measured: overall width 29.94, overall height 31.23,
across flats 24.93, bottom edge -> top of flat 17.52.
Photo-derived (scaled from the calipered values): outer R16, notch,
hole PCD/diameter, hub ring.

Layers:
    OUTLINE       closed polyline (lines + true arcs) of the true plate profile;
                  cut this with the tool OUTSIDE (e.g. to make a plate/template)
    RECESS        outline + clearance with sharp notch shoulders; cut this with
                  the tool INSIDE (pocket/recess the plate drops into), any tool size
    HOLES         screw hole circles
    PLATE_PILOT_CENTRES  POINT at the centre of each screw hole (pilot drilling)
    REFERENCE     hub ring and spindle centre cross, not for cutting

Also writes door-face layouts Nido-Dummy-Door-LH.dxf / -RH.dxf (spindle at the
origin, backplate vertical, +Y up): RECESS rotated so the notch points away from
the lever, POINTs for the two backplate screws (65 above, 135 below the spindle;
measured off a ruler photo; PILOT_CENTRES), the round plate's three screws
(PLATE_PILOT_CENTRES) and the spindle centre. LH = hinges on the left,
lever pointing left, as seen from the face being machined.
"""
import argparse
import math
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


def recess_profile(c):
    """Outline offset outward by clearance c, for routing a recess from the inside.

    Same lines/arcs as the plate, but the notch shoulders are sharp instead of
    filleted: an R0.95 convex arc can't be followed by any tool bigger than
    1.9 mm when cutting inside (Maestro: "Profile Radius less Tool Radius"),
    whereas a sharp corner works with any tool and simply leaves a corner the
    tool's own radius.
    """
    Rc, xw, rn = R + c, NOTCH_HW - c, NOTCH_HW - c
    xfc = xf + c
    # right-hand ear chamfer, offset outward by c
    d = (x_tip - xf, y_tip - y_flat_top)
    L = math.hypot(*d)
    d = (d[0] / L, d[1] / L)
    n = (d[1], -d[0])                       # outward normal (away from the centre)
    q = (xf + c * n[0], y_flat_top + c * n[1])
    t_top = (xfc - q[0]) / d[0]             # meets the offset flat
    flat_top = (xfc, q[1] + t_top * d[1])
    bq, cq = q[0] * d[0] + q[1] * d[1], q[0] ** 2 + q[1] ** 2 - Rc ** 2
    t_tip = -bq + math.sqrt(bq * bq - cq)   # meets the offset outer arc
    tip = (q[0] + t_tip * d[0], q[1] + t_tip * d[1])
    flat_bot = (xfc, -math.sqrt(Rc ** 2 - xfc ** 2))
    shoulder = (xw, math.sqrt(Rc ** 2 - xw ** 2))
    v = [
        (tip[0], tip[1], bulge(ang(*tip), ang(*shoulder), True)),                 # outer arc
        (shoulder[0], shoulder[1], 0),                                            # notch wall
        (xw, NOTCH_YC, bulge(0, math.pi, False)),                                 # notch bottom
        (-xw, NOTCH_YC, 0),                                                       # notch wall
        (-shoulder[0], shoulder[1], bulge(ang(-shoulder[0], shoulder[1]), ang(-tip[0], tip[1]), True)),
        (-tip[0], tip[1], 0),                                                     # L ear chamfer
        (-flat_top[0], flat_top[1], 0),                                           # L flat
        (-flat_bot[0], flat_bot[1], bulge(ang(-flat_bot[0], flat_bot[1]), ang(*flat_bot), True)),
        (flat_bot[0], flat_bot[1], 0),                                            # R flat
        (flat_top[0], flat_top[1], 0),                                            # R ear chamfer
    ]
    assert rn > 0 and shoulder[1] > NOTCH_YC
    return v


def build(out, clearance=0.2):
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # show points as an X
    doc.header["$PDSIZE"] = 0.8   # point marker size, mm
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("RECESS", color=4)
    doc.layers.add("HOLES", color=1)
    doc.layers.add("PLATE_PILOT_CENTRES", color=3)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()

    msp.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in outline], format="xyseb",
                       close=True, dxfattribs={"layer": "OUTLINE"})
    msp.add_lwpolyline(recess_profile(clearance), format="xyb",
                       close=True, dxfattribs={"layer": "RECESS"})
    for c in holes:
        msp.add_circle(c, HOLE_D / 2, dxfattribs={"layer": "HOLES"})
        msp.add_point(c, dxfattribs={"layer": "PLATE_PILOT_CENTRES"})
    msp.add_circle((0, 0), BOSS_D / 2, dxfattribs={"layer": "REFERENCE"})
    msp.add_line((-2, 0), (2, 0), dxfattribs={"layer": "REFERENCE"})
    msp.add_line((0, -2), (0, 2), dxfattribs={"layer": "REFERENCE"})
    doc.saveas(out)


# ---- long backplate, as fitted on the door (measured off a ruler photo) ----
PILOT_NEAR = 65.0    # spindle centre -> nearer backplate screw (fitted ABOVE the spindle)
PILOT_SPACING = 200.0  # backplate screw centre -> centre (202 off the photo drilled ~2 mm long; checked on a test door)


def rotate(v, deg):
    """Rotate (x, y, bulge) vertices about the origin; bulges are unchanged."""
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return [(x * c - y * s, x * s + y * c, b) for x, y, b in v]


def build_door(out, hand, clearance=0.2):
    """Door-face layout: spindle at the origin, backplate vertical (+Y up), viewed
    from the face being machined. LH = hinges on the left, lever points left, so
    the plate's notch (which points away from the lever) points right; RH mirrors it.
    """
    turn = -90.0 if hand == "LH" else 90.0  # plate notch is +Y in plate coordinates
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # same point style as Nido-Dummy-Plate.dxf
    doc.header["$PDSIZE"] = 0.8
    doc.layers.add("RECESS", color=4)
    doc.layers.add("PILOT_CENTRES", color=3)
    doc.layers.add("PLATE_PILOT_CENTRES", color=3)
    doc.layers.add("SPINDLE_CENTRE", color=1)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()
    msp.add_lwpolyline(rotate(recess_profile(clearance), turn), format="xyb",
                       close=True, dxfattribs={"layer": "RECESS"})
    pilots = [(0.0, PILOT_NEAR), (0.0, PILOT_NEAR - PILOT_SPACING)]
    for p in pilots:
        msp.add_point(p, dxfattribs={"layer": "PILOT_CENTRES"})
    plate_pilots = [(round(x, 6) + 0.0, round(y, 6) + 0.0) for x, y, _ in rotate([(hx, hy, 0) for hx, hy in holes], turn)]
    for p in plate_pilots:
        msp.add_point(p, dxfattribs={"layer": "PLATE_PILOT_CENTRES"})
    msp.add_point((0, 0), dxfattribs={"layer": "SPINDLE_CENTRE"})
    msp.add_lwpolyline(rotate(outline, turn), format="xyb", close=True,
                       dxfattribs={"layer": "REFERENCE"})  # true plate outline, not for cutting
    msp.add_line((0, pilots[1][1]), (0, pilots[0][1]), dxfattribs={"layer": "REFERENCE"})
    doc.saveas(out)
    return pilots, plate_pilots


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(Path(__file__).with_suffix(".dxf")))
    ap.add_argument("--clearance", type=float, default=0.2,
                    help="RECESS offset outside the plate outline, mm (default 0.2)")
    args = ap.parse_args()
    out = Path(args.out)
    build(out, args.clearance)
    print(f"wrote {out}  (RECESS clearance {args.clearance} mm)")
    for hand in ("LH", "RH"):
        door = out.with_name(f"Nido-Dummy-Door-{hand}.dxf")
        pts, plate_pts = build_door(door, hand, args.clearance)
        print(f"wrote {door}  backplate pilots {pts}  round-plate pilots {plate_pts}")
    print(f"  shoulder fillet R{RF:.3f}, ear tips (+/-{x_tip:.3f}, {y_tip:.3f}), "
          f"flats y {y_flat_bot:.3f}..{y_flat_top:.3f}")
    for x, y in holes:
        print(f"  hole centre ({x:7.3f}, {y:7.3f})  dia {HOLE_D}")
