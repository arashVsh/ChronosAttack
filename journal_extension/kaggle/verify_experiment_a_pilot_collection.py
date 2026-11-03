"""Seal and verify all four downloaded Experiment A pilot runs."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import issue_experiment_a_pilot_receipt_v1 as receipt_issuer
import verify_experiment_a_pilot_tasks as task_verifier


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUN_ROOT = HERE / "round2_runs_20260920" / "experiment_a_pilots"
MANIFEST = GENERATED / "experiment_a_pilot_collection_v1.json"
PRE_PILOT_KNOWN_DAILY_COST_USD = 8.555856
DAILY_LIMIT_USD = 10.0
QUOTA_UI_AFTER_COLLECTION_USD = 8.65

RUNS = (
    {
        "label": "terra_low",
        "model": "openai/gpt-5.6-terra",
        "model_dir": "gpt-5.6-terra",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_terra_low_v1",
        "task": "chronos-r2-water4-pilot-terra-low-v1",
        "output_folder": "round2_water4_pilot_terra_low_v1",
        "source_file": "water4_pilot_terra_low_v1.py",
        "evidence_file": "openai_gpt-5.6-terra.jsonl",
        "run_id": 2674517,
    },
    {
        "label": "gemini_minimal",
        "model": "google/gemini-3.6-flash",
        "model_dir": "gemini-3.6-flash",
        "reasoning": "minimal",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_gemini_minimal_v1",
        "task": "chronos-r2-water4-pilot-gemini-minimal-v1",
        "output_folder": "round2_water4_pilot_gemini_minimal_v1",
        "source_file": "water4_pilot_gemini_minimal_v1.py",
        "evidence_file": "google_gemini-3.6-flash.jsonl",
        "run_id": 2674725,
    },
    {
        "label": "qwen_low",
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "model_dir": "qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_qwen_low_v1",
        "task": "chronos-r2-water4-pilot-qwen-low-v1",
        "output_folder": "round2_water4_pilot_qwen_low_v1",
        "source_file": "water4_pilot_qwen_low_v1.py",
        "evidence_file": "qwen_qwen3-235b-a22b-instruct-2507.jsonl",
        "run_id": 2675684,
    },
    {
        "label": "claude_none",
        "model": "anthropic/claude-sonnet-4-6@default",
        "model_dir": "claude-sonnet-4-6-default",
        "reasoning": "none",
        "role": "reasoning_off_sensitivity",
        "study_id": "chronos_round2_water4_pilot_claude_none_v1",
        "task": "chronos-r2-water4-pilot-claude-none-v1",
        "output_folder": "round2_water4_pilot_claude_none_v1",
        "source_file": "water4_pilot_claude_none_v1.py",
        "evidence_file": "anthropic_claude-sonnet-4-6@default.jsonl",
        "run_id": 2675872,
    },
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _manifest_hash(manifest: dict) -> str:
    return _canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "collection_manifest_sha256"
        }
    )


def _run_root(spec: dict) -> Path:
    return (
        RUN_ROOT
        / spec["label"]
        / spec["task"]
        / "1"
        / spec["model_dir"]
        / str(spec["run_id"])
    )


def paths_for(spec: dict) -> dict[str, Path]:
    root = _run_root(spec)
    output = root / spec["output_folder"]
    metadata_stem = (
        f"{spec['task']}-run_id_Run_1_"
        f"{spec['model'].replace('/', '_').replace('@', '')}"
    )
    return {
        "frozen_source": GENERATED / spec["source_file"],
        "notebook": root / "__notebook__.ipynb",
        "task_metadata": root / f"{spec['task']}.task.json",
        "run_metadata": root / f"{metadata_stem}.run.json",
        "result_metadata": root / f"{metadata_stem}.result.json",
        "atif_metadata": root / f"{metadata_stem}.atif.json",
        "intended_manifest": output / "intended_manifest.json",
        "terminal": output / "pilot_terminal.json",
        "hosted_audit": output / "audit.json",
        "evidence": output / spec["evidence_file"],
        "receipt": output / "pilot_receipt.json",
    }


def _artifact(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _hosted_definition(source: str) -> str:
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "hosted_cell"
    ]
    if len(functions) != 1:
        raise ValueError("frozen source does not contain one hosted_cell")
    function = functions[0]
    start = min(
        [function.lineno]
        + [decorator.lineno for decorator in function.decorator_list]
    )
    lines = source.splitlines(keepends=True)
    return "".join(lines[start - 1 : function.end_lineno])


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _verify_platform_metadata(spec: dict, paths: dict[str, Path]) -> dict:
    source_raw = paths["frozen_source"].read_bytes()
    source = source_raw.decode()
    definition = _hosted_definition(source)
    notebook = _load_json(paths["notebook"], "downloaded notebook")
    cells = notebook.get("cells")
    code_cells = [cell for cell in cells or [] if cell.get("cell_type") == "code"]
    if len(code_cells) != 1:
        raise ValueError("downloaded pilot notebook does not have one code cell")
    notebook_source = "".join(code_cells[0].get("source", []))
    if not source.endswith("\n") or notebook_source != source[:-1]:
        raise ValueError("downloaded notebook is not the exact frozen source")

    task = _load_json(paths["task_metadata"], "task metadata")
    run = _load_json(paths["run_metadata"], "run metadata")
    result = _load_json(paths["result_metadata"], "result metadata")
    atif = _load_json(paths["atif_metadata"], "ATIF metadata")
    task_version = run.get("taskVersion") or {}
    if (
        task.get("versionNumber") != 1
        or task.get("name") != spec["task"]
        or task.get("definition") != definition
        or task_version.get("versionNumber") != 1
        or task_version.get("name") != spec["task"]
        or task_version.get("definition") != definition
        or (run.get("modelVersion") or {}).get("slug") != spec["model"]
        or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or run.get("results")
        != [{"type": "AGGREGATED", "booleanResult": True}]
    ):
        raise ValueError("Kaggle task/run metadata differs from the frozen pilot")
    start, end = run.get("startTime"), run.get("endTime")
    if not start or not end or _parse_time(start) >= _parse_time(end):
        raise ValueError("Kaggle run timestamps are invalid")
    py_run_id = run.get("pyRunId")
    if (
        result.get("task_name") != spec["task"]
        or result.get("trial_name") != py_run_id
        or ((result.get("agent_info") or {}).get("model_info") or {}).get("name")
        != spec["model"]
        or ((result.get("verifier_result") or {}).get("rewards") or {}).get(
            "score"
        )
        != 1.0
        or result.get("started_at") != start
        or result.get("finished_at") != end
    ):
        raise ValueError("Kaggle result metadata differs from the completed run")
    atif_task = ((atif.get("extra") or {}).get("kbench") or {}).get(
        "task_version"
    ) or {}
    if (
        atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != py_run_id
        or atif.get("trajectory_id") != py_run_id
        or (atif.get("agent") or {}).get("model_name") != spec["model"]
        or ((atif.get("final_metrics") or {}).get("extra") or {}).get(
            "kbench_result"
        )
        != {"score": 1.0}
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != spec["task"]
        or atif_task.get("definition") != definition
        or ((atif.get("extra") or {}).get("kbench") or {}).get("state")
        != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or ((atif.get("extra") or {}).get("kbench") or {}).get("end_time")
        != end
    ):
        raise ValueError("ATIF metadata differs from the completed pilot run")
    return {"start_time": start, "end_time": end, "py_run_id": py_run_id}


def _verify_embedded_sources(spec: dict, intended: dict) -> dict:
    source_root = _run_root(spec) / f"{spec['output_folder']}_source"
    expected_hashes = intended.get("source_sha256")
    if not isinstance(expected_hashes, dict):
        raise ValueError("intended manifest has no embedded source hashes")
    records = {}
    for name, expected_hash in sorted(expected_hashes.items()):
        path = source_root / name
        local = HERE / name
        raw = path.read_bytes()
        if raw != local.read_bytes() or _sha256(raw) != expected_hash:
            raise ValueError(f"downloaded embedded source changed: {name}")
        records[name] = _artifact(path)
    return records


def _verify_hosted_audit(audit: dict, receipt: dict) -> None:
    evidence = receipt["evidence"]
    accounting = {
        key: evidence[key]
        for key in (
            "events",
            "invalid_json_lines",
            "accounting_complete",
            "started_attempts",
            "completed_jobs",
            "observed_invocations",
            "complete_calls",
            "failed_calls",
            "known_cost_usd",
            "unknown_cost_calls",
        )
    }
    raw = receipt["raw_revalidation"]
    if (
        audit.get("passed") is not True
        or audit.get("model") != receipt["model"]
        or audit.get("reasoning") != receipt["reasoning"]
        or audit.get("role") != receipt["role"]
        or audit.get("study_id") != receipt["study_id"]
        or audit.get("identity") != receipt["identity"]
        or audit.get("evidence_sha256") != evidence["sha256"]
        or audit.get("terminal_error") is not None
        or audit.get("stopped_early") is not None
        or audit.get("allocation_exhausted") is not False
        or audit.get("transient_waits") != {"count": 0, "seconds": 0}
        or audit.get("raw_accounting") != accounting
        or audit.get("ledger_audit") != raw["ledger"]
        or audit.get("structural_audit") != raw["structural"]
        or audit.get("pilot") != raw["pilot_gate"]
    ):
        raise ValueError("hosted audit disagrees with independent raw revalidation")


def _build_record(spec: dict) -> dict:
    paths = paths_for(spec)
    platform = _verify_platform_metadata(spec, paths)
    intended = _load_json(paths["intended_manifest"], "intended manifest")
    receipt = receipt_issuer.validate_pilot_receipt(
        receipt_raw=paths["receipt"].read_bytes(),
        evidence_raw=paths["evidence"].read_bytes(),
        terminal_raw=paths["terminal"].read_bytes(),
        intended_raw=paths["intended_manifest"].read_bytes(),
        expected_model=spec["model"],
        expected_reasoning=spec["reasoning"],
        expected_role=spec["role"],
        expected_study_id=spec["study_id"],
    )
    _verify_hosted_audit(
        _load_json(paths["hosted_audit"], "hosted audit"), receipt
    )
    embedded = _verify_embedded_sources(spec, intended)
    return {
        **{
            key: spec[key]
            for key in (
                "label",
                "model",
                "reasoning",
                "role",
                "study_id",
                "task",
                "output_folder",
                "run_id",
            )
        },
        "task_version": 1,
        **platform,
        "status": "passed_raw_revalidated",
        "job_count": 2,
        "planned_calls": 10,
        "known_cost_usd": receipt["evidence"]["known_cost_usd"],
        "receipt_sha256": receipt["receipt_sha256"],
        "evidence_sha256": receipt["evidence"]["sha256"],
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
        "embedded_sources": embedded,
    }


def build_manifest() -> dict:
    staged = task_verifier.verify()
    records = [_build_record(spec) for spec in RUNS]
    pilot_cost = math.fsum(record["known_cost_usd"] for record in records)
    known_daily = PRE_PILOT_KNOWN_DAILY_COST_USD + pilot_cost
    remaining = DAILY_LIMIT_USD - known_daily
    manifest = {
        "schema": "chronos.experiment-a-pilot-collection.v1",
        "collection_manifest_sha256": None,
        "status": "complete_raw_revalidated",
        "pilot_tasks_manifest_sha256": staged["pilot_tasks_manifest_sha256"],
        "latest_run_end_utc": max(record["end_time"] for record in records),
        "task_count": 4,
        "job_count": 8,
        "planned_calls": 40,
        "observed_invocations": 40,
        "failed_calls": 0,
        "pre_pilot_known_daily_cost_usd": PRE_PILOT_KNOWN_DAILY_COST_USD,
        "pilot_known_cost_usd": pilot_cost,
        "post_pilot_known_daily_cost_usd": known_daily,
        "daily_limit_usd": DAILY_LIMIT_USD,
        "remaining_daily_credit_usd": remaining,
        "quota_ui_after_collection_usd": QUOTA_UI_AFTER_COLLECTION_USD,
        "quota_ui_display_precision_usd": 0.01,
        "all_pilots_excluded_from_confirmation": True,
        "authorization_is_outcome_independent": True,
        "matched_primary_receipts": 3,
        "reasoning_off_sensitivity_receipts": 1,
        "full_cell_status": "not_started",
        "runs": records,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None) -> dict:
    manifest = json.loads(MANIFEST.read_text()) if value is None else value
    if not isinstance(manifest, dict):
        raise ValueError("Experiment A pilot collection is not an object")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Experiment A pilot collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Experiment A pilot collection differs from raw artifacts")
    receipt_hashes = {record["receipt_sha256"] for record in manifest["runs"]}
    evidence_hashes = {record["evidence_sha256"] for record in manifest["runs"]}
    if (
        len(receipt_hashes) != 4
        or len(evidence_hashes) != 4
        or manifest["post_pilot_known_daily_cost_usd"] > DAILY_LIMIT_USD
        or not math.isclose(
            manifest["remaining_daily_credit_usd"],
            1.35422583,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Experiment A pilot receipts collide or exceed budget")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['collection_manifest_sha256']}")
    checked = verify()
    for run in checked["runs"]:
        print(
            f"PASS {run['label']}: {run['job_count']} jobs / "
            f"{run['planned_calls']} calls, ${run['known_cost_usd']:.8f}, "
            f"receipt {run['receipt_sha256']}"
        )
    print(
        "EXPERIMENT A PILOTS SEALED: 8 jobs / 40 calls / 0 failures; "
        f"pilot cost ${checked['pilot_known_cost_usd']:.8f}; "
        f"daily remaining ${checked['remaining_daily_credit_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
