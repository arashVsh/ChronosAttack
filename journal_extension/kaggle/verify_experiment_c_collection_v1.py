"""Seal and replay the local Experiment C collection without Kaggle access.

The collection JSON is an index, not evidence. Every listed run is checked
against its downloaded platform metadata, generated source, prelaunch receipt,
embedded modules, terminal, and strict raw JSONL audit. Missing shards remain
explicitly partial; their planned calls are never reported as observations.
"""

from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

import audit_experiment_c_v1 as auditor
import build_experiment_c_cell_v1 as builder
import capture_browser_quota_v1 as browser_quota
import experiment_c_protocol_v1 as protocol
import experiment_c_selection_v1 as selections
import stage_experiment_c_tasks_v1 as staging
from round2_hosted import parse_jsonl_bytes, raw_event_summary, validate_resume_ledger


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "kaggle/round2_generated/experiment_c_collection_v1.json"
SCHEMA = "chronos.experiment-c-collection.v1"
ARTIFACT_KEYS = frozenset({
    "frozen_source", "contract", "prelaunch_receipt", "notebook",
    "task_metadata", "run_metadata", "result_metadata", "atif_metadata",
    "evidence", "terminal",
})
METADATA_PATTERNS = {
    "run_metadata": "*.run.json",
    "result_metadata": "*.result.json",
    "atif_metadata": "*.atif.json",
}
RUN_KEYS = frozenset({
    "shard_index", "task_name", "run_root", "run_id", "task_version",
    "artifacts", "embedded_sources", "parent_ledger", "complete",
    "completed_job_ids", "observed_invocations", "failed_calls",
    "known_cost_usd", "unknown_cost_calls",
})
CELL_KEYS = frozenset({
    "model", "reasoning", "role", "status", "stop_reason", "raw_ledgers",
    "completed_jobs", "planned_calls", "observed_invocations",
    "failed_calls", "known_cost_usd", "unknown_cost_calls",
})


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _path(value: str | Path) -> Path:
    if not isinstance(value, str) or not value.startswith("kaggle/"):
        raise ValueError("C artifact paths must be repo-relative under kaggle/")
    relative = Path(value)
    if (relative.is_absolute() or relative.as_posix() != value
            or any(part in (".", "..") for part in relative.parts)):
        raise ValueError("C artifact path is not canonical")
    resolved = (ROOT / relative).resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("C artifact escapes the repository")
    return resolved


def _input_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else ROOT / path).resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("C run input is outside the repository")
    return resolved


def pin_artifact(path: Path) -> dict:
    """Pin an existing local artifact by canonical repo-relative path and bytes."""
    resolved = _input_path(path)
    if not resolved.is_file():
        raise ValueError("C artifact to pin is not a file")
    raw = resolved.read_bytes()
    return {"path": str(resolved.relative_to(ROOT.resolve())),
            "sha256": _sha256(raw), "bytes": len(raw)}


def _artifact(record: dict, *, expected: Path | None = None) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
        raise ValueError("C artifact pin needs path, SHA-256 and byte count")
    path = _path(record["path"])
    if expected is not None and path != expected.resolve(strict=True):
        raise ValueError("C artifact is at the wrong path")
    digest, length = record["sha256"], record["bytes"]
    if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(length) is not int or length < 0 or not path.is_file()):
        raise ValueError("C artifact pin is malformed")
    raw = path.read_bytes()
    if len(raw) != length or _sha256(raw) != digest:
        raise ValueError(f"C artifact byte/SHA mismatch: {record['path']}")
    return path, raw


def _verify_browser_quota_predecessor(quota: dict) -> None:
    """Rebuild a browser attestation from one byte-pinned earlier run."""
    context = quota.get("run_context")
    if not isinstance(context, dict):
        raise ValueError("C browser quota is missing its predecessor context")
    matches = []
    snapshots = sorted((ROOT / "kaggle/round2_generated").glob(
        "experiment_c_collection_*snapshot_v1.json"
    ))
    for manifest_path in (
        ROOT / "kaggle/round2_generated/experiment_b_collection_v1.json",
        *snapshots,
        MANIFEST,
    ):
        if not manifest_path.is_file():
            continue
        manifest = _json(manifest_path.read_bytes(), "predecessor collection")
        body = {key: value for key, value in manifest.items()
                if key != "collection_sha256"}
        if manifest.get("collection_sha256") != _digest(body):
            raise ValueError("C quota predecessor collection self-hash mismatch")
        for cell in manifest.get("cells", []):
            for run in cell.get("raw_ledgers", []):
                artifacts = run.get("artifacts", {})
                evidence = artifacts.get("evidence", {})
                terminal = artifacts.get("terminal", {})
                if (run.get("task_name") == context.get("task")
                        and evidence.get("sha256") == context.get("evidence_sha256")
                        and terminal.get("sha256") == context.get("terminal_sha256")):
                    pair = (evidence, terminal)
                    if pair not in matches:
                        matches.append(pair)
    if len(matches) != 1:
        raise ValueError("C browser quota predecessor is not uniquely sealed")
    evidence_raw = _artifact(matches[0][0])[1]
    terminal_raw = _artifact(matches[0][1])[1]
    browser_quota.verify_attestation(quota, evidence_raw, terminal_raw)


