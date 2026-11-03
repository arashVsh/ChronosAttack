"""Build isolated Experiment B pilot and study shard sources offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import audit_experiment_b as auditor
import experiment_b_protocol as protocol
from round2_hosted import manifest_digest, parse_jsonl_bytes, select_shard, validate_resume_ledger
import verify_experiment_b_freeze as freeze


HERE = Path(__file__).resolve().parent
SOURCE_FILES = (
    "completion_protocol.py",
    "four_observation_protocol.py",
    "experiment_b_protocol.py",
    "audit_experiment_b.py",
    "round2_hosted.py",
    "reasoning_preflight_v1.py",
    "experiment_b_manifest_v1.json",
)
SHARD_COUNT = 30
PILOT_CEILING_USD = 0.25
TASK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
FOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sources() -> tuple[dict[str, str], dict[str, str]]:
    freeze.verify()
    sources = {name: (HERE / name).read_text() for name in SOURCE_FILES}
    hashes = {name: _sha256(content.encode()) for name, content in sources.items()}
    manifest = json.loads(sources["experiment_b_manifest_v1.json"])
    for name in SOURCE_FILES[:-1]:
        expected = manifest["source_sha256"].get(f"kaggle/{name}")
        if expected is not None and expected != hashes[name]:
            raise ValueError(f"Frozen Experiment B source changed: {name}")
    return sources, hashes


def _pilot_receipt(value: dict | None, model: str) -> dict | None:
    if value is None:
        return None
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    expected = _sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    cell = protocol.cell(model, "pilot")
    if (
        value.get("receipt_sha256") != expected
        or value.get("schema") != "chronos.experiment-b-pilot-receipt.v1"
        or value.get("model") != model
        or value.get("reasoning") != cell["reasoning"]
        or value.get("role") != cell["role"]
        or value.get("study_id") != cell["study_id"]
        or value.get("identity") != protocol.identity(model, "pilot")
        or value.get("passed") is not True
        or value.get("outcomes_examined_for_authorization") is not False
        or value.get("pilot_excluded_from_study") is not True
        or value.get("completed_jobs") != 2
        or value.get("observed_invocations") != 10
        or value.get("failed_calls") != 0
        or value.get("unknown_cost_calls") != 0
    ):
        raise ValueError("Passed, identity-matched Experiment B pilot receipt required")
    return value


def study_ceiling_from_pilot(receipt: dict) -> float:
    """Two times pilot cost per call for a 30-call shard, plus $0.10 reserve."""
    cost = receipt["known_cost_usd"]
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        raise ValueError("Pilot cost telemetry is invalid")
    return math.ceil((0.10 + 6 * cost) * 100) / 100


def plan_cell(
    *,
    model: str,
    phase: str,
    shard_index: int | None = None,
    resume_seed: bytes = b"",
) -> dict:
    frozen = freeze.verify()
    chosen = protocol.cell(model, phase)
    if phase == "pilot":
        if shard_index is not None or resume_seed:
            raise ValueError("Excluded pilot cannot shard or resume")
        jobs = protocol.jobs_for(model, "pilot")
    else:
        if shard_index is None or not 0 <= shard_index < SHARD_COUNT:
            raise ValueError("Study requires one of 30 deterministic shards")
        jobs = select_shard(protocol.jobs_for(model), shard_index=shard_index, shard_count=SHARD_COUNT)
    if resume_seed and not resume_seed.endswith(b"\n"):
        raise ValueError("Resume ledger must be newline terminated")
    events = parse_jsonl_bytes(resume_seed, label="B resume ledger")
    identity = protocol.identity(model, phase)
    seed_audit = validate_resume_ledger(
        events,
        model=model,
        identity=identity,
        expected_jobs={job["id"]: job for job in jobs},
        structural_audit=lambda data: auditor.audit(data, model, phase, require_complete=False),
    )
    expected = (2, 10) if phase == "pilot" else (6, 30)
    if (len(jobs), sum(job["calls"] for job in jobs)) != expected:
        raise ValueError("Experiment B shard topology changed")
    return {
        "schema": "chronos.experiment-b-hosted-cell.v1",
        **chosen,
        "shard_index": shard_index,
        "shard_count": None if phase == "pilot" else SHARD_COUNT,
        "jobs": jobs,
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": manifest_digest(jobs),
        "identity": identity,
        "fixture_manifest_sha256": frozen["manifest_sha256"],
        "resume_ledger": seed_audit,
    }


RUNTIME = '''# Generated offline by build_experiment_b_hosted_v1.py.
import hashlib
import json
import sys
from pathlib import Path
import kaggle_benchmarks as kbench

__ASSIGNMENTS__

for name, raw in SOURCES.items():
    if hashlib.sha256(raw.encode()).hexdigest() != SOURCE_SHA256[name]:
        raise ValueError('Embedded B source hash mismatch: ' + name)
fixture_manifest = json.loads(SOURCES['experiment_b_manifest_v1.json'])
body = {key: value for key, value in fixture_manifest.items() if key != 'manifest_sha256'}
if (hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        != CONTRACT['fixture_manifest_sha256']):
    raise ValueError('Embedded B fixture manifest changed')
if PHASE == 'study':
    receipt = PILOT_RECEIPT
    receipt_body = {key: value for key, value in receipt.items() if key != 'receipt_sha256'}
    receipt_hash = hashlib.sha256(json.dumps(
        receipt_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (receipt_hash != CONTRACT['pilot_receipt_sha256']
            or receipt_hash != receipt['receipt_sha256']
            or receipt['passed'] is not True
            or receipt['outcomes_examined_for_authorization'] is not False
            or receipt['pilot_excluded_from_study'] is not True
            or receipt['model'] != MODEL
            or receipt['reasoning'] != REASONING
            or receipt['role'] != ROLE):
        raise ValueError('B study lacks its own passed excluded pilot')

source_root = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
source_root.mkdir(parents=True, exist_ok=False)
for name, raw in SOURCES.items():
    (source_root / name).write_text(raw)
sys.path.insert(0, str(source_root))

import audit_experiment_b as auditor
import experiment_b_protocol as cell
import reasoning_preflight_v1 as pilot_gate
import round2_hosted as hosted

jobs = (cell.jobs_for(MODEL, 'pilot') if PHASE == 'pilot'
        else hosted.select_shard(cell.jobs_for(MODEL, 'study'),
                                 shard_index=CONTRACT['shard_index'],
                                 shard_count=CONTRACT['shard_count']))
fixtures = cell.fixtures()
identity = cell.identity(MODEL, PHASE)
structural_audit = lambda events: auditor.audit(events, MODEL, PHASE, require_complete=False)
if (jobs != EXPECTED_JOBS
        or hosted.manifest_digest(jobs) != CONTRACT['jobs_sha256']
        or identity != CONTRACT['identity']
        or cell.call_settings(MODEL) != CALL_SETTINGS):
    raise ValueError('Runtime B cell differs from intended contract')
seed_events = hosted.parse_jsonl_bytes(RESUME_LEDGER, label='B resume ledger')
seed_audit = hosted.validate_resume_ledger(
    seed_events, model=MODEL, identity=identity,
    expected_jobs={job['id']: job for job in jobs},
    structural_audit=structural_audit)
if (seed_audit != CONTRACT['resume_ledger']
        or (hashlib.sha256(RESUME_LEDGER).hexdigest() if RESUME_LEDGER else None)
        != CONTRACT['parent_ledger_sha256']):
    raise ValueError('Runtime B resume ledger changed')

output = Path('/kaggle/working') / OUTPUT_FOLDER
output.mkdir(parents=True, exist_ok=False)
manifest = dict(CONTRACT, jobs=jobs)
(output / 'intended_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))
evidence_path = output / (MODEL.replace('/', '_') + '.jsonl')
if RESUME_LEDGER:
    evidence_path.write_bytes(RESUME_LEDGER)

@kbench.task(name=__TASK_NAME_LITERAL__)
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError('Unexpected selected model')
    llm.client = llm.client.with_options(max_retries=0)
    error = None
    with cell.cell_runtime(MODEL, PHASE):
        try:
            if PHASE == 'pilot':
                pilot_gate.run_once(cell.engine, cell.tree.execute_job,
                                    kbench, llm, fixtures, jobs, output, CEILING_USD)
            else:
                cell.engine.run_jobs(kbench, llm, fixtures, jobs, output, CEILING_USD)
        except Exception as exc:
            response = getattr(exc, 'response', None)
            error = {
                'type': type(exc).__name__,
                'status_code': getattr(exc, 'status_code', None)
                               or getattr(response, 'status_code', None),
                'message': str(exc)[:2000],
            }

    raw = evidence_path.read_bytes() if evidence_path.exists() else b''
    prefix_ok = raw.startswith(RESUME_LEDGER)
    events, parse_failures = hosted.parse_jsonl_best_effort(raw)
    raw_accounting = hosted.raw_event_summary(events, invalid_json_lines=len(parse_failures))
    terminal = {
        'schema': 'chronos.experiment-b-terminal.v1',
        'model': MODEL,
        'reasoning': REASONING,
        'role': ROLE,
        'phase': PHASE,
        'study_id': STUDY_ID,
        'identity': identity,
        'fixture_manifest_sha256': CONTRACT['fixture_manifest_sha256'],
        'jobs_sha256': CONTRACT['jobs_sha256'],
        'job_ids': [job['id'] for job in jobs],
        'planned_calls': CONTRACT['planned_calls'],
        'call_settings': {**CALL_SETTINGS, 'sdk_max_retries': 0},
        'source_sha256': SOURCE_SHA256,
        'evidence_sha256': hashlib.sha256(raw).hexdigest(),
        'parent_ledger_sha256': CONTRACT['parent_ledger_sha256'],
        'pilot_receipt_sha256': CONTRACT['pilot_receipt_sha256'],
        'error': error,
    }
    (output / 'terminal.json').write_text(json.dumps(terminal, indent=2, sort_keys=True))
    try:
        if not prefix_ok or parse_failures:
            raise ValueError('Raw B ledger is malformed or lost its parent prefix')
        ledger = hosted.validate_resume_ledger(
            events, model=MODEL, identity=identity,
            expected_jobs={job['id']: job for job in jobs},
            structural_audit=structural_audit)
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {job['id'] for job in jobs})
        passed = bool(
            subset['complete'] and error is None and raw_accounting['accounting_complete']
            and (PHASE != 'pilot' or auditor.audit(events, MODEL, 'pilot')['pilot_passed'])
        )
        checked = {
            'schema': 'chronos.experiment-b-hosted-audit.v1',
            'passed': passed,
            'contract': CONTRACT,
            'ledger_audit': ledger,
            'structural_audit': structural,
            'subset': subset,
            'raw_accounting': raw_accounting,
            'parent_prefix_preserved': prefix_ok,
            'evidence_sha256': terminal['evidence_sha256'],
            'terminal_error': error,
        }
    except Exception as exc:
        checked = {
            'schema': 'chronos.experiment-b-hosted-audit.v1',
            'passed': False,
            'contract': CONTRACT,
            'audit_failed': repr(exc),
            'raw_accounting': raw_accounting,
            'parent_prefix_preserved': prefix_ok,
            'evidence_sha256': terminal['evidence_sha256'],
            'terminal_error': error,
            'parse_failures': parse_failures,
        }
    (output / 'audit.json').write_text(json.dumps(checked, indent=2, sort_keys=True))
    print('EXPERIMENT_B_AUDIT', json.dumps(checked, sort_keys=True), flush=True)

hosted_cell.run(kbench.llms[MODEL])
'''


def build_source(
    *,
    model: str,
    phase: str,
    task_name: str,
    output_folder: str,
    ceiling_usd: float,
    shard_index: int | None = None,
    resume_seed: bytes = b"",
    pilot_receipt: dict | None = None,
    pilot_evidence: bytes | None = None,
    pilot_terminal: bytes | None = None,
    pilot_intended: bytes | None = None,
) -> str:
    if not TASK_PATTERN.fullmatch(task_name) or not FOLDER_PATTERN.fullmatch(output_folder):
        raise ValueError("Invalid hosted B task or output folder")
    plan = plan_cell(model=model, phase=phase, shard_index=shard_index, resume_seed=resume_seed)
    receipt = _pilot_receipt(pilot_receipt, model)
    if phase == "pilot":
        if receipt is not None or ceiling_usd != PILOT_CEILING_USD:
            raise ValueError("B pilot must use its frozen $0.25 ceiling and no receipt")
    else:
        if receipt is None:
            raise ValueError("B study requires a passed excluded pilot receipt")
        if any(value is None for value in (pilot_evidence, pilot_terminal, pilot_intended)):
            raise ValueError("B study requires raw pilot artifacts for revalidation")
        import issue_experiment_b_pilot_receipt_v1 as issuer

        issuer.validate_receipt(
            receipt,
            evidence=pilot_evidence,
            terminal=pilot_terminal,
            intended=pilot_intended,
        )
        if ceiling_usd != study_ceiling_from_pilot(receipt):
            raise ValueError("B study ceiling must derive from its pilot telemetry")
    sources, hashes = _sources()
    effective = round(plan["resume_ledger"]["known_cost_usd"] + ceiling_usd, 9)
    if not 0 < effective <= 10:
        raise ValueError("Effective ceiling exceeds daily authorization")
    public = {key: value for key, value in plan.items() if key != "jobs"}
    public.update({
        "source_sha256": hashes,
        "incremental_ceiling_usd": ceiling_usd,
        "effective_ceiling_usd": effective,
        "parent_ledger_sha256": _sha256(resume_seed) if resume_seed else None,
        "pilot_receipt_sha256": receipt["receipt_sha256"] if receipt else None,
        "sdk_max_retries": 0,
    })
    assignments = {
        "SOURCES": sources,
        "SOURCE_SHA256": hashes,
        "CONTRACT": public,
        "EXPECTED_JOBS": plan["jobs"],
        "RESUME_LEDGER": resume_seed,
        "PILOT_RECEIPT": receipt,
        "MODEL": model,
        "REASONING": plan["reasoning"],
        "ROLE": plan["role"],
        "PHASE": phase,
        "STUDY_ID": plan["study_id"],
        "TASK_NAME": task_name,
        "OUTPUT_FOLDER": output_folder,
        "CEILING_USD": effective,
        "CALL_SETTINGS": protocol.call_settings(model),
    }
    header = "\n".join(f"{name} = {value!r}" for name, value in assignments.items())
    return (RUNTIME.replace("__ASSIGNMENTS__", header)
            .replace("__TASK_NAME_LITERAL__", repr(task_name)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--phase", choices=("pilot", "study"), required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--ceiling", type=float, required=True)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--pilot-receipt", type=Path)
    parser.add_argument("--pilot-evidence", type=Path)
    parser.add_argument("--pilot-terminal", type=Path)
    parser.add_argument("--pilot-intended", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = build_source(
        model=args.model,
        phase=args.phase,
        task_name=args.task,
        output_folder=args.output_folder,
        ceiling_usd=args.ceiling,
        shard_index=args.shard_index,
        resume_seed=args.resume_from.read_bytes() if args.resume_from else b"",
        pilot_receipt=json.loads(args.pilot_receipt.read_text()) if args.pilot_receipt else None,
        pilot_evidence=args.pilot_evidence.read_bytes() if args.pilot_evidence else None,
        pilot_terminal=args.pilot_terminal.read_bytes() if args.pilot_terminal else None,
        pilot_intended=args.pilot_intended.read_bytes() if args.pilot_intended else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source)
    print(f"WROTE {args.output}")


if __name__ == "__main__":
    main()
