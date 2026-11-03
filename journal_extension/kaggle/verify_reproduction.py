"""Legacy 46-check regression suite regenerated from raw evidence.

The broader report-aware verifier is ``verify_round2.py``. This script retains
the historical 46 checks, but B3/C1 are now rebuilt from their raw ledgers and
confirmation batches rather than trusted from ``completion_results/analysis.json``.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import four_observation_protocol as p
import four_observation_defenses as d
import analyze_four_observation as A
import analyze_completion_study as completion_analysis
import audit_completion_evidence as completion_audit
from recovery_adapter import amended_auditor

STUDY = [
    ("openai/gpt-5.6-terra", "none",
     "four_observation_results/terra_study_20260910/openai_gpt-5.6-terra.jsonl",
     dict(jobs=690, calls=2310, steer_pp=6.666666666666667)),
    ("anthropic/claude-sonnet-4-6@default", "none",
     "four_observation_results/claude_final_20260910/anthropic_claude-sonnet-4-6@default.jsonl",
     dict(jobs=690, calls=2310, steer_pp=-16.666666666666664)),
    ("google/gemini-3.6-flash", "minimal",
     "journal_gemini_study_20260914/output/journal_gemini_study_minimal/google_gemini-3.6-flash.jsonl",
     dict(jobs=690, calls=2310, steer_pp=46.666666666666664, cost=3.9131894999999974)),
    ("qwen/qwen3-235b-a22b-instruct-2507", "low",
     "qwen_study_sep16/chronos-qwen-study-sep16/1/qwen3-235b-a22b-instruct-2507/2219989"
     "/study_out/qwen_qwen3-235b-a22b-instruct-2507.jsonl",
     dict(jobs=690, calls=2310, steer_pp=100.0, cost=0.5590406800000012)),
]
DEFENSE = [
    ("google/gemini-3.6-flash", "minimal",
     "defense_runs_20260914/gemini_output", dict(jobs=120, calls=600, cost=0.926421,
                                                 arms={"undefended_natural": 30.0, "undefended_attack": 90.0,
                                                       "randomized": 13.333333333333334, "invariant": 0.0})),
    ("openai/gpt-5.6-terra", "none",
     "defense_runs_20260914/terra_output", dict(jobs=120, calls=600, cost=1.877610999999997,
                                                arms={"undefended_natural": 0.0, "undefended_attack": 3.3333333333333335,
                                                      "randomized": 0.0, "invariant": 0.0})),
    ("anthropic/claude-sonnet-4-6@default", "none",
     "defense_runs_20260914/claude_all", dict(jobs=120, calls=600, cost=2.616477300000002,
                                              arms={"undefended_natural": 83.33333333333334, "undefended_attack": 90.0,
                                                    "randomized": 76.66666666666667, "invariant": 70.0})),
    ("qwen/qwen3-235b-a22b-instruct-2507", "low",
     "defense_runs_20260914/qwen_all", dict(jobs=120, calls=600, cost=0.1317146600000002,
                                            arms={"undefended_natural": 0.0, "undefended_attack": 100.0,
                                                  "randomized": 23.333333333333332, "invariant": 0.0})),
]
BASE = dict(p.engine.CALL_SETTINGS)
failures = []


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) < tol


def best_jsonl(root):
    best, jobs = None, -1
    for path in Path(root).rglob("*.jsonl"):
        n = sum('"job_complete"' in line for line in path.read_text().splitlines())
        if n > jobs:
            best, jobs = path, n
    return best


def check(label, got, want):
    ok = close(got, want) if isinstance(want, float) else got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r} want {want!r}")
    if not ok:
        failures.append(label)


print("=== study cells, fresh extraction ===")
audit = amended_auditor((HERE / "audit_four_observation.py").read_text())
for model, reasoning, rel, want in STUDY:
    p.engine.MODELS = tuple(dict.fromkeys((*p.engine.MODELS, model)))
    p.engine.CALL_SETTINGS = dict(BASE, reasoning=reasoning)
    events = [json.loads(x) for x in (HERE / rel).read_text().splitlines()]
    chk = audit(events, model, "study", False)
    name = model.split("/")[-1][:22]
    check(f"{name} jobs", chk["completed_jobs"], want["jobs"])
    check(f"{name} calls", chk["complete_trial_calls"], want["calls"])
    if "cost" in want:
        check(f"{name} cost", chk["known_cost_usd"], want["cost"])
    rep = A.analyze(events, model, "study", audit_fn=audit)
    check(f"{name} stateful steering pp",
          rep["primary_pairs"]["stateful"]["target_rate_change"] * 100, want["steer_pp"])

print("\n=== defense suites, fresh extraction ===")
for model, reasoning, root, want in DEFENSE:
    d.engine.MODELS = tuple(dict.fromkeys((*d.engine.MODELS, model)))
    d.engine.CALL_SETTINGS = dict(BASE, reasoning=reasoning)
    path = best_jsonl(HERE / root)
    events = [json.loads(x) for x in path.read_text().splitlines()]
    chk = d.audit(events, model, require_complete=True)
    name = model.split("/")[-1][:22]
    check(f"{name} defense jobs", chk["completed_jobs"], want["jobs"])
    check(f"{name} defense calls", chk["attempted_calls"], want["calls"])
    check(f"{name} defense cost", chk["known_cost_usd"], want["cost"])
    target = d.fixtures()["tree4"]["target"]
    arm = {}
    for e in events:
        if e["event"] == "job_complete":
            arm.setdefault(e["job"]["mode"], []).append(e["final"]["final_choice"])
    for mode, expected in want["arms"].items():
        rate = sum(c == target for c in arm[mode]) / len(arm[mode]) * 100
        check(f"{name} {mode} target rate", rate, expected)

print("\n=== cross-scenario table (section 3.7) ===")
completion_logs = [
    HERE / "completion_results/terra_saved.jsonl",
    HERE / "completion_results/claude_v3_final_preserved.jsonl",
    HERE / "completion_results/claude_v4_delta_verified.jsonl",
]
three = completion_analysis.analyze(completion_audit.audit(completion_logs))
for key, expected in (("openai/gpt-5.6-terra|b3", 83.33333333333334),
                      ("anthropic/claude-sonnet-4-6@default|b3", 70.0),
                      ("openai/gpt-5.6-terra|c1", 53.333333333333336),
                      ("anthropic/claude-sonnet-4-6@default|c1", 53.33333333333333)):
    got = three["cells"][key]["stateful"]["target_rate_difference"] * 100
    check(f"{key} change", got, expected)

print()
if failures:
    print(f"REPRODUCTION FAILED: {len(failures)} mismatch(es)")
    sys.exit(1)
print("LEGACY REPRODUCTION VERIFIED: all 46 regression checks regenerate from raw evidence")
