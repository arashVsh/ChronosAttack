"""Analyse Experiments D/F from raw ledgers: each three-observation variant's 6-order panel
against the same cell's four-observation 24-order panel. Exploratory and descriptive.
Plan: specs/journal-extension-sep14/round2-df-leave-one-out-plan-2026-10-08.md."""

from collections import Counter, defaultdict
from itertools import permutations
import hashlib
import json
import math
from pathlib import Path
import random

import audit_experiment_df as auditor
import experiment_df_protocol as protocol
from round2_shards import counted_audits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = HERE / "round2_runs_20260920" / "experiment_df_study"
OUT = HERE / "round2_analysis" / "experiment_df_analysis_v1.json"
SHORT = {"openai/gpt-5.6-terra": "terra", "google/gemini-3.6-flash": "gemini",
         "qwen/qwen3-235b-a22b-instruct-2507": "qwen", "anthropic/claude-sonnet-4-6@default": "claude"}
TARGET = "C"
NULL_REPETITIONS, NULL_SEED = 999, 20260909
TREE4 = protocol.tree.fixtures()["tree4"]
TREE4_ORDERS = [list(o) for o in permutations(TREE4["natural"])]


def entropy(choices):
    counts, n = Counter(choices), len(choices)
    return -sum(c / n * math.log2(c / n) for c in counts.values()) if n else 0.0


def information(panels):
    """Plug-in mutual information between order (column) and choice, over complete panels (rows)."""
    k = len(panels[0])
    marginal = entropy([c for row in panels for c in row])
    conditional = sum(entropy([row[i] for row in panels]) for i in range(k)) / k
    return max(0.0, marginal - conditional)


def order_information(panels):
    observed = information(panels)
    rng, exceeds, null = random.Random(NULL_SEED), 0, []
    for _ in range(NULL_REPETITIONS):
        value = information([rng.sample(row, len(row)) for row in panels])
        null.append(value)
        exceeds += value >= observed - 1e-12
    return {"bits": observed, "null_mean_bits": sum(null) / len(null),
            "excess_bits": observed - sum(null) / len(null),
            "p_raw": (exceeds + 1) / (NULL_REPETITIONS + 1), "panels": len(panels), "orders": len(panels[0])}


def summarize(panels, orders, natural, attack):
    """panels: list of rows, each a list of choices in ``orders`` order."""
    k = len(orders)
    rates = [sum(row[i] == TARGET for row in panels) / len(panels) for i in range(k)]
    worst, best = max(range(k), key=lambda i: (rates[i], -i)), min(range(k), key=lambda i: (rates[i], i))
    return {
        "panels": len(panels),
        "target_rate_overall": sum(rates) / k,
        "choice_counts": dict(Counter(c for row in panels for c in row)),
        "target_rate_by_order": [{"order": orders[i], "target_rate": rates[i]} for i in range(k)],
        "natural_order_target_rate": rates[orders.index(natural)],
        "attack_order_target_rate": rates[orders.index(attack)],
        "max_order": {"order": orders[worst], "target_rate": rates[worst]},
        "min_order": {"order": orders[best], "target_rate": rates[best]},
        "target_rate_range": rates[worst] - rates[best],
        "orders_with_any_target": sum(r > 0 for r in rates),
        "order_information": order_information(panels),
    }


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def df_cell(model):
    """Decisions from every passed shard ledger; the passed attempt is the only one used."""
    decisions, sources = {}, []
    for audit_path in counted_audits(RUNS / SHORT[model]):
        ledger = audit_path.parent / (model.replace("/", "_") + ".jsonl")
        events = [json.loads(line) for line in ledger.read_text().splitlines()]
        checked = auditor.audit(events, model, require_complete=False)
        for d in checked["decisions"]:
            if d["job_id"] in decisions:
                raise ValueError("A job completed in two passed shard ledgers")
            decisions[d["job_id"]] = d
        sources.append({"path": str(ledger.relative_to(ROOT)), "sha256": _sha(ledger),
                        "known_cost_usd": checked["known_cost_usd"], "observed_invocations": checked["observed_invocations"],
                        "failed_calls": checked["failed_calls"]})
    fixtures = protocol.fixtures()
    variants = {}
    for scenario, fixture in fixtures.items():
        orders = [list(o) for o in permutations(fixture["natural"])]
        by_rep = defaultdict(dict)
        for d in decisions.values():
            if d["scenario"] == scenario:
                by_rep[d["rep"]][int(d["condition"])] = d["choice"]
        panels = [[row[i] for i in range(6)] for _, row in sorted(by_rep.items()) if len(row) == 6]
        variants[scenario] = ({"removed": fixture["removed"], "complete": len(panels) == protocol.REPETITIONS,
                               **summarize(panels, orders, fixture["natural"], fixture["attack"])}
                              if panels else {"removed": fixture["removed"], "complete": False, "panels": 0})
    return {"completed_jobs": len(decisions), "planned_jobs": 240, "sources": sources,
            "known_cost_usd": sum(s["known_cost_usd"] for s in sources), "variants": variants}


