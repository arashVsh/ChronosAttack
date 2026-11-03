"""Generate Fig. 3 (fig_tree_order_heatmap.pdf) for the IEEE paper."""
from itertools import permutations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[3]
AN = ROOT / "kaggle" / "round2_analysis"
OUT = Path(__file__).resolve().parent

INK, INK2, MUTED = "#111111", "#333333", "#666666"
BLUES = LinearSegmentedColormap.from_list(
    "blues", ["#f4f3f0", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
)
CELLS = [
    ("terra_low", "GPT-5.6 Terra"),
    ("gemini_minimal", "Gemini 3.6"),
    ("qwen_low", "Qwen3"),
    ("claude_none", "Claude 4.6"),
]
TOOLS = {"equity_tool": "E", "heat_tool": "H", "survival_tool": "S", "cost_tool": "C"}

plt.rcParams.update({
    "font.size": 8.5,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
    "text.color": INK,
    "axes.labelcolor": INK,
    "xtick.color": INK2,
    "ytick.color": INK,
})


def load(name):
    return json.loads((AN / name).read_text())


def main():
    cells = load("tree4_cells_v1.json")
    natural = list(TOOLS)
    orders = list(permutations(natural))
    attack = tuple(natural[1:] + natural[:1])
    rates = []
    for key, _ in CELLS:
        panels = cells[key]["panels"]["permutation_stateful"]
        rows = load("analysis.json")["study_models"] if key != "terra_low" else None
        choices = (
            load("terra_low_study_analysis_v1.json")["study"]["model_order_panel_choices"]
            if key == "terra_low"
            else rows[
                {
                    "gemini_minimal": "google/gemini-3.6-flash",
                    "qwen_low": "qwen/qwen3-235b-a22b-instruct-2507",
                    "claude_none": "anthropic/claude-sonnet-4-6@default",
                }[key]
            ]["model_order_panel_choices"]
        )
        rates.append([sum(r[i] == "C" for r in choices.values()) / len(choices) for i in range(24)])
        assert panels["complete_panels"] == len(choices) == 10

    fig, ax = plt.subplots(figsize=(7.1, 1.85))
    image = ax.imshow(rates, cmap=BLUES, vmin=0, vmax=1, aspect="auto")
    for y, row in enumerate(rates):
        for x, value in enumerate(row):
            ax.text(
                x, y, f"{round(100 * value)}",
                ha="center", va="center", fontsize=7,
                color="#ffffff" if value > 0.52 else INK2,
            )
    ax.set_yticks(range(len(CELLS)), [label for _, label in CELLS], fontsize=8.5)
    ax.set_xticks(
        range(24),
        ["".join(TOOLS[t] for t in o) for o in orders],
        rotation=90, fontsize=7.5, family="monospace",
    )
    for index, order in enumerate(orders):
        if order in (tuple(natural), attack):
            ax.get_xticklabels()[index].set_color(INK)
            ax.get_xticklabels()[index].set_fontweight("bold")
    ax.tick_params(length=0, pad=3)
    for spine in ax.spines.values():
        spine.set_visible(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.022, pad=0.015, ticks=[0, 0.25, 0.5, 0.75, 1.0])
    bar.ax.set_yticklabels(["0", "25", "50", "75", "100"], fontsize=7.5)
    bar.set_label("Target rate (%)", fontsize=8.5, labelpad=4)
    bar.outline.set_visible(False)
    ax.set_xlabel(
        "Completion order (E: equity, H: heat, S: survival, C: cost; bold: natural EHSC and fixed attack HSCE)",
        fontsize=8.5, labelpad=5,
    )
    fig.savefig(OUT / "fig_tree_order_heatmap.pdf", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


if __name__ == "__main__":
    main()
