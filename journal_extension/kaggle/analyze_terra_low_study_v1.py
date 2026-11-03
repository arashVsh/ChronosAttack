"""Matched Terra-low four-observation study and defense cells (collected 2026-09-20), analysed with
the same audited functions as the four-model analysis (``round2_analysis``). No model calls."""

import json
from pathlib import Path

import round2_analysis as r2
import verify_round2_terra_defense_collection as defense_verifier
import verify_round2_terra_study_collection as collection_verifier

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "round2_analysis" / "terra_low_study_analysis_v1.json"
MODEL = "openai/gpt-5.6-terra"


def _ledger_events(collection_name):
    collection = json.loads((HERE / "round2_generated" / collection_name).read_text())
    events, sources = [], []
    for shard in collection.get("shards") or collection.get("arms"):
        record = shard["artifacts"]["evidence"]
        raw = (ROOT / record["path"]).read_bytes()
        if r2.hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError(f"Pinned ledger changed: {record['path']}")
        events += [json.loads(line) for line in raw.decode().splitlines()]
        sources.append(record)
    return collection, events, sources


def _verified_counts(events, verified):
    """Stand-in for the standard auditor, whose three-attempt limit predates the approved
    attempt extension of shard 00. The gate is the sealed collection verifier (run first);
    this only reports its counts in the auditor's shape."""
    def audit_fn(_events, model, phase, require_complete=True):
        calls = [e for e in events if e["event"] in ("call_complete", "call_failed")]
        return {"verifier": "verify_round2_terra_study_collection.verify", "verified": verified,
                "completed_jobs": sum(e["event"] == "job_complete" for e in events),
                "complete_trial_calls": sum(e["planned_calls"] for e in events if e["event"] == "job_complete"),
                "observed_invocations": len(calls), "failed_calls": sum(e["event"] == "call_failed" for e in calls),
                "known_cost_usd": sum(e["cost_usd"] or 0 for e in calls),
                "unknown_cost_calls": sum(e["cost_usd"] is None for e in calls)}
    return audit_fn


def _with_events(events, verified, function, *args):
    original_read, original_amended = r2.read_jsonl, r2.amended_auditor
    r2.read_jsonl = lambda path: events
    r2.amended_auditor = lambda source: _verified_counts(events, verified)
    try:
        return function(*args)
    finally:
        r2.read_jsonl, r2.amended_auditor = original_read, original_amended


def analyze():
    manifest = json.loads(r2.MANIFEST_PATH.read_text())
    verified = collection_verifier.verify()
    _, study_events, study_sources = _ledger_events("terra_study_collection_v1.json")
    study_id = study_events[0]["job_id"].split("|")[0]
    engine = r2.protocol.engine
    old_id = engine.STUDY_ID
    engine.STUDY_ID = study_id
    try:
        study = _with_events(study_events, verified, r2._audited_study,
                             {"model": MODEL, "reasoning": "low", "path": HERE / "round2_generated" / "terra_study_collection_v1.json"}, manifest["held_out_order"])
    finally:
        engine.STUDY_ID = old_id
    defense_verified = defense_verifier.verify()
    _, defense_events, defense_sources = _ledger_events("terra_defense_collection_v1.json")
    defense = r2.defense_telemetry(defense_events, target=r2.defenses.fixtures()["tree4"]["target"],
                                   expected_per_arm=r2.defenses.REPETITIONS)
    if defense["totals"]["completed_decisions"] != 120:
        raise ValueError("Complete Terra-low defense matrix required")
    raw = {mode: defense["arms"][mode]["paired_vs_attacked"]["exact_p_raw"] for mode in ("randomized", "invariant")}
    defense["defended_pair_family"] = {"scope": "randomized and invariant versus contemporaneous attacked arm",
                                       "raw": raw, "holm": r2.analysis.holm(raw)}
    return {"schema": "chronos.terra-low-study-analysis.v1", "model": MODEL, "reasoning": "low",
            "study_id": study_id, "study_sources": study_sources, "study": study,
            "defense_verifier": defense_verified, "defense_sources": defense_sources, "defense": defense}


if __name__ == "__main__":
    result = analyze()
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    s = result["study"]
    print(json.dumps({k: s[k] for k in ("stateful_primary",) if k in s}, indent=1)[:1500])
