"""Write every table of the final report (deliverables/final_report/tables/*.tex) from the sealed
analysis files and raw records. No model calls; rerun after any input changes. A table is written
only when its inputs are complete, so a blank cell can never reach the report."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K = ROOT / "kaggle"
AN = K / "round2_analysis"
OUT = ROOT / "deliverables" / "final_report" / "tables"

TERRA, GEMINI, QWEN, CLAUDE = ("openai/gpt-5.6-terra", "google/gemini-3.6-flash",
                               "qwen/qwen3-235b-a22b-instruct-2507", "anthropic/claude-sonnet-4-6@default")
MAIN = [("terra_low", TERRA, "Terra (low)"), ("gemini_minimal", GEMINI, "Gemini (minimal)"),
        ("qwen_low", QWEN, "Qwen (low)"), ("claude_none", CLAUDE, "Claude (off)")]
SENS = ("terra_none", TERRA, "Terra (off)\\textsuperscript{s}")
SHORT = {TERRA: "terra", GEMINI: "gemini", QWEN: "qwen", CLAUDE: "claude"}


def load(path):
    return json.loads(Path(path).read_text())


def pct(x):
    return f"{100 * x:.0f}\\%"


def frac(k, n):
    return f"{k}/{n}"


def pp(x):
    value = round(100 * x)
    return f"$-${-value}" if value < 0 else f"+{value}"


def pval(p):
    if p >= 0.01:
        return f"{p:.2g}" if p < 1 else "1"
    if p >= 0.001:
        return f"{p:.3f}"
    exponent = math.floor(math.log10(p))
    return f"${p / 10 ** exponent:.1f}\\times10^{{{exponent}}}$"


def paired_ci(natural, attack, gains, losses, n):
    """95% interval for the paired difference attack - natural (Newcombe 1998, method 10), as "[lo, hi]" in pp."""
    both, z = attack - gains, 1.959964
    if both != natural - losses or min(both, n - both - gains - losses) < 0:
        raise ValueError("inconsistent paired counts")
    neither = n - both - gains - losses

    def wilson(k):
        p, centre = k / n, (k / n + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return p, centre - half, centre + half

    (p1, l1, u1), (p2, l2, u2) = wilson(attack), wilson(natural)
    num = both * neither - gains * losses
    den = math.sqrt((both + gains) * (losses + neither) * (both + losses) * (gains + neither))
    phi = 0.0 if den == 0 else (max(num - n / 2, 0) if num > 0 else num) / den
    lo = p1 - p2 - math.sqrt(max((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2, 0))
    hi = p1 - p2 + math.sqrt(max((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2, 0))
    return f"[{pp(lo)}, {pp(hi)}]"


def holm(pvalues: dict) -> dict:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    adjusted, previous = {}, 0.0
    for rank, (key, p) in enumerate(ordered):
        previous = max(previous, min(1.0, (len(ordered) - rank) * p))
        adjusted[key] = previous
    return adjusted


def table(name, spec, header, rows, note=None):
    for row in rows:
        if any(str(cell).strip() in ("", "None", "nan", "—", "-") for cell in row):
            raise ValueError(f"{name}: blank cell in {row}")
    lines = ["\\begin{adjustbox}{max width=\\linewidth}", f"\\begin{{tabular}}{{@{{}}{spec}@{{}}}}", "\\toprule", " & ".join(header) + " \\\\", "\\midrule"]
    lines += [" & ".join(map(str, row)) + " \\\\" for row in rows]
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{adjustbox}"]
    if note:
        lines += ["", f"\\par\\smallskip{{\\footnotesize {note}\\par}}"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.tex").write_text("\n".join(lines) + "\n")
    return name


def exact_two_sided_binomial(gains, losses):
    n = gains + losses
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(gains, losses) + 1)) / 2 ** n)


def fisher_two_sided(a, b, c, d):
    """Fisher exact test for [[a, b], [c, d]] (two-sided, sum of tables as or less likely)."""
    row1, row2, col1, n = a + b, c + d, a + c, a + b + c + d
    prob = lambda x: math.comb(col1, x) * math.comb(n - col1, row1 - x) / math.comb(n, row1)
    observed = prob(a)
    return min(1.0, sum(prob(x) for x in range(max(0, row1 - (n - col1)), min(row1, col1) + 1)
                        if prob(x) <= observed * (1 + 1e-9)))


# ---------------------------------------------------------------- round zero: Luna, paper scenarios

def luna():
    base = ROOT / "chronos_luna_paper_20260901" / "codex"
    trials = load(base / "confirmation_trials.json")
    budget, barrier = load(base / "budget_trials.json"), load(base / "barrier_trials.json")
    consistency = load(base / "order_consistency_trials.json")
    names = {"cloud_backup": "Cloud backup", "shipping_partner": "Shipping partner"}
    primary, raw = [], {}
    for sid in names:
        hit = lambda mode, cond: [t["choice"] == t["target"] for t in trials
                                  if t["scenario"] == sid and t["mode"] == mode and t["condition"] == cond]
        n, a = hit("stateful", "natural"), hit("stateful", "attack")
        raw[sid] = fisher_two_sided(sum(a), len(a) - sum(a), sum(n), len(n) - sum(n))
        primary.append((sid, n, a, hit("stateless", "natural"), hit("stateless", "attack"),
                        hit("control", "simultaneous") or hit("simultaneous", "simultaneous")))
    adjusted = holm(raw)
    rows = []
    for sid, n, a, sn, sa, ctrl in primary:
        b = [t["choice"] == t["target"] for t in budget if t["scenario"] == sid]
        by_inv = {k: [t["choice"] == t["target"] for t in budget if t["scenario"] == sid and t["inversions"] == k] for k in (0, 1, 2)}
        bar = [t["choice"] == t["target"] for t in barrier if t["scenario"] == sid]
        con = [t for t in consistency if t["scenario"] == sid]
        rows.append([names[sid], f"{frac(sum(n), len(n))} ({pct(sum(n) / len(n))})", f"{frac(sum(a), len(a))} ({pct(sum(a) / len(a))})",
                     pp(sum(a) / len(a) - sum(n) / len(n)), pval(raw[sid]), pval(adjusted[sid]),
                     f"{sum(sn)}$\\to${sum(sa)} /{len(sn)}",
                     "/".join(str(sum(by_inv[k])) for k in (0, 1, 2)) + " /15",
                     frac(sum(bar), len(bar)), f"{sum(c['target_success'] for c in con)}/{len(con)}; {sum(c['abstained'] for c in con)}"])
    return table("t_luna", "lrrrrrrrrr",
                 ["Scenario", "Natural", "Attack", "$\\Delta$ pp", "Fisher $p$", "Holm $p$", "Stateless N$\\to$A",
                  "Inv.\\ 0/1/2", "Barrier", "Consist.; abst."], rows,
                 "GPT-5.6 Luna through Codex CLI, 1 September 2026, the paper's own harness. Target A. "
                 "Stateful: 30 natural and 30 attacked trials (unpaired, Fisher exact); Holm over the two scenarios.")


# ---------------------------------------------------------------- B3 / C1 (5 September + G)

def b3c1_cells():
    """{(cell key, scenario): cell analysis} for the five rows, or None if G is incomplete."""
    sept = load(K / "completion_results" / "analysis.json")["cells"]
    g_path = AN / "experiment_g_analysis_v1.json"
    if not g_path.exists():
        return None
    g = load(g_path)
    cells = {}
    for key, model, _ in MAIN + [SENS]:
        for sid in ("b3", "c1"):
            if key in ("claude_none", "terra_none"):
                cells[(key, sid)] = sept[f"{model}|{sid}"]
            else:
                if g["cells"][model]["completed_jobs"] != 420:
                    return None
                cells[(key, sid)] = g["cells"][model]["scenarios"][f"{model}|{sid}"]
    return cells


def b3c1():
    cells = b3c1_cells()
    if cells is None:
        return None
    names = {"b3": "B3 release (B)", "c1": "C1 microgrid (C)"}
    raw = {k: c["stateful"]["exact_mcnemar_p"] for k, c in cells.items()}
    adjusted = holm(raw)
    rows, controls = [], []
    for key, model, label in MAIN + [SENS]:
        for sid in ("b3", "c1"):
            c = cells[(key, sid)]
            s = c["stateful"]
            rows.append([label, names[sid], f"{s['natural']['target_count']}/30 ({pct(s['natural']['rate'])})",
                         f"{s['attack']['target_count']}/30 ({pct(s['attack']['rate'])})", pp(s["target_rate_difference"]),
                         paired_ci(s["natural"]["target_count"], s["attack"]["target_count"], s["positive_shifts"],
                                   s["reverse_shifts"], 30),
                         f"{s['positive_shifts']}/{s['reverse_shifts']}", pval(raw[(key, sid)]), pval(adjusted[(key, sid)])])
            sl = c["stateless"]
            controls.append([label, names[sid], f"{sl['natural']['target_count']}$\\to${sl['attack']['target_count']} /10",
                             f"{c['simultaneous']['target_count']}/10",
                             "/".join(str(c["budget"][k]["target_count"]) for k in ("0", "1", "2")) + " /15",
                             f"{c['barrier']['target_count']}/15",
                             f"{c['consistency']['votes']['target_count']}/10; {c['consistency']['abstentions']}"])
    note = ("Stateful primary endpoint, 30 paired trials per cell, exact McNemar; Holm over all ten tests in the table. "
            "CI: Newcombe score interval for a paired difference. "
            "Shifts: pairs moving to / away from the target. "
            "\\textsuperscript{s}Sensitivity cell (reasoning off). Claude and Terra (off): 5 September 2026; "
            "Terra (low), Gemini and Qwen: Experiment G, October 2026.")
    table("t_b3c1_primary", "llrrrrrrr", ["Model", "Scenario", "Natural", "Attack", "$\\Delta$ pp", "95\\% CI", "Shifts +/$-$",
                                         "exact $p$", "Holm $p$"], rows, note)
    table("t_b3c1_controls", "llrrrrr", ["Model", "Scenario", "Stateless N$\\to$A", "Simultaneous", "Inv.\\ 0/1/2",
                                          "Barrier", "Consist.\\ votes; abst."], controls,
          "Target counts. Consistency: ten six-order panels; a panel answers when one option has at least 4 of 6 votes.")
    return "b3c1"


# ---------------------------------------------------------------- tree, four observations

def tree_cells():
    return load(AN / "tree4_cells_v1.json")


def tree_primary():
    cells = tree_cells()
    order = MAIN + [SENS]
    raw = {}
    for key, _, _ in order:
        for mode in ("stateful", "stateless"):
            raw[(key, mode)] = cells[key]["primary_pairs"][mode]["exact_p_raw"]
    adjusted = holm(raw)
    rows = []
    for key, _, label in order:
        c = cells[key]
        s, sl = c["primary_pairs"]["stateful"], c["primary_pairs"]["stateless"]
        nat = c["cells"]["stateful|natural"]
        att = c["cells"]["stateful|attack"]
        panel = c["panels"]["permutation_stateful"]
        rows.append([label, f"{round(nat['target_rate'] * nat['n'])}/30 ({pct(nat['target_rate'])})",
                     f"{round(att['target_rate'] * att['n'])}/30 ({pct(att['target_rate'])})", pp(s["target_rate_change"]),
                     paired_ci(round(nat["target_rate"] * 30), round(att["target_rate"] * 30), s["gains"], s["losses"], 30),
                     pval(s["exact_p_raw"]), pval(adjusted[(key, "stateful")]),
                     f"{pp(sl['target_rate_change'])} ({pval(adjusted[(key, 'stateless')])})",
                     f"{panel['order_information_bits']:.2f} ({pval(panel['order_association_p_raw'])})"])
    table("t_tree_primary", "lrrrrrrrr", ["Model", "Natural", "Attack", "$\\Delta$ pp", "95\\% CI", "exact $p$", "Holm $p$",
                                         "Stateless $\\Delta$ (Holm)", "Order info, bits ($p$)"], rows,
          "Tree scenario, target C. Stateful: 30 pairs; stateless: 10 pairs; exact paired tests, Holm over the ten tests. "
          "CI: Newcombe score interval for the paired stateful difference. "
          "Order information: mutual information between arrival order and final choice over ten complete 24-order "
          "stateful panels, with a panel-preserving permutation $p$ (999 shuffles). \\textsuperscript{s}Sensitivity cell.")
    controls = []
    for key, _, label in order:
        c = cells[key]
        sim, bar = c["cells"]["control|simultaneous"], c["cells"]["barrier|canonical"]
        con = c["panels"]["consistency"]
        votes = con["two_thirds_consensus_counts"]
        controls.append([label, f"{round(sim['target_rate'] * sim['n'])}/{sim['n']}", f"{round(bar['target_rate'] * bar['n'])}/{bar['n']}",
                         f"{votes.get('C', 0)}/10", f"{votes.get('ABSTAIN', 0)}/10",
                         f"{con['order_information_bits']:.2f}"])
    table("t_tree_controls", "lrrrrr", ["Model", "Simultaneous", "Barrier", "Consistency target", "Consistency abstain",
                                         "Joint-prompt order info"], controls,
          "Target C counts. Consistency: ten 24-order panels of single joint-prompt decisions; a panel answers when one "
          "option has at least 16 of 24 votes.")
    inv = []
    for key, _, label in order:
        r = cells[key]["inversion"]["target_rates_by_distance"]
        inv.append([label] + [pct(r[str(k)]) for k in range(7)])
    table("t_tree_inversion", "lrrrrrrr", ["Model"] + [f"{k}" for k in range(7)], inv,
          "Target-C rate at each inversion distance from the natural order (15 stateful trials each); the fixed attack has distance 3.")
    held = []
    for key, _, label in order:
        h = cells[key]["held_out_order"]
        e = h["evaluation"]
        held.append([label, "".join(t[0].upper() for t in h["selected_order"]), pct(e["natural_target_rate"]), pct(e["selected_target_rate"]),
                     pp(e["paired"]["target_rate_change"]), f"{e['paired']['gains']}/{e['paired']['losses']}", pval(e["paired"]["exact_p_raw"])])
    table("t_tree_heldout", "lrrrrrr", ["Model", "Selected order", "Held-out natural", "Held-out selected", "$\\Delta$ pp",
                                        "Gains/losses", "exact $p$"], held,
          "Split-half order selection (seed 20260920): the order with the highest target rate on five panel repetitions, "
          "evaluated on the other five (E equity, H heat, S survival, C cost; natural EHSC). Descriptive.")
    pos = []
    tools = ["equity_tool", "heat_tool", "survival_tool", "cost_tool"]
    for key, _, label in order:
        p = cells[key]["position_effects"]
        pos.append([label] + [pp(p[t]["C"]["last_minus_first"]) for t in tools])
    table("t_tree_position", "lrrrr", ["Model", "Equity", "Heat", "Survival", "Cost"], pos,
          "Target-C rate when the tool arrives last minus when it arrives first (pp), over the ten 24-order panels "
          "(60 trials per position).")
    traj = []
    for key, _, label in order:
        t = cells[key]["trajectory"]["permutation_stateful"]
        traj.append([label, pct(t["final_equals_first"]), pct(t["never_revised"]), f"{t['mean_revisions']:.2f}",
                     pct(t["returned_to_first"]), pct(t["final_synthesis_changed"])])
    table("t_tree_trajectory", "lrrrrr", ["Model", "Final = first", "Never revised", "Mean revisions", "Returned to first",
                                          "Final step changed"], traj,
          "Provisional-choice trajectories over the 240 stateful panel trials per model.")
    return "tree"


def tree_defense():
    old = load(AN / "analysis.json")["defense_models"]
    new = load(AN / "terra_low_study_analysis_v1.json")["defense"]
    sources = {"terra_low": new, "gemini_minimal": old[GEMINI], "qwen_low": old[QWEN], "claude_none": old[CLAUDE],
               "terra_none": old[TERRA]}
    raw = {(k, arm): sources[k]["arms"][arm]["paired_vs_attacked"]["exact_p_raw"] for k in sources for arm in ("randomized", "invariant")}
    adjusted = holm(raw)
    rows = []
    for key, _, label in MAIN + [SENS]:
        arms = sources[key]["arms"]
        cell = lambda arm: f"{round(arms[arm]['target_rate'] * 30)}/30"
        rows.append([label, cell("undefended_natural"), cell("undefended_attack"), cell("randomized"), cell("invariant"),
                     f"{pp(arms['invariant']['target_rate_change_vs_attacked'])} ({pval(adjusted[(key, 'invariant')])})",
                     f"{pp(arms['randomized']['target_rate_change_vs_attacked'])} ({pval(adjusted[(key, 'randomized')])})"])
    table("t_tree_defense", "lrrrrrr", ["Model", "Natural", "Attack", "Randomised", "Invariant", "Invariant vs attack (Holm)",
                                        "Randomised vs attack (Holm)"], rows,
          "Defense suite on the tree scenario, 30 trials per arm, target-C counts; every arm answered all 30 trials. "
          "Paired exact tests against the attacked arm; Holm over the ten tests.")
    return "defense"


# ---------------------------------------------------------------- round two: A, B, C, E

def exp_a():
    a = load(AN / "experiment_a_analysis_v1.json")
    key = {TERRA: "terra", GEMINI: "gemini", QWEN: "qwen"}
    holm_a = a["primary_multiplicity"]["adjusted_p"]
    rows, controls = [], []
    for _, model, label in MAIN:
        cell = a["claude_none_sensitivity"] if model == CLAUDE else a["matched_non_off_primary"][key[model]]
        s, sl = cell["primary_pairs"]["stateful"], cell["primary_pairs"]["stateless"]
        panel = cell["stateful_24_order_panel"]
        h = s["exact_p_raw"] if model == CLAUDE else holm_a[f"{key[model]}|stateful"]
        rows.append([label, pct(s["natural_target_rate"]), pct(s["attacked_target_rate"]), pp(s["target_rate_change"]),
                     paired_ci(round(s["natural_target_rate"] * 30), round(s["attacked_target_rate"] * 30), s["gains"],
                               s["losses"], 30),
                     pval(s["exact_p_raw"]), pval(h) + ("\\textsuperscript{r}" if model == CLAUDE else ""),
                     pp(sl["target_rate_change"]), f"{panel['order_information_bits']:.2f} ({pval(panel['order_association_p_raw'])})"])
        inv = cell["inversion"]["distance_levels"]
        controls.append([label, pct(cell["controls"]["simultaneous"]["target_rate"]), pct(cell["controls"]["barrier_canonical"]["target_rate"])]
                        + [pct(inv[str(k)]["target_rate"]) for k in range(7)])
    table("t_a_primary", "lrrrrrrrr", ["Model", "Natural", "Attack", "$\\Delta$ pp", "95\\% CI", "exact $p$", "Holm $p$", "Stateless $\\Delta$",
                                      "Order info, bits ($p$)"], rows,
          "Experiment A, water-supply scenario, target C, 30 stateful and 10 stateless pairs; CI: Newcombe paired "
          "interval. Holm over the frozen "
          "eight-slot family. \\textsuperscript{r}Claude (off) is outside that family; its raw $p$ is shown.")
    table("t_a_controls", "lrrrrrrrrr", ["Model", "Simult.", "Barrier"] + [f"Inv.\\ {k}" for k in range(7)], controls,
          "Experiment A target-C rates: simultaneous control (10), barrier (15), and each inversion distance (15).")
    return "a"


def exp_b():
    b = load(AN / "experiment_b_analysis_v2.json")
    cells = {**b["matched_non_off_primary"], CLAUDE: b["claude_none_sensitivity"]}
    rows = []
    for _, model, label in MAIN:
        r = cells[model]["by_rotation_condition"]
        rows.append([label] + [f"{pct(r[f'rot{k}|natural']['semantic_target_rate'])} $\\to$ {pct(r[f'rot{k}|attack']['semantic_target_rate'])}"
                               for k in range(3)])
    return table("t_b", "lrrr", ["Model", "Labelling 1", "Labelling 2", "Labelling 3"], rows,
                 "Experiment B, label rotation on the tree scenario: semantic-target rate, natural $\\to$ attack, "
                 "30 fresh stateful pairs per labelling. Exploratory.")


def exp_c():
    c = load(AN / "experiment_c_collection_report_qwen_s29_provider429_snapshot_v1.json")
    cells = {**c["matched_non_off_primary"], CLAUDE: c["claude_none_sensitivity"]}
    arms = ["undefended_natural", "undefended_selected_order", "randomized", "barrier", "invariant", "order_consistency_24"]
    rows = []
    for _, model, label in MAIN:
        a = cells[model]["analysis"]["arms"]
        order = " $\\to$ ".join(t.split("_")[0] for t in cells[model]["analysis"]["selected_order"])
        rows.append([label, order] + [pct(a[arm]["target_C_rate_all_decisions"]) +
                                      ("" if a[arm]["coverage"] == 1 else f" ({pct(a[arm]['coverage'])} cov.)") for arm in arms])
    return table("t_c", "llrrrrrr", ["Model", "Worst order", "Natural", "Worst", "Randomised", "Barrier", "Invariant", "24-order vote"],
                 rows, "Experiment C, defenses at each model's worst-case order (selected post hoc from its 24-order panel), "
                 "target-C rate, 30 trials per arm. Coverage shown where a defense abstained.")


def exp_e():
    e = load(AN / "experiment_e_analysis_v1.json")
    by_model = {c["model"]: c for c in e["cells"]}
    rows = []
    for _, model, label in MAIN:
        w = by_model[model]["wordings"]
        rows.append([label] + [f"{pct(w[k]['natural_target_rate'])} $\\to$ {pct(w[k]['attack_target_rate'])}" for k in ("w0", "w1", "w2")])
    return table("t_e", "lrrr", ["Model", "Original wording", "Wording 1", "Wording 2"], rows,
                 "Experiment E, paraphrase on the tree scenario: target-C rate natural $\\to$ attack, 30 stateful pairs per wording.")


# ---------------------------------------------------------------- D and F

def exp_df():
    df = load(AN / "experiment_df_analysis_v1.json")["models"]
    if any(df[m]["three_observations"]["completed_jobs"] != 240 for _, m, _ in MAIN):
        return None
    variants = [("tree3_no_equity", "No equity"), ("tree3_no_heat", "No heat"), ("tree3_no_survival", "No survival"),
                ("tree3_no_cost", "No cost")]
    rows, f_rows = [], []
    for _, model, label in MAIN:
        four = df[model]["four_observations"]
        rows.append([label, "All four (24 orders)", pct(four["natural_order_target_rate"]), pct(four["attack_order_target_rate"]),
                     pct(four["min_order"]["target_rate"]), pct(four["max_order"]["target_rate"]),
                     f"{four['order_information']['bits']:.2f} ({four['order_information']['null_mean_bits']:.2f})",
                     pval(four["order_information"]["p_raw"])])
        threes = []
        for key, name in variants:
            v = df[model]["three_observations"]["variants"][key]
            threes.append(v)
            rows.append([label, name + " (6 orders)", pct(v["natural_order_target_rate"]),
                         pct(v["attack_order_target_rate"]) + ("\\textsuperscript{n}" if key == "tree3_no_equity" else ""),
                         pct(v["min_order"]["target_rate"]), pct(v["max_order"]["target_rate"]),
                         f"{v['order_information']['bits']:.2f} ({v['order_information']['null_mean_bits']:.2f})",
                         pval(v["order_information"]["p_raw"])])
        mean = lambda f: sum(f(v) for v in threes) / len(threes)
        bits = lambda x: f"{x:.2f}".replace("-0.00", "0.00")
        f_rows.append([label, bits(four['order_information']['excess_bits']), bits(mean(lambda v: v['order_information']['excess_bits'])),
                       pct(four["target_rate_range"]), pct(mean(lambda v: v["target_rate_range"])),
                       pct(four["max_order"]["target_rate"]), pct(mean(lambda v: v["max_order"]["target_rate"])),
                       pct(four["target_rate_overall"]), pct(mean(lambda v: v["target_rate_overall"]))])
    table("t_d", "llrrrrrr", ["Model", "Observations", "Natural order", "Attack order", "Min order", "Max order",
                               "Order info (null)", "$p$"], rows,
          "Experiment D, leave one observation out. Target-C rate per order over complete panels of ten repetitions "
          "(four observations: 24 orders, September cells; three observations: 6 orders, October). Order information in bits "
          "with the permutation-null mean in brackets. \\textsuperscript{n}With equity removed the attack order equals the natural order.")
    table("t_f", "lrrrrrrrr", ["Model", "Excess bits 4", "Excess bits 3", "Range 4", "Range 3", "Max 4", "Max 3",
                                "Overall C 4", "Overall C 3"], f_rows,
          "Experiment F, three versus four observations. ``3'' is the mean over the four leave-one-out variants. Excess bits: "
          "order information minus its permutation-null mean. Range: highest minus lowest per-order target rate. "
          "Max: highest per-order target rate (the worst case an attacker can reach by choosing the order).")
    return "df"


def _attempt_costs(study_dir):
    """Known cost and invocations over every downloaded attempt (passed or failed) of a D/F or G study."""
    cost, calls = 0.0, 0
    for audit_path in (K / "round2_runs_20260920" / study_dir).rglob("audit.json"):
        raw = load(audit_path)["raw_accounting"]
        cost += raw["known_cost_usd"]
        calls += raw["observed_invocations"]
    return cost, calls


def costs():
    four = load(AN / "analysis.json")["costs"]
    terra_low = load(K / "round2_generated" / "terra_study_collection_v1.json")["totals"]
    terra_low_def = load(K / "round2_generated" / "terra_defense_collection_v1.json")["totals"]
    a = load(AN / "experiment_a_analysis_v1.json")
    a_cost = sum(c["cost"]["all_attempts_known_usd"] for c in a["matched_non_off_primary"].values()) \
        + a["claude_none_sensitivity"]["cost"]["all_attempts_known_usd"]
    b = load(AN / "experiment_b_analysis_v2.json")["aggregate_accounting"]
    c = load(AN / "experiment_c_collection_report_qwen_s29_provider429_snapshot_v1.json")["aggregate_accounting"]
    e = load(AN / "experiment_e_analysis_v1.json")["accounting"]
    df_cost, df_calls = _attempt_costs("experiment_df_study")
    g_cost, g_calls = _attempt_costs("experiment_g_study")
    money = lambda x: f"\\${float(x):.2f}"
    rows = [
        ["Round zero, Luna (Codex CLI)", "paper scenarios", "320 trials", "subscription, no per-call charge"],
        ["B3/C1, 5 September (Terra and Claude off)", "B3, C1", "2,100 calls", money(load(K / "completion_results" / "analysis.json")["new_measured_cost_usd"])],
        ["Tree study and defenses, September (four cells)", "tree", "2,760 + 480 trials", money(four["overall_known_cost_usd"])],
        ["Tree study and defenses, Terra (low)", "tree", "690 + 120 trials", money(terra_low["known_daily_cost_usd"] + terra_low_def["defense_known_cost_usd"])],
        ["A, water supply", "water", "2,760 trials", money(a_cost)],
        ["B, label rotation", "tree", "720 trials", money(b["all_cost_exact_usd"])],
        ["C, worst-case defenses", "tree", "720 trials", money(c["known_cost_usd_all_attempts_lower_bound"])],
        ["D and F, leave one out", "tree (3 tools)", "960 trials", money(df_cost)],
        ["E, paraphrase", "tree", "720 trials", money(e["total_known_cost_usd"])],
        ["G, B3/C1 on Terra (low), Gemini, Qwen", "B3, C1", "1,260 trials", money(g_cost)],
    ]
    total = sum(float(r[3].replace("\\$", "")) for r in rows[1:])
    rows.append(["Total (Kaggle)", "", "", money(total)])
    rows[-1][1] = rows[-1][2] = "all"
    return table("t_costs", "llrr", ["Experiment", "Scenario", "Size", "Known cost"], rows,
                 "Known Kaggle cost over every attempt, including failed and rerun attempts. A few calls refused by "
                 "the provider carry no recorded price; they are settled from the Kaggle meter in the experiment notes.")


# ---------------------------------------------------------------- original study, matrix, deeper tree analyses

def original_paper():
    o = load(AN / "original_paper_results_v1.json")
    n = o["n"]
    names = {"cloud": "Cloud backup", "shipping": "Shipping partner"}
    main_rows, defense_rows = [], []
    for model in o["models"]:
        for sid in ("cloud", "shipping"):
            c = o["cells"][f"{model}|{sid}"]
            (sn, sa), (ln, la) = c["stateful"], c["stateless"]
            main_rows.append([model, names[sid], f"{sn}/{n['stateful']} ({pct(sn / n['stateful'])})",
                              f"{sa}/{n['stateful']} ({pct(sa / n['stateful'])})", pp((sa - sn) / n["stateful"]),
                              f"{ln}$\\to${la} /{n['stateless']}", f"{c['simultaneous']}/{n['simultaneous']}"])
            defense_rows.append([model, names[sid], "/".join(map(str, c["inversion"])) + f" /{n['inversion']}",
                                 f"{c['barrier']}/{n['barrier']}", f"{c['consistency_target']}/{n['consistency']}"])
    source = "From the preprint (DOI 10.21203/rs.3.rs-10854515/v1), not re-run; target A in both scenarios."
    table("t_orig_primary", "llrrrrr", ["Model", "Scenario", "Natural", "Attack", "$\\Delta$ pp", "Stateless N$\\to$A",
                                        "Simultaneous"], main_rows,
          "Original study, target counts. Stateful: 30 trials per schedule; stateless: 10 per serialisation; "
          "simultaneous control: 10. " + source)
    table("t_orig_controls", "llrrr", ["Model", "Scenario", "Inv.\\ 0/1/2", "Barrier", "Consistency target"], defense_rows,
          "Original study, target counts: 15 stateful trials per inversion level, 15 barrier trials, ten six-order "
          "consistency panels (a panel answers when at least 4 of 6 agree). Abstentions reported in the preprint: "
          "Claude, cloud backup, 10/10 (3--3 splits); Gemini, shipping, 2/10. " + source)
    return "orig"


def coverage_matrix():
    rows = [
        ["B3/C1 matrix", "B3, C1", "30 + 10 pairs, 10 simultaneous, 15 $\\times$ 3 inversion levels, 15 barrier, 10 six-order panels", "420"],
        ["Tree study", "tree", "30 + 10 pairs, 10 simultaneous, 15 $\\times$ 7 inversion distances, 15 barrier, 10 $\\times$ 24 orders stateful and joint", "690"],
        ["Tree defense suite", "tree", "natural, attack, randomised, invariant; 30 each", "120"],
        ["A, water supply", "water", "same as the tree study", "690"],
        ["B, label rotation", "tree", "3 labellings $\\times$ 30 pairs", "180"],
        ["C, worst-case defenses", "tree", "natural, worst order, randomised, barrier, invariant, 24-order vote; 30 each", "180"],
        ["D and F, leave one out", "tree, 3 tools", "4 variants $\\times$ 6 orders $\\times$ 10", "240"],
        ["E, paraphrase", "tree", "3 wordings $\\times$ 30 pairs", "180"],
    ]
    rows = [r + ["4/4"] for r in rows]
    return table("t_matrix", "llp{7.2cm}rr", ["Block", "Scenario", "Arms per model", "Trials per model", "Models complete"], rows,
                 "Balanced matrix: every block ran with the same arms and repetitions on Terra (low), Gemini (minimal), "
                 "Qwen (low) and Claude (off); completeness is checked by each block's auditor against its frozen manifest. "
                 "Terra (off) adds B3/C1, the tree study and its defenses as a sensitivity cell. Claude with reasoning on "
                 "was exempted (cost).")


def tree_sensitivity():
    cells = tree_cells()
    rows, trans = [], []
    for key, _, label in MAIN + [SENS]:
        panel = cells[key]["panels"]["permutation_stateful"]
        within = [x for x in panel["within_order_disagreement"]]
        between = panel["between_order_disagreement_by_panel"]
        rows.append([label, f"{panel['entropy_bits']:.2f}", f"{panel['mean_within_order_entropy_bits']:.2f}",
                     f"{panel['order_information_bits']:.2f}", f"{sum(within) / len(within):.2f}",
                     f"{sum(between) / len(between):.2f}"])
        t = cells[key]["transitions"]
        steps, changes = t["revisions_by_step"], t["change_counts"]
        trans.append([label] + [str(steps.get(k, 0)) for k in ("2", "3", "4", "5")]
                     + [str(changes.get(k, 0)) for k in ("A>B", "A>C", "B>A", "B>C", "C>A", "C>B")])
        if t["trials"] != 240:
            raise ValueError(f"{key}: incomplete trajectory panel")
    table("t_tree_sensitivity", "lrrrrr", ["Model", "Choice entropy", "Within-order entropy", "Order info",
                                           "Within-order disagr.", "Between-order disagr."], rows,
          "Ten complete 24-order stateful panels per model (240 trials). Entropy in bits of the final choice overall and, "
          "on average, within one order; order information is their difference. Disagreement: chance that two answers "
          "differ, for two repetitions of the same order (within) or two orders in the same repetition (between). "
          "Between-order disagreement above within-order disagreement means order, not sampling noise, drives the variation.")
    table("t_tree_transitions", "lrrrrrrrrrr", ["Model", "Obs.\\ 2", "Obs.\\ 3", "Obs.\\ 4", "Final",
                                                "A$\\to$B", "A$\\to$C", "B$\\to$A", "B$\\to$C", "C$\\to$A", "C$\\to$B"], trans,
          "Revisions of the provisional choice in the 240 stateful panel trials per model: number of revisions made "
          "after the 2nd, 3rd and 4th observation and at the final synthesis, and counts of each change.")
    return "sensitivity"


def defense_cost():
    old = load(AN / "analysis.json")["defense_models"]
    sources = {"terra_low": load(AN / "terra_low_study_analysis_v1.json")["defense"], "gemini_minimal": old[GEMINI],
               "qwen_low": old[QWEN], "claude_none": old[CLAUDE], "terra_none": old[TERRA]}
    names = {"undefended_attack": "Attack, undefended", "randomized": "Randomised", "invariant": "Invariant"}
    rows = []
    for key, _, label in MAIN + [SENS]:
        for arm, name in names.items():
            a = sources[key]["arms"][arm]
            rows.append([label, name, pct(a["coverage"]), f"{a['observed_invocations'] / a['completed_decisions']:.1f}",
                         f"{a['elapsed_seconds_per_decision_mean']:.1f}", f"{100 * a['cost_per_completed_decision_usd']:.2f}",
                         f"{a['utility_tv_from_natural']:.2f}"])
    return table("t_defense_cost", "llrrrrr", ["Model", "Arm", "Coverage", "Calls / decision", "Latency (s)",
                                               "Cost (cents)", "TV from natural"], rows,
                 "Practical cost of the tree defense suite, 30 decisions per arm. Calls include retries; latency is the "
                 "mean model time per decision (retry waits excluded); TV: total-variation distance of the choice "
                 "distribution from the undefended natural arm (0 = same choices as without attack). Each arm plans five "
                 "calls per decision; the 24-order vote needs 24 joint calls per decision and the barrier one.")


def cross_scenario():
    o = load(AN / "original_paper_results_v1.json")
    tree, a = tree_cells(), load(AN / "experiment_a_analysis_v1.json")
    cells = b3c1_cells()
    if cells is None:
        return None
    rows = []
    for key, model, label, orig in (("gemini_minimal", GEMINI, "Gemini 3.6 Flash", "Gemini 3.6 Flash"),
                                    ("claude_none", CLAUDE, "Claude Sonnet 4.6", "Claude Sonnet 4.6")):
        row = [label]
        for sid in ("cloud", "shipping"):
            n, k = o["cells"][f"{orig}|{sid}"]["stateful"]
            row.append(f"{pct(n / 30)}$\\to${pct(k / 30)}")
        for sid in ("b3", "c1"):
            st = cells[(key, sid)]["stateful"]
            row.append(f"{pct(st['natural']['rate'])}$\\to${pct(st['attack']['rate'])}")
        sp = tree[key]["stateful_primary"]
        row.append(f"{pct(sp['natural_target_rate'])}$\\to${pct(sp['attacked_target_rate'])}")
        ac = a["claude_none_sensitivity"] if model == CLAUDE else a["matched_non_off_primary"]["gemini"]
        st = ac["primary_pairs"]["stateful"]
        row.append(f"{pct(st['natural_target_rate'])}$\\to${pct(st['attacked_target_rate'])}")
        rows.append(row)
    return table("t_cross", "lrrrrrr", ["Model", "Cloud", "Shipping", "B3", "C1", "Tree", "Water"], rows,
                 "The two models that ran in all six scenarios: stateful target rate, natural $\\to$ fixed attack. Cloud "
                 "and shipping: original study (reasoning setting as published); B3 to water: this extension (Gemini "
                 "minimal, Claude off).")


def main():
    written = [luna(), tree_primary(), tree_defense(), exp_a(), exp_b(), exp_c(), exp_e(), b3c1(), exp_df(), costs(),
               original_paper(), coverage_matrix(), tree_sensitivity(), defense_cost(), cross_scenario()]
    print("written:", [w for w in written if w], "| pending:", [n for n, w in zip(
        ["luna", "tree", "defense", "a", "b", "c", "e", "b3c1", "df", "costs", "orig", "matrix", "sensitivity",
         "defense_cost", "cross"], written) if not w])


if __name__ == "__main__":
    main()
