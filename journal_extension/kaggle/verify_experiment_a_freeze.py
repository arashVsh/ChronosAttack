"""Verify experiment A's frozen scenario, topology and no-call state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "experiment_a_manifest_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dominates(left: str, right: str, metrics: dict) -> bool:
    weakly_better = []
    strictly_better = []
    for metric in metrics.values():
        left_value = metric["values"][left]
        right_value = metric["values"][right]
        if metric["direction"] == "higher_is_better":
            weakly_better.append(left_value >= right_value)
            strictly_better.append(left_value > right_value)
        elif metric["direction"] == "lower_is_better":
            weakly_better.append(left_value <= right_value)
            strictly_better.append(left_value < right_value)
        else:
            raise ValueError("unknown metric direction")
    return all(weakly_better) and any(strictly_better)


def verify() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    expected_keys = {
        "schema", "manifest_sha256", "status", "frozen_at", "round_amendment", "sources",
        "study_id", "seed", "domain", "horizon_years", "options",
        "semantic_target", "metrics", "natural_order", "attack_order",
        "natural_arrival_ms", "models", "reasoning_policy",
        "study_trials_per_model", "study_calls_per_model", "primary_estimand",
        "primary_repetitions", "endpoints", "analysis", "multiplicity",
        "exclusions", "attack_selection", "collection_status",
    }
    if set(manifest) != expected_keys:
        raise ValueError("invalid experiment-A freeze schema")
    if (
        manifest["schema"] != "chronos.experiment-a-freeze.v1"
        or manifest["status"] != "fixture_frozen_no_calls"
        or manifest["collection_status"] != "not_started"
        or manifest["attack_selection"] != "fixed_before_collection_no_outcome_search"
    ):
        raise ValueError("experiment A is not in the frozen pre-collection state")
    unhashed = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    canonical = json.dumps(unhashed, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != manifest["manifest_sha256"]:
        raise ValueError("experiment-A manifest self-hash mismatch")
    amendment = manifest["round_amendment"]
    amendment_path = ROOT / amendment["path"]
    if _sha256(amendment_path) != amendment["sha256"]:
        raise ValueError("round amendment hash mismatch")
    if set(manifest["sources"]) != {
        "completion_protocol.py", "water_supply_protocol.py", "audit_water_supply.py"
    }:
        raise ValueError("experiment-A source set is incomplete")
    for name, expected_hash in manifest["sources"].items():
        if _sha256(HERE / name) != expected_hash:
            raise ValueError(f"frozen experiment-A source hash mismatch: {name}")

    fixture = protocol.fixtures()["water4"]
    protocol.validate_fixture(fixture)
    if (
        protocol.engine.STUDY_ID != manifest["study_id"]
        or protocol.engine.SEED != manifest["seed"]
        or fixture["target"] != manifest["semantic_target"]
        or fixture["natural"] != manifest["natural_order"]
        or fixture["attack"] != manifest["attack_order"]
        or fixture["arrivals"] != manifest["natural_arrival_ms"]
        or fixture["attack"] != fixture["natural"][1:] + fixture["natural"][:1]
    ):
        raise ValueError("runtime fixture differs from the frozen scenario contract")
    if "arrival timing is not evidence" not in fixture["system"]:
        raise ValueError("system prompt does not neutralize timing as evidence")
    metrics = manifest["metrics"]
    if set(metrics) != set(fixture["payloads"]):
        raise ValueError("metric/tool set differs from the runtime fixture")
    for tool, record in metrics.items():
        payload = json.loads(fixture["payloads"][tool])
        expected_payload = {
            "synthetic": True,
            "service_area": "same regional utility",
            "metric": record["metric"],
            "direction": record["direction"],
            "values": record["values"],
        }
        if (
            payload != expected_payload
            or fixture["hashes"][tool] != record["payload_sha256"]
        ):
            raise ValueError(f"frozen payload mismatch: {tool}")

    options = sorted(manifest["options"])
    leaders = set()
    for metric in metrics.values():
        values = metric["values"]
        best = (
            max(values.values())
            if metric["direction"] == "higher_is_better"
            else min(values.values())
        )
        leaders.update(option for option, value in values.items() if value == best)
    if leaders != set(options):
        raise ValueError("every option must lead at least one frozen tradeoff")
    if any(
        _dominates(left, right, metrics)
        for left in options
        for right in options
        if left != right
    ):
        raise ValueError("a frozen option Pareto-dominates another option")
    if (
        manifest["analysis"] != {
            "primary_test": "two_sided_exact_mcnemar_on_paired_target_C_binary",
            "effect": "attack_minus_natural_percentage_points",
            "confidence_level": 0.95,
            "order_panel_repetitions": 10,
            "permutation_order_count": 24,
            "model_pooling": "none_for_primary_tests",
            "classification": "confirmatory_independent_scenario",
        }
        or manifest["multiplicity"] != {
            "method": "holm",
            "alpha": 0.05,
            "family": "eight_primary_tests_four_models_by_stateful_or_stateless",
            "family_size": 8,
        }
        or manifest["exclusions"] != {
            "compatibility_pilots": "always_excluded",
            "invalid_or_missing_trial": "no_imputation_report_cell_partial",
            "failed_attempt": "cost_and_failure_accounting_only",
            "successful_retry": "one_outcome_for_the_completed_trial_all_attempt_costs_retained",
            "data_dependent_exclusions": "forbidden",
            "selection_data_in_primary_natural_attack_test": "none",
        }
        or len(manifest["endpoints"]["primary"]) != 2
        or len(manifest["endpoints"]["secondary"]) != 8
    ):
        raise ValueError("experiment-A analysis contract drifted")

    old_models = protocol.engine.MODELS
    try:
        protocol.engine.MODELS = tuple(manifest["models"])
        per_model = []
        all_ids = []
        for model in manifest["models"]:
            jobs = protocol.jobs_for(model, "study")
            if (
                len(jobs) != manifest["study_trials_per_model"]
                or sum(job["calls"] for job in jobs)
                != manifest["study_calls_per_model"]
                or len({job["id"] for job in jobs}) != len(jobs)
                or any(job["scenario"] != "water4" for job in jobs)
            ):
                raise ValueError(f"invalid experiment-A job topology: {model}")
            natural = [
                job for job in jobs
                if job["mode"] == "stateful" and job["condition"] == "natural"
            ]
            attack = [
                job for job in jobs
                if job["mode"] == "stateful" and job["condition"] == "attack"
            ]
            if (
                len(natural) != manifest["primary_repetitions"]
                or len(attack) != manifest["primary_repetitions"]
                or {job["rep"] for job in natural} != {job["rep"] for job in attack}
            ):
                raise ValueError("primary paired stateful panel is incomplete")
            all_ids.extend(job["id"] for job in jobs)
            per_model.append(
                {"model": model, "jobs": len(jobs), "calls": sum(job["calls"] for job in jobs)}
            )
    finally:
        protocol.engine.MODELS = old_models
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("experiment-A job identities collide across models")
    return {
        "status": manifest["status"],
        "models": per_model,
        "total_jobs": sum(item["jobs"] for item in per_model),
        "total_calls": sum(item["calls"] for item in per_model),
        "source_sha256": manifest["sources"],
    }


def main() -> None:
    checked = verify()
    for item in checked["models"]:
        print(f"PASS {item['model']}: {item['jobs']} jobs / {item['calls']} calls")
    print(
        f"EXPERIMENT A FIXTURE VERIFIED: {checked['total_jobs']} jobs / "
        f"{checked['total_calls']} calls; collection not started"
    )


if __name__ == "__main__":
    main()
