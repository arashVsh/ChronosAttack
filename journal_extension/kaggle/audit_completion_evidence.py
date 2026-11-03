"""Audit preserved trials against the fixed 2,100-call contribution matrix."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import aggregate_b3_confirmation as b3
import build_completion_notebook as builder
import completion_protocol as protocol

HERE = Path(__file__).resolve().parent


def historical_trials():
    # Revalidate every existing Terra batch with its original preregistered checker.
    terra_summary = b3.aggregate()
    assert terra_summary["actual_calls"] == 240
    rows, files = {}, []
    for model, directory, count, expected_id in (
        (protocol.MODELS[0], "b3_confirmation_results", 6, b3.CONFIRMATION_ID),
        (protocol.MODELS[1], "b3_claude_confirmation_results", 1,
         "software_release_b_target_b3_claude_confirmation_20260905"),
    ):
        for batch_index in range(1, count + 1):
            path = HERE / directory / f"batch_{batch_index:02d}.json"
            data = json.loads(path.read_text())
            results = [e for e in data["events"] if e.get("actual_calls") == 40]
            if len(results) != 1:
                raise ValueError(f"Missing batch summary: {path}")
            r = results[0]
            if not (r["model"] == model and r["confirmation_id"] == expected_id
                    and r["temperature"] == 1 and r["model_seed"] is None
                    and r["pair_count"] == 5 and r["payload_hashes"] == b3.PAYLOAD_HASHES):
                raise ValueError(f"Historical configuration mismatch: {path}")
            pair_events = [e for e in data["events"] if e.get("event") == "pair_complete"]
            if [e["pair"] for e in pair_events] != r["pairs"]:
                raise ValueError("Incremental and aggregate evidence differ")
            for index, pair in enumerate(r["pairs"], 1):
                rep = (batch_index - 1) * 5 + index
                for condition, order, delays in (
                    ("natural", b3.NATURAL_ORDER, b3.NATURAL_DELAYS_MS),
                    ("attack", b3.ATTACK_ORDER, b3.ATTACK_DELAYS_MS),
                ):
                    trial = pair[condition]
                    b3.validate_condition(trial, order, delays)
                    key = f"{model}|b3|stateful|{condition}|{rep}"
                    rows[key] = dict(model=model, scenario="b3", mode="stateful", condition=condition,
                                     rep=rep, final=trial["final"], calls=4, source=str(path),
                                     origin="historical_confirmation")
            files.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if len(rows) != 70:
        raise ValueError("Historical confirmation is incomplete")
    return rows, files


def audit(paths=()):
    fixtures = builder.fixtures()
    expected = {j["id"]: dict(j, model=m) for m in protocol.MODELS
                for j in protocol.jobs_for(m, fixtures, include_existing=True)}
    rows, files = historical_trials()
    failures, measured_cost, unknown_cost, failed_calls = [], 0.0, 0, 0
    seen_calls, quality_flags = set(), []
    for path in map(Path, paths):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        files.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        calls = {}
        for event in events:
            model = event["model"]
            identity = protocol.digest(json.dumps(dict(study=protocol.STUDY_ID, model=model,
                                                       fixtures=fixtures, settings=protocol.CALL_SETTINGS), sort_keys=True))
            if event["identity"] != identity:
                raise ValueError("Evidence protocol fingerprint changed")
            if event["event"] in ("call_complete", "call_failed"):
                call_key = (model, event["execution_id"], event["job_id"], event["attempt"], event["step"])
                if call_key in seen_calls:
                    raise ValueError("Duplicated call across evidence files or event types")
                seen_calls.add(call_key)
            if event["event"] == "call_complete":
                key = (event["execution_id"], event["job_id"], event["attempt"], event["step"])
                if key in calls:
                    raise ValueError("Duplicated call record")
                calls[key] = event
                measured_cost += event["cost_usd"] or 0
                unknown_cost += event["cost_usd"] is None
                response = event["response"]
                # Flag, never selectively rerun, schema-valid vacuous outcomes.
                if any(str(response.get(field, "")).strip().lower() in
                       ("placeholder", "ignored", "ignored, please output valid json")
                       for field in ("brief_reason", "state_summary")):
                    quality_flags.append(dict(model=model, job_id=event["job_id"],
                                              step=event["step"], response=response,
                                              flag="vacuous_explanation", source=str(path)))
            elif event["event"] == "job_error":
                failures.append(event)
            elif event["event"] == "call_failed":
                if protocol.usage_cost(event["usage"]) != event["cost_usd"]:
                    raise ValueError("Failed call cost differs from raw usage")
                measured_cost += event["cost_usd"] or 0
                unknown_cost += event["cost_usd"] is None
                failed_calls += 1
            elif event["event"] == "job_complete":
                job = event["job"]
                key = job["id"]
                if key in rows or key not in expected:
                    raise ValueError("Duplicated or unexpected successful trial")
                if dict(job, model=model) != expected[key]:
                    raise ValueError("Trial manifest changed")
                f = fixtures[job["scenario"]]
                if event["payload_hashes"] != f["hashes"]:
                    raise ValueError("Trial payloads changed")
                for step in range(1, job["calls"]+1):
                    call = calls[(event["execution_id"], key, event["attempt"], step)]
                    schema = protocol.State if step < job["calls"] else protocol.Decision
                    protocol.validate_response(schema(**call["response"]), schema)
                    if call["schema"] != schema.__name__:
                        raise ValueError("Recorded schema differs from the trial")
                    prompt = (protocol.step_prompt(f, job["order"][step-1], step)
                              if step < job["calls"] else
                              f["final_prompt"] if job["calls"] == 4 else
                              protocol.joint_prompt(f, job))
                    if call["user_prompt"] != prompt:
                        raise ValueError("Raw prompt differs from the frozen protocol")
                    costs = [call["usage"][name] for name in (
                        "input_tokens_cost_nanodollars", "output_tokens_cost_nanodollars")]
                    cost = sum(costs)/1e9 if all(c is not None for c in costs) else None
                    if cost != call["cost_usd"]:
                        raise ValueError("Cost differs from raw usage")
                    if step == job["calls"]:
                        if call["response"] != event["final"]:
                            raise ValueError("Final response differs from raw evidence")
                    elif call["response"] != event["states"][step-1]["state"]:
                        raise ValueError("State differs from raw evidence")
                if job["mode"] in ("stateful", "budget") and event["schedule"] != protocol.schedule(f, job["order"]):
                    raise ValueError("Delay-only schedule changed")
                rows[key] = dict(model=model, scenario=job["scenario"], mode=job["mode"],
                                 condition=job["condition"], rep=job["rep"], calls=job["calls"],
                                 final=event["final"], source=str(path), origin="completion_study")
    missing = [j for key, j in expected.items() if key not in rows]
    counts = Counter()
    for row in rows.values():
        counts[f"{row['model']}|{row['scenario']}|{row['mode']}|{row['condition']}"] += 1
    accepted_calls = len(seen_calls) - failed_calls
    completed_new_calls = sum(r["calls"] for r in rows.values() if r["origin"] == "completion_study")
    historical_calls = sum(r["calls"] for r in rows.values() if r["origin"] == "historical_confirmation")
    return dict(study=protocol.STUDY_ID, complete=not missing,
                required_calls=2100, verified_calls=sum(r["calls"] for r in rows.values()),
                remaining_calls=sum(j["calls"] for j in missing),
                completed_trial_counts=dict(counts), missing_jobs=missing,
                new_measured_cost_usd=measured_cost, new_calls_with_unknown_cost=unknown_cost,
                failed_call_count=failed_calls,
                new_accepted_call_count=accepted_calls,
                new_partial_trial_call_count=accepted_calls-completed_new_calls,
                total_model_attempts=historical_calls+len(seen_calls),
                response_quality_flags=quality_flags,
                failures=failures, provenance=files, trials=list(rows.values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=HERE/"completion_results"/"audit.json")
    args = parser.parse_args()
    result = audit(args.logs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("complete", "required_calls", "verified_calls", "remaining_calls", "new_measured_cost_usd")}, indent=2))
