"""Regenerate the post hoc Experiment C defense analysis from strict raw JSONL.

No model/network calls occur here. A cell is analysed only after the C auditor
has validated all 180 fresh jobs and every prompt, vote, summary reuse, cost,
and scientific identity. Partial cells need an explicit status report elsewhere;
their observed subset is never silently promoted to a six-arm comparison.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median

import audit_experiment_c_v1 as strict_audit
import experiment_c_protocol_v1 as protocol
import experiment_c_selection_v1 as selection_rules
import verify_experiment_c_collection_v1 as collection


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = "chronos.experiment-c-analysis.v1"
CHOICES = ("A", "B", "C", "ABSTAIN")
PRIMARY_MODELS = (
    "openai/gpt-5.6-terra",
    "google/gemini-3.6-flash",
    "qwen/qwen3-235b-a22b-instruct-2507",
)
SENSITIVITY_MODEL = "anthropic/claude-sonnet-4-6@default"


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _job_id(event: dict) -> str | None:
    return event.get("job_id") or (event.get("job") or {}).get("id")


def _finite_nonnegative(value, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid {label}")
    return float(value)


def _distribution(choices: list[str]) -> dict:
    if len(choices) != 30 or any(choice not in CHOICES for choice in choices):
        raise ValueError("each C arm needs 30 valid decisions")
    counts = Counter(choices)
    coverage = (30 - counts["ABSTAIN"]) / 30
    return {
        "choice_counts": {choice: counts[choice] for choice in CHOICES},
        "choice_proportions": {choice: counts[choice] / 30 for choice in CHOICES},
        "target_C_rate_all_decisions": counts["C"] / 30,
        "target_C_rate_given_coverage": counts["C"] / (30 - counts["ABSTAIN"]) if coverage else None,
        "coverage": coverage,
        "recorded_abstentions": counts["ABSTAIN"],
    }


def _tv(left: dict, right: dict) -> float:
    return 0.5 * math.fsum(abs(left["choice_proportions"][choice] - right["choice_proportions"][choice]) for choice in CHOICES)


def _summary(values: list[float | None]) -> dict:
    known = [value for value in values if value is not None]
    return {
        "mean": mean(known) if known else None,
        "median": median(known) if known else None,
        "known_decisions": len(known),
        "missing_decisions": len(values) - len(known),
    }


def _telemetry(jobs: list[dict], calls: dict[str, list[dict]]) -> dict:
    per_job_elapsed, per_job_backend = [], []
    all_calls = [event for job in jobs for event in calls[job["id"]]]
    failed = [event for event in all_calls if event["event"] == "call_failed"]
    costs = [_finite_nonnegative(event.get("cost_usd"), "call cost") for event in all_calls]
    failed_costs = [_finite_nonnegative(event.get("cost_usd"), "failed-call cost") for event in failed]
    missing_elapsed_calls, missing_backend_calls = 0, 0
    for job in jobs:
        call_events = calls[job["id"]]
        elapsed = [_finite_nonnegative(event.get("elapsed_seconds"), "inference elapsed time") for event in call_events]
        backend = [_finite_nonnegative((event.get("usage") or {}).get("total_backend_latency_ms"), "backend latency") for event in call_events]
        missing_elapsed_calls += sum(value is None for value in elapsed)
        missing_backend_calls += sum(value is None for value in backend)
        per_job_elapsed.append(math.fsum(elapsed) if all(value is not None for value in elapsed) else None)
        per_job_backend.append(math.fsum(backend) / 1000 if all(value is not None for value in backend) else None)
    planned = sum(job["calls"] for job in jobs)
    return {
        "planned_calls_per_decision": jobs[0]["calls"],
        "planned_calls_total": planned,
        "observed_provider_invocations": len(all_calls),
        "extra_observed_invocations_vs_plan": len(all_calls) - planned,
        "failed_provider_invocations": len(failed),
        "known_cost_usd_all_attempts": math.fsum(value for value in costs if value is not None),
        "known_cost_usd_failed_attempts": math.fsum(value for value in failed_costs if value is not None),
        "unknown_cost_calls": sum(value is None for value in costs),
        "charged_failed_calls": sum(value is not None and value > 0 for value in failed_costs),
        "inference_elapsed_seconds_per_decision": _summary(per_job_elapsed),
        "inference_elapsed_missing_calls": missing_elapsed_calls,
        "backend_latency_seconds_per_decision": _summary(per_job_backend),
        "backend_latency_missing_calls": missing_backend_calls,
    }


def _vote_detail(trials: list[dict]) -> dict:
    top_counts, unanimous = [], 0
    for trial in trials:
        counts = trial["final"]["vote_counts"]
        top = max(counts.values())
        top_counts.append(top)
        unanimous += top == 24
    return {
        "independent_permutation_decisions_per_repetition": 24,
        "supermajority_threshold": 16,
        "winning_vote_count_mean": mean(top_counts),
        "winning_vote_count_median": median(top_counts),
        "winning_vote_count_distribution": {str(count): top_counts.count(count) for count in sorted(set(top_counts))},
        "unanimous_repetitions": unanimous,
        "abstained_repetitions": sum(trial["final"]["final_choice"] == "ABSTAIN" for trial in trials),
    }


def _reverse_detail(trials: list[dict], model: str) -> dict:
    if model not in protocol.REVERSE_MODELS:
        if any(trial.get("reverse_final") is not None for trial in trials):
            raise ValueError("unplanned reverse synthesis recorded")
        return {"status": "not_planned_for_this_setting"}
    pairs = [(trial["final"]["final_choice"], trial["reverse_final"]["final_choice"]) for trial in trials]
    return {
        "status": "planned_and_audited_same_four_summaries",
        "repetitions": len(pairs),
        "forward_reverse_disagreements": sum(forward != reverse for forward, reverse in pairs),
        "forward_reverse_agreement_rate": sum(forward == reverse for forward, reverse in pairs) / len(pairs),
        "forward_target_C_rate": sum(forward == "C" for forward, _ in pairs) / len(pairs),
        "reverse_target_C_rate": sum(reverse == "C" for _, reverse in pairs) / len(pairs),
        "forward_C_reverse_not_C": sum(forward == "C" and reverse != "C" for forward, reverse in pairs),
        "reverse_C_forward_not_C": sum(reverse == "C" and forward != "C" for forward, reverse in pairs),
    }


def analyze_cell(events: list[dict], selection: dict, *, raw_sources: list[dict] | None = None, raw_evidence_sha256: str | None = None) -> dict:
    selection_rules.validate_selection(selection)
    model = selection["model"]
    checked = strict_audit.audit(events, model, selection, require_complete=True)
    if checked["completed_jobs"] != 180 or checked["complete_trial_calls"] != (1380 if model in protocol.REVERSE_MODELS else 1350):
        raise ValueError("Experiment C full-cell call topology changed")
    jobs = protocol.jobs_for(model, selection)
    by_arm_jobs = {arm: [job for job in jobs if job["mode"] == arm] for arm in protocol.ARMS}
    completed = {_job_id(event): event for event in events if event.get("event") == "job_complete"}
    calls: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event.get("event") in ("call_complete", "call_failed"):
            calls[_job_id(event)].append(event)
    arm_trials = {arm: [completed[job["id"]] for job in arm_jobs] for arm, arm_jobs in by_arm_jobs.items()}
    distributions = {arm: _distribution([trial["final"]["final_choice"] for trial in trials]) for arm, trials in arm_trials.items()}
    natural = distributions["undefended_natural"]
    attacked = distributions["undefended_selected_order"]
    if natural["recorded_abstentions"] or attacked["recorded_abstentions"]:
        raise ValueError("fresh undefended baseline cannot abstain")
    arms = {}
    for arm in protocol.ARMS:
        trials = arm_trials[arm]
        distribution = distributions[arm]
        if arm != "order_consistency_24" and distribution["recorded_abstentions"]:
            raise ValueError("only the 24-order vote may abstain")
        distribution["abstention_permitted"] = arm == "order_consistency_24"
        telemetry = _telemetry(by_arm_jobs[arm], calls)
        arms[arm] = {
            "repetitions": 30,
            **distribution,
            "defense_efficacy_target_C_reduction_pp_vs_selected_attack": 100 * (attacked["target_C_rate_all_decisions"] - distribution["target_C_rate_all_decisions"]),
            "utility_total_variation_vs_fresh_natural": _tv(distribution, natural),
            "telemetry": telemetry,
            "choices_by_repetition": [trial["final"]["final_choice"] for trial in trials],
        }
    arms["order_consistency_24"]["vote"] = _vote_detail(arm_trials["order_consistency_24"])
    arms["invariant"]["reverse_synthesis"] = _reverse_detail(arm_trials["invariant"], model)
    planned = sum(arm["telemetry"]["planned_calls_total"] for arm in arms.values())
    observed = sum(arm["telemetry"]["observed_provider_invocations"] for arm in arms.values())
    cost = math.fsum(arm["telemetry"]["known_cost_usd_all_attempts"] for arm in arms.values())
    failed_cost = math.fsum(arm["telemetry"]["known_cost_usd_failed_attempts"] for arm in arms.values())
    if planned != checked["complete_trial_calls"] or observed != checked["observed_invocations"] or not math.isclose(cost, checked["known_cost_usd"], rel_tol=0, abs_tol=1e-10):
        raise ValueError("C analysis and strict raw audit disagree on call or cost accounting")
    body = {
        "schema": SCHEMA,
        "model": model,
        "reasoning": selection["reasoning"],
        "role": selection["role"],
        "classification": "post_hoc_worst_case_defense_stress_test",
        "source_tree_log_sha256": selection["source_log_sha256"],
        "selection_manifest_sha256": selection["selection_manifest_sha256"],
        "selected_condition_index": selection["selected_condition_index"],
        "selected_order": selection["selected_order"],
        "raw_c_evidence_sources": raw_sources,
        "raw_c_evidence_sha256": raw_evidence_sha256,
        "audit": checked,
        "arms": arms,
        "totals": {
            "completed_decisions": 180,
            "planned_calls": planned,
            "observed_provider_invocations": observed,
            "failed_provider_invocations": checked["failed_calls"],
            "known_cost_usd_all_attempts": cost,
            "known_cost_usd_failed_attempts": failed_cost,
            "unknown_cost_calls": checked["unknown_cost_calls"],
        },
        "interpretation_limits": [
            "The strongest order was chosen post hoc from the full tree-study panel; this is a stress test, not an independent order-selection confirmation.",
            "Efficacy is unconditional target-C reduction versus the same fresh selected-order arm; coverage is reported separately for vote abstentions.",
            "Utility is total-variation distance from the same run's fresh undefended-natural choice distribution, not objective decision correctness.",
            "Inference elapsed and backend latency exclude simulated arrival delay; missing telemetry is never treated as zero.",
        ],
    }
    return {**body, "analysis_sha256": _canonical_hash(body)}


def analyze_files(selection_path: Path, evidence_paths: list[Path], *, root: Path = ROOT) -> dict:
    selection = json.loads(selection_path.read_text())
    selection_rules.verify_selection_source(selection, root=root)
    if not evidence_paths or len(evidence_paths) != len(set(evidence_paths)):
        raise ValueError("C evidence files must be nonempty and unique")
    parts = []
    for path in evidence_paths:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root.resolve()).as_posix()
        raw = resolved.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError(f"C raw evidence is empty or not newline terminated: {relative}")
        parts.append((relative, raw))
    parts.sort(key=lambda item: item[0])
    sources = [{"path": relative, "sha256": _hash(raw), "bytes": len(raw)} for relative, raw in parts]
    events = []
    for relative, raw in parts:
        for number, line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid C JSONL {relative}:{number}") from error
            if not isinstance(event, dict):
                raise ValueError(f"nonobject C event {relative}:{number}")
            events.append(event)
    return analyze_cell(
        collection._normalize_consistency_transport(events), selection,
        raw_sources=sources, raw_evidence_sha256=_hash(b"".join(raw for _, raw in parts)))


def verify_analysis_file(path: Path, selection_path: Path, evidence_paths: list[Path]) -> dict:
    saved = json.loads(path.read_text())
    regenerated = analyze_files(selection_path, evidence_paths)
    if saved != regenerated:
        raise ValueError("C analysis differs from fresh strict raw regeneration")
    return regenerated


def combine_cells(cells: list[dict]) -> dict:
    by_model = {cell["model"]: cell for cell in cells}
    if len(by_model) != len(cells) or set(by_model) != set(PRIMARY_MODELS) | {SENSITIVITY_MODEL}:
        raise ValueError("full C report requires three primary settings and Claude-none sensitivity")
    for cell in cells:
        body = {key: value for key, value in cell.items() if key != "analysis_sha256"}
        if cell.get("schema") != SCHEMA or cell.get("analysis_sha256") != _canonical_hash(body):
            raise ValueError("C cell analysis hash changed")
        if selection_rules.ROSTER.get((cell["model"], cell["reasoning"])) != cell["role"]:
            raise ValueError("C inferential role changed")
    body = {
        "schema": "chronos.experiment-c-four-setting-report.v1",
        "classification": "post_hoc_worst_case_defense_stress_test",
        "matched_non_off_primary": {model: by_model[model] for model in PRIMARY_MODELS},
        "unavailable_matched_primary": {"model": SENSITIVITY_MODEL, "reasoning": "non_off_unavailable", "status": "operationally_unavailable"},
        "claude_none_sensitivity": by_model[SENSITIVITY_MODEL],
        "model_pooling": "none",
    }
    return {**body, "report_sha256": _canonical_hash(body)}


def combine_verified_cells(specs: list[dict]) -> dict:
    """Build the four-setting report only from fresh raw-regenerated cells.

    Each spec has ``analysis_path``, ``selection_path``, and ``evidence_paths``.
    A saved self-hash alone is not accepted as evidence for the final report.
    """
    cells = [
        verify_analysis_file(
            Path(spec["analysis_path"]),
            Path(spec["selection_path"]),
            [Path(path) for path in spec["evidence_paths"]],
        )
        for spec in specs
    ]
    return combine_cells(cells)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("choose --output or --verify")
    result = verify_analysis_file(args.verify, args.selection, args.evidence) if args.verify else analyze_files(args.selection, args.evidence)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {args.output} {result['analysis_sha256']}")
    elif args.verify:
        print(f"PASS Experiment C analysis {result['analysis_sha256']}")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
