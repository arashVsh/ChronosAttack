"""Analyse Experiment G (B3/C1 on Terra-low, Gemini-minimal, Qwen-low) from raw ledgers with the
5 September per-cell analysis (``analyze_completion_study``). Holm over the six new primary tests.
Plan: specs/journal-extension-sep14/round2-g-b3c1-matched-plan-2026-10-08.md."""

import hashlib
import json
from pathlib import Path

import analyze_completion_study as completion
import audit_experiment_g as auditor
import experiment_g_protocol as protocol
from round2_shards import counted_audits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = HERE / "round2_runs_20260920" / "experiment_g_study"
OUT = HERE / "round2_analysis" / "experiment_g_analysis_v1.json"
SHORT = {"openai/gpt-5.6-terra": "terra", "google/gemini-3.6-flash": "gemini",
         "qwen/qwen3-235b-a22b-instruct-2507": "qwen"}


def cell_trials(model):
    trials, sources = {}, []
    for audit_path in counted_audits(RUNS / SHORT[model]):
        ledger = audit_path.parent / (model.replace("/", "_") + ".jsonl")
        checked = auditor.audit([json.loads(l) for l in ledger.read_text().splitlines()], model, require_complete=False)
        for t in checked["trials"]:
            if t["job_id"] in trials:
                raise ValueError("A job completed in two passed shard ledgers")
            trials[t["job_id"]] = t
        sources.append({"path": str(ledger.relative_to(ROOT)), "sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
                        "known_cost_usd": checked["known_cost_usd"], "observed_invocations": checked["observed_invocations"],
                        "failed_calls": checked["failed_calls"]})
    return list(trials.values()), sources


def analyze():
    result = {"schema": "chronos.experiment-g-analysis.v1", "cells": {}, "plan": protocol.__doc__.split("Plan: ")[1].strip()}
    primary = {}
    for model in SHORT:
        trials, sources = cell_trials(model)
        old = completion.protocol.MODELS
        completion.protocol.MODELS = (model,)
        try:
            cells = completion.analyze({"trials": trials, "complete": len(trials) == 420,
                                        "verified_calls": sum(t["calls"] for t in trials), "required_calls": 1050,
                                        "new_measured_cost_usd": sum(s["known_cost_usd"] for s in sources),
                                        "new_calls_with_unknown_cost": 0})["cells"]
        finally:
            completion.protocol.MODELS = old
        for key, cell in cells.items():
            if cell["stateful"]["complete"]:
                primary[key] = cell["stateful"]["exact_mcnemar_p"]
        result["cells"][model] = {"cell": protocol.cell(model), "completed_jobs": len(trials), "planned_jobs": 420,
                                  "known_cost_usd": sum(s["known_cost_usd"] for s in sources),
                                  "sources": sources, "scenarios": cells}
    result["primary_raw_p"] = primary
    result["primary_holm_adjusted_p"] = completion.holm(primary) if len(primary) == 6 else None
    return result


if __name__ == "__main__":
    result = analyze()
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for model, cell in result["cells"].items():
        print(SHORT[model], cell["completed_jobs"], "/ 420 jobs", f"${cell['known_cost_usd']:.4f}")
