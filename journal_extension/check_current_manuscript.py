#!/usr/bin/env python3
"""Offline current-paper checks; no model calls and no scientific input writes.

Independently calculate Fisher/Holm and independent Newcombe intervals from
raw-ledger target counts. Historical analyses retain their original paired tests.
The defense figure check reconciles its literal data with the raw-derived C report;
it does not replace that report's raw-evidence verifier or a visual PDF review.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zipfile import ZipFile

sys.dont_write_bytecode = True
MODELS = {
    "GPT-5.6 Terra": "openai/gpt-5.6-terra",
    "Gemini 3.6": "google/gemini-3.6-flash",
    "Qwen3": "qwen/qwen3-235b-a22b-instruct-2507",
    "Claude 4.6": "anthropic/claude-sonnet-4-6@default",
}


def fisher(a, n_a, b, n_b):
    """Two-sided Fisher: sum tables no more probable than the observed table."""
    total, successes = n_a + n_b, a + b
    denominator = math.comb(total, n_a)
    weight = lambda x: math.comb(successes, x) * math.comb(total-successes, n_a-x)
    observed = weight(a)
    return min(1.0, sum(weight(x) for x in range(max(0, n_a-(total-successes)),
                                               min(n_a, successes)+1)
                        if weight(x) <= observed) / denominator)


def holm(values):
    adjusted, previous = {}, 0.0
    for rank, (key, value) in enumerate(sorted(values.items(), key=lambda item: item[1])):
        previous = max(previous, min(1.0, (len(values)-rank)*value))
        adjusted[key] = previous
    return adjusted


def independent_newcombe(a, n_a, b, n_b):
    """Newcombe's independent Wilson-score difference interval, attack minus natural."""
    def wilson(k, n):
        z = 1.959963984540054
        p, denominator = k/n, 1+z*z/n
        centre = (p+z*z/(2*n))/denominator
        half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
        return p, centre-half, centre+half
    pa, la, ua = wilson(a, n_a)
    pb, lb, ub = wilson(b, n_b)
    difference = pa-pb
    return [difference-math.hypot(pa-la, ub-pb),
            difference+math.hypot(ua-pa, pb-lb)]


