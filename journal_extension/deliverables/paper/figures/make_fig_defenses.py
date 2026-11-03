"""Fig. 4: target rate under each model's natural order, the adaptive attacker's order, and that order with each defense.
Values transcribed from deliverables/final_report/tables/t_c.tex (Experiment C)."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "fig_defenses.pdf"
models = ["GPT-5.6 Terra", "Gemini 3.6", "Qwen3", "Claude 4.6"]
arms = ["Natural order", "Attacker's order", "Barrier", "Randomized", "Order vote", "Order-invariant"]
rates = np.array([
    [0, 60, 0, 0, 0, 3],
    [37, 100, 60, 10, 0, 3],
    [0, 97, 0, 40, 70, 0],
    [90, 83, 0, 67, 0, 63],
])
colors = ["#9e9e9e", "#b2182b", "#4393c3", "#4393c3", "#4393c3", "#1b7837"]
plt.rcParams.update({
    "font.size": 8.5,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
    "axes.edgecolor": "#444444",
    "axes.linewidth": 0.7,
})
fig, axes = plt.subplots(2, 2, figsize=(3.5, 3.6), sharex=True, sharey=True)
y = np.arange(len(arms))[::-1]
for ax, model, row in zip(axes.flat, models, rates):
    ax.grid(axis="x", color="#e6e6e6", linewidth=0.5, zorder=0)
    ax.axvline(row[0], color="#666666", linestyle="--", linewidth=0.8, zorder=2)
    ax.barh(y, row, color=colors, height=0.62, zorder=3)
    for yy, v in zip(y, row):
        ax.text(
            v + 3.5, yy, f"{v}", va="center", ha="left", fontsize=8, color="#111111", zorder=4,
            bbox=dict(boxstyle="square,pad=0.06", facecolor="white", edgecolor="none", alpha=0.85),
        )
    ax.set_title(model, fontsize=9, fontweight="bold", pad=5)
    ax.set_xlim(0, 128)
    ax.set_ylim(-0.6, len(arms) - 0.4)
    ax.set_xticks([0, 50, 100])
    ax.tick_params(axis="x", labelsize=8, length=2.5, color="#444444")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
axes[0, 0].set_yticks(y)
axes[0, 0].set_yticklabels(arms, fontsize=8)
fig.subplots_adjust(left=0.31, right=0.98, top=0.92, bottom=0.14, wspace=0.22, hspace=0.34)
fig.text(0.645, 0.02, "Target rate (%)", ha="center", va="bottom", fontsize=9)
fig.savefig(OUT, bbox_inches="tight", pad_inches=0.02)


