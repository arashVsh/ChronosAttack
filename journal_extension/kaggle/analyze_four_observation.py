"""Prespecified descriptive analysis of audited, complete trial records.

Partial runs are never silently treated as a complete matrix. Entropy association
tests use complete 24-order panels and retain panel membership under the null.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random

from audit_four_observation import audit
import four_observation_protocol as protocol


def entropy(choices):
    counts = Counter(choices)
    n = sum(counts.values())
    return -sum((c/n) * math.log2(c/n) for c in counts.values()) if n else None


def disagreement(choices):
    n = len(choices)
    return 1 - sum(c*(c-1) for c in Counter(choices).values())/(n*(n-1)) if n > 1 else None


def interval(values):
    """Deterministic percentile bootstrap over independent pairs/panels."""
    if len(values) < 2:
        return None
    rng = random.Random(20260909)
    means = sorted(sum(rng.choices(values, k=len(values)))/len(values) for _ in range(2000))
    return [means[49], means[1949]]


def wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    rate = successes/n
    denominator = 1 + z*z/n
    middle = (rate + z*z/(2*n))/denominator
    radius = z*math.sqrt(rate*(1-rate)/n + z*z/(4*n*n))/denominator
    return [max(0.0, middle-radius), min(1.0, middle+radius)]


def holm(p_values):
    """Correct one explicitly named family; leave missing tests as missing."""
    ordered = sorted((p, name) for name, p in p_values.items() if p is not None)
    adjusted, previous = {name: None for name in p_values}, 0.0
    for index, (p, name) in enumerate(ordered):
        previous = max(previous, min(1.0, (len(ordered)-index)*p))
        adjusted[name] = previous
    return adjusted


def paired_test(natural, attacked):
    require = len(natural) == len(attacked)
    if not require:
        raise ValueError("Mismatched paired observations")
    gain = sum(not n and a for n, a in zip(natural, attacked))
    loss = sum(n and not a for n, a in zip(natural, attacked))
    discordant = gain + loss
    p = min(1.0, 2*sum(math.comb(discordant, k) for k in range(min(gain, loss)+1))/2**discordant) if discordant else 1.0
    changes = [int(a)-int(n) for n, a in zip(natural, attacked)]
    return dict(pairs=len(changes), gains=gain, losses=loss,
                target_rate_change=sum(changes)/len(changes) if changes else None,
                bootstrap_95=interval(changes), exact_p_raw=p if len(changes) >= 2 else None)


def panel_analysis(trials, target, null_repetitions=999):
    by_rep = defaultdict(dict)
    for trial in trials:
        by_rep[trial["job"]["rep"]][int(trial["job"]["condition"])] = trial
    complete = [panel for _, panel in sorted(by_rep.items()) if set(panel) == set(range(24))]
    if not complete:
        return dict(complete_panels=0, incomplete_panels=len(by_rep))
    labels = [[panel[i]["final"]["final_choice"] for i in range(24)] for panel in complete]

    def information(matrix):
        marginal = entropy([c for row in matrix for c in row])
        conditional = sum(entropy([row[i] for row in matrix]) for i in range(24))/24
        return marginal, conditional, max(0.0, marginal-conditional)

    h, conditional, mutual = information(labels)
    p = None
    if len(labels) >= 2:
        rng, exceeds = random.Random(20260909), 0
        for _ in range(null_repetitions):
            shuffled = [rng.sample(row, len(row)) for row in labels]
            exceeds += information(shuffled)[2] >= mutual - 1e-12
        p = (exceeds+1)/(null_repetitions+1)
    position = {}
    for tool in protocol.fixtures()["tree4"]["natural"]:
        position[tool] = {}
        for choice in protocol.engine.CHOICES:
            rates = [[sum(t["final"]["final_choice"] == choice for t in panel.values()
                          if t["job"]["order"][pos] == tool)/6 for pos in range(4)] for panel in complete]
            differences = [row[3]-row[0] for row in rates]
            position[tool][choice] = dict(rates_by_position=[sum(row[i] for row in rates)/len(rates) for i in range(4)],
                                         last_minus_first=sum(differences)/len(differences),
                                         panel_bootstrap_95=interval(differences))
    votes = [protocol.consistency_vote(row) for row in labels]
    answered = [v for v in votes if v != "ABSTAIN"]
    return dict(complete_panels=len(complete), incomplete_panels=len(by_rep)-len(complete),
                choice_counts=dict(Counter(c for row in labels for c in row)),
                entropy_bits=h, normalized_entropy=h/math.log2(3),
                mean_within_order_entropy_bits=conditional, order_information_bits=mutual,
                order_association_p_raw=p, null_repetitions=null_repetitions if p is not None else 0,
                within_order_disagreement=[disagreement([row[i] for row in labels]) for i in range(24)],
                between_order_disagreement_by_panel=[disagreement(row) for row in labels],
                position_associations=position,
                # Only interpret these as a defense for the consistency mode.
                two_thirds_consensus_counts=dict(Counter(votes)),
                consensus_coverage=len(answered)/len(votes),
                consensus_target_unconditional=sum(v == target for v in votes)/len(votes),
                consensus_target_given_answer=sum(v == target for v in answered)/len(answered) if answered else None)


def analyze(events, model, phase, audit_fn=audit):
    checked = audit_fn(events, model, phase, require_complete=False)
    trials = [e for e in events if e["event"] == "job_complete"]
    target = protocol.fixtures()["tree4"]["target"]
    groups = defaultdict(list)
    for trial in trials:
        groups[(trial["job"]["mode"], trial["job"]["condition"])].append(trial)
    cells = {"|".join(key): dict(n=len(rows), choices=dict(Counter(r["final"]["final_choice"] for r in rows)),
                                  target_rate_wilson_95=wilson(sum(r["final"]["final_choice"] == target for r in rows), len(rows)),
                                  target_rate=sum(r["final"]["final_choice"] == target for r in rows)/len(rows))
             for key, rows in sorted(groups.items())}
    pairs = {}
    for mode in ("stateful", "stateless"):
        n = {t["job"]["rep"]: t["final"]["final_choice"] == target for t in groups[(mode, "natural")]}
        a = {t["job"]["rep"]: t["final"]["final_choice"] == target for t in groups[(mode, "attack")]}
        shared = sorted(set(n) & set(a))
        pairs[mode] = paired_test([n[r] for r in shared], [a[r] for r in shared])
    revisions = defaultdict(list)
    for trial in trials:
        if not trial["states"]:
            continue
        path = [s["state"]["current_choice"] for s in trial["states"]] + [trial["final"]["final_choice"]]
        changes = [a != b for a, b in zip(path, path[1:])]
        revisions[trial["job"]["mode"]].append(dict(job_id=trial["job"]["id"], choices=path,
            transition_changes=sum(changes), final_equals_first=path[-1] == path[0],
            never_revised=not any(changes), returned_to_first=any(changes) and path[-1] == path[0],
            first_departure_step=next((i for i, c in enumerate(path[1:], 2) if c != path[0]), None),
            final_synthesis_changed=changes[-1]))
    panels = {mode: panel_analysis([t for t in trials if t["job"]["mode"] == mode], target)
              for mode in ("consistency", "permutation_stateful")}
    return dict(audit=checked, cells=cells, primary_pairs=pairs, panels=panels, revision_records=revisions,
                caveats=["Pilot data are excluded from confirmation.",
                         "Incomplete panels are excluded from panel metrics and counted explicitly.",
                         "Entropy includes sampling noise; order information is finite-sample biased.",
                         "Position contrasts are exploratory with pointwise, not simultaneous intervals.",
                         "Raw p-values require family-wide multiplicity correction before confirmatory claims.",
                         "Consensus is a defense only in the defense-instructed consistency condition."])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--phase", choices=("pilot", "study"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze([json.loads(x) for x in args.path.read_text().splitlines()], args.model, args.phase)
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded)
