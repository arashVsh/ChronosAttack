"""Offline selection seals and receipt-gated deterministic Experiment C shards.

This builder creates source-hashed Kaggle task files but never uploads or runs
them.  Launch requires a fresh official quota attestation supplied by caller.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import audit_experiment_c_v1 as auditor
import capture_benchmark_quota_v1 as quota_capture
import experiment_c_protocol_v1 as protocol
import experiment_c_selection_v1 as selection_rules
from round2_hosted import manifest_digest, parse_jsonl_bytes, select_shard, validate_resume_ledger


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARD_COUNT = 30
SOURCE_FILES = (
    "completion_protocol.py",
    "four_observation_protocol.py",
    "four_observation_defenses.py",
    "experiment_c_selection_v1.py",
    "experiment_c_protocol_v1.py",
    "audit_experiment_c_v1.py",
    "round2_hosted.py",
)
TASK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
FOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")


def _source_texts() -> tuple[dict[str, str], dict[str, str]]:
    sources = {name: (HERE / name).read_text() for name in SOURCE_FILES}
    hashes = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in sources.items()}
    return sources, hashes


def _authoritative_source(model: str, reasoning: str) -> tuple[list[Path], dict]:
    """Run the existing strict tree-study audit before accepting source logs."""
    if (model, reasoning) == ("openai/gpt-5.6-terra", "low"):
        import verify_round2_terra_study_collection as verifier

        report = verifier.verify()
        if report["completed_jobs"] != 690 or report["planned_calls"] != 2310 or report["unknown_cost_calls"]:
            raise ValueError("Terra low tree study collection is not strictly sealed")
        collection = json.loads(verifier.MANIFEST.read_text())
        paths = [ROOT / row["artifacts"]["evidence"]["path"] for row in collection["shards"]]
        return paths, {"kind": "terra_low_collection", "collection_manifest_sha256": report["collection_manifest_sha256"], "completed_jobs": 690, "complete_trial_calls": 2310}

    import round2_analysis as historical

    cells = [cell for cell in historical.STUDY_CELLS if cell["model"] == model and cell["reasoning"] == reasoning]
    if len(cells) != 1:
        raise ValueError("no authoritative complete tree-study source for this setting")
    split = json.loads((HERE / "round2_manifest_v1.json").read_text())["held_out_order"]
    report = historical._audited_study(cells[0], split)["audit"]
    if report["completed_jobs"] != 690 or report["complete_trial_calls"] != 2310:
        raise ValueError("historical tree study does not have a complete audited matrix")
    return [cells[0]["path"]], {"kind": "historical_tree_study", "completed_jobs": 690, "complete_trial_calls": 2310, "unknown_historical_cost_calls": report["unknown_cost_calls"]}


def seal_selection(model: str, reasoning: str) -> dict:
    role = selection_rules.ROSTER.get((model, reasoning))
    if role is None:
        raise ValueError("setting outside executable C roster")
    paths, _ = _authoritative_source(model, reasoning)
    return selection_rules.make_selection(model=model, reasoning=reasoning, role=role, source_files=paths)


def _selection_gate(selection: dict) -> dict:
    selection_rules.validate_selection(selection)
    selection_rules.verify_selection_source(selection)
    paths, report = _authoritative_source(selection["model"], selection["reasoning"])
    authoritative = selection_rules.make_selection(model=selection["model"], reasoning=selection["reasoning"], role=selection["role"], source_files=paths)
    if authoritative != selection:
        raise ValueError("selection seal does not match strictly audited authoritative logs")
    return report


def _quota_gate(quota: dict, evidence: bytes, terminal: bytes, ceiling_usd: float, *, now: datetime | None = None) -> dict:
    quota_capture.verify_attestation(quota, evidence, terminal)
    now = now or datetime.now(timezone.utc)
    queried = datetime.fromisoformat(quota["queried_at_end_utc"])
    if queried.tzinfo is None or not 0 <= (now - queried).total_seconds() <= 15 * 60:
        raise ValueError("official quota attestation must be fresh within 15 minutes")
    response = quota["response"]
    used, allowed = response.get("daily_quota_used_usd"), response.get("total_daily_quota_allowed_usd")
    if not all(type(value) in (int, float) and value >= 0 for value in (used, allowed)) or allowed > 10 or used + ceiling_usd > allowed:
        raise ValueError("shard ceiling exceeds the fresh authorized daily balance")
    return {"attestation_sha256": quota["attestation_sha256"], "used_usd": used, "allowed_usd": allowed, "remaining_usd": allowed - used}


def _sequence_gate() -> dict:
    """Require fresh A regeneration and B's final raw-revalidated report.

    The frozen B/C availability amendment explicitly permits C after B is
    completed *or explicitly reported partial*. The B verifier regenerates
    either disposition from the final sealed raw collection; an absent or
    in-progress B artifact is not a report.
    """
    import analyze_experiment_a as a_analysis

    a_path = HERE / "round2_analysis/experiment_a_analysis_v1.json"
    a_result = a_analysis.verify_analysis_file(a_path)
    if a_result.get("schema") != "chronos.experiment-a-analysis.v1":
        raise ValueError("Experiment A frozen analysis is not sealed")
    try:
        import analyze_experiment_b_v1 as b_analysis
    except ImportError as error:
        raise ValueError("Experiment C cannot stage until the Experiment B final-analysis verifier exists") from error
    b_path = HERE / "round2_analysis/experiment_b_analysis_v1.json"
    b_result = b_analysis.verify_analysis_file(b_path)
    if (
        b_result.get("schema") != "chronos.experiment-b-analysis.v1"
        or b_result.get("status") not in (
            "complete_raw_revalidated", "partial_raw_revalidated"
        )
        or b_result.get("aggregate_accounting", {}).get("completed_study_cells", -1)
        + b_result.get("aggregate_accounting", {}).get("pilot_failed_study_cells", -1)
        + b_result.get("aggregate_accounting", {}).get("study_partial_cells", -1)
        != 4
    ):
        raise ValueError("Experiment C requires B's final complete-or-explicit-partial raw report")
    return {
        "experiment_a_analysis_sha256": a_result["analysis_sha256"],
        "experiment_a_file_sha256": hashlib.sha256(a_path.read_bytes()).hexdigest(),
        "experiment_a_verifier_sha256": hashlib.sha256(Path(a_analysis.__file__).read_bytes()).hexdigest(),
        "experiment_b_analysis_sha256": b_result["analysis_sha256"],
        "experiment_b_file_sha256": hashlib.sha256(b_path.read_bytes()).hexdigest(),
        "experiment_b_verifier_sha256": hashlib.sha256(Path(b_analysis.__file__).read_bytes()).hexdigest(),
    }


def plan_cell(
    *,
    selection: dict,
    shard_index: int,
    ceiling_usd: float,
    last_task: str,
    last_run_id: int,
    quota_evidence: bytes,
    quota_terminal: bytes,
    resume_seed: bytes = b"",
) -> dict:
    if type(shard_index) is not int or shard_index not in range(SHARD_COUNT):
        raise ValueError("C uses exactly 30 deterministic shards")
    if type(ceiling_usd) not in (int, float) or not 0 < ceiling_usd <= 10:
        raise ValueError("invalid explicit shard ceiling")
    if resume_seed and not resume_seed.endswith(b"\n"):
        raise ValueError("resume ledger must be newline terminated")
    sequence_gate = _sequence_gate()
    source_audit = _selection_gate(selection)
    response, queried_start, queried_end = quota_capture.fetch_quota()
    quota = quota_capture.build_attestation(
        response=response,
        queried_at_start=queried_start,
        queried_at_end=queried_end,
        task=last_task,
        run_id=last_run_id,
        evidence=quota_evidence,
        terminal=quota_terminal,
    )
    quota_record = _quota_gate(quota, quota_evidence, quota_terminal, ceiling_usd)
    model = selection["model"]
    protocol.configure(model, selection["reasoning"])
    jobs = select_shard(protocol.jobs_for(model, selection), shard_index=shard_index, shard_count=SHARD_COUNT)
    if len(jobs) != 6 or sum(job["calls"] for job in jobs) != (46 if model in protocol.REVERSE_MODELS else 45):
        raise ValueError("C shard no longer has one repetition of every arm")
    fixtures = protocol.fixtures(selection)
    identity = protocol.engine.digest(json.dumps({"study": protocol.STUDY_ID, "model": model, "fixtures": fixtures, "settings": protocol.engine.CALL_SETTINGS}, sort_keys=True))
    events = parse_jsonl_bytes(resume_seed, label="C resume ledger")
    seed = validate_resume_ledger(
        events,
        model=model,
        identity=identity,
        expected_jobs={job["id"]: job for job in jobs},
        structural_audit=lambda values: auditor.audit(values, model, selection, require_complete=False, expected_job_ids={job["id"] for job in jobs}),
    )
    _, source_hashes = _source_texts()
    body = {
        "schema": "chronos.experiment-c-shard-contract.v1",
        "study_id": protocol.STUDY_ID,
        "model": model,
        "reasoning": selection["reasoning"],
        "role": selection["role"],
        "shard_index": shard_index,
        "shard_count": SHARD_COUNT,
        "expected_job_ids": [job["id"] for job in jobs],
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_manifest_sha256": manifest_digest(jobs),
        "identity": identity,
        "source_sha256": source_hashes,
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quota_capture_source_sha256": hashlib.sha256(Path(quota_capture.__file__).read_bytes()).hexdigest(),
        "source_audit_gate": source_audit,
        "sequence_gate": sequence_gate,
        "selection_manifest_sha256": selection["selection_manifest_sha256"],
        "source_log_sha256": selection["source_log_sha256"],
        "amendment_sha256": selection_rules.AMENDMENT_SHA256,
        "quota_gate": quota_record,
        "quota_attestation": quota,
        "ceiling_usd": ceiling_usd,
        "parent_ledger_sha256": hashlib.sha256(resume_seed).hexdigest() if resume_seed else None,
        "resume_ledger": seed,
        "call_settings": {**protocol.engine.CALL_SETTINGS, "sdk_max_retries": 0},
    }
    return {**body, "contract_sha256": selection_rules.canonical_hash(body)}


def build_source(*, contract: dict, selection: dict, task_name: str, output_folder: str, resume_seed: bytes = b"") -> str:
    if not TASK_PATTERN.fullmatch(task_name) or not FOLDER_PATTERN.fullmatch(output_folder):
        raise ValueError("invalid explicit task or output folder")
    selection_rules.validate_selection(selection, model=contract["model"], reasoning=contract["reasoning"])
    body = {key: value for key, value in contract.items() if key != "contract_sha256"}
    if selection_rules.canonical_hash(body) != contract.get("contract_sha256"):
        raise ValueError("C shard contract changed")
    if (hashlib.sha256(resume_seed).hexdigest() if resume_seed else None) != contract["parent_ledger_sha256"]:
        raise ValueError("resume bytes differ from the preflighted parent ledger")
    sources, hashes = _source_texts()
    if hashes != contract["source_sha256"]:
        raise ValueError("C source changed after preflight")
    return f'''# Generated offline by build_experiment_c_cell_v1.py; no calls on import.
import hashlib
import json
import sys
from pathlib import Path
import kaggle_benchmarks as kbench

SOURCES = {sources!r}
SOURCE_HASHES = {hashes!r}
SELECTION = {selection!r}
CONTRACT = {contract!r}
RESUME_SEED = {resume_seed!r}
MODEL = {contract["model"]!r}
TASK = {task_name!r}
OUTPUT_FOLDER = {output_folder!r}
SOURCE_ROOT = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
for name, content in SOURCES.items():
    if hashlib.sha256(content.encode()).hexdigest() != SOURCE_HASHES[name]:
        raise ValueError('embedded Experiment C source changed')
    (SOURCE_ROOT / name).write_text(content)
sys.path.insert(0, str(SOURCE_ROOT))
import experiment_c_selection_v1 as selection_rules
import experiment_c_protocol_v1 as protocol
import audit_experiment_c_v1 as auditor
from round2_hosted import manifest_digest, parse_jsonl_best_effort, parse_jsonl_bytes, raw_event_summary, select_shard, validate_resume_ledger

selection_rules.validate_selection(SELECTION, model=MODEL, reasoning=CONTRACT['reasoning'])
if selection_rules.canonical_hash({{k:v for k,v in CONTRACT.items() if k != 'contract_sha256'}}) != CONTRACT['contract_sha256']:
    raise ValueError('Experiment C hosted contract changed')
if CONTRACT['selection_manifest_sha256'] != SELECTION['selection_manifest_sha256'] or CONTRACT['source_log_sha256'] != SELECTION['source_log_sha256']:
    raise ValueError('Experiment C selection source changed')
if CONTRACT['amendment_sha256'] != selection_rules.AMENDMENT_SHA256:
    raise ValueError('B/C availability amendment changed')
if CONTRACT['source_sha256'] != SOURCE_HASHES:
    raise ValueError('Experiment C source hashes changed')
if (hashlib.sha256(RESUME_SEED).hexdigest() if RESUME_SEED else None) != CONTRACT['parent_ledger_sha256']:
    raise ValueError('Experiment C resume ledger changed')
protocol.configure(MODEL, CONTRACT['reasoning'])
JOBS = select_shard(protocol.jobs_for(MODEL, SELECTION), shard_index=CONTRACT['shard_index'], shard_count=CONTRACT['shard_count'])
if [job['id'] for job in JOBS] != CONTRACT['expected_job_ids'] or manifest_digest(JOBS) != CONTRACT['jobs_manifest_sha256']:
    raise ValueError('Experiment C expected jobs changed')
FIXTURES = protocol.fixtures(SELECTION)
IDENTITY = protocol.engine.digest(json.dumps(dict(study=protocol.STUDY_ID, model=MODEL, fixtures=FIXTURES, settings=protocol.engine.CALL_SETTINGS), sort_keys=True))
if IDENTITY != CONTRACT['identity']:
    raise ValueError('Experiment C scientific identity changed')
OUTPUT = Path('/kaggle/working') / OUTPUT_FOLDER
OUTPUT.mkdir(parents=True, exist_ok=True)
EVIDENCE = OUTPUT / (MODEL.replace('/', '_') + '.jsonl')
if RESUME_SEED:
    if EVIDENCE.exists() and EVIDENCE.read_bytes() != RESUME_SEED:
        raise ValueError('hosted output already differs from the resume ledger')
    EVIDENCE.write_bytes(RESUME_SEED)
validate_resume_ledger(parse_jsonl_bytes(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={{job['id']:job for job in JOBS}},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))

@kbench.task(name={task_name!r})
def experiment_c(llm):
    if llm.model != MODEL:
        raise ValueError('unexpected selected model')
    llm.client = llm.client.with_options(max_retries=0)
    stopped = None
    try:
        protocol.engine.run_jobs(kbench, llm, FIXTURES, JOBS, OUTPUT, CONTRACT['ceiling_usd'])
    except Exception as error:
        # Do not raise: errored Kaggle tasks can discard paid raw evidence.
        stopped = repr(error)
    events, invalid_lines = parse_jsonl_best_effort(EVIDENCE.read_bytes() if EVIDENCE.exists() else b'')
    report, audit_error = None, None
    if invalid_lines:
        audit_error = 'malformed raw JSONL; inspect preserved evidence'
    else:
        try:
            report = auditor.audit(events, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids']))
        except Exception as error:
            audit_error = repr(error)
    raw = raw_event_summary(events, invalid_json_lines=len(invalid_lines))
    terminal = dict(schema='chronos.experiment-c-hosted-terminal.v1', task=TASK,
        contract_sha256=CONTRACT['contract_sha256'], status='complete' if report and report['complete'] and not stopped else 'stopped',
        stopped_early=stopped, audit_error=audit_error, audit=report, raw_accounting=raw)
    (OUTPUT / 'terminal.json').write_text(json.dumps(terminal, indent=2, sort_keys=True) + '\\n')
    print('EXPERIMENT_C_TERMINAL', json.dumps(terminal, sort_keys=True), flush=True)

experiment_c.run(kbench.llms[MODEL])
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("seal-selection")
    seal.add_argument("--model", required=True)
    seal.add_argument("--reasoning", required=True)
    seal.add_argument("--out", type=Path, required=True)
    stage = sub.add_parser("stage-shard")
    stage.add_argument("--selection", type=Path, required=True)
    stage.add_argument("--last-task", required=True)
    stage.add_argument("--last-run-id", type=int, required=True)
    stage.add_argument("--last-evidence", type=Path, required=True)
    stage.add_argument("--last-terminal", type=Path, required=True)
    stage.add_argument("--shard", type=int, required=True)
    stage.add_argument("--ceiling", type=float, required=True)
    stage.add_argument("--task", required=True)
    stage.add_argument("--folder", required=True)
    stage.add_argument("--out", type=Path, required=True)
    stage.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    if args.command == "seal-selection":
        result = seal_selection(args.model, args.reasoning)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(args.out, result["selection_manifest_sha256"])
        return
    selection = json.loads(args.selection.read_text())
    quota_evidence = args.last_evidence.read_bytes()
    quota_terminal = args.last_terminal.read_bytes()
    seed = args.resume_from.read_bytes() if args.resume_from else b""
    contract = plan_cell(selection=selection, shard_index=args.shard, ceiling_usd=args.ceiling,
                         last_task=args.last_task, last_run_id=args.last_run_id,
                         quota_evidence=quota_evidence, quota_terminal=quota_terminal, resume_seed=seed)
    source = build_source(contract=contract, selection=selection, task_name=args.task, output_folder=args.folder, resume_seed=seed)
    compile(source, str(args.out), "exec")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(source)
    contract_path = args.out.with_suffix(".contract.json")
    contract_path.write_text(json.dumps({**contract, "hosted_source_sha256": hashlib.sha256(source.encode()).hexdigest()}, indent=2, sort_keys=True) + "\n")
    quota_path = args.out.with_suffix(".quota.json")
    quota_path.write_text(json.dumps(contract["quota_attestation"], indent=2, sort_keys=True) + "\n")
    print(args.out, contract_path, quota_path, contract["contract_sha256"])


if __name__ == "__main__":
    main()