def tree4_panels(model):
    """The cell's four-observation 24-order stateful panels (10 repetitions)."""
    if model == "openai/gpt-5.6-terra":  # matched Terra-low collection of 2026-09-20
        collection = json.loads((HERE / "round2_generated" / "terra_study_collection_v1.json").read_text())
        by_rep, sources = defaultdict(dict), []
        for shard in collection["shards"]:
            path = ROOT / shard["artifacts"]["evidence"]["path"]
            if _sha(path) != shard["artifacts"]["evidence"]["sha256"]:
                raise ValueError("Terra-low ledger changed")
            sources.append({"path": shard["artifacts"]["evidence"]["path"], "sha256": shard["artifacts"]["evidence"]["sha256"]})
            for line in path.read_text().splitlines():
                event = json.loads(line)
                if event["event"] == "job_complete" and event["job"]["mode"] == "permutation_stateful":
                    by_rep[event["job"]["rep"]][int(event["job"]["condition"])] = event["final"]["final_choice"]
        panels = [[row[i] for i in range(24)] for _, row in sorted(by_rep.items()) if len(row) == 24]
        return panels, {"source": "terra_study_collection_v1.json (Terra-low, 2026-09-20)", "ledgers": sources}
    analysis = json.loads((HERE / "round2_analysis" / "analysis.json").read_text())
    cell = analysis["study_models"][model]
    panels = [row for _, row in sorted(cell["model_order_panel_choices"].items(), key=lambda kv: int(kv[0]))]
    return panels, {"source": "round2_analysis/analysis.json", "reasoning": cell["reasoning"],
                    "ledger": cell["provenance"]}


def analyze():
    result = {"schema": "chronos.experiment-df-analysis.v1", "classification": "exploratory_descriptive",
              "plan": "specs/journal-extension-sep14/round2-df-leave-one-out-plan-2026-10-08.md",
              "null": {"repetitions": NULL_REPETITIONS, "seed": NULL_SEED}, "models": {}}
    for model in SHORT:
        panels, provenance = tree4_panels(model)
        if len(panels) != 10:
            raise ValueError(f"Expected ten complete 24-order panels for {model}")
        result["models"][model] = {
            "cell": protocol.cell(model),
            "four_observations": {**summarize(panels, TREE4_ORDERS, TREE4["natural"], TREE4["attack"]),
                                  "provenance": provenance},
            "three_observations": df_cell(model),
        }
    return result


if __name__ == "__main__":
    result = analyze()
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for model, cell in result["models"].items():
        four = cell["four_observations"]
        print(SHORT[model], "4-obs", f"{four['order_information']['bits']:.2f}b",
              f"null {four['order_information']['null_mean_bits']:.2f}", f"range {four['target_rate_range']:.0%}",
              "| 3-obs jobs", cell["three_observations"]["completed_jobs"])
