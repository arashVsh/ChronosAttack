"""Figures for the final report, from the sealed analysis files. No model calls.
Palette: the dataviz reference instance (blue #2a78d6 attack, orange #eb6834 natural; sequential blue ramp)."""

from itertools import permutations
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "kaggle" / "round2_analysis"
OUT = ROOT / "deliverables" / "final_report" / "figures"
INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
ATTACK, NATURAL = "#2a78d6", "#eb6834"
BLUES = LinearSegmentedColormap.from_list("blues", ["#f0efec", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
CELLS = [("terra_low", "Terra (low)"), ("gemini_minimal", "Gemini (minimal)"), ("qwen_low", "Qwen (low)"),
         ("claude_none", "Claude (off)")]
TOOLS = {"equity_tool": "E", "heat_tool": "H", "survival_tool": "S", "cost_tool": "C"}

plt.rcParams.update({"font.size": 8, "axes.edgecolor": BASE, "axes.labelcolor": INK2, "xtick.color": MUTED,
                     "ytick.color": MUTED, "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 200, "savefig.bbox": "tight", "font.family": "DejaVu Sans"})


def load(name):
    return json.loads((AN / name).read_text())


def order_heatmap():
    cells = load("tree4_cells_v1.json")
    natural = list(TOOLS)
    orders = list(permutations(natural))
    attack = tuple(natural[1:] + natural[:1])
    rates = []
    for key, _ in CELLS:
        panels = cells[key]["panels"]["permutation_stateful"]
        rows = load("analysis.json")["study_models"] if key != "terra_low" else None
        choices = (load("terra_low_study_analysis_v1.json")["study"]["model_order_panel_choices"] if key == "terra_low"
                   else rows[{"gemini_minimal": "google/gemini-3.6-flash", "qwen_low": "qwen/qwen3-235b-a22b-instruct-2507",
                              "claude_none": "anthropic/claude-sonnet-4-6@default"}[key]]["model_order_panel_choices"])
        rates.append([sum(r[i] == "C" for r in choices.values()) / len(choices) for i in range(24)])
        assert panels["complete_panels"] == len(choices) == 10
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    image = ax.imshow(rates, cmap=BLUES, vmin=0, vmax=1, aspect="auto")
    for y, row in enumerate(rates):
        for x, value in enumerate(row):
            ax.text(x, y, f"{round(100 * value)}", ha="center", va="center", fontsize=5.5,
                    color="#ffffff" if value > 0.55 else INK2)
    ax.set_yticks(range(len(CELLS)), [label for _, label in CELLS], color=INK2)
    ax.set_xticks(range(24), ["".join(TOOLS[t] for t in o) for o in orders], rotation=90, fontsize=6, family="monospace")
    for index, order in enumerate(orders):
        if order in (tuple(natural), attack):
            ax.get_xticklabels()[index].set_color(INK)
            ax.get_xticklabels()[index].set_fontweight("bold")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.01)
    bar.set_label("target C rate", color=INK2)
    bar.outline.set_visible(False)
    ax.set_xlabel("arrival order (E equity, H heat, S survival, C cost); bold: natural EHSC and attack HSCE")
    fig.savefig(OUT / "fig_tree_order_heatmap.pdf")
    plt.close(fig)


def dumbbells(panels, name):
    """panels: list of (title, [(label, natural, attack)])."""
    fig, axes = plt.subplots(1, len(panels), figsize=(1.75 * len(panels), 1.9), sharey=True)
    for ax, (title, rows) in zip(axes, panels):
        for y, (label, natural, attack) in enumerate(rows):
            ax.plot([natural, attack], [y, y], color=BASE, lw=2, zorder=1)
            ax.scatter([natural], [y], s=26, color=NATURAL, zorder=2, edgecolor="#fcfcfb", linewidth=1)
            ax.scatter([attack], [y], s=26, color=ATTACK, zorder=3, edgecolor="#fcfcfb", linewidth=1)
        ax.set_title(title, fontsize=8, color=INK)
        ax.set_xlim(-0.05, 1.05)
        ax.set_xticks([0, 0.5, 1], ["0", "50", "100%"])
        ax.grid(axis="x", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_yticks(range(len(panels[0][1])), [label for label, _, _ in panels[0][1]], color=INK2)
    axes[0].invert_yaxis()
    handles = [plt.Line2D([], [], marker="o", ls="", color=NATURAL, label="natural order"),
               plt.Line2D([], [], marker="o", ls="", color=ATTACK, label="attack order")]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.55, 1.2))
    fig.savefig(OUT / name)
    plt.close(fig)


def primary_effects():
    tree = load("tree4_cells_v1.json")
    a = load("experiment_a_analysis_v1.json")
    a_cell = {"terra_low": a["matched_non_off_primary"]["terra"], "gemini_minimal": a["matched_non_off_primary"]["gemini"],
              "qwen_low": a["matched_non_off_primary"]["qwen"], "claude_none": a["claude_none_sensitivity"]}
    panels = []
    g_path = AN / "experiment_g_analysis_v1.json"
    if g_path.exists():
        g = load("experiment_g_analysis_v1.json")["cells"]
        sept = json.loads((ROOT / "kaggle" / "completion_results" / "analysis.json").read_text())["cells"]
        model = {"terra_low": "openai/gpt-5.6-terra", "gemini_minimal": "google/gemini-3.6-flash",
                 "qwen_low": "qwen/qwen3-235b-a22b-instruct-2507", "claude_none": "anthropic/claude-sonnet-4-6@default"}
        if all(g[model[k]]["completed_jobs"] == 420 for k, _ in CELLS[:3]):
            for sid, title in (("b3", "B3 release"), ("c1", "C1 microgrid")):
                rows = []
                for key, label in CELLS:
                    c = (sept if key == "claude_none" else g[model[key]]["scenarios"])[f"{model[key]}|{sid}"]["stateful"]
                    rows.append((label, c["natural"]["rate"], c["attack"]["rate"]))
                panels.append((title, rows))
    panels.append(("Tree", [(label, tree[k]["stateful_primary"]["natural_target_rate"],
                             tree[k]["stateful_primary"]["attacked_target_rate"]) for k, label in CELLS]))
    panels.append(("Water (A)", [(label, a_cell[k]["primary_pairs"]["stateful"]["natural_target_rate"],
                                  a_cell[k]["primary_pairs"]["stateful"]["attacked_target_rate"]) for k, label in CELLS]))
    dumbbells(panels, "fig_primary_effects.pdf")


def worst_case():
    c = load("experiment_c_collection_report_qwen_s29_provider429_snapshot_v1.json")
    cells = {**c["matched_non_off_primary"], "anthropic/claude-sonnet-4-6@default": c["claude_none_sensitivity"]}
    model = {"terra_low": "openai/gpt-5.6-terra", "gemini_minimal": "google/gemini-3.6-flash",
             "qwen_low": "qwen/qwen3-235b-a22b-instruct-2507", "claude_none": "anthropic/claude-sonnet-4-6@default"}
    rows = [(label, cells[model[k]]["analysis"]["arms"]["undefended_natural"]["target_C_rate_all_decisions"],
             cells[model[k]]["analysis"]["arms"]["undefended_selected_order"]["target_C_rate_all_decisions"]) for k, label in CELLS]
    tree = load("tree4_cells_v1.json")
    fixed = [(label, tree[k]["stateful_primary"]["natural_target_rate"], tree[k]["stateful_primary"]["attacked_target_rate"])
             for k, label in CELLS]
    dumbbells([("Fixed attack (tree)", fixed), ("Worst-case order (C)", rows)], "fig_fixed_vs_worst.pdf")


def position_effects():
    tree = load("tree4_cells_v1.json")
    names = {"equity_tool": "Equity", "heat_tool": "Heat", "survival_tool": "Survival", "cost_tool": "Cost"}
    fig, axes = plt.subplots(1, 4, figsize=(7.0, 1.9), sharey=True)
    for ax, (tool, title) in zip(axes, names.items()):
        values = [100 * tree[k]["position_effects"][tool]["C"]["last_minus_first"] for k, _ in CELLS]
        ax.barh(range(len(CELLS)), values, color=[ATTACK if v >= 0 else NATURAL for v in values], height=0.55)
        for y, v in enumerate(values):
            ax.text(v + (4 if v >= 0 else -4), y, f"{v:+.0f}", va="center", ha="left" if v >= 0 else "right",
                    fontsize=6.5, color=INK2)
        ax.axvline(0, color=BASE, lw=0.8)
        ax.set_xlim(-125, 125)
        ax.set_xticks([-100, 0, 100], ["$-$100", "0", "+100"])
        ax.set_title(f"{title} arrives last", fontsize=8, color=INK)
        ax.grid(axis="x", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
    axes[0].set_yticks(range(len(CELLS)), [label for _, label in CELLS], color=INK2)
    axes[0].invert_yaxis()
    fig.supxlabel("target-C rate when last minus when first (pp)", fontsize=7, color=INK2, y=-0.08)
    fig.savefig(OUT / "fig_position_effects.pdf")
    plt.close(fig)


def revisions():
    tree = load("tree4_cells_v1.json")
    colors = ["#2a78d6", "#eb6834", "#1f9e77", "#8a5cc2"]
    steps = ["2", "3", "4", "5"]
    fig, ax = plt.subplots(figsize=(3.6, 2.1))
    for (key, label), color in zip(CELLS, colors):
        t = tree[key]["transitions"]
        values = [t["revisions_by_step"].get(s, 0) / t["trials"] for s in steps]
        ax.plot(range(4), values, marker="o", ms=3.5, lw=1.4, color=color, label=label)
    ax.set_xticks(range(4), ["after obs. 2", "after obs. 3", "after obs. 4", "final"])
    ax.set_ylabel("revisions per trial")
    ax.set_ylim(0, 1)
    ax.grid(axis="y", color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    fig.savefig(OUT / "fig_revisions.pdf")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    order_heatmap()
    primary_effects()
    worst_case()
    position_effects()
    revisions()
    print(sorted(p.name for p in OUT.iterdir()))
