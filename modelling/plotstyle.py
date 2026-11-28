"""plotstyle.py - one look for every figure (reference palette of the dataviz method, light mode, static PNG).

AI disclosure: drafted with Claude (Anthropic) on 25 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

import settings as S

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf",
       "#1c5cab", "#184f95", "#104281", "#0d366b"]
BLUES = LinearSegmentedColormap.from_list("seq_blue", SEQ)
DIVERGE = LinearSegmentedColormap.from_list("div", ["#184f95", "#5598e7", "#f0efec", "#ec7a7a", "#b52f2f"])

# colour follows the model, never its rank (fixed for every figure)
MODEL_COLOR = {"RF": SLOT[0], "Lasso": SLOT[1], "B2": INK2, "B1": MUTED, "B2p": SLOT[2]}
MODEL_LABEL = {"RF": "M2 random forest", "Lasso": "M1 lasso", "B2": "B2 last observation",
               "B1": "B1 time-of-week rate", "B2p": "band persistence (reference)"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.labelcolor": INK2, "text.color": INK, "axes.edgecolor": AXIS,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    "legend.frameon": False, "legend.fontsize": 9, "figure.dpi": 110, "savefig.dpi": 150,
    "savefig.bbox": "tight",
})


def save(fig, name: str) -> None:
    p = S.FIGS / name
    fig.savefig(p)
    plt.close(fig)
    print(f"figure {p.relative_to(S.ROOT)}")


def hour_ticks(ax, slots: bool = True, every: int = 2) -> None:
    """x axis in 15-min slots (24 = 06:00) labelled by the hour."""
    ticks = list(range(24, 89, 4 * every)) if slots else list(range(6, 23, every))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{(t // 4 if slots else t):02d}:00" for t in ticks])
