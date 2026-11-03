"""Seal and independently verify the complete Terra-low defense collection.

Kaggle's successful task status is only transport evidence.  This verifier
pins every downloaded artifact, regenerates each uploaded source byte for byte,
replays the strict ledger and prompt-linked defense audit, checks the Kaggle
metadata, and proves that the four arms are a disjoint exhaustive 120-job /
600-call partition.  Charged failed calls remain part of the cost ledger.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
from pathlib import Path

import audit_round2_defense
from build_hosted_cell_v2 import build_source, plan_cell
import four_observation_defenses as defenses
from round2_hosted import raw_event_summary, subset_summary, validate_resume_ledger
import verify_round2_terra_defense_tasks as task_verifier
import verify_round2_terra_study_collection as study_verifier


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "round2_generated/terra_defense_collection_v1.json"
MODEL = "openai/gpt-5.6-terra"
MODEL_SLUG = "gpt-5.6-terra"
REASONING = "low"
STUDY_ID = "chronos_round2_terra_reasoning_defense_low_v1"
FROZEN_AT = "2026-09-20T20:54:19+03:30"
PARENT_COLLECTION_HASH = (
    "99fb3f5d22d48bfcaa4d151702494c2e1ff78178c8b30011dbcb5fab37d4f253"
)
TASKS_MANIFEST_HASH = (
    "8947d4a7aa2cc096a91de0baf47ed841e05248c98aff999709e54aa239909faa"
)
PRIOR_KNOWN_DAILY_COST_USD = 6.968902
DEFENSE_KNOWN_COST_USD = 1.586954
KNOWN_DAILY_COST_USD = 8.555856
DAILY_LIMIT_USD = 10.0


def _execution(arm: str, label: str, run_id: int) -> dict:
    task = task_verifier._task(arm, label)
    run_root = (
        HERE
        / "round2_runs_20260920"
        / f"terra_defense_low_{label}"
        / task
        / "1"
        / MODEL_SLUG
        / str(run_id)
    )
    return {
        "arm": arm,
        "label": label,
        "task": task,
        "run_id": run_id,
        "run_root": run_root,
        "output_root": run_root / task_verifier._folder(arm),
        "source": task_verifier._source(label),
    }


EXECUTIONS = (
    _execution("undefended_natural", "natural", 2668878),
    _execution("undefended_attack", "attack", 2668894),
    _execution("randomized", "randomized", 2668893),
    _execution("invariant", "invariant", 2668879),
)

TOP_LEVEL_KEYS = {
    "schema",
    "defense_collection_manifest_sha256",
    "frozen_at",
    "model",
    "reasoning",
    "study_id",
    "parent_study_collection_manifest_sha256",
    "prelaunch_tasks_manifest_sha256",
    "arm_count",
    "job_count",
    "planned_calls",
    "daily_limit_usd",
    "totals",
    "arms",
}
ARM_KEYS = {
    "arm",
    "task",
    "task_version",
    "run_id",
    "model",
    "started_at",
    "finished_at",
    "status",
    "source",
    "artifacts",
    "accounting",
    "hosted_audit_passed",
}
ACCOUNTING_KEYS = {
    "job_count",
    "planned_calls",
    "observed_invocations",
    "failed_calls",
    "unknown_cost_calls",
    "known_cost_usd",
}
FILE_RECORD_KEYS = {"path", "sha256", "bytes"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _manifest_hash(manifest: dict) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key != "defense_collection_manifest_sha256"
    }
    return _canonical_hash(body)


def _equal(left, right) -> bool:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _require_equal(left, right, label: str) -> None:
    if not _equal(left, right):
        raise ValueError(f"{label} differs")


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": _repo_relative(path),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _artifact_paths(execution: dict) -> dict[str, Path]:
    task = execution["task"]
    root = execution["run_root"]
    output = execution["output_root"]
    prefix = f"{task}-run_id_Run_1_openai_gpt-5.6-terra"
    return {
        "task": root / f"{task}.task.json",
        "run": root / f"{prefix}.run.json",
        "result": root / f"{prefix}.result.json",
        "atif": root / f"{prefix}.atif.json",
        "intended_manifest": output / "intended_manifest.json",
        "audit": output / "audit.json",
        "evidence": output / "openai_gpt-5.6-terra.jsonl",
    }


def _assignments(source: str, path: Path) -> dict:
    values = {}
    for node in ast.parse(source, str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def _read_pinned(record: dict, expected: Path, label: str) -> bytes:
    if set(record) != FILE_RECORD_KEYS:
        raise ValueError(f"invalid pinned file record: {label}")
    path = (ROOT / record["path"]).resolve()
    if path != expected.resolve():
        raise ValueError(f"pinned path changed: {label}")
    if path != ROOT.resolve() and ROOT.resolve() not in path.parents:
        raise ValueError(f"pinned path escapes repository: {label}")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
        raise ValueError(f"pinned hash/size mismatch: {label}")
    return raw


def _json(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _source_values(raw: bytes, path: Path) -> tuple[dict, list[dict]]:
    values = _assignments(raw.decode("utf-8"), path)
    required = {
        "CONTRACT",
        "EXPECTED_JOBS",
        "MODEL",
        "REASONING",
        "STUDY_ID",
        "KIND",
        "OUTPUT_FOLDER",
        "INCREMENTAL_CEILING_USD",
        "MAX_WAIT_SECONDS",
        "RESUME_LEDGER",
    }
    if not required <= set(values):
        raise ValueError("generated defense source assignments are incomplete")
    return values, values["EXPECTED_JOBS"]


def _build_arm_record(execution: dict) -> dict:
    artifacts = _artifact_paths(execution)
    evidence = artifacts["evidence"].read_bytes()
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    result = json.loads(artifacts["result"].read_text())
    audit = json.loads(artifacts["audit"].read_text())
    source_raw = execution["source"].read_bytes()
    _, jobs = _source_values(source_raw, execution["source"])
    accounting = {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "observed_invocations": summary["observed_invocations"],
        "failed_calls": summary["failed_calls"],
        "unknown_cost_calls": summary["unknown_cost_calls"],
        "known_cost_usd": round(summary["known_cost_usd"], 12),
    }
    return {
        "arm": execution["arm"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
        "status": "complete_strictly_verified",
        "source": _file_record(execution["source"]),
        "artifacts": {
            label: _file_record(path) for label, path in artifacts.items()
        },
        "accounting": accounting,
        "hosted_audit_passed": audit.get("passed"),
    }


def build_manifest() -> dict:
    """Build the proposed immutable manifest from the downloaded files."""
    arms = [_build_arm_record(execution) for execution in EXECUTIONS]
    defense_cost = round(
        math.fsum(arm["accounting"]["known_cost_usd"] for arm in arms), 12
    )
    totals = {
        "completed_jobs": sum(arm["accounting"]["job_count"] for arm in arms),
        "planned_calls": sum(
            arm["accounting"]["planned_calls"] for arm in arms
        ),
        "observed_invocations": sum(
            arm["accounting"]["observed_invocations"] for arm in arms
        ),
        "failed_calls": sum(
            arm["accounting"]["failed_calls"] for arm in arms
        ),
        "unknown_cost_calls": sum(
            arm["accounting"]["unknown_cost_calls"] for arm in arms
        ),
        "defense_known_cost_usd": defense_cost,
        "prior_known_daily_cost_usd": PRIOR_KNOWN_DAILY_COST_USD,
        "known_daily_cost_usd": round(
            PRIOR_KNOWN_DAILY_COST_USD + defense_cost, 12
        ),
        "remaining_daily_credit_usd": round(
            DAILY_LIMIT_USD - PRIOR_KNOWN_DAILY_COST_USD - defense_cost, 12
        ),
    }
    manifest = {
        "schema": "chronos.round2.terra-defense-collection.v1",
        "defense_collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "parent_study_collection_manifest_sha256": PARENT_COLLECTION_HASH,
        "prelaunch_tasks_manifest_sha256": TASKS_MANIFEST_HASH,
        "arm_count": 4,
        "job_count": 120,
        "planned_calls": 600,
        "daily_limit_usd": DAILY_LIMIT_USD,
        "totals": totals,
        "arms": arms,
    }
    manifest["defense_collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Terra defense collection manifest schema")
    if _manifest_hash(manifest) != manifest["defense_collection_manifest_sha256"]:
        raise ValueError("Terra defense collection manifest self-hash mismatch")
    if (
        manifest["schema"] != "chronos.round2.terra-defense-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["study_id"] != STUDY_ID
        or manifest["parent_study_collection_manifest_sha256"]
        != PARENT_COLLECTION_HASH
        or manifest["prelaunch_tasks_manifest_sha256"] != TASKS_MANIFEST_HASH
        or manifest["arm_count"] != 4
        or manifest["job_count"] != 120
        or manifest["planned_calls"] != 600
        or manifest["daily_limit_usd"] != DAILY_LIMIT_USD
    ):
        raise ValueError("Terra defense collection top-level contract changed")
    return manifest


def _uploaded_definition(source: str, task: str) -> str:
    marker = f"@kbench.task(name={task!r})"
    start = source.rindex(marker)
    end = source.index("\nhosted_cell.run", start)
    return source[start:end].rstrip("\n") + "\n"


def _verify_metadata(record: dict, source: str, blobs: dict[str, bytes]) -> None:
    task = _json(blobs["task"], "task metadata")
    run = _json(blobs["run"], "run metadata")
    result = _json(blobs["result"], "result metadata")
    atif = _json(blobs["atif"], "ATIF metadata")
    name = record["task"]
    definition = _uploaded_definition(source, name)
    if task != {"versionNumber": 1, "name": name, "definition": definition}:
        raise ValueError("downloaded defense task differs from regenerated source")
    run_task = run.get("taskVersion") or {}
    if (
        run_task.get("versionNumber") != 1
        or run_task.get("name") != name
        or run_task.get("definition") != definition
        or run.get("modelVersion", {}).get("slug") != MODEL
        or run.get("pyRunId") != f"{name}-Run #1"
        or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or run.get("startTime") != record["started_at"]
        or run.get("endTime") != record["finished_at"]
    ):
        raise ValueError("downloaded defense run metadata changed")
    if (
        result.get("task_name") != name
        or result.get("trial_name") != f"{name}-Run #1"
        or result.get("started_at") != record["started_at"]
        or result.get("finished_at") != record["finished_at"]
        or result.get("agent_info", {}).get("model_info", {}).get("name")
        != MODEL
        or result.get("verifier_result", {}).get("rewards", {}).get("score")
        != 1.0
    ):
        raise ValueError("downloaded defense result metadata changed")
    kbench = atif.get("extra", {}).get("kbench", {})
    atif_task = kbench.get("task_version", {})
    if (
        atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != f"{name}-Run #1"
        or atif.get("trajectory_id") != f"{name}-Run #1"
        or atif.get("agent", {}).get("model_name") != MODEL
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != name
        or atif_task.get("definition") != definition
        or kbench.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or kbench.get("end_time") != record["finished_at"]
    ):
        raise ValueError("downloaded defense ATIF metadata changed")


def _configure_engine(contract: dict):
    previous = (
        defenses.STUDY_ID,
        defenses.engine.STUDY_ID,
        defenses.engine.CALL_SETTINGS,
        defenses.engine.MODELS,
    )
    defenses.STUDY_ID = contract["study_id"]
    defenses.engine.STUDY_ID = contract["study_id"]
    defenses.engine.CALL_SETTINGS = {
        key: value
        for key, value in contract["call_settings"].items()
        if key != "sdk_max_retries"
    }
    defenses.engine.MODELS = (MODEL,)
    return previous


def _restore_engine(previous) -> None:
    (
        defenses.STUDY_ID,
        defenses.engine.STUDY_ID,
        defenses.engine.CALL_SETTINGS,
        defenses.engine.MODELS,
    ) = previous


def _verify_arm(execution: dict, record: dict) -> dict:
    arm = execution["arm"]
    if set(record) != ARM_KEYS:
        raise ValueError(f"invalid Terra defense arm record: {arm}")
    expected_identity = {
        "arm": arm,
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "status": "complete_strictly_verified",
        "hosted_audit_passed": True,
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise ValueError(f"defense arm execution identity changed: {arm}")
    if set(record["accounting"]) != ACCOUNTING_KEYS:
        raise ValueError(f"defense arm accounting schema changed: {arm}")

    source_raw = _read_pinned(
        record["source"], execution["source"], f"defense source {arm}"
    )
    source = source_raw.decode("utf-8")
    regenerated = build_source(**task_verifier._arguments(arm, execution["label"]))
    if source != regenerated:
        raise ValueError(f"defense source is not byte-exact regeneration: {arm}")
    compile(source, str(execution["source"]), "exec")
    values, jobs = _source_values(source_raw, execution["source"])
    contract = values["CONTRACT"]
    if (
        values["MODEL"] != MODEL
        or values["REASONING"] != REASONING
        or values["STUDY_ID"] != STUDY_ID
        or values["KIND"] != "defense"
        or values["OUTPUT_FOLDER"] != task_verifier._folder(arm)
        or values["INCREMENTAL_CEILING_USD"] != 0.7
        or values["MAX_WAIT_SECONDS"] != 7200
        or values["RESUME_LEDGER"] != b""
        or contract["arm"] != arm
        or contract["model"] != MODEL
        or contract["reasoning"] != REASONING
        or contract["study_id"] != STUDY_ID
        or (contract["shard_index"], contract["shard_count"]) != (0, 1)
        or (contract["job_count"], contract["planned_calls"]) != (30, 150)
        or contract["incremental_ceiling_usd"] != 0.7
        or contract["effective_ceiling_usd"] != 0.7
        or contract["accepted_preflight_receipt_sha256"]
        != task_verifier.RECEIPT_HASH
        or contract["minimal_unsupported_receipt_sha256"]
        != task_verifier.MINIMAL_HASH
    ):
        raise ValueError(f"defense source contract changed: {arm}")

    expected_artifacts = _artifact_paths(execution)
    if set(record["artifacts"]) != set(expected_artifacts):
        raise ValueError(f"defense artifact set changed: {arm}")
    blobs = {
        label: _read_pinned(
            record["artifacts"][label], path, f"defense {arm} {label}"
        )
        for label, path in expected_artifacts.items()
    }
    result = _json(blobs["result"], "result metadata")
    if (
        record["started_at"] != result.get("started_at")
        or record["finished_at"] != result.get("finished_at")
    ):
        raise ValueError(f"defense recorded timestamps changed: {arm}")
    intended = _json(blobs["intended_manifest"], "intended manifest")
    expected_intended = dict(
        contract, jobs=jobs, seed_audit=contract["resume_ledger"]
    )
    _require_equal(intended, expected_intended, f"intended manifest {arm}")

    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError(f"defense evidence is not newline terminated: {arm}")
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    previous = _configure_engine(contract)
    try:
        def structural(candidate: list[dict]) -> dict:
            return audit_round2_defense.audit(
                candidate,
                MODEL,
                expected_jobs=jobs,
                require_complete=False,
            )

        ledger = validate_resume_ledger(
            events,
            model=MODEL,
            identity=contract["identity"],
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=structural,
        )
        strict = structural(events)
        subset = subset_summary(events, {job["id"] for job in jobs})
    finally:
        _restore_engine(previous)

    if (
        ledger["completed_jobs"] != 30
        or ledger["incomplete_jobs"]
        or strict["complete"] is not True
        or strict["completed_jobs"] != 30
        or strict["missing_jobs"]
        or strict["complete_trial_calls"] != 150
        or strict["unknown_cost_calls"] != 0
        or strict["observed_invocations"] != summary["observed_invocations"]
        or strict["failed_calls"] != summary["failed_calls"]
        or subset["complete"] is not True
        or subset["completed_jobs"] != 30
        or subset["missing_job_ids"]
        or subset["planned_job_ids"] != 30
        or subset["unknown_cost_calls"] != 0
        or summary["completed_jobs"] != 30
        or summary["unknown_cost_calls"] != 0
    ):
        raise ValueError(f"defense strict completion audit failed: {arm}")
    _require_equal(strict["known_cost_usd"], summary["known_cost_usd"], f"strict cost {arm}")

    audit = _json(blobs["audit"], "hosted audit")
    if (
        audit.get("passed") is not True
        or "audit_failed" in audit
        or audit.get("allocation_exhausted") is not False
        or audit.get("stopped_early") is not None
        or audit.get("terminal_error") is not None
        or audit.get("parent_prefix_preserved") is not True
        or audit.get("evidence_sha256") != _sha256(evidence)
    ):
        raise ValueError(f"defense hosted audit did not pass cleanly: {arm}")
    for key, value in contract.items():
        _require_equal(audit.get(key), value, f"hosted contract {arm} {key}")
    _require_equal(audit["ledger_audit"], ledger, f"hosted ledger {arm}")
    _require_equal(audit["structural_audit"], strict, f"hosted strict audit {arm}")
    _require_equal(audit["subset"], subset, f"hosted subset {arm}")
    _require_equal(audit["raw_accounting"], summary, f"hosted accounting {arm}")
    _require_equal(
        audit["new_suffix_accounting"], summary, f"hosted suffix accounting {arm}"
    )
    _verify_metadata(record, source, blobs)

    actual_accounting = {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "observed_invocations": summary["observed_invocations"],
        "failed_calls": summary["failed_calls"],
        "unknown_cost_calls": summary["unknown_cost_calls"],
        "known_cost_usd": summary["known_cost_usd"],
    }
    _require_equal(record["accounting"], actual_accounting, f"arm accounting {arm}")
    if actual_accounting["known_cost_usd"] > contract["incremental_ceiling_usd"]:
        raise ValueError(f"defense arm exceeded its cost ceiling: {arm}")
    return {"arm": arm, "jobs": jobs, "accounting": actual_accounting}


def verify(manifest_value: dict | None = None) -> dict:
    """Verify every pinned file, execution, budget, and cross-arm invariant."""
    manifest = _load_manifest(manifest_value)
    parent = study_verifier.verify()
    staged = task_verifier.verify()
    if (
        parent["collection_manifest_sha256"] != PARENT_COLLECTION_HASH
        or not math.isclose(
            parent["known_daily_cost_usd"],
            PRIOR_KNOWN_DAILY_COST_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or staged["defense_tasks_manifest_sha256"] != TASKS_MANIFEST_HASH
        or staged["job_count"] != 120
        or staged["planned_calls"] != 600
    ):
        raise ValueError("Terra defense parent or prelaunch contract changed")
    if not isinstance(manifest["arms"], list) or len(manifest["arms"]) != 4:
        raise ValueError("Terra defense collection must contain four arms")
    records = {record.get("arm"): record for record in manifest["arms"]}
    if len(records) != 4 or set(records) != {item["arm"] for item in EXECUTIONS}:
        raise ValueError("Terra defense arm identities are not exact")
    verified = [
        _verify_arm(execution, records[execution["arm"]])
        for execution in EXECUTIONS
    ]

    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    full = plan_cell(
        kind="defense",
        model=MODEL,
        reasoning=REASONING,
        study_id=STUDY_ID,
    )["jobs"]
    expected_ids = {job["id"] for job in full}
    if (
        len(full) != 120
        or sum(job["calls"] for job in full) != 600
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != expected_ids
    ):
        raise ValueError("Terra defense arms are not a disjoint exhaustive partition")

    accounts = [item["accounting"] for item in verified]
    defense_cost = math.fsum(item["known_cost_usd"] for item in accounts)
    actual_totals = {
        "completed_jobs": sum(item["job_count"] for item in accounts),
        "planned_calls": sum(item["planned_calls"] for item in accounts),
        "observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        ),
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "defense_known_cost_usd": defense_cost,
        "prior_known_daily_cost_usd": parent["known_daily_cost_usd"],
        "known_daily_cost_usd": parent["known_daily_cost_usd"] + defense_cost,
        "remaining_daily_credit_usd": (
            DAILY_LIMIT_USD - parent["known_daily_cost_usd"] - defense_cost
        ),
    }
    _require_equal(manifest["totals"], actual_totals, "defense collection totals")
    if (
        actual_totals["completed_jobs"] != 120
        or actual_totals["planned_calls"] != 600
        or actual_totals["observed_invocations"] != 628
        or actual_totals["failed_calls"] != 7
        or actual_totals["unknown_cost_calls"] != 0
    ):
        raise ValueError("Terra defense collection accounting topology changed")
    _require_equal(defense_cost, DEFENSE_KNOWN_COST_USD, "defense known cost")
    _require_equal(
        actual_totals["known_daily_cost_usd"],
        KNOWN_DAILY_COST_USD,
        "post-defense daily known cost",
    )
    if (
        defense_cost > staged["aggregate_incremental_ceiling_usd"]
        or actual_totals["known_daily_cost_usd"] > DAILY_LIMIT_USD
        or actual_totals["remaining_daily_credit_usd"] < 0
    ):
        raise ValueError("Terra defense collection exceeded an authorized budget")
    return {
        "schema": "chronos.round2.terra-defense-collection-verification.v1",
        "defense_collection_manifest_sha256": manifest[
            "defense_collection_manifest_sha256"
        ],
        "model": MODEL,
        "reasoning": REASONING,
        "arms": 4,
        "completed_jobs": actual_totals["completed_jobs"],
        "planned_calls": actual_totals["planned_calls"],
        "observed_invocations": actual_totals["observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "defense_known_cost_usd": defense_cost,
        "prior_known_daily_cost_usd": actual_totals["prior_known_daily_cost_usd"],
        "known_daily_cost_usd": actual_totals["known_daily_cost_usd"],
        "remaining_daily_credit_usd": actual_totals[
            "remaining_daily_credit_usd"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="write the self-hashed manifest before verifying it",
    )
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST}")
    checked = verify()
    print(
        "PASS Terra low defense: {completed_jobs}/120 jobs, {planned_calls} "
        "planned calls, {observed_invocations} measured invocations, "
        "{failed_calls} charged failures, ${defense_known_cost_usd:.6f} "
        "defense / ${known_daily_cost_usd:.6f} daily total; four arms "
        "disjoint and exhaustive".format(**checked)
    )


if __name__ == "__main__":
    main()
