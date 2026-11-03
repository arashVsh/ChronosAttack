"""Strict local receipt and quota gate for three B task-slug transport repairs.

No Kaggle mutation occurs here. The original v1 records had no source kernel or
model run when captured. A delayed platform creation remains possible, so the
replacement tasks must be monitored alongside the original slugs.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
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
import verify_experiment_b_transport_repair_sources_v1 as sources


ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "kaggle/round2_generated"
RUNS = ROOT / "kaggle/round2_runs_20260920/experiment_b_study"
ORPHANS = RUNS / "transport_repair_s06_s07"
POST_ORPHANS = ORPHANS / "post_repair_originals"
MANIFEST = GENERATED / "experiment_b_study_transport_repair_s06_s07_v1.json"
S05_SPECS = GENERATED / "experiment_b_study_s05_run_specs_v1.json"
BEFORE_METER = RUNS / "quota_after_b_study_s05_20260923_v1.json"
AFTER_METER = ORPHANS / "quota_after_orphan_observation_20260923_v1.json"
ACTIVE_EVENTS = ORPHANS / "browser_active_events_observation_20260923_v1.json"
RUN_IDS = {
    ("anthropic/claude-sonnet-4-6@default", 7): 2841366,
    ("openai/gpt-5.6-terra", 8): 2841364,
    ("anthropic/claude-sonnet-4-6@default", 8): 2841378,
    ("openai/gpt-5.6-terra", 9): 2841377,
    ("anthropic/claude-sonnet-4-6@default", 9): 2841379,
    ("openai/gpt-5.6-terra", 10): 2841376,
    ("anthropic/claude-sonnet-4-6@default", 10): 2841375,
}
EXPECTED_NEW_SHARDS = {
    "openai/gpt-5.6-terra": [8, 9, 10],
    "anthropic/claude-sonnet-4-6@default": [7, 8, 9, 10],
}
KNOWN_SEVEN_COST_USD = 0.8632881


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("B repair evidence timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _record(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"B repair evidence is missing: {path}")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _wave_tasks() -> dict[tuple[str, int], dict]:
    wave.verify_wave(wave.manifest_path(6, 10))
    saved = json.loads(wave.manifest_path(6, 10).read_text())
    return {(task["model"], task["shard_index"]): task for task in saved["tasks"]}


def _seven_run_specs(tasks: dict[tuple[str, int], dict]) -> dict:
    specs = copy.deepcopy(json.loads(S05_SPECS.read_text()))
    for model, indices in EXPECTED_NEW_SHARDS.items():
        _, _, tag = protocol.CELLS[model]
        model_dir = model.split("/", 1)[1].replace("@", "-")
        for index in indices:
            task = tasks[(model, index)]
            run_id = RUN_IDS[(model, index)]
            root = RUNS / tag.replace("_", "-") / task["task_name"] / "1" / model_dir / str(run_id)
            specs[model]["study_runs"].append({
                "run_root": str(root.relative_to(ROOT)),
                "source_path": task["source_path"],
            })
    return specs


def _seven_replay(specs: dict) -> tuple[dict, list[dict]]:
    sealed = collection.build_manifest_from_runs(specs)
    completed = []
    active = {cell["model_id"]: cell for cell in sealed["cells"]
              if cell["model_id"] in EXPECTED_NEW_SHARDS}
    if set(active) != set(EXPECTED_NEW_SHARDS):
        raise ValueError("B seven-run repair receipt has the wrong active cells")
    for model, indices in EXPECTED_NEW_SHARDS.items():
        cell = active[model]
        ledgers = cell["raw_ledgers"]
        if (
            cell["status"] != "study_partial"
            or cell["study_unknown_cost_calls"] != 0
            or [run["shard_index"] for run in ledgers] != list(range(6)) + indices
        ):
            raise ValueError("B seven-run receipt does not match the exact frozen shard subset")
        for run in ledgers[6:]:
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
        len(completed) != 7
        or sum(len(run["completed_job_ids"]) for run in completed) != 42
        or not math.isclose(math.fsum(run["known_cost_usd"] for run in completed),
                            KNOWN_SEVEN_COST_USD, rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("B seven completed runs do not reconcile to the raw cost")
    completed.sort(key=lambda run: (run["shard_index"], run["model"]))
    return sealed, completed


def _orphan_captures(repair_tasks: list[dict], *, directory: Path = ORPHANS,
                     must_start_after: datetime | None = None
                     ) -> tuple[list[dict], datetime]:
    records = []
    latest = _time("2026-01-01T00:00:00Z")
    for task in repair_tasks:
        path = directory / f"{task['original_task_name']}.json"
        saved = json.loads(path.read_text())
        body = {key: value for key, value in saved.items() if key != "capture_sha256"}
        meta = saved.get("metadata", {})
        slug = meta.get("slug", {})
        if (
            saved.get("schema") != "chronos.experiment-b-orphan-task-capture.v1"
            or saved.get("capture_sha256") != digest(body)
            or saved.get("task") != task["original_task_name"]
            or slug.get("taskSlug") != task["original_task_name"]
            or slug.get("ownerSlug") != "masihmaafi"
            or slug.get("versionNumber") != 1
            or meta.get("creationState")
            != "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED"
            or meta.get("source") != "BENCHMARK_TASK_VERSION_SOURCE_UNSPECIFIED"
            or meta.get("sourceKernelId") is not None
            or saved.get("runs") != []
        ):
            raise ValueError("B original v1 task is not a source-less zero-run orphan")
        start = _time(saved["queried_at_start_utc"])
        end = _time(saved["queried_at_end_utc"])
        if start > end:
            raise ValueError("B orphan capture time is inverted")
        if must_start_after is not None and start <= must_start_after:
            raise ValueError("B original v1 monitoring predates the prior wave")
        latest = max(latest, end)
        records.append({**_record(path), "capture_sha256": saved["capture_sha256"]})
    return records, latest


def _active_events(repair_tasks: list[dict]) -> tuple[dict, datetime]:
    saved = json.loads(ACTIVE_EVENTS.read_text())
    slugs = {task["original_task_name"] for task in repair_tasks}
    times = saved.get("observed_between_utc", [])
    if (
        saved.get("schema") != "chronos.experiment-b-browser-active-events-observation.v1"
        or saved.get("active_events_count") != 0
        or set(saved.get("orphan_task_slugs_absent_from_active_events_list", [])) != slugs
        or len(times) != 2
        or _time(times[0]) > _time(times[1])
    ):
        raise ValueError("B manual active-events observation is not the scoped zero-active report")
    return {**_record(ACTIVE_EVENTS), "evidence_kind": "manual_browser_observation"}, _time(times[1])


def _quota_attestations(completed: list[dict], observed_after: datetime) -> tuple[dict, dict]:
    before = json.loads(BEFORE_METER.read_text())
    after = json.loads(AFTER_METER.read_text())
    seven_by_sha = {run["evidence_sha256"]: run for run in completed}
    after_context = after["run_context"]
    matched = seven_by_sha.get(after_context.get("evidence_sha256"))
    if matched is None:
        raise ValueError("B post-orphan official meter is not tied to one of seven raw runs")
    if (
        after_context.get("task") != matched["task_name"]
        or after_context.get("model") != matched["model"]
        or after_context.get("terminal_sha256") != matched["terminal_sha256"]
        or _time(after["queried_at_start_utc"]) <= max(
            observed_after, _time(matched["run_end_utc"])
        )
    ):
        raise ValueError("B official meter predates the orphan evidence or pinned run")
    evidence = (ROOT / matched["evidence_path"]).read_bytes()
    terminal = (ROOT / matched["terminal_path"]).read_bytes()
    capture_quota.verify_attestation(after, evidence, terminal)
    prior = json.loads(S05_SPECS.read_text())
    prefix = collection.verify_completed_prefix(prior, 6)
    last = prefix["last_run"]
    capture_quota.verify_attestation(
        before, (ROOT / last["evidence_path"]).read_bytes(),
        (ROOT / last["terminal_path"]).read_bytes(),
    )
    used_before = before["response"]["daily_quota_used_usd"]
    used_after = after["response"]["daily_quota_used_usd"]
    if (
        before["response"]["total_daily_quota_allowed_usd"] != 10.0
        or after["response"]["total_daily_quota_allowed_usd"] != 10.0
        or not math.isclose(used_after - used_before, KNOWN_SEVEN_COST_USD,
                            rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("B post-orphan official meter does not equal seven raw ledgers")
    return (
        {**_record(BEFORE_METER), "attestation_sha256": before["attestation_sha256"],
         "daily_used_usd": used_before},
        {**_record(AFTER_METER), "attestation_sha256": after["attestation_sha256"],
         "daily_used_usd": used_after, "pinned_completed_run": matched},
    )


def build_manifest() -> dict:
    source_package = sources.verify_sources()
    tasks = source_package["tasks"]
    orphan_records, orphan_end = _orphan_captures(tasks)
    browser, browser_end = _active_events(tasks)
    wave_tasks = _wave_tasks()
    specs = _seven_run_specs(wave_tasks)
    seven_collection, completed = _seven_replay(specs)
    before_meter, after_meter = _quota_attestations(completed, max(orphan_end, browser_end))
    body = {
        "schema": "chronos.experiment-b-transport-repair-tasks.v1",
        "status": "staged_after_source_less_zero_run_v1",
        "launch_authorized": False,
        "canonical_wave_manifest_sha256": source_package["canonical_wave_manifest_sha256"],
        "prior_s05_collection_sha256": json.loads(wave.manifest_path(6, 10).read_text())["prior_collection_sha256"],
        "seven_run_collection_sha256": seven_collection["collection_sha256"],
        "seven_run_specs": specs,
        "completed_original_runs": completed,
        "completed_original_run_count": 7,
        "completed_original_jobs": 42,
        "completed_original_planned_calls": 210,
        "completed_original_known_cost_usd": KNOWN_SEVEN_COST_USD,
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
        raise ValueError("B transport repair manifest is at the wrong path")
    saved = json.loads(path.read_text())
    body = {key: value for key, value in saved.items() if key != "repair_manifest_sha256"}
    if (
        saved.get("repair_manifest_sha256") != digest(body)
        or saved != build_manifest()
    ):
        raise ValueError("B transport repair manifest differs from pinned raw evidence")
    return {
        "repair_manifest_sha256": saved["repair_manifest_sha256"],
        "task_count": saved["task_count"],
        "jobs": saved["jobs"],
        "planned_calls": saved["planned_calls"],
        "aggregate_ceiling_usd": saved["aggregate_ceiling_usd"],
        "completed_original_run_count": saved["completed_original_run_count"],
        "completed_original_known_cost_usd": saved["completed_original_known_cost_usd"],
        "launch_authorized": False,
        "unresolved_delayed_orphan_creation_risk": True,
    }


def evaluate_quota(path: Path = MANIFEST, *, now: datetime | None = None) -> dict:
    verified = verify_manifest(path)
    saved = json.loads(Path(path).read_text())
    after = json.loads(AFTER_METER.read_text())
    pinned = saved["after_orphan_meter"]["pinned_completed_run"]
    gate = quota_gate.evaluate(
        task_manifest=saved,
        attestation=after,
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


def _verify_downloaded_replacement_run(*, model: str, shard_index: int,
                                       run_root: Path, receipt_checked: bool) -> dict:
    """Shared raw replay, with receipt reuse only inside the full discovery."""
    if not receipt_checked:
        verify_manifest()
    manifest = json.loads(MANIFEST.read_text())
    tasks = [task for task in manifest["tasks"]
             if task["model"] == model and task["shard_index"] == shard_index]
    if len(tasks) != 1:
        raise ValueError("B downloaded run is not one of three transport repairs")
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
        "repair_manifest_sha256": manifest["repair_manifest_sha256"],
        "run_end_utc": collection._run_end_utc(pinned),
    }


def verify_downloaded_replacement_run(*, model: str, shard_index: int,
                                      run_root: Path) -> dict:
    """Strictly replay one replacement v1; never count an original orphan run."""
    return _verify_downloaded_replacement_run(
        model=model, shard_index=shard_index, run_root=run_root,
        receipt_checked=False,
    )


def verify_post_repair_original_monitor(*, after: datetime) -> dict:
    """Require fresh zero-run v1 observations after replacement runs finish."""
    manifest = json.loads(MANIFEST.read_text())
    records, latest = _orphan_captures(
        manifest["tasks"], directory=POST_ORPHANS, must_start_after=after
    )
    body = {
        "schema": "chronos.experiment-b-transport-repair-postflight.v1",
        "original_v1_captures": records,
        "observed_after_run_end_utc": after.isoformat(),
        "latest_capture_end_utc": latest.isoformat(),
        "original_v1_run_count": 0,
        "original_v1_scientific_credit": False,
    }
    return {**body, "monitor_sha256": digest(body)}


def verify_fresh_original_monitor(*, wave_start: int, after: datetime) -> dict:
    """Seal zero-run original v1 status newly observed after a prior study wave."""
    if type(wave_start) is not int or not 16 <= wave_start < 30:
        raise ValueError("B fresh original monitoring is for post-s15 waves")
    candidates = sorted(
        path for path in ORPHANS.glob(f"post_s{wave_start - 1:02d}_originals_*")
        if path.is_dir()
    )
    if len(candidates) != 1:
        raise ValueError("B expected one dated fresh original-v1 capture directory")
    directory = candidates[0]
    manifest = json.loads(MANIFEST.read_text())
    records, latest = _orphan_captures(
        manifest["tasks"], directory=directory, must_start_after=after
    )
    body = {
        "schema": "chronos.experiment-b-wave-original-monitor.v1",
        "wave_start_shard_index": wave_start,
        "capture_directory": str(directory.relative_to(ROOT)),
        "observed_after_prior_run_end_utc": after.isoformat(),
        "latest_capture_end_utc": latest.isoformat(),
        "original_v1_captures": records,
        "original_v1_run_count": 0,
        "original_v1_scientific_credit": False,
    }
    return {**body, "monitor_sha256": digest(body)}


def discover_completed_run_specs() -> dict:
    """Index seven canonical and three replacement v1 roots; raw seal is separate."""
    verify_manifest()
    manifest = json.loads(MANIFEST.read_text())
    specs = copy.deepcopy(manifest["seven_run_specs"])
    latest_replacement_end = _time("2026-01-01T00:00:00Z")
    for task in manifest["tasks"]:
        model = task["model"]
        _, _, tag = protocol.CELLS[model]
        model_dir = model.split("/", 1)[1].replace("@", "-")
        parent = (RUNS / tag.replace("_", "-") / task["replacement_task_name"]
                  / "1" / model_dir)
        candidates = [candidate for candidate in parent.iterdir()
                      if candidate.is_dir()
                      and (candidate / task["output_folder"] / "terminal.json").is_file()
                     ] if parent.is_dir() else []
        if len(candidates) != 1:
            raise ValueError("Expected exactly one downloaded B replacement v1 run")
        checked = _verify_downloaded_replacement_run(
            model=model, shard_index=task["shard_index"], run_root=candidates[0],
            receipt_checked=True,
        )
        latest_replacement_end = max(
            latest_replacement_end, _time(checked["run_end_utc"])
        )
        specs[model]["study_runs"].append({
            "run_root": str(candidates[0].relative_to(ROOT)),
            "source_path": task["replacement_source_path"],
        })
    for model in EXPECTED_NEW_SHARDS:
        specs[model]["study_runs"].sort(key=lambda run: (
            wave.pilot_tasks.assignments(
                (ROOT / run["source_path"]).read_text()
            )["CONTRACT"]["shard_index"]
        ))
    verify_post_repair_original_monitor(after=latest_replacement_end)
    collection.verify_completed_prefix(specs, 11)
    return specs


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--quota-gate", action="store_true")
    group.add_argument("--verify-run", action="store_true")
    group.add_argument("--discover-run-specs", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    if args.quota_gate:
        result = evaluate_quota()
    elif args.verify_run:
        if args.model is None or args.shard_index is None or args.run_root is None:
            raise ValueError("B repair run verification requires model, shard and run root")
        result = verify_downloaded_replacement_run(
            model=args.model, shard_index=args.shard_index,
            run_root=args.run_root,
        )
    elif args.discover_run_specs:
        result = discover_completed_run_specs()
    else:
        result = verify_manifest()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
