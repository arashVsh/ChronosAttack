"""Render deterministic round-two reports from a fresh raw-evidence analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from round2_analysis import HERE, build_round2_analysis


PROJECT = HERE.parent
SPECS = PROJECT / "specs/journal-extension-sep14"
ANALYSIS_DESTINATION = HERE / "round2_analysis/analysis.json"
MODEL_ORDER = (
    "openai/gpt-5.6-terra",
    "anthropic/claude-sonnet-4-6@default",
    "google/gemini-3.6-flash",
    "qwen/qwen3-235b-a22b-instruct-2507",
)
MODEL_LABELS = {
    "openai/gpt-5.6-terra": "Terra",
    "anthropic/claude-sonnet-4-6@default": "Claude",
    "google/gemini-3.6-flash": "Gemini",
    "qwen/qwen3-235b-a22b-instruct-2507": "Qwen",
}
TOOL_ORDER = ("equity_tool", "heat_tool", "survival_tool", "cost_tool")
TOOL_LABELS = {tool: tool.removesuffix("_tool") for tool in TOOL_ORDER}
ARM_ORDER = (
    "undefended_natural",
    "undefended_attack",
    "randomized",
    "invariant",
)
ARM_LABELS = {
    "undefended_natural": "undefended natural",
    "undefended_attack": "undefended attacked",
    "randomized": "randomized ordering",
    "invariant": "order-invariant synthesis",
}


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _pp(value: float) -> str:
    return f"{value * 100:+.1f}pp"


def _p_value(value: float | None) -> str:
    if value is None:
        return "—"
    if value < 0.001:
        return f"{value:.2e}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _interval(values: list[float]) -> str:
    return f"[{values[0] * 100:.1f}, {values[1] * 100:.1f}]"


def _order(order: list[str]) -> str:
    return " → ".join(TOOL_LABELS[tool] for tool in order)


def _choices(counts: dict[str, int]) -> str:
    return ", ".join(f"{choice}×{counts[choice]}" for choice in sorted(counts))


def _generated_note() -> str:
    return (
        "Generated deterministically by `kaggle/render_round2_reports.py` from "
        "the pinned raw JSONL files. Do not hand-edit numeric results.\n"
    )


def _provenance(studies: dict) -> str:
    lines = [
        "## Raw-evidence provenance",
        "",
        "| model | reasoning | raw SHA-256 |",
        "| --- | --- | --- |",
    ]
    for model in MODEL_ORDER:
        cell = studies[model]
        lines.append(
            f"| {MODEL_LABELS[model]} | `{cell['reasoning']}` | "
            f"`{cell['provenance']['sha256']}` |"
        )
    return "\n".join(lines)


def render_inversion(result: dict) -> str:
    studies = result["study_models"]
    lines = [
        "# Inversion-count ablation: distance is not a sufficient attack model",
        "",
        _generated_note().rstrip(),
        "",
        "The prespecified `budget` arm contains 15 trials at each inversion distance",
        "from 0 through 6. These are descriptive target-C rates; the cross-distance",
        "interpretation is exploratory.",
        "",
        "## Target-choice rate by inversion distance",
        "",
        "| model | inv0 | inv1 | inv2 | inv3 | inv4 | inv5 | inv6 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_ORDER:
        rates = studies[model]["inversion"]["target_rates_by_distance"]
        lines.append(
            f"| {MODEL_LABELS[model]} | "
            + " | ".join(_percent(rates[str(distance)]) for distance in range(7))
            + " |"
        )
    lines.extend(
        [
            "",
            "Terra, Claude and Gemini are non-monotonic. Qwen is different: it is at",
            "0% for distances 0–3 and 100% for distances 4–6. Qwen therefore rules",
            "out the old claim that inversion distance carries almost no information",
            "in every model. The defensible four-model conclusion is narrower:",
            "distance is not a sufficient description of a schedule's effect.",
            "",
            "## Equal-distance counterexample",
            "",
            "The fixed attacked order and the lexicographically frozen budget order are",
            "both distance 3 from natural order, but they are different permutations.",
            "",
            "| model | fixed attack | frozen distance-3 order | gap |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for model in MODEL_ORDER:
        inversion = studies[model]["inversion"]
        lines.append(
            f"| {MODEL_LABELS[model]} | "
            f"{_percent(inversion['fixed_attack_target_rate'])} | "
            f"{_percent(inversion['equal_distance_budget_target_rate'])} | "
            f"{_pp(inversion['equal_distance_gap'])} |"
        )
    lines.extend(
        [
            "",
            "All four models have a nonzero equal-distance gap; for Qwen it is 100pp.",
            "The identity of the permutation matters beyond its inversion count.",
            "",
            "## Scope",
            "",
            "This result does not estimate a delay-magnitude effect. The implementation",
            "shows the model only the delivered order; simulated arrival times never enter",
            "the prompt. The threat model uses delay as a means of inducing an order, while",
            "this experiment estimates order effects only.",
            "",
            _provenance(studies),
            "",
        ]
    )
    return "\n".join(lines)


def render_position(result: dict) -> str:
    studies = result["study_models"]
    lines = [
        "# Which observation matters: model-specific position effects",
        "",
        _generated_note().rstrip(),
        "",
        "The complete stateful permutation panels contain ten repetitions of all 24",
        "orders. Each tool therefore appears first and last 60 times per model. Rates",
        "below are target-C choice; intervals resample complete 24-order panels and are",
        "pointwise exploratory intervals.",
        "",
        "| model | tool | first | last | last − first | panel bootstrap 95% |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_ORDER:
        effects = studies[model]["position_effects"]
        for tool in TOOL_ORDER:
            cell = effects[tool]["C"]
            lines.append(
                f"| {MODEL_LABELS[model]} | {TOOL_LABELS[tool]} | "
                f"{_percent(cell['rates_by_position'][0])} | "
                f"{_percent(cell['rates_by_position'][3])} | "
                f"{_pp(cell['last_minus_first'])} | "
                f"{_interval(cell['panel_bootstrap_95'])} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Position effects are large but heterogeneous. Claude and Gemini show large",
            "negative heat effects and positive cost effects. Qwen reverses the simple",
            "cost-last account: equity changes from 0% first to 100% last, while cost",
            "changes from 83.3% first to 5.0% last. No single recency rule or tool-level",
            "mechanism generalizes across all four endpoints.",
            "",
            "The stable conclusion is that tool identity and position interact. This",
            "complements the equal-distance result: two schedules can be equally displaced",
            "while assigning very different positions to the observations that matter for a",
            "particular model. It is a behavioral pattern, not evidence of an internal",
            "cognitive mechanism.",
            "",
            _provenance(studies),
            "",
        ]
    )
    return "\n".join(lines)


def render_trajectory(result: dict) -> str:
    studies = result["study_models"]
    modes = (
        ("stateful", "stateful natural/attack pairs"),
        ("permutation_stateful", "24-order panels"),
    )
    lines = [
        "# Decision trajectories: persistence and revision",
        "",
        _generated_note().rstrip(),
        "",
        "This analysis reuses provisional choices already recorded in stateful trials.",
        "It describes decision persistence and revision; it does not identify an internal",
        "anchoring mechanism.",
        "",
        "## Revision behavior",
        "",
        "| model | arm | trials | mean revisions | final = first | never revised | returned to first | synthesis changed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_ORDER:
        trajectory = studies[model]["trajectory"]
        for mode, label in modes:
            cell = trajectory[mode]
            lines.append(
                f"| {MODEL_LABELS[model]} | {label} | {cell['trials']} | "
                f"{cell['mean_revisions']:.2f} | {_percent(cell['final_equals_first'])} | "
                f"{_percent(cell['never_revised'])} | "
                f"{_percent(cell['returned_to_first'])} | "
                f"{_percent(cell['final_synthesis_changed'])} |"
            )
    lines.extend(
        [
            "",
            "## First departure from the initial choice in the 24-order panels",
            "",
            "| model | step 2 | step 3 | step 4 | step 5 | never departed |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for model in MODEL_ORDER:
        cell = studies[model]["trajectory"]["permutation_stateful"]
        counts = cell["first_departure_step_counts"]
        departed = sum(counts.get(str(step), 0) for step in range(2, 6))
        never = cell["trials"] - departed
        lines.append(
            f"| {MODEL_LABELS[model]} | "
            + " | ".join(str(counts.get(str(step), 0)) for step in range(2, 6))
            + f" | {never} |"
        )
    lines.extend(
        [
            "",
            "Revision remains front-loaded across all four models. Qwen strengthens that",
            "description—every panel trial departs by step 2 or 3—but it also revises more",
            "often overall (2.19 transitions per panel trial). Final synthesis changes are",
            "rare rather than universally absent: 0% for Terra and Gemini, 6.7% for Claude",
            "and 4.6% for Qwen in the permutation panels.",
            "",
            "These records locate when observable choices change. They do not show why the",
            "model changed or justify claims about hidden reasoning state.",
            "",
            _provenance(studies),
            "",
        ]
    )
    return "\n".join(lines)


def render_order_analysis(result: dict) -> str:
    studies = result["study_models"]
    regression = result["model_by_order_regression"]
    lines = [
        "# Held-out order selection and model-by-order regression",
        "",
        _generated_note().rstrip(),
        "",
        "## Frozen split-half analysis",
        "",
        "Seed `20260920` produced selection repetitions 3, 4, 5, 7 and 10;",
        "evaluation repetitions are 1, 2, 6, 8 and 9. The selected order maximizes",
        "target-C rate in the selection half, with the lowest numeric condition as the",
        "tie-break. Selection rows never enter evaluation.",
        "",
        "| model | selected condition and order | selection C | tied maxima | held-out natural | held-out selected | change | gains/losses | exact p |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_ORDER:
        held = studies[model]["held_out_order"]
        evaluation = held["evaluation"]
        paired = evaluation["paired"]
        lines.append(
            f"| {MODEL_LABELS[model]} | {held['selected_condition']}: "
            f"{_order(held['selected_order'])} | "
            f"{held['selection']['target_successes']}/5 | "
            f"{held['selection']['tie_count']} | "
            f"{sum(c == 'C' for c in evaluation['natural_choices'])}/5 | "
            f"{sum(c == 'C' for c in evaluation['selected_choices'])}/5 | "
            f"{_pp(paired['target_rate_change'])} | "
            f"{paired['gains']}/{paired['losses']} | "
            f"{_p_value(paired['exact_p_raw'])} |"
        )
    lines.extend(
        [
            "",
            "These five-pair evaluations are descriptive. Even five gains and no losses",
            "give a minimum two-sided exact p of 0.0625, observed for Qwen. The split",
            "protects evaluation from order selection but does not create high power.",
            "",
            "## Separation-resistant global model-by-order analysis",
            "",
            f"The raw 4×24 grid has {regression['raw_boundary_cells']} of "
            f"{regression['raw_total_cells']} cells at 0% or 100%, so ordinary logistic",
            "MLE/Wald inference is unsuitable. The frozen analysis uses Firth logistic",
            "regression for `model * categorical_order`. The full interaction fit has",
            f"{regression['full_interaction']['parameter_count']} parameters; the additive",
            f"fit has {regression['additive']['parameter_count']}. The single exploratory",
            "global penalized likelihood-ratio assessment is",
            f"χ²({regression['global_interaction']['degrees_of_freedom']}) = "
            f"{regression['global_interaction']['statistic']:.2f}, "
            f"p = {_p_value(regression['global_interaction']['p_value'])}.",
            "",
            "The global comparison uses the full-model Jeffreys penalty under both the",
            "interaction and additive fits. Its chi-square reference is exploratory and",
            "not calibrated for this sparse finite sample.",
            "",
            "Predictions below are separation-resistant cell probabilities with empirical",
            "95% panel-resampling stability intervals from 2,000 resamples of complete",
            "24-order panels within model. Repetition IDs are balanced-panel bookkeeping,",
            "not subject or temporal identities. Boundary cells can have zero-width",
            "intervals because a nonparametric bootstrap cannot generate an outcome absent",
            "from all ten observed panels; these are not calibrated probability confidence",
            "intervals.",
            "",
            "| order | Terra | Claude | Gemini | Qwen |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for order in regression["orders"]:
        cells = []
        for model in MODEL_ORDER:
            cell = regression["predicted_cell_probabilities"][model][str(order)]
            cells.append(
                f"{_percent(cell['estimate'])} {_interval(cell['panel_bootstrap_95'])}"
            )
        lines.append(f"| {order} | " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "The global p-value is an uncalibrated asymptotic exploratory assessment. The",
            "cell probabilities and empirical stability intervals are the primary",
            "regression outputs; no",
            "catalogue of interaction-coefficient Wald p-values is reported.",
            "",
            _provenance(studies),
            "",
        ]
    )
    return "\n".join(lines)


def render_cross_scenario(result: dict) -> str:
    completion = result["completion_scenarios"]
    studies = result["study_models"]
    rows = []
    for model in MODEL_ORDER[:2]:
        for scenario in ("b3", "c1"):
            cell = completion["cells"][f"{model}|{scenario}"]
            rows.append((model, scenario.upper(), 3, cell))
        rows.append((model, "tree4", 4, studies[model]["stateful_primary"]))
    for model in MODEL_ORDER[2:]:
        rows.append((model, "tree4", 4, studies[model]["stateful_primary"]))

    lines = [
        "# Cross-scenario analysis: baseline rate does not determine steerability",
        "",
        _generated_note().rstrip(),
        "",
        "This comparison is exploratory. Each cell followed its own frozen protocol, but",
        "the cross-scenario synthesis was defined after the outcomes were known. B3 and C1",
        "use three observations; tree4 uses four. C1 transfers a similar numerical tradeoff",
        "geometry to another domain and is not the independent second scenario planned for",
        "round two.",
        "",
        "## All eight completed stateful cells",
        "",
        "| model | scenario | observations | natural | attacked | change | exact p |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, scenario, observations, cell in rows:
        lines.append(
            f"| {MODEL_LABELS[model]} | {scenario} | {observations} | "
            f"{_percent(cell['natural_target_rate'])} | "
            f"{_percent(cell['attacked_target_rate'])} | "
            f"{_pp(cell['target_rate_change'])} | "
            f"{_p_value(cell['exact_p_raw'])} |"
        )
    lines.extend(
        [
            "",
            "## What survives the falsification",
            "",
            "The seven-cell analysis originally proposed target-rate headroom as the",
            "explanation: significant cells had mid-range natural baselines, while Terra",
            "floored and Claude ceilinged on tree4. Qwen is the direct counterexample. It",
            "has a 0% natural target rate, exactly like Terra, yet the same fixed order moves",
            "it to 100%. Baseline position therefore does not determine steerability.",
            "",
            "Model identity alone does not determine steerability either. Terra and Claude",
            "show large positive changes in B3 and C1 but little or negative change in",
            "tree4. The result is an interaction among endpoint, scenario and exact order,",
            "not a stable ranking of model robustness. Baseline rate still constrains the",
            "numerical range a target-rate difference can take, but it is not a mechanism",
            "or sufficient predictor.",
            "",
            "The position and inversion analyses provide descriptive localization, not a",
            "replacement mechanism claim: schedules at the same inversion distance can",
            "differ by 100pp, and tool-position effects differ sharply by model. The new",
            "independent scenario is needed to test transfer without reusing this geometry.",
            "",
            "## Provenance",
            "",
            f"The B3/C1 matrix is regenerated from historical confirmation batches plus "
            f"three pinned JSONL ledgers and verifies {completion['verified_calls']:,}/"
            f"{completion['required_calls']:,} planned calls. It does not read "
            "`completion_results/analysis.json`. Tree4 provenance is listed below.",
            "",
            _provenance(studies),
            "",
        ]
    )
    return "\n".join(lines)


def render_defense(result: dict) -> str:
    defenses = result["defense_models"]
    lines = [
        "# Defense suite results: efficacy, utility, calls, cost and latency",
        "",
        _generated_note().rstrip(),
        "",
        "The historical suite contains 30 contemporaneous decisions in each of four",
        "arms per model. Utility is total-variation distance from that run's undefended",
        "natural choice distribution; this fixture has no objective correctness key.",
        "",
        "## Outcomes",
        "",
        "| model | arm | choices | target rate | change vs attacked | TV from natural | raw p | Holm p | coverage | abstention |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for model in MODEL_ORDER:
        suite = defenses[model]
        for arm_name in ARM_ORDER:
            arm = suite["arms"][arm_name]
            raw = suite["defended_pair_family"]["raw"].get(arm_name)
            holm = suite["defended_pair_family"]["holm"].get(arm_name)
            lines.append(
                f"| {MODEL_LABELS[model]} | {ARM_LABELS[arm_name]} | "
                f"{_choices(arm['choice_counts'])} | {_percent(arm['target_rate'])} | "
                f"{_pp(arm['target_rate_change_vs_attacked'])} | "
                f"{arm['utility_tv_from_natural']:.3f} | {_p_value(raw)} | "
                f"{_p_value(holm)} | {arm['completed_decisions']}/"
                f"{arm['planned_decisions']} | 0 recorded; schema permits A/B/C only |"
            )
    lines.extend(
        [
            "",
            "Randomized and invariant efficacy is interpretable for Gemini and Qwen, where",
            "the contemporaneous attack moves target rate by 60pp and 100pp. Terra has a",
            "floor and almost no attack effect; Claude has a high natural target baseline,",
            "so lower target rate there is disagreement with normal behavior, not clean",
            "security benefit. Qwen invariant synthesis removes the full attack and exactly",
            "matches its natural distribution (TV 0.000). Gemini invariant synthesis also",
            "removes target steering but changes the natural distribution (TV 0.300).",
            "",
            "Zero recorded abstention is structural for these arms: the response schema",
            "does not permit abstention. It is not evidence of voluntary non-abstention.",
            "",
            "## Provider invocations, charged cost and inference latency",
            "",
            "Planned calls come from completed manifests. Observed invocations count both",
            "successful and failed provider calls. Cost likewise includes every known-cost",
            "`call_complete` and `call_failed` event. Elapsed and backend columns are means",
            "of per-decision sums; simulated arrival delay and unlogged retry/backoff waits",
            "are excluded.",
            "",
            "| model | arm | planned calls | observed invocations | failed | charged cost | cost/decision | elapsed/decision | backend/decision |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for model in MODEL_ORDER:
        suite = defenses[model]
        for arm_name in ARM_ORDER:
            arm = suite["arms"][arm_name]
            lines.append(
                f"| {MODEL_LABELS[model]} | {ARM_LABELS[arm_name]} | "
                f"{arm['planned_calls']} | {arm['observed_invocations']} | "
                f"{arm['failed_invocations']} | ${arm['known_cost_usd']:.8f} | "
                f"${arm['cost_per_completed_decision_usd']:.5f} | "
                f"{arm['elapsed_seconds_per_decision_mean']:.2f}s | "
                f"{arm['backend_seconds_per_decision_mean']:.2f}s |"
            )
    lines.extend(
        [
            "",
            "Claude's attacked arm has 160 observed invocations for 150 planned calls:",
            "three charged failed calls plus successful retries. Those failures cost",
            "$0.01964430. Including them corrects Claude's suite to $2.63612160 and the",
            f"four-suite defense total to ${result['costs']['defense_known_cost_usd']:.8f}.",
            f"Known study-plus-defense spend is ${result['costs']['overall_known_cost_usd']:.8f};",
            "Claude's historical study also contains three explicitly reported unknown-cost",
            "provider failures, so this is a known-cost total rather than proof that no other",
            "charge existed.",
            "",
            "Barrier and 24-order consistency results belong to a different study manifest",
            "with different decision and call counts, so they are not merged into this",
            "contemporaneous four-arm table. The round-two worst-case stress test will collect",
            "all six frozen arms against fresh baselines under one explicit design.",
            "",
            "## Raw-evidence provenance",
            "",
            "| model | reasoning | raw SHA-256 |",
            "| --- | --- | --- |",
        ]
    )
    for model in MODEL_ORDER:
        suite = defenses[model]
        lines.append(
            f"| {MODEL_LABELS[model]} | `{suite['reasoning']}` | "
            f"`{suite['provenance']['sha256']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def render_reports(result: dict) -> dict[Path, str]:
    return {
        SPECS / "inversion-ablation.md": render_inversion(result),
        SPECS / "which-tool-ablation.md": render_position(result),
        SPECS / "trajectory-analysis.md": render_trajectory(result),
        SPECS / "order-analysis.md": render_order_analysis(result),
        SPECS / "cross-scenario-finding.md": render_cross_scenario(result),
        SPECS / "defense-results.md": render_defense(result),
    }


def _encoded_analysis(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def check_outputs(result: dict) -> list[str]:
    expected = {ANALYSIS_DESTINATION: _encoded_analysis(result), **render_reports(result)}
    mismatches = []
    for path, content in expected.items():
        if not path.exists():
            mismatches.append(f"missing: {path.relative_to(PROJECT)}")
        elif path.read_text() != content:
            mismatches.append(f"drifted: {path.relative_to(PROJECT)}")
    return mismatches


def write_outputs(result: dict) -> None:
    ANALYSIS_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_DESTINATION.write_text(_encoded_analysis(result))
    for path, content in render_reports(result).items():
        path.write_text(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build_round2_analysis()
    if args.write:
        write_outputs(result)
        print("wrote round-two analysis and six deterministic reports")
        return
    mismatches = check_outputs(result)
    if mismatches:
        raise SystemExit("\n".join(mismatches))
    print("round-two analysis and reports match fresh raw-evidence regeneration")


if __name__ == "__main__":
    main()