def check(root):
    root = Path(root).resolve()
    analysis = root / "kaggle/round2_analysis"
    load = lambda name: json.loads((analysis/name).read_text())
    checked_sources = {}
    failures = []

    def jobs(sources):
        result = {}
        for source in sources:
            relative = source["path"]
            raw = (root/relative).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if source.get("sha256") and digest != source["sha256"]:
                raise ValueError("Raw evidence hash mismatch: " + relative)
            checked_sources[relative] = digest
            for line in raw.splitlines():
                event = json.loads(line)
                if event.get("event") != "job_complete":
                    continue
                job = event["job"]
                key = (event["model"], job["id"])
                row = {**job, "model": event["model"], "target": event["target"],
                       "choice": event["final"]["final_choice"]}
                if key in result and result[key] != row:
                    raise ValueError("Conflicting duplicate raw job: " + str(key))
                result[key] = row
        return list(result.values())

    def count(rows, scenario=None):
        selected = [r for r in rows if r["mode"] == "stateful"
                    and (scenario is None or r["scenario"] == scenario)]
        counts = {}
        for condition in ["natural", "attack"]:
            arm = [r for r in selected if r["condition"] == condition]
            counts[condition] = [sum(r["choice"] == r["target"] for r in arm), len(arm)]
            if len(arm) != 30:
                raise ValueError("Expected 30 independent trials: " + str((scenario, condition, len(arm))))
        return counts

    source_zip = root / "manuscript/source.zip"
    if not source_zip.is_file():
        source_zip = root / "submission/arash-package/source.zip"
    with ZipFile(source_zip) as archive:
        main = archive.read("main.tex").decode()
        defense_asset = archive.read("figures/fig_defenses.pdf")
    fixed_table = next(block for block in re.findall(r"\\begin\{table\}.*?\\end\{table\}", main, re.S)
                       if r"\label{tab:fixed}" in block)
    new_table = fixed_table.split("(b) New tasks and models", 1)[1]
    printed = {}
    for label in MODELS:
        line = next(line for line in new_table.splitlines() if line.startswith(label + " &"))
        cells = line.split(" & ")[1:]
        printed[label] = [(list(map(int, re.search(r"(\d+)\$\\to\$(\d+)", cell).groups())),
                           r"\textbf" in cell) for cell in cells]

    historical = load("analysis.json")
    low = load("terra_low_study_analysis_v1.json")
    g, a = load("experiment_g_analysis_v1.json"), load("experiment_a_analysis_v1.json")
    # Reuse the frozen original evidence auditor for its historical confirmation patches.
    sys.path.insert(0, str(root/"kaggle"))
    import audit_completion_evidence
    completion = audit_completion_evidence.audit([
        root/"kaggle/completion_results/terra_saved.jsonl",
        root/"kaggle/completion_results/claude_v3_final_preserved.jsonl",
        root/"kaggle/completion_results/claude_v4_delta_verified.jsonl",
    ])
    if not completion["complete"] or completion["verified_calls"] != 2100:
        raise ValueError("Historical completion raw audit is incomplete")
    for source in completion["provenance"]:
        checked_sources[str(Path(source["path"]).relative_to(root))] = source["sha256"]
    counts = {}
    for label, model in MODELS.items():
        if model in g["cells"]:
            release_rows = jobs(g["cells"][model]["sources"])
        else:
            release_rows = [{**r, "target": "B" if r["scenario"] == "b3" else "C",
                             "choice": r["final"]["final_choice"]}
                            for r in completion["trials"] if r["model"] == model]
        counts[label+"|release"] = count(release_rows, "b3")
        counts[label+"|microgrid"] = count(release_rows, "c1")
        tree_sources = low["study_sources"] if label == "GPT-5.6 Terra" else [historical["study_models"][model]["provenance"]]
        counts[label+"|tree"] = count(jobs(tree_sources))
        water = a["claude_none_sensitivity"] if label == "Claude 4.6" else a["matched_non_off_primary"][{
            "GPT-5.6 Terra": "terra", "Gemini 3.6": "gemini", "Qwen3": "qwen"}[label]]
        counts[label+"|water"] = count(jobs(water["provenance"]["raw_ledgers"]))
    pvalues = {key: fisher(*value["attack"], *value["natural"]) for key, value in counts.items()}
    adjusted = holm(pvalues)
    tests = []
    for label in MODELS:
        for index, scenario in enumerate(["release", "microgrid", "tree", "water"]):
            key, observed = label+"|"+scenario, counts[label+"|"+scenario]
            percentages = [int(f"{100*observed[c][0]/observed[c][1]:.0f}") for c in ["natural", "attack"]]
            significant = adjusted[key] < 0.05
            if printed[label][index] != (percentages, significant):
                failures.append({"cell": key, "printed": printed[label][index],
                                 "recomputed": [percentages, significant]})
            tests.append({"cell": key, "counts": observed, "percentages": percentages,
                          "fisher_two_sided": pvalues[key], "holm_16": adjusted[key],
                          "significant": significant,
                          "independent_newcombe_95": independent_newcombe(*observed["attack"], *observed["natural"])})
    gemini_ci = next(t["independent_newcombe_95"] for t in tests if t["cell"] == "Gemini 3.6|microgrid")
    ci_display = [round(100*x) for x in gemini_ci]
    if ci_display != [-1, 39] or "$-1$ to $+39$" not in main:
        failures.append({"gemini_microgrid_ci": gemini_ci, "rounded_pp": ci_display})
    deltas = [100*(t["counts"]["attack"][0]/30-t["counts"]["natural"][0]/30)
              for t in tests if t["significant"]]
    if round(min(deltas)) != 37:
        failures.append({"minimum_significant_change_pp": min(deltas)})

    c = load("experiment_c_collection_report_qwen_s29_provider429_snapshot_v1.json")
    arm_order = ["undefended_natural", "undefended_selected_order", "barrier", "randomized", "order_consistency_24", "invariant"]
    figure_rates = []
    for label, model in MODELS.items():
        cell = c["claude_none_sensitivity"] if label == "Claude 4.6" else c["matched_non_off_primary"][model]
        figure_rates.append([round(100*cell["analysis"]["arms"][arm]["target_C_rate_all_decisions"]) for arm in arm_order])
    generator = root/"deliverables/paper/figures/make_fig_defenses.py"
    rate_assignment = next(node for node in ast.parse(generator.read_text()).body
                           if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "rates" for t in node.targets))
    plotted_rates = ast.literal_eval(rate_assignment.value.args[0])
    if figure_rates != plotted_rates:
        failures.append({"defense_figure_report_rates": figure_rates, "generator_rates": plotted_rates})
    if defense_asset != (root/"deliverables/paper/figures/fig_defenses.pdf").read_bytes():
        failures.append({"defense_asset": "Current source ZIP differs from checked local figure"})
    return {"schema": "chronos.current-manuscript-check.v1", "passed": not failures,
            "source_zip_sha256": hashlib.sha256(source_zip.read_bytes()).hexdigest(),
            "main_tex_sha256": hashlib.sha256(main.encode()).hexdigest(),
            "raw_evidence_files_checked": len(checked_sources), "raw_evidence_sha256": checked_sources,
            "independent_tests": tests, "family_size": len(tests),
            "significant_tests": sum(t["significant"] for t in tests),
            "minimum_significant_change_pp": min(deltas), "gemini_microgrid_ci_rounded_pp": ci_display,
            "defense_figure": {"arms": arm_order, "models": list(MODELS), "rates_percent": figure_rates,
                               "check_scope": "Current PDF identity and generator literal rates matched to saved raw-derived Experiment C report; C raw re-audit belongs to the packet verifier"},
            "failures": failures,
            "limits": ["Imported original-study results are descriptive and are not part of Holm-16.",
                       "No model calls, source changes, full mathematical proof, or visual-layout review."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--root", type=Path, default=here if (here/"kaggle").is_dir() else here.parents[1])
    result = check(parser.parse_args().root)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
