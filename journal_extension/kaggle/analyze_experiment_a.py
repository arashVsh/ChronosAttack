"""Regenerate the frozen water4 Experiment A analysis from sealed raw ledgers.

Collection verifiers authenticate every downloaded shard before this module
reads its scientific JSONL. The Claude-none invalid tail is scientifically
excluded but retained in the independently verified cost totals.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import importlib
from itertools import permutations
import json
import math
from pathlib import Path
import random
from statistics import mean, median

from scipy.stats import beta

import analyze_four_observation as statistics
import audit_water_supply
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
DEFAULT_OUTPUT = HERE / "round2_analysis/experiment_a_analysis_v1.json"
FIXTURE_MANIFEST = HERE / "experiment_a_manifest_v1.json"
AVAILABILITY_MANIFEST = HERE / "experiment_a_availability_v1.json"

CELLS = (
    {
        "name": "terra",
        "model": "openai/gpt-5.6-terra",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "verifier": "verify_experiment_a_terra_batch10_collection",
        "final_manifest": "experiment_a_terra_batch10_collection_v1.json",
        "batches": tuple(f"experiment_a_terra_batch{i:02d}_collection_v1.json" for i in range(9))
        + ("experiment_a_terra_batch10_collection_v1.json",),
    },
    {
        "name": "gemini",
        "model": "google/gemini-3.6-flash",
        "reasoning": "minimal",
        "role": "matched_non_off_primary",
        "verifier": "verify_experiment_a_gemini_remaining_wave03_collection",
        "final_manifest": "experiment_a_gemini_remaining_wave03_collection_v1.json",
        "batches": tuple(f"experiment_a_gemini_batch{i:02d}_collection_v1.json" for i in range(4))
        + tuple(f"experiment_a_gemini_remaining_wave{i:02d}_collection_v1.json" for i in range(1, 4)),
    },
    {
        "name": "qwen",
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "verifier": "verify_experiment_a_qwen_cell_collection",
        "final_manifest": "experiment_a_qwen_cell_collection_v1.json",
        "batches": tuple(f"experiment_a_qwen_batch{i:02d}_collection_v1.json" for i in range(5)),
    },
    {
        "name": "claude_none",
        "model": "anthropic/claude-sonnet-4-6@default",
        "reasoning": "none",
        "role": "reasoning_off_sensitivity",
        "verifier": "verify_experiment_a_claude_none_batch07_collection",
        "final_manifest": "experiment_a_claude_none_batch07_collection_v1.json",
        "batches": tuple(f"experiment_a_claude_none_batch{i:02d}_collection_v1.json" for i in range(8)),
    },
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _read_pinned_file(record: dict) -> tuple[Path, bytes]:
    if set(record) != {"path", "sha256", "bytes"}:
        raise ValueError("invalid pinned evidence record")
    path = (ROOT / record["path"]).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError("evidence path escapes the repository")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
        raise ValueError(f"pinned evidence changed: {path}")
    return path, raw


@contextmanager
def _cell_runtime(cell: dict, study_id: str):
    engine = protocol.engine
    previous = engine.MODELS, engine.STUDY_ID, engine.CALL_SETTINGS
    engine.MODELS = tuple(dict.fromkeys((*engine.MODELS, cell["model"])))
    engine.STUDY_ID = study_id
    engine.CALL_SETTINGS = {
        "temperature": 1,
        "reasoning": cell["reasoning"],
        "max_completion_tokens": 256,
        "timeout": 30,
    }
    try:
        yield
    finally:
        engine.MODELS, engine.STUDY_ID, engine.CALL_SETTINGS = previous


def _read_cell(cell: dict) -> tuple[list[dict], dict]:
    """Require final recursive seal, then read one final ledger per shard."""
    verifier = importlib.import_module(cell["verifier"])
    verified = verifier.verify()
    if verified["model"] != cell["model"] or verified["reasoning"] != cell["reasoning"]:
        raise ValueError(f"{cell['name']}: final collection has wrong identity")
    if verified.get("remaining_jobs", 0) != 0 or verified.get("jobs", 690) != 690:
        raise ValueError(f"{cell['name']}: final collection is incomplete")

    final_path = GENERATED / cell["final_manifest"]
    final_raw = final_path.read_bytes()
    batches = [json.loads((GENERATED / name).read_text()) for name in cell["batches"]]
    study_ids = {batch["study_id"] for batch in batches}
    if len(study_ids) != 1:
        raise ValueError(f"{cell['name']}: conflicting study IDs")
    study_id = study_ids.pop()
    if any(
        batch["model"] != cell["model"]
        or batch["reasoning"] != cell["reasoning"]
        or batch["role"] != cell["role"]
        for batch in batches
    ):
        raise ValueError(f"{cell['name']}: batch role or model changed")

    shard_records = [shard for batch in batches for shard in batch["shards"]]
    if sorted(shard["shard_index"] for shard in shard_records) != list(range(30)):
        raise ValueError(f"{cell['name']}: shards are not exactly 0--29")
    events = []
    raw_records = []
    for shard in sorted(shard_records, key=lambda item: item["shard_index"]):
        path, raw = _read_pinned_file(shard["artifacts"]["evidence"])
        if not raw.endswith(b"\n"):
            raise ValueError(f"{path}: unterminated JSONL")
        shard_events = [json.loads(line) for line in raw.splitlines()]
        events.extend(shard_events)
        raw_records.append(shard["artifacts"]["evidence"])

    with _cell_runtime(cell, study_id):
        expected = protocol.jobs_for(cell["model"], "study")
        checked = audit_water_supply.audit(events, cell["model"], "study")
    completed = [event for event in events if event["event"] == "job_complete"]
    ids = [event["job"]["id"] for event in completed]
    if (
        len(expected) != 690
        or sum(job["calls"] for job in expected) != 2310
        or len(ids) != 690
        or len(set(ids)) != 690
        or set(ids) != {job["id"] for job in expected}
        or checked["completed_jobs"] != 690
        or checked["complete_trial_calls"] != 2310
        or checked["unknown_cost_calls"] != 0
    ):
        raise ValueError(f"{cell['name']}: incomplete or duplicated raw cell")

    scientific_cost = math.fsum(
        event["cost_usd"]
        for event in events
        if event["event"] in ("call_complete", "call_failed")
    )
    tail_records = []
    for batch in batches:
        totals = batch["totals"]
        tail_fields = {key for key in totals if "excluded" in key and "tail" in key}
        if not tail_fields:
            continue
        counts = [
            totals[key]
            for key in (
                "excluded_incomplete_tail_invocations",
                "excluded_tail_observed_invocations",
            )
            if key in totals
        ]
        if (
            "excluded_tail_known_cost_usd" not in totals
            or not counts
            or len(set(counts)) != 1
            or counts[0] <= 0
        ):
            raise ValueError(f"{cell['name']}: unaccounted excluded tail")
        tail_records.append({
            "batch": batch["batch"],
            "invocations": counts[0],
            "known_cost_usd": totals["excluded_tail_known_cost_usd"],
        })
    excluded_tail_cost = math.fsum(record["known_cost_usd"] for record in tail_records)
    excluded_tail_calls = sum(record["invocations"] for record in tail_records)
    manifest_cost = math.fsum(batch["totals"]["batch_known_cost_usd"] for batch in batches)
    if not math.isclose(
        scientific_cost + excluded_tail_cost, manifest_cost, rel_tol=0, abs_tol=1e-9
    ):
        raise ValueError(f"{cell['name']}: verified batch cost differs from raw calls")
    if cell["name"] == "claude_none":
        if len(tail_records) != 3:
            raise ValueError("Claude excluded-tail batch count changed")
        if not math.isclose(excluded_tail_cost, 0.0509334, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Claude invalid tail cost changed")
        if excluded_tail_calls != 13:
            raise ValueError("Claude invalid tail invocation count changed")
    elif excluded_tail_cost or excluded_tail_calls:
        raise ValueError(f"{cell['name']}: unexpected excluded cost")

    call_events = [event for event in events if event["event"] in ("call_complete", "call_failed")]
    evidence = {
        "study_id": study_id,
        "reasoning": cell["reasoning"],
        "role": cell["role"],
        "audit": checked,
        "final_collection_manifest": {
            "path": str(final_path.relative_to(ROOT)),
            "sha256": _sha256(final_raw),
            "bytes": len(final_raw),
        },
        "raw_ledgers": raw_records,
        "cost": {
            "scientific_ledger_known_usd": round(scientific_cost, 12),
            "excluded_invalid_tail_known_usd": round(excluded_tail_cost, 12),
            "all_attempts_known_usd": round(manifest_cost, 12),
            "scientific_ledger_invocations": len(call_events),
            "excluded_invalid_tail_invocations": excluded_tail_calls,
            "excluded_invalid_tails_by_batch": tail_records,
            "all_attempts_invocations": len(call_events) + excluded_tail_calls,
            "failed_invocations": sum(event["event"] == "call_failed" for event in call_events),
        },
    }
    return events, evidence


def _choice_counts(trials: list[dict]) -> dict[str, int]:
    counts = Counter(trial["final"]["final_choice"] for trial in trials)
    return {choice: counts[choice] for choice in ("A", "B", "C")}


def _cell_rates(trials: list[dict], target: str) -> dict:
    grouped = defaultdict(list)
    for trial in trials:
        grouped[(trial["job"]["mode"], trial["job"]["condition"])].append(trial)
    result = {}
    for (mode, condition), rows in sorted(grouped.items()):
        counts = _choice_counts(rows)
        result[f"{mode}|{condition}"] = {
            "n": len(rows),
            "choice_counts": counts,
            "target_rate": counts[target] / len(rows),
            "target_rate_wilson_95": statistics.wilson(counts[target], len(rows)),
        }
    return result


def _primary_pairs(trials: list[dict], target: str) -> dict:
    pairs = {}
    for mode, repetitions in (("stateful", 30), ("stateless", 10)):
        by_condition = {}
        for condition in ("natural", "attack"):
            rows = [
                trial for trial in trials
                if trial["job"]["mode"] == mode
                and trial["job"]["condition"] == condition
            ]
            mapped = {trial["job"]["rep"]: trial["final"]["final_choice"] == target for trial in rows}
            if len(rows) != repetitions or set(mapped) != set(range(1, repetitions + 1)):
                raise ValueError(f"{mode}|{condition}: missing or duplicate pairs")
            by_condition[condition] = mapped
        natural = [by_condition["natural"][rep] for rep in range(1, repetitions + 1)]
        attack = [by_condition["attack"][rep] for rep in range(1, repetitions + 1)]
        paired = statistics.paired_test(natural, attack)
        pairs[mode] = {
            "natural_target_rate": sum(natural) / repetitions,
            "attacked_target_rate": sum(attack) / repetitions,
            **paired,
            "supplementary_exact_bonferroni_95": _bonferroni_exact_paired_interval(
                paired["gains"], paired["losses"], repetitions
            ),
        }
    return pairs


def _bonferroni_exact_paired_interval(gains: int, losses: int, pairs: int) -> list[float]:
    """Conservative effect interval for multinomial gain minus loss probability.

    Each of four marginal binomial tails has error at most .0125. A union
    bound gives simultaneous coverage of at least .95, including at boundaries.
    This supplements, rather than replaces, the historical bootstrap interval.
    """
    if not 0 <= gains <= pairs or not 0 <= losses <= pairs or gains + losses > pairs:
        raise ValueError("invalid paired discordance counts")
    alpha = 0.0125

    def lower(successes: int) -> float:
        return float(beta.ppf(alpha, successes, pairs - successes + 1)) if successes else 0.0

    def upper(successes: int) -> float:
        return float(beta.ppf(1 - alpha, successes + 1, pairs - successes)) if successes < pairs else 1.0

    return [
        max(-1.0, lower(gains) - upper(losses)),
        min(1.0, upper(gains) - lower(losses)),
    ]


def _order_panel(trials: list[dict], target: str, mode: str = "permutation_stateful") -> dict:
    if mode not in ("permutation_stateful", "consistency"):
        raise ValueError("unsupported order-panel mode")
    panel = defaultdict(dict)
    orders = {}
    for trial in trials:
        job = trial["job"]
        if job["mode"] != mode:
            continue
        rep, condition = job["rep"], int(job["condition"])
        if condition in panel[rep]:
            raise ValueError("duplicate permutation cell")
        panel[rep][condition] = trial
        old = orders.setdefault(condition, job["order"])
        if old != job["order"]:
            raise ValueError("permutation order changed across repetitions")
    if set(panel) != set(range(1, 11)) or set(orders) != set(range(24)):
        raise ValueError("permutation panels are incomplete")
    if any(set(row) != set(range(24)) for row in panel.values()):
        raise ValueError("permutation panel has a missing order")
    matrix = [
        [panel[rep][condition]["final"]["final_choice"] for condition in range(24)]
        for rep in range(1, 11)
    ]
    marginal = statistics.entropy([choice for row in matrix for choice in row])
    conditional = mean(statistics.entropy([row[i] for row in matrix]) for i in range(24))
    information = max(0.0, marginal - conditional)
    rng = random.Random(20260909)
    exceed = 0
    for _ in range(999):
        shuffled = [rng.sample(row, len(row)) for row in matrix]
        null_marginal = statistics.entropy([choice for row in shuffled for choice in row])
        null_conditional = mean(statistics.entropy([row[i] for row in shuffled]) for i in range(24))
        exceed += null_marginal - null_conditional >= information - 1e-12
    rates = []
    for condition in range(24):
        choices = [row[condition] for row in matrix]
        counts = Counter(choices)
        rates.append({
            "condition": condition,
            "order": orders[condition],
            "choice_counts": {choice: counts[choice] for choice in ("A", "B", "C")},
            "target_rate": counts[target] / 10,
        })
    return {
        "mode": mode,
        "complete_panels": 10,
        "orders": rates,
        "choice_counts": dict(Counter(choice for row in matrix for choice in row)),
        "entropy_bits": marginal,
        "mean_within_order_entropy_bits": conditional,
        "order_information_bits": information,
        "order_association_p_raw": (exceed + 1) / 1000,
        "null_repetitions": 999,
    }


def _position_and_inversion(trials: list[dict], target: str) -> dict:
    fixture = protocol.fixtures()["water4"]
    tool = "aquifer_tool"
    position_rows = [[] for _ in range(4)]
    by_rep = defaultdict(lambda: [[] for _ in range(4)])
    for trial in trials:
        job = trial["job"]
        if job["mode"] != "permutation_stateful":
            continue
        position = job["order"].index(tool)
        hit = int(trial["final"]["final_choice"] == target)
        position_rows[position].append(hit)
        by_rep[job["rep"]][position].append(hit)
    if any(len(row) != 60 for row in position_rows):
        raise ValueError("target-favouring position panel is incomplete")
    per_panel_differences = []
    for rep in range(1, 11):
        if any(len(row) != 6 for row in by_rep[rep]):
            raise ValueError("position counts changed in panel")
        per_panel_differences.append(mean(by_rep[rep][3]) - mean(by_rep[rep][0]))
    budget = {}
    expected_orders = list(permutations(fixture["natural"]))
    for distance in range(7):
        rows = [
            trial for trial in trials
            if trial["job"]["mode"] == "budget"
            and trial["job"]["condition"] == str(distance)
        ]
        if len(rows) != 15:
            raise ValueError("inversion level is incomplete")
        expected_order = next(
            order for order in expected_orders
            if protocol.inversions(order, fixture["natural"]) == distance
        )
        if any(trial["job"]["order"] != list(expected_order) for trial in rows):
            raise ValueError("inversion order changed")
        hits = sum(trial["final"]["final_choice"] == target for trial in rows)
        budget[str(distance)] = {
            "n": 15,
            "order": list(expected_order),
            "target_rate": hits / 15,
            "target_rate_wilson_95": statistics.wilson(hits, 15),
        }
    return {
        "target_favouring_tool_position": {
            "tool": tool,
            "n_per_position": 60,
            "target_rate_by_position": [mean(row) for row in position_rows],
            "last_minus_first": mean(per_panel_differences),
            "panel_bootstrap_95": statistics.interval(per_panel_differences),
        },
        "inversion": {
            "distance_levels": budget,
            "fixed_attack_distance": protocol.inversions(fixture["attack"], fixture["natural"]),
        },
    }


def _trajectory(trials: list[dict]) -> dict:
    result = {}
    for condition in ("natural", "attack"):
        rows = [
            trial for trial in trials
            if trial["job"]["mode"] == "stateful"
            and trial["job"]["condition"] == condition
        ]
        if len(rows) != 30:
            raise ValueError("stateful trajectory is incomplete")
        paths = [
            [state["state"]["current_choice"] for state in trial["states"]]
            + [trial["final"]["final_choice"]]
            for trial in rows
        ]
        if any(len(path) != 5 for path in paths):
            raise ValueError("stateful trajectory has wrong length")
        result[condition] = {
            "n": 30,
            "choice_counts_by_step": [
                {choice: Counter(path[i] for path in paths)[choice] for choice in ("A", "B", "C")}
                for i in range(5)
            ],
            "changed_from_previous_by_step": [
                sum(path[i] != path[i - 1] for path in paths) for i in range(1, 5)
            ],
            "final_equals_first": sum(path[-1] == path[0] for path in paths),
            "never_revised": sum(len(set(path)) == 1 for path in paths),
        }
    return result


def _latency(events: list[dict], completed: list[dict]) -> dict:
    by_job = defaultdict(list)
    for event in events:
        if event["event"] in ("call_complete", "call_failed"):
            by_job[event["job_id"]].append(event)
    values, missing = [], 0
    for trial in completed:
        calls = by_job[trial["job"]["id"]]
        if not calls or any(
            not isinstance(call.get("elapsed_seconds"), (int, float))
            or not math.isfinite(call["elapsed_seconds"])
            for call in calls
        ):
            missing += 1
            continue
        values.append(math.fsum(call["elapsed_seconds"] for call in calls))
    return {
        "completed_decisions": len(completed),
        "decisions_with_complete_inference_elapsed": len(values),
        "decisions_missing_inference_elapsed": missing,
        "inference_elapsed_seconds_per_decision_mean": mean(values) if values else None,
        "inference_elapsed_seconds_per_decision_median": median(values) if values else None,
        "excludes_simulated_arrival_delays": True,
    }


def _analyze_cell(cell: dict) -> dict:
    events, evidence = _read_cell(cell)
    trials = [event for event in events if event["event"] == "job_complete"]
    target = protocol.fixtures()["water4"]["target"]
    rates = _cell_rates(trials, target)
    pairs = _primary_pairs(trials, target)
    stateful_panel = _order_panel(trials, target)
    consistency_panel = _order_panel(trials, target, "consistency")
    position = _position_and_inversion(trials, target)
    trajectory = _trajectory(trials)
    latency = _latency(events, trials)
    cost = evidence["cost"]
    cost["amortized_usd_per_completed_decision"] = cost["all_attempts_known_usd"] / 690
    return {
        "model": cell["model"],
        "reasoning": cell["reasoning"],
        "role": cell["role"],
        "primary_pairs": pairs,
        "final_choice_distributions": rates,
        "stateful_24_order_panel": stateful_panel,
        "consistency_24_order_panel": consistency_panel,
        **position,
        "stateful_provisional_choice_trajectory": trajectory,
        "controls": {
            "simultaneous": rates["control|simultaneous"],
            "barrier_canonical": rates["barrier|canonical"],
        },
        "latency": latency,
        "cost": cost,
        "provenance": {key: value for key, value in evidence.items() if key != "cost"},
    }


def build_analysis() -> dict:
    fixture = json.loads(FIXTURE_MANIFEST.read_text())
    availability = json.loads(AVAILABILITY_MANIFEST.read_text())
    if fixture["semantic_target"] != "C" or fixture["study_trials_per_model"] != 690:
        raise ValueError("Experiment A frozen fixture changed")
    if availability["multiplicity"] != {
        "claude_none_in_primary_family": False,
        "evaluable_matched_hypotheses": 6,
        "method": "holm",
        "model_pooling": "none_for_primary_tests",
        "planned_family_size": 8,
        "structural_p_one_for_adjustment_only": 2,
        "unavailable_matched_hypotheses": 2,
    }:
        raise ValueError("Experiment A availability multiplicity changed")
    cells = {cell["name"]: _analyze_cell(cell) for cell in CELLS}
    raw_p = {
        f"{name}|{mode}": cells[name]["primary_pairs"][mode]["exact_p_raw"]
        for name in ("terra", "gemini", "qwen")
        for mode in ("stateful", "stateless")
    }
    structural = {"claude_unavailable|stateful": 1.0, "claude_unavailable|stateless": 1.0}
    adjusted = statistics.holm({**raw_p, **structural})
    result = {
        "schema": "chronos.experiment-a-analysis.v1",
        "analysis_sha256": None,
        "source": "sealed_raw_experiment_a_ledgers",
        "fixture_manifest_sha256": _sha256(FIXTURE_MANIFEST.read_bytes()),
        "availability_manifest_sha256": _sha256(AVAILABILITY_MANIFEST.read_bytes()),
        "target": "C",
        "matched_non_off_primary": {name: cells[name] for name in ("terra", "gemini", "qwen")},
        "unavailable_matched_primary": {
            "model": "anthropic/claude-sonnet-4-6@default",
            "status": "operationally_unavailable_after_bounded_retry",
            "reasoning": "non_off_unavailable",
            "p_values": None,
        },
        "claude_none_sensitivity": cells["claude_none"],
        "primary_multiplicity": {
            "method": "holm",
            "family_size": 8,
            "raw_p": raw_p,
            "adjusted_p": {key: adjusted[key] for key in raw_p},
            "structural_p_one_for_accounting_only": structural,
            "classification": "confirmatory_independent_scenario",
        },
        "qualifications": [
            "Claude-none is a reasoning-off sensitivity and is outside the matched primary family.",
            "Claude matched non-off effects are unavailable, not observed null effects.",
            "Order information and position associations are exploratory and finite-sample sensitive.",
            "Latency excludes simulated arrival delays and unlogged transient wait time.",
            "The water4 options have no objective correctness key.",
            "Paired bootstrap intervals retain the established analysis convention; "
            "supplementary exact Bonferroni intervals use four one-sided .0125 "
            "Clopper-Pearson bounds for boundary-robust uncertainty.",
        ],
    }
    result["analysis_sha256"] = _canonical_hash(
        {key: value for key, value in result.items() if key != "analysis_sha256"}
    )
    return result


def verify_analysis_file(path: Path = DEFAULT_OUTPUT) -> dict:
    saved = json.loads(path.read_text())
    actual = build_analysis()
    if saved != actual:
        raise ValueError("Experiment A analysis differs from fresh raw regeneration")
    return actual


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("choose --output or --verify")
    if args.verify:
        result = verify_analysis_file(args.verify)
        print(f"PASS Experiment A analysis {result['analysis_sha256']}")
        return
    result = build_analysis()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print(f"WROTE {args.output} {result['analysis_sha256']}")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
