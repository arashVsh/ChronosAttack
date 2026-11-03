"""Descriptive and fixed-sample inference from audited trials, never raw guesses."""

import argparse
from collections import Counter
import json
from pathlib import Path

from aggregate_b3_confirmation import exact_mcnemar_p, wilson_interval
import completion_protocol as protocol


def rate(choices, target):
    n = len(choices)
    hits = choices.count(target)
    return dict(n=n, target_count=hits, rate=hits/n if n else None,
                wilson_95=wilson_interval(hits, n) if n else None,
                choices=dict(Counter(choices)))


def paired(rows, target, expected_pairs):
    conditions = {c: {r["rep"]: r["final"]["final_choice"] for r in rows
                      if r["condition"] == c} for c in ("natural", "attack")}
    shared = sorted(set(conditions["natural"]) & set(conditions["attack"]))
    natural = [conditions["natural"][rep] for rep in shared]
    attack = [conditions["attack"][rep] for rep in shared]
    positive = sum(a != target and b == target for a, b in zip(natural, attack))
    reverse = sum(a == target and b != target for a, b in zip(natural, attack))
    complete = len(shared) == expected_pairs
    return dict(pairs=len(shared), expected_pairs=expected_pairs, complete=complete,
                natural=rate(natural, target), attack=rate(attack, target),
                positive_shifts=positive, reverse_shifts=reverse,
                target_rate_difference=(positive-reverse)/len(shared) if shared else None,
                exact_mcnemar_p=exact_mcnemar_p(positive, reverse) if complete else None)


def holm(pvalues):
    result, previous = {}, 0.0
    for rank, (key, value) in enumerate(sorted(pvalues.items(), key=lambda x: x[1])):
        previous = min(1.0, max(previous, (len(pvalues)-rank)*value))
        result[key] = previous
    return result


def analyze(audit):
    cells, primary = {}, {}
    for model in protocol.MODELS:
        for sid, target in (("b3", "B"), ("c1", "C")):
            key = f"{model}|{sid}"
            rows = [r for r in audit["trials"] if r["model"] == model and r["scenario"] == sid]
            modes = {mode: [r for r in rows if r["mode"] == mode]
                     for mode in ("stateful", "stateless", "budget", "control", "barrier", "consistency")}
            stateful = paired(modes["stateful"], target, 30)
            flagged_ids = {r["job_id"] for r in audit.get("response_quality_flags", [])}
            flagged_reps = {r["rep"] for r in modes["stateful"]
                            if f"{model}|{sid}|stateful|{r['condition']}|{r['rep']}" in flagged_ids}
            sensitivity_rows = [r for r in modes["stateful"] if r["rep"] not in flagged_reps]
            if stateful["complete"]:
                primary[key] = stateful["exact_mcnemar_p"]
            panels = {}
            for r in modes["consistency"]:
                panels.setdefault(r["rep"], []).append(r["final"]["final_choice"])
            complete_panels = [choices for choices in panels.values() if len(choices) == 6]
            votes = [protocol.consistency_vote(choices) for choices in complete_panels]
            cells[key] = dict(
                target=target, stateful=stateful, stateless=paired(modes["stateless"], target, 10),
                descriptive_quality_sensitivity=dict(
                    excluded_pair_reps=sorted(flagged_reps),
                    paired=paired(sensitivity_rows, target, 30),
                    note="Post-hoc descriptive check only. Primary analysis retains all schema-valid outcomes; no selective retries."),
                budget={level: rate([r["final"]["final_choice"] for r in modes["budget"]
                                    if r["condition"] == level], target) for level in ("0", "1", "2")},
                simultaneous=rate([r["final"]["final_choice"] for r in modes["control"]], target),
                barrier=rate([r["final"]["final_choice"] for r in modes["barrier"]], target),
                consistency=dict(panels=len(complete_panels), expected_panels=10,
                                 votes=rate(votes, target), abstentions=votes.count("ABSTAIN"),
                                 disagreement_panels=sum(len(set(c)) > 1 for c in complete_panels)),
            )
    # Do not apply a smaller correction while any planned primary comparison is missing.
    corrected = holm(primary) if len(primary) == 4 else None
    return dict(complete=audit["complete"], verified_calls=audit["verified_calls"],
                required_calls=audit["required_calls"], cells=cells,
                primary_holm_adjusted_p=corrected,
                new_measured_cost_usd=audit["new_measured_cost_usd"],
                unknown_cost_calls=audit["new_calls_with_unknown_cost"],
                response_quality_flags=audit.get("response_quality_flags", []),
                interpretation="Target-choice frequency measures schedule sensitivity, not objectively correct decisions."
                " Incomplete cells are descriptive only; fixed sample sizes do not depend on significance."
                " Consistency votes use panels, not individual permutations, as the analysis unit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=Path(__file__).parent/"completion_results/audit.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent/"completion_results/analysis.json")
    args = parser.parse_args()
    result = analyze(json.loads(args.audit.read_text()))
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: result[k] for k in ("complete", "verified_calls", "required_calls", "new_measured_cost_usd")}))
