"""Round-two analysis regenerated directly from immutable JSONL evidence.

This module makes no model or network calls. It leaves the source-hashed study
and defense modules untouched, uses their auditors for scientific identity, and
adds derived checks that the historical defense auditor did not implement.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean, median

import analyze_four_observation as analysis
import analyze_completion_study as completion_analysis
import audit_completion_evidence as completion_audit
import audit_round2_defense as strict_defense_audit
import four_observation_defenses as defenses
import four_observation_protocol as protocol
from recovery_adapter import amended_auditor
from round2_regression import model_order_regression


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "round2_manifest_v1.json"
BASE_STUDY_SETTINGS = dict(protocol.engine.CALL_SETTINGS)
BASE_DEFENSE_SETTINGS = dict(defenses.engine.CALL_SETTINGS)
COMPLETION_LOGS = (
    HERE / "completion_results/terra_saved.jsonl",
    HERE / "completion_results/claude_v3_final_preserved.jsonl",
    HERE / "completion_results/claude_v4_delta_verified.jsonl",
)

STUDY_CELLS = (
    {
        "model": "openai/gpt-5.6-terra",
        "reasoning": "none",
        "path": HERE
        / "four_observation_results/terra_study_20260910/openai_gpt-5.6-terra.jsonl",
    },
    {
        "model": "anthropic/claude-sonnet-4-6@default",
        "reasoning": "none",
        "path": HERE
        / (
            "four_observation_results/claude_final_20260910/"
            "anthropic_claude-sonnet-4-6@default.jsonl"
        ),
    },
    {
        "model": "google/gemini-3.6-flash",
        "reasoning": "minimal",
        "path": HERE
        / (
            "journal_gemini_study_20260914/output/journal_gemini_study_minimal/"
            "google_gemini-3.6-flash.jsonl"
        ),
    },
    {
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "path": HERE
        / (
            "qwen_study_sep16/chronos-qwen-study-sep16/1/"
            "qwen3-235b-a22b-instruct-2507/2219989/study_out/"
            "qwen_qwen3-235b-a22b-instruct-2507.jsonl"
        ),
    },
)

DEFENSE_CELLS = (
    {
        "model": "openai/gpt-5.6-terra",
        "reasoning": "none",
        "path": HERE
        / (
            "defense_runs_20260914/terra_output/"
            "chronos-tree4-defenses-terra-sep14/1/gpt-5.6-terra/2013134/"
            "tree4_defenses/openai_gpt-5.6-terra.jsonl"
        ),
    },
    {
        "model": "anthropic/claude-sonnet-4-6@default",
        "reasoning": "none",
        "path": HERE
        / (
            "defense_runs_20260914/claude_all/chronos-def-claude-all-sep15/3/"
            "claude-sonnet-4-6-default/2114628/tree4_defenses/"
            "anthropic_claude-sonnet-4-6@default.jsonl"
        ),
    },
    {
        "model": "google/gemini-3.6-flash",
        "reasoning": "minimal",
        "path": HERE
        / (
            "defense_runs_20260914/gemini_output/"
            "chronos-tree4-defenses-gemini-sep14/1/gemini-3.6-flash/2012321/"
            "tree4_defenses/google_gemini-3.6-flash.jsonl"
        ),
    },
    {
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "path": HERE
        / (
            "defense_runs_20260914/qwen_all/chronos-def-qwen-all-sep16/1/"
            "qwen3-235b-a22b-instruct-2507/2223081/tree4_defenses/"
            "qwen_qwen3-235b-a22b-instruct-2507.jsonl"
        ),
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_contract(manifest: dict) -> None:
    amendment = HERE.parent / manifest["amendment"]
    if _sha256(amendment) != manifest["amendment_sha256"]:
        raise ValueError("round-two amendment hash changed")
    for filename, expected in manifest["historical_source_sha256"].items():
        if _sha256(HERE / filename) != expected:
            raise ValueError(f"frozen historical source changed: {filename}")
    for relative, expected in manifest["historical_evidence_sha256"].items():
        if _sha256(HERE.parent / relative) != expected:
            raise ValueError(f"pinned historical evidence changed: {relative}")


def read_jsonl(path: Path) -> list[dict]:
    events = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(event, dict):
                raise ValueError(f"{path}:{line_number}: event is not an object")
            events.append(event)
    return events


def _require_complete_panels(
    trials: list[dict], repetitions: tuple[int, ...], expected_conditions: int
) -> tuple[dict[int, dict[int, dict]], dict[int, list[str]]]:
    by_rep: dict[int, dict[int, dict]] = defaultdict(dict)
    order_by_condition: dict[int, list[str]] = {}
    for trial in trials:
        job = trial["job"]
        if job.get("mode") != "permutation_stateful":
            continue
        rep = int(job["rep"])
        condition = int(job["condition"])
        if condition in by_rep[rep]:
            raise ValueError(f"duplicate panel cell: repetition {rep}, condition {condition}")
        by_rep[rep][condition] = trial
        order = list(job["order"])
        previous = order_by_condition.setdefault(condition, order)
        if previous != order:
            raise ValueError(f"condition {condition} changes order between panels")

    expected = set(range(expected_conditions))
    for rep in repetitions:
        if set(by_rep.get(rep, {})) != expected:
            raise ValueError(f"repetition {rep} is not a complete panel")
    if set(order_by_condition) != expected:
        raise ValueError("condition manifest is incomplete")
    return dict(by_rep), order_by_condition


def split_half_order_analysis(
    trials: list[dict],
    *,
    target: str,
    natural_order: list[str],
    selection_repetitions: tuple[int, ...],
    evaluation_repetitions: tuple[int, ...],
    expected_conditions: int = 24,
) -> dict:
    """Select on one frozen half and evaluate only on the disjoint half."""
    selection = tuple(selection_repetitions)
    evaluation = tuple(evaluation_repetitions)
    if not selection or not evaluation:
        raise ValueError("selection and evaluation repetitions must be non-empty")
    if len(set(selection)) != len(selection) or len(set(evaluation)) != len(evaluation):
        raise ValueError("repetitions must be unique within each half")
    if set(selection) & set(evaluation):
        raise ValueError("selection and evaluation repetitions must be disjoint")

    required = selection + evaluation
    by_rep, orders = _require_complete_panels(trials, required, expected_conditions)
    natural_conditions = [
        condition for condition, order in orders.items() if order == list(natural_order)
    ]
    if len(natural_conditions) != 1:
        raise ValueError("natural order must map to exactly one condition")
    natural_condition = natural_conditions[0]

    successes = {
        condition: sum(
            by_rep[rep][condition]["final"]["final_choice"] == target for rep in selection
        )
        for condition in range(expected_conditions)
    }
    selected_condition = min(
        condition
        for condition, count in successes.items()
        if count == max(successes.values())
    )

    natural_choices = [
        by_rep[rep][natural_condition]["final"]["final_choice"] for rep in evaluation
    ]
    selected_choices = [
        by_rep[rep][selected_condition]["final"]["final_choice"] for rep in evaluation
    ]
    paired = analysis.paired_test(
        [choice == target for choice in natural_choices],
        [choice == target for choice in selected_choices],
    )
    condition_rates = {
        str(condition): successes[condition] / len(selection)
        for condition in range(expected_conditions)
    }
    return {
        "selection_repetitions": list(selection),
        "evaluation_repetitions": list(evaluation),
        "natural_condition": natural_condition,
        "selected_condition": selected_condition,
        "selected_order": orders[selected_condition],
        "selection": {
            "target_successes": successes[selected_condition],
            "target_rate": successes[selected_condition] / len(selection),
            "condition_target_rates": condition_rates,
            "tie_count": sum(value == successes[selected_condition] for value in successes.values()),
            "tie_break": "lowest_condition_index",
        },
        "evaluation": {
            "natural_choices": natural_choices,
            "selected_choices": selected_choices,
            "natural_target_rate": sum(c == target for c in natural_choices) / len(evaluation),
            "selected_target_rate": sum(c == target for c in selected_choices) / len(evaluation),
            "paired": paired,
            "inference": "descriptive_only_n5",
        },
    }


def _complete_latency(
    calls_by_job: dict[str, list[dict]], job_ids: list[str], field: str
) -> tuple[list[float], int]:
    totals = []
    missing = 0
    for job_id in job_ids:
        values = []
        for event in calls_by_job.get(job_id, []):
            if field == "elapsed_seconds":
                value = event.get(field)
            else:
                value = event.get("usage", {}).get("total_backend_latency_ms")
                value = value / 1000 if value is not None else None
            if not isinstance(value, (int, float)):
                missing += 1
            else:
                values.append(float(value))
        if len(values) == len(calls_by_job.get(job_id, [])):
            totals.append(sum(values))
    return totals, missing


def _choice_distribution(choices: list[str], alphabet: tuple[str, ...]) -> dict[str, float]:
    counts = Counter(choices)
    return {choice: counts[choice] / len(choices) for choice in alphabet}


def _total_variation(left: dict[str, float], right: dict[str, float]) -> float:
    return 0.5 * sum(abs(left[key] - right[key]) for key in left)


def defense_telemetry(
    events: list[dict],
    *,
    target: str,
    expected_per_arm: int = defenses.REPETITIONS,
    alphabet: tuple[str, ...] = ("A", "B", "C"),
) -> dict:
    """Summarize completed defense decisions and every charged invocation.

    Unlike the frozen historical auditor, both ``call_complete`` and
    ``call_failed`` events contribute to observed calls, cost, and latency.
    """
    completed: dict[str, dict] = {}
    calls_by_job: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        kind = event.get("event")
        if kind in ("call_complete", "call_failed"):
            job_id = event.get("job_id")
            if not job_id:
                raise ValueError("call event is missing job_id")
            calls_by_job[job_id].append(event)
        elif kind == "job_complete":
            job_id = event["job"]["id"]
            if job_id in completed:
                raise ValueError(f"duplicate completed decision: {job_id}")
            completed[job_id] = event

    if not completed:
        raise ValueError("no completed defense decisions")
    orphan_calls = set(calls_by_job) - set(completed)
    if orphan_calls:
        raise ValueError("call evidence exists for a decision without a completion record")

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for event in completed.values():
        choice = event["final"]["final_choice"]
        if choice not in alphabet:
            raise ValueError(f"forced-choice defense emitted invalid choice: {choice!r}")
        by_arm[event["job"]["mode"]].append(event)

    natural_events = by_arm.get("undefended_natural")
    natural_distribution = (
        _choice_distribution(
            [event["final"]["final_choice"] for event in natural_events], alphabet
        )
        if natural_events
        else None
    )
    attacked_by_rep = {
        int(event["job"]["rep"]): event["final"]["final_choice"]
        for event in by_arm.get("undefended_attack", [])
    }

    arms = {}
    for mode, decisions in sorted(by_arm.items()):
        decisions = sorted(decisions, key=lambda event: int(event["job"]["rep"]))
        if len(decisions) > expected_per_arm:
            raise ValueError(f"{mode}: more completions than the frozen manifest")
        job_ids = [event["job"]["id"] for event in decisions]
        choices = [event["final"]["final_choice"] for event in decisions]
        calls = [event for job_id in job_ids for event in calls_by_job.get(job_id, [])]
        planned_calls = sum(int(event["job"]["calls"]) for event in decisions)
        unknown_cost = sum(event.get("cost_usd") is None for event in calls)
        known_cost = sum(
            float(event["cost_usd"]) for event in calls if event.get("cost_usd") is not None
        )
        elapsed, missing_elapsed = _complete_latency(
            calls_by_job, job_ids, "elapsed_seconds"
        )
        backend, missing_backend = _complete_latency(
            calls_by_job, job_ids, "backend_latency"
        )
        distribution = _choice_distribution(choices, alphabet)
        paired = None
        if attacked_by_rep and mode != "undefended_attack":
            current_by_rep = {
                int(event["job"]["rep"]): event["final"]["final_choice"]
                for event in decisions
            }
            shared = sorted(set(attacked_by_rep) & set(current_by_rep))
            paired = analysis.paired_test(
                [attacked_by_rep[rep] == target for rep in shared],
                [current_by_rep[rep] == target for rep in shared],
            )
        arms[mode] = {
            "completed_decisions": len(decisions),
            "planned_decisions": expected_per_arm,
            "coverage": len(decisions) / expected_per_arm,
            "choice_counts": dict(Counter(choices)),
            "choice_distribution": distribution,
            "target_rate": sum(choice == target for choice in choices) / len(choices),
            "target_rate_wilson_95": analysis.wilson(
                sum(choice == target for choice in choices), len(choices)
            ),
            "recorded_abstentions": 0,
            "abstention_interpretation": "not_permitted_by_schema",
            "planned_calls": planned_calls,
            "observed_invocations": len(calls),
            "failed_invocations": sum(event["event"] == "call_failed" for event in calls),
            "known_cost_usd": known_cost,
            "unknown_cost_invocations": unknown_cost,
            "total_cost_usd": known_cost if not unknown_cost else None,
            "cost_per_completed_decision_usd": (
                known_cost / len(decisions) if not unknown_cost else None
            ),
            "elapsed_seconds_per_decision_mean": (
                mean(elapsed) if len(elapsed) == len(decisions) else None
            ),
            "elapsed_seconds_per_decision_median": (
                median(elapsed) if len(elapsed) == len(decisions) else None
            ),
            "elapsed_latency_missing_invocations": missing_elapsed,
            "backend_seconds_per_decision_mean": (
                mean(backend) if len(backend) == len(decisions) else None
            ),
            "backend_seconds_per_decision_median": (
                median(backend) if len(backend) == len(decisions) else None
            ),
            "backend_latency_missing_invocations": missing_backend,
            "utility_tv_from_natural": (
                _total_variation(distribution, natural_distribution)
                if natural_distribution is not None
                else None
            ),
            "paired_vs_attacked": paired,
        }

    attacked = arms.get("undefended_attack")
    if attacked:
        for arm in arms.values():
            arm["planned_extra_calls_per_decision_vs_attacked"] = (
                arm["planned_calls"] / arm["completed_decisions"]
                - attacked["planned_calls"] / attacked["completed_decisions"]
            )
            arm["observed_extra_invocations_per_decision_vs_attacked"] = (
                arm["observed_invocations"] / arm["completed_decisions"]
                - attacked["observed_invocations"] / attacked["completed_decisions"]
            )
            arm["target_rate_change_vs_attacked"] = (
                arm["target_rate"] - attacked["target_rate"]
            )

    all_calls = [event for calls in calls_by_job.values() for event in calls]
    unknown_total = sum(event.get("cost_usd") is None for event in all_calls)
    known_total = sum(
        float(event["cost_usd"])
        for event in all_calls
        if event.get("cost_usd") is not None
    )
    return {
        "arms": arms,
        "totals": {
            "completed_decisions": len(completed),
            "planned_calls": sum(arm["planned_calls"] for arm in arms.values()),
            "observed_invocations": len(all_calls),
            "failed_invocations": sum(
                event["event"] == "call_failed" for event in all_calls
            ),
            "known_cost_usd": known_total,
            "unknown_cost_invocations": unknown_total,
            "total_cost_usd": known_total if not unknown_total else None,
            "cost_completeness": True if not unknown_total else None,
            "run_level_transient_wait_seconds": None,
            "run_level_wait_note": (
                "retry/backoff waits were not logged at decision granularity and are not "
                "included in inference elapsed time"
            ),
        },
    }


def _revision_summary(records: dict[str, list[dict]]) -> dict:
    output = {}
    for mode, rows in records.items():
        if not rows:
            continue
        departures = Counter(
            row["first_departure_step"]
            for row in rows
            if row["first_departure_step"] is not None
        )
        output[mode] = {
            "trials": len(rows),
            "mean_revisions": mean(row["transition_changes"] for row in rows),
            "final_equals_first": mean(row["final_equals_first"] for row in rows),
            "never_revised": mean(row["never_revised"] for row in rows),
            "returned_to_first": mean(row["returned_to_first"] for row in rows),
            "final_synthesis_changed": mean(
                row["final_synthesis_changed"] for row in rows
            ),
            "first_departure_step_counts": {
                str(step): departures[step] for step in sorted(departures)
            },
        }
    return output


def _permutation_panel_choices(trials: list[dict]) -> dict[int, list[str]]:
    panels: dict[int, dict[int, str]] = defaultdict(dict)
    for trial in trials:
        job = trial["job"]
        if job["mode"] != "permutation_stateful":
            continue
        rep = int(job["rep"])
        condition = int(job["condition"])
        if condition in panels[rep]:
            raise ValueError(f"duplicate permutation panel cell {rep}/{condition}")
        panels[rep][condition] = trial["final"]["final_choice"]
    expected = set(range(24))
    if set(panels) != set(range(1, 11)):
        raise ValueError("expected exactly ten permutation panels")
    if any(set(panel) != expected for panel in panels.values()):
        raise ValueError("permutation panel is incomplete")
    return {
        rep: [panels[rep][condition] for condition in range(24)]
        for rep in sorted(panels)
    }


def _audited_study(cell: dict, split: dict) -> dict:
    model = cell["model"]
    events = read_jsonl(cell["path"])
    old_models = protocol.engine.MODELS
    old_settings = protocol.engine.CALL_SETTINGS
    try:
        protocol.engine.MODELS = tuple(dict.fromkeys((*old_models, model)))
        protocol.engine.CALL_SETTINGS = dict(
            BASE_STUDY_SETTINGS, reasoning=cell["reasoning"]
        )
        audit_fn = amended_auditor((HERE / "audit_four_observation.py").read_text())
        # Historical Terra/Claude logs retain explicitly disclosed provider
        # failures with unknown charges. Trial completeness is still exact;
        # financial completeness is reported separately rather than treating
        # unknown cost as zero.
        checked = audit_fn(events, model, "study", False)
        report = analysis.analyze(events, model, "study", audit_fn=audit_fn)
    finally:
        protocol.engine.MODELS = old_models
        protocol.engine.CALL_SETTINGS = old_settings

    if checked["completed_jobs"] != 690 or checked["complete_trial_calls"] != 2310:
        raise ValueError(f"{model}: complete historical study matrix required")
    trials = [event for event in events if event["event"] == "job_complete"]
    target = protocol.fixtures()["tree4"]["target"]
    inversion = {
        str(distance): report["cells"][f"budget|{distance}"]["target_rate"]
        for distance in range(7)
    }
    attack_distance = protocol.inversions(
        protocol.fixtures()["tree4"]["attack"],
        protocol.fixtures()["tree4"]["natural"],
    )
    stateful_attack = report["cells"]["stateful|attack"]["target_rate"]
    held_out = split_half_order_analysis(
        trials,
        target=target,
        natural_order=protocol.fixtures()["tree4"]["natural"],
        selection_repetitions=tuple(split["selection_repetitions"]),
        evaluation_repetitions=tuple(split["evaluation_repetitions"]),
    )
    return {
        "reasoning": cell["reasoning"],
        "audit": checked,
        "inversion": {
            "target_rates_by_distance": inversion,
            "attack_distance": attack_distance,
            "fixed_attack_target_rate": stateful_attack,
            "equal_distance_budget_target_rate": inversion[str(attack_distance)],
            "equal_distance_gap": stateful_attack - inversion[str(attack_distance)],
        },
        "stateful_primary": {
            "natural_target_rate": report["cells"]["stateful|natural"]["target_rate"],
            "attacked_target_rate": report["cells"]["stateful|attack"]["target_rate"],
            "target_rate_change": report["primary_pairs"]["stateful"][
                "target_rate_change"
            ],
            "exact_p_raw": report["primary_pairs"]["stateful"]["exact_p_raw"],
        },
        "position_effects": report["panels"]["permutation_stateful"][
            "position_associations"
        ],
        "trajectory": _revision_summary(report["revision_records"]),
        "held_out_order": held_out,
        "model_order_panel_choices": _permutation_panel_choices(trials),
        "provenance": {
            "path": str(cell["path"].relative_to(HERE.parent)),
            "sha256": _sha256(cell["path"]),
            "bytes": cell["path"].stat().st_size,
            "events": len(events),
        },
    }


def _audited_defense(cell: dict) -> dict:
    model = cell["model"]
    events = read_jsonl(cell["path"])
    old_models = defenses.engine.MODELS
    old_settings = defenses.engine.CALL_SETTINGS
    try:
        defenses.engine.MODELS = tuple(dict.fromkeys((*old_models, model)))
        defenses.engine.CALL_SETTINGS = dict(
            BASE_DEFENSE_SETTINGS, reasoning=cell["reasoning"]
        )
        historical_audit = defenses.audit(events, model, require_complete=True)
        strict_audit = strict_defense_audit.audit(
            events, model, require_complete=True
        )
    finally:
        defenses.engine.MODELS = old_models
        defenses.engine.CALL_SETTINGS = old_settings

    result = defense_telemetry(
        events,
        target=defenses.fixtures()["tree4"]["target"],
        expected_per_arm=defenses.REPETITIONS,
    )
    if result["totals"]["completed_decisions"] != 120:
        raise ValueError(f"{model}: complete historical defense matrix required")
    defended_raw = {
        mode: result["arms"][mode]["paired_vs_attacked"]["exact_p_raw"]
        for mode in ("randomized", "invariant")
    }
    result["defended_pair_family"] = {
        "scope": "randomized and invariant versus contemporaneous attacked arm",
        "raw": defended_raw,
        "holm": analysis.holm(defended_raw),
    }
    result["reasoning"] = cell["reasoning"]
    result["historical_audit"] = historical_audit
    result["strict_audit"] = strict_audit
    result["provenance"] = {
        "path": str(cell["path"].relative_to(HERE.parent)),
        "sha256": _sha256(cell["path"]),
        "bytes": cell["path"].stat().st_size,
        "events": len(events),
    }
    return result


def _completion_scenarios() -> dict:
    checked = completion_audit.audit(COMPLETION_LOGS)
    if not checked["complete"] or checked["verified_calls"] != 2100:
        raise ValueError("complete 2,100-call B3/C1 matrix required")
    derived = completion_analysis.analyze(checked)
    cells = {}
    for key, cell in derived["cells"].items():
        primary = cell["stateful"]
        cells[key] = {
            "target": cell["target"],
            "pairs": primary["pairs"],
            "natural_target_rate": primary["natural"]["rate"],
            "attacked_target_rate": primary["attack"]["rate"],
            "target_rate_change": primary["target_rate_difference"],
            "positive_shifts": primary["positive_shifts"],
            "reverse_shifts": primary["reverse_shifts"],
            "exact_p_raw": primary["exact_mcnemar_p"],
        }
    return {
        "complete": checked["complete"],
        "verified_calls": checked["verified_calls"],
        "required_calls": checked["required_calls"],
        "new_measured_cost_usd": checked["new_measured_cost_usd"],
        "new_calls_with_unknown_cost": checked["new_calls_with_unknown_cost"],
        "failed_call_count": checked["failed_call_count"],
        "cells": cells,
        "primary_holm_adjusted_p": derived["primary_holm_adjusted_p"],
        # Project-relative, so the analysis regenerates identically from any extraction.
        "provenance": [{**item, "path": str(Path(item["path"]).relative_to(HERE.parent))}
                       for item in checked["provenance"]],
    }


def build_round2_analysis() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    verify_frozen_contract(manifest)
    split = manifest["held_out_order"]
    studies = {cell["model"]: _audited_study(cell, split) for cell in STUDY_CELLS}
    defense_results = {
        cell["model"]: _audited_defense(cell) for cell in DEFENSE_CELLS
    }
    completion_scenarios = _completion_scenarios()
    regression = model_order_regression(
        {
            model: study["model_order_panel_choices"]
            for model, study in studies.items()
        },
        target=protocol.fixtures()["tree4"]["target"],
        bootstrap_repetitions=2000,
        seed=manifest["regression"]["seed"],
    )
    total_study_cost = sum(
        study["audit"]["known_cost_usd"] for study in studies.values()
    )
    total_defense_cost = sum(
        defense["totals"]["known_cost_usd"] for defense in defense_results.values()
    )
    return {
        "schema_version": 1,
        "round_id": manifest["round_id"],
        "classification": "historical_heterogeneous_reasoning_sensitivity",
        "source": "immutable_raw_jsonl",
        "study_models": studies,
        "completion_scenarios": completion_scenarios,
        "model_by_order_regression": regression,
        "defense_models": defense_results,
        "costs": {
            "study_known_cost_usd": total_study_cost,
            "defense_known_cost_usd": total_defense_cost,
            "overall_known_cost_usd": total_study_cost + total_defense_cost,
        },
        "qualifications": [
            "Terra and Claude use historical reasoning=none cells; they are sensitivity evidence.",
            "The split-half order analysis is exploratory and descriptive with five evaluation pairs.",
            "Randomized and invariant defenses permitted only A/B/C, so zero recorded abstention "
            "is structural rather than behavioral.",
            "Inference elapsed time excludes unlogged transient retry/backoff waits and all "
            "simulated arrival delays.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_round2_analysis()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print(f"wrote {args.output}")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
