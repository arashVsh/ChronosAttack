"""Stage and verify B study waves only after strict prior-shard raw seals."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol
import experiment_b_quota_gate_v1 as quota_gate
import verify_experiment_b_final_collection_v1 as collection
import verify_experiment_b_pilot_tasks as pilot_tasks
import verify_experiment_b_remaining_study_plan_v1 as remaining
import verify_experiment_b_study_batch00_tasks as batch00


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MAX_SHARDS_PER_WAVE = 5


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def manifest_path(start: int, stop: int) -> Path:
    return GENERATED / f"experiment_b_study_wave_s{start:02d}_s{stop:02d}_tasks_v1.json"


def _validate_wave(start: int, stop: int) -> None:
    if (
        type(start) is not int or type(stop) is not int
        or not 1 <= start <= stop < builder.SHARD_COUNT
        or stop - start + 1 > MAX_SHARDS_PER_WAVE
    ):
        raise ValueError("B wave must be 1–5 contiguous shards in s01–s29")


def _post_repair_monitor(start: int, progress: dict) -> dict | None:
    """Pin the post-replacement zero-run check into every later wave."""
    if start <= 10:
        return None
    import verify_experiment_b_transport_repair_v1 as repair

    required = (collection.FIRST_TRANSPORT_REPAIR_SHARDS if start <= 20
                else collection.TRANSPORT_REPAIR_SHARDS)
    repaired_ends = {}
    for cell in progress["collection_manifest"]["cells"]:
        model = cell["model_id"]
        for run in cell["raw_ledgers"]:
            key = (model, run["shard_index"])
            if key in required:
                repaired_ends[key] = datetime.fromisoformat(
                    collection._run_end_utc(run).replace("Z", "+00:00")
                )
    if set(repaired_ends) != required:
        raise ValueError(f"B later wave is missing one of {len(required)} repaired raw runs")
    if start <= 20:
        return repair.verify_post_repair_original_monitor(after=max(repaired_ends.values()))
    import verify_experiment_b_transport_repair_s18_s19_v1 as second_repair

    return second_repair.verify_post_repair_original_monitor(
        after=max(repaired_ends.values())
    )


def _fresh_original_monitor(start: int, progress: dict) -> dict | None:
    """Recheck source-less original v1 tasks after each completed later wave."""
    if start < 16:
        return None
    import verify_experiment_b_transport_repair_v1 as repair

    prior_end = datetime.fromisoformat(
        progress["last_run"]["run_end_utc"].replace("Z", "+00:00")
    )
    if start <= 20:
        return repair.verify_fresh_original_monitor(
            wave_start=start, after=prior_end
        )
    import verify_experiment_b_transport_repair_s18_s19_v1 as second_repair

    return second_repair.verify_fresh_original_monitor(
        wave_start=start, after=prior_end
    )


def build_wave(*, start: int, stop: int, run_specs: dict) -> tuple[dict[str, str], dict]:
    """Return byte-exact source texts and a staged task manifest; write nothing."""
    _validate_wave(start, stop)
    planned = remaining.verify()
    progress = collection.verify_completed_prefix(run_specs, start)
    if progress["completed_shards_per_cell"] != start:
        raise ValueError("B wave does not follow the strictly completed shard prefix")
    post_repair_monitor = _post_repair_monitor(start, progress)
    fresh_original_monitor = _fresh_original_monitor(start, progress)
    remaining_plan = json.loads(remaining.MANIFEST.read_text())
    frozen_entries = {
        (entry["model"], entry["shard_index"]): entry
        for entry in remaining_plan["shards"]
    }
    pilots = {model: batch00._pilot(model) for model in batch00.PILOT_RUNS}
    sources = {}
    tasks = []
    all_ids = set()
    for index in range(start, stop + 1):
        for model in batch00.PILOT_RUNS:
            planned_task = frozen_entries[(model, index)]
            checked, raw = pilots[model]
            receipt = checked["receipt"]
            ceiling = builder.study_ceiling_from_pilot(receipt)
            if (
                planned_task["pilot_receipt_sha256"] != receipt["receipt_sha256"]
                or planned_task["incremental_ceiling_usd"] != ceiling
            ):
                raise ValueError("B remaining plan no longer matches the passed pilot")
            source = builder.build_source(
                model=model, phase="study", shard_index=index,
                task_name=planned_task["task_name"],
                output_folder=planned_task["output_folder"],
                ceiling_usd=ceiling,
                pilot_receipt=receipt,
                pilot_evidence=raw["evidence"],
                pilot_terminal=raw["terminal"],
                pilot_intended=raw["intended"],
            )
            source_bytes = source.encode()
            source_path = planned_task["source_path"]
            sources[source_path] = source
            plan = builder.plan_cell(model=model, phase="study", shard_index=index)
            ids = {job["id"] for job in plan["jobs"]}
            if len(ids) != 6 or ids & all_ids:
                raise ValueError("B study wave has duplicate trial jobs")
            all_ids.update(ids)
            tasks.append({
                **{key: value for key, value in planned_task.items() if key != "source_sha256"},
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_bytes": len(source_bytes),
                "pilot_evidence_sha256": checked["evidence_sha256"],
                "pilot_terminal_sha256": checked["terminal_sha256"],
                "pilot_intended_sha256": checked["intended_manifest_sha256"],
            })
    body = {
        "schema": "chronos.experiment-b-study-batch.v1",
        "batch": f"s{start:02d}-s{stop:02d}",
        "status": "staged_after_strict_prior_prefix",
        "launch_authorized": False,
        "fixture_manifest_sha256": remaining_plan["fixture_manifest_sha256"],
        "pilot_tasks_manifest_sha256": remaining_plan["pilot_tasks_manifest_sha256"],
        "remaining_plan_sha256": planned["remaining_plan_sha256"],
        "prior_progress_sha256": progress["progress_sha256"],
        "prior_collection_sha256": progress["collection_sha256"],
        "prior_last_run": progress["last_run"],
        **({"post_repair_original_monitor": post_repair_monitor}
           if post_repair_monitor is not None else {}),
        **({"fresh_original_monitor": fresh_original_monitor}
           if fresh_original_monitor is not None else {}),
        "run_specs": run_specs,
        "start_shard_index": start,
        "stop_shard_index": stop,
        "task_count": len(tasks),
        "jobs": sum(task["job_count"] for task in tasks),
        "planned_calls": sum(task["planned_calls"] for task in tasks),
        "aggregate_ceiling_usd": round(sum(
            task["incremental_ceiling_usd"] for task in tasks
        ), 9),
        "tasks": tasks,
    }
    return sources, {**body, "batch_manifest_sha256": digest(body)}


def verify_wave(path: Path) -> dict:
    saved = json.loads(Path(path).read_text())
    body = {key: value for key, value in saved.items() if key != "batch_manifest_sha256"}
    if saved.get("batch_manifest_sha256") != digest(body):
        raise ValueError("B wave task manifest self-hash mismatch")
    start, stop = saved["start_shard_index"], saved["stop_shard_index"]
    if Path(path).resolve() != manifest_path(start, stop).resolve():
        raise ValueError("B wave task manifest is at the wrong path")
    sources, expected = build_wave(start=start, stop=stop, run_specs=saved["run_specs"])
    if saved != expected:
        raise ValueError("B wave manifest differs from strict prior seal or frozen plan")
    for task in saved["tasks"]:
        source = (ROOT / task["source_path"]).read_text()
        if source != sources[task["source_path"]]:
            raise ValueError("B wave generated source differs from deterministic regeneration")
        compile(source, task["source_path"], "exec")
        if pilot_tasks.discovered_task_names(source) != [task["task_name"]]:
            raise ValueError("B wave task is not statically discoverable")
    return {
        "batch_manifest_sha256": saved["batch_manifest_sha256"],
        "prior_progress_sha256": saved["prior_progress_sha256"],
        "task_count": saved["task_count"],
        "jobs": saved["jobs"],
        "planned_calls": saved["planned_calls"],
        "aggregate_ceiling_usd": saved["aggregate_ceiling_usd"],
        "launch_authorized": False,
    }


def _planned_source_records(*, start: int, stop: int) -> list[tuple[dict, str]]:
    """Regenerate source-only future shards without touching study progress."""
    _validate_wave(start, stop)
    remaining.verify()
    planned = json.loads(remaining.MANIFEST.read_text())
    entries = {
        (entry["model"], entry["shard_index"]): entry
        for entry in planned["shards"]
    }
    pilots = {model: batch00._pilot(model) for model in batch00.PILOT_RUNS}
    records = []
    for index in range(start, stop + 1):
        for model in batch00.PILOT_RUNS:
            entry = entries[(model, index)]
            pilot, raw = pilots[model]
            source = builder.build_source(
                model=model, phase="study", shard_index=index,
                task_name=entry["task_name"], output_folder=entry["output_folder"],
                ceiling_usd=entry["incremental_ceiling_usd"],
                pilot_receipt=pilot["receipt"],
                pilot_evidence=raw["evidence"], pilot_terminal=raw["terminal"],
                pilot_intended=raw["intended"],
            )
            records.append((entry, source))
    return records


def stage_planned_sources(*, start: int, stop: int) -> dict:
    """Write only missing, byte-exact future sources; never authorize launch."""
    records = _planned_source_records(start=start, stop=stop)
    for entry, source in records:
        path = ROOT / entry["source_path"]
        if path.exists() and path.read_bytes() != source.encode():
            raise ValueError("B pre-staged source differs from deterministic regeneration")
    for entry, source in records:
        path = ROOT / entry["source_path"]
        if not path.exists():
            with path.open("x") as file:
                file.write(source)
    return verify_planned_sources(start=start, stop=stop)


def verify_planned_sources(*, start: int, stop: int) -> dict:
    """Check deterministic source bytes without claiming a prior-shard seal."""
    checked = []
    for entry, source in _planned_source_records(start=start, stop=stop):
        path = ROOT / entry["source_path"]
        if path.read_bytes() != source.encode():
            raise ValueError("B pre-staged source differs from deterministic regeneration")
        compile(source, str(path), "exec")
        if pilot_tasks.discovered_task_names(source) != [entry["task_name"]]:
            raise ValueError("B pre-staged task is not statically discoverable")
        checked.append({
            "task_name": entry["task_name"],
            "source_path": entry["source_path"],
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        })
    return {
        "schema": "chronos.experiment-b-prestaged-sources.v1",
        "start_shard_index": start,
        "stop_shard_index": stop,
        "tasks": checked,
        "task_count": len(checked),
        "strict_prior_prefix_checked": False,
        "launch_authorized": False,
    }


def discover_completed_run_specs(
    path: Path, *, through_shard_index: int | None = None,
) -> dict:
    """Find one downloaded run per staged task through a complete shard prefix."""
    verify_wave(path)
    manifest = json.loads(Path(path).read_text())
    start = manifest["start_shard_index"]
    stop = manifest["stop_shard_index"]
    if through_shard_index is not None and (
        type(through_shard_index) is not int
        or not start <= through_shard_index <= stop
    ):
        raise ValueError("B discovery must end within the staged wave")
    selected = [
        task for task in manifest["tasks"]
        if through_shard_index is None
        or task["shard_index"] <= through_shard_index
    ]
    if len(selected) != 2 * (
        (stop if through_shard_index is None else through_shard_index)
        - start + 1
    ):
        raise ValueError("B discovery requires both model tasks per shard")
    result = copy.deepcopy(manifest["run_specs"])
    base = HERE / "round2_runs_20260920/experiment_b_study"
    repair_tasks = {}
    if any((task["model"], task["shard_index"])
           in collection.SECOND_TRANSPORT_REPAIR_SHARDS
           for task in manifest["tasks"]):
        import verify_experiment_b_transport_repair_s18_s19_v1 as second_repair

        second_repair.verify_manifest()
        repair_tasks = {
            (task["model"], task["shard_index"]): task
            for task in json.loads(second_repair.MANIFEST.read_text())["tasks"]
        }
    for task in selected:
        model = task["model"]
        _, _, tag = protocol.CELLS[model]
        model_dir = model.split("/", 1)[1].replace("@", "-")
        repair_task = repair_tasks.get((model, task["shard_index"]))
        task_name = (repair_task["replacement_task_name"] if repair_task
                     else task["task_name"])
        source_path = (repair_task["replacement_source_path"] if repair_task
                       else task["source_path"])
        parent = base / tag.replace("_", "-") / task_name / "1" / model_dir
        candidates = [
            candidate for candidate in parent.iterdir()
            if candidate.is_dir()
            and (candidate / task["output_folder"] / "terminal.json").is_file()
        ] if parent.is_dir() else []
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one downloaded B run for {task_name}")
        result[model]["study_runs"].append({
            "run_root": str(candidates[0].relative_to(ROOT)),
            "source_path": source_path,
        })
    return result


def verify_downloaded_wave_run(
    *, path: Path, model: str, shard_index: int, run_root: Path,
) -> dict:
    """Independently replay one downloaded wave task before the full wave seals."""
    verify_wave(path)
    manifest = json.loads(Path(path).read_text())
    tasks = [
        task for task in manifest["tasks"]
        if task["model"] == model and task["shard_index"] == shard_index
    ]
    if len(tasks) != 1:
        raise ValueError("B downloaded run is not in the staged wave")
    task = tasks[0]
    pilot, raw = batch00._pilot(model)
    raw = {**raw, "intended_manifest": raw["intended"]}
    pinned = collection._pin_run(
        run_root=collection._input_path(run_root), model=model,
        task_name=task["task_name"], output_folder=task["output_folder"],
        source_path=ROOT / task["source_path"],
    )
    pinned.update({"shard_index": shard_index, "parent_ledger": None})
    checked = collection._study_shard(
        pinned, model, pilot, raw, require_claims=False
    )
    return {
        **checked,
        "task_name": task["task_name"],
        "source_sha256": task["source_sha256"],
    }


def evaluate_wave_quota(
    *, path: Path, attestation: dict, evidence: bytes, terminal: bytes,
) -> dict:
    """Bind a fresh official meter to the last strictly pinned prior run."""
    verified = verify_wave(path)
    saved = json.loads(Path(path).read_text())
    last = saved["prior_last_run"]
    context = attestation.get("run_context") or {}
    if (
        context.get("task") != last["task_name"]
        or context.get("model") != last["model_id"]
        or context.get("study_id") != protocol.cell(last["model_id"])["study_id"]
        or context.get("evidence_sha256") != last["evidence_sha256"]
        or context.get("terminal_sha256") != last["terminal_sha256"]
        or hashlib.sha256(evidence).hexdigest() != last["evidence_sha256"]
        or hashlib.sha256(terminal).hexdigest() != last["terminal_sha256"]
        or datetime.fromisoformat(attestation["queried_at_start_utc"].replace("Z", "+00:00"))
        <= datetime.fromisoformat(last["run_end_utc"].replace("Z", "+00:00"))
    ):
        raise ValueError("B wave quota attestation is not tied to the pinned last run")
    fresh_monitor = saved.get("fresh_original_monitor")
    if fresh_monitor is not None and (
        datetime.fromisoformat(attestation["queried_at_start_utc"].replace("Z", "+00:00"))
        <= datetime.fromisoformat(fresh_monitor["latest_capture_end_utc"])
    ):
        raise ValueError("B official quota observation predates the fresh original-v1 monitor")
    quota = quota_gate.evaluate(
        task_manifest=saved, attestation=attestation,
        evidence=evidence, terminal=terminal,
    )
    body = {
        **{key: value for key, value in quota.items() if key != "gate_sha256"},
        "prior_progress_sha256": verified["prior_progress_sha256"],
        "prior_last_run_sha256": last["evidence_sha256"],
        "wave_manifest_sha256": verified["batch_manifest_sha256"],
    }
    return {**body, "gate_sha256": digest(body)}


def stage_wave(*, start: int, stop: int, run_specs: dict) -> dict:
    """Create the manifest after the seal, reusing byte-identical pre-staged sources."""
    sources, manifest = build_wave(start=start, stop=stop, run_specs=run_specs)
    output = manifest_path(start, stop)
    if output.exists():
        raise ValueError("B wave manifest already exists; no overwrite allowed")
    for relative, source in sources.items():
        path = ROOT / relative
        if path.exists() and path.read_bytes() != source.encode():
            raise ValueError("B pre-staged source differs from sealed source; no overwrite allowed")
    for relative, source in sources.items():
        path = ROOT / relative
        if not path.exists():
            with path.open("x") as file:
                file.write(source)
    with output.open("x") as file:
        file.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    verify_wave(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--verify-sources", action="store_true")
    group.add_argument("--stage-sources", action="store_true")
    group.add_argument("--verify-run", action="store_true")
    group.add_argument("--quota-gate", action="store_true")
    parser.add_argument("--start", type=int)
    parser.add_argument("--stop", type=int)
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--prior-wave-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--quota-attestation", type=Path)
    parser.add_argument("--quota-evidence", type=Path)
    parser.add_argument("--quota-terminal", type=Path)
    args = parser.parse_args()
    if args.stage:
        if None in (args.start, args.stop):
            raise ValueError("B wave stage requires shard bounds")
        if (args.run_specs is None) == (args.prior_wave_manifest is None):
            raise ValueError("B wave stage requires exactly one prior-run source")
        run_specs = (
            json.loads(args.run_specs.read_text())
            if args.run_specs is not None else
            discover_completed_run_specs(
                args.prior_wave_manifest,
                through_shard_index=args.start - 1,
            )
        )
        result = stage_wave(
            start=args.start, stop=args.stop,
            run_specs=run_specs,
        )
    elif args.verify:
        if args.manifest is None:
            raise ValueError("B wave verify requires a manifest")
        result = verify_wave(args.manifest)
    elif args.verify_sources or args.stage_sources:
        if None in (args.start, args.stop):
            raise ValueError("B source staging/verification requires shard bounds")
        result = (stage_planned_sources if args.stage_sources else verify_planned_sources)(
            start=args.start, stop=args.stop
        )
    elif args.verify_run:
        if any(value is None for value in (
            args.manifest, args.model, args.shard_index, args.run_root,
        )):
            raise ValueError("B wave run verification requires manifest/model/shard/run root")
        result = verify_downloaded_wave_run(
            path=args.manifest, model=args.model,
            shard_index=args.shard_index, run_root=args.run_root,
        )
    else:
        if any(value is None for value in (
            args.manifest, args.quota_attestation, args.quota_evidence,
            args.quota_terminal,
        )):
            raise ValueError("B wave quota gate requires manifest, attestation and raw prior run")
        result = evaluate_wave_quota(
            path=args.manifest,
            attestation=json.loads(args.quota_attestation.read_text()),
            evidence=args.quota_evidence.read_bytes(),
            terminal=args.quota_terminal.read_bytes(),
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
