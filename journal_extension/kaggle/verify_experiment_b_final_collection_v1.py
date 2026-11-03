"""Verify the final, raw-replayed four-cell Experiment B collection.

The collection manifest is only an index. Every claimed result is rebuilt from
the pinned downloaded bytes, including Kaggle provenance and excluded pilots.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
import re

import build_experiment_b_hosted_v1 as builder
import audit_experiment_b as auditor
import experiment_b_protocol as protocol
import verify_experiment_a_pilot_collection as platform_checks
import verify_experiment_b_collection as raw_checks
import verify_experiment_b_freeze as freeze
import verify_experiment_b_pilot_tasks as pilot_tasks
from round2_hosted import (event_job_id, parse_jsonl_bytes, raw_event_summary,
                           subset_summary, validate_resume_ledger)


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "kaggle/round2_generated/experiment_b_collection_v1.json"
SCHEMA = "chronos.experiment-b-collection.v1"
ARTIFACT_KEYS = frozenset({
    "frozen_source", "notebook", "task_metadata", "run_metadata",
    "result_metadata", "atif_metadata", "evidence", "terminal",
    "intended_manifest", "hosted_audit",
})
METADATA_PATTERNS = {
    "run_metadata": "*.run.json",
    "result_metadata": "*.result.json",
    "atif_metadata": "*.atif.json",
}
FIRST_TRANSPORT_REPAIR_SHARDS = frozenset({
    ("openai/gpt-5.6-terra", 6),
    ("anthropic/claude-sonnet-4-6@default", 6),
    ("openai/gpt-5.6-terra", 7),
})
SECOND_TRANSPORT_REPAIR_SHARDS = frozenset({
    ("anthropic/claude-sonnet-4-6@default", 18),
    ("openai/gpt-5.6-terra", 19),
    ("anthropic/claude-sonnet-4-6@default", 19),
})
TRANSPORT_REPAIR_SHARDS = FIRST_TRANSPORT_REPAIR_SHARDS | SECOND_TRANSPORT_REPAIR_SHARDS


def _study_task_names(model: str, index: int) -> tuple[str, str, Path, Path]:
    _, _, tag = protocol.CELLS[model]
    canonical = f"chronos-r2-tree4-rotation-study-{tag.replace('_', '-')}-s{index:02d}-v1"
    replacement = canonical.removesuffix("-v1") + "-transport-repair-v1"
    original_path = ROOT / "kaggle/round2_generated" / (
        f"tree4_rotation_study_{tag}_s{index:02d}_v1.py"
    )
    repair_path = original_path.with_name(
        f"tree4_rotation_study_{tag}_s{index:02d}_transport_repair_v1.py"
    )
    return canonical, replacement, original_path, repair_path


def _authorized_study_task(model: str, index: int, source_path: Path,
                           literals: dict, source: str) -> str:
    """Bind each scientific shard to exactly one approved transport source."""
    canonical, replacement, original_path, repair_path = _study_task_names(model, index)
    key = (model, index)
    if literals.get("TASK_NAME") != canonical:
        raise ValueError("B source internal frozen task identity changed")
    actual = pilot_tasks.discovered_task_names(source)
    if key in TRANSPORT_REPAIR_SHARDS:
        if source_path != repair_path.resolve(strict=True) or actual != [replacement]:
            raise ValueError("B repaired shard must use its sole approved replacement source")
        return replacement
    if source_path != original_path.resolve(strict=True) or actual != [canonical]:
        raise ValueError("B study shard must use its canonical frozen source")
    return canonical


def _expected_study_source(*, run: dict, model: str, index: int, pilot: dict,
                           pilot_raws: dict, parent: bytes) -> str:
    canonical, replacement, _, repair_path = _study_task_names(model, index)
    task_name = run["task_name"]
    if (model, index) in TRANSPORT_REPAIR_SHARDS:
        if (task_name != replacement
                or _relative_path(run["artifacts"]["frozen_source"]["path"])
                != repair_path.resolve(strict=True)):
            raise ValueError("B repaired shard has an unapproved platform task/source")
    elif task_name != canonical:
        raise ValueError("B study shard has an unapproved platform task")
    original = builder.build_source(
        model=model, phase="study", shard_index=index,
        task_name=canonical,
        output_folder=f"round2_tree4_rotation_study_{protocol.CELLS[model][2]}_s{index:02d}_v1",
        ceiling_usd=builder.study_ceiling_from_pilot(pilot["receipt"]),
        resume_seed=parent, pilot_receipt=pilot["receipt"],
        pilot_evidence=pilot_raws["evidence"],
        pilot_terminal=pilot_raws["terminal"],
        pilot_intended=pilot_raws["intended_manifest"],
    )
    if task_name == canonical:
        return original
    old = f"@kbench.task(name={canonical!r})"
    new = f"@kbench.task(name={replacement!r})"
    if original.count(old) != 1 or new in original:
        raise ValueError("B repaired decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("B repaired study source is not exactly reversible")
    return repaired


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value.startswith("kaggle/"):
        raise ValueError("B collection paths must be repo-relative under kaggle/")
    relative = Path(value)
    if relative.is_absolute() or relative.as_posix() != value or any(
        part in (".", "..") for part in relative.parts
    ):
        raise ValueError("B collection contains a noncanonical artifact path")
    resolved = (ROOT / relative).resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("B collection artifact escapes the repository")
    return resolved


def _artifact(record: dict, *, expected: Path | None = None) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
        raise ValueError("B collection artifact must pin path, SHA-256 and byte count")
    path = _relative_path(record["path"])
    if expected is not None and path != expected.resolve(strict=True):
        raise ValueError("B collection artifact is at the wrong path")
    length = record["bytes"]
    digest = record["sha256"]
    if (isinstance(length, bool) or not isinstance(length, int) or length < 0
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
        raise ValueError("B collection artifact pin is malformed")
    if not path.is_file():
        raise ValueError("B collection artifact is not a file")
    raw = path.read_bytes()
    if len(raw) != length or _sha256(raw) != digest:
        raise ValueError(f"B collection artifact byte/SHA mismatch: {record['path']}")
    return path, raw


def pin_artifact(path: Path) -> dict:
    """Create one repo-relative byte pin for an already downloaded local file."""
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("B artifact to pin must be a repository file")
    raw = resolved.read_bytes()
    return {
        "path": str(resolved.relative_to(ROOT.resolve())),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _one(root: Path, pattern: str) -> Path:
    matches = list(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one B platform artifact matching {pattern}")
    return matches[0]


def _run_artifacts(run: dict, model: str, *, source_path: Path | None = None,
                   receipt_required: bool = False) -> tuple[dict[str, Path], dict[str, bytes]]:
    required = ARTIFACT_KEYS | ({"receipt"} if receipt_required else set())
    if not isinstance(run.get("artifacts"), dict) or set(run["artifacts"]) != required:
        raise ValueError("B collection run artifact set is incomplete")
    run_root = _relative_path(run.get("run_root"))
    output = run_root / run["output_folder"]
    expected = {
        "notebook": run_root / "__notebook__.ipynb",
        "task_metadata": run_root / f"{run['task_name']}.task.json",
        "evidence": output / (model.replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
        "intended_manifest": output / "intended_manifest.json",
        "hosted_audit": output / "audit.json",
    }
    expected.update({key: _one(run_root, pattern) for key, pattern in METADATA_PATTERNS.items()})
    if source_path is not None:
        expected["frozen_source"] = source_path
    paths, raws = {}, {}
    for key, record in run["artifacts"].items():
        paths[key], raws[key] = _artifact(record, expected=expected.get(key))
    if not paths["frozen_source"].is_relative_to(ROOT / "kaggle/round2_generated"):
        raise ValueError("B source must live under round2_generated")
    if paths["frozen_source"].suffix != ".py":
        raise ValueError("B source artifact is not Python")
    if receipt_required and run["artifacts"]["receipt"]["path"] == run["artifacts"]["evidence"]["path"]:
        raise ValueError("B pilot receipt aliases evidence")
    return paths, raws


def _embedded_sources(run: dict, run_root: Path) -> None:
    embedded = run.get("embedded_sources")
    if not isinstance(embedded, dict) or set(embedded) != set(builder.SOURCE_FILES):
        raise ValueError("B collection embedded source set is incomplete")
    source_root = run_root / (run["output_folder"] + "_source")
    for name in builder.SOURCE_FILES:
        _, raw = _artifact(embedded[name], expected=source_root / name)
        if raw != (builder.HERE / name).read_bytes():
            raise ValueError(f"B downloaded embedded source changed: {name}")


def _platform(run: dict, paths: dict[str, Path], model: str) -> dict:
    return platform_checks._verify_platform_metadata(
        {"task": run["task_name"], "model": model}, paths
    )


def _failed_pilot(model: str, raws: dict) -> dict:
    """Replay a stopped one-attempt pilot even when the failed call cost is unknown."""
    evidence = raws["evidence"]
    if not evidence or not evidence.endswith(b"\n"):
        raise ValueError("B failed pilot evidence is not complete JSONL")
    events = parse_jsonl_bytes(evidence, label="B failed pilot ledger")
    plan = builder.plan_cell(model=model, phase="pilot")
    expected_jobs = {job["id"]: job for job in plan["jobs"]}
    structural = auditor.audit(events, model, "pilot", require_complete=False)
    accounting = raw_event_summary(events)
    starts = [event for event in events if event["event"] == "job_started"]
    failed = [event for event in events if event["event"] == "call_failed"]
    job_errors = [event for event in events if event["event"] == "job_error"]
    completed = [event for event in events if event["event"] == "job_complete"]
    expected_ids = [job["id"] for job in plan["jobs"]]
    active = None
    for event in events:
        job_id = event_job_id(event)
        if event["event"] == "job_started":
            if active is not None:
                raise ValueError("B failed pilot interleaves two jobs")
            active = job_id
        elif job_id != active:
            raise ValueError("B failed pilot has an event outside its active job")
        if event["event"] in ("job_complete", "job_error"):
            active = None
    if (not 1 <= len(starts) <= 2
            or [event["job_id"] for event in starts] != expected_ids[:len(starts)]
            or [event["job"]["id"] for event in completed] != expected_ids[:len(completed)]
            or len(completed) != len(starts) - 1
            or len(failed) != 1 or len(job_errors) != 1
            or events[-1] != job_errors[0]
            or failed[0]["job_id"] != job_errors[0]["job"]["id"]
            or failed[0]["error_type"] != job_errors[0]["error_type"]
            or any(event["attempt"] != 1 for event in events)
            or structural["pilot_passed"] is not False
            or structural["completed_jobs"] != len(completed)
            or structural["failed_calls"] != 1
            or structural["job_errors"] != 1
            or structural["unknown_cost_calls"] != 1
            or accounting["unknown_cost_calls"] != 1
            or accounting["failed_calls"] != 1
            or accounting["completed_jobs"] != len(completed)
            or accounting["observed_invocations"] > 10):
        raise ValueError("B failed pilot is not a single stopped first-attempt run")
    # The hosted audit deliberately could not use the resume validator: unknown
    # failed-call cost cannot be re-run or silently converted to zero.
    try:
        validate_resume_ledger(
            events, model=model, identity=plan["identity"],
            expected_jobs=expected_jobs,
            structural_audit=lambda rows: auditor.audit(rows, model, "pilot", require_complete=False),
        )
    except ValueError as error:
        audit_failure = repr(error)
    else:
        raise ValueError("B failed pilot unexpectedly passed resume validation")
    intended = json.loads(raws["intended_manifest"])
    terminal = json.loads(raws["terminal"])
    hosted = json.loads(raws["hosted_audit"])
    _, source_hashes = builder._sources()
    expected_contract = {
        **{key: value for key, value in plan.items() if key != "jobs"},
        "source_sha256": source_hashes,
        "incremental_ceiling_usd": builder.PILOT_CEILING_USD,
        "effective_ceiling_usd": builder.PILOT_CEILING_USD,
        "parent_ledger_sha256": None,
        "pilot_receipt_sha256": None,
        "sdk_max_retries": 0,
    }
    error = terminal.get("error")
    expected_terminal = {
        "schema": "chronos.experiment-b-terminal.v1",
        **protocol.cell(model, "pilot"),
        "identity": plan["identity"],
        "fixture_manifest_sha256": plan["fixture_manifest_sha256"],
        "jobs_sha256": plan["jobs_sha256"],
        "job_ids": expected_ids,
        "planned_calls": 10,
        "call_settings": {**protocol.call_settings(model), "sdk_max_retries": 0},
        "source_sha256": source_hashes,
        "evidence_sha256": _sha256(evidence),
        "parent_ledger_sha256": None,
        "pilot_receipt_sha256": None,
        "error": error,
    }
    if (intended != {**expected_contract, "jobs": plan["jobs"]}
            or terminal != expected_terminal
            or not isinstance(error, dict)
            or error.get("type") != failed[0]["error_type"]
            or not isinstance(error.get("message"), str)
            or not error["message"]
            or hosted != {
                "schema": "chronos.experiment-b-hosted-audit.v1",
                "passed": False,
                "contract": expected_contract,
                "audit_failed": audit_failure,
                "raw_accounting": accounting,
                "parent_prefix_preserved": True,
                "evidence_sha256": _sha256(evidence),
                "terminal_error": error,
                "parse_failures": [],
            }):
        raise ValueError("B failed pilot terminal/audit differs from raw replay")
    return {
        "known_cost_usd": accounting["known_cost_usd"],
        "unknown_cost_calls": accounting["unknown_cost_calls"],
        "observed_invocations": accounting["observed_invocations"],
        "failed_calls": accounting["failed_calls"],
        "completed_jobs": accounting["completed_jobs"],
        "failure_type": error["type"],
        "receipt": None,
    }


def _pilot(run: dict, model: str, frozen_task: dict, *, failed: bool) -> tuple[dict, dict, dict]:
    if (not isinstance(run, dict)
            or set(run) != {"task_name", "output_folder", "run_root", "artifacts",
                             "embedded_sources", "known_cost_usd"}
            or run["task_name"] != frozen_task["task_name"]
            or run["output_folder"] != frozen_task["output_folder"]):
        raise ValueError("B pilot is not the frozen excluded task")
    paths, raws = _run_artifacts(
        run, model, source_path=ROOT / frozen_task["source_path"],
        receipt_required=not failed,
    )
    _embedded_sources(run, _relative_path(run["run_root"]))
    platform = _platform(run, paths, model)
    if failed:
        checked = _failed_pilot(model, raws)
    else:
        checked = raw_checks.verify_raw_pilot(
            model=model, evidence=raws["evidence"], terminal=raws["terminal"],
            intended=raws["intended_manifest"], hosted_audit=raws["hosted_audit"],
        )
        if json.loads(raws["receipt"]) != checked["receipt"]:
            raise ValueError("B pilot receipt differs from raw replay")
        checked = {**checked, "unknown_cost_calls": 0, "failed_calls": 0,
                   "completed_jobs": 2, "failure_type": None}
    if run["known_cost_usd"] != checked["known_cost_usd"]:
        raise ValueError("B pilot known cost differs from raw replay")
    return checked, platform, raws


def _study_shard(run: dict, model: str, pilot: dict, pilot_raws: dict,
                 *, require_claims: bool = True) -> dict:
    required = {"shard_index", "task_name", "output_folder", "run_root", "artifacts",
                "embedded_sources", "parent_ledger"}
    if require_claims:
        required |= {"completed_job_ids", "observed_invocations", "failed_calls", "known_cost_usd"}
    if not isinstance(run, dict) or set(run) != required:
        raise ValueError("B study shard record is incomplete")
    index = run["shard_index"]
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < builder.SHARD_COUNT:
        raise ValueError("B study shard index is invalid")
    paths, raws = _run_artifacts(run, model)
    _embedded_sources(run, _relative_path(run["run_root"]))
    _platform(run, paths, model)
    parent = b"" if run["parent_ledger"] is None else _artifact(run["parent_ledger"])[1]
    source = _expected_study_source(
        run=run, model=model, index=index, pilot=pilot,
        pilot_raws=pilot_raws, parent=parent,
    )
    if raws["frozen_source"] != source.encode():
        raise ValueError("B study source differs from deterministic regeneration")
    checked = raw_checks.verify_raw_study_shard(
        model=model, shard_index=index, evidence=raws["evidence"],
        terminal=raws["terminal"], intended=raws["intended_manifest"],
        hosted_audit=raws["hosted_audit"], parent_ledger=parent,
        pilot_receipt=pilot["receipt"], pilot_evidence=pilot_raws["evidence"],
        pilot_terminal=pilot_raws["terminal"], pilot_intended=pilot_raws["intended_manifest"],
    )
    if require_claims:
        for key in ("completed_job_ids", "observed_invocations", "failed_calls", "known_cost_usd"):
            if run[key] != checked[key]:
                raise ValueError(f"B shard {index} {key} differs from raw replay")
    artifacts = run["artifacts"]
    return {
        **checked,
        "path": artifacts["evidence"]["path"],
        "sha256": artifacts["evidence"]["sha256"],
        "terminal_path": artifacts["terminal"]["path"],
        "terminal_sha256": artifacts["terminal"]["sha256"],
        "intended_path": artifacts["intended_manifest"]["path"],
        "intended_sha256": artifacts["intended_manifest"]["sha256"],
        "audit_path": artifacts["hosted_audit"]["path"],
        "audit_sha256": artifacts["hosted_audit"]["sha256"],
    }


def _partial_study_shard(run: dict, model: str, pilot: dict, pilot_raws: dict,
                         *, require_claims: bool = True) -> dict:
    """Replay one stopped study shard without treating unknown cost as zero."""
    required = {"shard_index", "task_name", "output_folder", "run_root", "artifacts",
                "embedded_sources", "parent_ledger"}
    claims = {"completed_job_ids", "observed_invocations", "failed_calls",
              "known_cost_usd", "unknown_cost_calls"}
    if not isinstance(run, dict) or set(run) != required | (claims if require_claims else set()):
        raise ValueError("B partial study run record is incomplete")
    index = run["shard_index"]
    if type(index) is not int or not 0 <= index < builder.SHARD_COUNT:
        raise ValueError("B partial study shard index is invalid")
    paths, raws = _run_artifacts(run, model)
    _embedded_sources(run, _relative_path(run["run_root"]))
    _platform(run, paths, model)
    parent = b"" if run["parent_ledger"] is None else _artifact(run["parent_ledger"])[1]
    if not raws["evidence"].startswith(parent) or not raws["evidence"].endswith(b"\n"):
        raise ValueError("B partial study ledger lost its parent or final newline")
    source = _expected_study_source(
        run=run, model=model, index=index, pilot=pilot,
        pilot_raws=pilot_raws, parent=parent,
    )
    if raws["frozen_source"] != source.encode():
        raise ValueError("B partial study source differs from deterministic regeneration")
    values = pilot_tasks.assignments(source)
    contract, jobs = values["CONTRACT"], values["EXPECTED_JOBS"]
    intended = json.loads(raws["intended_manifest"])
    terminal = json.loads(raws["terminal"])
    error = terminal.get("error")
    expected_terminal = {
        "schema": "chronos.experiment-b-terminal.v1",
        **protocol.cell(model),
        "identity": contract["identity"],
        "fixture_manifest_sha256": contract["fixture_manifest_sha256"],
        "jobs_sha256": contract["jobs_sha256"],
        "job_ids": [job["id"] for job in jobs],
        "planned_calls": 30,
        "call_settings": {**protocol.call_settings(model), "sdk_max_retries": 0},
        "source_sha256": contract["source_sha256"],
        "evidence_sha256": _sha256(raws["evidence"]),
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "pilot_receipt_sha256": pilot["receipt"]["receipt_sha256"],
        "error": error,
    }
    if intended != {**contract, "jobs": jobs} or terminal != expected_terminal:
        raise ValueError("B partial study terminal/intended contract differs from source")
    events = parse_jsonl_bytes(raws["evidence"], label="B partial study ledger")
    structural = auditor.audit(events, model, "study", require_complete=False)
    accounting = raw_event_summary(events)
    subset = subset_summary(events, {job["id"] for job in jobs})
    if subset["complete"] and accounting["accounting_complete"] and error is None:
        raise ValueError("B partial study run is actually complete")
    hosted = json.loads(raws["hosted_audit"])
    common = {
        "schema": "chronos.experiment-b-hosted-audit.v1",
        "passed": False,
        "contract": contract,
        "raw_accounting": accounting,
        "parent_prefix_preserved": True,
        "evidence_sha256": _sha256(raws["evidence"]),
        "terminal_error": error,
    }
    try:
        ledger = validate_resume_ledger(
            events, model=model, identity=contract["identity"],
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=lambda rows: auditor.audit(rows, model, "study", require_complete=False),
        )
    except ValueError as failure:
        expected_hosted = {
            **common, "audit_failed": repr(failure), "parse_failures": [],
        }
    else:
        expected_hosted = {
            **common, "ledger_audit": ledger, "structural_audit": structural,
            "subset": subset,
        }
    if hosted != expected_hosted:
        raise ValueError("B partial study hosted audit differs from raw replay")
    checked = {
        "model": model,
        "shard_index": index,
        "completed_job_ids": sorted(
            event["job"]["id"] for event in events if event["event"] == "job_complete"
        ),
        "observed_invocations": accounting["observed_invocations"],
        "failed_calls": accounting["failed_calls"],
        "known_cost_usd": accounting["known_cost_usd"],
        "unknown_cost_calls": accounting["unknown_cost_calls"],
        "path": run["artifacts"]["evidence"]["path"],
        "sha256": run["artifacts"]["evidence"]["sha256"],
        "terminal_path": run["artifacts"]["terminal"]["path"],
        "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
        "intended_path": run["artifacts"]["intended_manifest"]["path"],
        "intended_sha256": run["artifacts"]["intended_manifest"]["sha256"],
        "audit_path": run["artifacts"]["hosted_audit"]["path"],
        "audit_sha256": run["artifacts"]["hosted_audit"]["sha256"],
    }
    if require_claims and any(run[key] != checked[key] for key in claims):
        raise ValueError("B partial study summary differs from raw replay")
    return checked


def _input_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else ROOT / path).resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("B run input is outside the repository")
    return resolved


def _transport_repair_groups_used(run_specs: dict) -> set[str]:
    """Recognize receipt groups by resolved source, including local aliases."""
    approved = {
        _study_task_names(model, index)[3].resolve(strict=True): group
        for group, shards in (
            ("first", FIRST_TRANSPORT_REPAIR_SHARDS),
            ("second", SECOND_TRANSPORT_REPAIR_SHARDS),
        )
        for model, index in shards
    }
    return {
        approved[source]
        for spec in run_specs.values() if isinstance(spec, dict)
        for run in [*spec.get("study_runs", []), spec.get("partial_run")]
        if isinstance(run, dict)
        if (source := _input_path(run["source_path"])) in approved
    }


def _uses_transport_repair_source(run_specs: dict) -> bool:
    return bool(_transport_repair_groups_used(run_specs))


def _pin_run(*, run_root: Path, model: str, task_name: str,
             output_folder: str, source_path: Path,
             receipt_path: Path | None = None) -> dict:
    output = run_root / output_folder
    files = {
        "frozen_source": source_path,
        "notebook": run_root / "__notebook__.ipynb",
        "task_metadata": run_root / f"{task_name}.task.json",
        "run_metadata": _one(run_root, "*.run.json"),
        "result_metadata": _one(run_root, "*.result.json"),
        "atif_metadata": _one(run_root, "*.atif.json"),
        "evidence": output / (model.replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
        "intended_manifest": output / "intended_manifest.json",
        "hosted_audit": output / "audit.json",
    }
    if receipt_path is not None:
        files["receipt"] = receipt_path
    source_root = run_root / (output_folder + "_source")
    return {
        "task_name": task_name,
        "output_folder": output_folder,
        "run_root": str(run_root.relative_to(ROOT.resolve())),
        "artifacts": {key: pin_artifact(path) for key, path in files.items()},
        "embedded_sources": {
            name: pin_artifact(source_root / name) for name in builder.SOURCE_FILES
        },
    }


def build_manifest_from_runs(run_specs: dict[str, dict]) -> dict:
    """Seal explicit local run roots without hand-authoring artifact hashes.

    ``run_specs`` has exactly one key per frozen model. Each value contains
    ``pilot_run_root``, ``pilot_receipt_path`` (None for a failed pilot), and
    ``study_runs``, and optional ``partial_run``. Each study run contains
    ``run_root``, ``source_path``, and optional ``parent_ledger_path``. Source
    literals supply the shard index, task name, and output folder; every raw
    record is replayed before sealing.
    """
    frozen = freeze.verify()
    staged = pilot_tasks.verify()
    if not isinstance(run_specs, dict) or set(run_specs) != set(protocol.CELLS):
        raise ValueError("B run specs must contain the exact frozen model roster")
    repair_groups = _transport_repair_groups_used(run_specs)
    if "first" in repair_groups:
        # Both receipts replay prior sources only, so these preflights cannot
        # recursively validate themselves through their own repair runs.
        import verify_experiment_b_transport_repair_v1 as first_repair
        first_repair.verify_manifest()
    if "second" in repair_groups:
        import verify_experiment_b_transport_repair_s18_s19_v1 as second_repair
        second_repair.verify_manifest()
    frozen_tasks = {task["model"]: task for task in json.loads(pilot_tasks.MANIFEST.read_text())["tasks"]}
    cells = []
    for model in protocol.CELLS:
        spec = run_specs[model]
        if not isinstance(spec, dict) or not {
            "pilot_run_root", "pilot_receipt_path", "study_runs"
        } <= set(spec) or set(spec) - {
            "pilot_run_root", "pilot_receipt_path", "study_runs", "partial_run"
        } or not isinstance(spec["study_runs"], list):
            raise ValueError("B run spec is incomplete")
        task = frozen_tasks[model]
        failed = spec["pilot_receipt_path"] is None
        pilot_run = _pin_run(
            run_root=_input_path(spec["pilot_run_root"]), model=model,
            task_name=task["task_name"], output_folder=task["output_folder"],
            source_path=ROOT / task["source_path"],
            receipt_path=(_input_path(spec["pilot_receipt_path"]) if not failed else None),
        )
        pilot_events = parse_jsonl_bytes(
            _artifact(pilot_run["artifacts"]["evidence"])[1], label="B pinned pilot ledger"
        )
        pilot_run["known_cost_usd"] = raw_event_summary(pilot_events)["known_cost_usd"]
        pilot, _, pilot_raws = _pilot(pilot_run, model, task, failed=failed)
        if failed and (spec["study_runs"] or spec.get("partial_run") is not None):
            raise ValueError("B failed pilot cannot have study runs")
        ledger_runs, ledger_checks = [], []
        partial_run = None
        listed_runs = [(study_spec, False) for study_spec in spec["study_runs"]]
        if spec.get("partial_run") is not None:
            listed_runs.append((spec["partial_run"], True))
        for study_spec, is_partial in listed_runs:
            if not isinstance(study_spec, dict) or not {
                "run_root", "source_path"
            } <= set(study_spec) or set(study_spec) - {
                "run_root", "source_path", "parent_ledger_path"
            }:
                raise ValueError("B study run spec is incomplete")
            source_path = _input_path(study_spec["source_path"])
            source_text = source_path.read_text()
            literals = pilot_tasks.assignments(source_text)
            contract = literals.get("CONTRACT")
            if (literals.get("MODEL") != model or literals.get("PHASE") != "study"
                    or not isinstance(contract, dict)
                    or type(contract.get("shard_index")) is not int):
                raise ValueError("B study source does not identify one frozen shard")
            parent_path = study_spec.get("parent_ledger_path")
            parent = _input_path(parent_path) if parent_path is not None else None
            if bool(literals.get("RESUME_LEDGER")) != (parent is not None):
                raise ValueError("B resumed study source requires its parent raw ledger")
            external_task_name = _authorized_study_task(
                model, contract["shard_index"], source_path, literals, source_text
            )
            run = _pin_run(
                run_root=_input_path(study_spec["run_root"]), model=model,
                task_name=external_task_name,
                output_folder=literals["OUTPUT_FOLDER"], source_path=source_path,
            )
            run.update({
                "shard_index": contract["shard_index"],
                "parent_ledger": pin_artifact(parent) if parent is not None else None,
            })
            checked = (_partial_study_shard if is_partial else _study_shard)(
                run, model, pilot, pilot_raws, require_claims=False
            )
            run.update({key: checked[key] for key in (
                "completed_job_ids", "observed_invocations", "failed_calls",
                "known_cost_usd",
            )})
            if is_partial:
                run["unknown_cost_calls"] = checked["unknown_cost_calls"]
                partial_run = run
                partial_check = checked
            else:
                ledger_runs.append(run)
                ledger_checks.append(checked)
        if failed:
            study = {key: 0 for key in (
                "completed_jobs", "planned_calls", "observed_invocations",
                "failed_calls", "known_cost_usd",
            )}
            unknown_study_cost = 0
            status = "pilot_failed"
        elif partial_run is not None:
            if (len(ledger_runs) >= builder.SHARD_COUNT
                    or len({run["shard_index"] for run in ledger_runs}) != len(ledger_runs)
                    or partial_run["shard_index"] in {
                        run["shard_index"] for run in ledger_runs
                    }):
                raise ValueError("B partial study shards overlap or exceed plan")
            study = {
                "completed_jobs": sum(len(check["completed_job_ids"]) for check in ledger_checks)
                + len(partial_check["completed_job_ids"]),
                "planned_calls": 30 * (len(ledger_runs) + 1),
                "observed_invocations": sum(check["observed_invocations"] for check in ledger_checks)
                + partial_check["observed_invocations"],
                "failed_calls": sum(check["failed_calls"] for check in ledger_checks)
                + partial_check["failed_calls"],
                "known_cost_usd": math.fsum([
                    *(check["known_cost_usd"] for check in ledger_checks),
                    partial_check["known_cost_usd"],
                ]),
            }
            unknown_study_cost = partial_check["unknown_cost_calls"]
            status = "study_partial"
        elif len(ledger_runs) < builder.SHARD_COUNT:
            if len({run["shard_index"] for run in ledger_runs}) != len(ledger_runs):
                raise ValueError("B in-progress study shards overlap")
            study = {
                "completed_jobs": 6 * len(ledger_runs),
                "planned_calls": 30 * len(ledger_runs),
                "observed_invocations": sum(check["observed_invocations"] for check in ledger_checks),
                "failed_calls": sum(check["failed_calls"] for check in ledger_checks),
                "known_cost_usd": math.fsum(check["known_cost_usd"] for check in ledger_checks),
            }
            unknown_study_cost = 0
            status = "study_partial"
        else:
            study = raw_checks.verify_study_cell(ledger_checks, model)
            unknown_study_cost = 0
            status = "complete"
        identity = protocol.cell(model)
        cells.append({
            "model_id": model,
            "reasoning_id": identity["reasoning"],
            "cohort_role": identity["role"],
            "status": status,
            "pilot": {**pilot_run, "known_cost_usd": pilot["known_cost_usd"]},
            "raw_ledgers": sorted(ledger_runs, key=lambda record: record["shard_index"]),
            "partial_study": partial_run,
            **{key: study[key] for key in (
                "completed_jobs", "planned_calls", "observed_invocations",
                "failed_calls", "known_cost_usd",
            )},
            "pilot_known_cost_usd": pilot["known_cost_usd"],
            "pilot_unknown_cost_calls": pilot["unknown_cost_calls"],
            "pilot_observed_invocations": pilot["observed_invocations"],
            "pilot_failed_calls": pilot["failed_calls"],
            "pilot_failure_type": pilot["failure_type"],
            "study_unknown_cost_calls": unknown_study_cost,
        })
    body = {
        "schema": SCHEMA,
        "status": ("complete_raw_revalidated" if all(
            cell["status"] == "complete" for cell in cells
        ) else "partial_raw_revalidated"),
        "fixture_manifest_sha256": frozen["manifest_sha256"],
        "pilot_tasks_manifest_sha256": staged["pilot_tasks_manifest_sha256"],
        "cells": cells,
    }
    return {**body, "collection_sha256": _digest(body)}


def _run_end_utc(run: dict) -> str:
    metadata = run["artifacts"]["run_metadata"]
    _, raw = _artifact(metadata)
    value = json.loads(raw).get("endTime")
    if not isinstance(value, str):
        raise ValueError("B study run has no platform end timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("B study run end timestamp lacks timezone")
    return value


def verify_completed_prefix(run_specs: dict[str, dict], expected_shards: int) -> dict:
    """Seal a clean Terra/Claude shard prefix before staging the next shard."""
    if type(expected_shards) is not int or not 1 <= expected_shards <= builder.SHARD_COUNT:
        raise ValueError("B progress seal requires 1–30 completed shards per active cell")
    manifest = build_manifest_from_runs(run_specs)
    active = {"openai/gpt-5.6-terra", "anthropic/claude-sonnet-4-6@default"}
    records = []
    latest = None
    latest_time = None
    for cell in manifest["cells"]:
        model = cell["model_id"]
        shards = cell["raw_ledgers"]
        if model in active:
            expected_status = "complete" if expected_shards == builder.SHARD_COUNT else "study_partial"
            if (cell["status"] != expected_status or cell["partial_study"] is not None
                    or cell["study_unknown_cost_calls"] != 0
                    or [run["shard_index"] for run in shards] != list(range(expected_shards))):
                raise ValueError("B active cell is not a clean contiguous shard prefix")
            for run in shards:
                end = _run_end_utc(run)
                end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if latest_time is None or end_time > latest_time:
                    latest_time = end_time
                    latest = {
                        "task_name": run["task_name"],
                        "model_id": model,
                        "evidence_sha256": run["artifacts"]["evidence"]["sha256"],
                        "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
                        "evidence_path": run["artifacts"]["evidence"]["path"],
                        "terminal_path": run["artifacts"]["terminal"]["path"],
                        "run_end_utc": end,
                    }
        elif cell["status"] != "pilot_failed" or shards or cell["partial_study"] is not None:
            raise ValueError("B failed-pilot cell acquired study evidence")
        records.append({
            "model_id": model,
            "status": cell["status"],
            "raw_ledgers": [
                {
                    "shard_index": run["shard_index"],
                    "path": run["artifacts"]["evidence"]["path"],
                    "sha256": run["artifacts"]["evidence"]["sha256"],
                    "terminal_path": run["artifacts"]["terminal"]["path"],
                    "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
                    "completed_job_ids": run["completed_job_ids"],
                    "observed_invocations": run["observed_invocations"],
                    "failed_calls": run["failed_calls"],
                    "known_cost_usd": run["known_cost_usd"],
                }
                for run in shards
            ],
        })
    body = {
        "schema": "chronos.experiment-b-study-prefix.v1",
        "status": "completed_prefix_raw_revalidated",
        "completed_shards_per_cell": expected_shards,
        "collection_sha256": manifest["collection_sha256"],
        "cells": records,
        "last_run": latest,
        "collection_manifest": manifest,
    }
    return {**body, "progress_sha256": _digest(body)}


def verify_collection_manifest(path: Path = MANIFEST) -> dict:
    """Return complete normalized cells only after replaying every pinned raw run."""
    manifest = json.loads(Path(path).read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "status", "fixture_manifest_sha256", "pilot_tasks_manifest_sha256",
        "cells", "collection_sha256",
    }:
        raise ValueError("B final collection manifest schema is incomplete")
    body = {key: value for key, value in manifest.items() if key != "collection_sha256"}
    if manifest["collection_sha256"] != _digest(body):
        raise ValueError("B final collection self-hash mismatch")
    frozen = freeze.verify()
    staged = pilot_tasks.verify()
    if (manifest["schema"] != SCHEMA
            or manifest["status"] not in ("complete_raw_revalidated", "partial_raw_revalidated")
            or manifest["fixture_manifest_sha256"] != frozen["manifest_sha256"]
            or manifest["pilot_tasks_manifest_sha256"] != staged["pilot_tasks_manifest_sha256"]
            or not isinstance(manifest["cells"], list)
            or len(manifest["cells"]) != len(protocol.CELLS)):
        raise ValueError("B final collection identity/topology mismatch")
    frozen_tasks = {task["model"]: task for task in json.loads(pilot_tasks.MANIFEST.read_text())["tasks"]}
    normalized = []
    for cell, model in zip(manifest["cells"], protocol.CELLS):
        required = {"model_id", "reasoning_id", "cohort_role", "status", "pilot",
                    "raw_ledgers", "completed_jobs", "planned_calls", "observed_invocations",
                    "failed_calls", "known_cost_usd", "pilot_known_cost_usd",
                    "pilot_unknown_cost_calls", "pilot_observed_invocations",
                    "pilot_failed_calls", "pilot_failure_type", "partial_study",
                    "study_unknown_cost_calls"}
        identity = protocol.cell(model)
        if (not isinstance(cell, dict) or set(cell) != required
                or cell["model_id"] != model
                or cell["reasoning_id"] != identity["reasoning"]
                or cell["cohort_role"] != identity["role"]
                or cell["status"] not in ("complete", "pilot_failed", "study_partial")
                or not isinstance(cell["raw_ledgers"], list)):
            raise ValueError("B final cell roster/status mismatch")
        failed = cell["status"] == "pilot_failed"
        pilot, platform, pilot_raws = _pilot(
            cell["pilot"], model, frozen_tasks[model], failed=failed
        )
        if (cell["pilot_known_cost_usd"] != pilot["known_cost_usd"]
                or cell["pilot_unknown_cost_calls"] != pilot["unknown_cost_calls"]
                or cell["pilot_observed_invocations"] != pilot["observed_invocations"]
                or cell["pilot_failed_calls"] != pilot["failed_calls"]
                or cell["pilot_failure_type"] != pilot["failure_type"]):
            raise ValueError("B final pilot counts differ from raw replay")
        if failed:
            if (cell["raw_ledgers"] != [] or cell["partial_study"] is not None
                    or cell["study_unknown_cost_calls"] != 0
                    or any(cell[key] != 0 for key in (
                        "completed_jobs", "planned_calls", "observed_invocations",
                        "failed_calls", "known_cost_usd",
                    ))):
                raise ValueError("B failed pilot must have no study evidence")
            ledgers = []
            study = {key: 0 for key in (
                "completed_jobs", "planned_calls", "observed_invocations",
                "failed_calls", "known_cost_usd",
            )}
            partial = None
        else:
            if len(cell["raw_ledgers"]) > builder.SHARD_COUNT:
                raise ValueError("B study cell has too many shards")
            ledgers = [_study_shard(run, model, pilot, pilot_raws) for run in cell["raw_ledgers"]]
            indices = [record["shard_index"] for record in ledgers]
            if indices != sorted(set(indices)):
                raise ValueError("B study cell has duplicate or unordered shards")
            if cell["status"] == "complete":
                if (len(ledgers) != builder.SHARD_COUNT
                        or indices != list(range(builder.SHARD_COUNT))
                        or cell["partial_study"] is not None
                        or cell["study_unknown_cost_calls"] != 0):
                    raise ValueError("B complete study cell requires 30 clean shards")
                partial = None
                study = raw_checks.verify_study_cell(ledgers, model)
            else:
                if len(ledgers) >= builder.SHARD_COUNT:
                    raise ValueError("B partial study cannot contain 30 complete shards")
                partial = (
                    _partial_study_shard(cell["partial_study"], model, pilot, pilot_raws)
                    if cell["partial_study"] is not None else None
                )
                if partial is not None and partial["shard_index"] in indices:
                    raise ValueError("B partial study overlaps a complete shard")
                study = {
                    "completed_jobs": sum(len(record["completed_job_ids"]) for record in ledgers)
                    + (len(partial["completed_job_ids"]) if partial else 0),
                    "planned_calls": 30 * (len(ledgers) + (1 if partial else 0)),
                    "observed_invocations": sum(record["observed_invocations"] for record in ledgers)
                    + (partial["observed_invocations"] if partial else 0),
                    "failed_calls": sum(record["failed_calls"] for record in ledgers)
                    + (partial["failed_calls"] if partial else 0),
                    "known_cost_usd": math.fsum([
                        *(record["known_cost_usd"] for record in ledgers),
                        *([partial["known_cost_usd"]] if partial else []),
                    ]),
                }
                if cell["study_unknown_cost_calls"] != (
                    partial["unknown_cost_calls"] if partial else 0
                ):
                    raise ValueError("B partial study unknown-cost count differs from raw")
            if any(cell[key] != study[key] for key in (
                "completed_jobs", "planned_calls", "observed_invocations",
                "failed_calls", "known_cost_usd",
            )):
                raise ValueError("B study cell totals differ from replayed raw shards")
        normalized.append({
            "model_id": model,
            "reasoning_id": identity["reasoning"],
            "cohort_role": identity["role"],
            "status": cell["status"],
            "completed_jobs": study["completed_jobs"],
            "planned_calls": study["planned_calls"],
            "observed_invocations": study["observed_invocations"],
            "failed_calls": study["failed_calls"],
            "known_cost_usd": study["known_cost_usd"],
            "pilot_known_cost_usd": pilot["known_cost_usd"],
            "pilot_unknown_cost_calls": pilot["unknown_cost_calls"],
            "pilot_observed_invocations": pilot["observed_invocations"],
            "pilot_failed_calls": pilot["failed_calls"],
            "pilot_failure_type": pilot["failure_type"],
            "study_unknown_cost_calls": cell["study_unknown_cost_calls"],
            "pilot_receipt_sha256": (
                pilot["receipt"]["receipt_sha256"] if pilot["receipt"] else None
            ),
            "pilot_platform": platform,
            "raw_ledgers": ledgers,
            "partial_study": partial,
        })
    expected_status = ("complete_raw_revalidated" if all(
        cell["status"] == "complete" for cell in normalized
    ) else "partial_raw_revalidated")
    if manifest["status"] != expected_status:
        raise ValueError("B final collection status does not match cell completion")
    return {
        "schema": SCHEMA,
        "status": expected_status,
        "collection_sha256": manifest["collection_sha256"],
        "fixture_manifest_sha256": frozen["manifest_sha256"],
        "cells": normalized,
        "completed_jobs": sum(cell["completed_jobs"] for cell in normalized),
        "planned_calls": sum(cell["planned_calls"] for cell in normalized),
        "observed_invocations": sum(cell["observed_invocations"] for cell in normalized),
        "failed_calls": sum(cell["failed_calls"] for cell in normalized),
        "known_cost_usd": math.fsum(cell["known_cost_usd"] for cell in normalized),
        "pilot_known_cost_usd": math.fsum(cell["pilot_known_cost_usd"] for cell in normalized),
        "pilot_unknown_cost_calls": sum(cell["pilot_unknown_cost_calls"] for cell in normalized),
        "study_unknown_cost_calls": sum(cell["study_unknown_cost_calls"] for cell in normalized),
    }


if __name__ == "__main__":
    print(json.dumps(verify_collection_manifest(), indent=2, sort_keys=True))
