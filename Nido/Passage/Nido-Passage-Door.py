"""Windsor Nido 8427 Verge Longplate Passage Set -> door-face DXF.

Usage:
    pip install ezdxf
    python Nido-Passage-Door.py [output.dxf]

Door-face layout, units mm, spindle centre at the origin, longplate vertical (+Y up).
Same longplate as the 8423 dummy set: fixings 65 above and 135 below the spindle
(200 c-c, proven on a test door with the dummy set).

All holes sit on the vertical centreline and go through the door (split spindle
through the latch, bolt-through fixings joining the two plates), so the same file
works for left- and right-hand doors.

Layers (all POINT entities, which SCM Maestro imports):
    SPINDLE_CENTRE   spindle / latch follower through-hole
    FIXING_CENTRES   the two bolt-through fixing holes
    REFERENCE        centreline between the fixings, not for cutting
"""
import sys
from pathlib import Path

import ezdxf

FIX_ABOVE = 65.0     # spindle centre -> top fixing
FIX_SPACING = 200.0  # top fixing -> bottom fixing, centre to centre


def build(out):
    doc = ezdxf.new("R2000", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$PDMODE"] = 3     # same point style as the dummy files
    doc.header["$PDSIZE"] = 0.8
    doc.layers.add("SPINDLE_CENTRE", color=1)
    doc.layers.add("FIXING_CENTRES", color=3)
    doc.layers.add("REFERENCE", color=8, linetype="DASHED")
    msp = doc.modelspace()
    fixings = [(0.0, FIX_ABOVE), (0.0, FIX_ABOVE - FIX_SPACING)]
    msp.add_point((0.0, 0.0), dxfattribs={"layer": "SPINDLE_CENTRE"})
    for p in fixings:
        msp.add_point(p, dxfattribs={"layer": "FIXING_CENTRES"})
    msp.add_line(fixings[1], fixings[0], dxfattribs={"layer": "REFERENCE"})
    doc.saveas(out)
    return fixings


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_suffix(".dxf")
    fixings = build(out)
    print(f"wrote {out}: spindle (0, 0), fixings {fixings}")
