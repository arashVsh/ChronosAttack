"""Strict local receipt for three source-less B s18/s19 task creations.

The five accepted canonical tasks are independently raw-replayed. No Kaggle
mutation occurs here. A delayed original-v1 creation remains a residual risk.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import capture_benchmark_quota_v1 as capture_quota
import experiment_b_protocol as protocol
import experiment_b_quota_gate_v1 as quota_gate
import verify_experiment_b_final_collection_v1 as collection
import verify_experiment_b_study_wave_v1 as wave
import verify_experiment_b_study_batch00_tasks as batch00
import verify_experiment_b_transport_repair_v1 as first_repair
import verify_experiment_b_transport_repair_s18_s19_sources_v1 as sources


ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "kaggle/round2_generated"
RUNS = ROOT / "kaggle/round2_runs_20260920/experiment_b_study"
ORPHANS = RUNS / "transport_repair_s18_s19"
POST_ORPHANS = ORPHANS / "post_repair_originals_20260923"
MANIFEST = GENERATED / "experiment_b_study_transport_repair_s18_s19_v1.json"
BEFORE_METER = RUNS / "quota_after_b_study_s15_20260923_v1.json"
AFTER_METER = ORPHANS / "quota_after_orphan_observation_20260923_v1.json"
ACTIVE_EVENTS = ORPHANS / "browser_active_events_observation_20260923_v1.json"
RUN_IDS = {
    ("openai/gpt-5.6-terra", 16): 2844790,
    ("anthropic/claude-sonnet-4-6@default", 16): 2844749,
    ("openai/gpt-5.6-terra", 17): 2844772,
    ("anthropic/claude-sonnet-4-6@default", 17): 2844755,
    ("openai/gpt-5.6-terra", 18): 2844796,
}
EXPECTED_NEW_SHARDS = {
    "openai/gpt-5.6-terra": [16, 17, 18],
    "anthropic/claude-sonnet-4-6@default": [16, 17],
}
KNOWN_FIVE_COST_USD = 0.5925509


def digest(value: dict) -> str:
    return first_repair.digest(value)


def _time(value: str) -> datetime:
    return first_repair._time(value)


def _record(path: Path) -> dict:
    return first_repair._record(path)


def _wave_tasks() -> tuple[dict, dict[tuple[str, int], dict]]:
    checked = wave.verify_wave(sources.WAVE_PATH)
    if checked["batch_manifest_sha256"] != sources.WAVE_SHA256:
        raise ValueError("B s18/s19 repair canonical wave identity changed")
    saved = json.loads(sources.WAVE_PATH.read_text())
    tasks = {(task["model"], task["shard_index"]): task for task in saved["tasks"]}
    return saved, tasks


def _five_specs(wave_manifest: dict, tasks: dict[tuple[str, int], dict]) -> dict:
    specs = copy.deepcopy(wave_manifest["run_specs"])
    for model, indices in EXPECTED_NEW_SHARDS.items():
        _, _, tag = protocol.CELLS[model]
        model_dir = model.split("/", 1)[1].replace("@", "-")
        for index in indices:
            task = tasks[(model, index)]
            root = (RUNS / tag.replace("_", "-") / task["task_name"] / "1"
                    / model_dir / str(RUN_IDS[(model, index)]))
            specs[model]["study_runs"].append({
                "run_root": str(root.relative_to(ROOT)),
                "source_path": task["source_path"],
            })
    return specs


def _five_replay(specs: dict) -> tuple[dict, list[dict]]:
    sealed = collection.build_manifest_from_runs(specs)
    active = {cell["model_id"]: cell for cell in sealed["cells"]
              if cell["model_id"] in EXPECTED_NEW_SHARDS}
    if set(active) != set(EXPECTED_NEW_SHARDS):
        raise ValueError("B five-run repair receipt has the wrong active cells")
    completed = []
    for model, indices in EXPECTED_NEW_SHARDS.items():
        cell = active[model]
        ledgers = cell["raw_ledgers"]
        if (
            cell["status"] != "study_partial"
            or cell["study_unknown_cost_calls"] != 0
            or [run["shard_index"] for run in ledgers] != list(range(16)) + indices
        ):
            raise ValueError("B five-run receipt has an incomplete or unexpected shard subset")
        for run in ledgers[16:]:
            if len(run["completed_job_ids"]) != 6:
                raise ValueError("B accepted shard is not a complete six-job run")
            completed.append({
                "model": model,
                "shard_index": run["shard_index"],
                "task_name": run["task_name"],
                "evidence_path": run["artifacts"]["evidence"]["path"],
                "evidence_sha256": run["artifacts"]["evidence"]["sha256"],
                "terminal_path": run["artifacts"]["terminal"]["path"],
                "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
                "run_end_utc": collection._run_end_utc(run),
                "known_cost_usd": run["known_cost_usd"],
                "observed_invocations": run["observed_invocations"],
                "failed_calls": run["failed_calls"],
                "completed_job_ids": run["completed_job_ids"],
            })
    if (
        len(completed) != 5
        or sum(len(run["completed_job_ids"]) for run in completed) != 30
        or not math.isclose(math.fsum(run["known_cost_usd"] for run in completed),
                            KNOWN_FIVE_COST_USD, rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("B five accepted runs do not reconcile to raw cost")
    completed.sort(key=lambda run: (run["shard_index"], run["model"]))
    return sealed, completed


def _active_events(tasks: list[dict], completed: list[dict]) -> tuple[dict, datetime]:
    saved = json.loads(ACTIVE_EVENTS.read_text())
    slugs = {task["original_task_name"] for task in tasks}
    times = saved.get("observed_between_utc", [])
    if (
        saved.get("schema") != "chronos.experiment-b-browser-active-events-observation.v1"
        or saved.get("active_events_count") != 0
        or set(saved.get("orphan_task_slugs_absent_from_active_events_list", [])) != slugs
        or len(times) != 2
        or _time(times[0]) > _time(times[1])
        or _time(times[0]) <= max(_time(run["run_end_utc"]) for run in completed)
    ):
        raise ValueError("B manual zero-active-events report is not after five accepted runs")
    return {**_record(ACTIVE_EVENTS), "evidence_kind": "manual_browser_observation"}, _time(times[1])


def _quota_attestations(*, wave_manifest: dict, completed: list[dict],
                        observed_after: datetime) -> tuple[dict, dict]:
    before = json.loads(BEFORE_METER.read_text())
    after = json.loads(AFTER_METER.read_text())
    prior_last = wave_manifest["prior_last_run"]
    capture_quota.verify_attestation(
        before, (ROOT / prior_last["evidence_path"]).read_bytes(),
        (ROOT / prior_last["terminal_path"]).read_bytes(),
    )
    latest_run = max(completed, key=lambda run: _time(run["run_end_utc"]))
    context = after["run_context"]
    if (
        context.get("task") != latest_run["task_name"]
        or context.get("model") != latest_run["model"]
        or context.get("evidence_sha256") != latest_run["evidence_sha256"]
        or context.get("terminal_sha256") != latest_run["terminal_sha256"]
        or _time(after["queried_at_start_utc"]) <= max(
            observed_after, _time(latest_run["run_end_utc"])
        )
    ):
        raise ValueError("B post-orphan official meter is not after the latest raw run and observation")
    capture_quota.verify_attestation(
        after, (ROOT / latest_run["evidence_path"]).read_bytes(),
        (ROOT / latest_run["terminal_path"]).read_bytes(),
    )
    used_before = before["response"]["daily_quota_used_usd"]
    used_after = after["response"]["daily_quota_used_usd"]
    if (
        before["response"]["total_daily_quota_allowed_usd"] != 10.0
        or after["response"]["total_daily_quota_allowed_usd"] != 10.0
        or not math.isclose(used_after - used_before, KNOWN_FIVE_COST_USD,
                            rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("B official quota delta differs from five strict raw ledgers")
    return (
        {**_record(BEFORE_METER), "attestation_sha256": before["attestation_sha256"],
         "daily_used_usd": used_before},
        {**_record(AFTER_METER), "attestation_sha256": after["attestation_sha256"],
         "daily_used_usd": used_after, "pinned_completed_run": latest_run},
    )


def build_manifest() -> dict:
    source_package = sources.verify_sources()
    tasks = source_package["tasks"]
    orphan_records, orphan_end = first_repair._orphan_captures(tasks, directory=ORPHANS)
    wave_manifest, wave_tasks = _wave_tasks()
    specs = _five_specs(wave_manifest, wave_tasks)
    five_collection, completed = _five_replay(specs)
    browser, browser_end = _active_events(tasks, completed)
    before_meter, after_meter = _quota_attestations(
        wave_manifest=wave_manifest, completed=completed,
        observed_after=max(orphan_end, browser_end),
    )
    body = {
        "schema": "chronos.experiment-b-transport-repair-s18-s19-tasks.v1",
        "status": "staged_after_source_less_zero_run_v1",
        "launch_authorized": False,
        "canonical_wave_manifest_sha256": source_package["canonical_wave_manifest_sha256"],
        "prior_s15_collection_sha256": wave_manifest["prior_collection_sha256"],
        "five_run_collection_sha256": five_collection["collection_sha256"],
        "five_run_specs": specs,
        "completed_original_runs": completed,
        "completed_original_run_count": 5,
        "completed_original_jobs": 30,
        "completed_original_planned_calls": 150,
        "completed_original_known_cost_usd": KNOWN_FIVE_COST_USD,
        "original_orphan_captures": orphan_records,
        "manual_active_events_observation": browser,
        "before_meter": before_meter,
        "after_orphan_meter": after_meter,
        "tasks": tasks,
        "task_count": source_package["task_count"],
        "jobs": source_package["jobs"],
        "planned_calls": source_package["planned_calls"],
        "aggregate_ceiling_usd": source_package["aggregate_ceiling_usd"],
        "scientific_changes": [],
        "original_v1_scientific_credit": False,
        "unresolved_delayed_orphan_creation_risk": True,
        "post_repair_original_status_monitor_required": True,
    }
    return {**body, "repair_manifest_sha256": digest(body)}


def verify_manifest(path: Path = MANIFEST) -> dict:
    path = Path(path)
    if path.resolve() != MANIFEST.resolve():
        raise ValueError("B s18/s19 transport repair manifest is at the wrong path")
    saved = json.loads(path.read_text())
    body = {key: value for key, value in saved.items() if key != "repair_manifest_sha256"}
    if saved.get("repair_manifest_sha256") != digest(body) or saved != build_manifest():
        raise ValueError("B s18/s19 repair manifest differs from pinned raw evidence")
    return {
        "repair_manifest_sha256": saved["repair_manifest_sha256"],
        "completed_original_run_count": 5,
        "completed_original_known_cost_usd": KNOWN_FIVE_COST_USD,
        "task_count": saved["task_count"],
        "jobs": saved["jobs"],
        "planned_calls": saved["planned_calls"],
        "aggregate_ceiling_usd": saved["aggregate_ceiling_usd"],
        "launch_authorized": False,
        "unresolved_delayed_orphan_creation_risk": True,
    }


def evaluate_quota(path: Path = MANIFEST, *, now: datetime | None = None) -> dict:
    verified = verify_manifest(path)
    saved = json.loads(path.read_text())
    after = json.loads(AFTER_METER.read_text())
    pinned = saved["after_orphan_meter"]["pinned_completed_run"]
    gate = quota_gate.evaluate(
        task_manifest=saved, attestation=after,
        evidence=(ROOT / pinned["evidence_path"]).read_bytes(),
        terminal=(ROOT / pinned["terminal_path"]).read_bytes(),
        now=now,
    )
    body = {
        **{key: value for key, value in gate.items() if key != "gate_sha256"},
        "repair_manifest_sha256": verified["repair_manifest_sha256"],
        "transport_prerequisites_checked": True,
        "original_v1_scientific_credit": False,
        "unresolved_delayed_orphan_creation_risk": True,
        "post_repair_original_status_monitor_required": True,
        "launch_authorized": True,
    }
    return {**body, "gate_sha256": digest(body)}


def verify_downloaded_replacement_run(*, model: str, shard_index: int,
                                      run_root: Path) -> dict:
    """Replay one replacement with external task identity and frozen science."""
    verified = verify_manifest()
    manifest = json.loads(MANIFEST.read_text())
    tasks = [task for task in manifest["tasks"]
             if task["model"] == model and task["shard_index"] == shard_index]
    if len(tasks) != 1:
        raise ValueError("B downloaded run is not an s18/s19 transport repair")
    task = tasks[0]
    pilot, raw = batch00._pilot(model)
    pinned = collection._pin_run(
        run_root=collection._input_path(run_root), model=model,
        task_name=task["replacement_task_name"],
        output_folder=task["output_folder"],
        source_path=ROOT / task["replacement_source_path"],
    )
    pinned.update({"shard_index": shard_index, "parent_ledger": None})
    checked = collection._study_shard(
        pinned, model, pilot, {**raw, "intended_manifest": raw["intended"]},
        require_claims=False,
    )
    return {
        **checked,
        "task_name": task["replacement_task_name"],
        "source_sha256": task["replacement_source_sha256"],
        "repair_manifest_sha256": verified["repair_manifest_sha256"],
        "run_end_utc": collection._run_end_utc(pinned),
    }


def _six_original_captures(*, directory: Path, after: datetime) -> tuple[list[dict], datetime]:
    """Replay source-less zero-run status for both transport-repair groups."""
    first = json.loads(first_repair.MANIFEST.read_text())["tasks"]
    second = json.loads(MANIFEST.read_text())["tasks"]
    records, latest = first_repair._orphan_captures(
        first + second, directory=directory, must_start_after=after,
    )
    if len(records) != 6:
        raise ValueError("B post-repair monitor must contain six original tasks")
    return records, latest


def _six_browser_original_captures(*, directory: Path, after: datetime
                                   ) -> tuple[list[dict], list[dict], datetime, dict]:
    """Check the signed-in page API against earlier strict SDK identities."""
    first = json.loads(first_repair.MANIFEST.read_text())["tasks"]
    second = json.loads(MANIFEST.read_text())["tasks"]
    prior, _ = first_repair._orphan_captures(
        first + second, directory=POST_ORPHANS,
    )
    path = directory / "browser_original_monitor.json"
    saved = json.loads(path.read_text())
    captures = saved.get("captures")
    expected = {task["original_task_name"] for task in first + second}
    if (
        saved.get("schema") != "chronos.experiment-b-browser-original-monitor.v1"
        or saved.get("metadata_endpoint")
        != "/api/i/benchmarks.BenchmarkTaskService/GetBenchmarkTask"
        or saved.get("runs_endpoint")
        != "/api/i/benchmarks.BenchmarkTaskRunService/ListBenchmarkTaskRuns"
        or saved.get("transport")
        != "signed-in Kaggle browser CDP Network.getResponseBody"
        or not isinstance(captures, list) or len(captures) != 6
        or {item.get("task") for item in captures} != expected
    ):
        raise ValueError("B browser original monitor has the wrong task roster")
    latest = after
    ids = set()
    versions = set()
    empty_runs_hash = hashlib.sha256(b"{}").hexdigest()
    for item in captures:
        observed = _time(item["queried_at_utc"])
        if (
            observed <= after
            or type(item.get("task_id")) is not int or item["task_id"] <= 0
            or type(item.get("version_id")) is not int or item["version_id"] <= 0
            or item.get("version_number") != 1
            or item.get("version_source") != "CLI"
            or item.get("has_source_kernel_id") is not False
            or item.get("runs") != {}
            or item.get("runs_response_sha256") != empty_runs_hash
            or not isinstance(item.get("metadata_response_sha256"), str)
            or len(item["metadata_response_sha256"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in item["metadata_response_sha256"])
        ):
            raise ValueError("B browser original monitoring predates the prior wave or is not zero-run")
        ids.add(item["task_id"])
        versions.add(item["version_id"])
        latest = max(latest, observed)
    if len(ids) != 6 or len(versions) != 6:
        raise ValueError("B browser original monitor has duplicate task identities")
    return captures, prior, latest, _record(path)


def verify_post_repair_original_monitor(*, after: datetime) -> dict:
    records, latest = _six_original_captures(directory=POST_ORPHANS, after=after)
    body = {
        "schema": "chronos.experiment-b-second-transport-repair-postflight.v1",
        "capture_directory": str(POST_ORPHANS.relative_to(ROOT)),
        "original_v1_captures": records,
        "observed_after_run_end_utc": after.isoformat(),
        "latest_capture_end_utc": latest.isoformat(),
        "original_v1_run_count": 0,
        "original_v1_scientific_credit": False,
    }
    return {**body, "monitor_sha256": digest(body)}


def verify_fresh_original_monitor(*, wave_start: int, after: datetime) -> dict:
    """Require a unique dated six-task capture after each completed later wave."""
    if type(wave_start) is not int or not 21 <= wave_start < 30:
        raise ValueError("B second repair monitoring is for post-s20 waves")
    candidates = sorted(
        path for path in ORPHANS.glob(f"post_s{wave_start - 1:02d}_originals_*")
        if path.is_dir()
    )
    if len(candidates) != 1:
        raise ValueError("B expected one dated six-task original capture directory")
    directory = candidates[0]
    browser = directory / "browser_original_monitor.json"
    if browser.is_file():
        records, prior, latest, artifact = _six_browser_original_captures(
            directory=directory, after=after,
        )
    else:
        records, latest = _six_original_captures(directory=directory, after=after)
    body = {
        "schema": "chronos.experiment-b-second-wave-original-monitor.v1",
        "wave_start_shard_index": wave_start,
        "capture_directory": str(directory.relative_to(ROOT)),
        "observed_after_prior_run_end_utc": after.isoformat(),
        "latest_capture_end_utc": latest.isoformat(),
        "original_v1_captures": records,
        "original_v1_run_count": 0,
        "original_v1_scientific_credit": False,
        **({"evidence_kind": "signed_in_browser_api",
            "browser_capture_artifact": artifact,
            "prior_strict_sdk_captures": prior,
            "browser_metadata_response_bodies_pinned": False}
           if browser.is_file() else {}),
    }
    return {**body, "monitor_sha256": digest(body)}


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--quota-gate", action="store_true")
    group.add_argument("--verify-run", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    if args.stage:
        if MANIFEST.exists():
            raise ValueError("B s18/s19 transport repair manifest already exists")
        result = build_manifest()
        with MANIFEST.open("x") as file:
            file.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        verify_manifest()
    elif args.quota_gate:
        result = evaluate_quota()
    elif args.verify_run:
        if args.model is None or args.shard_index is None or args.run_root is None:
            raise ValueError("B repair run verification requires model, shard and run root")
        result = verify_downloaded_replacement_run(
            model=args.model, shard_index=args.shard_index, run_root=args.run_root,
        )
    else:
        result = verify_manifest()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
