"""Model x order Firth regression on the matched roster (Terra low, Gemini minimal, Qwen low, Claude off).

round2_analysis fits the same frozen regression on the September cells, where Terra ran with reasoning off.
This refit swaps in the Terra-low panels so the regression uses the roster of every other table.
No model calls; same target, bootstrap size and seed as the frozen manifest."""

import json
from pathlib import Path

import round2_analysis as r2
from round2_regression import model_order_regression

HERE = Path(__file__).resolve().parent
AN = HERE / "round2_analysis"
OUT = AN / "regression_matched_roster_v1.json"
TERRA = "openai/gpt-5.6-terra"


def build():
    september = json.loads((AN / "analysis.json").read_text())["study_models"]
    panels = {model: study["model_order_panel_choices"] for model, study in september.items() if model != TERRA}
    panels[TERRA] = json.loads((AN / "terra_low_study_analysis_v1.json").read_text())["study"]["model_order_panel_choices"]
    panels = {model: {int(rep): choices for rep, choices in reps.items()} for model, reps in panels.items()}
    seed = json.loads(r2.MANIFEST_PATH.read_text())["regression"]["seed"]
    result = model_order_regression(panels, target=r2.protocol.fixtures()["tree4"]["target"],
                                    bootstrap_repetitions=2000, seed=seed)
    result["roster"] = {TERRA: "low", **{m: september[m]["reasoning"] for m in panels if m != TERRA}}
    return result


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    g = data["global_interaction"]
    print(data["roster"], f"chi2({g['degrees_of_freedom']}) = {g['statistic']:.1f}, p = {g['p_value']:.2g}")
