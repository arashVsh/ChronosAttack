"""Stage C's frozen 120-task topology offline; authorize one shard only later.

This plan contains no runnable hosted source and cannot authorize model calls.
After a final raw-revalidated B report and fresh official quota observation,
``authorize_one`` checks the exact staged task before the hosted builder emits
its task-specific, source-hashed file. No Kaggle upload occurs here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

import build_experiment_c_cell_v1 as builder
import experiment_c_protocol_v1 as protocol
import experiment_c_selection_v1 as selection_rules
from round2_hosted import manifest_digest, select_shard


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_c_staged_tasks_v1.json"
SCHEMA = "chronos.experiment-c-staged-tasks.v1"
MAX_SHARD_CEILING_USD = 1.0
SELECTIONS = (
    ("openai/gpt-5.6-terra", "low", "terra_low"),
    ("google/gemini-3.6-flash", "minimal", "gemini_minimal"),
    ("qwen/qwen3-235b-a22b-instruct-2507", "low", "qwen_low"),
    ("anthropic/claude-sonnet-4-6@default", "none", "claude_none"),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _selection(model: str, reasoning: str, tag: str) -> tuple[dict, Path]:
    path = GENERATED / f"experiment_c_{tag}_selection_v1.json"
    value = json.loads(path.read_text())
    selection_rules.validate_selection(value, model=model, reasoning=reasoning)
    selection_rules.verify_selection_source(value)
    return value, path


def _identity(model: str, selection: dict) -> str:
    protocol.configure(model, selection["reasoning"])
    return protocol.engine.digest(json.dumps({
        "study": protocol.STUDY_ID,
        "model": model,
        "fixtures": protocol.fixtures(selection),
        "settings": protocol.engine.CALL_SETTINGS,
    }, sort_keys=True))


def build_manifest() -> dict:
    """Derive all shard IDs/hashes from the existing four pinned selections."""
    _, source_hashes = builder._source_texts()
    task_records = []
    selection_records = []
    all_ids = set()
    for model, reasoning, tag in SELECTIONS:
        selection, path = _selection(model, reasoning, tag)
        jobs = protocol.jobs_for(model, selection)
        identity = _identity(model, selection)
        if len(jobs) != 180 or len({job["id"] for job in jobs}) != 180:
            raise ValueError("C selection does not produce 180 distinct defense jobs")
        selection_records.append({
            "model": model,
            "reasoning": reasoning,
            "role": selection["role"],
            "path": str(path.relative_to(ROOT)),
            "file_sha256": _sha256(path.read_bytes()),
            "selection_manifest_sha256": selection["selection_manifest_sha256"],
            "source_log_sha256": selection["source_log_sha256"],
            "selected_condition_index": selection["selected_condition_index"],
            "selected_order": selection["selected_order"],
            "identity": identity,
        })
        for index in range(builder.SHARD_COUNT):
            shard_jobs = select_shard(
                jobs, shard_index=index, shard_count=builder.SHARD_COUNT
            )
            shard_ids = [job["id"] for job in shard_jobs]
            if len(shard_jobs) != 6 or len(set(shard_ids)) != 6 or all_ids & set(shard_ids):
                raise ValueError("C staged shard has missing or overlapping arm jobs")
            all_ids.update(shard_ids)
            planned = sum(job["calls"] for job in shard_jobs)
            expected_calls = 46 if model in protocol.REVERSE_MODELS else 45
            if planned != expected_calls or {job["mode"] for job in shard_jobs} != set(protocol.ARMS):
                raise ValueError("C staged shard changed its six-arm call topology")
            shard_tag = f"s{index:02d}"
            task_records.append({
                "model": model,
                "reasoning": reasoning,
                "role": selection["role"],
                "shard_index": index,
                "task_name": f"chronos-r2-tree4-c-{tag.replace('_', '-')}-{shard_tag}-v1",
                "output_folder": f"round2_tree4_c_{tag}_{shard_tag}_v1",
                "future_source_path": f"kaggle/round2_generated/tree4_c_{tag}_{shard_tag}_v1.py",
                "selection_manifest_sha256": selection["selection_manifest_sha256"],
                "identity": identity,
                "expected_job_ids": shard_ids,
                "jobs_manifest_sha256": manifest_digest(shard_jobs),
                "jobs": 6,
                "planned_calls": planned,
                "max_ceiling_usd": MAX_SHARD_CEILING_USD,
                "launch_authorized": False,
                "hosted_source_sha256": None,
            })
    if len(task_records) != 120 or len(all_ids) != 720 or sum(
        task["planned_calls"] for task in task_records
    ) != 5460:
        raise ValueError("C staged aggregate differs from 720 jobs and 5,460 calls")
    body = {
        "schema": SCHEMA,
        "status": "staged_waiting_for_final_b_and_fresh_quota",
        "launch_authorized": False,
        "study_id": protocol.STUDY_ID,
        "selection_count": 4,
        "task_count": 120,
        "job_count": 720,
        "planned_calls": 5460,
        "shards_per_setting": 30,
        "max_ceiling_per_shard_usd": MAX_SHARD_CEILING_USD,
        "quota_rule": "one task at a time; fresh authenticated daily balance must cover its ceiling",
        "required_b_report_status": ["complete_raw_revalidated", "partial_raw_revalidated"],
        "experiment_b_analysis_sha256": None,
        "fresh_quota_attestation_sha256": None,
        "source_module_sha256": source_hashes,
        "hosted_builder_sha256": _sha256(Path(builder.__file__).read_bytes()),
        "strict_auditor_sha256": source_hashes["audit_experiment_c_v1.py"],
        "selection_seals": selection_records,
        "tasks": task_records,
    }
    return {**body, "staged_manifest_sha256": _digest(body)}


def verify_manifest(path: Path = MANIFEST) -> dict:
    saved = json.loads(Path(path).read_text())
    body = {key: value for key, value in saved.items() if key != "staged_manifest_sha256"}
    if saved.get("staged_manifest_sha256") != _digest(body) or saved != build_manifest():
        raise ValueError("C staged plan differs from frozen selections and source bytes")
    if saved["launch_authorized"] is not False or any(
        task["launch_authorized"] is not False or task["hosted_source_sha256"] is not None
        for task in saved["tasks"]
    ):
        raise ValueError("C staged plan is not launch-inert")
    return saved


def discovered_task_names(source: str) -> list[str]:
    """Require the static literal decorator form used by Kaggle CLI discovery."""
    names = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not (
                isinstance(target, ast.Attribute) and target.attr == "task"
                and isinstance(target.value, ast.Name) and target.value.id == "kbench"
            ):
                continue
            matches = [keyword.value for keyword in decorator.keywords if keyword.arg == "name"]
            if (
                len(matches) != 1 or not isinstance(matches[0], ast.Constant)
                or not isinstance(matches[0].value, str)
            ):
                raise ValueError("C hosted task decorator name must be a literal string")
            names.append(matches[0].value)
    return names


def _source_path(task: dict, resume_seed: bytes) -> str:
    """Keep every launched source immutable, including an identity-aware resume."""
    base = Path(task["future_source_path"])
    if not resume_seed:
        return base.as_posix()
    parent = _sha256(resume_seed)
    return base.with_name(f"{base.stem}_resume_{parent[:16]}.py").as_posix()


def authorize_one(
    *, task_name: str, ceiling_usd: float, last_task: str,
    last_run_id: int, quota_evidence: bytes, quota_terminal: bytes,
    resume_seed: bytes = b"",
) -> tuple[str, dict, dict]:
    """After B finalizes, join a fresh quota to exactly one staged C task."""
    staged = verify_manifest()
    matches = [task for task in staged["tasks"] if task["task_name"] == task_name]
    if len(matches) != 1:
        raise ValueError("C task is outside the staged manifest")
    task = matches[0]
    if type(ceiling_usd) not in (int, float) or not 0 < ceiling_usd <= task["max_ceiling_usd"]:
        raise ValueError("C shard ceiling exceeds the staged per-task maximum")
    seal = next(
        item for item in staged["selection_seals"] if item["model"] == task["model"]
    )
    selection = json.loads((ROOT / seal["path"]).read_text())
    contract = builder.plan_cell(
        selection=selection, shard_index=task["shard_index"],
        ceiling_usd=ceiling_usd, last_task=last_task, last_run_id=last_run_id,
        quota_evidence=quota_evidence, quota_terminal=quota_terminal,
        resume_seed=resume_seed,
    )
    if (
        contract["selection_manifest_sha256"] != task["selection_manifest_sha256"]
        or contract["identity"] != task["identity"]
        or contract["expected_job_ids"] != task["expected_job_ids"]
        or contract["jobs_manifest_sha256"] != task["jobs_manifest_sha256"]
        or contract["job_count"] != task["jobs"]
        or contract["planned_calls"] != task["planned_calls"]
        or contract["source_sha256"] != staged["source_module_sha256"]
        or contract["builder_sha256"] != staged["hosted_builder_sha256"]
    ):
        raise ValueError("C prelaunch contract diverges from staged task")
    source = builder.build_source(
        contract=contract, selection=selection, task_name=task_name,
        output_folder=task["output_folder"], resume_seed=resume_seed,
    )
    compile(source, task["future_source_path"], "exec")
    if discovered_task_names(source) != [task_name]:
        raise ValueError("C generated source is not statically discoverable")
    receipt_body = {
        "schema": "chronos.experiment-c-prelaunch-receipt.v1",
        "staged_manifest_sha256": staged["staged_manifest_sha256"],
        "task_name": task_name,
        "source_path": _source_path(task, resume_seed),
        "source_sha256": _sha256(source.encode()),
        "contract_sha256": contract["contract_sha256"],
        "selection_manifest_sha256": task["selection_manifest_sha256"],
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "experiment_b_analysis_sha256": contract["sequence_gate"]["experiment_b_analysis_sha256"],
        "fresh_quota_attestation_sha256": contract["quota_attestation"]["attestation_sha256"],
        "ceiling_usd": ceiling_usd,
        "launch_authorized": True,
    }
    receipt = {**receipt_body, "receipt_sha256": _digest(receipt_body)}
    return source, contract, receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    write = sub.add_parser("write-manifest")
    write.add_argument("--output", type=Path, default=MANIFEST)
    authorize = sub.add_parser("authorize-one")
    authorize.add_argument("--task-name", required=True)
    authorize.add_argument("--ceiling", required=True, type=float)
    authorize.add_argument("--last-task", required=True)
    authorize.add_argument("--last-run-id", required=True, type=int)
    authorize.add_argument("--last-evidence", required=True, type=Path)
    authorize.add_argument("--last-terminal", required=True, type=Path)
    authorize.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    if args.command == "write-manifest":
        result = build_manifest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(args.output, result["staged_manifest_sha256"])
        return
    if args.command == "verify":
        result = verify_manifest()
        print(f"PASS C staged manifest {result['staged_manifest_sha256']}")
        return
    seed = args.resume_from.read_bytes() if args.resume_from else b""
    source, contract, receipt = authorize_one(
        task_name=args.task_name, ceiling_usd=args.ceiling,
        last_task=args.last_task, last_run_id=args.last_run_id,
        quota_evidence=args.last_evidence.read_bytes(),
        quota_terminal=args.last_terminal.read_bytes(), resume_seed=seed,
    )
    source_path = ROOT / receipt["source_path"]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    sidecars = [source_path.with_suffix(suffix) for suffix in (".contract.json", ".prelaunch.json")]
    if source_path.exists() or any(path.exists() for path in sidecars):
        raise FileExistsError("C prelaunch source or sidecar already exists; never overwrite a pinned attempt")
    with source_path.open("x", encoding="utf-8") as handle:
        handle.write(source)
    for suffix, value in ((".contract.json", contract), (".prelaunch.json", receipt)):
        sidecar = source_path.with_suffix(suffix)
        with sidecar.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(source_path, receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
