"""C collection replay adding resumed runs under the provider-429 procedure.

Builds on the composed layer (``verify_experiment_c_collection_v3``: Gemini s03
bridge, Gemini s06 v2 resume, Qwen s02 route). Runs listed in ``RESUMES`` are
verified here instead, keyed by their exact run folder:

* the source is regenerated with the repair builder that produced it and must
  match byte-for-byte, with its account-reconciliation record re-derived;
* Kaggle's downloaded metadata labels the run as version 1, so the true version
  is taken from the pinned signed-in ``ListBenchmarkTaskRuns`` response bytes,
  which must also agree with the downloaded run times, task name and definition;
* the parent is the exact previous cumulative ledger; the novel suffix is
  either clean or ends in exactly one new null-cost 429 (shard stays partial).

See ``specs/journal-extension-sep14/experiment-c-provider-429-procedure-2026-09-25.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from unittest import mock

import experiment_c_provider_429_v1 as procedure
import round2_hosted as hosted
import verify_experiment_c_collection_v1 as v1
import verify_experiment_c_collection_v3 as composed
import verify_experiment_c_gemini_s03_platform_bridge_v1 as bridge
import verify_experiment_c_gemini_s06_resume_collection_v1 as gemini_layer


SCHEMA = "chronos.experiment-c-collection-provider-429-resumes.v1"
_BELOW = composed._ordinary_or_qwen
_NEW_429: dict = {}
_KIND_CACHE: dict = {}
_WAITS: dict = {}


def _qwen_s02_repair_v1():
    import build_experiment_c_qwen_s02_resume_v1 as repair
    import experiment_c_qwen_s02_reconciled_view_v1 as view
    return {"repair": repair, "record": repair.reconciliation_record(),
            "parent_view": lambda parent: view.normalized_cumulative(parent, parent),
            "parent_sha256": view.PARENT_SHA256}


def _generic(task: dict, parent: bytes):
    """Resume authorized by authorize_experiment_c_provider_429_resume_v1 (registry-settled pins)."""
    model = task["model"]
    if parent:
        pins, proofs = procedure.settled_pins(parent, model)
        parent_sha = procedure.sha256(parent)
    else:
        pins, proofs, parent_sha = (), [], None

    class Repair:
        TASK = task["task_name"]
        FOLDER = task["output_folder"]

        @staticmethod
        def build_source(contract, selection, resume_seed, standard_builder=None):
            return procedure.build_source(contract, selection, resume_seed, pins, task_name=task["task_name"],
                                          output_folder=task["output_folder"], standard_builder=standard_builder)

    return {"repair": Repair, "record": procedure.reconciliation_record(parent, pins, proofs) if pins else None,
            "parent_view": (lambda raw: procedure.normalized(raw, raw, parent_sha, pins, model)) if pins else (lambda raw: []),
            "parent_sha256": parent_sha}


KINDS = {"qwen_s02_repair_v1": lambda task, parent: _qwen_s02_repair_v1(), "provider_429_generic_v1": _generic}

REGISTRY_PATH = bridge.ROOT / "kaggle/experiment_c_registered_runs_v1.json"
_REGISTRY = json.loads(REGISTRY_PATH.read_text())
if _REGISTRY.get("schema") != "chronos.experiment-c-registered-variant-runs.v1":
    raise ValueError("C registered-run file schema differs")
RESUMES = _REGISTRY["runs"]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _listed_run(entry: dict, task_name: str, source: str, model: str) -> dict:
    raw = (bridge.ROOT / entry["list_runs_path"]).read_bytes()
    raw = raw[:-1] if raw.endswith(b"\n") else raw
    if _sha(raw) != entry["list_runs_sha256"]:
        raise ValueError("C resumed run listing bytes changed")
    response = json.loads(raw)
    if (set(response) != {"benchmarkTaskRuns", "totalResults"} or response["totalResults"] != 1
            or len(response["benchmarkTaskRuns"]) != 1):
        raise ValueError("C resumed run listing roster changed")
    run = response["benchmarkTaskRuns"][0]
    version = run.get("taskVersion") or {}
    if (run.get("id") != entry["platform_run_id"]
            or version.get("id") != entry["platform_version_id"]
            or version.get("versionNumber") != entry["version"]
            or version.get("name") != task_name
            or version.get("definition") != v1._hosted_definition(source)
            or (run.get("modelVersion") or {}).get("modelProxySlug") != model
            or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"):
        raise ValueError("C resumed run listing is not the authorized run")
    return run


def _pin_with_true_version(original_pin):
    def pin(run_root, source_path, task, parent_ledger_path=None):
        record = original_pin(run_root, source_path, task, parent_ledger_path)
        entry = RESUMES.get(record["run_root"])
        if entry is not None:
            if record["task_version"] != 1 or (parent_ledger_path is None) != (entry["version"] == 1):
                raise ValueError("C registered run metadata label or parent differs from the procedure")
            record["task_version"] = entry["version"]
        return record
    return pin


def _verify_resumed(run: dict, task: dict, staged: dict, *, require_claims: bool = True) -> dict:
    entry = RESUMES[run["run_root"]]
    parent = v1._artifact(run["parent_ledger"])[1] if run.get("parent_ledger") else b""
    kind = _KIND_CACHE[run["run_root"]]
    repair = kind["repair"]
    if (set(run) != v1.RUN_KEYS or run.get("task_version") != entry["version"]
            or task.get("task_name") != repair.TASK
            or (run.get("parent_ledger") is None) != (entry["version"] == 1)):
        raise ValueError("C registered run is not the registered version")
    run_root = v1._path(run["run_root"])
    output = run_root / task["output_folder"]
    source_path = v1._path(run["artifacts"]["frozen_source"]["path"])
    expected = {
        "frozen_source": source_path,
        "contract": source_path.with_suffix(".contract.json"),
        "prelaunch_receipt": source_path.with_suffix(".prelaunch.json"),
        "notebook": v1._notebook_path(run_root),
        "task_metadata": run_root / f"{task['task_name']}.task.json",
        "evidence": output / (task["model"].replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
    }
    expected.update({key: v1._one(run_root, pattern) for key, pattern in v1.METADATA_PATTERNS.items()})
    if not isinstance(run.get("artifacts"), dict) or set(run["artifacts"]) != v1.ARTIFACT_KEYS:
        raise ValueError("C resumed run artifact set is incomplete")
    paths, raws = {}, {}
    for key, record in run["artifacts"].items():
        paths[key], raws[key] = v1._artifact(record, expected=expected[key])
    if (_sha(parent) if parent else None) != kind["parent_sha256"]:
        raise ValueError("C resumed run parent differs from the registered ledger")

    original_builder = v1.builder.build_source

    def variant_builder(*, contract, selection, task_name, output_folder, resume_seed):
        if task_name != repair.TASK or output_folder != repair.FOLDER:
            raise ValueError("C resumed source changed its frozen task")
        return repair.build_source(contract, selection, resume_seed, standard_builder=original_builder)

    with mock.patch.object(v1.builder, "build_source", side_effect=variant_builder):
        contract, selection, seed = v1._source_and_receipt(run, task, staged, paths, raws)
    if seed != parent or contract.get("cost_reconciliation") != kind["record"]:
        raise ValueError("C resumed run reconciliation differs from its account proof")

    nested = list(run_root.glob(f"{task['task_name']}/{entry['version']}/*/{entry['platform_run_id']}"))
    if len(nested) != 1 or not nested[0].is_dir():
        raise ValueError("C registered run lacks its original run-ID download")
    originals = sorted(path for path in nested[0].rglob("*") if path.is_file()
                       and "__pycache__" not in path.parts and path.suffix != ".lock")
    if len(originals) < 10 or any(
            (run_root / path.relative_to(nested[0])).read_bytes() != path.read_bytes() for path in originals):
        raise ValueError("C registered run canonical copy differs from its original run-ID download")
    source_text = raws["frozen_source"].decode("utf-8")
    local = v1._platform({**run, "task_version": 1}, paths, source_text, task["model"])
    if entry["version"] > 1:
        listed = _listed_run(entry, task["task_name"], source_text, task["model"])
        if (local["task_version"] != 1 or local["start_time"] != listed["startTime"]
                or local["end_time"] != listed["endTime"]):
            raise ValueError("C resumed run listing and downloaded execution disagree")
    platform = {**local, "task_version": entry["version"]}

    jobs = {job["id"]: job for job in v1.protocol.jobs_for(task["model"], selection)
            if job["id"] in set(task["expected_job_ids"])}

    def structural(rows):
        return v1.auditor.audit(v1._normalize_consistency_transport(rows), task["model"], selection,
                                require_complete=False, expected_job_ids=set(task["expected_job_ids"]))

    policy = contract.get("transport_policy")
    if policy is not None:
        if policy != procedure.TRANSPORT_POLICY:
            raise ValueError("C run transport policy differs from the amendment")
        waits_path = output / "transient_waits.json"
        waits = json.loads(waits_path.read_bytes())
        if (set(waits) != {"schema", "count", "seconds"} or waits["schema"] != policy["schema"]
                or type(waits["count"]) is not int or waits["count"] < 0 or waits["seconds"] < 0):
            raise ValueError("C run transient-wait record is malformed")
        _WAITS[run["run_root"]] = {**waits, "sha256": _sha(waits_path.read_bytes())}
    parent_view = kind["parent_view"](parent)
    if hosted.validate_resume_ledger(parent_view, model=task["model"], identity=task["identity"],
                                     expected_jobs=jobs, structural_audit=structural) != contract["resume_ledger"]:
        raise ValueError("C resumed normalized parent differs from its contract")
    evidence = raws["evidence"]
    suffix = procedure.check_resumed_suffix(evidence, parent, task["model"])
    events = hosted.parse_jsonl_bytes(evidence, label="C resumed cumulative raw ledger")
    mixed = parent_view + events[len(parent_view):]
    audit = structural(mixed)
    raw_accounting = hosted.raw_event_summary(events)
    completed_ids = [event["job"]["id"] for event in events if event["event"] == "job_complete"]
    new_429 = suffix["new_429"]
    if (len(completed_ids) != len(set(completed_ids)) or audit["completed_jobs"] != len(completed_ids)
            or audit["observed_invocations"] != raw_accounting["observed_invocations"]
            or audit["failed_calls"] != raw_accounting["failed_calls"]
            or audit["unknown_cost_calls"] != (1 if new_429 else 0)
            or not math.isclose(audit["known_cost_usd"], raw_accounting["known_cost_usd"], rel_tol=0, abs_tol=1e-12)):
        raise ValueError("C resumed raw and reconciled replay disagree")
    terminal = v1._json(raws["terminal"], "C resumed hosted terminal")
    stopped = terminal.get("stopped_early")
    if new_429:
        if not isinstance(stopped, str) or not stopped.startswith("RateLimitError("):
            raise ValueError("C resumed run stop reason is not the new 429")
        expected_terminal = {
            "schema": "chronos.experiment-c-hosted-terminal.v1", "task": task["task_name"],
            "contract_sha256": contract["contract_sha256"], "status": "stopped",
            "stopped_early": stopped, "audit_error": "ValueError('another unknown-cost call remains')",
            "audit": None, "raw_accounting": raw_accounting}
        complete = False
    else:
        complete = bool(audit["complete"] and stopped is None)
        hosted_bug = (terminal.get("status") == "stopped" and terminal.get("audit_error") == procedure.TRANSPORT_BUG
                      and terminal.get("audit") is None)
        expected_terminal = {
            "schema": "chronos.experiment-c-hosted-terminal.v1", "task": task["task_name"],
            "contract_sha256": contract["contract_sha256"],
            "status": "stopped" if hosted_bug else "complete" if complete else "stopped",
            "stopped_early": stopped, "audit_error": procedure.TRANSPORT_BUG if hosted_bug else None,
            "audit": None if hosted_bug else audit, "raw_accounting": raw_accounting}
    if kind["record"] is not None or "cost_reconciliation" in contract:
        expected_terminal["cost_reconciliation"] = contract["cost_reconciliation"]
    if terminal != expected_terminal:
        differing = sorted(key for key in set(terminal) | set(expected_terminal)
                           if terminal.get(key) != expected_terminal.get(key))
        raise ValueError(f"C resumed hosted terminal differs: {differing}")
    claims = {
        "complete": complete, "completed_job_ids": sorted(completed_ids),
        "observed_invocations": raw_accounting["observed_invocations"],
        "failed_calls": raw_accounting["failed_calls"],
        "known_cost_usd": raw_accounting["known_cost_usd"],
        "unknown_cost_calls": raw_accounting["unknown_cost_calls"],
    }
    if require_claims and any(run[key] != value for key, value in claims.items()):
        raise ValueError("C resumed run claims differ from raw replay")
    _NEW_429[run["run_root"]] = new_429.as_dict() if new_429 else None
    return {
        "shard_index": task["shard_index"], "task_name": task["task_name"],
        "run_id": platform["run_id"], "task_version": platform["task_version"],
        "complete": complete, "completed_job_ids": claims["completed_job_ids"],
        "planned_calls": task["planned_calls"],
        "observed_invocations": claims["observed_invocations"], "failed_calls": claims["failed_calls"],
        "known_cost_usd": claims["known_cost_usd"], "unknown_cost_calls": claims["unknown_cost_calls"],
        "stop_reason": stopped if not complete else None,
        "path": run["artifacts"]["evidence"]["path"], "sha256": run["artifacts"]["evidence"]["sha256"],
        "terminal_path": run["artifacts"]["terminal"]["path"],
        "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
        "source_path": run["artifacts"]["frozen_source"]["path"],
        "source_sha256": run["artifacts"]["frozen_source"]["sha256"],
        "contract_sha256": contract["contract_sha256"],
        "prelaunch_receipt_sha256": run["artifacts"]["prelaunch_receipt"]["sha256"],
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "platform": platform,
    }


def _route(run: dict, task: dict, staged: dict, *, require_claims: bool = True) -> dict:
    if run.get("run_root") in RESUMES:
        return _verify_resumed(run, task, staged, require_claims=require_claims)
    return _BELOW(run, task, staged, require_claims=require_claims)


def _prepare_kinds(run_specs_path: Path) -> None:
    """Evaluate every listed resume's account proofs before any verifier patch is active.

    Legacy proofs replay their own sealed collections; doing that inside the
    outer patched replay would nest the same bridge patches."""
    import stage_experiment_c_tasks_v1 as stage
    _KIND_CACHE.clear()
    staged = {item["task_name"]: item for item in stage.verify_manifest()["tasks"]}
    specs = json.loads(run_specs_path.read_text())
    for cell in specs.values():
        for item in cell.get("runs", []):
            entry = RESUMES.get(item["run_root"])
            if entry is None:
                continue
            task = next(t for t in staged.values() if t["model"] in specs and t["shard_index"] == item["shard_index"]
                        and item["run_root"].split("/")[-2] == t["task_name"])
            parent = (bridge.ROOT / item["parent_ledger_path"]).read_bytes() if item.get("parent_ledger_path") else b""
            _KIND_CACHE[item["run_root"]] = KINDS[entry["kind"]](task, parent)


def build(run_specs_path: Path) -> dict:
    _NEW_429.clear()
    _WAITS.clear()
    _prepare_kinds(run_specs_path)
    with mock.patch.object(gemini_layer, "_ORDINARY_VERIFY", side_effect=_route), \
            mock.patch.object(v1, "_pin_run", side_effect=_pin_with_true_version(v1._pin_run)):
        layered = gemini_layer.build(run_specs_path)
    body = {key: value for key, value in layered.items() if key != "collection_sha256"}
    body["schema"] = SCHEMA
    specs = json.loads(run_specs_path.read_text())
    listed = {run["run_root"] for cell in specs.values() for run in cell.get("runs", [])}
    body["provider_429_resumes"] = {
        "schema": "chronos.experiment-c-provider-429-resume-registry.v1",
        "procedure": "specs/journal-extension-sep14/experiment-c-provider-429-procedure-2026-09-25.md",
        "runs": {root: {**RESUMES[root], "new_unsettled_429": _NEW_429.get(root),
                        **({"transient_waits": _WAITS[root]} if root in _WAITS else {})}
                 for root in sorted(RESUMES) if root in listed},
    }
    return {**body, "collection_sha256": v1._digest(body)}


def verify(path: Path) -> dict:
    saved = json.loads(path.read_text())
    specs_path = bridge.ROOT / (saved.get("provenance_bridge") or {}).get("run_specs_path", "")
    if not specs_path.is_file():
        raise ValueError("C provider-429 collection run specs are missing")
    rebuilt = build(specs_path)
    if saved != rebuilt:
        raise ValueError("C provider-429 collection differs from raw replay")
    return rebuilt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.run_specs is None:
        result = verify(args.output)
    else:
        result = build(args.run_specs)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(args.output, result["collection_sha256"])


if __name__ == "__main__":
    main()
