"""Render DXF files from this repo to a PNG preview, one panel per file.

pip install ezdxf matplotlib numpy
python tools/preview.py out.png "Panel title" file1.dxf ["Panel title" file2.dxf ...] [--title TEXT]

Lines/arcs/circles are drawn per layer (REFERENCE dashed grey); POINTs are drawn
as crosses labelled with their coordinates.
"""
import argparse

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from ezdxf import path  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

PALETTE = ["tab:blue", "tab:green", "tab:red", "tab:purple", "tab:orange", "tab:brown",
           "tab:pink", "tab:olive", "tab:cyan"]


def draw(ax, dxf, title, colours):
    ms = ezdxf.readfile(dxf).modelspace()
    pts = []
    for e in ms:
        layer = e.dxf.layer
        if layer != "REFERENCE" and layer not in colours:
            colours[layer] = PALETTE[len(colours) % len(PALETTE)]
        if e.dxftype() == "POINT":
            x, y = e.dxf.location.x, e.dxf.location.y
            ax.plot(x, y, "x", color=colours[layer], ms=8, mew=2, zorder=3)
            pts.append((x, y))
            ax.annotate(f"({x:g}, {y:g})", (x, y), xytext=(6, 4), textcoords="offset points",
                        fontsize=7.5)
        else:
            p = np.array([(v.x, v.y) for v in path.make_path(e).flattening(0.01)])
            ref = layer == "REFERENCE"
            ax.plot(p[:, 0], p[:, 1], color="grey" if ref else colours[layer],
                    lw=0.8 if ref else 1.5, ls="--" if ref else "-")
            pts.extend(p.tolist())
    P = np.array(pts)
    lo, hi = P.min(0), P.max(0)
    pad = max(8.0, 0.08 * float(np.max(hi - lo)))
    ax.set_xlim(lo[0] - pad - 12, hi[0] + pad + 12)
    ax.set_ylim(lo[1] - pad, hi[1] + pad)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.set_title(title, fontsize=9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("panels", nargs="+", help="title1 file1.dxf [title2 file2.dxf ...]")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    pairs = list(zip(a.panels[::2], a.panels[1::2]))
    fig, axs = plt.subplots(1, len(pairs), figsize=(3.6 * len(pairs) + 0.5, 8))
    axs = np.atleast_1d(axs)
    colours = {}
    for ax, (title, f) in zip(axs, pairs):
        draw(ax, f, title, colours)
    handles = [Line2D([], [], color=c, lw=2, label=l) for l, c in colours.items()]
    handles.append(Line2D([], [], color="grey", ls="--", label="REFERENCE (not for cutting)"))
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=8, frameon=False)
    if a.title:
        fig.suptitle(a.title, fontsize=11)
    fig.tight_layout(rect=(0, 0.08, 1, 0.97 if a.title else 1))
    fig.savefig(a.out, dpi=130)


if __name__ == "__main__":
    main()
