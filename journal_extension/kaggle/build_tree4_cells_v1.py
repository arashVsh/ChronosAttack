"""All five four-observation (tree) study cells for the final report: Terra-low, Gemini-minimal,
Qwen-low, Claude-none, and the historical Terra-none. Runs the same audited functions as the
round-two analysis and keeps the full per-cell report (stateless, controls, barrier, panels),
which ``round2_analysis`` computes but does not store. No model calls."""

import json
from pathlib import Path

import analyze_terra_low_study_v1 as terra_low
import round2_analysis as r2

HERE = Path(__file__).resolve().parent
OUT = HERE / "round2_analysis" / "tree4_cells_v1.json"
NAMES = {"terra_low": "openai/gpt-5.6-terra", "gemini_minimal": "google/gemini-3.6-flash",
         "qwen_low": "qwen/qwen3-235b-a22b-instruct-2507", "claude_none": "anthropic/claude-sonnet-4-6@default",
         "terra_none": "openai/gpt-5.6-terra"}


def _capture(run):
    """Run ``run`` and return (its result, the report that analysis.analyze produced inside it)."""
    original, captured = r2.analysis.analyze, {}

    def wrapper(*args, **kwargs):
        captured["report"] = original(*args, **kwargs)
        return captured["report"]

    r2.analysis.analyze = wrapper
    try:
        return run(), captured["report"]
    finally:
        r2.analysis.analyze = original


def _transitions(records):
    """Counts of provisional-choice changes (e.g. "A>B") and of revisions at each step, stateful panel trials."""
    changes, steps = {}, {}
    for row in records:
        for step, (a, b) in enumerate(zip(row["choices"], row["choices"][1:]), 2):
            if a != b:
                changes[f"{a}>{b}"] = changes.get(f"{a}>{b}", 0) + 1
                steps[str(step)] = steps.get(str(step), 0) + 1
    return {"trials": len(records), "change_counts": dict(sorted(changes.items())),
            "revisions_by_step": dict(sorted(steps.items()))}


def _slim(report):
    return {"cells": report["cells"], "primary_pairs": report["primary_pairs"],
            "transitions": _transitions(report["revision_records"]["permutation_stateful"]),
            "panels": {mode: {k: v for k, v in panel.items() if k not in ("position_associations",)}
                       for mode, panel in report["panels"].items()}}


def build():
    manifest = json.loads(r2.MANIFEST_PATH.read_text())
    split = manifest["held_out_order"]
    by_model = {cell["model"]: cell for cell in r2.STUDY_CELLS}
    result = {}
    for key, model in NAMES.items():
        if key == "terra_low":
            verified = terra_low.collection_verifier.verify()
            _, events, _ = terra_low._ledger_events("terra_study_collection_v1.json")
            engine = r2.protocol.engine
            old_id, engine.STUDY_ID = engine.STUDY_ID, events[0]["job_id"].split("|")[0]
            try:
                study, report = _capture(lambda: terra_low._with_events(
                    events, verified, r2._audited_study,
                    {"model": model, "reasoning": "low", "path": HERE / "round2_generated" / "terra_study_collection_v1.json"},
                    split))
            finally:
                engine.STUDY_ID = old_id
        else:
            cell = by_model[model]
            if key.endswith("none") != (cell["reasoning"] == "none"):
                raise ValueError("Unexpected historical reasoning setting")
            study, report = _capture(lambda: r2._audited_study(cell, split))
        result[key] = {"model": model, "reasoning": study["reasoning"], **_slim(report),
                       **{k: study[k] for k in ("stateful_primary", "inversion", "held_out_order", "trajectory",
                                                "position_effects", "provenance")},
                       "known_cost_usd": study["audit"]["known_cost_usd"]}
    return result


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    for key, cell in data.items():
        p, panel = cell["primary_pairs"], cell["panels"]["permutation_stateful"]
        print(key, cell["reasoning"], "stateful", p["stateful"]["target_rate_change"], p["stateful"]["exact_p_raw"],
              "stateless", p["stateless"]["target_rate_change"], f"{panel['order_information_bits']:.2f}b")
