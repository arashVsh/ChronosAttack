"""Seal and verify the v2 Experiment B collection: the sealed v1 collection plus the
Gemini-minimal and Qwen-low cells run under the 2026-09-25 replacement-pilot and
2026-09-26 transport-wait amendments.

Terra-low and Claude-none come from the v1 collection, which is re-verified from raw
bytes. Each new shard is replayed with the frozen v1 checks; only its expected
source differs (frozen builder output plus the wrapper, via
``experiment_b_gemini_qwen_study_v1``). Each shard's signed-in monthly quota change
must equal its raw known cost.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
import math
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_b_gemini_qwen_study_v1 as study
import experiment_b_protocol as protocol
import verify_experiment_b_collection as raw_checks
import verify_experiment_b_final_collection_v1 as final
from round2_hosted import parse_jsonl_bytes, raw_event_summary

ROOT = final.ROOT
GENERATED = ROOT / "kaggle/round2_generated"
STUDY_RUNS = ROOT / "kaggle/round2_runs_20260920/experiment_b_study"
BASE = final.MANIFEST
OUTPUT = GENERATED / "experiment_b_collection_v2.json"
SCHEMA = "chronos.experiment-b-collection.v2"
AMENDMENTS = (
    "specs/journal-extension-sep14/round2-b-gemini-qwen-replacement-pilot-amendment-2026-09-25.md",
    study.PROCEDURE,
    study.REPLACEMENT_NOTE,
)
QUOTA_SCHEMA = "chronos.kaggle-browser-quota-observation.v1"
QUOTA_TRANSPORT = "signed-in Kaggle browser CDP Network.getResponseBody"
METER_TOLERANCE = Decimal("0.000001")  # the meter reports binary floats; same bound as the C per-run check


def _amendment_pins() -> list[dict]:
    return [{"path": path, "sha256": final._sha256((ROOT / path).read_bytes())} for path in AMENDMENTS]


def _setting(model: str) -> str:
    return next(name for name, (m, _) in study.SETTINGS.items() if m == model)


def _pilot_task(setting: str) -> dict:
    us = setting.replace("-", "_")
    return {"task_name": f"chronos-r2-tree4-rotation-pilot-{setting}-v2",
            "output_folder": f"round2_tree4_rotation_pilot_{us}_v2",
            "source_path": f"kaggle/round2_generated/tree4_rotation_pilot_{us}_v2.py"}


def _monthly(raw: bytes) -> tuple[Decimal, datetime, datetime]:
    value = json.loads(raw)
    if value.get("schema") != QUOTA_SCHEMA or value.get("transport") != QUOTA_TRANSPORT:
        raise ValueError("quota observation is not a signed-in browser capture")
    rows = json.loads(value["response_raw"], parse_float=Decimal)["quotaBalances"]
    (used,) = [row["quotaUsed"] for row in rows if row["refillPeriod"] == "MONTHLY"]
    return used, _time(value["queried_at_start_utc"]), _time(value["queried_at_end_utc"])


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _raw_cost(evidence: bytes) -> Decimal:
    events = [json.loads(line) for line in evidence.splitlines()]
    return sum((Decimal(str(event["cost_usd"])) for event in events
                if event.get("event") in ("call_complete", "call_failed") and event.get("cost_usd") is not None),
               Decimal(0))


def _bracket(run: dict, raws: dict) -> Decimal:
    """Monthly meter change across a run whose readings strictly bracket it."""
    before, _, before_end = _monthly(final._artifact(run["quota_before"])[1])
    after, after_start, _ = _monthly(final._artifact(run["quota_after"])[1])
    meta = json.loads(raws["run_metadata"])
    start, end = (_time(meta[key]) for key in ("startTime", "endTime"))
    if not before_end < start < end < after_start:
        raise ValueError(f"B v2 {run['task_name']} quota readings do not bracket the run")
    return after - before


def _replaced(run: dict, model: str) -> dict:
    """A failed shard run superseded under the replacement note: pinned and costed, never analysed."""
    extra = {"quota_before", "quota_after"}
    base = {key: value for key, value in run.items() if key not in extra}
    index = base["shard_index"]
    task, folder, source_path = study.names(_setting(model), index)
    if set(run) - set(base) != extra or (base["task_name"], base["output_folder"]) != (task, folder) \
            or (_setting(model), index, 1) not in study.REPLACEMENTS:
        raise ValueError("B v2 replaced run is not the one named by the replacement note")
    _, raws = final._run_artifacts(base, model, source_path=source_path)
    if raws["frozen_source"] != study.build_source(_setting(model), index).encode():
        raise ValueError("B v2 replaced-run source differs from deterministic regeneration")
    events = [json.loads(line) for line in raws["evidence"].splitlines()]
    calls = [e for e in events if e.get("event") in ("call_complete", "call_failed")]
    unknown = sum(e.get("cost_usd") is None for e in calls)
    terminal = json.loads(raws["terminal"])
    known, delta = _raw_cost(raws["evidence"]), _bracket(run, raws)
    if terminal.get("error") is None or delta < known - METER_TOLERANCE:
        raise ValueError("B v2 replaced run did not fail or its meter change is below its known cost")
    return {"shard_index": index, "task_name": task, "error_type": terminal["error"]["type"],
            "completed_jobs": sum(e.get("event") == "job_complete" for e in events),
            "observed_invocations": len(calls), "unknown_cost_calls": unknown,
            "known_cost_usd": str(known), "quota_monthly_delta_usd": str(delta),
            "meter_attributed_unknown_usd": str(delta - known),
            "evidence_path": base["artifacts"]["evidence"]["path"],
            "evidence_sha256": base["artifacts"]["evidence"]["sha256"]}


def _shard(run: dict, model: str, pilot: dict, pilot_raws: dict) -> dict:
    extra = {"transient_waits", "quota_before", "quota_after"}
    base = {key: value for key, value in run.items() if key not in extra | {"rerun"}}
    if set(run) - set(base) - {"rerun"} != extra or base.get("parent_ledger") is not None:
        raise ValueError("B v2 shard record is incomplete or resumed")
    index, rerun = base["shard_index"], run.get("rerun", 0)
    task, folder, source_path = study.names(_setting(model), index, rerun)
    if (base["task_name"], base["output_folder"]) != (task, folder):
        raise ValueError("B v2 shard has an unapproved task or folder")
    paths, raws = final._run_artifacts(base, model, source_path=source_path)
    if raws["frozen_source"] != study.build_source(_setting(model), index, rerun).encode():
        raise ValueError("B v2 source differs from deterministic regeneration")
    final._embedded_sources(base, final._relative_path(base["run_root"]))
    platform = final._platform(base, paths, model)
    checked = raw_checks.verify_raw_study_shard(
        model=model, shard_index=index, evidence=raws["evidence"], terminal=raws["terminal"],
        intended=raws["intended_manifest"], hosted_audit=raws["hosted_audit"], parent_ledger=b"",
        pilot_receipt=pilot["receipt"], pilot_evidence=pilot_raws["evidence"],
        pilot_terminal=pilot_raws["terminal"], pilot_intended=pilot_raws["intended_manifest"])
    for key in ("completed_job_ids", "observed_invocations", "failed_calls", "known_cost_usd"):
        if base[key] != checked[key]:
            raise ValueError(f"B v2 shard {index} {key} differs from raw replay")
    output = final._relative_path(base["run_root"]) / folder
    _, waits_raw = final._artifact(run["transient_waits"], expected=output / "transient_waits.json")
    waits = json.loads(waits_raw)
    if waits.get("schema") != study.TRANSPORT_POLICY["schema"]:
        raise ValueError("B v2 transient-wait record has the wrong schema")
    delta = _bracket(run, raws)
    if abs(delta - _raw_cost(raws["evidence"])) > METER_TOLERANCE:
        raise ValueError(f"B v2 shard {index} quota change differs from raw cost")
    artifacts = base["artifacts"]
    return {**checked,
            "path": artifacts["evidence"]["path"], "sha256": artifacts["evidence"]["sha256"],
            "terminal_path": artifacts["terminal"]["path"], "terminal_sha256": artifacts["terminal"]["sha256"],
            "intended_path": artifacts["intended_manifest"]["path"],
            "intended_sha256": artifacts["intended_manifest"]["sha256"],
            "audit_path": artifacts["hosted_audit"]["path"], "audit_sha256": artifacts["hosted_audit"]["sha256"],
            "transient_waits": {"count": waits["count"], "seconds": waits["seconds"]},
            "rerun": rerun, "quota_monthly_delta_usd": str(delta)}


def _cell(cell: dict) -> dict:
    model = cell["model_id"]
    setting = _setting(model)
    identity = protocol.cell(model)
    pilot, platform, pilot_raws = final._pilot(cell["pilot"], model, _pilot_task(setting), failed=False)
    ledgers = [_shard(run, model, pilot, pilot_raws) for run in cell["raw_ledgers"]]
    replaced = [_replaced(run, model) for run in cell["replaced_runs"]]
    if [r["shard_index"] for r in replaced] != [r["shard_index"] for r in ledgers if r["rerun"]]:
        raise ValueError("B v2 replacements and replaced runs do not pair one to one")
    indices = [record["shard_index"] for record in ledgers]
    if indices != sorted(set(indices)):
        raise ValueError("B v2 cell has duplicate or unordered shards")
    complete = indices == list(range(builder.SHARD_COUNT))
    study_totals = raw_checks.verify_study_cell(ledgers, model) if complete else {
        "completed_jobs": sum(len(record["completed_job_ids"]) for record in ledgers),
        "planned_calls": 30 * len(ledgers),
        "observed_invocations": sum(record["observed_invocations"] for record in ledgers),
        "failed_calls": sum(record["failed_calls"] for record in ledgers),
        "known_cost_usd": math.fsum(record["known_cost_usd"] for record in ledgers),
    }
    return {
        "model_id": model, "reasoning_id": identity["reasoning"], "cohort_role": identity["role"],
        "status": "complete" if complete else "study_partial",
        **{key: study_totals[key] for key in ("completed_jobs", "planned_calls", "observed_invocations",
                                                "failed_calls", "known_cost_usd")},
        "pilot_known_cost_usd": pilot["known_cost_usd"],
        "pilot_unknown_cost_calls": pilot["unknown_cost_calls"],
        "pilot_observed_invocations": pilot["observed_invocations"],
        "pilot_failed_calls": pilot["failed_calls"],
        "pilot_failure_type": pilot["failure_type"],
        "study_unknown_cost_calls": 0,
        "pilot_receipt_sha256": pilot["receipt"]["receipt_sha256"],
        "pilot_platform": platform,
        "raw_ledgers": ledgers,
        "partial_study": None,
        "replaced_runs": replaced,
        "amendments": list(AMENDMENTS),
        "transient_waits": {"count": sum(r["transient_waits"]["count"] for r in ledgers),
                            "seconds": sum(r["transient_waits"]["seconds"] for r in ledgers)},
    }


def verify(path: Path = OUTPUT) -> dict:
    manifest = json.loads(Path(path).read_bytes())
    body = {key: value for key, value in manifest.items() if key != "collection_sha256"}
    if set(manifest) != {"schema", "base_collection", "amendments", "added_cells", "status", "collection_sha256"} \
            or manifest["collection_sha256"] != final._digest(body) or manifest["schema"] != SCHEMA:
        raise ValueError("B v2 collection schema or self-hash mismatch")
    final._artifact(manifest["base_collection"], expected=BASE)
    if manifest["amendments"] != _amendment_pins():
        raise ValueError("B v2 amendment text changed")
    base = final.verify_collection_manifest(BASE)
    added = {cell["model_id"]: _cell(cell) for cell in manifest["added_cells"]}
    if set(added) != {model for model, _ in study.SETTINGS.values()}:
        raise ValueError("B v2 must add exactly the Gemini and Qwen cells")
    cells = []
    for cell in base["cells"]:
        if cell["model_id"] in added:
            if cell["status"] != "pilot_failed":
                raise ValueError("B v2 may only replace failed-pilot cells")
            cells.append(added[cell["model_id"]])
        else:
            cells.append(cell)
    status = ("complete_raw_revalidated" if all(cell["status"] == "complete" for cell in cells)
              else "partial_raw_revalidated")
    if manifest["status"] != status:
        raise ValueError("B v2 status does not match cell completion")
    return {
        **{key: base[key] for key in ("fixture_manifest_sha256",)},
        "schema": SCHEMA, "status": status, "collection_sha256": manifest["collection_sha256"],
        "base_collection_sha256": base["collection_sha256"], "cells": cells,
        **{key: sum(cell[key] for cell in cells) for key in (
            "completed_jobs", "planned_calls", "observed_invocations", "failed_calls",
            "pilot_unknown_cost_calls", "study_unknown_cost_calls")},
        "known_cost_usd": math.fsum(cell["known_cost_usd"] for cell in cells),
        "pilot_known_cost_usd": math.fsum(cell["pilot_known_cost_usd"] for cell in cells),
    }


def _one(pattern: str) -> Path:
    matches = sorted(GENERATED.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one file for {pattern}, found {len(matches)}")
    return matches[0]


def seal(output: Path = OUTPUT) -> dict:
    added = []
    for setting, (model, pilot_run) in study.SETTINGS.items():
        short, us = setting.split("-")[0], setting.replace("-", "_")
        task = _pilot_task(setting)
        pilot = {**final._pin_run(
            run_root=ROOT / "kaggle/round2_runs_20260920/experiment_b_pilot" / setting / (task["task_name"] + "/1") / pilot_run,
            model=model, task_name=task["task_name"], output_folder=task["output_folder"],
            source_path=ROOT / task["source_path"], receipt_path=GENERATED / f"experiment_b_pilot_receipt_{us}_v2.json"),
            "known_cost_usd": json.loads((GENERATED / f"experiment_b_pilot_receipt_{us}_v2.json").read_text())["known_cost_usd"]}
        runs, replaced = [], []
        for index in range(builder.SHARD_COUNT):
            rerun = int((setting, index, 1) in study.REPLACEMENTS
                        and any((STUDY_RUNS / setting / study.names(setting, index, 1)[0] / "1").glob("*/*")))
            if rerun:
                name, folder, source_path = study.names(setting, index)
                (root,) = sorted((STUDY_RUNS / setting / name / "1").glob("*/*"))
                replaced.append({**final._pin_run(run_root=root, model=model, task_name=name, output_folder=folder,
                                                  source_path=source_path),
                                 "shard_index": index, "parent_ledger": None,
                                 "quota_before": final.pin_artifact(_one(f"experiment_b_quota_before_{short}_s{index:02d}_browser_observation_*_v1.json")),
                                 "quota_after": final.pin_artifact(_one(f"experiment_b_quota_after_{short}_s{index:02d}_browser_observation_*_v1.json"))})
            name, folder, source_path = study.names(setting, index, rerun)
            tag = f"s{index:02d}" + (f"_r{rerun}" if rerun else "")
            roots = sorted((STUDY_RUNS / setting / name / "1").glob("*/*"))
            if not roots:
                continue
            (root,) = roots
            run = {**final._pin_run(run_root=root, model=model, task_name=name, output_folder=folder,
                                    source_path=source_path),
                   "shard_index": index, "parent_ledger": None, **({"rerun": rerun} if rerun else {})}
            evidence = (root / folder / (model.replace("/", "_") + ".jsonl")).read_bytes()
            summary = raw_event_summary(parse_jsonl_bytes(evidence, label="B v2 shard"))
            run.update({
                "completed_job_ids": sorted(json.loads(line)["job"]["id"] for line in evidence.splitlines()
                                            if json.loads(line).get("event") == "job_complete"),
                "observed_invocations": summary["observed_invocations"],
                "failed_calls": summary["failed_calls"],
                "known_cost_usd": summary["known_cost_usd"],
                "transient_waits": final.pin_artifact(root / folder / "transient_waits.json"),
                "quota_before": final.pin_artifact(_one(f"experiment_b_quota_before_{short}_{tag}_browser_observation_*_v1.json")),
                "quota_after": final.pin_artifact(_one(f"experiment_b_quota_after_{short}_{tag}_browser_observation_*_v1.json")),
            })
            runs.append(run)
        added.append({"model_id": model, "pilot": pilot, "raw_ledgers": runs, "replaced_runs": replaced})
    complete = all(len(cell["raw_ledgers"]) == builder.SHARD_COUNT for cell in added)
    body = {"schema": SCHEMA, "base_collection": final.pin_artifact(BASE),
            "amendments": _amendment_pins(),
            "added_cells": added,
            "status": "complete_raw_revalidated" if complete else "partial_raw_revalidated"}
    manifest = {**body, "collection_sha256": final._digest(body)}
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return verify(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    checked = seal(args.seal) if args.seal else verify(args.verify or OUTPUT)
    print(json.dumps({key: checked[key] for key in ("status", "collection_sha256", "completed_jobs",
                                                   "known_cost_usd")}, sort_keys=True))
    for cell in checked["cells"]:
        print(cell["model_id"], cell["status"], cell["completed_jobs"], len(cell["raw_ledgers"]),
              cell.get("transient_waits"))


if __name__ == "__main__":
    main()
