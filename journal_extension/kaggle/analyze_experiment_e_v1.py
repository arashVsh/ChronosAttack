"""Experiment E (paraphrase) analysis from raw shard ledgers. Exploratory, no hypothesis tests.

For each model: every raw shard ledger is re-audited with ``audit_experiment_e`` (all 180
jobs complete), and the target rate under natural and attack order is reported for each
wording, with the paired attack-minus-natural change (pairs share a repetition index).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import audit_experiment_e as auditor
import experiment_e_protocol as protocol

HERE = Path(__file__).resolve().parent
RUNS = HERE / "round2_runs_20260920/experiment_e_study"
OUTPUT = HERE / "round2_analysis/experiment_e_analysis_v1.json"
SHORT = {"openai/gpt-5.6-terra": "terra", "google/gemini-3.6-flash": "gemini",
         "qwen/qwen3-235b-a22b-instruct-2507": "qwen", "anthropic/claude-sonnet-4-6@default": "claude"}


def _ledgers(model: str) -> list[Path]:
    """One ledger per shard: the run whose hosted audit passed (failed runs stay pinned, excluded)."""
    name = model.replace("/", "_") + ".jsonl"
    by_shard = {}
    for path in sorted((RUNS / SHORT[model]).rglob(name)):
        if json.loads((path.parent / "audit.json").read_text()).get("passed") is not True:
            continue
        shard = path.parent.name.split("_s")[-1][:2]
        if shard in by_shard:
            raise ValueError(f"{model}: two passed runs for shard {shard}")
        by_shard[shard] = path
    return [by_shard[key] for key in sorted(by_shard)]


def cell(model: str) -> dict:
    paths = _ledgers(model)
    events = [json.loads(line) for path in paths for line in path.read_bytes().splitlines()]
    complete = len(paths) == 30
    checked = auditor.audit(events, model, "study", require_complete=complete)
    target = protocol.SEMANTIC_TARGET
    wordings = {}
    for wording in protocol.ROTATIONS:
        picks = {(d["condition"], d["rep"]): d["semantic_choice"] for d in checked["decisions"]
                 if d["rotation"] == wording}
        # A partial cell keeps only repetitions with both a natural and an attack decision.
        reps = [r for r in range(1, protocol.REPETITIONS + 1) if ("natural", r) in picks and ("attack", r) in picks]
        natural = [picks[("natural", r)] == target for r in reps]
        attack = [picks[("attack", r)] == target for r in reps]
        wordings[f"w{wording}"] = {
            "pairs": len(natural),
            "natural_target_rate": sum(natural) / len(natural),
            "attack_target_rate": sum(attack) / len(attack),
            "attack_minus_natural": (sum(attack) - sum(natural)) / len(natural),
            "gains": sum(a and not n for a, n in zip(attack, natural)),
            "losses": sum(n and not a for a, n in zip(attack, natural)),
            "natural_choices": {c: sum(picks[("natural", r)] == c for r in reps) for c in "ABC"},
            "attack_choices": {c: sum(picks[("attack", r)] == c for r in reps) for c in "ABC"},
        }
    effects = [w["attack_minus_natural"] for w in wordings.values()]
    return {"model": model, "reasoning": protocol.cell(model)["reasoning"], "role": protocol.cell(model)["role"],
            "status": "complete" if complete else "partial", "passed_shards": len(paths),
            "completed_jobs": checked["completed_jobs"], "observed_invocations": checked["observed_invocations"],
            "failed_calls": checked["failed_calls"], "known_cost_usd": checked["known_cost_usd"],
            "unknown_cost_calls": checked["unknown_cost_calls"], "wordings": wordings,
            "effect_range_across_wordings": max(effects) - min(effects),
            "raw_ledgers": [{"path": str(p.relative_to(HERE.parent)),
                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}


GENERATED = HERE / "round2_generated"
LANE_NOTE = "specs/journal-extension-sep14/round2-e-parallel-lanes-note-2026-10-04.md"
# Successful test calls in the lane period whose result (and cost) was not saved: the save step
# was added at about 19:30 UTC (lane note). Busy test calls are refused and not charged.
UNRECORDED_LANE_PROBES = ["claude v5", "claude v6", "claude v7", "qwen v9"]


def _monthly(path: Path) -> tuple[Decimal, str, str]:
    value = json.loads(path.read_text())
    if value.get("no_quota_reading"):  # attempt-start marker of the no-reading Claude lane (lane note)
        return None, value["queried_at_start_utc"], value["queried_at_start_utc"]
    rows = json.loads(value["response_raw"], parse_float=Decimal)["quotaBalances"]
    used = next((r.get("quotaUsed", Decimal(0)) for r in rows if r["refillPeriod"] == "MONTHLY"), Decimal(0))
    return Decimal(used), value["queried_at_start_utc"], value["queried_at_end_utc"]


def accounting() -> dict:
    """Every attempt (passed or not) and every saved test call, with the lane-period meter check."""
    attempts = []
    for model, short in SHORT.items():
        for path in sorted((RUNS / short).rglob(model.replace("/", "_") + ".jsonl")):
            events = [json.loads(line) for line in path.read_bytes().splitlines()]
            calls = [e for e in events if e.get("event") in ("call_complete", "call_failed")]
            tag = path.parent.name.removeprefix("round2_tree4_paraphrase_")
            before = GENERATED / f"experiment_e_quota_before_{tag}_browser_observation_v1.json"
            attempts.append({
                "run": tag, "path": str(path.relative_to(HERE.parent)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "passed": json.loads((path.parent / "audit.json").read_text()).get("passed") is True,
                "completed_jobs": sum(e.get("event") == "job_complete" for e in events),
                "calls": len(calls), "unknown_cost_calls": sum(e.get("cost_usd") is None for e in calls),
                "known_cost_usd": str(sum((Decimal(str(e["cost_usd"])) for e in calls if e.get("cost_usd") is not None), Decimal(0))),
                "quota_before_start_utc": _monthly(before)[1]})
    probes = []
    for path in sorted((GENERATED / "experiment_e_probe_results").glob("*.json")):
        value = json.loads(path.read_text())
        probes.append({"probe": path.stem, "ok": value["result"]["ok"], "cost_usd": value["result"].get("cost_usd")})
    lane_start = GENERATED / "experiment_e_quota_lane_start_browser_observation_v1.json"
    lane_end = GENERATED / "experiment_e_quota_lane_end_browser_observation_v1.json"
    lane = None
    if lane_end.exists():
        (start_used, start_time, _), (end_used, _, _) = _monthly(lane_start), _monthly(lane_end)
        in_lane = [a for a in attempts if a["quota_before_start_utc"] > start_time]
        shard_cost = sum((Decimal(a["known_cost_usd"]) for a in in_lane), Decimal(0))
        probe_cost = sum((Decimal(str(p["cost_usd"])) for p in probes if p["ok"] and p["cost_usd"] is not None), Decimal(0))
        delta = end_used - start_used
        lane = {"note": LANE_NOTE, "monthly_delta_usd": str(delta), "attempts": len(in_lane),
                "attempt_known_cost_usd": str(shard_cost), "recorded_probe_cost_usd": str(probe_cost),
                "unrecorded_successful_probes": UNRECORDED_LANE_PROBES,
                "residual_usd": str(delta - shard_cost - probe_cost),
                "unknown_cost_calls": sum(a["unknown_cost_calls"] for a in in_lane)}
    return {"attempts": attempts, "probes": probes, "lane_period_meter_check": lane,
            "total_known_cost_usd": str(sum((Decimal(a["known_cost_usd"]) for a in attempts), Decimal(0))
                                        + sum((Decimal(str(p["cost_usd"])) for p in probes if p["cost_usd"] is not None), Decimal(0)))}


def build() -> dict:
    body = {"schema": "chronos.experiment-e-analysis.v1", "classification": "exploratory_descriptive",
            "question": "Does the order effect hold when the prompt and observation wording changes?",
            "manifest_sha256": json.loads((HERE / "experiment_e_manifest_v1.json").read_text())["manifest_sha256"],
            "cells": [cell(model) for model in protocol.CELLS], "accounting": accounting()}
    return {**body, "analysis_sha256": hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = build()
    if args.verify:
        if json.loads(OUTPUT.read_text()) != result:
            raise SystemExit("E analysis differs from fresh regeneration")
    else:
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["analysis_sha256"])
    for c in result["cells"]:
        print(c["model"].split("/")[-1][:14], {k: (round(v["natural_target_rate"], 2), round(v["attack_target_rate"], 2))
                                              for k, v in c["wordings"].items()}, round(c["known_cost_usd"], 4))


if __name__ == "__main__":
    main()