def _normalize_consistency_transport(events: list[dict]) -> list[dict]:
    """Undo only JSON's tuple-to-list conversion before the frozen audit.

    The hosted audit compares its Python tuple for each permutation against a
    JSON-decoded list. This representation bug does not alter any decision or
    vote; the raw bytes remain separately pinned and accounted for.
    """
    normalized = copy.deepcopy(events)
    for event in normalized:
        if (event.get("event") == "job_complete"
                and (event.get("job") or {}).get("mode") == "order_consistency_24"):
            decisions = event.get("consistency_decisions")
            if not isinstance(decisions, list):
                raise ValueError("C consistency decisions are not a JSON list")
            for row in decisions:
                if not isinstance(row, dict) or not isinstance(row.get("order"), list):
                    raise ValueError("C consistency order is not a JSON list")
                row["order"] = tuple(row["order"])
    return normalized


def _one(root: Path, pattern: str) -> Path:
    matches = list(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one C platform artifact matching {pattern}")
    return matches[0]


def _json(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"C {label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"C {label} must be an object")
    return value


def _literal_assignments(source: str) -> dict:
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                pass
    return result


def _hosted_definition(source: str) -> str:
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "experiment_c"]
    if len(functions) != 1:
        raise ValueError("C source does not contain exactly one experiment_c task")
    node = functions[0]
    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
    return "".join(source.splitlines(keepends=True)[start - 1:node.end_lineno])


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("C platform timestamp is missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("C platform timestamp lacks timezone")
    return result


def _notebook_path(run_root: Path) -> Path:
    # Kaggle exports notebook-mode runs as __notebook__.ipynb and script-mode
    # runs as __script__.ipynb. A run must have exactly one downloaded source.
    candidates = [run_root / name for name in ("__notebook__.ipynb", "__script__.ipynb")]
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise ValueError("C run requires exactly one downloaded notebook or script")
    return found[0]


def _platform(run: dict, paths: dict[str, Path], source: str, model: str) -> dict:
    definition = _hosted_definition(source)
    notebook = _json(paths["notebook"].read_bytes(), "downloaded notebook")
    cells = notebook.get("cells")
    code = [cell for cell in cells or [] if isinstance(cell, dict) and cell.get("cell_type") == "code"]
    # Browser-imported notebook cells can drop the final newline. Kaggle's
    # script-mode export instead prepends this exact cell marker to the source.
    hosted_code = "".join(code[0].get("source", [])) if len(code) == 1 else None
    if paths["notebook"].name == "__script__.ipynb":
        allowed = ("# %% [code]\n" + source,)
    else:
        allowed = (source[:-1], source)
    if (len(code) != 1 or not source.endswith("\n")
            or hosted_code not in allowed):
        raise ValueError("C downloaded notebook differs from frozen hosted source")
    task = _json(paths["task_metadata"].read_bytes(), "task metadata")
    metadata = _json(paths["run_metadata"].read_bytes(), "run metadata")
    result = _json(paths["result_metadata"].read_bytes(), "result metadata")
    atif = _json(paths["atif_metadata"].read_bytes(), "ATIF metadata")
    version = metadata.get("taskVersion") or {}
    number = version.get("versionNumber")
    if (type(number) is not int or number < 1
            or type(run["task_version"]) is not int or run["task_version"] != number
            or task.get("versionNumber") != number
            or task.get("name") != run["task_name"]
            or task.get("definition") != definition
            or version.get("name") != run["task_name"]
            or version.get("definition") != definition
            or (metadata.get("modelVersion") or {}).get("slug") != model
            or metadata.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
            or metadata.get("results") != [{"type": "AGGREGATED", "booleanResult": True}]):
        raise ValueError("C platform task/run metadata differs from frozen source")
    start, end = metadata.get("startTime"), metadata.get("endTime")
    if _time(start) >= _time(end):
        raise ValueError("C platform run timestamps are invalid")
    py_run_id = metadata.get("pyRunId")
    if (not isinstance(py_run_id, str) or not py_run_id
            or result.get("task_name") != run["task_name"]
            or result.get("trial_name") != py_run_id
            or ((result.get("agent_info") or {}).get("model_info") or {}).get("name") != model
            or ((result.get("verifier_result") or {}).get("rewards") or {}).get("score") != 1.0
            or result.get("started_at") != start or result.get("finished_at") != end):
        raise ValueError("C result metadata disagrees with Kaggle run")
    atif_task = ((atif.get("extra") or {}).get("kbench") or {}).get("task_version") or {}
    if (atif.get("schema_version") != "ATIF-v1.7"
            or atif.get("session_id") != py_run_id or atif.get("trajectory_id") != py_run_id
            or (atif.get("agent") or {}).get("model_name") != model
            or ((atif.get("final_metrics") or {}).get("extra") or {}).get("kbench_result") != {"score": 1.0}
            or atif_task.get("version_number") != number
            or atif_task.get("name") != run["task_name"]
            or atif_task.get("definition") != definition
            or ((atif.get("extra") or {}).get("kbench") or {}).get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
            or ((atif.get("extra") or {}).get("kbench") or {}).get("end_time") != end):
        raise ValueError("C ATIF metadata disagrees with Kaggle run")
    run_root = paths["notebook"].parent
    if (not run_root.name.isdecimal() or int(run_root.name) != run["run_id"]
            or type(run["run_id"]) is not int or run["run_id"] < 1):
        raise ValueError("C run ID does not match downloaded run directory")
    return {"run_id": run["run_id"], "task_version": number,
            "py_run_id": py_run_id, "start_time": start, "end_time": end}


def _source_and_receipt(run: dict, task: dict, staged: dict,
                        paths: dict[str, Path], raws: dict[str, bytes]) -> tuple[dict, dict, bytes]:
    source = raws["frozen_source"].decode("utf-8")
    literals = _literal_assignments(source)
    if staging.discovered_task_names(source) != [task["task_name"]]:
        raise ValueError("C hosted source is not statically discoverable")
    contract = _json(raws["contract"], "shard contract")
    receipt = _json(raws["prelaunch_receipt"], "prelaunch receipt")
    seal = next(item for item in staged["selection_seals"] if item["model"] == task["model"])
    selection = _json((ROOT / seal["path"]).read_bytes(), "selection seal")
    selections.validate_selection(selection, model=task["model"], reasoning=task["reasoning"])
    if (literals.get("SOURCES") != builder._source_texts()[0]
            or literals.get("SOURCE_HASHES") != staged["source_module_sha256"]
            or literals.get("SELECTION") != selection
            or literals.get("CONTRACT") != contract
            or literals.get("MODEL") != task["model"]
            or literals.get("TASK") != task["task_name"]
            or literals.get("OUTPUT_FOLDER") != task["output_folder"]
            or not isinstance(literals.get("RESUME_SEED"), bytes)):
        raise ValueError("C hosted source literals differ from staged contract")
    seed = literals["RESUME_SEED"]
    expected = {
        "model": task["model"], "reasoning": task["reasoning"], "role": task["role"],
        "shard_index": task["shard_index"], "shard_count": 30,
        "expected_job_ids": task["expected_job_ids"],
        "jobs_manifest_sha256": task["jobs_manifest_sha256"],
        "job_count": task["jobs"], "planned_calls": task["planned_calls"],
        "identity": task["identity"],
        "selection_manifest_sha256": task["selection_manifest_sha256"],
        "source_sha256": staged["source_module_sha256"],
        "builder_sha256": staged["hosted_builder_sha256"],
    }
    if (contract.get("schema") != "chronos.experiment-c-shard-contract.v1"
            or contract.get("study_id") != protocol.STUDY_ID
            or any(contract.get(key) != value for key, value in expected.items())
            or contract.get("source_log_sha256") != selection["source_log_sha256"]
            or contract.get("amendment_sha256") != selections.AMENDMENT_SHA256
            or contract.get("contract_sha256") != _digest({
                key: value for key, value in contract.items() if key != "contract_sha256"
            })
            or contract.get("parent_ledger_sha256") != (_sha256(seed) if seed else None)
            or type(contract.get("ceiling_usd")) not in (int, float)
            or not math.isfinite(contract["ceiling_usd"])
            or not 0 < contract["ceiling_usd"] <= task["max_ceiling_usd"]):
        raise ValueError("C hosted contract differs from staged shard")
    quota = contract.get("quota_attestation") or {}
    quota_body = {key: value for key, value in quota.items() if key != "attestation_sha256"}
    quota_gate = contract.get("quota_gate") or {}
    response = quota.get("response") or {}
    used, allowed = response.get("daily_quota_used_usd"), response.get("total_daily_quota_allowed_usd")
    browser_capture = quota.get("schema") == browser_quota.BROWSER_SCHEMA
    if browser_capture:
        _verify_browser_quota_predecessor(quota)
    if (quota.get("schema") not in (builder.quota_capture.SCHEMA, browser_quota.BROWSER_SCHEMA)
            or quota.get("endpoint") != (browser_quota.BROWSER_ENDPOINT if browser_capture
                                             else builder.quota_capture.ENDPOINT)
            or quota.get("attestation_sha256") != _digest(quota_body)
            or type(used) not in (int, float) or type(allowed) not in (int, float)
            or not math.isfinite(used) or not math.isfinite(allowed)
            or not 0 <= used <= allowed <= 10
            or used + contract["ceiling_usd"] > allowed
            or quota_gate != {"attestation_sha256": quota["attestation_sha256"],
                              "used_usd": used, "allowed_usd": allowed,
                              "remaining_usd": allowed - used}):
        raise ValueError("C prelaunch quota attestation/ceiling differs from contract")
    actual_source_path = run["artifacts"]["frozen_source"]["path"]
    if actual_source_path != staging._source_path(task, seed):
        raise ValueError("C resume source path is not derived from the pinned parent")
    receipt_body = {
        "schema": "chronos.experiment-c-prelaunch-receipt.v1",
        "staged_manifest_sha256": staged["staged_manifest_sha256"],
        "task_name": task["task_name"],
        "source_path": actual_source_path,
        "source_sha256": _sha256(raws["frozen_source"]),
        "contract_sha256": contract["contract_sha256"],
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "selection_manifest_sha256": task["selection_manifest_sha256"],
        "experiment_b_analysis_sha256": (contract.get("sequence_gate") or {}).get("experiment_b_analysis_sha256"),
        "fresh_quota_attestation_sha256": quota["attestation_sha256"],
        "ceiling_usd": contract["ceiling_usd"],
        "launch_authorized": True,
    }
    if (receipt != {**receipt_body, "receipt_sha256": _digest(receipt_body)}
            or not isinstance(receipt["experiment_b_analysis_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt["experiment_b_analysis_sha256"]) is None):
        raise ValueError("C prelaunch receipt differs from staged source/contract")
    # The saved JSON sorts keys, while the hosted Python literal retains the
    # builder's insertion order. Equality above proves identical values; use
    # the literal to reproduce its exact source bytes.
    regenerated = builder.build_source(
        contract=literals["CONTRACT"], selection=selection, task_name=task["task_name"],
        output_folder=task["output_folder"], resume_seed=seed,
    )
    if source != regenerated:
        raise ValueError("C hosted source differs from deterministic regeneration")
    source_root = paths["notebook"].parent / (task["output_folder"] + "_source")
    if (not isinstance(run.get("embedded_sources"), dict)
            or set(run["embedded_sources"]) != set(builder.SOURCE_FILES)):
        raise ValueError("C downloaded embedded source set is incomplete")
    for name in builder.SOURCE_FILES:
        _, raw = _artifact(run["embedded_sources"][name], expected=source_root / name)
        if raw != (builder.HERE / name).read_bytes() or _sha256(raw) != staged["source_module_sha256"][name]:
            raise ValueError(f"C downloaded embedded source changed: {name}")
    return contract, selection, seed


def _verify_run(run: dict, task: dict, staged: dict, *, require_claims: bool = True) -> dict:
    if (not isinstance(run, dict) or set(run) != RUN_KEYS
            or run["task_name"] != task["task_name"]
            or run["shard_index"] != task["shard_index"]):
        raise ValueError("C run does not match one staged task/shard")
    run_root = _path(run["run_root"])
    output = run_root / task["output_folder"]
    source_path = _path(run["artifacts"]["frozen_source"]["path"])
    expected = {
        "frozen_source": source_path,
        "contract": source_path.with_suffix(".contract.json"),
        "prelaunch_receipt": source_path.with_suffix(".prelaunch.json"),
        "notebook": _notebook_path(run_root),
        "task_metadata": run_root / f"{task['task_name']}.task.json",
        "evidence": output / (task["model"].replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
    }
    expected.update({key: _one(run_root, pattern) for key, pattern in METADATA_PATTERNS.items()})
    if not isinstance(run.get("artifacts"), dict) or set(run["artifacts"]) != ARTIFACT_KEYS:
        raise ValueError("C run artifact set is incomplete")
    paths, raws = {}, {}
    for key, record in run["artifacts"].items():
        paths[key], raws[key] = _artifact(record, expected=expected[key])
    contract, selection, seed = _source_and_receipt(run, task, staged, paths, raws)
    platform = _platform(run, paths, raws["frozen_source"].decode("utf-8"), task["model"])
    parent = b"" if run["parent_ledger"] is None else _artifact(run["parent_ledger"])[1]
    if parent != seed or (parent and not parent.endswith(b"\n")):
        raise ValueError("C parent ledger differs from hosted resume seed")
    jobs = {job["id"]: job for job in protocol.jobs_for(task["model"], selection)
            if job["id"] in set(task["expected_job_ids"])}
    structural = lambda rows: auditor.audit(
        _normalize_consistency_transport(rows), task["model"], selection, require_complete=False,
        expected_job_ids=set(task["expected_job_ids"]),
    )
    parent_events = parse_jsonl_bytes(parent, label="C parent ledger")
    checked_seed = validate_resume_ledger(
        parent_events, model=task["model"], identity=task["identity"],
        expected_jobs=jobs, structural_audit=structural,
    )
    if checked_seed != contract["resume_ledger"]:
        raise ValueError("C parent ledger accounting differs from prelaunch contract")
    evidence = raws["evidence"]
    if (not evidence.startswith(parent) or (evidence and not evidence.endswith(b"\n"))):
        raise ValueError("C raw evidence lost the exact parent prefix or final newline")
    events = parse_jsonl_bytes(evidence, label="C raw ledger")
    audit = structural(events)
    accounting = raw_event_summary(events)
    completed_ids = [event["job"]["id"] for event in events if event["event"] == "job_complete"]
    if (len(completed_ids) != len(set(completed_ids))
            or audit["completed_jobs"] != len(completed_ids)
            or audit["observed_invocations"] != accounting["observed_invocations"]
            or audit["failed_calls"] != accounting["failed_calls"]
            or audit["unknown_cost_calls"] != accounting["unknown_cost_calls"]
            or not math.isclose(audit["known_cost_usd"], accounting["known_cost_usd"], rel_tol=0, abs_tol=1e-12)):
        raise ValueError("C strict audit and raw cost/accounting disagree")
    terminal = _json(raws["terminal"], "hosted terminal")
    stopped = terminal.get("stopped_early")
    complete = bool(audit["complete"] and stopped is None)
    transport_bug = "ValueError('24-order decisions/vote inputs changed')"
    hosted_bug = (terminal.get("status") == "stopped"
                  and terminal.get("audit_error") == transport_bug
                  and terminal.get("audit") is None)
    expected_terminal = {
        "schema": "chronos.experiment-c-hosted-terminal.v1",
        "task": task["task_name"],
        "contract_sha256": contract["contract_sha256"],
        "status": "stopped" if hosted_bug else "complete" if complete else "stopped",
        "stopped_early": stopped,
        "audit_error": transport_bug if hosted_bug else None,
        "audit": None if hosted_bug else audit,
        "raw_accounting": accounting,
    }
    if (terminal != expected_terminal
            or stopped is not None and (not isinstance(stopped, str) or not stopped)):
        raise ValueError("C hosted terminal differs from strict raw replay")
    claims = {
        "complete": complete,
        "completed_job_ids": sorted(completed_ids),
        "observed_invocations": accounting["observed_invocations"],
        "failed_calls": accounting["failed_calls"],
        "known_cost_usd": accounting["known_cost_usd"],
        "unknown_cost_calls": accounting["unknown_cost_calls"],
    }
    if require_claims and any(run[key] != value for key, value in claims.items()):
        raise ValueError("C run summary differs from strict raw replay")
    return {
        "shard_index": task["shard_index"], "task_name": task["task_name"],
        "run_id": platform["run_id"], "task_version": platform["task_version"],
        "complete": complete, "completed_job_ids": claims["completed_job_ids"],
        "planned_calls": task["planned_calls"],
        "observed_invocations": claims["observed_invocations"],
        "failed_calls": claims["failed_calls"],
        "known_cost_usd": claims["known_cost_usd"],
        "unknown_cost_calls": claims["unknown_cost_calls"],
        "stop_reason": stopped if not complete else None,
        "path": run["artifacts"]["evidence"]["path"],
        "sha256": run["artifacts"]["evidence"]["sha256"],
        "terminal_path": run["artifacts"]["terminal"]["path"],
        "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
        "source_path": run["artifacts"]["frozen_source"]["path"],
        "source_sha256": run["artifacts"]["frozen_source"]["sha256"],
        "contract_sha256": contract["contract_sha256"],
        "prelaunch_receipt_sha256": run["artifacts"]["prelaunch_receipt"]["sha256"],
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "platform": platform,
    }


def _cell(model: str, reasoning: str, role: str, runs: list[dict],
          stop_reason: str | None, staged: dict) -> dict:
    if not isinstance(runs, list):
        raise ValueError("C cell runs must be an ordered list")
    tasks = {task["shard_index"]: task for task in staged["tasks"] if task["model"] == model}
    checked = []
    previous_run = None
    previous_check = None
    for run in runs:
        index = run.get("shard_index") if isinstance(run, dict) else None
        if type(index) is not int or index not in tasks:
            raise ValueError("C run has an invalid staged shard index")
        if previous_run is None:
            if (index != 0 or run["parent_ledger"] is not None
                    or type(run.get("task_version")) is not int or run["task_version"] != 1):
                raise ValueError("C cell must start at shard zero, version one, without a parent")
        elif index == previous_run["shard_index"]:
            if previous_check["complete"]:
                raise ValueError("C attempted a new version after shard completion")
            current_version, prior_version = run.get("task_version"), previous_run.get("task_version")
            if (run["parent_ledger"] != previous_run["artifacts"]["evidence"]
                    or run["task_name"] != previous_run["task_name"]
                    or type(current_version) is not int or type(prior_version) is not int
                    or current_version != prior_version + 1):
                raise ValueError("C resume is not an exact chained task version")
        else:
            if (index != previous_run["shard_index"] + 1
                    or not previous_check["complete"]
                    or run["parent_ledger"] is not None
                    or type(run.get("task_version")) is not int or run["task_version"] != 1):
                raise ValueError("C shards are not a clean contiguous prefix")
        replayed = _verify_run(run, tasks[index], staged)
        if previous_run is not None and index == previous_run["shard_index"]:
            predecessor = previous_run["artifacts"]["evidence"]
            _, previous_raw = _artifact(predecessor)
            _, current_raw = _artifact(run["artifacts"]["evidence"])
            if not current_raw.startswith(previous_raw):
                raise ValueError("C resumed evidence lost the previous run's raw prefix")
            suffix = current_raw[len(previous_raw):]
            if suffix and not suffix.endswith(b"\n"):
                raise ValueError("C resumed raw suffix is not newline terminated")
            suffix_summary = raw_event_summary(parse_jsonl_bytes(suffix, label="C novel run suffix"))
            history = checked[-1]["run_history"]
            checked.pop()
        else:
            _, suffix = _artifact(run["artifacts"]["evidence"])
            suffix_summary = raw_event_summary(parse_jsonl_bytes(suffix, label="C first run ledger"))
            history = []
        history.append({
            "run_id": replayed["run_id"], "task_version": replayed["task_version"],
            "path": replayed["path"], "sha256": replayed["sha256"],
            "source_path": replayed["source_path"],
            "prelaunch_receipt_sha256": replayed["prelaunch_receipt_sha256"],
            "novel_observed_invocations": suffix_summary["observed_invocations"],
            "novel_failed_calls": suffix_summary["failed_calls"],
            "novel_known_cost_usd": suffix_summary["known_cost_usd"],
            "novel_unknown_cost_calls": suffix_summary["unknown_cost_calls"],
        })
        if (sum(item["novel_observed_invocations"] for item in history)
                != replayed["observed_invocations"]
                or sum(item["novel_failed_calls"] for item in history)
                != replayed["failed_calls"]
                or sum(item["novel_unknown_cost_calls"] for item in history)
                != replayed["unknown_cost_calls"]
                or not math.isclose(math.fsum(item["novel_known_cost_usd"] for item in history),
                                    replayed["known_cost_usd"], rel_tol=0, abs_tol=1e-12)):
            raise ValueError("C chained run suffix accounting differs from cumulative raw")
        checked.append({**replayed, "run_history": history})
        previous_run, previous_check = run, replayed
    if len(checked) > 30 or any(not record["complete"] for record in checked[:-1]):
        raise ValueError("C partial shard may occur only at the prefix tail")
    completed_ids = [job_id for record in checked for job_id in record["completed_job_ids"]]
    if len(completed_ids) != len(set(completed_ids)):
        raise ValueError("C collection duplicates a completed job ID")
    status = ("not_started" if not checked else "complete" if len(checked) == 30
              and all(record["complete"] for record in checked) else "study_partial")
    if status == "complete":
        if stop_reason is not None or len(completed_ids) != 180 or sum(
            record["planned_calls"] for record in checked
        ) != (1380 if model in protocol.REVERSE_MODELS else 1350):
            raise ValueError("C complete cell lacks all 30 shards and 180 jobs")
    elif not isinstance(stop_reason, str) or not stop_reason.strip():
        raise ValueError("C partial/not-started cell needs an explicit stop reason")
    return {
        "model": model, "reasoning": reasoning, "role": role,
        "status": status, "stop_reason": stop_reason,
        "raw_ledgers": checked,
        "completed_jobs": len(completed_ids),
        "planned_calls": sum(record["planned_calls"] for record in checked),
        "observed_invocations": sum(record["observed_invocations"] for record in checked),
        "failed_calls": sum(record["failed_calls"] for record in checked),
        "known_cost_usd": math.fsum(record["known_cost_usd"] for record in checked),
        "unknown_cost_calls": sum(record["unknown_cost_calls"] for record in checked),
    }


def _pin_run(run_root: Path, source_path: Path, task: dict,
             parent_ledger_path: Path | None = None) -> dict:
    root = _input_path(run_root)
    source = _input_path(source_path)
    if not source.is_relative_to((ROOT / "kaggle/round2_generated").resolve()):
        raise ValueError("C source is outside round2_generated")
    output = root / task["output_folder"]
    files = {
        "frozen_source": source,
        "contract": source.with_suffix(".contract.json"),
        "prelaunch_receipt": source.with_suffix(".prelaunch.json"),
        "notebook": _notebook_path(root),
        "task_metadata": root / f"{task['task_name']}.task.json",
        "run_metadata": _one(root, "*.run.json"),
        "result_metadata": _one(root, "*.result.json"),
        "atif_metadata": _one(root, "*.atif.json"),
        "evidence": output / (task["model"].replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
    }
    metadata = _json(files["run_metadata"].read_bytes(), "run metadata")
    source_root = root / (task["output_folder"] + "_source")
    return {
        "shard_index": task["shard_index"], "task_name": task["task_name"],
        "run_root": str(root.relative_to(ROOT.resolve())),
        "run_id": int(root.name),
        "task_version": (metadata.get("taskVersion") or {}).get("versionNumber"),
        "artifacts": {name: pin_artifact(path) for name, path in files.items()},
        "embedded_sources": {name: pin_artifact(source_root / name)
                             for name in builder.SOURCE_FILES},
        "parent_ledger": pin_artifact(parent_ledger_path) if parent_ledger_path else None,
        "complete": None, "completed_job_ids": None,
        "observed_invocations": None, "failed_calls": None,
        "known_cost_usd": None, "unknown_cost_calls": None,
    }


def build_manifest_from_runs(run_specs: dict[str, dict]) -> dict:
    """Seal four explicit local run lists; never discover or fetch remote runs.

    Each model maps to ``{"runs": [{"shard_index", "run_root", "source_path",
    "parent_ledger_path"?}], "stop_reason": str|None}``. Incomplete cells
    require a human-written reason. A resumed run lists the exact parent JSONL.
    """
    staged = staging.verify_manifest()
    models = [model for model, _, _ in staging.SELECTIONS]
    if not isinstance(run_specs, dict) or set(run_specs) != set(models):
        raise ValueError("C run specs must contain exactly the four frozen settings")
    cells, normalized_cells = [], []
    for model, reasoning, _ in staging.SELECTIONS:
        spec = run_specs[model]
        if (not isinstance(spec, dict) or set(spec) != {"runs", "stop_reason"}
                or not isinstance(spec["runs"], list)):
            raise ValueError("C run spec must contain runs and stop_reason")
        pinned = []
        for item in spec["runs"]:
            if (not isinstance(item, dict)
                    or not {"shard_index", "run_root", "source_path"} <= set(item)
                    or set(item) - {"shard_index", "run_root", "source_path", "parent_ledger_path"}
                    or type(item["shard_index"]) is not int
                    or not 0 <= item["shard_index"] < 30):
                raise ValueError("C shard run spec is incomplete")
            task = next(task for task in staged["tasks"]
                        if task["model"] == model and task["shard_index"] == item["shard_index"])
            record = _pin_run(item["run_root"], item["source_path"], task,
                              item.get("parent_ledger_path"))
            # The raw replay supplies all six claims; no operator-entered outcome.
            checked = _verify_run(record, task, staged, require_claims=False)
            record.update({key: checked[key] for key in (
                "complete", "completed_job_ids", "observed_invocations",
                "failed_calls", "known_cost_usd", "unknown_cost_calls",
            )})
            pinned.append(record)
        role = next(item["role"] for item in staged["selection_seals"] if item["model"] == model)
        normalized = _cell(model, reasoning, role, pinned, spec["stop_reason"], staged)
        normalized_cells.append(normalized)
        cells.append({key: normalized[key] if key != "raw_ledgers" else pinned for key in CELL_KEYS})
    _unique_runs(cells)
    _unique_completed(normalized_cells)
    body = {
        "schema": SCHEMA,
        "status": "complete_raw_revalidated" if all(cell["status"] == "complete" for cell in cells)
                  else "partial_raw_revalidated",
        "staged_manifest_sha256": staged["staged_manifest_sha256"],
        "cells": cells,
    }
    return {**body, "collection_sha256": _digest(body)}


def _unique_runs(cells: list[dict]) -> None:
    task_run_ids, source_paths, task_owners, shard_owners = set(), set(), {}, {}
    for cell in cells:
        for run in cell["raw_ledgers"]:
            run_id = run["run_id"]
            source_path = run["artifacts"]["frozen_source"]["path"]
            task_name = run["task_name"]
            shard = (cell["model"], run["shard_index"])
            task_run_id = (task_name, run_id)
            if task_run_id in task_run_ids or source_path in source_paths:
                raise ValueError("C collection duplicates a run ID or immutable source")
            if (task_name in task_owners and task_owners[task_name] != shard
                    or shard in shard_owners and shard_owners[shard] != task_name):
                raise ValueError("C collection duplicates a task/shard identity")
            task_run_ids.add(task_run_id)
            source_paths.add(source_path)
            task_owners[task_name] = shard
            shard_owners[shard] = task_name


def _unique_completed(cells: list[dict]) -> None:
    completed = set()
    for cell in cells:
        for ledger in cell["raw_ledgers"]:
            ids = ledger["completed_job_ids"]
            if len(ids) != len(set(ids)) or completed & set(ids):
                raise ValueError("C collection duplicates completed job IDs")
            completed.update(ids)


def verify_collection_manifest(path: Path = MANIFEST) -> dict:
    """Return normalized cells after strict byte-pinned local raw replay."""
    manifest = _json(Path(path).read_bytes(), "collection manifest")
    if set(manifest) != {"schema", "status", "staged_manifest_sha256", "cells", "collection_sha256"}:
        raise ValueError("C collection manifest schema is incomplete")
    body = {key: value for key, value in manifest.items() if key != "collection_sha256"}
    if manifest["collection_sha256"] != _digest(body):
        raise ValueError("C collection self-hash mismatch")
    staged = staging.verify_manifest()
    if (manifest["schema"] != SCHEMA
            or manifest["staged_manifest_sha256"] != staged["staged_manifest_sha256"]
            or not isinstance(manifest["cells"], list) or len(manifest["cells"]) != 4):
        raise ValueError("C collection staged topology mismatch")
    normalized = []
    for cell, (model, reasoning, _) in zip(manifest["cells"], staging.SELECTIONS):
        seal = next(item for item in staged["selection_seals"] if item["model"] == model)
        if (not isinstance(cell, dict) or set(cell) != CELL_KEYS
                or (cell["model"], cell["reasoning"], cell["role"])
                != (model, reasoning, seal["role"])):
            raise ValueError("C collection cell roster mismatch")
        checked = _cell(model, reasoning, seal["role"], cell["raw_ledgers"],
                        cell["stop_reason"], staged)
        if any(cell[key] != checked[key] for key in CELL_KEYS if key != "raw_ledgers"):
            raise ValueError("C collection cell summary differs from raw replay")
        normalized.append(checked)
    _unique_runs(manifest["cells"])
    _unique_completed(normalized)
    expected_status = "complete_raw_revalidated" if all(
        cell["status"] == "complete" for cell in normalized
    ) else "partial_raw_revalidated"
    if manifest["status"] != expected_status:
        raise ValueError("C collection status differs from cell completion")
    return {
        "schema": SCHEMA, "status": expected_status,
        "collection_sha256": manifest["collection_sha256"],
        "staged_manifest_sha256": staged["staged_manifest_sha256"],
        "cells": normalized,
        "completed_jobs": sum(cell["completed_jobs"] for cell in normalized),
        "planned_calls": sum(cell["planned_calls"] for cell in normalized),
        "observed_invocations": sum(cell["observed_invocations"] for cell in normalized),
        "failed_calls": sum(cell["failed_calls"] for cell in normalized),
        "known_cost_usd": math.fsum(cell["known_cost_usd"] for cell in normalized),
        "unknown_cost_calls": sum(cell["unknown_cost_calls"] for cell in normalized),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--output", type=Path, default=MANIFEST)
    args = parser.parse_args()
    if args.run_specs is None:
        result = verify_collection_manifest(args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    specs = _json(args.run_specs.read_bytes(), "run specs")
    result = build_manifest_from_runs(specs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(args.output, result["collection_sha256"])


if __name__ == "__main__":
    main()
